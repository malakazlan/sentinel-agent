"""Synthesizer rule tests with mocked MCP responses.

Each test patches the module-level MCP toolset getter to return a fake
toolset that yields a chosen ``list-traces`` / ``get-span-annotations``
envelope, then asserts the synthesizer emits the directive shape the rule
specifies. No real Phoenix or LLM calls.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from sentinel.memory import self_introspection
from sentinel.memory.briefing import PriorContextBriefing


# ── fixture helpers ─────────────────────────────────────────────────────────


def _mcp_envelope(payload: Any) -> dict:
    """Wrap a Python object as the MCP ``{content: [{type, text}]}`` envelope."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "isError": False,
    }


def _root_span(
    *,
    trace_id: str,
    span_id: str,
    status: str = "OK",
    start: str = "2026-05-24T10:00:00+00:00",
    end: str = "2026-05-24T10:00:04+00:00",
) -> dict:
    return {
        "context": {"trace_id": trace_id, "span_id": span_id},
        "parent_id": None,
        "status_code": status,
        "start_time": start,
        "end_time": end,
    }


def _trace_with(root: dict) -> dict:
    return {"traceId": root["context"]["trace_id"], "spans": [root]}


def _annotation(*, span_id: str, label: str) -> dict:
    return {
        "name": "hallucination",
        "span_id": span_id,
        "result": {"label": label, "score": 1.0 if label == "faithful" else 0.0},
    }


class _FakeTool:
    def __init__(self, name: str, return_value: Any) -> None:
        self.name = name
        self._return_value = return_value

    async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> Any:
        return self._return_value


class _FakeToolset:
    def __init__(self, traces_payload: Any, annotations_payload: Any) -> None:
        self._tools = [
            _FakeTool("list-traces", _mcp_envelope(traces_payload)),
            _FakeTool("get-span-annotations", _mcp_envelope(annotations_payload)),
        ]

    async def get_tools(self) -> list[_FakeTool]:
        return self._tools


def _patch_mcp(monkeypatch: pytest.MonkeyPatch, toolset: _FakeToolset) -> None:
    monkeypatch.setattr(self_introspection, "_get_mcp", lambda: toolset)


# ── rule: cold start when no traces ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_start_when_no_traces(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload=[], annotations_payload=[]))
    b = await self_introspection.synthesize_prior_context()
    assert isinstance(b, PriorContextBriefing)
    assert b.cold_start is True
    assert b.first_route is None
    assert b.must_eval_after is False
    assert b.stats["n_total"] == 0


# ── rule: ERROR cluster forces first_route=trace_analyzer (the demo headline) ─


@pytest.mark.asyncio
async def test_error_cluster_forces_first_route_trace_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 of 8 root spans ERROR → first_route='trace_analyzer'."""
    traces_payload = [
        _trace_with(_root_span(
            trace_id=f"trace-{i}",
            span_id=f"span-{i}",
            status="ERROR" if i < 5 else "OK",
        ))
        for i in range(8)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, []))

    b = await self_introspection.synthesize_prior_context()
    assert b.first_route == "trace_analyzer"
    assert "ERROR" in b.evidence.get("first_route", "")
    assert b.stats["n_error"] == 5
    assert b.stats["n_total"] == 8


@pytest.mark.asyncio
async def test_below_error_count_threshold_does_not_set_first_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 of 8 ERROR — below the count threshold (3) — no override."""
    traces_payload = [
        _trace_with(_root_span(
            trace_id=f"trace-{i}",
            span_id=f"span-{i}",
            status="ERROR" if i < 2 else "OK",
        ))
        for i in range(8)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, []))

    b = await self_introspection.synthesize_prior_context()
    assert b.first_route is None


@pytest.mark.asyncio
async def test_high_error_count_but_low_share_does_not_force_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 of 20 ERROR — count passes but ratio (15%) below threshold (30%)."""
    traces_payload = [
        _trace_with(_root_span(
            trace_id=f"trace-{i}",
            span_id=f"span-{i}",
            status="ERROR" if i < 3 else "OK",
        ))
        for i in range(20)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, []))

    b = await self_introspection.synthesize_prior_context()
    assert b.first_route is None


# ── rule: any recent hallucination → must_eval_after ─────────────────────────


@pytest.mark.asyncio
async def test_hallucination_annotation_forces_must_eval_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    traces_payload = [
        _trace_with(_root_span(trace_id="trace-1", span_id="span-1", status="OK")),
    ]
    annotations_payload = [_annotation(span_id="span-1", label="hallucinated")]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, annotations_payload))

    b = await self_introspection.synthesize_prior_context()
    assert b.must_eval_after is True
    assert "hallucinat" in b.evidence.get("must_eval_after", "").lower()


@pytest.mark.asyncio
async def test_only_faithful_annotations_does_not_force_must_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    traces_payload = [
        _trace_with(_root_span(trace_id=f"t-{i}", span_id=f"s-{i}", status="OK"))
        for i in range(3)
    ]
    annotations_payload = [
        _annotation(span_id=f"s-{i}", label="faithful") for i in range(3)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, annotations_payload))

    b = await self_introspection.synthesize_prior_context()
    assert b.must_eval_after is False


# ── rule: low volume widens default_hours_back ───────────────────────────────


@pytest.mark.asyncio
async def test_low_volume_widens_default_hours_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 traces < threshold (3) → default_hours_back=24 instead of 1."""
    traces_payload = [
        _trace_with(_root_span(trace_id=f"t-{i}", span_id=f"s-{i}"))
        for i in range(2)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, []))

    b = await self_introspection.synthesize_prior_context()
    assert b.default_hours_back == 24
    assert "default_hours_back" in b.evidence


@pytest.mark.asyncio
async def test_healthy_volume_keeps_narrow_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    traces_payload = [
        _trace_with(_root_span(trace_id=f"t-{i}", span_id=f"s-{i}"))
        for i in range(10)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, []))

    b = await self_introspection.synthesize_prior_context()
    assert b.default_hours_back == 1


# ── narrative discipline: skip_routes left empty in normal cases ─────────────


@pytest.mark.asyncio
async def test_clean_normal_case_emits_no_skip_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-009 narrative: skip_routes is not the demo's headline mechanism."""
    traces_payload = [
        _trace_with(_root_span(trace_id=f"t-{i}", span_id=f"s-{i}", status="OK"))
        for i in range(5)
    ]
    annotations_payload = [
        _annotation(span_id=f"s-{i}", label="faithful") for i in range(5)
    ]
    _patch_mcp(monkeypatch, _FakeToolset(traces_payload, annotations_payload))

    b = await self_introspection.synthesize_prior_context()
    assert b.skip_routes == []
    assert b.first_route is None  # no override on clean state
    assert b.must_eval_after is False


# ── error path: MCP failure surfaces as cold-start, never raises ─────────────


@pytest.mark.asyncio
async def test_mcp_failure_yields_cold_start_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomToolset:
        async def get_tools(self) -> list:
            raise RuntimeError("MCP unreachable")

    monkeypatch.setattr(self_introspection, "_get_mcp", lambda: _BoomToolset())

    b = await self_introspection.synthesize_prior_context()
    assert b.cold_start is True
    assert "MCP" in b.evidence.get("cold_start", "") or "RuntimeError" in b.evidence.get(
        "cold_start", ""
    )
