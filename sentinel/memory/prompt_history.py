"""Per-agent prompt-version + critic-score history. Phase 8 / ADR-020.

Each entry records: which agent ran, which prompt version it used,
what critic dimensions scored, when. Stored as JSONL at
``data/memory/prompt_history.jsonl`` (machine-local). The
``PromptEvolverAgent`` reads rolling averages from this store to decide
when an agent's prompt is underperforming and a refinement should be
proposed.

This is a minimal append-only store. No deletes; no replication. The
local-JSONL backend matches the rest of Phase 7/8 memory components
(``IncidentMemoryStore`` lives next door at ``incident_memory.py``).
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/memory/prompt_history.jsonl")
_DEFAULT_WINDOW = 20  # rolling-window size per agent
_DEFAULT_MIN_SAMPLES = 5  # minimum runs before evolver considers an agent


@dataclass(frozen=True)
class PromptRunRecord:
    """One agent invocation's prompt-version + critic outcome."""

    agent_name: str
    prompt_version: str
    prompt_hash: str  # short hash of the prompt text — for dedup
    incident_id: str
    scenario_id: str
    aggregate_critic_score: float
    rubric_scores: dict[str, float] = field(default_factory=dict)
    timestamp_iso: str = ""

    def to_jsonl(self) -> str:
        return json.dumps(
            {
                "agent_name": self.agent_name,
                "prompt_version": self.prompt_version,
                "prompt_hash": self.prompt_hash,
                "incident_id": self.incident_id,
                "scenario_id": self.scenario_id,
                "aggregate_critic_score": self.aggregate_critic_score,
                "rubric_scores": self.rubric_scores,
                "timestamp_iso": self.timestamp_iso,
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class AgentRollup:
    """Rolling stats for one agent — what the evolver consults."""

    agent_name: str
    current_prompt_version: str
    sample_count: int
    avg_aggregate_score: float
    avg_rubric_scores: dict[str, float]
    last_record_timestamp: str


class PromptHistoryStore:
    """Append-only JSONL store of per-run prompt + score records.

    Thread-safe append via an internal lock. Reads are best-effort and
    do not lock — the orchestrator only writes from one task at a time
    and any read-after-partial-write produces a recoverable result
    (the malformed last line is skipped).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        if path is None:
            env = os.environ.get("SENTINEL_PROMPT_HISTORY_PATH")
            path = Path(env) if env else _DEFAULT_PATH
        self.path = path
        self._lock = threading.Lock()

    def append(self, record: PromptRunRecord) -> None:
        """Append one record. Creates the parent dir + file if missing."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(record.to_jsonl() + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    _logger.warning(
                        "Skipping malformed line in %s — likely partial write.",
                        self.path,
                    )
        return records

    def recent_for_agent(
        self, agent_name: str, window: int = _DEFAULT_WINDOW
    ) -> list[dict[str, Any]]:
        """Return the ``window`` most recent records for ``agent_name``."""
        all_records = self.load_all()
        filtered = [r for r in all_records if r["agent_name"] == agent_name]
        return filtered[-window:]

    def rollup_for_agent(
        self,
        agent_name: str,
        window: int = _DEFAULT_WINDOW,
    ) -> Optional[AgentRollup]:
        """Build the rolling rollup the evolver reads.

        Returns ``None`` when no records exist for ``agent_name``.
        """
        recent = self.recent_for_agent(agent_name, window=window)
        if not recent:
            return None
        avg_agg = statistics.fmean(
            r["aggregate_critic_score"] for r in recent
        )
        # Aggregate per-dimension means.
        rubric_avg: dict[str, list[float]] = {}
        for r in recent:
            for dim, val in (r.get("rubric_scores") or {}).items():
                rubric_avg.setdefault(dim, []).append(float(val))
        rubric_means = {
            dim: statistics.fmean(vals) for dim, vals in rubric_avg.items()
        }
        latest = recent[-1]
        return AgentRollup(
            agent_name=agent_name,
            current_prompt_version=latest.get("prompt_version", "v0"),
            sample_count=len(recent),
            avg_aggregate_score=avg_agg,
            avg_rubric_scores=rubric_means,
            last_record_timestamp=latest.get("timestamp_iso", ""),
        )

    def all_agent_names(self) -> list[str]:
        return sorted({r["agent_name"] for r in self.load_all()})


# Module-level singleton so the orchestrator + the evolver share one
# file handle path. Tests overwrite with a tmp_path-backed instance.
_default_store: Optional[PromptHistoryStore] = None


def shared_store() -> PromptHistoryStore:
    global _default_store
    if _default_store is None:
        _default_store = PromptHistoryStore()
    return _default_store


def record_run(
    *,
    agent_name: str,
    prompt_version: str,
    prompt_hash: str,
    incident_id: str,
    scenario_id: str,
    aggregate_critic_score: float,
    rubric_scores: Optional[dict[str, float]] = None,
) -> None:
    """Convenience writer used by the orchestrator after the critic stage."""
    record = PromptRunRecord(
        agent_name=agent_name,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        incident_id=incident_id,
        scenario_id=scenario_id,
        aggregate_critic_score=float(aggregate_critic_score),
        rubric_scores=rubric_scores or {},
        timestamp_iso=_iso_now(),
    )
    shared_store().append(record)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
