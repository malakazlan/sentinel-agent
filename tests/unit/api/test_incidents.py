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
