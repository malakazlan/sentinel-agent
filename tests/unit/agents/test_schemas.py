"""Schema and validator tests for cross-agent contracts.

Production-shaped schemas — the validators here are load-bearing for real
ops consumers (PagerDuty / Linear / SRE templates). Bad data must fail at
construction time, not silently corrupt a downstream system.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.agents.schemas import (
    ActionItem,
    EvalGuardrail,
    POSTMORTEM_REQUIRED_SECTIONS,
    Postmortem,
    RemediationPlan,
)


# ── EvalGuardrail ──────────────────────────────────────────────────────────


def test_eval_guardrail_minimal_valid() -> None:
    g = EvalGuardrail(
        name="fp_rate_spike_5m",
        trigger_metric="fp_rate_5m",
        threshold=0.15,
        severity_on_breach="P1",
        why_this_eval="Catches false-positive bursts that froze accounts on 2026-05-24.",
    )
    assert g.name == "fp_rate_spike_5m"
    assert g.severity_on_breach == "P1"


def test_eval_guardrail_rejects_short_name() -> None:
    with pytest.raises(ValidationError):
        EvalGuardrail(
            name="x",
            trigger_metric="x",
            threshold=0.0,
            severity_on_breach="P1",
            why_this_eval="x" * 20,
        )


def test_eval_guardrail_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        EvalGuardrail(
            name="ok_name",
            trigger_metric="ok",
            threshold=0.0,
            severity_on_breach="urgent",  # type: ignore[arg-type]
            why_this_eval="x" * 20,
        )


# ── RemediationPlan — at-least-one-action invariant ────────────────────────


def test_remediation_plan_with_only_rollback_is_valid() -> None:
    p = RemediationPlan(
        severity="P1",
        confidence="high",
        rollback_target="fraud-classifier-v2.2.7",
        rationale=(
            "RootCause identified prompt-version v2.3.1 deployed at T-18m as "
            "the most likely cause; rollback restores prior stable behavior."
        ),
        rollback_plan_if_remediation_fails=(
            "Re-deploy v2.3.1 and escalate to model-team on-call."
        ),
    )
    assert p.rollback_target == "fraud-classifier-v2.2.7"
    assert p.patched_prompt is None


def test_remediation_plan_with_only_patched_prompt_is_valid() -> None:
    p = RemediationPlan(
        severity="P2",
        confidence="medium",
        patched_prompt="Classify the transaction. Output exactly one of: APPROVE, FRAUD, REVIEW. No other text.",
        rationale=(
            "RootCause flagged free-form classifier output as the failure source; "
            "this patched prompt constrains the output set."
        ),
        risks=["May reduce nuanced REVIEW cases", "Needs eval re-run before broad rollout"],
        rollback_plan_if_remediation_fails=(
            "Revert classifier prompt to last known-good (v2.2.7) and re-escalate."
        ),
    )
    assert p.patched_prompt is not None


def test_remediation_plan_with_only_guardrail_is_valid() -> None:
    g = EvalGuardrail(
        name="fp_rate_spike_5m",
        trigger_metric="fp_rate_5m",
        threshold=0.15,
        severity_on_breach="P1",
        why_this_eval="Detects future false-positive bursts faster than current paging.",
    )
    p = RemediationPlan(
        severity="P3",
        confidence="high",
        eval_guardrail=g,
        rationale=(
            "RootCause could not isolate a single fault; adding a faster "
            "detection guardrail is the actionable remediation available."
        ),
        rollback_plan_if_remediation_fails=(
            "Disable the new guardrail in evals registry and revert to previous alerting cadence."
        ),
    )
    assert p.eval_guardrail is g


def test_remediation_plan_with_no_actions_is_rejected() -> None:
    """A plan with no actions is not a plan — must fail at construction."""
    with pytest.raises(ValidationError) as exc:
        RemediationPlan(
            severity="P1",
            confidence="high",
            rationale="x" * 50,
            rollback_plan_if_remediation_fails="x" * 30,
        )
    assert "at least ONE action" in str(exc.value)


# ── RemediationPlan — low-confidence-requires-risks invariant ─────────────


def test_low_confidence_without_risks_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        RemediationPlan(
            severity="P2",
            confidence="low",
            rollback_target="fraud-classifier-v2.2.7",
            rationale="x" * 50,
            rollback_plan_if_remediation_fails="x" * 30,
            # risks intentionally empty
        )
    assert "low" in str(exc.value) and "risks" in str(exc.value)


def test_low_confidence_with_risks_is_valid() -> None:
    p = RemediationPlan(
        severity="P2",
        confidence="low",
        rollback_target="fraud-classifier-v2.2.7",
        rationale="x" * 50,
        rollback_plan_if_remediation_fails="x" * 30,
        risks=["RootCause hypothesis is unverified; rollback may not address true cause."],
    )
    assert p.confidence == "low"


def test_high_confidence_pure_rollback_with_no_risks_is_valid() -> None:
    p = RemediationPlan(
        severity="P1",
        confidence="high",
        rollback_target="fraud-classifier-v2.2.7",
        rationale="x" * 50,
        rollback_plan_if_remediation_fails="x" * 30,
    )
    assert p.risks == []


# ── Rationale length floors ───────────────────────────────────────────────


def test_rationale_too_short_rejected() -> None:
    with pytest.raises(ValidationError):
        RemediationPlan(
            severity="P1",
            confidence="high",
            rollback_target="fraud-classifier-v2.2.7",
            rationale="short",
            rollback_plan_if_remediation_fails="x" * 30,
        )


# ── ActionItem ─────────────────────────────────────────────────────────────


def _valid_action_item(**overrides) -> ActionItem:
    base = dict(
        description="Add a synthetic FP-rate canary that pages within 5 min of breach.",
        owner_role="fraud-ml-team",
        severity="P2",
        due_within_days=14,
    )
    base.update(overrides)
    return ActionItem(**base)


def test_action_item_minimal_valid() -> None:
    item = _valid_action_item()
    assert item.owner_role == "fraud-ml-team"


def test_action_item_rejects_short_description() -> None:
    with pytest.raises(ValidationError):
        _valid_action_item(description="too short")


def test_action_item_rejects_due_zero_days() -> None:
    with pytest.raises(ValidationError):
        _valid_action_item(due_within_days=0)


def test_action_item_rejects_due_over_90_days() -> None:
    with pytest.raises(ValidationError):
        _valid_action_item(due_within_days=120)


# ── Postmortem ─────────────────────────────────────────────────────────────


def _valid_postmortem(**overrides) -> Postmortem:
    """Build a baseline valid Postmortem for tests; overrides exercise specific fields."""
    base = dict(
        title="Fraud-detection false-positive burst 2026-05-24",
        incident_id="fraud-fp-spike-20260524T204248Z",
        severity="P1",
        summary=(
            "Fraud classifier hit 3x baseline FP rate for ~90s at 20:42 UTC, blocking "
            "1247 legitimate transactions before rollback restored prior behavior."
        ),
        impact=(
            "1247 transactions blocked, 312 customer accounts frozen, ~$84k revenue at risk. "
            "No regulatory disclosure threshold breached."
        ),
        timeline=[
            "20:42 UTC — FP rate alert fires (3x baseline within 90s window).",
            "20:43 UTC — On-call paged; incident channel opened.",
            "20:48 UTC — Rollback to fraud-classifier-v2.2.7 initiated.",
            "20:51 UTC — FP rate returned to baseline; incident resolved.",
        ],
        root_cause=(
            "Prompt revision in fraud-classifier-v2.3.1 (deployed 20:24 UTC) introduced an "
            "overly broad pattern match that flagged routine merchant categories as fraud."
        ),
        detection="FP-rate canary tripped at +90s after threshold breach. Mean-time-to-detect ~2 min.",
        resolution=(
            "Rollback to v2.2.7 + added an eval guardrail (fp_rate_spike_5m) that would "
            "have detected this regression in pre-prod."
        ),
        action_items=[
            _valid_action_item().model_dump(),
        ],
        lessons_learned=[
            "Prompt-only changes to scoring models require the same pre-prod canary as model swaps."
        ],
    )
    base.update(overrides)
    return Postmortem(**base)


def test_postmortem_full_valid_construction() -> None:
    pm = _valid_postmortem()
    assert pm.severity == "P1"
    assert len(pm.timeline) == 4
    assert len(pm.action_items) == 1
    assert pm.action_items[0].owner_role == "fraud-ml-team"


def test_postmortem_rejects_too_few_timeline_entries() -> None:
    with pytest.raises(ValidationError):
        _valid_postmortem(timeline=["20:42 UTC — single entry, not enough"])


def test_postmortem_rejects_empty_timeline_entry() -> None:
    with pytest.raises(ValidationError) as exc:
        _valid_postmortem(timeline=["20:42 UTC — fine", "   "])
    assert "timeline contains empty entries" in str(exc.value)


def test_postmortem_rejects_zero_action_items() -> None:
    with pytest.raises(ValidationError):
        _valid_postmortem(action_items=[])


def test_postmortem_rejects_zero_lessons() -> None:
    with pytest.raises(ValidationError):
        _valid_postmortem(lessons_learned=[])


def test_postmortem_rejects_empty_lesson() -> None:
    with pytest.raises(ValidationError) as exc:
        _valid_postmortem(lessons_learned=["valid lesson", "  "])
    assert "lessons_learned contains empty entries" in str(exc.value)


def test_postmortem_rejects_stub_summary() -> None:
    with pytest.raises(ValidationError):
        _valid_postmortem(summary="too short")


def test_postmortem_required_sections_match_model_fields() -> None:
    """POSTMORTEM_REQUIRED_SECTIONS must equal Postmortem's declared fields."""
    model_fields = set(Postmortem.model_fields.keys())
    declared = set(POSTMORTEM_REQUIRED_SECTIONS)
    assert model_fields == declared, (
        f"drift between Postmortem model_fields {model_fields} and "
        f"POSTMORTEM_REQUIRED_SECTIONS {declared} — sync the tuple"
    )
