"""Schema and validator tests for cross-agent contracts.

Production-shaped schemas — the validators here are load-bearing for real
ops consumers (PagerDuty / Linear / SRE templates). Bad data must fail at
construction time, not silently corrupt a downstream system.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.agents.schemas import EvalGuardrail, RemediationPlan


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
