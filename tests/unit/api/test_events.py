"""Tests for the IncidentEvent discriminated union — the wire schema
between the FastAPI backend and the Next.js frontend. Drift here means
the frontend's TypeScript mirror breaks; these tests are the contract."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from sentinel.api.events import (
    IncidentEvent,
    IncidentStartedEvent,
    SeedCompletedEvent,
    StageStartedEvent,
    StageCompletedEvent,
    PostmortemValidatedEvent,
    IncidentCompletedEvent,
    IncidentFailedEvent,
)


def test_incident_started_round_trips_through_json() -> None:
    ev = IncidentStartedEvent(
        incident_id="fraud-fp-spike-20260526T133012Z",
        elapsed_ms=0,
        scenario_id="fraud-fp-burst",
        severity="P1",
        title="False-positive burst on transaction classifier",
        watched_project="fraud-detector-prod",
    )
    payload = ev.model_dump_json()
    parsed = IncidentEvent.model_validate_json(payload)
    assert parsed == ev
    assert parsed.type == "incident_started"


def test_stage_started_uses_stage_literal() -> None:
    ev = StageStartedEvent(
        incident_id="x",
        elapsed_ms=4200,
        stage="investigate",
        prompt_preview="Production incident alert received...",
    )
    assert ev.type == "stage_started"
    # only the four real stages should validate
    with pytest.raises(ValidationError):
        StageStartedEvent(
            incident_id="x",
            elapsed_ms=0,
            stage="not-a-stage",  # type: ignore[arg-type]
            prompt_preview="...",
        )


def test_stage_completed_carries_authors_and_final_text() -> None:
    ev = StageCompletedEvent(
        incident_id="x",
        elapsed_ms=62300,
        stage="investigate",
        latency_ms=58100,
        authors=["coordinator", "trace_analyzer"],
        final_text="The analysis of the last 60 minutes...",
    )
    assert ev.type == "stage_completed"
    assert ev.authors == ["coordinator", "trace_analyzer"]


def test_postmortem_validated_carries_completeness() -> None:
    ev = PostmortemValidatedEvent(
        incident_id="x",
        elapsed_ms=254000,
        completeness_score=1.0,
        completeness_label="complete",
        postmortem_json='{"title":"...","severity":"P1"}',
    )
    assert ev.type == "postmortem_validated"
    assert 0.0 <= ev.completeness_score <= 1.0


def test_incident_event_discriminator_routes_to_right_subclass() -> None:
    """The frontend dispatches on `type`; this verifies the discriminator works."""
    raw = json.dumps({
        "type": "stage_completed",
        "incident_id": "x",
        "elapsed_ms": 1000,
        "stage": "remediation",
        "latency_ms": 500,
        "authors": ["coordinator", "remediation"],
        "final_text": "...",
    })
    parsed = IncidentEvent.model_validate_json(raw)
    assert isinstance(parsed, StageCompletedEvent)


def test_incident_failed_carries_error() -> None:
    ev = IncidentFailedEvent(
        incident_id="x",
        elapsed_ms=5000,
        error="Phoenix unreachable: ConnectionError",
    )
    assert ev.type == "incident_failed"


def test_completeness_score_bounded() -> None:
    with pytest.raises(ValidationError):
        PostmortemValidatedEvent(
            incident_id="x",
            elapsed_ms=0,
            completeness_score=1.5,  # > 1.0
            completeness_label="complete",
            postmortem_json="{}",
        )
