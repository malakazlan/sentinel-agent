"""Unit tests for ``IncidentRun`` summarization.

Pure record-shape assertions — no LLM, no Phoenix. Verify that the
cold-vs-warm demo panel will read the right numbers off whatever the
Coordinator stream yields.
"""

from __future__ import annotations

import pytest

from evals.incident_metrics import IncidentRun, summarize_run
from sentinel.memory.briefing import PriorContextBriefing


def _records_cold_path() -> list[dict]:
    """Simulate a cold-path stream: coordinator calls tool, then final reply."""
    return [
        {
            "kind": "tool_call",
            "author": "coordinator",
            "tool": "get_recent_traces",
            "args": {"hours_back": 1},
        },
        {
            "kind": "tool_result",
            "author": "coordinator",
            "tool": "get_recent_traces",
            "result_excerpt": "Found 5 traces...",
        },
        {
            "kind": "final",
            "author": "coordinator",
            "text": "Cold-path summary.",
        },
    ]


def _records_warm_path() -> list[dict]:
    """Simulate a warm-path stream: coordinator transfers, sub-agent handles."""
    return [
        {
            "kind": "tool_call",
            "author": "coordinator",
            "tool": "transfer_to_agent",
            "args": {"agent_name": "trace_analyzer"},
        },
        {
            "kind": "tool_result",
            "author": "coordinator",
            "tool": "transfer_to_agent",
            "result_excerpt": "{}",
        },
        {
            "kind": "tool_call",
            "author": "trace_analyzer",
            "tool": "get_recent_traces",
            "args": {"hours_back": 1},
        },
        {
            "kind": "tool_result",
            "author": "trace_analyzer",
            "tool": "get_recent_traces",
            "result_excerpt": "Found 5 traces...",
        },
        {
            "kind": "final",
            "author": "trace_analyzer",
            "text": "Warm-path deep analysis.",
        },
    ]


def test_cold_path_counts_one_tool_no_transfer() -> None:
    run = summarize_run(
        label="cold",
        prompt="status?",
        records=_records_cold_path(),
        latency_ms=4200,
        briefing=PriorContextBriefing(cold_start=True),
    )
    assert run.label == "cold"
    assert run.latency_ms == 4200
    assert run.n_tool_calls == 1  # get_recent_traces
    assert run.n_transfers == 0
    assert run.directive_fired is False
    assert run.path == "coordinator"
    assert run.final_text == "Cold-path summary."


def test_warm_path_counts_one_transfer_one_tool() -> None:
    run = summarize_run(
        label="warm",
        prompt="status?",
        records=_records_warm_path(),
        latency_ms=2100,
        briefing=PriorContextBriefing(
            first_route="trace_analyzer",
            evidence={"first_route": "test fixture"},
        ),
    )
    assert run.n_tool_calls == 1  # trace_analyzer's get_recent_traces
    assert run.n_transfers == 1  # coordinator's transfer_to_agent
    assert run.directive_fired is True
    assert run.path == "coordinator -> trace_analyzer"
    assert run.final_text == "Warm-path deep analysis."


def test_directive_fired_is_false_when_briefing_is_none() -> None:
    run = summarize_run(
        label="no-briefing",
        prompt="status?",
        records=_records_cold_path(),
        latency_ms=1000,
        briefing=None,
    )
    assert run.directive_fired is False


def test_directive_fired_true_for_must_eval_after() -> None:
    run = summarize_run(
        label="x",
        prompt="x",
        records=[],
        latency_ms=0,
        briefing=PriorContextBriefing(must_eval_after=True),
    )
    assert run.directive_fired is True


def test_directive_fired_true_for_skip_routes() -> None:
    run = summarize_run(
        label="x",
        prompt="x",
        records=[],
        latency_ms=0,
        briefing=PriorContextBriefing(skip_routes=["eval_runner"]),
    )
    assert run.directive_fired is True


def test_authors_unique_preserves_order() -> None:
    run = IncidentRun(
        label="x",
        prompt="x",
        latency_ms=0,
        n_tool_calls=0,
        n_transfers=0,
        authors=["coordinator", "trace_analyzer", "coordinator", "trace_analyzer"],
    )
    assert run.authors_unique == ["coordinator", "trace_analyzer"]


def test_empty_records_yields_no_records_path() -> None:
    run = summarize_run(
        label="empty",
        prompt="x",
        records=[],
        latency_ms=0,
        briefing=None,
    )
    assert run.path == "(no records)"
    assert run.final_text == ""
    assert run.n_tool_calls == 0
    assert run.n_transfers == 0


def test_briefing_override_isolates_run() -> None:
    """Override is scoped to the context manager — leaks back to None on exit."""
    from sentinel.memory import self_introspection

    assert self_introspection._briefing_override is None
    test_briefing = PriorContextBriefing(first_route="eval_runner")
    with self_introspection.briefing_override(test_briefing):
        assert self_introspection._briefing_override is test_briefing
    assert self_introspection._briefing_override is None


def test_briefing_override_resets_even_on_exception() -> None:
    from sentinel.memory import self_introspection

    test_briefing = PriorContextBriefing(cold_start=True)
    with pytest.raises(RuntimeError):
        with self_introspection.briefing_override(test_briefing):
            raise RuntimeError("simulated")
    assert self_introspection._briefing_override is None


# ── n_llm_calls plumbing ──────────────────────────────────────────────────


def test_summarize_run_passes_n_llm_calls_through() -> None:
    run = summarize_run(
        label="x",
        prompt="x",
        records=[],
        latency_ms=0,
        briefing=None,
        n_llm_calls=3,
    )
    assert run.n_llm_calls == 3


def test_summarize_run_defaults_n_llm_calls_to_zero() -> None:
    run = summarize_run(
        label="x",
        prompt="x",
        records=[],
        latency_ms=0,
        briefing=None,
    )
    assert run.n_llm_calls == 0


async def test_counter_callback_increments_and_resets() -> None:
    """count_real_llm_calls bumps the module counter; reset zeroes it."""
    from sentinel.memory import enforcement

    enforcement.reset_llm_round_trip_counter()
    assert enforcement.get_llm_round_trip_count() == 0

    # Counter callback returns None (does not short-circuit) and increments.
    result = await enforcement.count_real_llm_calls(callback_context=None, llm_request=None)
    assert result is None
    assert enforcement.get_llm_round_trip_count() == 1

    await enforcement.count_real_llm_calls(callback_context=None, llm_request=None)
    assert enforcement.get_llm_round_trip_count() == 2

    enforcement.reset_llm_round_trip_counter()
    assert enforcement.get_llm_round_trip_count() == 0
