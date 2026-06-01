"""High-level recall API for the incident memory store (Phase 7 Addition 2).

This is what the Coordinator's briefing synthesizer calls.

Public surface:

- ``recall_similar_incidents(alert_payload, top_k=3)`` — embeds the alert and
  returns the top-K similar past incidents from the local store.
- ``remember_incident(...)`` — writes a completed incident to the store so
  future runs can recall it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sentinel.memory.embedder import embed_text
from sentinel.memory.incident_memory import (
    IncidentMemoryStore,
    IncidentRecord,
    SimilarIncident,
)

_logger = logging.getLogger(__name__)


def _shared_store() -> IncidentMemoryStore:
    """Lazy singleton for the default-path store."""
    return IncidentMemoryStore()


def recall_similar_incidents(
    alert_payload: str,
    top_k: int = 3,
    min_similarity: float = 0.5,
    store: Optional[IncidentMemoryStore] = None,
) -> list[SimilarIncident]:
    """Return up to ``top_k`` past incidents similar to the current alert.

    Embedding failures degrade gracefully to an empty list — the synthesizer
    treats that as "no memory recall this turn" and continues.

    Args:
        alert_payload: the raw alert text (typically the scenario's
            ``initial_prompt()`` or the user's first message). Embedded as a
            single string.
        top_k: max results. Default 3.
        min_similarity: cosine floor. Default 0.5.
        store: dependency-injection seam for tests.

    Returns:
        A list of ``SimilarIncident``, possibly empty.
    """
    if not alert_payload:
        return []
    embedding = embed_text(alert_payload)
    if not embedding:
        return []
    target = store or _shared_store()
    return target.top_k_similar(
        embedding, top_k=top_k, min_similarity=min_similarity
    )


def remember_incident(
    incident_id: str,
    scenario_id: str,
    title: str,
    postmortem_summary: str,
    root_cause: str,
    remediation_summary: str = "",
    store: Optional[IncidentMemoryStore] = None,
) -> bool:
    """Embed a completed incident and append it to the local store.

    Returns ``True`` on success, ``False`` when the embedding step failed
    (the record is NOT written without a valid embedding).
    """
    embedding_input = "\n".join(
        [
            f"title: {title}",
            f"summary: {postmortem_summary}",
            f"root_cause: {root_cause}",
            f"remediation: {remediation_summary}",
        ]
    )
    embedding = embed_text(embedding_input)
    if not embedding:
        _logger.warning(
            "remember_incident: embedding failed; not writing record for %s",
            incident_id,
        )
        return False
    record = IncidentRecord(
        incident_id=incident_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        title=title,
        postmortem_summary=postmortem_summary,
        root_cause=root_cause,
        remediation_summary=remediation_summary,
        embedding=embedding,
    )
    target = store or _shared_store()
    target.append(record)
    return True
