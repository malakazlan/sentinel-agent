"""Cosine-similarity search over the regulatory corpus.

Phase 8 / ADR-019. The corpus is a JSONL file at
``data/regulatory/corpus.jsonl``. Each line is one clause. The search
embeds each clause via Vertex ``text-embedding-004`` on first use and
caches the embeddings in-process for the lifetime of the search object.

The search returns a list of ``CitedClauseRecord`` ranked by cosine
similarity to the query.

**Hallucination guard.** ``last_results`` tracks the most recent set of
clauses returned, keyed by ``(regulation_short_name, clause_id)``.
``ComplianceOfficerAgent`` uses this set to validate every citation in
its output. Any citation tuple not in ``last_results`` fails the
post-LLM validator. This is the contract that makes ADR-019's promise
("hallucinated cites are a disqualifier") enforceable in code, not just
in the prompt.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CitedClauseRecord:
    """One clause returned by ``RegulatorySearch.semantic_search``."""

    regulation_short_name: str
    regulation_full_name: str
    clause_id: str
    clause_title: str
    clause_text: str
    source_url: str
    retrieved_at: str
    applicable_workflows: tuple[str, ...]
    reporting_obligation: Optional[dict[str, Any]]
    similarity: float

    @property
    def citation_key(self) -> tuple[str, str]:
        """The ``(regulation_short_name, clause_id)`` tuple used by the
        hallucination guard."""
        return (self.regulation_short_name, self.clause_id)


@dataclass
class RegulatorySearch:
    """In-process cosine search over the regulatory corpus.

    Construct with ``RegulatorySearch.from_corpus()`` to pick up the
    default corpus path; pass a ``corpus_path`` to override for tests.
    """

    corpus_path: Path
    _records: list[dict[str, Any]] = field(default_factory=list)
    _embeddings: list[list[float]] = field(default_factory=list)
    _embedder: Optional[Any] = None
    last_results: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def from_corpus(cls, corpus_path: Optional[Path] = None) -> "RegulatorySearch":
        """Build a search over the configured corpus path."""
        if corpus_path is None:
            env_path = os.environ.get("SENTINEL_REGULATORY_CORPUS")
            corpus_path = (
                Path(env_path)
                if env_path
                else Path("data/regulatory/corpus.jsonl")
            )
        inst = cls(corpus_path=corpus_path)
        inst._load()
        return inst

    # ── corpus + embedding bootstrap ───────────────────────────────────

    def _load(self) -> None:
        """Read the corpus JSONL into memory."""
        if not self.corpus_path.exists():
            _logger.warning(
                "Regulatory corpus not found at %s; search will return no "
                "matches and the ComplianceOfficer will emit the "
                "'no specific regulation matched' fallback.",
                self.corpus_path,
            )
            self._records = []
            return
        records: list[dict[str, Any]] = []
        with self.corpus_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        self._records = records

    def _ensure_embeddings(self) -> None:
        """Compute embeddings for every clause on first use.

        Lazy so that test fixtures using a tiny corpus don't trigger a
        live Vertex call. The actual embed-call wrapper lives in the
        existing ``IncidentMemoryStore``'s embedding pipeline; we use
        the same ``text-embedding-004`` model via the shared utility.
        """
        if self._embeddings or not self._records:
            return
        try:
            from sentinel.memory.embedder import embed_text
            embedder = embed_text
        except ImportError:
            _logger.warning(
                "Embedding pipeline unavailable; falling back to "
                "token-overlap scoring for the regulatory corpus."
            )
            embedder = None
        self._embedder = embedder
        embeddings: list[list[float]] = []
        for rec in self._records:
            text = self._composite_text(rec)
            if embedder is None:
                embeddings.append([])  # marker for token-overlap fallback
            else:
                embeddings.append(embedder(text))
        self._embeddings = embeddings

    @staticmethod
    def _composite_text(rec: dict[str, Any]) -> str:
        """Build the embedding input from short_name + title + text."""
        return " — ".join(
            [
                rec.get("regulation_short_name", ""),
                rec.get("clause_id", ""),
                rec.get("clause_title", ""),
                rec.get("clause_text", ""),
            ]
        )

    # ── search ─────────────────────────────────────────────────────────

    def semantic_search(
        self,
        query: str,
        *,
        k: int = 5,
        workflow_filter: Optional[str] = None,
    ) -> list[CitedClauseRecord]:
        """Return the top-``k`` clauses most similar to ``query``.

        When ``workflow_filter`` is set (e.g. ``"fraud detection"``),
        candidates are restricted to those whose ``applicable_workflows``
        list contains that string. Cosine similarity over the same
        Vertex embedding pipeline used elsewhere in Sentinel; falls back
        to token-overlap scoring when the embedder is unreachable.
        """
        if not self._records:
            self.last_results = set()
            return []
        self._ensure_embeddings()

        candidates = [
            (i, rec) for i, rec in enumerate(self._records)
            if workflow_filter is None
            or workflow_filter in (rec.get("applicable_workflows") or [])
        ]
        scored: list[tuple[float, dict[str, Any]]] = []
        if self._embedder is not None:
            q_emb = self._embedder(query)
            for i, rec in candidates:
                sim = _cosine(q_emb, self._embeddings[i])
                scored.append((sim, rec))
        else:
            for i, rec in candidates:
                sim = _token_overlap(query, self._composite_text(rec))
                scored.append((sim, rec))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[: max(0, k)]

        out: list[CitedClauseRecord] = []
        for sim, rec in top:
            out.append(
                CitedClauseRecord(
                    regulation_short_name=rec["regulation_short_name"],
                    regulation_full_name=rec.get("regulation_full_name", ""),
                    clause_id=rec["clause_id"],
                    clause_title=rec.get("clause_title", ""),
                    clause_text=rec.get("clause_text", ""),
                    source_url=rec.get("source_url", ""),
                    retrieved_at=rec.get("retrieved_at", ""),
                    applicable_workflows=tuple(rec.get("applicable_workflows", [])),
                    reporting_obligation=rec.get("reporting_obligation"),
                    similarity=float(sim),
                )
            )
        self.last_results = {r.citation_key for r in out}
        return out

    # ── hallucination guard ────────────────────────────────────────────

    def is_citation_grounded(self, regulation_short_name: str, clause_id: str) -> bool:
        """Return True iff ``(regulation_short_name, clause_id)`` was in
        the most recent ``semantic_search`` result set.

        The ComplianceOfficer's post-LLM validator calls this for every
        cited clause. False → that citation gets rejected and replaced
        with the literal 'no specific regulation matched' fallback per
        ADR-019.
        """
        return (regulation_short_name, clause_id) in self.last_results


# ── tiny linalg + fallback ────────────────────────────────────────────


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _token_overlap(a: str, b: str) -> float:
    """Bag-of-words Jaccard for the no-Vertex fallback path."""
    ta = {t for t in a.lower().split() if len(t) > 2}
    tb = {t for t in b.lower().split() if len(t) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
