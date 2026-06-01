"""Local file-backed incident memory store (ADR-013 / Phase 7 Addition 2).

Path A scope-down: replaces Vertex AI Vector Search with a JSONL file +
in-process cosine similarity. Same MemoryAgent + briefing-integration story,
demonstrates persistent memory + RAG across the full corpus of past
incidents (not just a 1-hour Phoenix window). Vertex Vector Search is the
post-hackathon production upgrade — see ADR-013.

Storage shape:
- one JSONL file at ``data/memory/incidents.jsonl``
- one line per completed incident
- each line: ``{incident_id, scenario_id, timestamp, title, postmortem_summary,
  root_cause, remediation_summary, embedding: list[float]}``

The store is intentionally append-only for the demo; deduplication on
``incident_id`` happens at read time.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)

# Default location — overridable via env so tests can write into a temp dir
# without touching the real store.
_DEFAULT_STORE_PATH = "data/memory/incidents.jsonl"


def get_store_path() -> Path:
    """Resolve the store path from env or default. Creates the parent dir."""
    raw = os.environ.get("SENTINEL_MEMORY_STORE_PATH", _DEFAULT_STORE_PATH)
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class IncidentRecord(BaseModel):
    """One past incident, embedded and ready for similarity retrieval."""

    incident_id: str = Field(..., min_length=3, max_length=200)
    scenario_id: str = Field(..., min_length=1, max_length=80)
    timestamp: str = Field(..., description="ISO-8601 UTC of postmortem validation.")
    title: str = Field(..., min_length=1, max_length=400)
    postmortem_summary: str = Field(..., min_length=1)
    root_cause: str = Field(..., min_length=1)
    remediation_summary: str = Field(default="", description="Empty when no remediation was generated.")
    embedding: list[float] = Field(..., min_length=1, description="Dense vector for cosine retrieval.")


class SimilarIncident(BaseModel):
    """A past incident plus its similarity score to the query.

    Distinct from ``IncidentRecord`` so the briefing schema only carries the
    fields the Coordinator's prompt actually consumes — embedding stays out of
    the wire format.
    """

    incident_id: str
    scenario_id: str
    timestamp: str
    title: str
    summary: str
    root_cause_excerpt: str
    similarity: float = Field(..., ge=0.0, le=1.0)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors. Returns 0.0 on
    degenerate input (mismatched dims or zero norms) rather than raising —
    the memory store is best-effort and shouldn't crash the synthesizer.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class IncidentMemoryStore:
    """JSONL-backed append-only incident store with in-process retrieval.

    Why a class and not module-level functions: tests need to instantiate a
    store against a temp path without leaning on env-var hacks.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path: Path = path if path is not None else get_store_path()

    # ── writes ────────────────────────────────────────────────────────────

    def append(self, record: IncidentRecord) -> None:
        """Append a record to the JSONL store. Creates the file if absent."""
        with self.path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    # ── reads ─────────────────────────────────────────────────────────────

    def load_all(self) -> list[IncidentRecord]:
        """Read every record from disk. Dedupes by ``incident_id`` (last-write-wins).

        Malformed JSON lines are logged and skipped — the store is best-effort
        memory, not a database.
        """
        if not self.path.exists():
            return []
        by_id: dict[str, IncidentRecord] = {}
        with self.path.open("r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    rec = IncidentRecord(**obj)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    _logger.warning(
                        "incident_memory: skipping malformed line %d in %s: %s",
                        line_no,
                        self.path,
                        exc,
                    )
                    continue
                by_id[rec.incident_id] = rec
        return list(by_id.values())

    # ── retrieval ─────────────────────────────────────────────────────────

    def top_k_similar(
        self,
        query_embedding: list[float],
        top_k: int = 3,
        min_similarity: float = 0.5,
    ) -> list[SimilarIncident]:
        """Return up to ``top_k`` records above ``min_similarity``, sorted desc.

        Args:
            query_embedding: dense vector for the current incident.
            top_k: maximum results to return. Default 3 — Coordinator's prompt
                consumes a small set.
            min_similarity: floor below which matches are dropped as noise.
                Cosine ranges 0-1; 0.5 is a permissive default.

        Returns:
            A list of ``SimilarIncident`` (not ``IncidentRecord`` — embeddings
            are stripped to keep the briefing block compact).
        """
        records = self.load_all()
        scored: list[tuple[float, IncidentRecord]] = []
        for rec in records:
            score = cosine_similarity(query_embedding, rec.embedding)
            if score >= min_similarity:
                scored.append((score, rec))
        scored.sort(key=lambda t: t[0], reverse=True)
        out: list[SimilarIncident] = []
        for score, rec in scored[:top_k]:
            excerpt = rec.root_cause[:240] + ("…" if len(rec.root_cause) > 240 else "")
            out.append(
                SimilarIncident(
                    incident_id=rec.incident_id,
                    scenario_id=rec.scenario_id,
                    timestamp=rec.timestamp,
                    title=rec.title,
                    summary=rec.postmortem_summary,
                    root_cause_excerpt=excerpt,
                    similarity=round(score, 4),
                )
            )
        return out
