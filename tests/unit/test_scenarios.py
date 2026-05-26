"""Tests for the scripted incident scenarios used in the end-to-end pipeline.

Pure data tests — no LLM, no Phoenix. Verify each scenario is well-formed
and the helpers work as documented.
"""

from __future__ import annotations

import json

import pytest

from sentinel.agents.schemas import Severity
from sentinel.scenarios import SCENARIOS, IncidentScenario, get_scenario


def test_three_scenarios_shipped() -> None:
    """CLAUDE.md §8 Phase 4 step 5 specifies three end-to-end scenarios."""
    assert len(SCENARIOS) == 3
    ids = {s.id for s in SCENARIOS}
    assert ids == {
        "fraud-fp-burst",
        "kyc-sanctions-hallucination",
        "lending-latency-regression",
    }


def test_scenarios_have_unique_ids() -> None:
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))


def test_scenarios_have_unique_alert_ids() -> None:
    """alert_id is what Phoenix annotates against — must be unique."""
    alert_ids = [s.alert_payload["alert_id"] for s in SCENARIOS]
    assert len(alert_ids) == len(set(alert_ids))


def test_every_scenario_has_required_payload_keys() -> None:
    """Each scenario's payload must shape like a real alerting webhook."""
    required = {"alert_id", "source", "alert_type", "severity"}
    for s in SCENARIOS:
        missing = required - s.alert_payload.keys()
        assert not missing, f"scenario {s.id!r} missing payload keys: {missing}"


def test_payload_severity_matches_scenario_severity() -> None:
    """Sanity: alert payload severity must match the scenario's declared severity."""
    for s in SCENARIOS:
        assert s.alert_payload["severity"] == s.severity, (
            f"scenario {s.id!r}: payload severity={s.alert_payload['severity']!r} "
            f"!= scenario severity={s.severity!r}"
        )


def test_severity_values_are_in_canonical_set() -> None:
    """Severity must be one of the Severity Literal values."""
    valid: set[Severity] = {"P0", "P1", "P2", "P3"}
    for s in SCENARIOS:
        assert s.severity in valid


def test_incident_id_returns_alert_id() -> None:
    s = SCENARIOS[0]
    assert s.incident_id == s.alert_payload["alert_id"]


def test_initial_prompt_contains_serialized_payload() -> None:
    s = SCENARIOS[0]
    prompt = s.initial_prompt()
    assert "```json" in prompt
    assert s.alert_payload["alert_id"] in prompt
    # Round-trip the embedded JSON to make sure it's valid
    start = prompt.find("```json\n") + len("```json\n")
    end = prompt.find("\n```", start)
    parsed = json.loads(prompt[start:end])
    assert parsed["alert_id"] == s.alert_payload["alert_id"]


def test_get_scenario_returns_matching_scenario() -> None:
    s = get_scenario("fraud-fp-burst")
    assert isinstance(s, IncidentScenario)
    assert s.id == "fraud-fp-burst"


def test_get_scenario_raises_on_unknown_id() -> None:
    with pytest.raises(KeyError, match="unknown scenario id"):
        get_scenario("not-a-real-id")


def test_scenarios_cover_three_distinct_finserv_workflows() -> None:
    """Per 00-mission.md: fraud detection, KYC/AML, lending."""
    workflows = {s.workflow for s in SCENARIOS}
    assert workflows == {"fraud detection", "KYC/AML screening", "lending / credit underwriting"}


def test_scenarios_are_immutable() -> None:
    """frozen=True dataclass — protects against accidental in-place edits."""
    s = SCENARIOS[0]
    with pytest.raises(AttributeError):
        s.id = "tampered"  # type: ignore[misc]
