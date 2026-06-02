"""Tests for VectorSearchMemoryStore (ADR-013 reversal / Phase 7).

Uses unittest.mock to stub out google.cloud.aiplatform so the tests have
no Vertex dependency. The dual-write pattern + sidecar hydration is
exercised end-to-end with a temp-path sidecar.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sentinel.memory.incident_memory import IncidentMemoryStore, IncidentRecord
from sentinel.memory.vector_search_store import (
    VectorSearchMemoryStore,
    VectorSearchUnavailable,
    get_config_path,
)


def _record(incident_id: str, embedding: list[float]) -> IncidentRecord:
    return IncidentRecord(
        incident_id=incident_id,
        scenario_id="fraud-fp-burst",
        timestamp="2026-06-02T00:00:00+00:00",
        title="Test incident",
        postmortem_summary="A spike of false positives.",
        root_cause="Over-sensitive thresholding for electronics.",
        remediation_summary="Rolled back.",
        embedding=embedding,
    )


# ── from_config ───────────────────────────────────────────────────────────


def test_from_config_raises_when_file_missing(tmp_path) -> None:
    with pytest.raises(VectorSearchUnavailable, match="Vector Search config missing"):
        VectorSearchMemoryStore.from_config(config_path=tmp_path / "missing.json")


def test_from_config_raises_when_keys_missing(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"index_resource_name": "abc"}), encoding="utf-8")
    with pytest.raises(VectorSearchUnavailable, match="missing keys"):
        VectorSearchMemoryStore.from_config(config_path=path)


def test_from_config_constructs_store(tmp_path) -> None:
    path = tmp_path / "config.json"
    payload = {
        "index_resource_name": "projects/p/locations/l/indexes/123",
        "endpoint_resource_name": "projects/p/locations/l/indexEndpoints/456",
        "deployed_index_id": "deployed_id_789",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = IncidentMemoryStore(path=tmp_path / "sidecar.jsonl")

    store = VectorSearchMemoryStore.from_config(
        config_path=path, sidecar_store=sidecar
    )
    assert store._index_name == payload["index_resource_name"]
    assert store._endpoint_name == payload["endpoint_resource_name"]
    assert store._deployed_index_id == payload["deployed_index_id"]


# ── append (dual-write) ───────────────────────────────────────────────────


def test_append_writes_sidecar_first_then_vector_search(tmp_path) -> None:
    sidecar = IncidentMemoryStore(path=tmp_path / "sidecar.jsonl")
    store = VectorSearchMemoryStore(
        index_resource_name="i",
        endpoint_resource_name="e",
        deployed_index_id="d",
        sidecar_store=sidecar,
    )

    fake_index = MagicMock()
    store._index = fake_index

    record = _record("inc-1", [0.1, 0.2, 0.3])
    store.append(record)

    # Sidecar got the record.
    loaded = sidecar.load_all()
    assert len(loaded) == 1
    assert loaded[0].incident_id == "inc-1"

    # Vector Search got an upsert call with the expected datapoint shape.
    fake_index.upsert_datapoints.assert_called_once()
    _, kwargs = fake_index.upsert_datapoints.call_args
    [dp] = kwargs["datapoints"]
    assert dp["datapoint_id"] == "inc-1"
    assert dp["feature_vector"] == [0.1, 0.2, 0.3]
    assert dp["restricts"][0]["namespace"] == "scenario_id"
    assert dp["restricts"][0]["allow_list"] == ["fraud-fp-burst"]


def test_append_raises_unavailable_when_vector_search_upsert_fails(tmp_path) -> None:
    sidecar = IncidentMemoryStore(path=tmp_path / "sidecar.jsonl")
    store = VectorSearchMemoryStore(
        index_resource_name="i",
        endpoint_resource_name="e",
        deployed_index_id="d",
        sidecar_store=sidecar,
    )
    fake_index = MagicMock()
    fake_index.upsert_datapoints.side_effect = RuntimeError("simulated transport failure")
    store._index = fake_index

    record = _record("inc-1", [0.1, 0.2, 0.3])
    with pytest.raises(VectorSearchUnavailable, match="upsert failed"):
        store.append(record)

    # Sidecar still got the record — data is never lost.
    assert len(sidecar.load_all()) == 1


# ── top_k_similar (ANN via Vector Search; hydrate via sidecar) ────────────


def test_top_k_similar_hydrates_records_from_sidecar(tmp_path) -> None:
    sidecar = IncidentMemoryStore(path=tmp_path / "sidecar.jsonl")
    sidecar.append(_record("inc-1", [1.0, 0.0, 0.0]))
    sidecar.append(_record("inc-2", [0.0, 1.0, 0.0]))

    store = VectorSearchMemoryStore(
        index_resource_name="i",
        endpoint_resource_name="e",
        deployed_index_id="d",
        sidecar_store=sidecar,
    )
    fake_endpoint = MagicMock()
    # Vertex Vector Search returns cosine DISTANCE; we convert to similarity.
    # 0.1 distance → 0.9 similarity (above 0.5 floor).
    # 0.7 distance → 0.3 similarity (below floor, filtered out).
    fake_endpoint.find_neighbors.return_value = [
        [
            SimpleNamespace(id="inc-1", distance=0.1),
            SimpleNamespace(id="inc-2", distance=0.7),
        ]
    ]
    store._endpoint = fake_endpoint

    results = store.top_k_similar([1.0, 0.0, 0.0], top_k=5, min_similarity=0.5)
    assert len(results) == 1
    assert results[0].incident_id == "inc-1"
    assert results[0].similarity == pytest.approx(0.9, abs=1e-4)


def test_top_k_similar_returns_empty_on_empty_query() -> None:
    store = VectorSearchMemoryStore(
        index_resource_name="i",
        endpoint_resource_name="e",
        deployed_index_id="d",
        sidecar_store=IncidentMemoryStore(),
    )
    assert store.top_k_similar([], top_k=3) == []


def test_top_k_similar_skips_ids_with_no_sidecar_record(tmp_path) -> None:
    sidecar = IncidentMemoryStore(path=tmp_path / "sidecar.jsonl")
    # No records in sidecar. Vector Search returns IDs that don't exist.
    store = VectorSearchMemoryStore(
        index_resource_name="i",
        endpoint_resource_name="e",
        deployed_index_id="d",
        sidecar_store=sidecar,
    )
    fake_endpoint = MagicMock()
    fake_endpoint.find_neighbors.return_value = [
        [SimpleNamespace(id="stale-id", distance=0.1)]
    ]
    store._endpoint = fake_endpoint

    # No hydration possible → empty result, no crash.
    assert store.top_k_similar([1.0, 0.0, 0.0], top_k=3, min_similarity=0.0) == []


def test_top_k_similar_raises_unavailable_on_endpoint_failure(tmp_path) -> None:
    sidecar = IncidentMemoryStore(path=tmp_path / "sidecar.jsonl")
    store = VectorSearchMemoryStore(
        index_resource_name="i",
        endpoint_resource_name="e",
        deployed_index_id="d",
        sidecar_store=sidecar,
    )
    fake_endpoint = MagicMock()
    fake_endpoint.find_neighbors.side_effect = RuntimeError("simulated network failure")
    store._endpoint = fake_endpoint

    with pytest.raises(VectorSearchUnavailable, match="query failed"):
        store.top_k_similar([1.0, 0.0, 0.0])


# ── backend selection in recall._shared_store ─────────────────────────────


def test_shared_store_falls_back_to_local_when_vector_search_misconfigured(
    monkeypatch, tmp_path
) -> None:
    """When SENTINEL_MEMORY_BACKEND=vector_search but config is missing,
    the recall path must degrade to the local store, not crash."""
    from sentinel.memory import recall

    monkeypatch.setenv("SENTINEL_MEMORY_BACKEND", "vector_search")
    monkeypatch.setenv(
        "SENTINEL_VECTOR_SEARCH_CONFIG", str(tmp_path / "missing.json")
    )
    store = recall._shared_store()
    # Local fallback engaged.
    assert isinstance(store, IncidentMemoryStore)


def test_shared_store_returns_local_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SENTINEL_MEMORY_BACKEND", raising=False)
    from sentinel.memory import recall

    store = recall._shared_store()
    assert isinstance(store, IncidentMemoryStore)
