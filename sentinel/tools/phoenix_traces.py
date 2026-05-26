"""Phoenix trace-fetching tool — Coordinator's first observability tool.

This module exposes ``get_recent_traces``, the function the agents call when
they need recent root-level traces from the active Phoenix project. It hits
Phoenix's REST API via the official ``phoenix.client.Client`` and returns a
structured text summary the LLM can reason about.

Key design point: the output includes excerpts of ``input.value``,
``output.value``, and ``status_message`` from each span's OpenInference
attributes when present. Sub-agents need this to understand the *semantic*
failure mode (e.g. a false-positive misclassification with ``true_label`` in
the output payload) and not just the status code. Without the excerpts,
agents see "ERROR" and default to assuming "service outage" — which inverts
the failure narrative in workloads like fraud detection where ERROR-status
means over-blocking, not service down.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from phoenix.client import Client

_DEFAULT_PROJECT = "sentinel"
_MAX_LIMIT = 100
_ATTR_EXCERPT_MAX_CHARS = 280


def get_recent_traces(hours_back: int = 1, limit: int = 20) -> str:
    """Return a text summary of the most recent root-level traces in Phoenix.

    Use this when the user asks about recent activity, incidents, the last
    deploy's behavior, or anything that requires looking at production
    observability data. Only returns *root* spans (full top-level
    invocations); nested LLM and tool spans are summarized by their parent.

    The summary for each span includes:
    - name, span kind, duration, status, start time (header line)
    - status_message when set (one sub-line)
    - input.value excerpt from span attributes when present
    - output.value excerpt from span attributes when present

    The input/output excerpts are critical for distinguishing failure modes
    in production AI workloads (e.g. a fraud classifier returning a false
    positive vs a service outage — both show as ERROR status, but the output
    payload tells the real story).

    Args:
        hours_back: How far back to look, in hours. Default 1. Use larger
            values (e.g. 24) for daily context, smaller values for an
            incident-window.
        limit: Maximum number of root traces to return. Default 20. Hard
            capped at 100 to keep responses bounded.

    Returns:
        A Markdown-formatted summary the LLM can read aloud or reason over.
        Either a multi-line listing of traces or a clear "no traces found"
        message.
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
        lines.append(_format_span_block(idx, span))
    return "\n".join(lines)


def _format_span_block(idx: int, span: dict) -> str:
    """Multi-line block per span: header + status_message + input/output excerpts."""
    name = span.get("name", "<unnamed>")
    kind = span.get("span_kind", "?")
    status = span.get("status_code", "?")
    start_iso = span.get("start_time", "")
    end_iso = span.get("end_time", "")
    duration = _duration_ms(start_iso, end_iso)
    status_message = (span.get("status_message") or "").strip()

    attrs = span.get("attributes") or {}
    input_excerpt = _attr_excerpt(attrs, "input.value")
    output_excerpt = _attr_excerpt(attrs, "output.value")

    lines = [
        f"{idx}. {name} | kind={kind} | {duration} | status={status} | started={start_iso}"
    ]
    if status_message:
        lines.append(f"   status_message: {status_message}")
    if input_excerpt:
        lines.append(f"   input:  {input_excerpt}")
    if output_excerpt:
        lines.append(f"   output: {output_excerpt}")
    return "\n".join(lines)


def _attr_excerpt(attrs: dict[str, Any], key: str, max_chars: int = _ATTR_EXCERPT_MAX_CHARS) -> str:
    """Extract a span-attribute value as a compact one-line excerpt.

    OpenInference convention stores ``input.value`` / ``output.value`` as
    JSON strings. We re-serialize compactly (no whitespace) so the LLM
    sees the structured payload in a single line, then truncate to a
    bounded length so multi-trace listings stay readable.

    Returns an empty string when the attribute is missing or empty — the
    caller suppresses the line in that case.
    """
    raw = attrs.get(key)
    if raw is None or raw == "":
        return ""

    # If the value is already a Python structure (e.g. dict from a
    # deserialized payload), serialize it directly. If it's a string,
    # attempt to parse it as JSON and re-emit compactly; fall back to the
    # raw string when it isn't valid JSON.
    text: str
    if isinstance(raw, (dict, list)):
        try:
            text = json.dumps(raw, separators=(",", ":"))
        except (TypeError, ValueError):
            text = str(raw)
    else:
        text = str(raw).strip()
        try:
            parsed = json.loads(text)
            text = json.dumps(parsed, separators=(",", ":"))
        except (json.JSONDecodeError, TypeError):
            # Not JSON — keep the original text
            pass

    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def _duration_ms(start_iso: str, end_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return f"{(end - start).total_seconds() * 1000:.0f}ms"
    except (TypeError, ValueError):
        return "duration=?"
