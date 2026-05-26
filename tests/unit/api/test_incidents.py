"""Endpoint tests for /incidents — POST creates and starts a run;
the test mocks the heavy pipeline so this stays fast and offline."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel.api.main import create_app


@pytest.mark.asyncio
async def test_post_incident_returns_incident_id_and_201() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        with patch("sentinel.api.incidents._run_in_background") as mock_run:
            resp = await client.post("/incidents", json={"scenario_id": "fraud-fp-burst"})
            assert resp.status_code == 201
            body = resp.json()
            assert "incident_id" in body
            assert body["scenario_id"] == "fraud-fp-burst"
            assert body["severity"] == "P1"
            mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_post_incident_rejects_unknown_scenario() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/incidents", json={"scenario_id": "not-a-scenario"})
        assert resp.status_code == 400
        assert "unknown scenario" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_incident_validates_request_body() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/incidents", json={})  # missing scenario_id
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_incident_twice_yields_distinct_incident_ids() -> None:
    """Two posts to the same scenario must not clobber each other in the registry."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        with patch("sentinel.api.incidents._run_in_background"):
            r1 = await client.post("/incidents", json={"scenario_id": "fraud-fp-burst"})
            r2 = await client.post("/incidents", json={"scenario_id": "fraud-fp-burst"})
            assert r1.status_code == 201
            assert r2.status_code == 201
            assert r1.json()["incident_id"] != r2.json()["incident_id"]


@pytest.mark.asyncio
async def test_stream_yields_events_until_terminal() -> None:
    """Subscribe to /incidents/{id}/stream and verify events flow until
    incident_completed (or incident_failed)."""
    from sentinel.api.events import (
        IncidentCompletedEvent,
        IncidentStartedEvent,
        StageStartedEvent,
    )
    from sentinel.api.incidents import _IncidentState, _REGISTRY

    state = _IncidentState(
        incident_id="t-incident",
        scenario_id="fraud-fp-burst",
        severity="P1",
        title="test",
    )
    _REGISTRY["t-incident"] = state

    # Pre-load some events
    await state.queue.put(IncidentStartedEvent(
        incident_id="t-incident", elapsed_ms=0,
        scenario_id="fraud-fp-burst", severity="P1",
        title="test", watched_project="x",
    ))
    await state.queue.put(StageStartedEvent(
        incident_id="t-incident", elapsed_ms=100,
        stage="investigate", prompt_preview="...",
    ))
    await state.queue.put(IncidentCompletedEvent(
        incident_id="t-incident", elapsed_ms=200, total_latency_ms=200,
    ))
    state.completed.set()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        async with client.stream("GET", "/incidents/t-incident/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            chunks = []
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    chunks.append(line[len("data:"):].strip())
                if len(chunks) >= 3:
                    break
    assert len(chunks) == 3
    import json
    types = [json.loads(c)["type"] for c in chunks]
    assert types == ["incident_started", "stage_started", "incident_completed"]


@pytest.mark.asyncio
async def test_stream_unknown_incident_returns_404() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/incidents/does-not-exist/stream")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_terminates_on_incident_failed_event() -> None:
    """The stream must close cleanly on IncidentFailedEvent too, not only
    on IncidentCompletedEvent."""
    from sentinel.api.events import IncidentFailedEvent, IncidentStartedEvent
    from sentinel.api.incidents import _IncidentState, _REGISTRY

    state = _IncidentState(
        incident_id="t-failed",
        scenario_id="fraud-fp-burst",
        severity="P1",
        title="test",
    )
    _REGISTRY["t-failed"] = state

    await state.queue.put(IncidentStartedEvent(
        incident_id="t-failed", elapsed_ms=0,
        scenario_id="fraud-fp-burst", severity="P1",
        title="test", watched_project="x",
    ))
    await state.queue.put(IncidentFailedEvent(
        incident_id="t-failed", elapsed_ms=50,
        error="RuntimeError: boom",
    ))
    state.completed.set()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        async with client.stream("GET", "/incidents/t-failed/stream") as resp:
            assert resp.status_code == 200
            chunks = []
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    chunks.append(line[len("data:"):].strip())
                if len(chunks) >= 2:
                    break
    import json
    types = [json.loads(c)["type"] for c in chunks]
    assert types[-1] == "incident_failed"


@pytest.mark.asyncio
async def test_get_incident_returns_final_result_when_completed() -> None:
    from sentinel.api.incidents import _IncidentState, _REGISTRY
    from sentinel.coordinator import EndToEndResult
    from sentinel.agents.schemas import Postmortem, ActionItem

    pm = Postmortem(
        title="Test postmortem for grounded electronics false positives",
        incident_id="t-completed",
        severity="P1",
        summary="A spike in false positives occurred for electronics merchant category transactions, blocking legitimate retail purchases.",
        impact="12 legitimate transactions blocked between 13:16 and 13:21 UTC.",
        timeline=["13:16 UTC — onset", "13:21 UTC — last false positive observed"],
        root_cause="Model exhibited over-sensitive thresholding for electronics merchant category transactions above $800.",
        detection="Discovered via post-hoc verification logs comparing model output to verified labels.",
        resolution="Investigation in progress; rollback to previous version being evaluated.",
        action_items=[ActionItem(description="Investigate model sensitivity to electronics", owner_role="fraud-ml-team", severity="P1", due_within_days=7)],
        lessons_learned=["High-confidence scores are unreliable during drift events."],
    )
    state = _IncidentState(
        incident_id="t-completed",
        scenario_id="fraud-fp-burst",
        severity="P1",
        title="test",
    )
    state.result = EndToEndResult(
        scenario_id="fraud-fp-burst",
        total_latency_ms=12345,
        stages=[],
        seed_summary=None,
        postmortem=pm,
        completeness=None,
        error=None,
    )
    state.completed.set()
    _REGISTRY["t-completed"] = state

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/incidents/t-completed")
        assert resp.status_code == 200
        body = resp.json()
        assert body["succeeded"] is True
        assert body["total_latency_ms"] == 12345
        assert body["postmortem"]["severity"] == "P1"


@pytest.mark.asyncio
async def test_get_incident_pending_returns_202_with_status() -> None:
    from sentinel.api.incidents import _IncidentState, _REGISTRY
    state = _IncidentState(
        incident_id="t-pending",
        scenario_id="fraud-fp-burst",
        severity="P1",
        title="test",
    )
    _REGISTRY["t-pending"] = state  # completed not set, result is None

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/incidents/t-pending")
        assert resp.status_code == 202
        assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_get_incident_unknown_returns_404() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/incidents/does-not-exist")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_incident_failed_returns_succeeded_false_with_error() -> None:
    """If the runner caught an exception, the GET should return succeeded=False
    plus the error message, with status 200 (the request is fine; the pipeline failed)."""
    from sentinel.api.incidents import _IncidentState, _REGISTRY
    state = _IncidentState(
        incident_id="t-failed-get",
        scenario_id="fraud-fp-burst",
        severity="P1",
        title="test",
    )
    state.failed_with = "RuntimeError: simulated boom"
    state.completed.set()
    _REGISTRY["t-failed-get"] = state

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/incidents/t-failed-get")
        assert resp.status_code == 200
        body = resp.json()
        assert body["succeeded"] is False
        assert "simulated boom" in body["error"]
