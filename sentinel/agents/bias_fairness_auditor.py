"""BiasFairnessAuditor — Phase 8 / ADR-023.

For fraud / KYC / lending incidents, audits the watched-system's
decision distribution across protected attributes using the 4/5ths
rule, statistical parity difference, and equalized odds delta.

The computation is deterministic (``sentinel.tools.fairness_metrics``);
this module exposes the FairnessReport schema and an aggregating
function that operates on the scenario's ``decisions_by_protected_class``
seed.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sentinel.tools.fairness_metrics import (
    FairnessAuditResult,
    GroupCounts,
    audit_attribute,
)


class FairnessAttributeFinding(BaseModel):
    """One protected attribute's audit (e.g. ``customer_segment``)."""

    model_config = ConfigDict(extra="forbid")
    attribute_name: str
    reference_group: str
    disparate_impact_ratios: dict[str, float] = Field(default_factory=dict)
    statistical_parity_differences: dict[str, float] = Field(default_factory=dict)
    equalized_odds_deltas: dict[str, float] = Field(default_factory=dict)
    flag: str


class FairnessReport(BaseModel):
    """Top-level fairness assessment for an incident. Phase 8 / ADR-023."""

    model_config = ConfigDict(extra="forbid")
    by_attribute: list[FairnessAttributeFinding] = Field(default_factory=list)
    aggregate_flag: str = Field(...)
    methodology_note: str = Field(
        ...,
        min_length=20,
        description=(
            "Standard line documenting the 3 metrics used + their "
            "industry/regulator alignment."
        ),
    )


_METHODOLOGY = (
    "Audited using the EEOC 4/5ths rule (1978 Uniform Guidelines on "
    "Employee Selection Procedures), statistical parity difference, "
    "and equalized odds delta. EU AI Act Article 10 cross-applies. "
    "Reports clean / watch / significant / severe per attribute."
)


_SEVERITY_RANK = {
    "clean": 0,
    "watch": 1,
    "significant": 2,
    "severe": 3,
    "insufficient_data": -1,
}


def _attr_from_result(r: FairnessAuditResult) -> FairnessAttributeFinding:
    return FairnessAttributeFinding(
        attribute_name=r.attribute_name,
        reference_group=r.reference_group,
        disparate_impact_ratios=r.disparate_impact_ratios,
        statistical_parity_differences=r.statistical_parity_differences,
        equalized_odds_deltas=r.equalized_odds_deltas,
        flag=r.flag,
    )


def audit_incident_decisions(
    decisions_by_attribute: dict[str, dict[str, dict[str, int]]],
) -> FairnessReport:
    """Build a complete FairnessReport from the scenario-seed shape.

    Input shape (e.g. one fraud incident's audit):

    ```
    {
      "customer_segment": {
        "prime":   {"approved": 100, "declined":  5},
        "subprime":{"approved":  80, "declined": 20},
      },
      "age_band": {
        "<30":  {"approved": 80, "declined": 10},
        "30-60":{"approved": 90, "declined": 15},
      }
    }
    ```
    """
    findings: list[FairnessAttributeFinding] = []
    for attr_name, group_map in decisions_by_attribute.items():
        groups = [
            GroupCounts(
                group_name=g_name,
                approved=int(counts.get("approved", 0)),
                declined=int(counts.get("declined", 0)),
                true_positive=int(counts.get("true_positive", 0)),
                true_negative=int(counts.get("true_negative", 0)),
                false_positive=int(counts.get("false_positive", 0)),
                false_negative=int(counts.get("false_negative", 0)),
            )
            for g_name, counts in group_map.items()
        ]
        if len(groups) < 2:
            continue
        result = audit_attribute(attr_name, groups)
        findings.append(_attr_from_result(result))

    if not findings:
        return FairnessReport(
            by_attribute=[],
            aggregate_flag="clean",
            methodology_note=_METHODOLOGY,
        )
    standard = [
        f.flag for f in findings if f.flag in _SEVERITY_RANK and _SEVERITY_RANK[f.flag] >= 0
    ]
    if not standard:
        agg = "insufficient_data"
    else:
        worst = max(_SEVERITY_RANK[f] for f in standard)
        agg = {v: k for k, v in _SEVERITY_RANK.items() if v >= 0}[worst]
    return FairnessReport(
        by_attribute=findings,
        aggregate_flag=agg,
        methodology_note=_METHODOLOGY,
    )
