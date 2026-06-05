"""Phase 8 / ADR-019 — Regulatory corpus + RAG layer.

Public exports:

- ``RegulatorySearch`` — cosine-similarity search over a curated corpus
  of regulator clauses.
- ``CitedClause`` — what the search returns. Mirrors the schema field of
  the same name in ``sentinel.agents.schemas``.

The corpus itself lives at ``data/regulatory/corpus.jsonl``. The repo
ships with a hand-curated seed; ``corpus_builder.py`` extends it from
live regulator URLs on demand.
"""

from sentinel.regulatory.search import RegulatorySearch, CitedClauseRecord  # noqa: F401

__all__ = ["RegulatorySearch", "CitedClauseRecord"]
