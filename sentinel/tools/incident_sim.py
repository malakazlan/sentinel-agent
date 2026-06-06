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
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from phoenix.client import Client

_logger = logging.getLogger(__name__)

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


# ── Phase 8 — in-process trace cache (Phoenix-unreachable fallback) ──────
#
# Cloud Run deploys point at the customer's OTLP collector in production
# (per ADR-017). For the hosted demo there's no Phoenix at the configured
# endpoint and `Client().spans.log_spans` raises ConnectError on every
# seed call. To keep downstream agents grounded in real evidence rather
# than handing them "Connection refused" strings, every seed function
# also stashes its synthetic spans in this in-process dict keyed by
# project name. ``get_recent_traces`` falls back to this cache when
# Phoenix is unreachable. ZERO fabrication — these are the EXACT spans
# the seed would have written; we just don't lose them when the
# collector is offline.
_TRACE_CACHE: dict[str, list[dict]] = {}


def get_cached_spans(project: str) -> list[dict]:
    """Return the cached spans for ``project`` (empty list if none seeded)."""
    return list(_TRACE_CACHE.get(project, []))


def _cache_spans(project: str, spans: list[dict]) -> None:
    """Replace the cached spans for ``project``."""
    _TRACE_CACHE[project] = list(spans)


def clear_trace_cache() -> None:
    """Test helper — wipe the cache between runs."""
    _TRACE_CACHE.clear()


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

    # Cache before the Phoenix write so the in-process fallback is
    # populated even when ``log_spans`` raises ConnectError (Phase 8
    # trace cache; see _TRACE_CACHE module comment).
    _cache_spans(project, spans)
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

    _cache_spans(project, spans)
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

    _cache_spans(project, spans)
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

# Mirror of each seeder's default ``project`` kwarg. Used to label the
# degraded ``SeedSummary`` when the OTLP collector is unreachable so
# downstream readers (the orchestrator + UI) still see *which* watched
# project the seed would have populated.
_PROJECT_BY_SCENARIO: dict[str, str] = {
    "fraud-fp-burst": "fraud-detector-prod",
    "kyc-sanctions-hallucination": "kyc-screener-prod",
    "lending-latency-regression": "underwriting-prod",
}


def seed_scenario(scenario_id: str, *, client: Optional[Client] = None) -> SeedSummary:
    """Dispatch to the matching seed function by scenario id.

    ADR-017 — When the Phoenix / OTLP collector is unreachable
    (``httpx.ConnectError``), this function logs a WARNING and returns a
    degraded ``SeedSummary`` with ``spans_written=0`` instead of raising.
    The agent pipeline then runs without trace grounding rather than
    failing the whole incident, matching real-world deployments where the
    customer's collector may be reachable from some networks but not
    others. ALL other exceptions still propagate.
    """
    seeder = _SEEDERS.get(scenario_id)
    if seeder is None:
        raise KeyError(
            f"no seeder registered for scenario id {scenario_id!r}. "
            f"Known: {list(_SEEDERS.keys())}"
        )
    try:
        return seeder(client=client)
    except httpx.ConnectError as exc:
        endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "<unset>")
        project = _PROJECT_BY_SCENARIO.get(scenario_id, "")
        # Phase 8 — the seed function cached its spans BEFORE the Phoenix
        # write threw, so downstream agents will read them via
        # ``get_recent_traces``'s in-process fallback. Report the cached
        # counts so the UI's "Traces analyzed" metric is meaningful
        # instead of "0 traces" (which made every demo postmortem look
        # broken).
        cached = get_cached_spans(project)
        n_ok = sum(1 for s in cached if s.get("status_code") == "OK")
        n_error = sum(1 for s in cached if s.get("status_code") == "ERROR")
        _logger.warning(
            "Phoenix OTLP collector unreachable at %s; seed_scenario(%s) "
            "degraded to in-process trace cache (project=%s, spans_cached=%d). "
            "Pipeline continues with cached trace grounding. Underlying error: %s",
            endpoint, scenario_id, project, len(cached), exc,
        )
        return SeedSummary(
            project=project,
            spans_written=len(cached),
            n_ok=n_ok,
            n_error=n_error,
        )
