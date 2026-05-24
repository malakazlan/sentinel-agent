"""Sentinel self-introspection — Phase 3 step 2.

Queries Phoenix MCP for recent Sentinel activity and produces a typed
``PriorContextBriefing`` of plan-shaping directives the Coordinator must
honor on the current turn. This is the **differentiator** — see ADR-009 for
the design (directives, not memory recap) and the narrative discipline
amendment (demo headline = first_route, not skip_routes).

Public surface:

- ``synthesize_prior_context()`` — async; queries MCP, returns a
  ``PriorContextBriefing``.
- ``before_coordinator_callback(callback_context)`` — ADK
  ``before_agent_callback`` hook; runs once per invocation, stores the
  briefing object (not a string) in callback-context state.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from statistics import median
from typing import Any, Iterator, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.mcp_tool import McpToolset

from sentinel.memory.briefing import PriorContextBriefing
from sentinel.observability.phoenix_mcp import make_phoenix_mcp_toolset

_logger = logging.getLogger(__name__)

# Demo / test hook: when set (via ``briefing_override`` context manager),
# ``synthesize_prior_context`` short-circuits and returns this object instead
# of querying Phoenix MCP. Production code never touches this; only the
# Streamlit cold-vs-warm demo and unit tests use it.
_briefing_override: Optional[PriorContextBriefing] = None


@contextmanager
def briefing_override(briefing: PriorContextBriefing) -> Iterator[None]:
    """Context manager that pins ``synthesize_prior_context``'s return value.

    Used by the cold-vs-warm demo to control the briefing per-run for camera
    reproducibility (ADR-009). The override is module-scoped; for parallel
    invocations this would race, but the demo and tests are sequential.
    """
    global _briefing_override
    _briefing_override = briefing
    try:
        yield
    finally:
        _briefing_override = None

# Directive extraction thresholds. These are tuned for the demo path and
# the Phase 2 sub-agent surface; revisit when Phase 4 adds more routes.
_INTROSPECTION_LIMIT = 100
_LOOKBACK_HOURS_DEFAULT = 24
_PROJECT = "sentinel"

# In a financial-services context, recent errors are always signal — not noise.
# We require a meaningful raw count (>=3) so a single transient blip doesn't
# steer routing, but we do NOT gate on share: ANY production system with a
# handful of recent failures deserves depth-first investigation on the next
# inbound request, regardless of total volume.
_ERROR_CLUSTER_MIN_COUNT = 3
_LOW_VOLUME_TOTAL = 3               # below this, widen the default window
_LOW_VOLUME_HOURS_BACK = 24

# Module-level toolset — stdio MCP subprocess stays warm across callbacks
# after the first call. Lazy so import time stays cheap.
_mcp_toolset: Optional[McpToolset] = None


def _get_mcp() -> McpToolset:
    global _mcp_toolset
    if _mcp_toolset is None:
        _mcp_toolset = make_phoenix_mcp_toolset()
    return _mcp_toolset


async def synthesize_prior_context() -> PriorContextBriefing:
    """Return a typed directive briefing for the Coordinator's next turn.

    Queries Phoenix MCP (``list-traces`` + ``get-span-annotations``), applies
    the directive-extraction rules below, and returns a
    ``PriorContextBriefing``. Errors are swallowed and rendered as a
    cold-start briefing so the Coordinator never blocks on MCP failure.

    Extraction rules (intentionally narrow — see ADR-009 narrative note):

    - ``cold_start = True`` iff zero root spans extractable.
    - ``first_route = "trace_analyzer"`` iff recent ERROR cluster
      (``n_error >= 3`` and ``n_error / n_total >= 0.30``). This is the
      demo's headline directive.
    - ``must_eval_after = True`` iff any recent hallucination annotation.
    - ``default_hours_back = 24`` iff recent volume < 3 traces; else 1.
    - ``skip_routes`` left empty by default — capability preserved for true
      redundancy but not the demo's headline mechanism.

    Honors ``briefing_override`` for the demo and unit-test paths.
    """
    if _briefing_override is not None:
        return _briefing_override
    try:
        mcp = _get_mcp()
        tools = await mcp.get_tools()
        tool_by_name = {t.name: t for t in tools}

        traces_result = await tool_by_name["list-traces"].run_async(
            args={
                "project_identifier": _PROJECT,
                "limit": _INTROSPECTION_LIMIT,
            },
            tool_context=None,
        )
        root_spans = _extract_root_spans(traces_result)
        if not root_spans:
            return PriorContextBriefing(
                cold_start=True,
                stats={"n_total": 0, "lookback_hours": _LOOKBACK_HOURS_DEFAULT},
            )

        span_ids = [
            s["context"]["span_id"]
            for s in root_spans
            if s.get("context", {}).get("span_id")
        ]
        annotations: list[dict] = []
        if span_ids:
            anns_result = await tool_by_name["get-span-annotations"].run_async(
                args={
                    "span_ids": span_ids,
                    "project_identifier": _PROJECT,
                },
                tool_context=None,
            )
            annotations = _extract_annotations(anns_result)

        return _derive_briefing(root_spans, annotations)
    except Exception as exc:
        _logger.warning("self-introspection failed: %s", exc, exc_info=True)
        return PriorContextBriefing(
            cold_start=True,
            stats={"introspection_error": 1},
            evidence={"cold_start": f"Phoenix MCP query failed: {type(exc).__name__}"},
        )


async def before_coordinator_callback(
    callback_context: CallbackContext,
) -> None:
    """ADK ``before_agent_callback`` hook for the Coordinator.

    Runs once per invocation before the LLM sees the user message. Stores
    the typed briefing in callback state under ``"prior_context_briefing"``
    so the Coordinator's instruction provider can render the directive
    block. Returns ``None`` so the agent runs normally (no short-circuit).
    """
    briefing = await synthesize_prior_context()
    callback_context.state["prior_context_briefing"] = briefing
    return None


# ── directive extraction ─────────────────────────────────────────────────


def _derive_briefing(
    root_spans: list[dict], annotations: list[dict]
) -> PriorContextBriefing:
    """Compute aggregations and emit directives per the rules above."""
    n_total = len(root_spans)
    n_error = sum(
        1 for s in root_spans if (s.get("status_code") or "OK") not in ("OK", "")
    )

    halluc_anns = [a for a in annotations if (a.get("name") or "") == "hallucination"]
    n_hallucinated = sum(
        1
        for a in halluc_anns
        if (a.get("result") or {}).get("label") == "hallucinated"
    )
    n_faithful = sum(
        1
        for a in halluc_anns
        if (a.get("result") or {}).get("label") == "faithful"
    )

    latencies = []
    for s in root_spans:
        try:
            start = datetime.fromisoformat(s["start_time"])
            end = datetime.fromisoformat(s["end_time"])
            latencies.append((end - start).total_seconds() * 1000.0)
        except (KeyError, TypeError, ValueError):
            continue
    median_ms = int(median(latencies)) if latencies else 0

    stats: dict[str, int] = {
        "n_total": n_total,
        "n_error": n_error,
        "n_hallucinated": n_hallucinated,
        "n_faithful": n_faithful,
        "median_latency_ms": median_ms,
        "lookback_hours": _LOOKBACK_HOURS_DEFAULT,
    }
    evidence: dict[str, str] = {}

    first_route: Optional[str] = None
    error_share = n_error / n_total if n_total > 0 else 0.0
    if n_error >= _ERROR_CLUSTER_MIN_COUNT:
        first_route = "trace_analyzer"
        evidence["first_route"] = (
            f"{n_error} ERROR traces in last {n_total} root invocations "
            f"({int(error_share * 100)}% of recent history); quick-tool "
            f"summary would mask the failure mode — go depth-first."
        )

    must_eval_after = n_hallucinated >= 1
    if must_eval_after:
        evidence["must_eval_after"] = (
            f"{n_hallucinated} hallucinated annotation(s) in the inspected "
            f"window across {len(halluc_anns)} annotated traces; double "
            f"down on safety on this turn."
        )

    default_hours_back = (
        _LOW_VOLUME_HOURS_BACK if n_total < _LOW_VOLUME_TOTAL else 1
    )
    if default_hours_back != 1:
        evidence["default_hours_back"] = (
            f"Only {n_total} traces in the inspection window; widen the "
            f"default tool window to {default_hours_back}h to surface useful data."
        )

    return PriorContextBriefing(
        cold_start=False,
        first_route=first_route,  # type: ignore[arg-type]  # Literal narrowing at runtime
        skip_routes=[],
        must_eval_after=must_eval_after,
        default_hours_back=default_hours_back,
        evidence=evidence,
        stats=stats,
    )


# ── MCP envelope helpers (Phoenix MCP wraps tool results as text-content) ─


def _extract_root_spans(traces_result: Any) -> list[dict]:
    """Pull root spans (parent_id is None) out of an MCP ``list-traces`` envelope."""
    content = _unwrap_mcp_content(traces_result)
    if content is None:
        return []
    try:
        traces = json.loads(content) if isinstance(content, str) else content
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(traces, list):
        return []

    root_spans: list[dict] = []
    for trace in traces:
        for span in trace.get("spans", []) if isinstance(trace, dict) else []:
            if span.get("parent_id") in (None, ""):
                root_spans.append(span)
                break
    return root_spans


def _extract_annotations(annotations_result: Any) -> list[dict]:
    """Pull a flat list of annotations out of an MCP ``get-span-annotations`` envelope."""
    content = _unwrap_mcp_content(annotations_result)
    if content is None:
        return []
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [a for a in parsed if isinstance(a, dict)]
    if isinstance(parsed, dict):
        for key in ("data", "annotations", "results"):
            if key in parsed and isinstance(parsed[key], list):
                return [a for a in parsed[key] if isinstance(a, dict)]
    return []


def _unwrap_mcp_content(result: Any) -> Optional[str]:
    """Extract the inner text payload from an MCP tool envelope.

    MCP tool responses look like ``{"content": [{"type": "text", "text":
    "..."}], "isError": False}``. Returns the concatenated text or ``None``
    on error / unexpected shape.
    """
    if not isinstance(result, dict):
        return None
    if result.get("isError"):
        return None
    parts = result.get("content", [])
    if not isinstance(parts, list):
        return None
    text_pieces = [
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    ]
    if not text_pieces:
        return None
    return "".join(text_pieces)
