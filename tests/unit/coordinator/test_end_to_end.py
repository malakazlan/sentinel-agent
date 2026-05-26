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

    async def fake(user_text: str):
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
    """Happy path: 4 stages run, postmortem stage produces valid JSON."""
    scenario = get_scenario("fraud-fp-burst")
    valid_pm = _valid_postmortem().model_dump()
    pm_text = "```json\n" + json.dumps(valid_pm) + "\n```"

    fake = _make_canned_stream(
        {
            "Investigate this incident": ("trace_analyzer", "Recent traces: 5 ERROR, 20 OK..."),
            "hypothesize the root cause": ("root_cause", "1. Prompt regression (confidence: high)"),
            "draft a remediation plan": ("remediation", '{"severity":"P1","confidence":"high"}'),
            "write the postmortem": ("postmortem", pm_text),
        }
    )

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=fake):
        result = await run_end_to_end_scenario(scenario)

    assert result.scenario_id == "fraud-fp-burst"
    assert len(result.stages) == 4
    assert [s.name for s in result.stages] == [
        "investigate",
        "root_cause",
        "remediation",
        "postmortem",
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

    async def crashing_stream(user_text: str):
        if "hypothesize" in user_text:
            raise RuntimeError("simulated mid-stage failure")
        yield _final_record("ok", author="coordinator")

    with patch("sentinel.coordinator.stream_coordinator_with_chain", side_effect=crashing_stream):
        result = await run_end_to_end_scenario(scenario)

    # First stage completed; second stage failed
    assert len(result.stages) == 1
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
