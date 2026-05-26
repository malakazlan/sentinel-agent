"""run_end_to_end_scenario(on_event=callback) — verify the callback fires
in the right order at stage boundaries and gets the right payloads.

This is the seam the FastAPI SSE endpoint uses; if the order or fields
drift, the frontend's stepper will desync.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.api.events import (
    IncidentCompletedEvent,
    IncidentFailedEvent,
    IncidentStartedEvent,
    PostmortemValidatedEvent,
    SeedCompletedEvent,
    StageCompletedEvent,
    StageStartedEvent,
)
from sentinel.coordinator import StageResult, run_end_to_end_scenario
from sentinel.scenarios import get_scenario
from sentinel.tools.incident_sim import SeedSummary


def _stub_stage_factory() -> Any:
    """Return an async fn that produces a canned StageResult per call.

    Each invocation tags the StageResult with the requested stage name so
    the test can verify ordering against the emitted events.
    """

    async def fake_run_stage(name: str, prompt: str) -> StageResult:
        return StageResult(
            name=name,
            prompt=prompt,
            records=[{"kind": "final", "author": "coordinator", "text": "ok"}],
            final_text="stub final text",
            latency_ms=10,
        )

    return fake_run_stage


@pytest.mark.asyncio
async def test_on_event_callback_fires_lifecycle_in_order() -> None:
    """The callback receives events in the lifecycle order — and only
    once each at the right stage boundaries."""
    events: list[Any] = []

    async def capture(ev: Any) -> None:
        events.append(ev)

    # Patch the heavy parts — we're testing the event emission contract,
    # not the actual pipeline. seed_scenario and _run_stage are mocked
    # to return canned results so the test runs in milliseconds.
    with (
        patch("sentinel.coordinator.seed_scenario") as mock_seed,
        patch(
            "sentinel.coordinator._run_stage",
            side_effect=_stub_stage_factory(),
        ),
        patch("sentinel.coordinator._extract_postmortem_json") as mock_extract,
    ):
        mock_seed.return_value = SeedSummary(
            project="fraud-detector-prod",
            spans_written=42,
            n_ok=30,
            n_error=12,
        )
        # Returning None from extract makes postmortem validation skip the
        # success branch — we still want incident_completed at the end.
        mock_extract.return_value = None

        scenario = get_scenario("fraud-fp-burst")
        result = await run_end_to_end_scenario(scenario, on_event=capture)
        # The postmortem couldn't validate (we made extract return None),
        # but the lifecycle still emits all stage events and the terminal
        # incident_completed — that's what we're asserting here.
        assert result is not None

    # First event: incident_started carries scenario metadata.
    assert isinstance(events[0], IncidentStartedEvent)
    assert events[0].scenario_id == "fraud-fp-burst"
    assert events[0].severity == "P1"
    assert events[0].title.startswith("Fraud detection")
    assert events[0].watched_project == "fraud-detector-prod"

    # Second event: seed_completed carries SeedSummary fields.
    assert isinstance(events[1], SeedCompletedEvent)
    assert events[1].project == "fraud-detector-prod"
    assert events[1].spans_written == 42
    assert events[1].n_ok == 30
    assert events[1].n_error == 12

    # 4 stages × (started, completed) = 8 stage events, in order.
    stage_events = [
        e for e in events if isinstance(e, (StageStartedEvent, StageCompletedEvent))
    ]
    assert len(stage_events) == 8
    expected_stages = ["investigate", "root_cause", "remediation", "postmortem"]
    for i, stage in enumerate(expected_stages):
        assert isinstance(stage_events[i * 2], StageStartedEvent)
        assert stage_events[i * 2].stage == stage
        assert isinstance(stage_events[i * 2 + 1], StageCompletedEvent)
        assert stage_events[i * 2 + 1].stage == stage
        assert stage_events[i * 2 + 1].latency_ms >= 0
        assert "coordinator" in stage_events[i * 2 + 1].authors
        assert stage_events[i * 2 + 1].final_text == "stub final text"

    # The terminal event is incident_completed.
    assert isinstance(events[-1], IncidentCompletedEvent)
    assert events[-1].total_latency_ms >= 0


@pytest.mark.asyncio
async def test_on_event_emits_postmortem_validated_when_postmortem_parses() -> None:
    """When the postmortem stage produces valid JSON, the callback also
    receives a PostmortemValidatedEvent before incident_completed."""
    from tests.unit.agents.test_schemas import _valid_postmortem  # type: ignore

    events: list[Any] = []

    async def capture(ev: Any) -> None:
        events.append(ev)

    valid_pm_dict = _valid_postmortem().model_dump()

    with (
        patch("sentinel.coordinator.seed_scenario") as mock_seed,
        patch(
            "sentinel.coordinator._run_stage",
            side_effect=_stub_stage_factory(),
        ),
        patch("sentinel.coordinator._extract_postmortem_json") as mock_extract,
    ):
        mock_seed.return_value = SeedSummary(
            project="fraud-detector-prod", spans_written=1, n_ok=1, n_error=0
        )
        mock_extract.return_value = valid_pm_dict

        scenario = get_scenario("fraud-fp-burst")
        result = await run_end_to_end_scenario(scenario, on_event=capture)
        assert result.succeeded

    validated = [e for e in events if isinstance(e, PostmortemValidatedEvent)]
    assert len(validated) == 1
    assert 0.0 <= validated[0].completeness_score <= 1.0
    assert validated[0].completeness_label
    assert validated[0].postmortem_json  # non-empty JSON string

    # Order: postmortem_validated must come before incident_completed.
    idx_validated = events.index(validated[0])
    idx_completed = next(
        i for i, e in enumerate(events) if isinstance(e, IncidentCompletedEvent)
    )
    assert idx_validated < idx_completed


@pytest.mark.asyncio
async def test_no_callback_means_no_emission_no_crash() -> None:
    """Existing call sites that don't pass `on_event` still work — the
    function is backward-compatible."""
    with (
        patch("sentinel.coordinator.seed_scenario") as mock_seed,
        patch(
            "sentinel.coordinator._run_stage",
            side_effect=_stub_stage_factory(),
        ),
        patch("sentinel.coordinator._extract_postmortem_json") as mock_extract,
    ):
        mock_seed.return_value = SeedSummary(
            project="x", spans_written=1, n_ok=1, n_error=0
        )
        mock_extract.return_value = None

        scenario = get_scenario("fraud-fp-burst")
        result = await run_end_to_end_scenario(scenario)  # no on_event
        assert result is not None
        # Four stages still ran.
        assert [s.name for s in result.stages] == [
            "investigate",
            "root_cause",
            "remediation",
            "postmortem",
        ]


@pytest.mark.asyncio
async def test_callback_failure_fires_incident_failed_then_captured() -> None:
    """If something raises mid-pipeline (here: during seeding), the
    callback receives IncidentFailedEvent. The orchestrator already
    captures seeding errors into ``result.error`` rather than reraising,
    so we verify the failure event was emitted before the function
    returned its error result."""
    events: list[Any] = []

    async def capture(ev: Any) -> None:
        events.append(ev)

    with patch(
        "sentinel.coordinator.seed_scenario", side_effect=RuntimeError("boom")
    ):
        scenario = get_scenario("fraud-fp-burst")
        result = await run_end_to_end_scenario(scenario, on_event=capture)

    # incident_started fired first, then incident_failed before the abort.
    assert isinstance(events[0], IncidentStartedEvent)
    failed = [e for e in events if isinstance(e, IncidentFailedEvent)]
    assert len(failed) == 1
    assert "boom" in failed[0].error
    assert "RuntimeError" in failed[0].error

    # Existing contract: seeding errors are captured into result.error.
    assert result.error is not None
    assert "boom" in result.error


@pytest.mark.asyncio
async def test_on_event_uses_explicit_incident_id_when_provided() -> None:
    """The API layer passes a unique registry id; events must carry it,
    not scenario.incident_id (the deterministic alert_id)."""
    events: list[Any] = []

    async def capture(ev: Any) -> None:
        events.append(ev)

    with (
        patch("sentinel.coordinator.seed_scenario") as mock_seed,
        patch("sentinel.coordinator._run_stage") as mock_run_stage,
        patch("sentinel.coordinator._extract_postmortem_json") as mock_extract,
        patch("sentinel.coordinator.completeness_score") as mock_completeness,
    ):
        from sentinel.tools.incident_sim import SeedSummary
        from sentinel.coordinator import StageResult
        mock_seed.return_value = SeedSummary(
            project="x", spans_written=1, n_ok=1, n_error=0
        )
        mock_run_stage.return_value = StageResult(
            name="stub",
            prompt="...",
            records=[{"kind": "final", "author": "coordinator", "text": "..."}],
            final_text="...",
            latency_ms=10,
        )
        mock_extract.return_value = None
        mock_completeness.return_value = None

        scenario = get_scenario("fraud-fp-burst")
        custom_id = "fraud-fp-spike-20260524T204248Z-abcd1234"
        await run_end_to_end_scenario(scenario, on_event=capture, incident_id=custom_id)

    # EVERY event must carry the explicit incident_id, not scenario.incident_id
    for ev in events:
        assert ev.incident_id == custom_id, f"event {type(ev).__name__} has incident_id={ev.incident_id!r}, expected {custom_id!r}"


@pytest.mark.asyncio
async def test_callback_failure_during_stage_fires_incident_failed() -> None:
    """If a stage raises mid-pipeline, the callback receives
    IncidentFailedEvent before the orchestrator returns its error result."""
    events: list[Any] = []

    async def capture(ev: Any) -> None:
        events.append(ev)

    async def crashing_stage(name: str, prompt: str) -> StageResult:
        if name == "root_cause":
            raise RuntimeError("stage boom")
        return StageResult(
            name=name,
            prompt=prompt,
            records=[{"kind": "final", "author": "coordinator", "text": "ok"}],
            final_text="ok",
            latency_ms=1,
        )

    with (
        patch("sentinel.coordinator.seed_scenario") as mock_seed,
        patch("sentinel.coordinator._run_stage", side_effect=crashing_stage),
    ):
        mock_seed.return_value = SeedSummary(
            project="x", spans_written=1, n_ok=1, n_error=0
        )
        scenario = get_scenario("fraud-fp-burst")
        result = await run_end_to_end_scenario(scenario, on_event=capture)

    # The investigate stage's started+completed both fired, then root_cause
    # started fired, then failure.
    failed = [e for e in events if isinstance(e, IncidentFailedEvent)]
    assert len(failed) == 1
    assert "stage boom" in failed[0].error
    assert result.error is not None
    assert "root_cause" in result.error
