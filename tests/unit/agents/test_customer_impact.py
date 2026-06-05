"""Tests for the CustomerImpactQuantifier + ImpactReport schema (ADR-018).

Agent wiring is asserted statically (no live LLM calls). The schema is
exercised against both grounded reports (seed-derived, no caveats) and
the unhappy paths (missing seed → degraded confidence + required
caveats; invalid bounds → ValidationError). End-to-end orchestration is
covered separately in tests/unit/coordinator/.
"""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent
from pydantic import ValidationError

from sentinel.agents.customer_impact import customer_impact_quantifier
from sentinel.agents.schemas import ImpactReport, Postmortem
from sentinel.constants import SUBAGENT_MODEL


# ── Agent wiring ──────────────────────────────────────────────────────────


def test_customer_impact_is_llm_agent() -> None:
    assert isinstance(customer_impact_quantifier, LlmAgent)
    assert customer_impact_quantifier.name == "customer_impact_quantifier"


def test_customer_impact_uses_subagent_model() -> None:
    assert customer_impact_quantifier.model == SUBAGENT_MODEL


def test_customer_impact_has_no_tools() -> None:
    """The quantifier must reason from seed + payload only — tools would let it
    invent figures and bypass the audit-citation requirement.
    """
    assert (
        customer_impact_quantifier.tools == []
        or customer_impact_quantifier.tools is None
        or len(customer_impact_quantifier.tools) == 0
    )


def test_customer_impact_disallows_transfers() -> None:
    assert customer_impact_quantifier.disallow_transfer_to_parent is True
    assert customer_impact_quantifier.disallow_transfer_to_peers is True


# ── ImpactReport schema — happy path (seed-grounded) ─────────────────────


def _seed_grounded_report() -> dict:
    """Plausible seed-grounded ImpactReport for the fraud-fp-burst scenario."""
    return {
        "dollars_at_risk_usd": 84293.20,
        "customers_affected": 312,
        "transactions_affected": 1247,
        "estimated_revenue_loss_usd": 13668.18,
        "customer_trust_score_delta": -0.281,
        "audit_citation_lines": [
            "transactions_affected=1247 [source: scenario.impact_seed.affected_transactions]",
            "avg_transaction_usd=67.60 [source: scenario.impact_seed]",
            "dollars_at_risk_usd=84293.20 [source: derived: 1247 * 67.60]",
        ],
        "confidence": "seed_grounded",
        "caveats": [],
    }


def test_seed_grounded_report_validates() -> None:
    report = ImpactReport.model_validate(_seed_grounded_report())
    assert report.confidence == "seed_grounded"
    assert report.dollars_at_risk_usd > 0
    assert report.customers_affected > 0
    assert report.transactions_affected > 0
    assert report.audit_citation_lines  # required, non-empty
    # seed-grounded reports may legitimately have no caveats
    assert report.caveats == []


def test_audit_citations_required() -> None:
    """A report with empty audit_citation_lines is rejected at schema time."""
    bad = _seed_grounded_report()
    bad["audit_citation_lines"] = []
    with pytest.raises(ValidationError, match="audit_citation_lines"):
        ImpactReport.model_validate(bad)


def test_dollars_at_risk_must_be_non_negative() -> None:
    bad = _seed_grounded_report()
    bad["dollars_at_risk_usd"] = -1
    with pytest.raises(ValidationError):
        ImpactReport.model_validate(bad)


def test_trust_score_delta_clipped_to_unit_interval() -> None:
    bad = _seed_grounded_report()
    bad["customer_trust_score_delta"] = -1.5
    with pytest.raises(ValidationError):
        ImpactReport.model_validate(bad)
    bad["customer_trust_score_delta"] = 1.1
    with pytest.raises(ValidationError):
        ImpactReport.model_validate(bad)


# ── ImpactReport schema — unhappy path (missing seed / default caveat) ───


def test_default_caveat_confidence_requires_caveats() -> None:
    """When seed is empty, the agent must flag confidence=default_caveat AND
    include caveats. The schema rejects default_caveat with an empty caveats
    list — fail fast rather than ship a misleadingly-confident zero report.
    """
    bad = {
        "dollars_at_risk_usd": 0,
        "customers_affected": 0,
        "transactions_affected": 0,
        "estimated_revenue_loss_usd": 0,
        "customer_trust_score_delta": 0,
        "audit_citation_lines": ["no seed data; defaults to zeros"],
        "confidence": "default_caveat",
        "caveats": [],  # ← missing; should reject
    }
    with pytest.raises(ValidationError, match="caveat"):
        ImpactReport.model_validate(bad)


def test_default_caveat_with_caveats_validates() -> None:
    """The graceful unhappy-path: zeros + explicit caveats + at least one
    audit-citation line explaining why we're zero — accepted.
    """
    ok = {
        "dollars_at_risk_usd": 0,
        "customers_affected": 0,
        "transactions_affected": 0,
        "estimated_revenue_loss_usd": 0,
        "customer_trust_score_delta": 0,
        "audit_citation_lines": [
            "scenario.impact_seed=<empty>; quantification not possible"
        ],
        "confidence": "default_caveat",
        "caveats": [
            "Scenario impact_seed was empty; figures default to zero pending "
            "seed authoring. Quantification will activate once the scenario "
            "carries avg_transaction_usd, affected_customers, etc.",
        ],
    }
    report = ImpactReport.model_validate(ok)
    assert report.confidence == "default_caveat"
    assert report.dollars_at_risk_usd == 0
    assert len(report.caveats) >= 1


def test_scenario_inferred_confidence_also_requires_caveats() -> None:
    """``scenario_inferred`` (derived from alert payload only) still must
    surface caveats explaining the limited grounding.
    """
    bad = _seed_grounded_report()
    bad["confidence"] = "scenario_inferred"
    bad["caveats"] = []
    with pytest.raises(ValidationError, match="caveat"):
        ImpactReport.model_validate(bad)


# ── Postmortem integration: optional impact_quantified field ─────────────


def _valid_postmortem_dict() -> dict:
    """Minimal valid Postmortem used by the integration test below."""
    return {
        "title": "Fraud false-positive burst 2026-05-24",
        "incident_id": "fraud-fp-spike-20260524T204248Z",
        "severity": "P1",
        "summary": (
            "A 90-second spike in false-positive fraud classifications "
            "blocked 1247 legitimate transactions across 312 customer "
            "accounts before automated rollback engaged."
        ),
        "impact": (
            "1247 legitimate transactions declined, 312 accounts frozen, "
            "~$84,293 USD at risk over a 90-second window."
        ),
        "timeline": [
            "20:42 UTC — fp_rate_5m breach detected",
            "20:43 UTC — rollback initiated; baseline restored",
        ],
        "root_cause": (
            "A 18-minute-old deploy of fraud-classifier-v2.3.1 increased "
            "false-positive rate from baseline 7.2% to peak 21.3%."
        ),
        "detection": (
            "fp_rate_5m monitor breached at 20:42:48 UTC, 12s after onset."
        ),
        "resolution": (
            "Rollback to fraud-classifier-v2.2.7 within 60s; FP rate "
            "returned to baseline within 5 minutes."
        ),
        "action_items": [
            {
                "description": (
                    "Add fp_rate canary gate to fraud-classifier deploy "
                    "pipeline so a 50%-burst is auto-rolled back pre-prod."
                ),
                "owner_role": "fraud-ml-team",
                "severity": "P1",
                "due_within_days": 7,
            }
        ],
        "lessons_learned": [
            "Auto-rollback on classification-rate deviation is effective; "
            "tighten the deviation threshold from 50% to 30%.",
        ],
    }


def test_postmortem_accepts_impact_quantified_field() -> None:
    """A postmortem with the new optional impact_quantified block validates."""
    base = _valid_postmortem_dict()
    base["impact_quantified"] = _seed_grounded_report()
    pm = Postmortem.model_validate(base)
    assert pm.impact_quantified is not None
    assert pm.impact_quantified.dollars_at_risk_usd > 0
    assert pm.impact_quantified.audit_citation_lines


def test_postmortem_without_impact_quantified_still_validates() -> None:
    """Backwards-compatibility — pre-Phase-8 postmortems still validate."""
    pm = Postmortem.model_validate(_valid_postmortem_dict())
    assert pm.impact_quantified is None


# ── Scenario seed sanity ─────────────────────────────────────────────────


def test_every_scenario_carries_an_impact_seed() -> None:
    """Each shipped scenario must declare an impact_seed so the quantifier
    can ground figures. An empty seed is acceptable (the agent will emit
    a default_caveat report), but the attribute must exist.
    """
    from sentinel.scenarios import SCENARIOS

    for scenario in SCENARIOS:
        assert hasattr(scenario, "impact_seed"), scenario.id
        assert isinstance(scenario.impact_seed, dict), scenario.id


def test_fraud_scenario_seed_carries_expected_primitives() -> None:
    """The fraud scenario should ground at least transaction count + avg
    transaction value so dollars_at_risk_usd can be derived.
    """
    from sentinel.scenarios import get_scenario

    s = get_scenario("fraud-fp-burst")
    assert "affected_transactions" in s.impact_seed
    assert "avg_transaction_usd" in s.impact_seed
    assert "affected_customers" in s.impact_seed
    assert s.impact_seed["affected_transactions"] > 0
    assert s.impact_seed["avg_transaction_usd"] > 0
