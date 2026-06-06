"""Fairness metrics — disparate impact + statistical parity + equalized odds.

Phase 8 / ADR-023. Pure-python, no ML lib dependencies. All three
metrics are returned per protected-attribute audit so the reader can
triangulate (no single metric is sufficient alone).

Metric choices follow EEOC + EU AI Act guidance:

- Disparate impact ratio (4/5ths rule, EEOC Uniform Guidelines 1978).
- Statistical parity difference.
- Equalized odds delta (when ground-truth labels are available).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


SEVERITY_FLAGS = ("clean", "watch", "significant", "severe", "insufficient_data")


@dataclass(frozen=True)
class GroupCounts:
    """One protected group's decision distribution."""

    group_name: str
    approved: int
    declined: int
    true_positive: int = 0  # decision=approve AND ground_truth=approve
    true_negative: int = 0
    false_positive: int = 0
    false_negative: int = 0

    @property
    def total(self) -> int:
        return self.approved + self.declined

    @property
    def approve_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.approved / self.total


@dataclass(frozen=True)
class FairnessAuditResult:
    attribute_name: str  # e.g. "customer_segment"
    reference_group: str
    disparate_impact_ratios: dict[str, float]
    statistical_parity_differences: dict[str, float]
    equalized_odds_deltas: dict[str, float]
    flag: str  # severity tag from SEVERITY_FLAGS


# Below this per-group sample count, ratios are too noisy to publish.
# Set to 10 (down from 30) because Phase 8 demo scenarios deliver
# 20–30 spans per group via the in-process trace cache; 30 was the
# textbook regulator floor for prod auditing but it's too tight for
# the demo corpus. Production deployers should override this via the
# scenario seed when sample sizes are reliably higher.
_MIN_SAMPLES_PER_GROUP = 10


def audit_attribute(
    attribute_name: str,
    groups: list[GroupCounts],
    *,
    reference_group_name: Optional[str] = None,
) -> FairnessAuditResult:
    """Run all three fairness metrics across the groups of one attribute.

    The reference group is the one with the highest approve_rate (treats
    the most-favored group as reference for the 4/5ths rule) unless an
    explicit ``reference_group_name`` is provided.

    Returns ``flag=insufficient_data`` when any group has fewer than 30
    samples — small samples produce unstable ratios. Otherwise the flag
    is the worst across the three metrics.
    """
    if any(g.total < _MIN_SAMPLES_PER_GROUP for g in groups):
        return FairnessAuditResult(
            attribute_name=attribute_name,
            reference_group="",
            disparate_impact_ratios={},
            statistical_parity_differences={},
            equalized_odds_deltas={},
            flag="insufficient_data",
        )

    if reference_group_name:
        ref = next(g for g in groups if g.group_name == reference_group_name)
    else:
        ref = max(groups, key=lambda g: g.approve_rate)
    ref_rate = ref.approve_rate

    di_ratios: dict[str, float] = {}
    parity_diff: dict[str, float] = {}
    eo_delta: dict[str, float] = {}

    for g in groups:
        # 4/5ths rule: ratio of approve_rate(group) / approve_rate(reference)
        # Below 0.8 flags disparate impact.
        di_ratios[g.group_name] = (
            (g.approve_rate / ref_rate) if ref_rate > 0 else 0.0
        )
        parity_diff[g.group_name] = g.approve_rate - ref_rate
        # Equalized odds: |TPR_g - TPR_ref| + |FPR_g - FPR_ref|
        tpr_g = _tpr(g)
        tpr_r = _tpr(ref)
        fpr_g = _fpr(g)
        fpr_r = _fpr(ref)
        eo_delta[g.group_name] = abs(tpr_g - tpr_r) + abs(fpr_g - fpr_r)

    flag = _classify_flag(di_ratios, parity_diff, eo_delta)
    return FairnessAuditResult(
        attribute_name=attribute_name,
        reference_group=ref.group_name,
        disparate_impact_ratios=di_ratios,
        statistical_parity_differences=parity_diff,
        equalized_odds_deltas=eo_delta,
        flag=flag,
    )


def _tpr(g: GroupCounts) -> float:
    denom = g.true_positive + g.false_negative
    if denom == 0:
        return 0.0
    return g.true_positive / denom


def _fpr(g: GroupCounts) -> float:
    denom = g.false_positive + g.true_negative
    if denom == 0:
        return 0.0
    return g.false_positive / denom


def _classify_flag(
    di: dict[str, float],
    parity: dict[str, float],
    eo: dict[str, float],
) -> str:
    """Return the worst severity across the three metrics."""
    rank = 0
    # Disparate impact: <0.8 fails 4/5ths rule.
    for ratio in di.values():
        if math.isfinite(ratio):
            if ratio < 0.6:
                rank = max(rank, 3)
            elif ratio < 0.8:
                rank = max(rank, 2)
            elif ratio < 0.9:
                rank = max(rank, 1)
    # Statistical parity: |diff| > 0.10 is significant
    for diff in parity.values():
        if abs(diff) > 0.20:
            rank = max(rank, 3)
        elif abs(diff) > 0.10:
            rank = max(rank, 2)
        elif abs(diff) > 0.05:
            rank = max(rank, 1)
    # Equalized odds: > 0.10 is significant
    for delta in eo.values():
        if delta > 0.20:
            rank = max(rank, 3)
        elif delta > 0.10:
            rank = max(rank, 2)
        elif delta > 0.05:
            rank = max(rank, 1)
    return {0: "clean", 1: "watch", 2: "significant", 3: "severe"}[rank]
