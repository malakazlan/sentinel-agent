"""SentinelMonitor — Phase 8 / ADR-026.

Recursive observability: watches Sentinel's own telemetry. Reads from
the prompt-history store + per-stage latency aggregates, computes
rolling means + 7-run trend slopes, classifies each agent's health.

The HTTP-facing endpoint is in ``sentinel.api.phase8_routes`` at
``GET /sentinel/health``; this module computes the underlying snapshot
so the route + a CLI surface share one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sentinel.memory.prompt_history import (
    PromptHistoryStore,
    shared_store,
)


HEALTHY_THRESHOLD = 0.90
WATCH_THRESHOLD = 0.80
DEGRADED_THRESHOLD = 0.70


class AgentHealthSnapshot(BaseModel):
    """One agent's health snapshot for the /sentinel-health page."""

    model_config = ConfigDict(extra="forbid")
    agent_name: str
    sample_count: int
    avg_aggregate_score: float
    avg_rubric_scores: dict[str, float] = Field(default_factory=dict)
    trend_slope: float = Field(
        ...,
        description=(
            "Linear regression slope over the last N runs' aggregate "
            "scores. Negative = trending worse; positive = trending "
            "better. Bounded by [-1, +1] practical range."
        ),
    )
    health_flag: str  # "healthy" | "watch" | "degraded" | "underperforming"
    last_record_timestamp: str
    insufficient_history: bool = False


class SentinelHealthReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentHealthSnapshot] = Field(default_factory=list)
    history_total: int
    healthy_count: int
    watch_count: int
    degraded_count: int
    underperforming_count: int


def _classify(score: float) -> str:
    if score >= HEALTHY_THRESHOLD:
        return "healthy"
    if score >= WATCH_THRESHOLD:
        return "watch"
    if score >= DEGRADED_THRESHOLD:
        return "degraded"
    return "underperforming"


def _trend_slope(scores: list[float]) -> float:
    """Simple least-squares slope. Returns 0 when n < 3 (insufficient)."""
    n = len(scores)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(scores) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, scores))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den else 0.0


def build_health_report(
    store: Optional[PromptHistoryStore] = None,
    *,
    window: int = 7,
    min_samples_for_trend: int = 3,
) -> SentinelHealthReport:
    """Aggregate per-agent health snapshots into a SentinelHealthReport."""
    store = store or shared_store()
    snapshots: list[AgentHealthSnapshot] = []
    for name in store.all_agent_names():
        rollup = store.rollup_for_agent(name)
        if rollup is None:
            continue
        recent = store.recent_for_agent(name, window=window)
        scores = [float(r["aggregate_critic_score"]) for r in recent]
        insufficient = len(scores) < min_samples_for_trend
        slope = 0.0 if insufficient else _trend_slope(scores)
        snapshots.append(AgentHealthSnapshot(
            agent_name=rollup.agent_name,
            sample_count=rollup.sample_count,
            avg_aggregate_score=round(rollup.avg_aggregate_score, 4),
            avg_rubric_scores={
                k: round(v, 4) for k, v in rollup.avg_rubric_scores.items()
            },
            trend_slope=round(slope, 6),
            health_flag=_classify(rollup.avg_aggregate_score),
            last_record_timestamp=rollup.last_record_timestamp,
            insufficient_history=insufficient,
        ))
    flag_counts = {"healthy": 0, "watch": 0, "degraded": 0, "underperforming": 0}
    for s in snapshots:
        flag_counts[s.health_flag] = flag_counts.get(s.health_flag, 0) + 1
    return SentinelHealthReport(
        agents=snapshots,
        history_total=len(store.load_all()),
        healthy_count=flag_counts["healthy"],
        watch_count=flag_counts["watch"],
        degraded_count=flag_counts["degraded"],
        underperforming_count=flag_counts["underperforming"],
    )
