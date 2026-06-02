"""Vertex AI Vector Search backend for the incident memory store
(Phase 7 / ADR-013 reversal — full production-grade memory layer).

Architecture: dual-write pattern.

- **ANN layer (Vector Search):** Matching Engine index stores embeddings,
  IDs, and lightweight restricts (scenario_id, severity). The endpoint
  serves nearest-neighbor queries with sub-100ms latency.
- **Metadata layer (local JSONL sidecar):** Full ``IncidentRecord`` rows
  (title, summary, root_cause, etc.) live in a local JSONL keyed by
  ``incident_id``. Vector Search returns IDs; we load full records from
  the sidecar.

Why dual-write rather than a heavier metadata store (Firestore / Cloud SQL):
the hackathon scope doesn't justify provisioning a second managed
service. The JSONL sidecar is bit-identical to the local-only fallback
(``incident_memory.IncidentMemoryStore``), so swapping back is a single
env-var flip with no data migration.

The store is loaded lazily — first access constructs the index +
endpoint handles from the JSON config emitted by
``scripts/setup_vector_search.py``. If the config is missing or the
endpoint is unreachable, the store raises ``VectorSearchUnavailable`` —
the recall path catches and degrades to the local store, never crashes
the Coordinator.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from sentinel.memory.incident_memory import (
    IncidentMemoryStore,
    IncidentRecord,
    SimilarIncident,
)

_logger = logging.getLogger(__name__)

# Config file written by scripts/setup_vector_search.py. Holds the index
# + endpoint resource names so the runtime doesn't reconstruct them from
# scratch on every boot.
_DEFAULT_CONFIG_PATH = "data/memory/vector_search_config.json"


class VectorSearchUnavailable(RuntimeError):
    """Raised when the Vector Search backend cannot be reached.

    Callers (specifically ``sentinel.memory.recall``) catch this and fall
    back to the local store. Never bubbles up to the Coordinator.
    """


def get_config_path() -> Path:
    """Resolve the Vector Search config path from env or default."""
    raw = os.environ.get("SENTINEL_VECTOR_SEARCH_CONFIG", _DEFAULT_CONFIG_PATH)
    return Path(raw)


class VectorSearchMemoryStore:
    """Vertex AI Vector Search backend with JSONL metadata sidecar.

    Matches the ``IncidentMemoryStore`` public interface exactly so callers
    don't branch on backend. ``append()`` dual-writes; ``top_k_similar()``
    queries Vector Search then hydrates full records from the sidecar.
    """

    def __init__(
        self,
        index_resource_name: str,
        endpoint_resource_name: str,
        deployed_index_id: str,
        sidecar_store: IncidentMemoryStore,
    ) -> None:
        """Construct from already-resolved resource names. Use
        ``from_config()`` to load from the on-disk config emitted by the
        setup script.
        """
        self._index_name = index_resource_name
        self._endpoint_name = endpoint_resource_name
        self._deployed_index_id = deployed_index_id
        self._sidecar = sidecar_store
        # aiplatform resources are heavy to construct; build lazily on
        # first use rather than at __init__ time.
        self._index: Optional[Any] = None
        self._endpoint: Optional[Any] = None

    # ── construction ──────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config_path: Optional[Path] = None,
        sidecar_store: Optional[IncidentMemoryStore] = None,
    ) -> "VectorSearchMemoryStore":
        """Load resource names from the on-disk config and return a store.

        Raises ``VectorSearchUnavailable`` if the config is missing or
        malformed — the recall path catches this and falls back.
        """
        path = config_path if config_path is not None else get_config_path()
        if not path.exists():
            raise VectorSearchUnavailable(
                f"Vector Search config missing at {path}. Run "
                f"`scripts/setup_vector_search.py` once to provision the "
                f"index + endpoint."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VectorSearchUnavailable(
                f"Vector Search config at {path} is unreadable: {exc}"
            ) from exc

        required = ("index_resource_name", "endpoint_resource_name", "deployed_index_id")
        missing = [k for k in required if not payload.get(k)]
        if missing:
            raise VectorSearchUnavailable(
                f"Vector Search config at {path} missing keys: {missing}"
            )

        return cls(
            index_resource_name=payload["index_resource_name"],
            endpoint_resource_name=payload["endpoint_resource_name"],
            deployed_index_id=payload["deployed_index_id"],
            sidecar_store=sidecar_store or IncidentMemoryStore(),
        )

    # ── lazy aiplatform handles ───────────────────────────────────────────

    def _get_index(self) -> Any:
        if self._index is None:
            try:
                from google.cloud import aiplatform
            except ImportError as exc:
                raise VectorSearchUnavailable(
                    "google-cloud-aiplatform not installed"
                ) from exc
            try:
                self._index = aiplatform.MatchingEngineIndex(
                    index_name=self._index_name
                )
            except Exception as exc:  # noqa: BLE001 — degraded path catches
                raise VectorSearchUnavailable(
                    f"Failed to attach to index {self._index_name}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        return self._index

    def _get_endpoint(self) -> Any:
        if self._endpoint is None:
            try:
                from google.cloud import aiplatform
            except ImportError as exc:
                raise VectorSearchUnavailable(
                    "google-cloud-aiplatform not installed"
                ) from exc
            try:
                self._endpoint = aiplatform.MatchingEngineIndexEndpoint(
                    index_endpoint_name=self._endpoint_name
                )
            except Exception as exc:  # noqa: BLE001 — degraded path catches
                raise VectorSearchUnavailable(
                    f"Failed to attach to endpoint {self._endpoint_name}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        return self._endpoint

    # ── writes (dual: Vector Search + sidecar) ───────────────────────────

    def append(self, record: IncidentRecord) -> None:
        """Upsert into Vector Search + append to the metadata sidecar.

        Vector Search upsert is the authoritative path for queries; the
        sidecar is the source of truth for full record contents. If the
        Vector Search upsert fails (network, quota), we raise — the
        recall path will see the next read fail and fall back. The
        sidecar write succeeds first so the data is never lost.
        """
        # 1) Always write the sidecar first so the data lands somewhere.
        self._sidecar.append(record)

        # 2) Then upsert the datapoint to Vector Search.
        try:
            from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import (
                Namespace,
            )
        except ImportError:
            Namespace = None  # type: ignore[assignment]

        index = self._get_index()
        datapoint = {
            "datapoint_id": record.incident_id,
            "feature_vector": record.embedding,
            # Restricts let us filter by scenario at query time if needed.
            "restricts": [
                {"namespace": "scenario_id", "allow_list": [record.scenario_id]},
            ],
        }
        try:
            index.upsert_datapoints(datapoints=[datapoint])
        except Exception as exc:  # noqa: BLE001 — degraded path catches
            raise VectorSearchUnavailable(
                f"Vector Search upsert failed for {record.incident_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ── reads ─────────────────────────────────────────────────────────────

    def load_all(self) -> list[IncidentRecord]:
        """Delegate to the sidecar — Vector Search doesn't store metadata."""
        return self._sidecar.load_all()

    # ── retrieval (ANN via Vector Search; hydrate via sidecar) ────────────

    def top_k_similar(
        self,
        query_embedding: list[float],
        top_k: int = 3,
        min_similarity: float = 0.5,
    ) -> list[SimilarIncident]:
        """Query Vector Search for the top-K IDs, then hydrate from sidecar.

        Vector Search returns nearest-neighbor IDs + distances. We convert
        cosine distance → cosine similarity (`1 - distance`), filter by
        ``min_similarity``, then look up full record contents from the
        sidecar (which stays in sync via dual-write).

        Raises ``VectorSearchUnavailable`` on transport failure so the
        recall path can fall back.
        """
        if not query_embedding:
            return []

        endpoint = self._get_endpoint()
        try:
            response = endpoint.find_neighbors(
                deployed_index_id=self._deployed_index_id,
                queries=[query_embedding],
                num_neighbors=max(1, int(top_k)),
            )
        except Exception as exc:  # noqa: BLE001 — degraded path catches
            raise VectorSearchUnavailable(
                f"Vector Search query failed: {type(exc).__name__}: {exc}"
            ) from exc

        # ``find_neighbors`` returns list[list[MatchNeighbor]] — one list per query.
        if not response:
            return []
        neighbors = response[0]

        # Hydrate from sidecar.
        sidecar_records = {r.incident_id: r for r in self._sidecar.load_all()}

        out: list[SimilarIncident] = []
        for n in neighbors:
            distance = getattr(n, "distance", None)
            if distance is None:
                continue
            # Vertex Vector Search COSINE_DISTANCE returns 1 - similarity.
            # Clamp to [0, 1] in case of float drift.
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            if similarity < min_similarity:
                continue
            rec = sidecar_records.get(getattr(n, "id", None) or "")
            if rec is None:
                # ID returned by Vector Search has no sidecar entry — log
                # and skip rather than fabricate. Indicates the sidecar
                # got truncated or the index has stale points.
                _logger.warning(
                    "Vector Search returned id=%s with no sidecar record",
                    getattr(n, "id", "?"),
                )
                continue
            excerpt = rec.root_cause[:240] + ("…" if len(rec.root_cause) > 240 else "")
            out.append(
                SimilarIncident(
                    incident_id=rec.incident_id,
                    scenario_id=rec.scenario_id,
                    timestamp=rec.timestamp,
                    title=rec.title,
                    summary=rec.postmortem_summary,
                    root_cause_excerpt=excerpt,
                    similarity=round(similarity, 4),
                )
            )
        return out
