"""Tests for ``recall_similar_incidents`` and ``remember_incident``.

The embedder is mocked — no Vertex calls in the unit suite.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sentinel.memory.incident_memory import IncidentMemoryStore, IncidentRecord
from sentinel.memory.recall import recall_similar_incidents, remember_incident


def _make_record(incident_id: str, embedding: list[float]) -> IncidentRecord:
    return IncidentRecord(
        incident_id=incident_id,
        scenario_id="fraud-fp-burst",
        timestamp="2026-06-01T00:00:00+00:00",
        title="Past fraud incident",
        postmortem_summary="Past FP spike on electronics.",
        root_cause="Past model drift on electronics merchant category.",
        remediation_summary="Past rollback.",
        embedding=embedding,
    )


# ── recall_similar_incidents ──────────────────────────────────────────────


def test_recall_returns_top_k_when_embedder_succeeds(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record("past-1", [1.0, 0.0, 0.0]))
    store.append(_make_record("past-2", [0.5, 0.5, 0.0]))
    store.append(_make_record("past-3", [0.0, 0.0, 1.0]))

    # Query embedding aligned with past-1.
    with patch(
        "sentinel.memory.recall.embed_text", return_value=[1.0, 0.0, 0.0]
    ):
        results = recall_similar_incidents(
            "fraud incident on electronics category",
            top_k=2,
            min_similarity=0.0,
            store=store,
        )
    assert len(results) == 2
    assert results[0].incident_id == "past-1"
    assert results[1].incident_id == "past-2"


def test_recall_returns_empty_when_embedder_fails(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record("past-1", [1.0, 0.0, 0.0]))

    with patch("sentinel.memory.recall.embed_text", return_value=[]):
        results = recall_similar_incidents(
            "irrelevant alert", top_k=3, store=store
        )
    assert results == []


def test_recall_returns_empty_on_empty_alert(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record("past-1", [1.0, 0.0, 0.0]))

    # The function short-circuits before calling the embedder.
    with patch("sentinel.memory.recall.embed_text") as mock_embed:
        results = recall_similar_incidents("", store=store)
        mock_embed.assert_not_called()
    assert results == []


def test_recall_returns_empty_when_store_is_empty(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    with patch(
        "sentinel.memory.recall.embed_text", return_value=[1.0, 0.0, 0.0]
    ):
        results = recall_similar_incidents("anything", store=store)
    assert results == []


# ── remember_incident ─────────────────────────────────────────────────────


def test_remember_appends_record_with_embedding(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    with patch(
        "sentinel.memory.recall.embed_text", return_value=[0.1, 0.2, 0.3]
    ):
        ok = remember_incident(
            incident_id="inc-new",
            scenario_id="fraud-fp-burst",
            title="False positive spike on electronics",
            postmortem_summary="Summary text.",
            root_cause="Root cause text.",
            remediation_summary="Remediation text.",
            store=store,
        )
    assert ok is True
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0].incident_id == "inc-new"
    assert loaded[0].embedding == [0.1, 0.2, 0.3]


def test_remember_returns_false_and_skips_write_when_embedder_fails(tmp_path) -> None:
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    with patch("sentinel.memory.recall.embed_text", return_value=[]):
        ok = remember_incident(
            incident_id="inc-fail",
            scenario_id="fraud-fp-burst",
            title="Title",
            postmortem_summary="Summary",
            root_cause="Root cause",
            store=store,
        )
    assert ok is False
    # No record written — the JSONL stays empty.
    assert store.load_all() == []


# ── synthesize_prior_context integration ──────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_attaches_similar_past_incidents_when_alert_provided(
    tmp_path,
) -> None:
    """The briefing returned by ``synthesize_prior_context(alert_payload=...)``
    must surface the top-K similar incidents from the local store.
    """
    from sentinel.memory import self_introspection as si
    from sentinel.memory.incident_memory import IncidentMemoryStore

    # Seed a store the recall function can find via dependency injection
    # through the embedder mock + store override below.
    store = IncidentMemoryStore(path=tmp_path / "incidents.jsonl")
    store.append(_make_record("past-fraud-1", [1.0, 0.0, 0.0]))

    # Mock Phoenix MCP to a known empty-history shape so the synthesizer
    # returns a cold-start briefing (simplest controlled path).
    async def fake_recall(alert_payload, top_k=3, min_similarity=0.5, store=None):
        from sentinel.memory.recall import recall_similar_incidents as real_recall
        return real_recall(
            alert_payload, top_k=top_k, min_similarity=min_similarity, store=store_arg
        )

    store_arg = store  # capture for closure

    with patch.object(si, "recall_similar_incidents") as mock_recall, patch.object(
        si, "_get_mcp"
    ) as mock_mcp:
        mock_recall.return_value = store.top_k_similar(
            [1.0, 0.0, 0.0], top_k=3, min_similarity=0.0
        )
        # Force the MCP path to raise so we fall into the cold-start branch
        # with similar_past_incidents still populated.
        mock_mcp.side_effect = RuntimeError("simulated MCP outage")

        briefing = await si.synthesize_prior_context(
            alert_payload="fraud incident on electronics"
        )
    assert briefing.cold_start is True
    assert len(briefing.similar_past_incidents) == 1
    assert briefing.similar_past_incidents[0].incident_id == "past-fraud-1"


@pytest.mark.asyncio
async def test_synthesize_with_no_alert_payload_skips_recall() -> None:
    """When called without an alert_payload, the synthesizer must not invoke
    recall_similar_incidents (saves a Vertex embedding call per invocation
    when the caller has nothing to embed)."""
    from sentinel.memory import self_introspection as si

    with patch.object(si, "recall_similar_incidents") as mock_recall, patch.object(
        si, "_get_mcp"
    ) as mock_mcp:
        mock_mcp.side_effect = RuntimeError("simulated MCP outage")
        briefing = await si.synthesize_prior_context()  # no alert_payload
    mock_recall.assert_not_called()
    assert briefing.similar_past_incidents == []
