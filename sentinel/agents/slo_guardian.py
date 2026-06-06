"""SLOGuardian — Phase 8 / ADR-024.

Computes per-monitored-service SLO budget burn rate. Two windows:

- **Fast-burn**: budget consumed in last 1h projected → if >2% of monthly
  budget → page-level severity.
- **Slow-burn**: budget consumed in last 6h projected → if >10% of
  monthly budget → ticket-level severity.

Methodology follows the Google SRE Workbook chapter 5. Pure-python, no
LLM call needed for the computation — the SLO target + observed error
rate are sufficient inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class SLOTarget:
    """One SLO budget definition for a monitored service."""

    name: str  # e.g. "accuracy", "p95_latency_ms", "refusal_rate"
    target: float  # e.g. 0.995 for accuracy SLO, or 800ms p95 latency cap
    window_days: int = 30  # default 30-day budget window


@dataclass(frozen=True)
class BurnObservation:
    """Per-window observed error rate."""

    window_hours: float
    observed_error_rate: float  # fraction of bad events in that window
    sample_count: int


class SLOBurnFinding(BaseModel):
    """One SLO budget assessment. Phase 8 / ADR-024."""

    model_config = ConfigDict(extra="forbid")
    slo_name: str
    target: float
    window_days: int
    fast_burn_pct: float
    slow_burn_pct: float
    fast_burn_alert: bool
    slow_burn_alert: bool
    severity: str  # "ok" | "ticket" | "page"


def assess_burn(
    target: SLOTarget,
    fast_obs: BurnObservation,
    slow_obs: BurnObservation,
) -> SLOBurnFinding:
    """Apply the Google SRE Workbook §5 fast-burn / slow-burn rules."""
    monthly_budget = 1.0 - target.target  # acceptable error fraction
    # Project the observed window's burn into a per-month percentage.
    # Fast: 1h * 24 * 30 / 1 = 720 projections per month
    fast_pct = _projected_pct(fast_obs, monthly_budget, target.window_days)
    slow_pct = _projected_pct(slow_obs, monthly_budget, target.window_days)
    fast_alert = fast_pct > 0.02  # 2% in 1h
    slow_alert = slow_pct > 0.10  # 10% in 6h
    severity = "page" if fast_alert else ("ticket" if slow_alert else "ok")
    return SLOBurnFinding(
        slo_name=target.name,
        target=target.target,
        window_days=target.window_days,
        fast_burn_pct=round(fast_pct, 6),
        slow_burn_pct=round(slow_pct, 6),
        fast_burn_alert=fast_alert,
        slow_burn_alert=slow_alert,
        severity=severity,
    )


def _projected_pct(obs: BurnObservation, monthly_budget: float, window_days: int) -> float:
    """Projected fraction of monthly budget consumed at the observed rate."""
    if monthly_budget <= 0 or obs.window_hours <= 0:
        return 0.0
    # consumed_in_window = observed_error_rate * sample_count
    # but we want: rate / budget * (window / window_days), which simplifies
    # to (observed / monthly) * window_hours / (window_days * 24).
    rate_per_unit = obs.observed_error_rate / monthly_budget
    return rate_per_unit * obs.window_hours / (window_days * 24)
