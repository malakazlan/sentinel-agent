"""Tests for PatternMiner clustering + proposal generation.

Phase 8 / ADR-021. Stub embeddings give deterministic clusters, so:

- Two recurring patterns + singletons → both clusters detected; the
  singletons are correctly dropped as noise.
- Only-singleton corpus → no proposals (no false positives).
- Cluster of size 2 → rejected (below MIN_CLUSTER_SIZE).
- Low-cohesion cluster → rejected by cohesion gate.
- Accept / reject persistence round-trips through the API helpers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.agents.pattern_miner import (
    COHESION_FLOOR,
    MIN_CLUSTER_SIZE,
    SIMILARITY_FLOOR,
    PatternProposal,
    cluster_cohesion,
    cluster_incidents,
    load_pattern_decision,
    mine_patterns,
    persist_pattern_decision,
)


# Three "themed" embeddings — within-theme cosine ~1.0; cross-theme ~0.0.
THEME_A = [1.0, 0.0, 0.0, 0.0]
THEME_B = [0.0, 1.0, 0.0, 0.0]
THEME_C = [0.0, 0.0, 1.0, 0.0]


def _inc(iid: str, scenario: str, emb: list[float], rc: str = "Root cause text long enough to satisfy the schema floor.") -> dict:
    return {
        "incident_id": iid,
        "scenario_id": scenario,
        "root_cause": rc,
        "remediation_summary": "Rollback and re-run with corrected upstream feed",
        "embedding": emb,
    }


def test_detects_two_distinct_recurring_patterns() -> None:
    """Eight incidents: 3 stale-cache + 3 latency-regression + 2 singletons."""
    incidents = [
        _inc("inc-1", "fraud", THEME_A, "Stale feature cache for 1h"),
        _inc("inc-2", "fraud", THEME_A, "Stale feature cache for 30m"),
        _inc("inc-3", "fraud", THEME_A, "Stale cache after upstream deploy"),
        _inc("inc-4", "lending", THEME_B, "Latency regression after deploy A"),
        _inc("inc-5", "lending", THEME_B, "Latency regression after deploy B"),
        _inc("inc-6", "lending", THEME_B, "Latency regression after deploy C"),
        _inc("inc-7", "kyc", THEME_C, "One-off PEP hallucination"),  # singleton
        _inc("inc-8", "kyc", [0.0, 0.0, 0.0, 1.0], "One-off model drift"),  # singleton
    ]
    proposals = mine_patterns(incidents)
    # Two clusters detected; singletons dropped.
    assert len(proposals) == 2
    member_counts = sorted([p.member_count for p in proposals])
    assert member_counts == [3, 3]
    # Both proposals are seed-grounded.
    for p in proposals:
        assert p.member_count >= MIN_CLUSTER_SIZE
        assert p.avg_pair_similarity >= COHESION_FLOOR


def test_only_singletons_yields_no_proposals() -> None:
    """The 'no false positive' unhappy path required by ADR-021."""
    incidents = [
        _inc("inc-1", "fraud", THEME_A),
        _inc("inc-2", "lending", THEME_B),
        _inc("inc-3", "kyc", THEME_C),
    ]
    proposals = mine_patterns(incidents)
    assert proposals == []


def test_cluster_of_two_rejected() -> None:
    """A pair is not a pattern. Verifies the size floor."""
    incidents = [
        _inc("inc-1", "fraud", THEME_A),
        _inc("inc-2", "fraud", THEME_A),
    ]
    proposals = mine_patterns(incidents)
    assert proposals == []


def test_cohesion_floor_rejects_loose_cluster() -> None:
    """Force a cluster of size 3 with low cohesion; verify it's rejected."""
    # All within similarity_floor of each other but never high-cohesion.
    low_a = [0.71, 0.71, 0.0, 0.0]
    low_b = [0.71, 0.0, 0.71, 0.0]
    low_c = [0.0, 0.71, 0.71, 0.0]
    incidents = [
        _inc("inc-1", "fraud", low_a),
        _inc("inc-2", "fraud", low_b),
        _inc("inc-3", "fraud", low_c),
    ]
    # Drop similarity_floor so they end up in one cluster, then check the
    # cohesion gate rejects them.
    proposals = mine_patterns(incidents, similarity_floor=0.3)
    assert proposals == []


def test_proposal_schema_fields_populated_correctly() -> None:
    incidents = [
        _inc("a", "fraud", THEME_A, "Stale upstream feature cache root cause A"),
        _inc("b", "fraud", THEME_A, "Stale upstream feature cache root cause B"),
        _inc("c", "fraud", THEME_A, "Stale upstream feature cache root cause C"),
    ]
    proposals = mine_patterns(incidents)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.member_count == 3
    assert set(p.member_incident_ids) == {"a", "b", "c"}
    assert p.proposed_mitigation_type in ("new_directive", "new_subagent")
    # Below size 5 → directive.
    assert p.proposed_mitigation_type == "new_directive"
    assert p.cluster_id.startswith("pattern-")


def test_large_cluster_promoted_to_subagent_recommendation() -> None:
    """Clusters >= 5 members suggest a specialized sub-agent."""
    incidents = [_inc(f"inc-{i}", "fraud", THEME_A) for i in range(5)]
    proposals = mine_patterns(incidents)
    assert len(proposals) == 1
    assert proposals[0].proposed_mitigation_type == "new_subagent"


# ── Accept / reject persistence ──────────────────────────────────────────


def test_persist_and_load_decision_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.agents import pattern_miner
    monkeypatch.setattr(pattern_miner, "_PATTERN_DIR", tmp_path)
    persist_pattern_decision("pattern-001-fraud", "accepted")
    assert load_pattern_decision("pattern-001-fraud") == "accepted"
    persist_pattern_decision("pattern-001-fraud", "rejected")
    assert load_pattern_decision("pattern-001-fraud") == "rejected"
    assert load_pattern_decision("nonexistent") is None


def test_persist_rejects_invalid_decision_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.agents import pattern_miner
    monkeypatch.setattr(pattern_miner, "_PATTERN_DIR", tmp_path)
    with pytest.raises(AssertionError):
        persist_pattern_decision("pattern-001", "maybe")
