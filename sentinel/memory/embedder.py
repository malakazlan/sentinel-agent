"""Embedding wrapper for the incident memory store (Phase 7 Addition 2).

Uses Vertex-routed ``text-embedding-004`` via google-genai. The same auth
path the rest of the project uses; no new credentials.

Cost: ~$0.000025 per 1k chars input. A typical alert payload + a few past
incidents fits well under a cent per query.

Tests should mock ``embed_text`` directly so the unit suite has no Vertex
dependency.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

_logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-004"

# Lazy genai client — same lifecycle pattern as elsewhere in the codebase.
_client: Optional[object] = None


def _get_client() -> object:
    global _client
    if _client is None:
        from google import genai  # local import to keep module import time cheap

        _client = genai.Client()
    return _client


def embed_text(text: str, model: Optional[str] = None) -> list[float]:
    """Embed a string into a dense vector. Returns an empty list on failure.

    The store / recall code is best-effort: an embedding failure degrades the
    self-improvement loop to "no memory recall this turn" rather than crashing
    the Coordinator.

    Args:
        text: input to embed. Truncated to 8192 chars (text-embedding-004 cap).
        model: embedding model id; defaults to ``text-embedding-004``.

    Returns:
        A list of floats (the dense vector) or ``[]`` on any error.
    """
    if not text:
        return []
    text = text[:8192]
    model_id = model or os.environ.get("SENTINEL_EMBEDDING_MODEL", _DEFAULT_MODEL)
    try:
        from google.genai import types  # local import

        resp = _get_client().models.embed_content(  # type: ignore[attr-defined]
            model=model_id,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        embeddings = getattr(resp, "embeddings", None)
        if not embeddings:
            return []
        values = getattr(embeddings[0], "values", None)
        if not values:
            return []
        return list(values)
    except Exception as exc:  # noqa: BLE001 — best-effort embed
        _logger.warning("embed_text failed: %s", exc, exc_info=True)
        return []
