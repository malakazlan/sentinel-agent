"""Run the cold-vs-warm scripted incident N times and tabulate metrics.

Supervisor gate (Phase 3 step 3): confirm the headline metric — real LLM
round-trip count — is reproducibly cold→warm across multiple runs.
Wall-clock latency may vary; round-trip count is the invariant.

Usage:
    GOOGLE_CLOUD_PROJECT=<project> python scripts/repro_cold_vs_warm.py [--runs 5]

Warm runs use the **real** ``synthesize_prior_context`` against Phoenix MCP,
not a hardcoded briefing — so the directive linkage in each warm run is
genuine evidence of the loop closing.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from dotenv import load_dotenv

load_dotenv()

from evals.incident_metrics import IncidentRun, summarize_run  # noqa: E402
from sentinel.coordinator import stream_coordinator  # noqa: E402
from sentinel.memory.briefing import PriorContextBriefing  # noqa: E402
from sentinel.memory.enforcement import (  # noqa: E402
    get_llm_round_trip_count,
    reset_llm_round_trip_counter,
)
from sentinel.memory.self_introspection import (  # noqa: E402
    briefing_override,
    synthesize_prior_context,
)
from sentinel.observability.instrumentation import setup_tracing  # noqa: E402

setup_tracing()

DEMO_PROMPT = (
    "Fraud detection alarm: false-positive rate has spiked 3x in the last "
    "90 seconds. Legitimate transactions are being blocked and the support "
    "inbox is flooding. What's happening?"
)


async def _drain(prompt: str) -> list[dict]:
    return [r async for r in stream_coordinator(prompt)]


def _run_once(label: str, briefing: PriorContextBriefing, prompt: str) -> IncidentRun:
    reset_llm_round_trip_counter()
    start = time.perf_counter()
    with briefing_override(briefing):
        records = asyncio.run(_drain(prompt))
    latency_ms = int((time.perf_counter() - start) * 1000)
    return summarize_run(
        label=label,
        prompt=prompt,
        records=records,
        latency_ms=latency_ms,
        briefing=briefing,
        n_llm_calls=get_llm_round_trip_count(),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    cold_briefing = PriorContextBriefing(
        cold_start=True,
        stats={"n_total": 0, "lookback_hours": 24},
    )

    rows: list[tuple[int, IncidentRun, IncidentRun, PriorContextBriefing]] = []
    for i in range(1, args.runs + 1):
        print(f"--- run {i} / {args.runs} ---", flush=True)
        cold = _run_once("cold", cold_briefing, DEMO_PROMPT)
        # Warm: synthesize REAL briefing from live Phoenix MCP for each run
        warm_briefing = asyncio.run(synthesize_prior_context())
        warm = _run_once("warm", warm_briefing, DEMO_PROMPT)
        rows.append((i, cold, warm, warm_briefing))
        print(
            f"  cold: llm={cold.n_llm_calls}  wall={cold.latency_ms}ms  path={cold.path}",
            flush=True,
        )
        print(
            f"  warm: llm={warm.n_llm_calls}  wall={warm.latency_ms}ms  path={warm.path}",
            flush=True,
        )

    # Tabulate
    print()
    print("REPRO TABLE")
    print(
        f"{'run':>3} | {'cold llm':>8} | {'warm llm':>8} | {'Δllm':>5} | "
        f"{'cold ms':>8} | {'warm ms':>8} | {'warm path':<42} | "
        f"{'first_route':<15} | {'evidence excerpt':<60}"
    )
    print("-" * 200)
    for i, cold, warm, brief in rows:
        ev = (brief.evidence.get("first_route") or "(none)")[:58]
        first = str(brief.first_route or "-")
        print(
            f"{i:>3} | {cold.n_llm_calls:>8} | {warm.n_llm_calls:>8} | "
            f"{warm.n_llm_calls - cold.n_llm_calls:>5} | "
            f"{cold.latency_ms:>8} | {warm.latency_ms:>8} | {warm.path:<42} | "
            f"{first:<15} | {ev:<60}"
        )

    # Invariant check
    invariant_ok = all(
        warm.n_llm_calls < cold.n_llm_calls for _, cold, warm, _ in rows
    )
    same_delta = len({warm.n_llm_calls - cold.n_llm_calls for _, cold, warm, _ in rows}) == 1

    print()
    print(f"invariant: warm.n_llm_calls < cold.n_llm_calls on every run? {invariant_ok}")
    print(f"invariant: delta identical on every run?                       {same_delta}")


if __name__ == "__main__":
    main()
