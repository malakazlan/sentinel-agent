"""Tests for the local incident memory store (ADR-013 / Phase 7 Addition 2).

Round-trip, dedup, cosine ordering, edge cases. No Vertex calls — embeddings
are passed in explicitly.
"""

from __future__ import annotations

import json

import pytest

from sentinel.memory.incident_memory import (
    IncidentMemoryStore,
    IncidentRecord,
    SimilarIncident,
    cosine_similarity,
)


# ── cosine_similarity ────────────────────────────────────────────────────


def test_cosine_identical_vectors_is_one() -> None:
    v = [0.5, 0.5, 0.5]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite_vectors_is_negative_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_degenerate_inputs_return_zero() -> None:
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0  # mismatched dims
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero norm


# ── IncidentMemoryStore ──────────────────────────────────────────────────


def _make_record(
    incident_id: str = "inc-1",
    scenario_id: str = "fraud-fp-burst",
    embedding: list[float] | None = None,
) -> IncidentRecord:
    return IncidentRecord(
        incident_id=incident_id,
        scenario_id=scenario_id,
        timestamp="2026-06-01T00:00:00+00:00",
        title="Test incident",
        postmortem_summary="A spike of false positives blocked legitimate transactions.",
        root_cause="Model exhibited over-sensitive thresholding for electronics.",
        remediation_summary="Rolled back to previous model version.",
        embedding=embedding if embedding is not None else [1.0, 0.0, 0.0],
    )


def test_store_appends_and_reads_back(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    rec = _make_record()
    store.append(rec)
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0].incident_id == "inc-1"
    assert loaded[0].embedding == [1.0, 0.0, 0.0]


def test_store_dedupes_by_incident_id_last_write_wins(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record(embedding=[1.0, 0.0, 0.0]))
    store.append(_make_record(embedding=[0.0, 1.0, 0.0]))  # same incident_id
    loaded = store.load_all()
    assert len(loaded) == 1
    # Last write wins
    assert loaded[0].embedding == [0.0, 1.0, 0.0]


def test_store_handles_missing_file(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "nonexistent.jsonl")
    assert store.load_all() == []


def test_store_skips_malformed_lines(tmp_path) -> None:
    path = tmp_path / "incidents.jsonl"
    store = IncidentMemoryStore(path=path)
    store.append(_make_record())
    # Append a junk line
    with path.open("a", encoding="utf-8") as f:
        f.write("this is not json\n")
        f.write(json.dumps({"incident_id": "bad", "missing_fields": True}) + "\n")
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0].incident_id == "inc-1"


# ── top_k_similar ─────────────────────────────────────────────────────────


def test_top_k_returns_results_sorted_by_similarity_descending(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    # Three records with different embeddings.
    store.append(_make_record(incident_id="inc-aligned", embedding=[1.0, 0.0, 0.0]))
    store.append(_make_record(incident_id="inc-partial", embedding=[0.7, 0.7, 0.0]))
    store.append(_make_record(incident_id="inc-orthogonal", embedding=[0.0, 1.0, 0.0]))

    query = [1.0, 0.0, 0.0]
    results = store.top_k_similar(query, top_k=3, min_similarity=0.0)
    assert len(results) == 3
    ids = [r.incident_id for r in results]
    assert ids == ["inc-aligned", "inc-partial", "inc-orthogonal"]
    assert results[0].similarity > results[1].similarity > results[2].similarity


def test_top_k_filters_below_min_similarity(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record(incident_id="close", embedding=[1.0, 0.0, 0.0]))
    store.append(_make_record(incident_id="far", embedding=[0.0, 0.0, 1.0]))

    results = store.top_k_similar([1.0, 0.0, 0.0], top_k=5, min_similarity=0.5)
    assert len(results) == 1
    assert results[0].incident_id == "close"


def test_top_k_returns_similar_incident_shape(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record())
    [hit] = store.top_k_similar([1.0, 0.0, 0.0], top_k=1, min_similarity=0.0)
    assert isinstance(hit, SimilarIncident)
    # Embedding must be stripped from the briefing-bound shape.
    assert not hasattr(hit, "embedding")
    assert 0.0 <= hit.similarity <= 1.0


def test_top_k_on_empty_store_returns_empty(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    assert store.top_k_similar([1.0, 0.0, 0.0]) == []
