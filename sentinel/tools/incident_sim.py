"""Demo theater — synthetic watched-system traces seeded into Phoenix.

CLAUDE.md §6 specifies this module as "simulates AI system under monitoring."
For the Phase 4 step 5 end-to-end demo, each scripted incident needs Phoenix
to actually contain realistic traces of the *watched* production AI failing,
not just the alert payload. Without those traces, the sub-agents have no
grounding and the Postmortem agent fabricates content (caught by our own
hallucination eval, but fabricated nonetheless).

This module writes OpenInference-shaped spans directly to Phoenix via
``phoenix.client.Client.spans.log_spans``. Each scenario gets its own
Phoenix project (e.g. ``fraud-detector-prod``) so:

- Sentinel's self-introspection still queries its own ``sentinel`` project
  (untouched by this module).
- The pipeline's ``get_recent_traces`` calls are pointed at the watched
  project for the duration of a scenario run (orchestrator handles the
  env-var swap).

Public API:

- ``seed_scenario(scenario_id)`` — dispatch by scenario id; calls the
  matching seeder. Returns ``SeedSummary``.
- One ``seed_*`` function per scenario id, all return ``SeedSummary``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from phoenix.client import Client

# OpenInference standard attribute keys — keeps Phoenix UI rendering correct.
_ATTR_INPUT_VALUE = "input.value"
_ATTR_INPUT_MIME = "input.mime_type"
_ATTR_OUTPUT_VALUE = "output.value"
_ATTR_OUTPUT_MIME = "output.mime_type"
_ATTR_LLM_MODEL = "llm.model_name"
_ATTR_MIME_JSON = "application/json"


@dataclass(frozen=True)
class SeedSummary:
    """Per-seed result for orchestrator + test reporting."""

    project: str
    spans_written: int
    n_ok: int
    n_error: int


# ── span construction helpers ─────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _new_trace_id() -> str:
    """32-hex-char trace id (OTel standard width)."""
    return uuid.uuid4().hex


def _new_span_id() -> str:
    """16-hex-char span id (OTel standard width)."""
    return uuid.uuid4().hex[:16]


def _make_root_span(
    *,
    name: str,
    span_kind: str,
    start_time: datetime,
    duration_ms: int,
    status: str,
    status_message: str = "",
    attributes: Optional[dict[str, Any]] = None,
) -> dict:
    """Build one root v1.Span dict for ``log_spans``."""
    end_time = start_time + timedelta(milliseconds=duration_ms)
    return {
        "name": name,
        "context": {"trace_id": _new_trace_id(), "span_id": _new_span_id()},
        "span_kind": span_kind,
        "parent_id": None,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "status_code": status,
        "status_message": status_message,
        "attributes": attributes or {},
        "events": [],
    }


def _llm_attrs(
    *,
    model_name: str,
    input_obj: dict[str, Any],
    output_obj: dict[str, Any],
) -> dict[str, Any]:
    """Standard OpenInference LLM-span attribute set."""
    return {
        _ATTR_LLM_MODEL: model_name,
        _ATTR_INPUT_VALUE: json.dumps(input_obj),
        _ATTR_INPUT_MIME: _ATTR_MIME_JSON,
        _ATTR_OUTPUT_VALUE: json.dumps(output_obj),
        _ATTR_OUTPUT_MIME: _ATTR_MIME_JSON,
    }


# ── per-scenario seeders ──────────────────────────────────────────────────


def seed_fraud_fp_burst(
    *,
    client: Optional[Client] = None,
    project: str = "fraud-detector-prod",
    n_baseline_ok: int = 30,
    n_burst_errors: int = 12,
) -> SeedSummary:
    """Seed ``fraud-classifier-v2.3.1`` traces — baseline OK + recent FP burst.

    The burst is clustered in the last 5 minutes (so a 1-hour ``get_recent_traces``
    window picks it up sharply against the broader baseline). Each ERROR span
    carries ``output.true_label`` so RootCause can verify the false-positive
    pattern from trace evidence alone.
    """
    client = client or Client()
    now = _now_utc()
    spans: list[dict] = []

    # Baseline OK: spread across last 30 min, all APPROVE for routine categories
    baseline_start = now - timedelta(minutes=30)
    for i in range(n_baseline_ok):
        t = baseline_start + timedelta(seconds=i * 50)
        spans.append(
            _make_root_span(
                name="classify_transaction",
                span_kind="LLM",
                start_time=t,
                duration_ms=120 + (i % 30),
                status="OK",
                attributes=_llm_attrs(
                    model_name="fraud-classifier-v2.3.1",
                    input_obj={
                        "tx_id": f"tx-{uuid.uuid4().hex[:8]}",
                        "amount_usd": 250 + i * 7,
                        "merchant_category": "groceries",
                        "customer_segment": "retail",
                    },
                    output_obj={"label": "APPROVE", "confidence": 0.92},
                ),
            )
        )

    # FP burst — recent ERROR cluster
    burst_start = now - timedelta(minutes=5)
    for i in range(n_burst_errors):
        t = burst_start + timedelta(seconds=i * 24)
        spans.append(
            _make_root_span(
                name="classify_transaction",
                span_kind="LLM",
                start_time=t,
                duration_ms=80 + (i % 20),
                status="ERROR",
                status_message="false positive: legitimate transaction flagged as FRAUD",
                attributes=_llm_attrs(
                    model_name="fraud-classifier-v2.3.1",
                    input_obj={
                        "tx_id": f"tx-{uuid.uuid4().hex[:8]}",
                        "amount_usd": 800 + i * 50,
                        "merchant_category": "electronics",
                        "customer_segment": "retail",
                    },
                    output_obj={
                        "label": "FRAUD",
                        "confidence": 0.97 - i * 0.005,
                        "true_label": "APPROVE",
                        "post_hoc_verified": True,
                    },
                ),
            )
        )

    client.spans.log_spans(project_identifier=project, spans=spans)
    return SeedSummary(
        project=project, spans_written=len(spans),
        n_ok=n_baseline_ok, n_error=n_burst_errors,
    )


def seed_kyc_sanctions_hallucination(
    *,
    client: Optional[Client] = None,
    project: str = "kyc-screener-prod",
    n_baseline_ok: int = 25,
    n_burst_errors: int = 7,
) -> SeedSummary:
    """Seed ``kyc-pep-screener-v3.1.0`` traces — baseline screens + fabricated PEP matches.

    The burst spans carry both the fabricated match AND the post-hoc-verified
    ``true_label="NO_MATCH"`` so RootCause can see the hallucination pattern.
    """
    client = client or Client()
    now = _now_utc()
    spans: list[dict] = []

    baseline_start = now - timedelta(minutes=40)
    for i in range(n_baseline_ok):
        t = baseline_start + timedelta(seconds=i * 90)
        spans.append(
            _make_root_span(
                name="screen_customer",
                span_kind="LLM",
                start_time=t,
                duration_ms=280 + (i % 40),
                status="OK",
                attributes=_llm_attrs(
                    model_name="kyc-pep-screener-v3.1.0",
                    input_obj={
                        "customer_id": f"cust-{uuid.uuid4().hex[:8]}",
                        "name": "redacted",
                        "country": "GB",
                        "lists_consulted": ["OFAC", "EU-consolidated", "UK-HMT"],
                    },
                    output_obj={"label": "NO_MATCH", "confidence": 0.99},
                ),
            )
        )

    burst_start = now - timedelta(minutes=2)
    for i in range(n_burst_errors):
        t = burst_start + timedelta(seconds=i * 17)
        spans.append(
            _make_root_span(
                name="screen_customer",
                span_kind="LLM",
                start_time=t,
                duration_ms=320 + (i % 30),
                status="ERROR",
                status_message="hallucinated sanctions match: name not present in any consulted list",
                attributes=_llm_attrs(
                    model_name="kyc-pep-screener-v3.1.0",
                    input_obj={
                        "customer_id": f"cust-{uuid.uuid4().hex[:8]}",
                        "name": "redacted",
                        "country": "GB",
                        "lists_consulted": ["OFAC", "EU-consolidated", "UK-HMT"],
                    },
                    output_obj={
                        "label": "PEP_MATCH",
                        "confidence": 0.94,
                        "claimed_list": "OFAC-SDN",
                        "true_label": "NO_MATCH",
                        "post_hoc_verified": True,
                        "verification_note": "name fabricated; not present in any consulted list",
                    },
                ),
            )
        )

    client.spans.log_spans(project_identifier=project, spans=spans)
    return SeedSummary(
        project=project, spans_written=len(spans),
        n_ok=n_baseline_ok, n_error=n_burst_errors,
    )


def seed_lending_latency_regression(
    *,
    client: Optional[Client] = None,
    project: str = "underwriting-prod",
    n_baseline_ok: int = 30,
    n_regression_slow: int = 18,
) -> SeedSummary:
    """Seed ``underwriting-credit`` traces — baseline fast + recent slow cluster.

    Models the post-deploy latency regression: baseline at ~280ms, slow cluster
    at 4000-4500ms after a synthetic deploy. Spans are still ``status=OK``
    (the model returns correct answers, just slowly) — the failure mode is
    SLA breach, not error. RootCause should pick up the duration shift, not
    look for ERROR clusters.
    """
    client = client or Client()
    now = _now_utc()
    spans: list[dict] = []

    baseline_start = now - timedelta(minutes=30)
    for i in range(n_baseline_ok):
        t = baseline_start + timedelta(seconds=i * 50)
        spans.append(
            _make_root_span(
                name="score_application",
                span_kind="LLM",
                start_time=t,
                duration_ms=270 + (i % 40),
                status="OK",
                attributes=_llm_attrs(
                    model_name="underwriting-credit-v3.7.2",
                    input_obj={
                        "application_id": f"app-{uuid.uuid4().hex[:8]}",
                        "loan_amount_usd": 15000 + i * 250,
                        "applicant_segment": "prime",
                    },
                    output_obj={"decision": "APPROVE", "rate_bps": 750 + i, "confidence": 0.88},
                ),
            )
        )

    regression_start = now - timedelta(minutes=8)
    for i in range(n_regression_slow):
        t = regression_start + timedelta(seconds=i * 25)
        spans.append(
            _make_root_span(
                name="score_application",
                span_kind="LLM",
                start_time=t,
                duration_ms=4000 + (i * 30),
                status="OK",
                attributes=_llm_attrs(
                    model_name="underwriting-credit-v4.0.0",  # newly-deployed version
                    input_obj={
                        "application_id": f"app-{uuid.uuid4().hex[:8]}",
                        "loan_amount_usd": 22000 + i * 300,
                        "applicant_segment": "prime",
                    },
                    output_obj={"decision": "APPROVE", "rate_bps": 780 + i, "confidence": 0.86},
                ),
            )
        )

    client.spans.log_spans(project_identifier=project, spans=spans)
    return SeedSummary(
        project=project, spans_written=len(spans),
        n_ok=n_baseline_ok + n_regression_slow, n_error=0,
    )


# ── dispatch ──────────────────────────────────────────────────────────────


_SEEDERS = {
    "fraud-fp-burst": seed_fraud_fp_burst,
    "kyc-sanctions-hallucination": seed_kyc_sanctions_hallucination,
    "lending-latency-regression": seed_lending_latency_regression,
}


def seed_scenario(scenario_id: str, *, client: Optional[Client] = None) -> SeedSummary:
    """Dispatch to the matching seed function by scenario id."""
    seeder = _SEEDERS.get(scenario_id)
    if seeder is None:
        raise KeyError(
            f"no seeder registered for scenario id {scenario_id!r}. "
            f"Known: {list(_SEEDERS.keys())}"
        )
    return seeder(client=client)
