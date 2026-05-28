"""End-to-end against real Vertex. GATED on RUN_INTEGRATION_TESTS=1.

Runs the fraud-fp-burst scenario through the real coordinator, real Phoenix
seed, real Gemini agents. ~$0.10 per run. Treat as release-gate.

Mirrors the gating pattern of tests/integration/test_plan_determinism.py.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="Real Vertex integration tests require RUN_INTEGRATION_TESTS=1",
)


@pytest.mark.asyncio
async def test_real_fraud_pipeline_produces_validated_postmortem() -> None:
    """Drive the fraud scenario through the real coordinator + Gemini + Phoenix."""
    from sentinel.coordinator import run_end_to_end_scenario
    from sentinel.scenarios import get_scenario

    scenario = get_scenario("fraud-fp-burst")
    result = await run_end_to_end_scenario(scenario)

    # Pipeline succeeded
    assert result.succeeded, f"pipeline failed: {result.error}"

    # Postmortem extracted + validated
    assert result.postmortem is not None
    assert result.postmortem.severity == "P1"

    # The grounding test: postmortem references "electronics" (the seeded
    # error category from incident_sim's fraud seeder)
    text_blob = " ".join([
        result.postmortem.summary,
        result.postmortem.impact,
        result.postmortem.root_cause,
    ]).lower()
    assert "electronics" in text_blob, (
        f"postmortem failed to ground in seeded error category. "
        f"summary={result.postmortem.summary!r}"
    )

    # Completeness scored
    assert result.completeness is not None
    assert result.completeness.score >= 0.8, (
        f"completeness too low: {result.completeness.score}"
    )

    # Seed summary present
    assert result.seed_summary is not None
    assert result.seed_summary.project == "fraud-detector-prod"
    assert result.seed_summary.n_error == 12
