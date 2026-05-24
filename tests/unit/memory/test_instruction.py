"""Coordinator instruction-provider tests — directives surface in the prompt.

These verify that a ``PriorContextBriefing`` of a given shape causes the
rendered instruction to contain the directive lines and protocol language
that ADR-009 mandates. Pure string assertions — no LLM calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sentinel.coordinator import _coordinator_instruction, render_directive_block
from sentinel.memory.briefing import PriorContextBriefing


def _ctx_with(briefing: Any) -> Any:
    """Build a minimal stand-in for ``ReadonlyContext`` that exposes ``state``."""
    return SimpleNamespace(state={"prior_context_briefing": briefing})


# ── render_directive_block ─────────────────────────────────────────────────


def test_cold_start_renders_no_active_directives() -> None:
    block = render_directive_block(PriorContextBriefing(cold_start=True))
    assert "cold_start: true" in block.lower()
    assert "no active directives" in block.lower() or "no overrides" in block.lower()
    # No imperative MUST clauses for cold-start
    assert "first_route" not in block or "first_route: none" in block.lower()


def test_first_route_renders_imperative_directive_with_evidence() -> None:
    briefing = PriorContextBriefing(
        first_route="trace_analyzer",
        evidence={"first_route": "5 of last 8 root spans were ERROR"},
        stats={"n_total": 8, "n_error": 5},
    )
    block = render_directive_block(briefing)
    assert "first_route: trace_analyzer" in block.lower()
    assert "5 of last 8" in block  # evidence preserved verbatim
    assert "MUST" in block  # imperative language present
    # Stats summary line is present
    assert "n_total=8" in block
    assert "n_error=5" in block


def test_must_eval_after_renders_post_action_directive() -> None:
    briefing = PriorContextBriefing(
        must_eval_after=True,
        evidence={"must_eval_after": "1 hallucinated annotation in window"},
    )
    block = render_directive_block(briefing)
    assert "must_eval_after: true" in block.lower()
    assert "eval_runner" in block
    assert "MUST" in block


def test_skip_routes_renders_with_must_not() -> None:
    briefing = PriorContextBriefing(
        skip_routes=["trace_analyzer"],
        evidence={"skip_routes": "test fixture"},
    )
    block = render_directive_block(briefing)
    assert "skip_routes" in block
    assert "trace_analyzer" in block
    assert "MUST NOT" in block


def test_default_hours_back_renders_in_block() -> None:
    briefing = PriorContextBriefing(
        default_hours_back=24,
        evidence={"default_hours_back": "low volume"},
    )
    block = render_directive_block(briefing)
    assert "default_hours_back: 24" in block.lower()


# ── _coordinator_instruction (full prompt assembly) ────────────────────────


def test_prompt_substitutes_directive_block_for_briefing_object() -> None:
    briefing = PriorContextBriefing(
        first_route="trace_analyzer",
        evidence={"first_route": "test-fixture evidence"},
    )
    prompt = _coordinator_instruction(_ctx_with(briefing))
    assert "first_route: trace_analyzer" in prompt.lower()
    assert "test-fixture evidence" in prompt
    # The placeholder must have been replaced — no raw curly-brace token left
    assert "{prior_context_briefing}" not in prompt


def test_prompt_falls_back_when_state_lacks_briefing() -> None:
    prompt = _coordinator_instruction(SimpleNamespace(state={}))
    assert "introspection has not run" in prompt.lower() or "unavailable" in prompt.lower()
    assert "{prior_context_briefing}" not in prompt


def test_prompt_falls_back_when_state_holds_wrong_type() -> None:
    """Defensive: if something stuffs a string into state, don't crash."""
    prompt = _coordinator_instruction(_ctx_with("not a briefing"))
    assert "unavailable" in prompt.lower()
    assert "{prior_context_briefing}" not in prompt
