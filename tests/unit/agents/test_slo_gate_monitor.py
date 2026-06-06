"""Tests for SLOGuardian + HumanOverrideGate + SentinelMonitor.

Phase 8 / ADR-024 + ADR-025 + ADR-026.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sentinel.agents.human_override import (
    GATED_ACTION_ITEM_ASSIGNMENT,
    GATED_REGULATOR_NOTIFICATION,
    GATED_SLACK_PROD_POST,
    is_action_gated,
    list_pending,
    request_gate,
    resolve_gate,
)
from sentinel.agents.sentinel_monitor import (
    SentinelHealthReport,
    _trend_slope,
    build_health_report,
)
from sentinel.agents.slo_guardian import (
    BurnObservation,
    SLOTarget,
    assess_burn,
)
from sentinel.memory.prompt_history import (
    PromptHistoryStore,
    PromptRunRecord,
)


# ── SLOGuardian ──────────────────────────────────────────────────────────


def test_slo_no_burn_when_within_budget() -> None:
    target = SLOTarget(name="accuracy", target=0.995, window_days=30)
    # Within budget: observed error rate 0.001 (well under 0.005).
    fast = BurnObservation(window_hours=1.0, observed_error_rate=0.001, sample_count=100)
    slow = BurnObservation(window_hours=6.0, observed_error_rate=0.001, sample_count=600)
    f = assess_burn(target, fast, slow)
    assert f.fast_burn_alert is False
    assert f.slow_burn_alert is False
    assert f.severity == "ok"


def test_slo_fast_burn_pages() -> None:
    target = SLOTarget(name="accuracy", target=0.995)
    # observed error rate 100x baseline -> fast burn alert
    fast = BurnObservation(window_hours=1.0, observed_error_rate=0.5, sample_count=100)
    slow = BurnObservation(window_hours=6.0, observed_error_rate=0.05, sample_count=600)
    f = assess_burn(target, fast, slow)
    assert f.fast_burn_alert is True
    assert f.severity == "page"


def test_slo_slow_burn_tickets() -> None:
    target = SLOTarget(name="accuracy", target=0.995)
    # Slow burn but not fast burn.
    fast = BurnObservation(window_hours=1.0, observed_error_rate=0.003, sample_count=100)
    slow = BurnObservation(window_hours=6.0, observed_error_rate=0.15, sample_count=600)
    f = assess_burn(target, fast, slow)
    assert f.fast_burn_alert is False
    assert f.slow_burn_alert is True
    assert f.severity == "ticket"


# ── HumanOverrideGate ────────────────────────────────────────────────────


def test_regulator_notification_always_gated() -> None:
    assert is_action_gated(GATED_REGULATOR_NOTIFICATION) is True


def test_slack_prod_post_default_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTINEL_SLACK_GATE_PROD", raising=False)
    assert is_action_gated(GATED_SLACK_PROD_POST) is True


def test_slack_prod_post_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_SLACK_GATE_PROD", "0")
    assert is_action_gated(GATED_SLACK_PROD_POST) is False


def test_action_item_gate_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTINEL_ACTION_ITEM_GATE", raising=False)
    assert is_action_gated(GATED_ACTION_ITEM_ASSIGNMENT) is False


def test_action_item_gate_on_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_ACTION_ITEM_GATE", "1")
    assert is_action_gated(GATED_ACTION_ITEM_ASSIGNMENT) is True


def test_gate_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.agents import human_override
    monkeypatch.setattr(human_override, "_PENDING_STORE", tmp_path / "pending.jsonl")
    monkeypatch.setattr(human_override, "_RESOLVED_STORE", tmp_path / "resolved.jsonl")

    gate = request_gate(
        incident_id="inc-1",
        action_type=GATED_REGULATOR_NOTIFICATION,
        action_summary="Draft FCA SUP 15.3 notification headline",
    )
    assert gate.gate_id
    pending = list_pending()
    assert any(g.gate_id == gate.gate_id for g in pending)

    resolve_gate(gate.gate_id, "approved", operator_note="ok")
    pending_after = list_pending()
    assert not any(g.gate_id == gate.gate_id for g in pending_after)


# ── SentinelMonitor ──────────────────────────────────────────────────────


def test_trend_slope_zero_when_insufficient_samples() -> None:
    assert _trend_slope([0.9]) == 0.0
    assert _trend_slope([0.9, 0.8]) == 0.0


def test_trend_slope_negative_for_descending_scores() -> None:
    slope = _trend_slope([0.95, 0.90, 0.85, 0.80])
    assert slope < 0


def test_trend_slope_positive_for_ascending_scores() -> None:
    slope = _trend_slope([0.70, 0.75, 0.80, 0.85])
    assert slope > 0


def test_build_health_report_classifies_correctly(tmp_path: Path) -> None:
    store = PromptHistoryStore(path=tmp_path / "history.jsonl")
    # Three agents with different score levels.
    for score in [0.95, 0.93, 0.94]:
        store.append(PromptRunRecord(
            agent_name="strong",
            prompt_version="v1", prompt_hash="h",
            incident_id="i", scenario_id="s",
            aggregate_critic_score=score,
        ))
    for score in [0.85, 0.82, 0.83]:
        store.append(PromptRunRecord(
            agent_name="watching",
            prompt_version="v1", prompt_hash="h",
            incident_id="i", scenario_id="s",
            aggregate_critic_score=score,
        ))
    for score in [0.65, 0.63, 0.60]:
        store.append(PromptRunRecord(
            agent_name="underperforming",
            prompt_version="v1", prompt_hash="h",
            incident_id="i", scenario_id="s",
            aggregate_critic_score=score,
        ))

    report = build_health_report(store=store)
    assert isinstance(report, SentinelHealthReport)
    flags = {a.agent_name: a.health_flag for a in report.agents}
    assert flags["strong"] == "healthy"
    assert flags["watching"] == "watch"
    assert flags["underperforming"] == "underperforming"
    assert report.healthy_count == 1
    assert report.watch_count == 1
    assert report.underperforming_count == 1


def test_build_health_report_empty_store_returns_empty(tmp_path: Path) -> None:
    store = PromptHistoryStore(path=tmp_path / "history.jsonl")
    report = build_health_report(store=store)
    assert report.agents == []
    assert report.history_total == 0
