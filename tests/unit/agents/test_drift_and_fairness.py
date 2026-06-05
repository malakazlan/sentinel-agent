"""Tests for DriftDetective + BiasFairnessAuditor.

Phase 8 / ADR-022 + ADR-023. Both modules are deterministic — these
tests cover the metric correctness + the severity classification + the
unhappy paths (insufficient samples).
"""

from __future__ import annotations

import math

from sentinel.agents.bias_fairness_auditor import (
    FairnessReport,
    audit_incident_decisions,
)
from sentinel.agents.drift_detective import (
    DriftReport,
    PerFeatureDrift,
    build_drift_report,
    detect_categorical_drift,
    detect_numeric_drift,
)
from sentinel.tools.distribution_stats import ks_two_sample, psi
from sentinel.tools.fairness_metrics import GroupCounts, audit_attribute


# ── KS test ──────────────────────────────────────────────────────────────


def test_ks_matched_distributions_no_drift() -> None:
    baseline = [1.0, 2.0, 3.0, 4.0, 5.0] * 20  # 100 samples
    incident = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
    res = ks_two_sample(baseline, incident)
    assert res.severity == "none"
    assert res.p_value > 0.05


def test_ks_shifted_distributions_significant_drift() -> None:
    baseline = list(range(1, 101))  # 1..100
    incident = list(range(50, 150))  # 50..149 — shifted
    res = ks_two_sample(baseline, incident)
    assert res.severity in ("significant", "severe", "watch")
    assert res.statistic > 0.3


def test_ks_empty_returns_neutral() -> None:
    res = ks_two_sample([], [1.0, 2.0])
    assert res.severity == "none"
    assert res.statistic == 0.0


# ── PSI ──────────────────────────────────────────────────────────────────


def test_psi_matched_categorical_no_drift() -> None:
    baseline = ["a"] * 50 + ["b"] * 50
    incident = ["a"] * 50 + ["b"] * 50
    res = psi(baseline, incident)
    assert res.severity == "none"
    assert res.psi < 0.10


def test_psi_dramatic_drift_significant() -> None:
    baseline = ["a"] * 80 + ["b"] * 20
    incident = ["a"] * 20 + ["b"] * 80
    res = psi(baseline, incident)
    assert res.severity in ("significant", "severe")
    assert res.psi > 0.25


# ── DriftDetective integration ──────────────────────────────────────────


def test_drift_detective_insufficient_baseline_flag() -> None:
    finding = detect_numeric_drift("amount_usd", [1, 2, 3], [10, 20, 30])
    assert finding.severity == "insufficient_baseline_data"


def test_drift_detective_numeric_drift_detected() -> None:
    baseline = list(range(1, 101))  # n=100
    incident = list(range(80, 180))  # shifted
    finding = detect_numeric_drift("amount_usd", baseline, incident)
    assert finding.severity in ("significant", "severe")


def test_drift_detective_categorical_clean() -> None:
    baseline = ["a"] * 50 + ["b"] * 50
    incident = ["a"] * 50 + ["b"] * 50
    finding = detect_categorical_drift("merchant_category", baseline, incident)
    assert finding.severity == "none"


def test_build_drift_report_aggregates_severity() -> None:
    report = build_drift_report(
        numeric={
            "amount_usd": (list(range(1, 101)), list(range(50, 150))),
        },
        categorical={
            "merchant_category": (["a"] * 80 + ["b"] * 20, ["a"] * 20 + ["b"] * 80),
        },
    )
    assert isinstance(report, DriftReport)
    assert len(report.per_feature) == 2
    assert report.aggregate_severity in ("significant", "severe", "watch")


def test_build_drift_report_no_features() -> None:
    report = build_drift_report()
    assert report.per_feature == []
    assert report.aggregate_severity == "none"


# ── Fairness metrics — disparate impact ─────────────────────────────────


def test_balanced_decisions_clean_flag() -> None:
    groups = [
        GroupCounts(group_name="prime", approved=80, declined=20),
        GroupCounts(group_name="subprime", approved=78, declined=22),
    ]
    res = audit_attribute("customer_segment", groups)
    assert res.flag == "clean"
    # 4/5ths ratio should be close to 1.
    for g, ratio in res.disparate_impact_ratios.items():
        assert 0.85 < ratio <= 1.05


def test_disparate_impact_flags_severe() -> None:
    # subprime approved at 50%, prime at 90% — ratio 0.55, fails 4/5ths badly
    groups = [
        GroupCounts(group_name="prime", approved=90, declined=10),
        GroupCounts(group_name="subprime", approved=50, declined=50),
    ]
    res = audit_attribute("customer_segment", groups)
    assert res.flag in ("significant", "severe")
    # subprime ratio < 0.8 → 4/5ths failure
    assert res.disparate_impact_ratios["subprime"] < 0.8


def test_insufficient_samples_flags() -> None:
    groups = [
        GroupCounts(group_name="a", approved=5, declined=2),  # < 30 total
        GroupCounts(group_name="b", approved=50, declined=10),
    ]
    res = audit_attribute("attr", groups)
    assert res.flag == "insufficient_data"


# ── Aggregating wrapper ─────────────────────────────────────────────────


def test_audit_incident_decisions_assembles_report() -> None:
    decisions = {
        "customer_segment": {
            "prime": {"approved": 100, "declined": 5},
            "subprime": {"approved": 50, "declined": 55},
        },
    }
    report = audit_incident_decisions(decisions)
    assert isinstance(report, FairnessReport)
    assert len(report.by_attribute) == 1
    assert report.aggregate_flag in ("significant", "severe")
    # Methodology cites EEOC + EU AI Act for traceability.
    assert "EEOC" in report.methodology_note
    assert "EU AI Act" in report.methodology_note


def test_audit_empty_decisions_yields_clean_report() -> None:
    report = audit_incident_decisions({})
    assert report.aggregate_flag == "clean"
    assert report.by_attribute == []


def test_audit_skips_attributes_with_one_group() -> None:
    """Single-group attributes can't be audited — skipped silently."""
    decisions = {
        "customer_segment": {
            "only-group": {"approved": 100, "declined": 5},
        },
        "age_band": {
            "<30": {"approved": 80, "declined": 10},
            "30-60": {"approved": 78, "declined": 12},
        },
    }
    report = audit_incident_decisions(decisions)
    assert len(report.by_attribute) == 1
    assert report.by_attribute[0].attribute_name == "age_band"
