"""Plan-determinism integration tests (ADR-009).

These exercise the full Coordinator with a real Vertex Gemini call but with
``synthesize_prior_context`` patched to return a controlled briefing. They
assert that each directive shape produces an observable, reproducible
change in the executed plan — which is the supervisor's invariant for the
demo's 4min→1min camera take.

Skipped automatically when ``GOOGLE_CLOUD_PROJECT`` is not set (CI without
Vertex creds), or when ``RUN_INTEGRATION_TESTS`` is not explicitly enabled.
Each test spends ~$0.0001 of Vertex flash-lite tokens.
"""

from __future__ import annotations

import os
from typing import Iterable

import pytest

from sentinel.memory.briefing import PriorContextBriefing

# Module-wide skip gate. ``RUN_INTEGRATION_TESTS=1`` is opt-in so a stray
# `pytest` in CI never burns Vertex tokens without intent.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason=(
            "integration tests are opt-in: set GOOGLE_CLOUD_PROJECT and "
            "RUN_INTEGRATION_TESTS=1 to enable"
        ),
    ),
]


def _stub_synthesize(monkeypatch: pytest.MonkeyPatch, briefing: PriorContextBriefing) -> None:
    """Replace ``synthesize_prior_context`` with a fixed-briefing stub.

    Patches the module attribute the callback closure resolves at call time;
    the patched value flows into ``before_coordinator_callback``'s call.
    """

    async def _fake() -> PriorContextBriefing:
        return briefing

    monkeypatch.setattr(
        "sentinel.memory.self_introspection.synthesize_prior_context",
        _fake,
    )


def _ensure_tracing_and_env() -> None:
    """Load .env and initialize tracing exactly once per test."""
    from dotenv import load_dotenv

    load_dotenv(override=True)
    from sentinel.observability.instrumentation import setup_tracing

    setup_tracing()


def _transfers(records: Iterable[dict]) -> list[dict]:
    return [
        r
        for r in records
        if r.get("kind") == "tool_call" and r.get("tool") == "transfer_to_agent"
    ]


def _direct_tool_calls(records: Iterable[dict], tool_name: str) -> list[dict]:
    return [
        r
        for r in records
        if r.get("kind") == "tool_call"
        and r.get("tool") == tool_name
        and r.get("author") == "coordinator"
    ]


# ── cold start: full default pipeline (no overrides) ───────────────────────


async def test_cold_start_uses_default_direct_tool_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold-start briefing → "what's going on?" routes to direct tool, no transfer."""
    _stub_synthesize(
        monkeypatch,
        PriorContextBriefing(cold_start=True, stats={"n_total": 0, "lookback_hours": 24}),
    )
    _ensure_tracing_and_env()
    from sentinel.coordinator import stream_coordinator

    records = [r async for r in stream_coordinator("what's going on?")]

    direct = _direct_tool_calls(records, "get_recent_traces")
    transfers = _transfers(records)
    assert direct, f"cold start: expected get_recent_traces call; got tool_calls={records}"
    assert not transfers, f"cold start: expected no transfer; got {transfers}"


# ── first_route directive: forces transfer to the named sub-agent ─────────


async def test_first_route_forces_trace_analyzer_transfer(monkeypatch: pytest.MonkeyPatch) -> None:
    """first_route='trace_analyzer' on a short status question → Coordinator transfers."""
    _stub_synthesize(
        monkeypatch,
        PriorContextBriefing(
            first_route="trace_analyzer",
            evidence={
                "first_route": "5 of last 8 root spans were ERROR; depth-first analysis required."
            },
            stats={"n_total": 8, "n_error": 5},
        ),
    )
    _ensure_tracing_and_env()
    from sentinel.coordinator import stream_coordinator

    records = [r async for r in stream_coordinator("what's going on?")]

    transfers = _transfers(records)
    assert transfers, f"expected a transfer driven by first_route; got tool_calls={records}"
    first_transfer_target = (transfers[0].get("args") or {}).get("agent_name")
    assert first_transfer_target == "trace_analyzer", (
        f"first transfer must target trace_analyzer per directive; "
        f"got {first_transfer_target!r}"
    )


# ── skip_routes directive: forbids transfer even when explicitly asked ────


async def test_skip_routes_blocks_named_subagent(monkeypatch: pytest.MonkeyPatch) -> None:
    """eval_runner in skip_routes → eval_runner never actually executes.

    The LLM may still attempt the transfer; the ``enforce_skip_routes``
    callback intercepts and returns a "blocked" tool result. The invariant
    is that the sub-agent never runs — verified by absence of
    ``@eval_runner`` records in the event stream.
    """
    _stub_synthesize(
        monkeypatch,
        PriorContextBriefing(
            skip_routes=["eval_runner"],
            evidence={"skip_routes": "Last 5 evaluated traces all faithful; skipping redundant eval."},
        ),
    )
    _ensure_tracing_and_env()
    from sentinel.coordinator import stream_coordinator

    records = [r async for r in stream_coordinator("run a hallucination check please")]

    eval_runner_records = [r for r in records if r.get("author") == "eval_runner"]
    assert not eval_runner_records, (
        f"skip_routes=['eval_runner'] must prevent eval_runner from running; "
        f"got records authored by eval_runner: {eval_runner_records}"
    )
