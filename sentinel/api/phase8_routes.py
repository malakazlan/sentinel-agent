"""Phase 8 / ADR-027 — additive FastAPI routes for the new UI surface.

This module adds:

- ``GET /patterns``                       — mined pattern proposals (TASK 4)
- ``POST /patterns/{cluster_id}/accept``  — accept a pattern proposal
- ``POST /patterns/{cluster_id}/reject``  — reject a pattern proposal
- ``GET /sentinel/health``                — Sentinel-watches-Sentinel (TASK 8)
- ``GET /prompts``                        — list per-agent prompt rollups
- ``GET /prompts/{agent_name}/history``   — full per-agent history
- ``GET /evals/trends``                   — critic-score trends per agent
- ``GET /architecture``                   — agent registry shape
- ``GET /incidents-history``              — list past incidents w/ filters

All routes are READ-ONLY except the two pattern decisions. The existing
``/incidents`` contract is untouched; ADR-019 is the locked baseline.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from sentinel.agents.pattern_miner import (
    PatternProposal,
    load_pattern_decision,
    mine_patterns,
    persist_pattern_decision,
)
from sentinel.memory.prompt_history import shared_store as shared_prompt_history


router = APIRouter()


# ── Patterns (TASK 4) ─────────────────────────────────────────────────────


@router.get("/patterns", response_model=list[PatternProposal])
def list_patterns() -> list[PatternProposal]:
    """Mine + return current pattern proposals from the incident memory.

    The miner runs on-demand each call — for the hackathon corpora this
    is fast. In production this would be backed by a periodic job; the
    interface is identical.
    """
    incidents = _load_incidents_for_mining()
    proposals = mine_patterns(incidents)
    # Attach persisted decisions (status field).
    out: list[PatternProposal] = []
    for p in proposals:
        decision = load_pattern_decision(p.cluster_id)
        if decision in ("accepted", "rejected"):
            p = p.model_copy(update={"status": decision})
        out.append(p)
    return out


@router.post("/patterns/{cluster_id}/accept")
def accept_pattern(cluster_id: str) -> dict[str, str]:
    persist_pattern_decision(cluster_id, "accepted")
    return {"cluster_id": cluster_id, "status": "accepted"}


@router.post("/patterns/{cluster_id}/reject")
def reject_pattern(cluster_id: str) -> dict[str, str]:
    persist_pattern_decision(cluster_id, "rejected")
    return {"cluster_id": cluster_id, "status": "rejected"}


def _load_incidents_for_mining() -> list[dict[str, Any]]:
    """Read the incident memory store and shape it for the miner.

    Returns an empty list when the store is empty or unreachable —
    ``/patterns`` then returns ``[]`` rather than failing.
    """
    try:
        from sentinel.memory.recall import _shared_store

        store = _shared_store()
        records = store.load_all() if hasattr(store, "load_all") else []
    except Exception:
        records = []
    out: list[dict[str, Any]] = []
    for r in records:
        # Support both dict and dataclass / Pydantic record shapes.
        out.append({
            "incident_id": _attr(r, "incident_id", ""),
            "scenario_id": _attr(r, "scenario_id", ""),
            "root_cause": _attr(r, "root_cause", ""),
            "remediation_summary": _attr(r, "remediation_summary", ""),
            "embedding": _attr(r, "embedding", []) or [],
        })
    return out


def _attr(rec: Any, key: str, default: Any) -> Any:
    """Read ``key`` off a dict or a dataclass / model."""
    if isinstance(rec, dict):
        return rec.get(key, default)
    return getattr(rec, key, default)


# ── Sentinel-watches-Sentinel (TASK 8) ────────────────────────────────────


@router.get("/sentinel/health")
def sentinel_health() -> dict[str, Any]:
    """Return Sentinel's own per-agent health snapshot.

    Delegates to ``sentinel.agents.sentinel_monitor.build_health_report``
    so the page + a future CLI share one computation. ADR-026.
    """
    from sentinel.agents.sentinel_monitor import build_health_report
    report = build_health_report()
    return report.model_dump()


# ── Human override gates (TASK 7 — ADR-025) ───────────────────────────────


@router.get("/gates")
def list_gates() -> dict[str, Any]:
    """Return all pending (unresolved) approval gates."""
    from sentinel.agents.human_override import list_pending
    pending = list_pending()
    return {"gates": [{
        "gate_id": g.gate_id,
        "incident_id": g.incident_id,
        "action_type": g.action_type,
        "action_summary": g.action_summary,
        "requested_at_iso": g.requested_at_iso,
        "timeout_at_iso": g.timeout_at_iso,
    } for g in pending]}


@router.post("/incidents/{incident_id}/gate/{gate_id}/approve")
def approve_gate(incident_id: str, gate_id: str) -> dict[str, str]:
    from sentinel.agents.human_override import resolve_gate
    resolve_gate(gate_id, "approved")
    return {"gate_id": gate_id, "incident_id": incident_id, "decision": "approved"}


@router.post("/incidents/{incident_id}/gate/{gate_id}/reject")
def reject_gate(incident_id: str, gate_id: str) -> dict[str, str]:
    from sentinel.agents.human_override import resolve_gate
    resolve_gate(gate_id, "rejected")
    return {"gate_id": gate_id, "incident_id": incident_id, "decision": "rejected"}


# ── Prompts (TASK 3 → /prompts page) ─────────────────────────────────────


@router.get("/prompts")
def prompts_overview() -> dict[str, Any]:
    """Lists per-agent prompt versions + scores + sample counts."""
    store = shared_prompt_history()
    out: list[dict[str, Any]] = []
    for name in store.all_agent_names():
        rollup = store.rollup_for_agent(name)
        if rollup is None:
            continue
        out.append({
            "agent_name": rollup.agent_name,
            "current_prompt_version": rollup.current_prompt_version,
            "sample_count": rollup.sample_count,
            "avg_aggregate_score": round(rollup.avg_aggregate_score, 4),
            "last_record_timestamp": rollup.last_record_timestamp,
        })
    return {"agents": out}


@router.get("/prompts/{agent_name}/history")
def prompts_history(agent_name: str) -> dict[str, Any]:
    store = shared_prompt_history()
    records = store.recent_for_agent(agent_name, window=200)
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"no prompt history for agent {agent_name!r}",
        )
    return {"agent_name": agent_name, "records": records}


# ── Evals trends (TASK 9 / 9 — /evals page) ──────────────────────────────


@router.get("/evals/trends")
def evals_trends() -> dict[str, Any]:
    """Per-agent + per-rubric-dimension trends from prompt history."""
    store = shared_prompt_history()
    by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in store.load_all():
        by_agent[r["agent_name"]].append({
            "timestamp_iso": r.get("timestamp_iso", ""),
            "aggregate": r.get("aggregate_critic_score"),
            "rubric_scores": r.get("rubric_scores", {}),
        })
    out: list[dict[str, Any]] = []
    for agent_name, points in by_agent.items():
        if not points:
            continue
        rubric_avgs: dict[str, list[float]] = defaultdict(list)
        agg_vals: list[float] = []
        for p in points:
            agg_vals.append(float(p["aggregate"] or 0))
            for k, v in (p.get("rubric_scores") or {}).items():
                rubric_avgs[k].append(float(v))
        out.append({
            "agent_name": agent_name,
            "point_count": len(points),
            "avg_aggregate": round(statistics.fmean(agg_vals), 4) if agg_vals else 0,
            "avg_rubric": {
                k: round(statistics.fmean(v), 4) for k, v in rubric_avgs.items()
            },
            "points": points,
        })
    return {"agents": out}


# ── Architecture registry (TASK 9 — /architecture page) ──────────────────


_AGENT_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "coordinator",
        "role": "Plans the investigation; routes to sub-agents via A2A.",
        "model": "gemini-3.1-pro",
        "adr": "n/a (root agent)",
    },
    {
        "name": "trace_analyzer",
        "role": "Pulls Phoenix trace windows; computes anomaly statistics.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-008",
    },
    {
        "name": "eval_runner",
        "role": "Single-suite eval; hallucination + faithfulness.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-005",
    },
    {
        "name": "parallel_eval_runner",
        "role": "Phase 7 fan-out: 4 evals in parallel.",
        "model": "ParallelAgent",
        "adr": "ADR-012",
    },
    {
        "name": "deploy_correlator",
        "role": "Queries GitHub MCP for commits/PRs around the incident window.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-014",
    },
    {
        "name": "root_cause",
        "role": "Proposes ranked causal hypotheses.",
        "model": "gemini-3.1-pro",
        "adr": "ADR-008",
    },
    {
        "name": "remediation",
        "role": "Drafts a structured RemediationPlan JSON.",
        "model": "gemini-3.1-pro",
        "adr": "ADR-008",
    },
    {
        "name": "customer_impact_quantifier",
        "role": "Quantifies dollars / customer count / revenue loss with audit citations.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-018",
    },
    {
        "name": "postmortem",
        "role": "Google-SRE-format RCA generator.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-008",
    },
    {
        "name": "critic",
        "role": "Four-dimension rubric scorer over draft postmortems.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-016",
    },
    {
        "name": "compliance_officer",
        "role": "Cites regulator clauses + reporting obligations via curated corpus.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-019",
    },
    {
        "name": "slack_announcer",
        "role": "Posts lifecycle updates to a Slack channel (env-gated).",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-015",
    },
    {
        "name": "prompt_evolver",
        "role": "Authors 2-3 prompt variants when an agent underperforms.",
        "model": "gemini-3.1-pro",
        "adr": "ADR-020",
    },
    {
        "name": "pattern_miner",
        "role": "Clusters past incidents; proposes recurring-pattern mitigations.",
        "model": "n/a (deterministic clustering)",
        "adr": "ADR-021",
    },
    {
        "name": "drift_detective",
        "role": "KS + PSI on watched-system distributions.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-022",
    },
    {
        "name": "bias_fairness_auditor",
        "role": "4/5ths rule + statistical parity + equalized odds.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-023",
    },
    {
        "name": "slo_guardian",
        "role": "Burn-rate alerting on watched-system SLOs.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-024",
    },
    {
        "name": "human_override",
        "role": "Synchronous approval gate for destructive actions.",
        "model": "n/a (gate)",
        "adr": "ADR-025",
    },
    {
        "name": "sentinel_monitor",
        "role": "Recursive observability: watches Sentinel's own telemetry.",
        "model": "gemini-3.1-flash-lite",
        "adr": "ADR-026",
    },
]


@router.get("/architecture")
def architecture() -> dict[str, Any]:
    return {"agents": _AGENT_REGISTRY}


# ── Incident history (TASK 9 — /history page) ────────────────────────────


@router.get("/incidents-history")
def incidents_history(
    severity: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> dict[str, Any]:
    """Past incidents from the memory store. Filters are optional.

    Decoupled from the existing /incidents endpoint (which is per-id).
    """
    try:
        from sentinel.memory.recall import _shared_store
        store = _shared_store()
        records = store.load_all() if hasattr(store, "load_all") else []
    except Exception:
        records = []
    out: list[dict[str, Any]] = []
    for r in records:
        if severity and _attr(r, "severity", None) != severity:
            continue
        if scenario_id and _attr(r, "scenario_id", None) != scenario_id:
            continue
        out.append({
            "incident_id": _attr(r, "incident_id", None),
            "scenario_id": _attr(r, "scenario_id", None),
            "title": _attr(r, "title", None),
            "severity": _attr(r, "severity", None),
            "completeness_score": _attr(r, "completeness_score", None),
            "timestamp_iso": _attr(r, "timestamp_iso", None),
        })
    return {"incidents": out}
