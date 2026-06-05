"""DriftDetective — Phase 8 / ADR-022.

Reads watched-system trace input/output distributions, runs KS (numeric)
+ PSI (categorical), and emits a typed ``DriftReport``. The LLM-shaped
agent here serves as the routing endpoint; the actual analysis is
deterministic and lives in ``sentinel.tools.distribution_stats``.

Pipeline placement: inserted as a stage between ``eval_fanout`` and
``deploy_correlation`` once wired into the orchestrator (Phase 8
follow-on); for V1 the agent + deterministic compute are stand-alone
and consumed by the postmortem schema's optional ``drift_analysis``
field.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sentinel.tools.distribution_stats import (
    KSResult,
    PSIResult,
    ks_two_sample,
    numeric_summary,
    psi,
)

_logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────


class PerFeatureDrift(BaseModel):
    """One feature's drift assessment.

    For numeric features ``test`` is ``ks`` and ``statistic`` + ``p_value``
    are populated. For categorical features ``test`` is ``psi`` and
    ``statistic`` carries the PSI value (``p_value`` is None).
    """

    model_config = ConfigDict(extra="forbid")
    feature_name: str = Field(..., min_length=1)
    test: str = Field(..., description="``ks`` or ``psi``.")
    statistic: float
    p_value: Optional[float] = None
    severity: str
    baseline_summary: dict[str, Optional[float]] = Field(default_factory=dict)
    incident_summary: dict[str, Optional[float]] = Field(default_factory=dict)


class DriftReport(BaseModel):
    """Top-level drift assessment for an incident. Phase 8 / ADR-022."""

    model_config = ConfigDict(extra="forbid")
    per_feature: list[PerFeatureDrift] = Field(default_factory=list)
    aggregate_severity: str = Field(
        ...,
        description=(
            "Highest severity observed across per-feature drifts. Used "
            "by the orchestrator to decide whether to alert."
        ),
    )
    insufficient_baseline_data: bool = Field(
        default=False,
        description=(
            "True when every feature had < ``MIN_BASELINE`` samples. The "
            "report's severities are set to ``insufficient_baseline_data`` "
            "rather than misleading p-values."
        ),
    )


# ── Compute ──────────────────────────────────────────────────────────────


MIN_BASELINE_SAMPLES = 30


_SEVERITY_RANK = {"none": 0, "watch": 1, "significant": 2, "severe": 3}


def _max_severity(flags: list[str]) -> str:
    rank = max(_SEVERITY_RANK.get(f, 0) for f in flags) if flags else 0
    return {v: k for k, v in _SEVERITY_RANK.items()}[rank]


def detect_numeric_drift(
    feature_name: str,
    baseline: list[float],
    incident: list[float],
) -> PerFeatureDrift:
    if len(baseline) < MIN_BASELINE_SAMPLES:
        return PerFeatureDrift(
            feature_name=feature_name,
            test="ks",
            statistic=0.0,
            p_value=None,
            severity="insufficient_baseline_data",
            baseline_summary=numeric_summary(baseline),
            incident_summary=numeric_summary(incident),
        )
    res: KSResult = ks_two_sample(baseline, incident)
    return PerFeatureDrift(
        feature_name=feature_name,
        test="ks",
        statistic=round(res.statistic, 4),
        p_value=round(res.p_value, 6),
        severity=res.severity,
        baseline_summary=numeric_summary(baseline),
        incident_summary=numeric_summary(incident),
    )


def detect_categorical_drift(
    feature_name: str,
    baseline: list[str],
    incident: list[str],
) -> PerFeatureDrift:
    if len(baseline) < MIN_BASELINE_SAMPLES:
        return PerFeatureDrift(
            feature_name=feature_name,
            test="psi",
            statistic=0.0,
            p_value=None,
            severity="insufficient_baseline_data",
            baseline_summary={"n": len(baseline)},
            incident_summary={"n": len(incident)},
        )
    res: PSIResult = psi(baseline, incident)
    return PerFeatureDrift(
        feature_name=feature_name,
        test="psi",
        statistic=round(res.psi, 4),
        p_value=None,
        severity=res.severity,
        baseline_summary={"n": float(res.baseline_n)},
        incident_summary={"n": float(res.incident_n)},
    )


def build_drift_report(
    *,
    numeric: Optional[dict[str, tuple[list[float], list[float]]]] = None,
    categorical: Optional[dict[str, tuple[list[str], list[str]]]] = None,
) -> DriftReport:
    """Build a complete DriftReport from numeric + categorical features.

    Each dict maps feature_name → (baseline_values, incident_values).
    """
    per_feature: list[PerFeatureDrift] = []
    if numeric:
        for name, (b, i) in numeric.items():
            per_feature.append(detect_numeric_drift(name, b, i))
    if categorical:
        for name, (b, i) in categorical.items():
            per_feature.append(detect_categorical_drift(name, b, i))
    if not per_feature:
        return DriftReport(per_feature=[], aggregate_severity="none")
    severities = [p.severity for p in per_feature]
    insufficient = all(s == "insufficient_baseline_data" for s in severities)
    standard = [s for s in severities if s in _SEVERITY_RANK]
    agg = _max_severity(standard) if standard else "insufficient_baseline_data"
    return DriftReport(
        per_feature=per_feature,
        aggregate_severity=agg,
        insufficient_baseline_data=insufficient,
    )
