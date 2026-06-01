"""Tests for the ParallelEvalRunner (ADR-012 / Phase 7 Addition 1).

Two layers tested:

1. **Composition shape** — `parallel_eval_runner` is a `SequentialAgent` whose
   first child is a `ParallelAgent` over the four named evaluators. This
   asserts the orchestration topology matches the ADR.
2. **Concurrency** — the four evaluator tools share the same asyncio substrate
   that ADK's ParallelAgent uses. Stubbed-delay versions of the four eval
   tools, when awaited via ``asyncio.gather`` (the same primitive
   ``ParallelAgent`` calls internally), complete faster than the strict sum
   of their sleeps. This is the wall-clock invariant ADR-012 relies on.

The composition test is fast; the concurrency test is also fast (4 × 200ms
stubs → ~200ms parallel vs ~800ms sequential).
"""

from __future__ import annotations

import asyncio
import time

import pytest
from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from sentinel.agents.parallel_eval import (
    drift_evaluator,
    faithfulness_evaluator,
    parallel_eval_runner,
    parallel_fanout,
    prompt_injection_evaluator,
    toxicity_evaluator,
)


# ── Composition tests ─────────────────────────────────────────────────────


def test_parallel_eval_runner_is_a_sequential_agent() -> None:
    assert isinstance(parallel_eval_runner, SequentialAgent)
    assert parallel_eval_runner.name == "parallel_eval_runner"


def test_first_child_is_the_parallel_fanout() -> None:
    children = list(parallel_eval_runner.sub_agents)
    assert len(children) == 2, "expected fanout + summarizer"
    assert isinstance(children[0], ParallelAgent)
    assert children[0] is parallel_fanout


def test_parallel_fanout_has_four_named_evaluators() -> None:
    leaves = list(parallel_fanout.sub_agents)
    assert len(leaves) == 4
    leaf_names = {a.name for a in leaves}
    assert leaf_names == {
        "faithfulness_evaluator",
        "drift_evaluator",
        "prompt_injection_evaluator",
        "toxicity_evaluator",
    }


def test_each_evaluator_writes_to_its_own_state_key() -> None:
    # LlmAgent is a Pydantic BaseModel without hash semantics, so we use a
    # list of tuples rather than a dict keyed by agent objects.
    expected: list[tuple[LlmAgent, str]] = [
        (faithfulness_evaluator, "faithfulness_result"),
        (drift_evaluator, "drift_result"),
        (prompt_injection_evaluator, "prompt_injection_result"),
        (toxicity_evaluator, "toxicity_result"),
    ]
    for agent, key in expected:
        assert isinstance(agent, LlmAgent)
        assert agent.output_key == key, (
            f"{agent.name} output_key={agent.output_key!r}, expected {key!r}"
        )


# ── Concurrency test ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_asyncio_gather_beats_sequential_sum() -> None:
    """The substrate ``ParallelAgent`` uses (asyncio task scheduling) must
    complete the four eval awaits faster than their sequential sum.

    This is the wall-clock invariant ADR-012 relies on for the demo: with
    four leaves each taking ~T seconds on a real Gemini call, the fan-out
    should land in ~T (not 4T) wall-clock.
    """
    sleep_ms = 200
    n = 4

    async def stub_eval() -> str:
        await asyncio.sleep(sleep_ms / 1000)
        return "ok"

    # Sequential baseline
    seq_start = time.perf_counter()
    for _ in range(n):
        await stub_eval()
    seq_elapsed = time.perf_counter() - seq_start

    # Parallel via the same primitive ParallelAgent uses
    par_start = time.perf_counter()
    await asyncio.gather(*[stub_eval() for _ in range(n)])
    par_elapsed = time.perf_counter() - par_start

    # Parallel must be meaningfully faster than sequential — at minimum
    # less than half the sequential time (very loose threshold for CI noise).
    assert par_elapsed < seq_elapsed / 2, (
        f"parallel ({par_elapsed:.3f}s) not meaningfully faster than "
        f"sequential ({seq_elapsed:.3f}s)"
    )
    # And it should be close to a single stub's wall-clock — within 3x of
    # the single-stub time accounts for asyncio scheduling overhead.
    assert par_elapsed < (sleep_ms / 1000) * 3, (
        f"parallel ({par_elapsed:.3f}s) too slow relative to single stub "
        f"({sleep_ms}ms)"
    )
