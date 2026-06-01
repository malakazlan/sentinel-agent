"""Prompt-injection eval — code-eval stub for Phase 7 / Addition 1.

Purpose: detect known prompt-injection signatures in incoming user / tool
inputs. Real production version would use a classifier or a dedicated LLM
judge; this stub is a regex-based signature scan that catches the obvious
("ignore previous instructions", role-confusion attempts, etc.).

Stub limitations documented in ADR-012. The point is the orchestration
pattern; eval quality is a separate workstream.
"""

from __future__ import annotations

import re
from typing import Any

VERDICT_CLEAN = "clean"
VERDICT_SUSPECT = "suspect"
VERDICT_SKIPPED = "skipped"

_SIGNATURE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all |any )?previous (instructions|prompts|rules)",
        r"disregard (the )?(system )?prompt",
        r"you are now (a |an )?(different|new|unrestricted)",
        r"jailbreak",
        r"DAN mode",
        r"system\s*[:>]\s*(you|act)",
        r"</?(system|assistant|user)>",
    )
)


def judge_text(text: str) -> dict[str, Any]:
    """Score a single text blob for prompt-injection signatures.

    Returns ``{label, matches, reason}``. ``matches`` lists the regex source
    strings that fired so the caller can attribute the verdict.
    """
    if not text or not isinstance(text, str):
        return {"label": VERDICT_SKIPPED, "matches": [], "reason": "empty or non-string input"}

    hits: list[str] = []
    for pat in _SIGNATURE_PATTERNS:
        if pat.search(text):
            hits.append(pat.pattern)

    if hits:
        return {
            "label": VERDICT_SUSPECT,
            "matches": hits,
            "reason": f"matched {len(hits)} injection signature(s)",
        }
    return {"label": VERDICT_CLEAN, "matches": [], "reason": "no signatures matched"}
