"""Time-to-response eval — wall-clock latency from user input to final response.

The eval is intentionally simple and code-deterministic (annotator_kind=CODE):
it reads a root span's ``start_time`` / ``end_time`` from Phoenix and writes
back a numeric annotation. Future evals (faithfulness, jailbreak, etc.) will
follow the same shape but with ``annotator_kind=LLM``.

Public API:

- ``time_to_response_ms(span)`` — pure function over a Phoenix span dict.
- ``annotate_span(span_id, latency_ms)`` — writes the annotation.
- ``annotate_latest_root_span(...)`` — convenience: fetch the most recent
  root span in the project and annotate it. This is what ``ui/app.py``
  calls after every Coordinator invocation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from phoenix.client import Client

ANNOTATION_NAME = "time_to_response_ms"
_DEFAULT_PROJECT = "sentinel"
_DEFAULT_LOOKBACK_MINUTES = 5
_DEFAULT_FETCH_LIMIT = 20


def time_to_response_ms(span: dict) -> Optional[float]:
    """Return the wall-clock duration of a Phoenix span in milliseconds.

    Args:
        span: A span dict as returned by ``Client().spans.get_spans(...)``,
            expected to contain ISO 8601 ``start_time`` and ``end_time``.

    Returns:
        The span duration in milliseconds, or ``None`` if either timestamp
        is missing or unparsable.
    """
    try:
        start = datetime.fromisoformat(span["start_time"])
        end = datetime.fromisoformat(span["end_time"])
    except (KeyError, TypeError, ValueError):
        return None
    return (end - start).total_seconds() * 1000.0


def annotate_span(span_id: str, latency_ms: float) -> None:
    """Write a ``time_to_response_ms`` annotation to a Phoenix span.

    Args:
        span_id: The hex span ID from ``span["context"]["span_id"]``.
        latency_ms: Wall-clock duration in milliseconds.
    """
    Client().spans.add_span_annotation(
        span_id=span_id,
        annotation_name=ANNOTATION_NAME,
        annotator_kind="CODE",
        score=float(latency_ms),
        explanation=f"Wall-clock from input to final response: {latency_ms:.0f}ms",
        sync=True,
    )


def annotate_latest_root_span(
    *,
    project: Optional[str] = None,
    lookback_minutes: int = _DEFAULT_LOOKBACK_MINUTES,
) -> Optional[dict]:
    """Fetch the most recent root span in the project and annotate it.

    Called from ``ui/app.py`` right after a Coordinator invocation completes,
    so the just-emitted trace gets its latency annotation immediately and the
    UI can show the result to the user.

    Args:
        project: Phoenix project name. Defaults to ``PHOENIX_PROJECT_NAME`` env
            var, then to ``"sentinel"``.
        lookback_minutes: How far back to search for the most recent root span.
            Default 5 minutes — generous to absorb any clock skew between the
            agent process and Phoenix, but tight enough not to annotate stale
            traces from old sessions.

    Returns:
        A dict ``{"span_id": str, "latency_ms": float, "name": str}`` describing
        the annotated span, or ``None`` if no root span was found in the window.
    """
    project_name = project or os.environ.get("PHOENIX_PROJECT_NAME", _DEFAULT_PROJECT)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    spans = Client().spans.get_spans(
        project_identifier=project_name,
        start_time=start_time,
        end_time=end_time,
        limit=_DEFAULT_FETCH_LIMIT,
    )
    root_spans = [s for s in spans if not s.get("parent_id")]
    if not root_spans:
        return None

    latest = max(root_spans, key=lambda s: s.get("start_time", ""))
    latency = time_to_response_ms(latest)
    if latency is None:
        return None

    span_id = latest["context"]["span_id"]
    annotate_span(span_id, latency)
    return {"span_id": span_id, "latency_ms": latency, "name": latest.get("name", "")}
