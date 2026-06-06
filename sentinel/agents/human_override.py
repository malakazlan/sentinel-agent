"""HumanOverrideGate — Phase 8 / ADR-025.

A synchronous gate (not an LLM agent) that pauses the orchestrator
before designated destructive actions. The UI receives a
``HumanGateAwaitingEvent``; the operator clicks Approve / Reject; the
orchestrator releases the gate via ``POST /incidents/{id}/gate/{gate_id}``.

For V1 the destructive-action list is explicit + small:

1. Regulator notification draft (always gated, never bypassable).
2. Slack post to prod channel (gated when SENTINEL_SLACK_GATE_PROD=1).
3. action_item assignment to a real human (gated when
   SENTINEL_ACTION_ITEM_GATE=1).

The gate state lives in a JSONL sidecar so Cloud Run instances that
scale down while waiting on a gate can rehydrate.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)


GATED_REGULATOR_NOTIFICATION = "regulator_notification"
GATED_SLACK_PROD_POST = "slack_prod_post"
GATED_ACTION_ITEM_ASSIGNMENT = "action_item_assignment"


# Default timeout for a pending gate. 30 min matches Cloud Run's
# default request timeout policy after which the gate auto-rejects.
DEFAULT_GATE_TIMEOUT_S: int = 30 * 60


@dataclass(frozen=True)
class PendingGate:
    """A gate awaiting human approval."""

    gate_id: str
    incident_id: str
    action_type: str
    action_summary: str
    requested_at_iso: str
    timeout_at_iso: str


@dataclass(frozen=True)
class ResolvedGate:
    gate_id: str
    incident_id: str
    decision: str  # "approved" | "rejected" | "timeout"
    resolved_at_iso: str
    operator_note: str = ""


_PENDING_STORE = Path("data/memory/pending_gates.jsonl")
_RESOLVED_STORE = Path("data/memory/resolved_gates.jsonl")

# Phase 8 — in-process awaiters. The orchestrator creates an
# ``asyncio.Event`` per pending gate; the API endpoint resolving the
# gate sets the event so the orchestrator unblocks within milliseconds
# (no need to poll the JSONL file). Cloud Run single-instance mode (set
# via ``--max-instances=1``) keeps requester + resolver on the same
# event loop.
import asyncio

_resolution_events: dict[str, asyncio.Event] = {}
_resolution_decisions: dict[str, str] = {}


def is_action_gated(action_type: str) -> bool:
    """Whether ``action_type`` requires an approval gate per env config.

    Regulator notifications are ALWAYS gated; the other two are env-toggleable.
    """
    if action_type == GATED_REGULATOR_NOTIFICATION:
        return True
    if action_type == GATED_SLACK_PROD_POST:
        return os.environ.get("SENTINEL_SLACK_GATE_PROD", "1") == "1"
    if action_type == GATED_ACTION_ITEM_ASSIGNMENT:
        return os.environ.get("SENTINEL_ACTION_ITEM_GATE", "0") == "1"
    return False


def request_gate(
    incident_id: str,
    action_type: str,
    action_summary: str,
    *,
    timeout_seconds: int = DEFAULT_GATE_TIMEOUT_S,
) -> PendingGate:
    """Persist a new pending gate, returning the record.

    The orchestrator emits ``HumanGateAwaitingEvent`` on the SSE wire
    with this gate's id; the UI banner reads the same gate id when the
    operator clicks Approve / Reject.
    """
    gate = PendingGate(
        gate_id=uuid.uuid4().hex[:12],
        incident_id=incident_id,
        action_type=action_type,
        action_summary=action_summary,
        requested_at_iso=_iso_now(),
        timeout_at_iso=_iso_at(time.time() + timeout_seconds),
    )
    _PENDING_STORE.parent.mkdir(parents=True, exist_ok=True)
    with _PENDING_STORE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps({
            "gate_id": gate.gate_id,
            "incident_id": gate.incident_id,
            "action_type": gate.action_type,
            "action_summary": gate.action_summary,
            "requested_at_iso": gate.requested_at_iso,
            "timeout_at_iso": gate.timeout_at_iso,
        }) + "\n")
    return gate


def resolve_gate(
    gate_id: str,
    decision: str,
    *,
    operator_note: str = "",
) -> ResolvedGate:
    assert decision in ("approved", "rejected", "timeout"), decision
    resolved = ResolvedGate(
        gate_id=gate_id,
        incident_id=_incident_id_for_gate(gate_id) or "",
        decision=decision,
        resolved_at_iso=_iso_now(),
        operator_note=operator_note,
    )
    _RESOLVED_STORE.parent.mkdir(parents=True, exist_ok=True)
    with _RESOLVED_STORE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps({
            "gate_id": resolved.gate_id,
            "incident_id": resolved.incident_id,
            "decision": resolved.decision,
            "resolved_at_iso": resolved.resolved_at_iso,
            "operator_note": resolved.operator_note,
        }) + "\n")
    # Notify any awaiting orchestrator coroutine. Safe to call even
    # when no awaiter is registered (the event won't exist).
    _resolution_decisions[gate_id] = decision
    event = _resolution_events.get(gate_id)
    if event is not None:
        event.set()
    return resolved


async def await_resolution(gate_id: str, *, timeout_s: float) -> str:
    """Block until ``gate_id`` is resolved or ``timeout_s`` elapses.

    Returns the decision string: ``approved``, ``rejected``, or
    ``timeout`` on the timeout fallback. The orchestrator awaits this
    after emitting ``HumanGateAwaitingEvent`` on the SSE wire; the API
    endpoints call ``resolve_gate`` which sets the in-process event.
    """
    if gate_id in _resolution_decisions:
        return _resolution_decisions[gate_id]
    event = _resolution_events.setdefault(gate_id, asyncio.Event())
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        resolve_gate(gate_id, "timeout", operator_note="auto-rejected on timeout")
        return "timeout"
    finally:
        _resolution_events.pop(gate_id, None)
    return _resolution_decisions.get(gate_id, "timeout")


def list_pending() -> list[PendingGate]:
    if not _PENDING_STORE.exists():
        return []
    pending: list[PendingGate] = []
    resolved_ids = _all_resolved_ids()
    with _PENDING_STORE.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d["gate_id"] in resolved_ids:
                continue
            pending.append(PendingGate(**d))
    return pending


def _all_resolved_ids() -> set[str]:
    if not _RESOLVED_STORE.exists():
        return set()
    ids: set[str] = set()
    with _RESOLVED_STORE.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["gate_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


def _incident_id_for_gate(gate_id: str) -> Optional[str]:
    if not _PENDING_STORE.exists():
        return None
    with _PENDING_STORE.open("r", encoding="utf-8") as fp:
        for line in fp:
            try:
                d = json.loads(line)
                if d["gate_id"] == gate_id:
                    return d["incident_id"]
            except json.JSONDecodeError:
                continue
    return None


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_at(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
