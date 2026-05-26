"""Unit tests for ``sentinel.tools.incident_sim``.

Phoenix client's ``log_spans`` is mocked so these run fast and without a
live Phoenix backend. We verify the *shape* of what would be written
(OpenInference-conformant spans, correct OK/ERROR mix, time clustering)
and the dispatch table.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from sentinel.scenarios import SCENARIOS
from sentinel.tools import incident_sim
from sentinel.tools.incident_sim import (
    SeedSummary,
    seed_fraud_fp_burst,
    seed_kyc_sanctions_hallucination,
    seed_lending_latency_regression,
    seed_scenario,
)


def _make_fake_client() -> tuple[MagicMock, list[Any]]:
    """Return ``(client_mock, captured_kwargs_list)``."""
    client = MagicMock()
    captured: list[dict] = []

    def log_spans(*, project_identifier: str, spans, timeout=5):
        captured.append({"project": project_identifier, "spans": spans})
        return MagicMock()

    client.spans.log_spans.side_effect = log_spans
    return client, captured


# ── seed_fraud_fp_burst ────────────────────────────────────────────────────


def test_fraud_seeder_writes_correct_mix_and_shape() -> None:
    client, captured = _make_fake_client()
    summary = seed_fraud_fp_burst(client=client)

    assert isinstance(summary, SeedSummary)
    assert summary.project == "fraud-detector-prod"
    assert summary.n_ok == 30
    assert summary.n_error == 12
    assert summary.spans_written == 42

    assert len(captured) == 1
    call = captured[0]
    assert call["project"] == "fraud-detector-prod"
    assert len(call["spans"]) == 42

    # OK / ERROR mix
    n_ok = sum(1 for s in call["spans"] if s["status_code"] == "OK")
    n_error = sum(1 for s in call["spans"] if s["status_code"] == "ERROR")
    assert n_ok == 30
    assert n_error == 12

    # OpenInference span shape on a sample
    sample = call["spans"][0]
    assert sample["name"] == "classify_transaction"
    assert sample["span_kind"] == "LLM"
    assert sample["parent_id"] is None
    assert "trace_id" in sample["context"]
    assert "span_id" in sample["context"]
    assert "input.value" in sample["attributes"]
    assert "output.value" in sample["attributes"]
    assert sample["attributes"]["llm.model_name"] == "fraud-classifier-v2.3.1"
    # input/output values are JSON strings — round-trip them
    in_obj = json.loads(sample["attributes"]["input.value"])
    out_obj = json.loads(sample["attributes"]["output.value"])
    assert "tx_id" in in_obj
    assert out_obj["label"] == "APPROVE"


def test_fraud_error_spans_carry_true_label_for_root_cause_evidence() -> None:
    """Each ERROR span must carry ``output.true_label`` so RootCause can verify the FP pattern."""
    client, captured = _make_fake_client()
    seed_fraud_fp_burst(client=client)
    error_spans = [s for s in captured[0]["spans"] if s["status_code"] == "ERROR"]
    assert len(error_spans) == 12
    for s in error_spans:
        out = json.loads(s["attributes"]["output.value"])
        assert out.get("label") == "FRAUD"
        assert out.get("true_label") == "APPROVE"
        assert out.get("post_hoc_verified") is True


# ── seed_kyc_sanctions_hallucination ───────────────────────────────────────


def test_kyc_seeder_writes_correct_mix_and_carries_hallucination_evidence() -> None:
    client, captured = _make_fake_client()
    summary = seed_kyc_sanctions_hallucination(client=client)

    assert summary.project == "kyc-screener-prod"
    assert summary.n_ok == 25
    assert summary.n_error == 7

    error_spans = [s for s in captured[0]["spans"] if s["status_code"] == "ERROR"]
    for s in error_spans:
        out = json.loads(s["attributes"]["output.value"])
        assert out.get("label") == "PEP_MATCH"
        assert out.get("true_label") == "NO_MATCH"
        assert out.get("claimed_list") == "OFAC-SDN"


# ── seed_lending_latency_regression ───────────────────────────────────────


def test_lending_seeder_all_ok_but_regression_cluster_is_slow() -> None:
    """Lending regression is OK-status (correct answers) with a slow cluster."""
    from datetime import datetime

    client, captured = _make_fake_client()
    summary = seed_lending_latency_regression(client=client)

    assert summary.project == "underwriting-prod"
    assert summary.n_error == 0  # no errors — latency regression keeps status=OK
    assert summary.n_ok == 30 + 18

    spans = captured[0]["spans"]
    durations_ms = []
    for s in spans:
        start = datetime.fromisoformat(s["start_time"])
        end = datetime.fromisoformat(s["end_time"])
        durations_ms.append((end - start).total_seconds() * 1000)

    # Baseline should be sub-second, slow cluster should be 4000+
    sorted_d = sorted(durations_ms)
    assert sorted_d[0] < 500, f"baseline floor too high: {sorted_d[0]}"
    assert sorted_d[-1] > 4000, f"slow cluster ceiling too low: {sorted_d[-1]}"
    # At least 18 spans should be in the slow cluster
    slow_count = sum(1 for d in durations_ms if d >= 3500)
    assert slow_count >= 18


def test_lending_model_name_changes_between_baseline_and_regression() -> None:
    """Baseline uses v3.7.2; regression uses v4.0.0 (the bad deploy)."""
    client, captured = _make_fake_client()
    seed_lending_latency_regression(client=client)
    models = {
        s["attributes"]["llm.model_name"] for s in captured[0]["spans"]
    }
    assert "underwriting-credit-v3.7.2" in models
    assert "underwriting-credit-v4.0.0" in models


# ── dispatch ───────────────────────────────────────────────────────────────


def test_seed_scenario_dispatches_to_correct_seeder() -> None:
    client, _ = _make_fake_client()
    for scenario in SCENARIOS:
        summary = seed_scenario(scenario.id, client=client)
        assert summary.project == scenario.watched_project


def test_seed_scenario_raises_on_unknown_id() -> None:
    with pytest.raises(KeyError, match="no seeder registered"):
        seed_scenario("not-a-real-scenario")


def test_every_scripted_scenario_has_a_registered_seeder() -> None:
    """Drift detector: adding a scenario without a seeder is rejected."""
    for scenario in SCENARIOS:
        assert scenario.id in incident_sim._SEEDERS, (
            f"scenario {scenario.id!r} has no seeder in incident_sim._SEEDERS — "
            f"add one or remove the scenario"
        )
