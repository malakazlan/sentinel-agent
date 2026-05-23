"""Phoenix trace-fetching tool — Coordinator's first observability tool (Phase 1).

This module exposes ``get_recent_traces``, the function the Coordinator calls
when the user asks "what's been happening?". It hits Phoenix's REST API via
the official ``phoenix.client.Client`` and returns a structured text summary
the LLM can reason about.

Phase 3 will replace direct REST with the Phoenix MCP server (the
self-improvement-loop differentiator); for now we use the simpler direct path.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from phoenix.client import Client

_DEFAULT_PROJECT = "sentinel"
_MAX_LIMIT = 100


def get_recent_traces(hours_back: int = 1, limit: int = 20) -> str:
    """Return a text summary of the most recent root-level traces in Phoenix.

    Use this when the user asks about recent activity, incidents, the last
    deploy's behavior, or anything that requires looking at production
    observability data. Only returns *root* spans (full top-level
    invocations); nested LLM and tool spans are summarized by their parent.

    Args:
        hours_back: How far back to look, in hours. Default 1. Use larger
            values (e.g. 24) for daily context, smaller values for an
            incident-window.
        limit: Maximum number of root traces to return. Default 20. Hard
            capped at 100 to keep responses bounded.

    Returns:
        A Markdown-formatted summary the LLM can read aloud or reason over.
        Either a numbered list of traces (name, span kind, duration, status,
        start time) or a clear "no traces found" message.
    """
    safe_limit = max(1, min(int(limit), _MAX_LIMIT))
    project = os.environ.get("PHOENIX_PROJECT_NAME", _DEFAULT_PROJECT)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=max(1, int(hours_back)))

    try:
        spans = Client().spans.get_spans(
            project_identifier=project,
            start_time=start_time,
            end_time=end_time,
            limit=safe_limit * 4,
        )
    except Exception as exc:  # surface as text for the LLM to explain to the user
        return f"Failed to query Phoenix at this time. {type(exc).__name__}: {exc}"

    root_spans = [s for s in spans if not s.get("parent_id")][:safe_limit]

    if not root_spans:
        return (
            f"No root-level traces found in project '{project}' in the last "
            f"{hours_back}h. Phoenix is reachable, but the project is quiet."
        )

    lines = [
        f"Found {len(root_spans)} recent trace(s) in project '{project}' "
        f"(window: last {hours_back}h):",
        "",
    ]
    for idx, span in enumerate(root_spans, start=1):
        lines.append(_format_span_line(idx, span))
    return "\n".join(lines)


def _format_span_line(idx: int, span: dict) -> str:
    name = span.get("name", "<unnamed>")
    kind = span.get("span_kind", "?")
    status = span.get("status_code", "?")
    start_iso = span.get("start_time", "")
    end_iso = span.get("end_time", "")
    duration = _duration_ms(start_iso, end_iso)
    return f"{idx}. {name} | kind={kind} | {duration} | status={status} | started={start_iso}"


def _duration_ms(start_iso: str, end_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return f"{(end - start).total_seconds() * 1000:.0f}ms"
    except (TypeError, ValueError):
        return "duration=?"
