"""Drift eval — code-eval stub for Phase 7 / Addition 1.

Purpose: detect distribution drift in span outcomes across two halves of a
time window. Real production version would compute population-stability index
or KS-test; this stub computes a simple proportion-delta on ``status_code``.

Heuristic:
- Split spans into first-half / second-half by start_time.
- For each half, compute the proportion of ``ERROR`` status codes.
- Drift score = |first_half_error_rate - second_half_error_rate|.
- Label = ``drift`` if score > threshold, else ``stable``.

Stub limitations documented honestly in ADR-012. Real version is a follow-up.
"""

from __future__ import annotations

from typing import Any

VERDICT_STABLE = "stable"
VERDICT_DRIFT = "drift"
VERDICT_SKIPPED = "skipped"


def evaluate_spans(spans: list[dict[str, Any]], threshold: float = 0.15) -> dict[str, Any]:
    """Score a window of spans for status-code drift.

    Args:
        spans: list of OpenInference span dicts with ``status_code`` and
            ``start_time`` keys.
        threshold: absolute proportion-delta above which we flag drift.

    Returns:
        ``{label, score, first_half_error_rate, second_half_error_rate,
        n_first, n_second, reason}``.
    """
    if len(spans) < 4:
        return {
            "label": VERDICT_SKIPPED,
            "score": 0.0,
            "reason": f"insufficient spans for two-window split (got {len(spans)})",
        }

    ordered = sorted(spans, key=lambda s: s.get("start_time", ""))
    mid = len(ordered) // 2
    first, second = ordered[:mid], ordered[mid:]

    def err_rate(window: list[dict[str, Any]]) -> float:
        if not window:
            return 0.0
        n_err = sum(1 for s in window if s.get("status_code") == "ERROR")
        return n_err / len(window)

    fer, ser = err_rate(first), err_rate(second)
    score = abs(fer - ser)
    label = VERDICT_DRIFT if score > threshold else VERDICT_STABLE
    return {
        "label": label,
        "score": round(score, 3),
        "first_half_error_rate": round(fer, 3),
        "second_half_error_rate": round(ser, 3),
        "n_first": len(first),
        "n_second": len(second),
        "reason": f"|{fer:.2f} - {ser:.2f}| = {score:.2f} {'>' if score > threshold else '<='} {threshold}",
    }
