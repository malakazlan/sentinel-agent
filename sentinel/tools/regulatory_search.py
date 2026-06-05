"""ADK FunctionTool wrapper around ``RegulatorySearch``.

Phase 8 / ADR-019. The tool exposes ``semantic_search`` to the
``ComplianceOfficerAgent``. The wrapper returns a plain-text rendering
of the top-K matches so the LLM can reason about them; the underlying
``RegulatorySearch`` instance also tracks ``last_results`` so the
post-LLM validator can verify every cite the agent emits.

A module-level singleton ``regulatory_search`` is the agent-facing
instance. Tests overwrite it with a corpus stub.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sentinel.regulatory.search import RegulatorySearch

_logger = logging.getLogger(__name__)


# Module-level singleton — exists so the post-LLM validator can read
# ``regulatory_search.last_results`` after a turn completes.
regulatory_search: RegulatorySearch = RegulatorySearch.from_corpus()


def search_regulations(query: str, k: int = 5, workflow_filter: Optional[str] = None) -> str:
    """Search the curated regulatory corpus for clauses matching ``query``.

    Returns a JSON-formatted string with the top ``k`` matches. Each match
    includes ``regulation_short_name``, ``clause_id``, ``clause_title``,
    ``clause_text`` (truncated to 600 chars for the LLM context budget),
    ``source_url``, ``retrieved_at``, ``applicable_workflows``, optional
    ``reporting_obligation`` block, and ``similarity`` score.

    The ComplianceOfficerAgent MUST only cite clauses that appeared in
    the most recent return from this tool — the post-LLM validator
    rejects any other cite as a fabrication.

    Args:
      query: Natural-language description of the incident or the
        compliance question. Examples: "fraud detection model
        false-positive rate spike", "PEP screening hallucination".
      k: Number of matches to return. Default 5; clamped to [1, 10].
      workflow_filter: Optional workflow scope ("fraud detection",
        "KYC/AML screening", "lending / credit underwriting"). When set,
        only clauses whose ``applicable_workflows`` list contains this
        value are returned.

    Returns:
      JSON string. Format:
      ``{"matches": [{...clause fields..., "similarity": 0.83}, ...]}``
    """
    k = max(1, min(int(k), 10))
    matches = regulatory_search.semantic_search(
        query, k=k, workflow_filter=workflow_filter
    )
    out = {
        "matches": [
            {
                "regulation_short_name": m.regulation_short_name,
                "regulation_full_name": m.regulation_full_name,
                "clause_id": m.clause_id,
                "clause_title": m.clause_title,
                "clause_text": m.clause_text[:600],
                "source_url": m.source_url,
                "retrieved_at": m.retrieved_at,
                "applicable_workflows": list(m.applicable_workflows),
                "reporting_obligation": m.reporting_obligation,
                "similarity": round(m.similarity, 4),
            }
            for m in matches
        ]
    }
    return json.dumps(out)
