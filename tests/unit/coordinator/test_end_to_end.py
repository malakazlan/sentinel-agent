"""Tests for ``run_end_to_end_scenario`` orchestrator.

Verifies stage chaining, postmortem extraction + Pydantic validation,
completeness scoring hookup, and error propagation. ``stream_coordinator_with_chain``
is patched to return canned records so these run fast and without LLM cost.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from sentinel.coordinator import (
    EndToEndResult,
    StageResult,
    _extract_postmortem_json,
    run_end_to_end_scenario,
)
from sentinel.scenarios import SCENARIOS, get_scenario
from tests.unit.agents.test_schemas import _valid_postmortem  # type: ignore


# ── _extract_postmortem_json ──────────────────────────────────────────────


def test_extract_postmortem_from_fenced_json() -> None:
    text = 'preamble\n```json\n{"a": 1, "b": [2, 3]}\n```\nepilogue'
    out = _extract_postmortem_json(text)
    assert out == {"a": 1, "b": [2, 3]}


def test_extract_postmortem_falls_back_to_unfenced_object() -> None:
    text = 'no fence, just object: {"a": 1}'
    out = _extract_postmortem_json(text)
    assert out == {"a": 1}


def test_extract_postmortem_returns_none_on_no_json() -> None:
    assert _extract_postmortem_json("plain prose with no braces at all") is None


def test_extract_postmortem_returns_none_on_invalid_json() -> None:
    text = '```json\n{"broken": malformed}\n```'
    assert _extract_postmortem_json(text) is None


# ── run_end_to_end_scenario ────────────────────────────────────────────────


def _final_record(text: str, author: str = "trace_analyzer") -> dict:
    return {"kind": "final", "author": author, "text": text}


def _make_canned_stream(
    prompt_to_text: dict[str, tuple[str, str]],
):
    """Build a fake ``stream_coordinator_with_chain`` keyed by prompt prefix.

    Each value is ``(author, final_text)``. Yields one tool_call record and
    one final record per stage so the StageResult has plausible structure.
    """

    async def fake(user_text: str, **_kwargs):
        # Accept arbitrary kwargs (alert_payload) the orchestrator now passes.
        for prefix, (author, final_text) in prompt_to_text.items():
            if prefix in user_text:
                yield {"kind": "tool_call", "author": "coordinator",
                       "tool": "transfer_to_agent", "args": {"agent_name": author}}
                yield _final_record(final_text, author=author)
                return
        # Default: empty stream
        return

    return fake


@pytest.mark.asyncio
async def test_full_pipeline_succeeds_with_valid_postmortem_json() -> None:
    """Happy path: 6 main stages + 1 critic stage (ADR-016 refinement loop).

    The chain now runs investigate → eval_fanout → deploy_correlation →
    root_cause → remediation → postmortem (Phase 7 / ADR-012 + ADR-014),
    plus the critic on the first iteration (which we make accept on first
    pass via canned stream).
    """
    scenario = get_scenario("fraud-fp-burst")
    valid_pm = _valid_postmortem().model_dump()
    pm_text = "```json\n" + json.dumps(valid_pm) + "\n```"

    # Critic returns an "accept" verdict so the loop terminates on the first
    # iteration without a revision.
    critic_text = (
        '```json\n{"score": 0.9, "rubric_scores": {"completeness": 0.9, '
        '"grounding": 0.9, "actionability": 0.9, "customer_impact": 0.9}, '
        '"critique": "Postmortem is grounded and actionable; no revisions '
        'required for this draft.", "gaps_by_section": {}, "accept": true}'
        "\n```"
    )

    # Canned ImpactReport for the new Phase 8 customer_impact stage.
    impact_text = (
        '```json\n{"dollars_at_risk_usd": 84293.20, "customers_affected": 312, '
        '"transactions_affected": 1247, "estimated_revenue_loss_usd": 13668.18, '
        '"customer_trust_score_delta": -0.281, "audit_citation_lines": '
        '["transactions_affected=1247 [source: scenario.impact_seed.affected_transactions]"], '
        '"confidence": "seed_grounded", "caveats": []}\n```'
    )

    # Canned ComplianceReport stub — single grounded citation, no
    # obligations. The guard happens to pass it through because the
    # mocked search registers the cite; for this happy-path test we
    # actually expect the unhappy-path downgrade since we don't run
    # search_regulations through the mock. Either way, the stage runs.
    compliance_text = (
        '```json\n{"incident_id": "fraud-fp-spike-20260524T204248Z", '
        '"citations": [], "reporting_obligations": [], '
        '"no_applicable_regulations": true, '
        '"generic_guidance": "no specific regulation matched in this stub run"}\n```'
    )

    fake = _make_canned_stream(
        {
            "Investigate this incident": ("trace_analyzer", "Recent traces: 5 ERROR, 20 OK..."),
            "fan out the full evaluation suite": (
                "parallel_eval_runner",
                "**Faithfulness:** clean | **Drift:** stable | **Prompt-injection:** clean | **Toxicity:** clean",
            ),
            "Correlate this incident with recent deploys": (
                "deploy_correlator",
                "**Window:** last 24h | **Repo:** acme/fraud-detector | **Candidates:** none above threshold.",
            ),
            "hypothesize the root cause": ("root_cause", "1. Prompt regression (confidence: high)"),
            "draft a remediation plan": ("remediation", '{"severity":"P1","confidence":"high"}'),
            "quantify the customer + financial impact": (
                "customer_impact_quantifier",
                impact_text,
            ),
            "write the postmortem": ("postmortem", pm_text),
            "Score this postmortem against the four-dimension rubric": (
                "critic",
                critic_text,
            ),
            "identify the regulatory exposure": (
                "compliance_officer",
                compliance_text,
            ),
        }
    )

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=fake):
        result = await run_end_to_end_scenario(scenario)

    assert result.scenario_id == "fraud-fp-burst"
    # 7 main stages (Phase 8 / ADR-018 added customer_impact) + 1 critic
    # iteration (accepted on first pass) + 1 compliance stage (ADR-019).
    assert len(result.stages) == 9
    assert [s.name for s in result.stages] == [
        "investigate",
        "eval_fanout",
        "deploy_correlation",
        "root_cause",
        "remediation",
        "customer_impact",
        "postmortem",
        "critic_iteration_1",
        "compliance",
    ]
    assert result.error is None
    assert result.succeeded is True
    assert result.postmortem is not None
    assert result.completeness is not None
    assert result.completeness.score > 0


@pytest.mark.asyncio
async def test_pipeline_reports_unparseable_postmortem_as_error() -> None:
    """Postmortem stage produces text with no JSON block → error captured."""
    scenario = get_scenario("kyc-sanctions-hallucination")
    fake = _make_canned_stream(
        {
            "Investigate this incident": ("trace_analyzer", "traces"),
            "hypothesize the root cause": ("root_cause", "hypotheses"),
            "draft a remediation plan": ("remediation", "plan"),
            "write the postmortem": ("postmortem", "I am sorry I cannot do that"),
        }
    )

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=fake):
        result = await run_end_to_end_scenario(scenario)

    assert result.postmortem is None
    assert result.completeness is None
    assert result.error is not None
    assert "no parseable JSON" in result.error
    assert result.succeeded is False


@pytest.mark.asyncio
async def test_pipeline_reports_schema_failure_as_error() -> None:
    """Postmortem stage produces parseable JSON that violates the schema → error."""
    scenario = get_scenario("lending-latency-regression")
    bad_pm = {"title": "short", "severity": "P1"}  # missing required fields
    pm_text = "```json\n" + json.dumps(bad_pm) + "\n```"
    fake = _make_canned_stream(
        {
            "Investigate this incident": ("trace_analyzer", "x"),
            "hypothesize the root cause": ("root_cause", "x"),
            "draft a remediation plan": ("remediation", "x"),
            "write the postmortem": ("postmortem", pm_text),
        }
    )

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=fake):
        result = await run_end_to_end_scenario(scenario)

    assert result.postmortem is None
    assert result.error is not None
    assert "schema validation" in result.error
    assert result.succeeded is False


@pytest.mark.asyncio
async def test_pipeline_aborts_on_mid_stage_exception() -> None:
    """If a stage raises, the orchestrator captures the error and stops."""
    scenario = get_scenario("fraud-fp-burst")

    async def crashing_stream(user_text: str, **_kwargs):
        if "hypothesize" in user_text:
            raise RuntimeError("simulated mid-stage failure")
        yield _final_record("ok", author="coordinator")

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=crashing_stream):
        result = await run_end_to_end_scenario(scenario)

    # Three stages completed (investigate, eval_fanout, deploy_correlation);
    # root_cause failed → orchestrator aborts.
    assert len(result.stages) == 3
    assert result.error is not None
    assert "root_cause" in result.error
    assert "simulated mid-stage failure" in result.error
    assert result.succeeded is False


@pytest.mark.asyncio
async def test_stages_capture_records_and_authors() -> None:
    """StageResult.records and .authors are populated from the stream."""
    scenario = SCENARIOS[0]
    valid_pm = _valid_postmortem().model_dump()
    pm_text = "```json\n" + json.dumps(valid_pm) + "\n```"
    fake = _make_canned_stream(
        {
            "Investigate this incident": ("trace_analyzer", "x"),
            "hypothesize the root cause": ("root_cause", "x"),
            "draft a remediation plan": ("remediation", "x"),
            "write the postmortem": ("postmortem", pm_text),
        }
    )

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=fake):
        result = await run_end_to_end_scenario(scenario)

    stage0 = result.stages[0]
    assert isinstance(stage0, StageResult)
    # Our canned stream yields tool_call + final per stage = 2 records
    assert len(stage0.records) == 2
    assert "coordinator" in stage0.authors
    assert "trace_analyzer" in stage0.authors
