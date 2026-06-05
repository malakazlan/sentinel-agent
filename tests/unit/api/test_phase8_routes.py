"""Tests for the Phase 8 additive API routes (ADR-027).

Uses FastAPI's TestClient. The store-backed routes return graceful
empty payloads when memory is empty (the smoke contract).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sentinel.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_still_responds(client: TestClient) -> None:
    """Sanity — the pre-existing /health route survives the additive include."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_patterns_returns_list_when_memory_empty_or_present(client: TestClient) -> None:
    r = client.get("/patterns")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_pattern_accept_round_trip(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.agents import pattern_miner
    monkeypatch.setattr(pattern_miner, "_PATTERN_DIR", tmp_path)
    r = client.post("/patterns/test-cluster/accept")
    assert r.status_code == 200
    assert r.json() == {"cluster_id": "test-cluster", "status": "accepted"}
    r = client.post("/patterns/test-cluster/reject")
    assert r.status_code == 200
    assert r.json() == {"cluster_id": "test-cluster", "status": "rejected"}


def test_sentinel_health_returns_agents_array(client: TestClient) -> None:
    r = client.get("/sentinel/health")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body
    assert "history_total" in body
    assert isinstance(body["agents"], list)


def test_prompts_overview_returns_agents_array(client: TestClient) -> None:
    r = client.get("/prompts")
    assert r.status_code == 200
    assert "agents" in r.json()


def test_prompts_history_404_for_unknown_agent(client: TestClient) -> None:
    r = client.get("/prompts/nonexistent_agent/history")
    assert r.status_code == 404


def test_evals_trends_returns_agents_array(client: TestClient) -> None:
    r = client.get("/evals/trends")
    assert r.status_code == 200
    assert "agents" in r.json()


def test_architecture_returns_documented_agent_registry(client: TestClient) -> None:
    r = client.get("/architecture")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body
    # Sanity: the registry includes at least the 11 sub-agents shipped through Phase 8.
    names = {a["name"] for a in body["agents"]}
    expected_subset = {
        "coordinator", "trace_analyzer", "eval_runner",
        "deploy_correlator", "root_cause", "remediation",
        "postmortem", "critic", "customer_impact_quantifier",
        "compliance_officer", "prompt_evolver", "pattern_miner",
    }
    assert expected_subset.issubset(names)


def test_incidents_history_filters_optional(client: TestClient) -> None:
    r = client.get("/incidents-history")
    assert r.status_code == 200
    body = r.json()
    assert "incidents" in body


def test_incidents_history_with_severity_filter(client: TestClient) -> None:
    r = client.get("/incidents-history?severity=P0")
    assert r.status_code == 200
