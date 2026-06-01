"""Tests for the CriticAgent + CritiqueResult schema (ADR-016 / Phase 7
Addition 4).

The agent's wiring is asserted statically (no live LLM calls). The schema
is exercised with both well-formed and ill-formed inputs to confirm the
validators bite. The orchestrator's refinement loop is exercised in the
integration test in tests/unit/coordinator/.
"""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent
from pydantic import ValidationError

from sentinel.agents.critic import (
    CRITIC_SCORE_THRESHOLD,
    MAX_REFINEMENT_ITERATIONS,
    critic,
)
from sentinel.agents.schemas import CritiqueResult
from sentinel.constants import SUBAGENT_MODEL


# ── Agent wiring ─────────────────────────────────────────────────────────


def test_critic_is_an_llm_agent() -> None:
    assert isinstance(critic, LlmAgent)
    assert critic.name == "critic"


def test_critic_uses_subagent_model() -> None:
    assert critic.model == SUBAGENT_MODEL


def test_critic_has_no_tools() -> None:
    # The critic must operate purely on the postmortem text in the user
    # message. Tools would let it invent trace evidence.
    assert critic.tools == [] or critic.tools is None or len(critic.tools) == 0


def test_critic_disallows_transfers() -> None:
    assert critic.disallow_transfer_to_parent is True
    assert critic.disallow_transfer_to_peers is True


def test_threshold_and_iteration_cap_are_documented_constants() -> None:
    # Hardcoded acceptance + iteration cap must be auditable.
    assert CRITIC_SCORE_THRESHOLD == 0.85
    assert MAX_REFINEMENT_ITERATIONS == 2


# ── CritiqueResult schema ────────────────────────────────────────────────


def _valid_critique(score: float = 0.9, accept: bool = True) -> CritiqueResult:
    return CritiqueResult(
        score=score,
        rubric_scores={
            "completeness": 0.9,
            "grounding": 0.9,
            "actionability": 0.9,
            "customer_impact": 0.9,
        },
        critique=(
            "Postmortem is grounded in trace evidence and the action items "
            "have specific owners and due dates. No revisions required."
        ),
        gaps_by_section={},
        accept=accept,
    )


def test_valid_critique_round_trips_through_json() -> None:
    crit = _valid_critique()
    parsed = CritiqueResult.model_validate_json(crit.model_dump_json())
    assert parsed.score == 0.9
    assert parsed.accept is True


def test_score_below_zero_or_above_one_rejected() -> None:
    with pytest.raises(ValidationError):
        CritiqueResult(score=-0.1, critique="x" * 30, accept=False)
    with pytest.raises(ValidationError):
        CritiqueResult(score=1.5, critique="x" * 30, accept=True)


def test_rubric_score_outside_unit_interval_rejected() -> None:
    with pytest.raises(ValidationError):
        CritiqueResult(
            score=0.5,
            rubric_scores={"completeness": 1.2},
            critique="x" * 30,
            accept=False,
        )


def test_critique_minimum_length_enforced() -> None:
    # Substantive feedback floor. Prevents empty/placeholder critiques.
    with pytest.raises(ValidationError):
        CritiqueResult(score=0.5, critique="short", accept=False)


# ── Critique extractor + revision-prompt helper ──────────────────────────


def test_extract_critique_json_handles_fenced_block() -> None:
    from sentinel.coordinator import _extract_critique_json

    text = (
        "Here is the critique:\n\n"
        '```json\n{"score": 0.7, "critique": "ok"}\n```\n'
    )
    obj = _extract_critique_json(text)
    assert obj == {"score": 0.7, "critique": "ok"}


def test_extract_critique_json_returns_none_on_no_json() -> None:
    from sentinel.coordinator import _extract_critique_json

    assert _extract_critique_json("no json here") is None


def test_build_revision_prompt_includes_score_gaps_and_truncated_original() -> None:
    from sentinel.coordinator import _build_revision_prompt

    crit = CritiqueResult(
        score=0.7,
        rubric_scores={"completeness": 0.6, "grounding": 0.8},
        critique="Impact section lacks customer-visible numbers.",
        gaps_by_section={"impact": "needs customer-visible numbers"},
        accept=False,
    )
    long_original = "x" * 4000
    prompt = _build_revision_prompt(
        original_text=long_original,
        critique=crit,
        scenario_id="fraud-fp-burst",
    )
    assert "0.70" in prompt
    assert "completeness: 0.60" in prompt
    assert "impact: needs customer-visible numbers" in prompt
    # Original is truncated at 3000 chars + ellipsis marker
    assert "(truncated)" in prompt
    assert prompt.count("x") <= 3001  # 3000 chars + 1 in the word "truncated"? no — exact slice
