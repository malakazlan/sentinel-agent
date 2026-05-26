"""Tests for ``get_recent_traces`` output formatting — especially the
input/output attribute excerpts that drive sub-agent semantic grounding.

Without these excerpts the agents only see status_code + duration and
default-assume "service outage" when status is ERROR — which inverts the
failure narrative in workloads like fraud detection where ERROR-status
means *over-blocking*, not service down. The excerpts let RootCause and
Postmortem distinguish a misclassification (output.true_label present)
from an actual service failure (no structured output).
"""

from __future__ import annotations

import json

import pytest

from sentinel.tools.phoenix_traces import (
    _attr_excerpt,
    _format_span_block,
)


# ── _attr_excerpt ──────────────────────────────────────────────────────────


def test_attr_excerpt_returns_empty_when_key_missing() -> None:
    assert _attr_excerpt({}, "input.value") == ""


def test_attr_excerpt_returns_empty_when_value_is_empty_string() -> None:
    assert _attr_excerpt({"input.value": ""}, "input.value") == ""


def test_attr_excerpt_parses_and_recompacts_json_string() -> None:
    """Input is the typical OpenInference shape: JSON encoded as a string."""
    payload = '{"label": "FRAUD", "confidence": 0.97, "true_label": "APPROVE"}'
    out = _attr_excerpt({"output.value": payload}, "output.value")
    # Re-parsed compact form — no whitespace
    assert ' ' not in out  # compact
    assert '"label":"FRAUD"' in out
    assert '"true_label":"APPROVE"' in out


def test_attr_excerpt_passes_through_non_json_strings() -> None:
    payload = "plain old text, not json"
    out = _attr_excerpt({"input.value": payload}, "input.value")
    assert out == payload


def test_attr_excerpt_truncates_with_ellipsis() -> None:
    big = {"text": "x" * 1000}
    out = _attr_excerpt({"output.value": json.dumps(big)}, "output.value", max_chars=60)
    assert len(out) == 60
    assert out.endswith("…")


def test_attr_excerpt_serializes_inline_dict_value() -> None:
    """Defensive: if the attribute is already a dict (not a JSON string), still works."""
    raw_dict = {"label": "APPROVE", "confidence": 0.9}
    out = _attr_excerpt({"output.value": raw_dict}, "output.value")
    parsed = json.loads(out)  # round-trip via json
    assert parsed == raw_dict


# ── _format_span_block ─────────────────────────────────────────────────────


def _span(
    *,
    name: str = "classify_transaction",
    kind: str = "LLM",
    status: str = "OK",
    status_message: str = "",
    start: str = "2026-05-26T01:00:00+00:00",
    end: str = "2026-05-26T01:00:00.150000+00:00",
    attributes: dict | None = None,
) -> dict:
    return {
        "name": name,
        "span_kind": kind,
        "status_code": status,
        "status_message": status_message,
        "start_time": start,
        "end_time": end,
        "attributes": attributes or {},
    }


def test_span_block_header_line_always_present() -> None:
    block = _format_span_block(1, _span())
    first_line = block.splitlines()[0]
    assert first_line.startswith("1. classify_transaction | kind=LLM")
    assert "status=OK" in first_line
    assert "150ms" in first_line


def test_span_block_omits_optional_lines_when_no_attrs() -> None:
    """Bare span with no attributes / no status_message → single header line."""
    block = _format_span_block(2, _span())
    assert len(block.splitlines()) == 1


def test_span_block_includes_input_and_output_excerpts() -> None:
    """OpenInference-shaped span with input/output JSON attributes."""
    span = _span(
        status="ERROR",
        status_message="false positive: legitimate transaction flagged as FRAUD",
        attributes={
            "input.value": json.dumps(
                {"tx_id": "tx-abc", "amount_usd": 850, "merchant_category": "electronics"}
            ),
            "output.value": json.dumps(
                {"label": "FRAUD", "confidence": 0.97, "true_label": "APPROVE", "post_hoc_verified": True}
            ),
        },
    )
    block = _format_span_block(3, span)
    lines = block.splitlines()
    assert len(lines) == 4
    assert "status=ERROR" in lines[0]
    assert "status_message: false positive" in lines[1]
    assert "input:" in lines[2]
    assert '"tx_id":"tx-abc"' in lines[2]
    assert "output:" in lines[3]
    # The CRITICAL field for semantic grounding — true_label MUST surface
    assert '"true_label":"APPROVE"' in lines[3]
    assert '"label":"FRAUD"' in lines[3]


def test_span_block_includes_status_message_alone_when_no_attrs() -> None:
    span = _span(
        status="ERROR",
        status_message="upstream timeout",
        attributes={},
    )
    block = _format_span_block(4, span)
    lines = block.splitlines()
    assert len(lines) == 2
    assert "status_message: upstream timeout" in lines[1]


def test_span_block_handles_missing_attributes_key() -> None:
    """Real Phoenix responses sometimes omit `attributes` entirely."""
    span = {
        "name": "classify_transaction",
        "span_kind": "LLM",
        "status_code": "OK",
        "start_time": "2026-05-26T01:00:00+00:00",
        "end_time": "2026-05-26T01:00:00.100000+00:00",
        # no `attributes` key at all
    }
    block = _format_span_block(5, span)
    assert "100ms" in block
    # No crash; just the header line
    assert len(block.splitlines()) == 1


def test_span_block_truncates_very_long_output_payload() -> None:
    """A massive output JSON should be truncated, not dump the whole thing."""
    big_output = json.dumps({"data": "x" * 5000})
    span = _span(attributes={"output.value": big_output})
    block = _format_span_block(6, span)
    output_line = next(line for line in block.splitlines() if line.lstrip().startswith("output:"))
    assert "…" in output_line  # truncation marker present
    assert len(output_line) < 400  # well bounded
