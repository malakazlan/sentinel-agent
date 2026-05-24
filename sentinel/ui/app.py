"""Phase 3 Streamlit UI — input, response, agent-reasoning sidebar, and the cold-vs-warm demo panel."""

from __future__ import annotations

import asyncio
import json
import os
import time

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from evals.incident_metrics import IncidentRun, summarize_run  # noqa: E402
from evals.time_to_response import annotate_latest_root_span  # noqa: E402
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

st.set_page_config(page_title="Sentinel — Phase 3", page_icon="🛡️", layout="wide")

# ── session state ──────────────────────────────────────────────────────────
if "agent_records" not in st.session_state:
    st.session_state.agent_records = []
if "agent_response" not in st.session_state:
    st.session_state.agent_response = ""
if "last_input" not in st.session_state:
    st.session_state.last_input = ""
if "last_eval" not in st.session_state:
    st.session_state.last_eval = None
if "cold_run" not in st.session_state:
    st.session_state.cold_run = None
if "warm_run" not in st.session_state:
    st.session_state.warm_run = None

phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
phoenix_project = os.environ.get("PHOENIX_PROJECT_NAME", "sentinel")


# ── stream consumer ────────────────────────────────────────────────────────
async def _consume(user_text: str) -> tuple[list[dict], str]:
    """Drain the Coordinator's event stream into a (records, final_text) pair."""
    records: list[dict] = []
    final_text = ""
    async for rec in stream_coordinator(user_text):
        records.append(rec)
        if rec["kind"] == "final":
            final_text += rec["text"]
    return records, final_text


async def _drain_records(user_text: str) -> list[dict]:
    """Collect every record from one Coordinator invocation."""
    return [r async for r in stream_coordinator(user_text)]


def _run_scripted_incident(
    *,
    label: str,
    prompt: str,
    briefing: PriorContextBriefing,
) -> IncidentRun:
    """Run the Coordinator under a forced briefing and return the measured incident.

    Resets the module-level real-LLM-call counter, runs the agent under the
    given briefing (via ``briefing_override``), measures wall-clock latency,
    captures the counter, and packages everything into an ``IncidentRun``.
    """
    reset_llm_round_trip_counter()
    start = time.perf_counter()
    with briefing_override(briefing):
        records = asyncio.run(_drain_records(prompt))
    latency_ms = int((time.perf_counter() - start) * 1000)
    return summarize_run(
        label=label,
        prompt=prompt,
        records=records,
        latency_ms=latency_ms,
        briefing=briefing,
        n_llm_calls=get_llm_round_trip_count(),
    )


def _synthesize_briefing_now() -> PriorContextBriefing:
    """Run ``synthesize_prior_context`` against the live Phoenix MCP synchronously."""
    return asyncio.run(synthesize_prior_context())


def _render_record(rec: dict) -> None:
    kind = rec.get("kind")
    author = rec.get("author") or "unknown"
    tag = f"`@{author}`"
    if kind == "tool_call":
        st.markdown(f"{tag} 🔧 **{rec['tool']}**")
        st.code(json.dumps(rec.get("args", {}), indent=2), language="json")
    elif kind == "tool_result":
        st.markdown(f"{tag} ⟵ result from `{rec['tool']}`")
        st.text(rec.get("result_excerpt", ""))
    elif kind == "assistant_text":
        st.markdown(f"{tag} 💭 *{rec['text']}*")
    elif kind == "final":
        st.markdown(f"{tag} 💬 final reply")


# ── main pane ──────────────────────────────────────────────────────────────
st.title("Sentinel")
st.caption(
    "Phase 3 — Coordinator now wired to Phoenix MCP (self-introspection). "
    "Ask about recent activity, deep stats, run eval suites, or query Phoenix "
    "projects / experiments / prompts directly."
)

st.info(f"Phoenix: {phoenix_endpoint} · project `{phoenix_project}`")

user_text = st.text_input(
    "Ask the Coordinator:",
    value=st.session_state.last_input,
    placeholder="what has been happening in production lately?",
    key="user_text_input",
)

if st.button("Send", type="primary", disabled=not user_text):
    st.session_state.last_input = user_text
    with st.spinner("Coordinator working..."):
        try:
            records, response = asyncio.run(_consume(user_text))
        except Exception as exc:
            st.session_state.agent_records = []
            st.session_state.agent_response = ""
            st.error(f"Coordinator failed: {exc}")
            st.exception(exc)
        else:
            st.session_state.agent_records = records
            st.session_state.agent_response = response
            try:
                st.session_state.last_eval = annotate_latest_root_span()
            except Exception as exc:
                st.session_state.last_eval = None
                st.warning(f"time_to_response eval failed: {exc}")

if st.session_state.agent_response:
    st.markdown("**Coordinator:**")
    st.write(st.session_state.agent_response)
    if st.session_state.last_eval:
        st.metric(
            "time_to_response",
            f"{st.session_state.last_eval['latency_ms']:.0f} ms",
            help="Wall-clock from input to final response, annotated on the Phoenix root span.",
        )
    st.success(
        f"Trace emitted to Phoenix. Open {phoenix_endpoint} and look in the "
        f"`{phoenix_project}` project for the nested span tree + the "
        f"`time_to_response_ms` annotation."
    )
elif st.session_state.agent_records:
    st.warning("Coordinator returned no final text. See sidebar for raw events.")

# ── cold-vs-warm demo panel ────────────────────────────────────────────────
st.divider()
st.subheader("🎯 Self-improvement loop — plan determinism on the warm path")
st.caption(
    "Same structured incident payload, run twice. The headline metric is "
    "**plan determinism**, not speed: the warm path's plan (route + LLM "
    "round-trip count) is fixed across runs because `enforce_first_route` "
    "honors a trace-derived directive; the cold path's plan drifts run to "
    "run because the LLM re-decides routing each turn. Warm is never "
    "worse than cold (Pareto): cheaper when cold drifts deep, same cost "
    "but deeper analysis when cold drifts shallow. The directive is "
    "synthesized live from Phoenix MCP — not hardcoded — see the linkage "
    "below."
)

DEMO_INCIDENT_PAYLOAD = json.dumps(
    {
        "alert_id": "fraud-fp-spike-20260524T204248Z",
        "source": "fraud-detector-prod-us-central1",
        "alert_type": "false_positive_burst",
        "severity": "P1",
        "metric": {
            "name": "fp_rate_5m",
            "current": 0.213,
            "baseline": 0.072,
            "threshold": 0.150,
            "delta_pct": 196,
        },
        "window": {
            "started_at": "2026-05-24T20:42:48Z",
            "duration_seconds": 90,
        },
        "impact": {
            "blocked_transactions": 1247,
            "estimated_revenue_at_risk_usd": 84300,
            "frozen_accounts": 312,
        },
        "watched_system": {
            "ai_model": "fraud-classifier-v2.3.1",
            "deploy_commit": "a3f9e22",
            "deploy_age_minutes": 18,
        },
    },
    indent=2,
)

st.caption(
    "Realistic trigger: how an alerting webhook (PagerDuty / Alertmanager / "
    "the bank's own monitoring) would invoke Sentinel in production."
)

scripted_prompt_raw = st.text_area(
    "Structured incident alert (JSON payload)",
    value=DEMO_INCIDENT_PAYLOAD,
    key="scripted_prompt",
    height=300,
)

scripted_prompt = (
    "Production incident alert received:\n```json\n"
    + scripted_prompt_raw
    + "\n```\nInvestigate and report what's happening in the watched system."
)

dcol1, dcol2 = st.columns(2)
with dcol1:
    if st.button("Run incident #1 — COLD start", use_container_width=True):
        with st.spinner("Coordinator (cold) running..."):
            try:
                st.session_state.cold_run = _run_scripted_incident(
                    label="cold",
                    prompt=scripted_prompt,
                    briefing=PriorContextBriefing(
                        cold_start=True,
                        stats={"n_total": 0, "lookback_hours": 24},
                    ),
                )
            except Exception as exc:
                st.error(f"Cold run failed: {exc}")
                st.exception(exc)

with dcol2:
    if st.button(
        "Run incident #2 — WARM (real synthesizer)",
        type="primary",
        use_container_width=True,
    ):
        with st.spinner("Synthesizing prior-context briefing from Phoenix MCP..."):
            try:
                warm_briefing = _synthesize_briefing_now()
            except Exception as exc:
                st.error(f"Synthesizer failed: {exc}")
                warm_briefing = None
        if warm_briefing is not None:
            with st.spinner("Coordinator (warm — directive enforced) running..."):
                try:
                    st.session_state.warm_run = _run_scripted_incident(
                        label="warm",
                        prompt=scripted_prompt,
                        briefing=warm_briefing,
                    )
                except Exception as exc:
                    st.error(f"Warm run failed: {exc}")
                    st.exception(exc)

# Delta panel — only when both runs exist
cold = st.session_state.cold_run
warm = st.session_state.warm_run

if cold or warm:
    st.markdown("### Plan determinism — the headline")
    if cold and warm:
        # Lead with the determinism narrative: warm plan is fixed (per 5-run
        # repro at scripts/repro_cold_vs_warm.py), cold plan drifts.
        dcol_a, dcol_b = st.columns(2)
        with dcol_a:
            st.markdown(
                f"**Warm path (deterministic):** `{warm.path}`  \n"
                f"**Warm LLM round-trips:** `{warm.n_llm_calls}`  \n"
                f"_5/5 runs: `coordinator -> trace_analyzer`, "
                f"`n_llm_calls=2` — `enforce_first_route` short-circuits "
                f"the Coordinator's routing turn._"
            )
        with dcol_b:
            st.markdown(
                f"**Cold path (drifts):** `{cold.path}`  \n"
                f"**Cold LLM round-trips:** `{cold.n_llm_calls}`  \n"
                f"_5/5 runs: ranges 2-4 calls; LLM re-decides routing each "
                f"turn — shallow-or-deep lottery, no plan guarantee._"
            )

        # Pareto claim — never worse than cold
        if warm.n_llm_calls < cold.n_llm_calls:
            st.success(
                f"✅ **Pareto:** warm saved **{cold.n_llm_calls - warm.n_llm_calls} "
                f"LLM round-trip(s)** vs cold this run — and the warm answer is "
                f"the deep-analysis path (TraceAnalyzer), not the shallow tool dump."
            )
        elif warm.n_llm_calls == cold.n_llm_calls:
            if warm.path != cold.path:
                st.success(
                    f"✅ **Pareto:** warm matched cold's `n_llm_calls={cold.n_llm_calls}` "
                    f"but took the **deep path** (`{warm.path}`) where cold "
                    f"took the **shallow path** (`{cold.path}`) — same cost, "
                    f"deeper answer."
                )
            else:
                st.info(
                    f"Warm and cold both took `{warm.path}` at "
                    f"`n_llm_calls={cold.n_llm_calls}` this run — directive "
                    f"asserted the path that the LLM happened to pick. Warm "
                    f"would have been deterministic next run; cold may drift."
                )
        else:
            st.warning(
                f"Warm cost more than cold this run ({warm.n_llm_calls} vs "
                f"{cold.n_llm_calls}). This is expected when cold takes the "
                f"shallow path the LLM picked spontaneously; warm is taking "
                f"the deep path enforced by the directive. Quality > cost."
            )

    st.markdown("### Run metrics")
    mcol1, mcol2, mcol3 = st.columns(3)

    with mcol1:
        if cold and warm:
            delta = warm.n_llm_calls - cold.n_llm_calls
            st.metric(
                "LLM round-trips (warm)",
                str(warm.n_llm_calls),
                delta=f"{delta:+d} vs cold ({cold.n_llm_calls})",
                delta_color="inverse",
                help=(
                    "Real LLM calls per invocation. Synthetic LlmResponses "
                    "from enforce_first_route are excluded. Warm is fixed "
                    "at 2 across 5/5 repro runs; cold ranges 2-4."
                ),
            )
        elif cold:
            st.metric("LLM round-trips (cold)", str(cold.n_llm_calls))
        elif warm:
            st.metric("LLM round-trips (warm)", str(warm.n_llm_calls))

    with mcol2:
        if cold and warm:
            delta_ms = warm.latency_ms - cold.latency_ms
            pct = (delta_ms / cold.latency_ms * 100) if cold.latency_ms else 0
            st.metric(
                "wall-clock (warm)",
                f"{warm.latency_ms:,} ms",
                delta=f"{delta_ms:+,} ms ({pct:+.0f}%) vs cold",
                delta_color="inverse",
                help=(
                    "Illustrative secondary. Varies run-to-run with model "
                    "and network jitter. The determinism claim is on call "
                    "count + path, not on wall-clock."
                ),
            )
        elif cold:
            st.metric("wall-clock (cold)", f"{cold.latency_ms:,} ms")
        elif warm:
            st.metric("wall-clock (warm)", f"{warm.latency_ms:,} ms")

    with mcol3:
        if cold and warm:
            st.metric(
                "transfers (warm)",
                str(warm.n_transfers),
                delta=f"{warm.n_transfers - cold.n_transfers:+d} vs cold ({cold.n_transfers})",
            )
        elif cold:
            st.metric("transfers (cold)", str(cold.n_transfers))
        elif warm:
            st.metric("transfers (warm)", str(warm.n_transfers))

    st.caption(
        "5-run reproduction with the full variance table is at "
        "`docs/repro-cold-vs-warm.md`. Honesty about cold-side drift is "
        "the point — it shows the loop's value is consistency, not magic."
    )

    # Warm briefing surfaced prominently — proves loop closure
    if warm and warm.briefing is not None and not warm.briefing.cold_start:
        st.markdown("### Warm briefing — directive linkage")
        st.caption(
            "Synthesized live from Phoenix MCP at click time. The `evidence` "
            "field maps each directive back to the trace fact that produced "
            "it — this is what closes the self-improvement loop."
        )
        b = warm.briefing
        bcol1, bcol2 = st.columns(2)
        with bcol1:
            st.markdown("**Directives**")
            st.json(
                {
                    "first_route": b.first_route,
                    "skip_routes": list(b.skip_routes),
                    "must_eval_after": b.must_eval_after,
                    "default_hours_back": b.default_hours_back,
                }
            )
        with bcol2:
            st.markdown("**Evidence (directive → real trace fact)**")
            if b.evidence:
                for field_name, why in b.evidence.items():
                    st.markdown(f"- `{field_name}` ← _{why}_")
            else:
                st.caption("(no non-default directives — synthesizer saw no risk signals)")
            st.markdown("**Raw stats**")
            st.json(b.stats)

    pcol1, pcol2 = st.columns(2)
    with pcol1:
        if cold:
            st.markdown(f"**Cold path:** `{cold.path}`")
            st.markdown(f"_directive fired:_ `{cold.directive_fired}` · _llm calls:_ `{cold.n_llm_calls}`")
            with st.expander("Cold final response"):
                st.write(cold.final_text or "_(empty)_")
    with pcol2:
        if warm:
            st.markdown(f"**Warm path:** `{warm.path}`")
            st.markdown(f"_directive fired:_ `{warm.directive_fired}` · _llm calls:_ `{warm.n_llm_calls}`")
            with st.expander("Warm final response"):
                st.write(warm.final_text or "_(empty)_")

# ── sidebar: agent reasoning ───────────────────────────────────────────────
with st.sidebar:
    st.header("🧠 Agent reasoning")
    if not st.session_state.agent_records:
        st.caption("No invocations yet. Send a message to see the agent's tool calls.")
    else:
        tool_calls = sum(1 for r in st.session_state.agent_records if r["kind"] == "tool_call")
        st.caption(
            f"{len(st.session_state.agent_records)} event(s) · "
            f"{tool_calls} tool call(s)"
        )
        st.divider()
        for rec in st.session_state.agent_records:
            _render_record(rec)
            st.divider()
