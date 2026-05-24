"""EvalRunner's tool surface — orchestrates eval suites over recent traces.

For Phase 2 step 2 there is exactly one suite (``run_hallucination_eval``).
More suites land in later phases (toxicity, faithfulness, drift, jailbreak per
CLAUDE.md §5). The pattern: fetch recent root traces from Phoenix, invoke the
matching eval module from ``evals/``, return a Markdown summary the agent can
quote or paraphrase.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from phoenix.client import Client

from evals.hallucination import evaluate_trace

_DEFAULT_PROJECT = "sentinel"
_MAX_LIMIT = 25


def run_hallucination_eval(hours_back: int = 1, limit: int = 5) -> str:
    """Run the hallucination eval on recent traces and return a Markdown summary.

    Fetches the most recent root traces from Phoenix in the window, invokes
    the LLM-as-judge hallucination eval on each one that has a tool call,
    writes ``hallucination`` annotations back into Phoenix, and returns a
    short summary the calling agent can read.

    Args:
        hours_back: How far back to look, in hours. Default 1. Larger values
            slow the eval (one judge LLM call per evaluated trace).
        limit: Max number of root traces to evaluate. Default 5. Hard capped
            at 25 to keep response time bounded.

    Returns:
        A Markdown summary: total evaluated, breakdown by label, per-trace
        results (truncated trace IDs). Or a "no traces" message if the window
        is empty.
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
    except Exception as exc:  # surface as text for the calling LLM
        return f"Failed to fetch traces from Phoenix. {type(exc).__name__}: {exc}"

    root_spans = [s for s in spans if not s.get("parent_id")]
    root_spans.sort(key=lambda s: s.get("start_time", ""), reverse=True)

    trace_ids: list[str] = []
    seen: set[str] = set()
    for span in root_spans:
        tid = span.get("context", {}).get("trace_id")
        if tid and tid not in seen:
            seen.add(tid)
            trace_ids.append(tid)
        if len(trace_ids) >= safe_limit:
            break

    if not trace_ids:
        return (
            f"No recent traces to evaluate in project '{project}' in the last "
            f"{hours_back}h."
        )

    results: list[dict] = []
    for tid in trace_ids:
        try:
            verdict = evaluate_trace(tid)
        except Exception as exc:
            results.append(
                {"trace_id": tid, "label": "error", "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        if verdict is None:
            results.append({"trace_id": tid, "label": "skipped", "reason": "no tool call in trace"})
        else:
            results.append(verdict)

    counts = {"faithful": 0, "hallucinated": 0, "skipped": 0, "error": 0, "unknown": 0}
    for r in results:
        counts[r.get("label", "unknown")] = counts.get(r.get("label", "unknown"), 0) + 1

    lines = [
        f"Hallucination eval: {len(results)} trace(s) in project '{project}' (last {hours_back}h).",
        (
            f"  faithful: {counts['faithful']}  |  hallucinated: {counts['hallucinated']}  "
            f"|  skipped (no tool): {counts['skipped']}  |  error: {counts['error']}"
        ),
        "",
    ]
    for r in results:
        tid_short = (r.get("trace_id", "?") or "?")[:8]
        label = r.get("label", "?")
        if label == "hallucinated":
            lines.append(f"- {tid_short}... => **HALLUCINATED**")
        elif label in {"error", "skipped"}:
            lines.append(f"- {tid_short}... => {label} ({r.get('reason', '')})")
        else:
            lines.append(f"- {tid_short}... => {label}")
    return "\n".join(lines)
