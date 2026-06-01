"""Faithfulness eval — code-eval stub for Phase 7 / Addition 1.

Purpose: verify that an agent's output is grounded in the trace data it had
access to. The full LLM-as-judge version is a follow-up (see ADR-012); this
stub is a code-eval that inspects span attributes and flags traces where the
``output.value`` references entities that do not appear in ``input.value``.

Heuristic (intentionally simple — pattern signal, not eval quality):
- Parse ``input.value`` and ``output.value`` as JSON.
- Extract a flat set of string tokens from ``input.value``.
- For each top-level string value in ``output.value``, check whether at least
  one input token appears as a substring.
- If no input token appears, the trace is flagged ``unsupported``.

This is a coarse-but-honest grounding check that runs in microseconds — fine
for parallel demonstration. The real LLM-as-judge version replaces this in a
later iteration without changing the tool surface.
"""

from __future__ import annotations

import json
from typing import Any

VERDICT_FAITHFUL = "faithful"
VERDICT_UNSUPPORTED = "unsupported"
VERDICT_SKIPPED = "skipped"


def _tokens_from(payload: Any) -> set[str]:
    """Flatten any JSON value into a set of lowercase string tokens."""
    out: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, str):
            for tok in v.lower().split():
                tok = tok.strip(",.;:()[]{}\"'")
                if tok:
                    out.add(tok)
        elif isinstance(v, dict):
            for child in v.values():
                walk(child)
        elif isinstance(v, list):
            for child in v:
                walk(child)

    walk(payload)
    return out


def judge_span(span_attrs: dict[str, Any]) -> dict[str, str]:
    """Score a single span. Returns ``{label, reason}``.

    Returns ``skipped`` for spans without both an input and output value.
    """
    raw_in = span_attrs.get("input.value")
    raw_out = span_attrs.get("output.value")
    if not raw_in or not raw_out:
        return {"label": VERDICT_SKIPPED, "reason": "missing input or output value"}

    try:
        in_obj = json.loads(raw_in) if isinstance(raw_in, str) else raw_in
        out_obj = json.loads(raw_out) if isinstance(raw_out, str) else raw_out
    except (TypeError, ValueError) as exc:
        return {"label": VERDICT_SKIPPED, "reason": f"non-JSON payload: {exc}"}

    in_tokens = _tokens_from(in_obj)
    out_tokens = _tokens_from(out_obj)
    if not out_tokens:
        return {"label": VERDICT_SKIPPED, "reason": "empty output tokens"}

    overlap = in_tokens & out_tokens
    if overlap:
        return {"label": VERDICT_FAITHFUL, "reason": f"shared tokens: {len(overlap)}"}
    return {"label": VERDICT_UNSUPPORTED, "reason": "output shares no token with input"}
