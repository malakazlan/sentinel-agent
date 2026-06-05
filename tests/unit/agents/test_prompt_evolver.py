"""Tests for PromptEvolver decision logic + history store + promotion gate.

Phase 8 / ADR-020. The Llm-based variant authoring (the agent's
generate-content turn) is asserted statically — wiring, model
selection, temperature, no-tools — but the actual variant text comes
from the LLM and is not unit-tested here.

The deterministic surfaces (history store, cooldown, decision +
promotion gate) ARE unit-tested rigorously, including the unhappy
paths (no improvement found, insufficient samples, cooldown active,
no scored variants).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.agents import LlmAgent
from pydantic import ValidationError

from sentinel.agents.prompt_evolver import (
    COOLDOWN_SECONDS,
    MIN_PROMOTION_DELTA,
    TRIGGER_MIN_SAMPLES,
    TRIGGER_SCORE_THRESHOLD,
    PromptEvolutionProposal,
    PromptVariant,
    PromptVariantSet,
    ScoredVariant,
    apply_promotion,
    autopromote_enabled,
    evaluate_proposal,
    hash_prompt,
    prompt_evolver,
    should_trigger_evolution,
)
from sentinel.constants import COORDINATOR_MODEL
from sentinel.memory.prompt_history import (
    AgentRollup,
    PromptHistoryStore,
    PromptRunRecord,
)


# ── Agent wiring ──────────────────────────────────────────────────────────


def test_prompt_evolver_is_llm_agent() -> None:
    assert isinstance(prompt_evolver, LlmAgent)
    assert prompt_evolver.name == "prompt_evolver"


def test_prompt_evolver_uses_coordinator_model() -> None:
    """Variant authoring needs reasoning depth — Pro model, not flash."""
    assert prompt_evolver.model == COORDINATOR_MODEL


def test_prompt_evolver_has_no_tools() -> None:
    assert prompt_evolver.tools == [] or prompt_evolver.tools is None


def test_prompt_evolver_disallows_transfers() -> None:
    assert prompt_evolver.disallow_transfer_to_parent is True
    assert prompt_evolver.disallow_transfer_to_peers is True


# ── History store ────────────────────────────────────────────────────────


def test_history_store_appends_and_reads_back(tmp_path: Path) -> None:
    store = PromptHistoryStore(path=tmp_path / "history.jsonl")
    store.append(PromptRunRecord(
        agent_name="postmortem",
        prompt_version="v1",
        prompt_hash="abc123",
        incident_id="inc-1",
        scenario_id="fraud-fp-burst",
        aggregate_critic_score=0.85,
        rubric_scores={"completeness": 0.9, "grounding": 0.8},
    ))
    records = store.load_all()
    assert len(records) == 1
    assert records[0]["agent_name"] == "postmortem"
    assert records[0]["aggregate_critic_score"] == 0.85


def test_history_store_rollup_computes_means(tmp_path: Path) -> None:
    store = PromptHistoryStore(path=tmp_path / "history.jsonl")
    for score in [0.7, 0.8, 0.75]:
        store.append(PromptRunRecord(
            agent_name="postmortem",
            prompt_version="v1",
            prompt_hash="abc",
            incident_id="x",
            scenario_id="y",
            aggregate_critic_score=score,
            rubric_scores={"completeness": score, "grounding": score - 0.05},
        ))
    rollup = store.rollup_for_agent("postmortem")
    assert rollup is not None
    assert rollup.sample_count == 3
    assert rollup.avg_aggregate_score == pytest.approx(0.75)
    assert rollup.avg_rubric_scores["completeness"] == pytest.approx(0.75)
    assert rollup.avg_rubric_scores["grounding"] == pytest.approx(0.70)


def test_history_store_returns_none_for_unknown_agent(tmp_path: Path) -> None:
    store = PromptHistoryStore(path=tmp_path / "history.jsonl")
    assert store.rollup_for_agent("nonexistent") is None


def test_history_store_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"agent_name": "x", "prompt_version": "v1", "prompt_hash": "h", '
        '"incident_id": "i", "scenario_id": "s", "aggregate_critic_score": 0.9, '
        '"rubric_scores": {}, "timestamp_iso": "t"}\n'
        "{ this is not valid json\n"
        '{"agent_name": "y", "prompt_version": "v1", "prompt_hash": "h", '
        '"incident_id": "i2", "scenario_id": "s", "aggregate_critic_score": 0.5, '
        '"rubric_scores": {}, "timestamp_iso": "t"}\n'
    )
    store = PromptHistoryStore(path=p)
    records = store.load_all()
    assert len(records) == 2  # malformed line silently dropped


# ── Trigger gate ─────────────────────────────────────────────────────────


def _rollup(score: float, samples: int = TRIGGER_MIN_SAMPLES + 1) -> AgentRollup:
    return AgentRollup(
        agent_name="postmortem",
        current_prompt_version="v1",
        sample_count=samples,
        avg_aggregate_score=score,
        avg_rubric_scores={},
        last_record_timestamp="2026-06-05T18:00:00Z",
    )


def test_trigger_false_when_no_rollup() -> None:
    assert should_trigger_evolution(None) is False


def test_trigger_false_when_score_above_threshold() -> None:
    assert should_trigger_evolution(_rollup(TRIGGER_SCORE_THRESHOLD + 0.01)) is False


def test_trigger_false_when_insufficient_samples() -> None:
    rollup = _rollup(0.5, samples=TRIGGER_MIN_SAMPLES - 1)
    assert should_trigger_evolution(rollup) is False


def test_trigger_true_when_below_threshold_with_samples(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Pin the lock dir to tmp_path so we don't read a stale real cooldown.
    from sentinel.agents import prompt_evolver as ev_mod
    monkeypatch.setattr(ev_mod, "_LOCK_DIR", tmp_path / "locks")
    assert should_trigger_evolution(_rollup(0.5)) is True


def test_trigger_false_during_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from sentinel.agents import prompt_evolver as ev_mod
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    monkeypatch.setattr(ev_mod, "_LOCK_DIR", lock_dir)
    # Stamp a "just now" timestamp so cooldown is active.
    import time
    (lock_dir / "postmortem.lock").write_text(str(time.time()))
    assert should_trigger_evolution(_rollup(0.5)) is False


# ── Promotion decision gate ──────────────────────────────────────────────


def _variant(vid: str = "var-a", text: str = "An entirely revised prompt body that is at least fifty chars long.") -> PromptVariant:
    return PromptVariant(
        variant_id=vid,
        prompt_text=text,
        rationale="Test rationale explaining why this variant addresses a measurable gap.",
    )


def test_evaluate_no_scored_variants_yields_no_recommendation() -> None:
    p = evaluate_proposal(
        target_agent="postmortem",
        current_prompt_version="v1",
        current_prompt_text="<current>",
        baseline_avg_score=0.7,
        scored_variants=[],
    )
    assert p.promotion_recommended is False
    assert p.proposed_winner is None
    assert "No variants" in p.decision_rationale


def test_evaluate_picks_highest_scoring_variant() -> None:
    scored = [
        ScoredVariant(variant=_variant("var-a"), replay_aggregate_score=0.78),
        ScoredVariant(variant=_variant("var-b"), replay_aggregate_score=0.91),
        ScoredVariant(variant=_variant("var-c"), replay_aggregate_score=0.82),
    ]
    p = evaluate_proposal(
        target_agent="postmortem",
        current_prompt_version="v1",
        current_prompt_text="<current>",
        baseline_avg_score=0.74,
        scored_variants=scored,
    )
    assert p.proposed_winner is not None
    assert p.proposed_winner.variant.variant_id == "var-b"
    assert p.score_delta_over_baseline == pytest.approx(0.17)
    assert p.promotion_recommended is True


def test_evaluate_rejects_below_min_delta() -> None:
    """The 'no improvement found' unhappy path required by ADR-020."""
    scored = [
        ScoredVariant(variant=_variant("var-a"), replay_aggregate_score=0.72),
        ScoredVariant(variant=_variant("var-b"), replay_aggregate_score=0.74),
    ]
    p = evaluate_proposal(
        target_agent="postmortem",
        current_prompt_version="v1",
        current_prompt_text="<current>",
        baseline_avg_score=0.74,
        scored_variants=scored,
    )
    assert p.proposed_winner is not None  # we still record the winner
    assert p.promotion_recommended is False  # but don't recommend promotion
    assert p.score_delta_over_baseline <= MIN_PROMOTION_DELTA


# ── Variant schema bounds ────────────────────────────────────────────────


def test_variant_set_requires_2_or_3_variants() -> None:
    with pytest.raises(ValidationError):
        PromptVariantSet(
            target_agent="postmortem",
            current_prompt_version="v1",
            proposed_variants=[_variant("var-a")],  # only 1
        )
    with pytest.raises(ValidationError):
        PromptVariantSet(
            target_agent="postmortem",
            current_prompt_version="v1",
            proposed_variants=[
                _variant("var-a"), _variant("var-b"),
                _variant("var-c"), _variant("var-d"),
            ],  # 4
        )


def test_variant_prompt_text_minimum_length() -> None:
    with pytest.raises(ValidationError):
        _variant("var-a", text="too short")


# ── Auto-promotion env gate ──────────────────────────────────────────────


def test_autopromote_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTINEL_PROMPT_EVOLUTION_AUTOPROMOTE", raising=False)
    assert autopromote_enabled() is False


def test_autopromote_on_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_PROMPT_EVOLUTION_AUTOPROMOTE", "1")
    assert autopromote_enabled() is True


# ── Apply promotion: writes file + archives old + stamps cooldown ────────


def test_apply_promotion_writes_new_prompt_and_archives_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.agents import prompt_evolver as ev_mod
    monkeypatch.setattr(ev_mod, "_LOCK_DIR", tmp_path / "locks")
    # Redirect the audit dir into tmp_path too.
    import sentinel.agents.prompt_evolver as ev_pkg
    real_write_audit = ev_pkg._write_audit
    monkeypatch.setattr(ev_pkg, "_write_audit", lambda p: None)

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    target = prompts_dir / "postmortem.md"
    target.write_text("OLD PROMPT BODY", encoding="utf-8")

    proposal = PromptEvolutionProposal(
        target_agent="postmortem",
        current_prompt_version="v1",
        current_prompt_hash=hash_prompt("OLD PROMPT BODY"),
        baseline_avg_score=0.7,
        proposed_winner=ScoredVariant(
            variant=_variant("var-v2", text="NEW PROMPT BODY THAT IS LONGER THAN FIFTY CHARS NO REALLY IT IS"),
            replay_aggregate_score=0.88,
        ),
        all_scored_variants=[],
        score_delta_over_baseline=0.18,
        promotion_recommended=True,
        decision_rationale="test promotion fixture rationale",
    )
    written = apply_promotion(proposal, prompts_dir=prompts_dir)
    assert written is True
    assert target.read_text().startswith("NEW PROMPT BODY")
    # Archive was written too.
    archive_files = list(prompts_dir.glob("postmortem_v1.archived.md"))
    assert len(archive_files) == 1
    assert archive_files[0].read_text() == "OLD PROMPT BODY"


def test_apply_promotion_noop_when_not_recommended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal = PromptEvolutionProposal(
        target_agent="postmortem",
        current_prompt_version="v1",
        current_prompt_hash=hash_prompt("X"),
        baseline_avg_score=0.7,
        proposed_winner=None,
        all_scored_variants=[],
        score_delta_over_baseline=0.0,
        promotion_recommended=False,
        decision_rationale="no improvement detected this cycle",
    )
    written = apply_promotion(proposal, prompts_dir=tmp_path)
    assert written is False
    assert list(tmp_path.iterdir()) == []
