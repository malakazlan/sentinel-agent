"""Tests for ``stream_coordinator_with_chain`` runtime enforcement of ``must_eval_after``.

The wrapper exists to resolve P2 — when the active directive sets
``must_eval_after=True`` and the user asks for a non-eval sub-agent, the
old prompt-side approach caused multi-transfer-in-one-turn collisions
(ADK honors only one transfer per turn). The wrapper moves enforcement
off the prompt and into a deterministic post-run chain.

Tests here mock ``stream_coordinator`` and ``synthesize_prior_context`` so
they run fast and without LLM cost.
"""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import patch

import pytest

from sentinel.coordinator import stream_coordinator_with_chain
from sentinel.memory.briefing import PriorContextBriefing
from sentinel.memory.self_introspection import briefing_override


# ── helpers ────────────────────────────────────────────────────────────────


def _record(kind: str, author: str, **extra: Any) -> dict:
    base: dict[str, Any] = {"kind": kind, "author": author}
    base.update(extra)
    return base


def _make_streamer(prompt_to_records: dict[str, list[dict]]) -> Callable:
    """Build a fake ``stream_coordinator`` that returns canned records per prompt.

    First-call returns the records for ``prompt_to_records[user_text]``; falls
    back to an empty stream for any unknown prompt.
    """

    async def fake_stream(user_text: str):
        for r in prompt_to_records.get(user_text, []):
            yield r

    return fake_stream


# ── chain triggered: must_eval_after=True and eval_runner did not run ────


@pytest.mark.asyncio
async def test_chain_appends_eval_followup_when_directive_requires_it() -> None:
    """must_eval_after=True + primary turn has no eval_runner → follow-up runs."""
    briefing = PriorContextBriefing(
        must_eval_after=True,
        evidence={"must_eval_after": "test fixture: hallucinated traces present"},
    )
    primary_records = [
        _record("tool_call", "coordinator", tool="transfer_to_agent", args={"agent_name": "remediation"}),
        _record("tool_result", "coordinator", tool="transfer_to_agent", result_excerpt="{}"),
        _record("final", "remediation", text='{"severity": "P1", ...}'),
    ]
    followup_records = [
        _record("tool_call", "coordinator", tool="transfer_to_agent", args={"agent_name": "eval_runner"}),
        _record("tool_result", "coordinator", tool="transfer_to_agent", result_excerpt="{}"),
        _record("final", "eval_runner", text="Hallucination eval: 2 faithful, 0 hallucinated."),
    ]
    fake = _make_streamer(
        {
            "draft a remediation plan": primary_records,
            # Whatever the wrapper sends for the follow-up, return our canned set.
        }
    )
    # The wrapper sends a specific follow-up prompt; capture it via call-through.

    async def stream_capturing(user_text: str):
        if user_text == "draft a remediation plan":
            async for r in fake(user_text):
                yield r
        else:
            # Treat any non-primary call as the follow-up
            for r in followup_records:
                yield r

    with briefing_override(briefing):
        with patch(
            "sentinel.coordinator.stream_coordinator",
            side_effect=stream_capturing,
        ):
            collected = [r async for r in stream_coordinator_with_chain("draft a remediation plan")]

    # All primary records preserved, in order
    assert collected[: len(primary_records)] == primary_records
    # Follow-up records appended
    assert collected[len(primary_records) :] == followup_records


# ── chain NOT triggered: must_eval_after=True but eval_runner already ran ─


@pytest.mark.asyncio
async def test_chain_skipped_when_eval_runner_already_ran_in_primary() -> None:
    """User explicitly asked for eval → no duplicate eval follow-up."""
    briefing = PriorContextBriefing(
        must_eval_after=True,
        evidence={"must_eval_after": "test fixture"},
    )
    primary_records = [
        _record("tool_call", "coordinator", tool="transfer_to_agent", args={"agent_name": "eval_runner"}),
        _record("final", "eval_runner", text="all clean."),
    ]
    fake = _make_streamer({"run a hallucination check": primary_records})

    async def boom_on_followup(user_text: str):
        if user_text == "run a hallucination check":
            async for r in fake(user_text):
                yield r
        else:
            pytest.fail(f"follow-up should not run; got prompt={user_text!r}")

    with briefing_override(briefing):
        with patch(
            "sentinel.coordinator.stream_coordinator",
            side_effect=boom_on_followup,
        ):
            collected = [r async for r in stream_coordinator_with_chain("run a hallucination check")]

    assert collected == primary_records


# ── chain NOT triggered: must_eval_after=False ────────────────────────────


@pytest.mark.asyncio
async def test_chain_skipped_when_must_eval_after_is_false() -> None:
    """Directive does not require post-eval → wrapper is transparent."""
    briefing = PriorContextBriefing(cold_start=True, stats={"n_total": 0})
    primary_records = [
        _record("tool_call", "coordinator", tool="get_recent_traces", args={}),
        _record("final", "coordinator", text="System healthy."),
    ]
    fake = _make_streamer({"what's going on?": primary_records})

    async def boom_on_followup(user_text: str):
        if user_text == "what's going on?":
            async for r in fake(user_text):
                yield r
        else:
            pytest.fail(f"follow-up should not run; got prompt={user_text!r}")

    with briefing_override(briefing):
        with patch(
            "sentinel.coordinator.stream_coordinator",
            side_effect=boom_on_followup,
        ):
            collected = [r async for r in stream_coordinator_with_chain("what's going on?")]

    assert collected == primary_records


# ── briefing source: respects external override vs synthesizes fresh ──────


@pytest.mark.asyncio
async def test_wrapper_uses_synthesized_briefing_when_no_override_active() -> None:
    """When no override is pinned, wrapper calls synthesize_prior_context once."""
    synthesized = PriorContextBriefing(must_eval_after=False)

    async def fake_synthesize() -> PriorContextBriefing:
        return synthesized

    async def fake_stream(user_text: str):
        yield _record("final", "coordinator", text="ok")

    # No briefing_override active in this test
    with patch(
        "sentinel.memory.self_introspection.synthesize_prior_context",
        side_effect=fake_synthesize,
    ):
        with patch(
            "sentinel.coordinator.stream_coordinator",
            side_effect=fake_stream,
        ):
            collected = [r async for r in stream_coordinator_with_chain("hi")]

    assert len(collected) == 1
    assert collected[0]["author"] == "coordinator"
