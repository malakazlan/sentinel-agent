"""Scripted financial-services incident scenarios — Phase 4 step 5.

Each ``IncidentScenario`` is a structured production-shape alert payload
(the kind a PagerDuty / Alertmanager / bank-internal monitoring webhook
would send to Sentinel) plus the metadata needed to drive an end-to-end
pipeline run.

These three are chosen to exercise the three FinServ workflows the
``00-mission.md`` positioning targets:

- Fraud detection (false-positive burst — operational/revenue impact)
- KYC/AML (sanctions-list hallucination — regulatory exposure)
- Lending (latency regression after deploy — SLA breach)

Adding a scenario is intentionally lightweight: append an
``IncidentScenario`` instance to ``SCENARIOS``. Each one auto-generates
the initial pipeline prompt via ``initial_prompt()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sentinel.agents.schemas import Severity


@dataclass(frozen=True)
class IncidentScenario:
    """One scripted incident the end-to-end pipeline can exercise."""

    id: str
    title: str
    short_description: str  # one-line summary for buttons / lists
    severity: Severity
    alert_payload: dict[str, Any]
    workflow: str  # human-readable FinServ workflow, e.g. "fraud detection"
    watched_project: str  # Phoenix project name for this scenario's synthetic traces

    @property
    def incident_id(self) -> str:
        """Stable identifier from the alert payload, for cross-stage referencing."""
        return self.alert_payload.get("alert_id", self.id)

    def initial_prompt(self) -> str:
        """The prompt for the first Coordinator turn (investigate)."""
        payload_json = json.dumps(self.alert_payload, indent=2)
        return (
            "Production incident alert received:\n```json\n"
            + payload_json
            + "\n```\nInvestigate this incident — pull the recent traces and "
            "describe what's happening."
        )


# ── The three scripted scenarios ───────────────────────────────────────────


SCENARIOS: list[IncidentScenario] = [
    IncidentScenario(
        id="fraud-fp-burst",
        title="Fraud detection — false-positive burst",
        short_description=(
            "FP rate spiked 3x in 90 seconds; 1247 legitimate transactions blocked, "
            "312 customer accounts frozen, support inbox flooding."
        ),
        severity="P1",
        workflow="fraud detection",
        watched_project="fraud-detector-prod",
        alert_payload={
            "alert_id": "fraud-fp-spike-20260524T204248Z",
            "source": "fraud-detector-prod-us-central1",
            "alert_type": "false_positive_burst",
            "severity": "P1",
            "metric": {
                "name": "fp_rate_5m",
                "current": 0.213,
                "baseline": 0.072,
                "threshold": 0.150,
                "delta_pct": 196,
            },
            "window": {
                "started_at": "2026-05-24T20:42:48Z",
                "duration_seconds": 90,
            },
            "impact": {
                "blocked_transactions": 1247,
                "estimated_revenue_at_risk_usd": 84300,
                "frozen_accounts": 312,
            },
            "watched_system": {
                "ai_model": "fraud-classifier-v2.3.1",
                "deploy_commit": "a3f9e22",
                "deploy_age_minutes": 18,
            },
        },
    ),
    IncidentScenario(
        id="kyc-sanctions-hallucination",
        title="KYC/AML — sanctions-list hallucination",
        short_description=(
            "LLM-based PEP screener returned 7 fabricated sanctions matches in "
            "120 seconds; 0 real matches in the same window. Regulatory disclosure "
            "threshold breached."
        ),
        severity="P0",
        workflow="KYC/AML screening",
        watched_project="kyc-screener-prod",
        alert_payload={
            "alert_id": "kyc-pep-fabrication-20260525T103015Z",
            "source": "kyc-screener-prod-eu-west1",
            "alert_type": "hallucinated_sanctions_match",
            "severity": "P0",
            "window": {
                "started_at": "2026-05-25T10:30:15Z",
                "duration_seconds": 120,
            },
            "details": {
                "model": "kyc-pep-screener-v3.1.0",
                "fabricated_matches": 7,
                "real_matches_in_same_window": 0,
                "verification_method": "post-hoc human review against OFAC + EU consolidated lists",
                "affected_customers": 7,
                "regulatory_disclosure_threshold_breached": True,
                "applicable_regulations": ["FCA SUP 15.3", "EU 5MLD Article 33"],
            },
            "watched_system": {
                "ai_model": "kyc-pep-screener-v3.1.0",
                "deploy_commit": "b2d8e91",
                "deploy_age_minutes": 6,
                "upstream_data_source": "ofac-consolidated-list-cached-2026-05-23",
            },
        },
    ),
    IncidentScenario(
        id="lending-latency-regression",
        title="Lending — latency regression after model deploy",
        short_description=(
            "Underwriting model p99 jumped 280ms → 4234ms within 8 minutes of "
            "deploy; 89 underwriting decisions delayed, 12 user-facing timeouts, "
            "SLA breached."
        ),
        severity="P2",
        workflow="lending / credit underwriting",
        watched_project="underwriting-prod",
        alert_payload={
            "alert_id": "lending-p99-regression-20260524T143022Z",
            "source": "underwriting-prod-us-east1",
            "alert_type": "latency_regression",
            "severity": "P2",
            "metric": {
                "name": "p99_latency_ms_5m",
                "current": 4234,
                "baseline": 280,
                "threshold": 800,
                "delta_pct": 1412,
            },
            "window": {
                "started_at": "2026-05-24T14:30:22Z",
                "duration_seconds": 600,
            },
            "impact": {
                "underwriting_decisions_delayed": 89,
                "user_facing_timeouts": 12,
                "sla_breach": True,
                "sla_p99_target_ms": 800,
            },
            "watched_system": {
                "ai_model": "underwriting-credit-v4.0.0",
                "deploy_commit": "f8c4a1e",
                "deploy_age_minutes": 8,
                "previous_version": "underwriting-credit-v3.7.2",
            },
        },
    ),
]


def get_scenario(scenario_id: str) -> IncidentScenario:
    """Look up a scenario by id; raise ``KeyError`` if unknown."""
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    raise KeyError(
        f"unknown scenario id: {scenario_id!r}. "
        f"Known: {[s.id for s in SCENARIOS]}"
    )
