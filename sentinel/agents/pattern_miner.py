"""PatternMiner — Phase 8 / ADR-021.

Mines completed incidents for recurring failure patterns and proposes
either a new directive (added to the Coordinator's briefing) or a new
specialized sub-agent (scaffolded under ``sentinel/agents/proposed_*``).

Approach: embed each completed incident's ``root_cause + remediation``
text via the shared Vertex pipeline, then group by greedy
similarity-threshold clustering (no sklearn dep, deterministic). For
each cluster of size >= ``MIN_CLUSTER_SIZE`` (default 3), an LLM
generates a structured ``PatternProposal`` capturing the recurring
pattern + proposed mitigation. The /patterns page surfaces accept /
reject buttons; the orchestrator never auto-promotes.

The LLM step ONLY summarizes clusters — it cannot invent clusters that
the embedding-similarity step did not produce. This is the structural
guard against hallucinated patterns.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

_logger = logging.getLogger(__name__)


# ── Bounds / thresholds (ADR-021) ─────────────────────────────────────────


# Minimum cluster size before a pattern is considered "recurring."
# 1-2 are noise; 3 is the smallest signal worth surfacing per ADR-021.
MIN_CLUSTER_SIZE: int = 3

# Pair-similarity floor for inclusion in a cluster. Above this two
# incidents are considered the "same pattern"; below they're distinct.
SIMILARITY_FLOOR: float = 0.70

# Per-cluster cohesion gate: average pair-similarity within a cluster
# must be at least this. Below it the cluster is rejected as
# low-cohesion (likely keyword overlap rather than shared root cause).
COHESION_FLOOR: float = 0.65


# ── Schemas ───────────────────────────────────────────────────────────────


MitigationType = "new_directive"  # type: ignore[assignment]


class PatternProposal(BaseModel):
    """One mined pattern + proposed mitigation. Phase 8 / ADR-021."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(..., min_length=3, max_length=80)
    representative_root_cause: str = Field(..., min_length=20, max_length=2000)
    member_incident_ids: list[str] = Field(..., min_length=MIN_CLUSTER_SIZE)
    member_count: int = Field(..., ge=MIN_CLUSTER_SIZE)
    avg_pair_similarity: float = Field(..., ge=0.0, le=1.0)
    proposed_mitigation_type: str = Field(
        ...,
        description="Either 'new_directive' or 'new_subagent'.",
    )
    proposed_mitigation_text: str = Field(..., min_length=20, max_length=1500)
    status: str = Field(
        default="proposed",
        description=(
            "Lifecycle: proposed → accepted | rejected. UI toggles via "
            "POST /patterns/{cluster_id}/{accept|reject}."
        ),
    )


# ── Clustering ────────────────────────────────────────────────────────────


@dataclass
class _IncidentEmbedding:
    incident_id: str
    scenario_id: str
    root_cause: str
    remediation_summary: str
    embedding: list[float]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class _Cluster:
    members: list[_IncidentEmbedding] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)

    def add(self, item: _IncidentEmbedding) -> None:
        self.members.append(item)
        self.centroid = _avg_vectors([m.embedding for m in self.members])


def _avg_vectors(vecs: list[list[float]]) -> list[float]:
    if not vecs:
        return []
    n = len(vecs[0])
    if n == 0:
        return []
    out = [0.0] * n
    for v in vecs:
        for i, x in enumerate(v):
            out[i] += x
    return [x / len(vecs) for x in out]


def cluster_incidents(
    items: list[_IncidentEmbedding],
    *,
    similarity_floor: float = SIMILARITY_FLOOR,
) -> list[_Cluster]:
    """Greedy centroid clustering.

    Walks items in order. For each item, attaches it to the existing
    cluster whose centroid is closest AND whose similarity exceeds
    ``similarity_floor``. If no cluster qualifies, starts a new one.
    Deterministic given a stable iteration order.

    Linear-ish; for the hackathon corpora (10s-100s of incidents) this
    is plenty fast and avoids a sklearn dep.
    """
    clusters: list[_Cluster] = []
    for item in items:
        best_idx: Optional[int] = None
        best_sim = similarity_floor
        for i, c in enumerate(clusters):
            sim = _cosine(c.centroid, item.embedding)
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        if best_idx is None:
            new = _Cluster()
            new.add(item)
            clusters.append(new)
        else:
            clusters[best_idx].add(item)
    return clusters


def cluster_cohesion(c: _Cluster) -> float:
    """Mean pair-cosine within a cluster. The cohesion floor gate uses this."""
    if len(c.members) < 2:
        return 1.0
    sims: list[float] = []
    for i in range(len(c.members)):
        for j in range(i + 1, len(c.members)):
            sims.append(_cosine(c.members[i].embedding, c.members[j].embedding))
    return sum(sims) / len(sims) if sims else 0.0


# ── Mining entry point ───────────────────────────────────────────────────


def mine_patterns(
    incidents: list[dict[str, Any]],
    *,
    min_cluster_size: int = MIN_CLUSTER_SIZE,
    cohesion_floor: float = COHESION_FLOOR,
    similarity_floor: float = SIMILARITY_FLOOR,
    embedder: Optional[Any] = None,
) -> list[PatternProposal]:
    """Return a list of PatternProposal objects mined from ``incidents``.

    Each input dict should carry: ``incident_id``, ``scenario_id``,
    ``root_cause``, ``remediation_summary``, and optionally
    ``embedding`` (a precomputed vector). If ``embedding`` is missing
    AND no ``embedder`` is provided, the incident is skipped with a
    warning.

    Returns proposals for every cluster of size >= ``min_cluster_size``
    whose cohesion >= ``cohesion_floor``. Smaller / lower-cohesion
    clusters are dropped silently per ADR-021.

    The proposal's ``proposed_mitigation_text`` and
    ``representative_root_cause`` are derived deterministically from the
    cluster centroid + member root_cause strings (the centroid-nearest
    member is the representative). An LLM step CAN refine these
    downstream, but the structure is built without LLM access so the
    mining step is fully testable.
    """
    if embedder is None:
        try:
            from sentinel.memory.embedder import embed_text
            embedder = embed_text
        except ImportError:
            embedder = None

    enriched: list[_IncidentEmbedding] = []
    for inc in incidents:
        emb = inc.get("embedding")
        if not emb and embedder is not None:
            text = (
                str(inc.get("root_cause", ""))
                + " "
                + str(inc.get("remediation_summary", ""))
            )
            emb = embedder(text)
        if not emb:
            _logger.warning(
                "Skipping incident %s — no embedding available",
                inc.get("incident_id", "?"),
            )
            continue
        enriched.append(_IncidentEmbedding(
            incident_id=inc["incident_id"],
            scenario_id=inc.get("scenario_id", ""),
            root_cause=inc.get("root_cause", ""),
            remediation_summary=inc.get("remediation_summary", ""),
            embedding=list(emb),
        ))

    clusters = cluster_incidents(enriched, similarity_floor=similarity_floor)

    proposals: list[PatternProposal] = []
    for idx, cluster in enumerate(clusters):
        if len(cluster.members) < min_cluster_size:
            continue
        cohesion = cluster_cohesion(cluster)
        if cohesion < cohesion_floor:
            continue
        # Centroid-nearest member is the representative.
        rep = max(
            cluster.members,
            key=lambda m: _cosine(cluster.centroid, m.embedding),
        )
        cluster_id = f"pattern-{idx:03d}-{rep.scenario_id or 'mixed'}"
        proposals.append(PatternProposal(
            cluster_id=cluster_id,
            representative_root_cause=rep.root_cause,
            member_incident_ids=[m.incident_id for m in cluster.members],
            member_count=len(cluster.members),
            avg_pair_similarity=round(cohesion, 4),
            proposed_mitigation_type=(
                "new_directive" if len(cluster.members) < 5 else "new_subagent"
            ),
            proposed_mitigation_text=(
                f"Recurring failure pattern across {len(cluster.members)} "
                f"incidents (cohesion={cohesion:.2f}). Representative root "
                f"cause: {rep.root_cause[:200]}. Recommend: add an "
                "operator-approved directive to the Coordinator briefing "
                "that surfaces this pattern proactively on similar "
                "incidents, OR scaffold a specialized sub-agent if the "
                "pattern requires structured remediation."
            ),
        ))
    return proposals


# ── Accept / reject persistence (read by the FastAPI endpoint) ───────────


_PATTERN_DIR = Path("data/memory/pattern_proposals")


def persist_pattern_decision(cluster_id: str, decision: str) -> None:
    """Write ``accepted`` or ``rejected`` to a sidecar file the API reads."""
    assert decision in ("accepted", "rejected"), decision
    _PATTERN_DIR.mkdir(parents=True, exist_ok=True)
    (_PATTERN_DIR / f"{cluster_id}.decision").write_text(decision)


def load_pattern_decision(cluster_id: str) -> Optional[str]:
    f = _PATTERN_DIR / f"{cluster_id}.decision"
    if not f.exists():
        return None
    return f.read_text().strip()
