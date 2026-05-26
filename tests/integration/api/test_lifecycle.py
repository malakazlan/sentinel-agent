"""End-to-end API lifecycle: POST /incidents → SSE → GET /incidents/{id}.

This test mocks the heavy ADK pipeline so it runs fast and offline. It
verifies the API contract from the frontend's perspective: every event
type fires in order, the final GET returns the validated postmortem.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel.api.main import create_app


@pytest.mark.asyncio
async def test_full_lifecycle_post_stream_get() -> None:
    """Drive a full incident through the API using a mocked pipeline."""
    from sentinel.coordinator import EndToEndResult
    from sentinel.tools.incident_sim import SeedSummary
    from sentinel.agents.schemas import Postmortem, ActionItem

    pm = Postmortem(
        title="Lifecycle test postmortem for grounded electronics FPs",
        incident_id="lifecycle-test",
        severity="P1",
        summary="A spike in false positives for electronics merchant category transactions caused legitimate retail purchases to be blocked.",
        impact="12 legitimate transactions blocked between 13:16 and 13:21 UTC.",
        timeline=["13:16 UTC — onset", "13:21 UTC — last false positive observed"],
        root_cause="Over-sensitive thresholding for electronics merchant category transactions above $800.",
        detection="Discovered via post-hoc verification logs comparing model output to verified labels.",
        resolution="Investigation in progress; rollback being evaluated.",
        action_items=[ActionItem(description="Investigate model sensitivity to electronics", owner_role="fraud-ml-team", severity="P1", due_within_days=7)],
        lessons_learned=["High-confidence scores can be misleading during drift events."],
    )

    async def fake_pipeline(scenario, *, on_event=None, incident_id=None):
        from sentinel.api.events import (
            IncidentCompletedEvent, IncidentStartedEvent,
            PostmortemValidatedEvent, SeedCompletedEvent,
            StageCompletedEvent, StageStartedEvent,
        )
        # Mirror the production behavior: use the API-supplied incident_id
        # when provided, else fall back to the scenario's deterministic id.
        emitted_id = incident_id if incident_id is not None else scenario.incident_id
        if on_event:
            await on_event(IncidentStartedEvent(
                incident_id=emitted_id, elapsed_ms=0,
                scenario_id=scenario.id, severity=scenario.severity,
                title=scenario.title, watched_project=scenario.watched_project,
            ))
            await on_event(SeedCompletedEvent(
                incident_id=emitted_id, elapsed_ms=10,
                project=scenario.watched_project, spans_written=42, n_ok=30, n_error=12,
            ))
            for stage in ("investigate", "root_cause", "remediation", "postmortem"):
                await on_event(StageStartedEvent(
                    incident_id=emitted_id, elapsed_ms=20,
                    stage=stage, prompt_preview="...",
                ))
                await on_event(StageCompletedEvent(
                    incident_id=emitted_id, elapsed_ms=100,
                    stage=stage, latency_ms=50,
                    authors=["coordinator", stage], final_text=f"{stage} text",
                ))
            await on_event(PostmortemValidatedEvent(
                incident_id=emitted_id, elapsed_ms=110,
                completeness_score=1.0, completeness_label="complete",
                postmortem_json=pm.model_dump_json(),
            ))
            await on_event(IncidentCompletedEvent(
                incident_id=emitted_id, elapsed_ms=120, total_latency_ms=120,
            ))

        return EndToEndResult(
            scenario_id=scenario.id, total_latency_ms=120,
            stages=[], seed_summary=SeedSummary(
                project=scenario.watched_project, spans_written=42, n_ok=30, n_error=12,
            ),
            postmortem=pm, completeness=None, error=None,
        )

    app = create_app()
    with patch("sentinel.api.incidents.run_end_to_end_scenario", side_effect=fake_pipeline):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            # 1) POST creates the incident
            post_resp = await client.post("/incidents", json={"scenario_id": "fraud-fp-burst"})
            assert post_resp.status_code == 201
            incident_id = post_resp.json()["incident_id"]

            # 2) SSE drains all events
            events: list[dict[str, Any]] = []
            async with client.stream("GET", f"/incidents/{incident_id}/stream") as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[len("data:"):].strip()))

            types = [e["type"] for e in events]
            assert types == [
                "incident_started", "seed_completed",
                "stage_started", "stage_completed",  # investigate
                "stage_started", "stage_completed",  # root_cause
                "stage_started", "stage_completed",  # remediation
                "stage_started", "stage_completed",  # postmortem
                "postmortem_validated", "incident_completed",
            ]

            # All events must carry the registry incident_id (not the deterministic scenario alert_id)
            for event_payload in events:
                assert event_payload["incident_id"] == incident_id, (
                    f"event {event_payload['type']} carried incident_id={event_payload['incident_id']!r}, "
                    f"expected {incident_id!r}"
                )

            # 3) Wait for the runner task's finally: state.completed.set() to fire.
            # Awaiting the actual signal removes the only non-deterministic point in the test.
            from sentinel.api.incidents import _REGISTRY
            await asyncio.wait_for(_REGISTRY[incident_id].completed.wait(), timeout=2.0)

            # 4) GET returns the validated postmortem
            get_resp = await client.get(f"/incidents/{incident_id}")
            assert get_resp.status_code == 200
            body = get_resp.json()
            assert body["succeeded"] is True
            assert body["total_latency_ms"] == 120
            assert body["scenario_id"] == "fraud-fp-burst"
            assert body["postmortem"]["severity"] == "P1"
            assert "electronics" in body["postmortem"]["root_cause"]
