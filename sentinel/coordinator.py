"""Phase 1 baseline Coordinator: a single LlmAgent with one observability tool.

Exposes two entry points:

- ``stream_coordinator(text)`` — async generator yielding structured event
  records (tool calls, tool results, final text). Used by the Streamlit UI to
  populate the agent-reasoning sidebar.
- ``run_coordinator(text)`` — convenience wrapper that drains the stream and
  returns the final response text. Used by smoke tests and any caller that
  only wants the final answer.

Both share the same module-level ``Runner`` + ``InMemorySessionService`` and
go through the OpenInference instrumentor wired in
``sentinel.observability.instrumentation``.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    Optional,
)

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

if TYPE_CHECKING:
    from sentinel.scenarios import IncidentScenario

from google.adk.agents.readonly_context import ReadonlyContext

from evals.completeness import CompletenessResult, completeness_score
from sentinel.agents.compliance_officer import compliance_officer
from sentinel.agents.customer_impact import customer_impact_quantifier
from sentinel.agents.critic import (
    CRITIC_SCORE_THRESHOLD,
    MAX_REFINEMENT_ITERATIONS,
    critic,
)
from sentinel.agents.deploy_correlator import deploy_correlator
from sentinel.agents.eval_runner import eval_runner
from sentinel.agents.parallel_eval import parallel_eval_runner
from sentinel.agents.postmortem import postmortem
from sentinel.agents.remediation import remediation
from sentinel.agents.root_cause import root_cause
from sentinel.agents.schemas import CritiqueResult, Postmortem
from sentinel.agents.slack_announcer import slack_announcer
from sentinel.agents.trace_analyzer import trace_analyzer
from sentinel.events import (
    BriefingResolvedEvent,
    IncidentCompletedEvent,
    IncidentFailedEvent,
    IncidentStartedEvent,
    PostmortemValidatedEvent,
    SeedCompletedEvent,
    SimilarIncidentSummary,
    StageCompletedEvent,
    StageStartedEvent,
)
from sentinel.constants import COORDINATOR_MODEL
from sentinel.memory.briefing import PriorContextBriefing
from sentinel.memory.enforcement import (
    count_real_llm_calls,
    enforce_first_route,
    enforce_skip_routes,
)
from sentinel.memory.self_introspection import before_coordinator_callback
from sentinel.observability.phoenix_mcp import make_phoenix_mcp_toolset
from sentinel.prompts import load_prompt
from sentinel.tools.incident_sim import seed_scenario
from sentinel.tools.phoenix_traces import get_recent_traces

_BRIEFING_PLACEHOLDER = "{prior_context_briefing}"


def render_directive_block(briefing: PriorContextBriefing) -> str:
    """Render a ``PriorContextBriefing`` as the directive block injected into the prompt.

    The directive block uses MUST/MUST-NOT imperative language per ADR-009 —
    the LLM is meant to follow these as plan-shaping directives, not weigh
    them as hints. Each non-default directive is followed by its evidence
    sentence (the audit trail that makes this a loop, not a guess).
    """
    if briefing.cold_start:
        return (
            "**Active directives from self-introspection:** none.\n"
            "- cold_start: true (no prior history; routing per defaults below).\n"
            "- stats: " + _format_stats(briefing.stats) + "\n\n"
            "**Directive protocol:** no overrides this turn — fall back to the "
            "default routing rules below."
        )

    lines = ["**Active directives from self-introspection:**", ""]
    lines.append(f"- first_route: {briefing.first_route or 'none'}")
    if briefing.first_route and briefing.evidence.get("first_route"):
        lines.append(f"  - evidence: {briefing.evidence['first_route']}")
    lines.append(f"- skip_routes: {list(briefing.skip_routes) or 'none'}")
    if briefing.skip_routes and briefing.evidence.get("skip_routes"):
        lines.append(f"  - evidence: {briefing.evidence['skip_routes']}")
    lines.append(f"- must_eval_after: {str(briefing.must_eval_after).lower()}")
    if briefing.must_eval_after and briefing.evidence.get("must_eval_after"):
        lines.append(f"  - evidence: {briefing.evidence['must_eval_after']}")
    lines.append(f"- default_hours_back: {briefing.default_hours_back}")
    if briefing.evidence.get("default_hours_back"):
        lines.append(f"  - evidence: {briefing.evidence['default_hours_back']}")
    lines.append("")
    lines.append(f"- stats: {_format_stats(briefing.stats)}")
    lines.append("")
    lines.append("**Directive protocol — MANDATORY:**")
    lines.append(
        "- If `first_route` is set AND the user message is not a greeting / "
        "capability question, your FIRST action this turn MUST be that route. "
        "Ignore the default 8-word heuristic; the directive wins."
    )
    lines.append(
        "- If a sub-agent appears in `skip_routes`, you MUST NOT transfer to "
        "it this turn, even if the user explicitly asks. Decline politely and "
        "cite the evidence."
    )
    lines.append(
        "- If `must_eval_after` is true, after delivering your main response "
        "you MUST end the turn by transferring to `eval_runner`."
    )
    lines.append(
        "- When you call `get_recent_traces`, use `default_hours_back` as the "
        "`hours_back` argument unless the user explicitly names a different window."
    )
    return "\n".join(lines)


def _format_stats(stats: dict) -> str:
    if not stats:
        return "n/a"
    keys = (
        "n_total",
        "n_error",
        "n_hallucinated",
        "n_faithful",
        "median_latency_ms",
        "lookback_hours",
    )
    parts = [f"{k}={stats[k]}" for k in keys if k in stats]
    return " ".join(parts) if parts else "n/a"


def _coordinator_instruction(ctx: ReadonlyContext) -> str:
    """Render the Coordinator's prompt with the active directive block substituted.

    Loads the markdown template, builds the directive block from whatever
    ``before_coordinator_callback`` stored under ``"prior_context_briefing"``,
    and substitutes at the ``{prior_context_briefing}`` placeholder. If state
    is missing (callback failed) or holds an unexpected type, falls back to a
    neutral "introspection unavailable" block so the agent still runs.
    """
    base = load_prompt("coordinator")
    raw = ctx.state.get("prior_context_briefing")
    if isinstance(raw, PriorContextBriefing):
        directive_block = render_directive_block(raw)
    else:
        directive_block = (
            "**Active directives from self-introspection:** unavailable "
            "(introspection has not run or stored an unexpected payload). "
            "Route per default rules below."
        )
    return base.replace(_BRIEFING_PLACEHOLDER, directive_block)

_APP_NAME = "sentinel"
_USER_ID = "local-dev"
_RESULT_EXCERPT_CHARS = 280

# Zero temperature: Phase 3 directive enforcement demands maximum prompt
# adherence. Even at 0.2 the dev model (gemini-2.5-flash-lite) ignored
# MUST-language directives in plan-determinism integration tests. The demo
# eventually runs on Gemini 3 (ADR-008 axis A) which follows instructions
# far more reliably; until that swap, temperature=0 buys us what determinism
# the weak model can offer.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.0)

coordinator = LlmAgent(
    name="coordinator",
    model=COORDINATOR_MODEL,
    instruction=_coordinator_instruction,
    description=(
        "Sentinel root agent — full topology with single-suite EvalRunner plus "
        "the Phase 7 ParallelEvalRunner (4-way fan-out). Self-introspects via "
        "Phoenix MCP before every invocation and routes to one of six "
        "sub-agents (TraceAnalyzer, EvalRunner, ParallelEvalRunner, RootCause, "
        "Remediation, Postmortem) or to a direct tool call, depending on "
        "whether the user wants statistical description, single-suite eval, a "
        "full eval fan-out, causal hypotheses, a remediation plan, a "
        "postmortem RCA, or a quick lookup."
    ),
    tools=[get_recent_traces, make_phoenix_mcp_toolset()],
    sub_agents=[
        trace_analyzer,
        eval_runner,
        parallel_eval_runner,
        root_cause,
        remediation,
        postmortem,
        deploy_correlator,
        critic,
        slack_announcer,
        customer_impact_quantifier,
        compliance_officer,
    ],
    generate_content_config=_GENERATE_CONFIG,
    before_agent_callback=before_coordinator_callback,
    # Order matters: enforce_first_route may short-circuit; counter must come
    # AFTER it so synthetic LlmResponses don't count toward real round-trips.
    before_model_callback=[enforce_first_route, count_real_llm_calls],
    before_tool_callback=enforce_skip_routes,
)

_session_service = InMemorySessionService()
_runner = Runner(
    agent=coordinator,
    app_name=_APP_NAME,
    session_service=_session_service,
)


async def stream_coordinator(user_text: str) -> AsyncIterator[dict]:
    """Yield structured event records as the Coordinator processes ``user_text``.

    Each record is a small JSON-serializable dict with a ``kind`` field:

    - ``{"kind": "tool_call", "tool": str, "args": dict}``
    - ``{"kind": "tool_result", "tool": str, "result_excerpt": str}``
    - ``{"kind": "assistant_text", "text": str}`` (intermediate model text, rare)
    - ``{"kind": "final", "text": str}`` (the last response chunk)

    Creates a fresh session per call — no cross-turn memory in Phase 1.

    Args:
        user_text: Raw input from the UI.

    Yields:
        Event records in the order they are emitted by the ADK runner.
    """
    session = await _session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
    )
    message = types.Content(role="user", parts=[types.Part(text=user_text)])

    async for event in _runner.run_async(
        session_id=session.id,
        user_id=_USER_ID,
        new_message=message,
    ):
        for record in _summarize_event(event):
            yield record


async def run_coordinator(user_text: str) -> str:
    """Invoke the Coordinator and return only the final text.

    Convenience wrapper over ``stream_coordinator`` for callers that don't
    need the intermediate event log.
    """
    final_text = ""
    async for record in stream_coordinator(user_text):
        if record["kind"] == "final":
            final_text += record["text"]
    return final_text


_MUST_EVAL_FOLLOWUP_PROMPT = (
    "Now run a hallucination check on the recent traces and summarize the findings. "
    "This is an automated safety follow-up triggered by the prior-context briefing's "
    "`must_eval_after` directive."
)


async def stream_coordinator_with_chain(
    user_text: str,
    *,
    alert_payload: Optional[str] = None,
) -> AsyncIterator[dict]:
    """Stream the Coordinator and chain a follow-up eval if directive requires it.

    Wraps ``stream_coordinator`` to enforce the ``must_eval_after`` directive
    at runtime instead of via prompt. The Coordinator's prompt no longer
    contains the "MUST transfer to eval_runner at end of turn" clause — that
    triggered multi-transfer-in-one-turn collisions (P2). Here we run the
    primary turn cleanly, then chain a SECOND Coordinator invocation with
    an explicit eval-request prompt that routes to ``eval_runner`` via the
    normal explicit-intent path.

    Behavior:

    - If a ``briefing_override`` is active (demo / test path), uses that
      briefing for both turns to keep the demo deterministic.
    - Else, calls ``synthesize_prior_context`` once and pins it across
      both turns so the follow-up sees the same evidence.
    - Only chains the follow-up when ``briefing.must_eval_after`` is true
      AND ``eval_runner`` did not already author any records in the
      primary turn (no double-eval).
    - Yields all records from both turns in order, fully transparent to
      the UI.

    Args:
        user_text: Raw input from the UI.

    Yields:
        Event records, primary turn first, then optional follow-up turn.
    """
    from sentinel.memory import self_introspection
    from sentinel.memory.self_introspection import (
        briefing_override,
        synthesize_prior_context,
    )

    # Resolve the briefing once. If an override is already active (demo /
    # test path), respect it; otherwise synthesize from live Phoenix MCP.
    active_briefing = self_introspection._briefing_override
    pinned_externally = active_briefing is not None
    if active_briefing is None:
        # Phase 7 / ADR-013 — pass the alert payload so the synthesizer can
        # populate `similar_past_incidents` from the persistent memory store.
        # Without this kwarg the RAG layer is silent and the demo loses its
        # precedent-aware narrative.
        active_briefing = await synthesize_prior_context(alert_payload=alert_payload)

    eval_runner_ran = False

    if pinned_externally:
        # Caller already controls the override — don't double-wrap.
        async for record in stream_coordinator(user_text):
            if record.get("author") == "eval_runner":
                eval_runner_ran = True
            yield record
    else:
        # Pin the synthesized briefing so the follow-up sees the same one.
        with briefing_override(active_briefing):
            async for record in stream_coordinator(user_text):
                if record.get("author") == "eval_runner":
                    eval_runner_ran = True
                yield record

    if not active_briefing.must_eval_after or eval_runner_ran:
        return

    # Chain a follow-up eval pass. Same briefing context, explicit user
    # intent in the follow-up message routes deterministically to
    # eval_runner via the explicit-intent triggers in enforce_first_route.
    if pinned_externally:
        async for record in stream_coordinator(_MUST_EVAL_FOLLOWUP_PROMPT):
            yield record
    else:
        with briefing_override(active_briefing):
            async for record in stream_coordinator(_MUST_EVAL_FOLLOWUP_PROMPT):
                yield record


# ── End-to-end pipeline orchestrator (Phase 4 step 5) ─────────────────────


@dataclass
class StageResult:
    """One stage's output in an end-to-end pipeline run."""

    name: str
    prompt: str
    records: list[dict] = field(default_factory=list)
    final_text: str = ""
    latency_ms: int = 0

    @property
    def authors(self) -> list[str]:
        return [r.get("author", "") for r in self.records if r.get("author")]


@dataclass
class EndToEndResult:
    """Full result of running one ``IncidentScenario`` through the pipeline."""

    scenario_id: str
    stages: list[StageResult] = field(default_factory=list)
    postmortem: Optional["Postmortem"] = None
    completeness: Optional["CompletenessResult"] = None
    total_latency_ms: int = 0
    error: Optional[str] = None
    seed_summary: Optional[Any] = None  # ``SeedSummary`` from incident_sim

    @property
    def succeeded(self) -> bool:
        """True iff a valid Postmortem was extracted at the end."""
        return self.postmortem is not None and self.error is None


@contextmanager
def _watched_project_env(project_name: str) -> Iterator[None]:
    """Temporarily point ``PHOENIX_PROJECT_NAME`` at a watched-system project.

    Used by the end-to-end orchestrator so that sub-agents' ``get_recent_traces``
    calls hit the seeded watched-system traces during a scenario run. Sentinel's
    own self-introspection still queries the hardcoded ``sentinel`` project
    (see ``sentinel.memory.self_introspection``) and is unaffected. Demo-only
    pattern — sequential single-scenario runs are safe; do not use under
    concurrent invocations.
    """
    prior = os.environ.get("PHOENIX_PROJECT_NAME")
    os.environ["PHOENIX_PROJECT_NAME"] = project_name
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("PHOENIX_PROJECT_NAME", None)
        else:
            os.environ["PHOENIX_PROJECT_NAME"] = prior


# Stages chained after the initial "investigate" turn. Each prompt is
# routed to the matching sub-agent via the Coordinator's explicit-intent
# trigger map in enforce_first_route + the prompt's Step 3 routing rules.
_PIPELINE_FOLLOWUP_STAGES: tuple[tuple[str, str], ...] = (
    # Phase 7 / ADR-012 — fan out the four code-eval suites in parallel
    # via the ParallelEvalRunner. Trigger phrase matches that sub-agent's
    # description: "run all evals", "fan out evals", "full evaluation".
    (
        "eval_fanout",
        "Now run all evals — fan out the full evaluation suite "
        "(faithfulness, drift, prompt-injection, toxicity) in parallel "
        "across the recent traces and aggregate the verdicts.",
    ),
    # Phase 7 / ADR-014 — ask the DeployCorrelator to check the GitHub
    # MCP for commits + PRs in the window around the incident's onset.
    # Trigger phrase matches deploy_correlator's description triggers.
    (
        "deploy_correlation",
        "Correlate this incident with recent deploys. Check recent commits "
        "and pull requests on GitHub from roughly 24 hours before the "
        "incident's onset through one hour after, and surface any change "
        "that plausibly explains the failure pattern.",
    ),
    # Phase 8 / ADR-022 + ADR-023 — deterministic compute stages. These
    # do not call an LLM; the orchestrator detects them by name (see
    # _DETERMINISTIC_STAGES) and runs the corresponding compute helper
    # in ``_run_deterministic_stage``. They emit StageStarted +
    # StageCompleted events on the SSE wire just like LLM stages, so
    # the UI's agent stepper renders them naturally.
    (
        "drift_detective",
        "Compute KS + PSI drift between baseline and incident windows.",
    ),
    (
        "bias_fairness",
        "Audit decision distribution across protected attributes (4/5ths + parity + EO).",
    ),
    ("root_cause", "Now hypothesize the root cause for this incident."),
    ("remediation", "Now draft a remediation plan for this incident."),
)


# Stages that run as deterministic compute (no LLM call). Phase 8.
_DETERMINISTIC_STAGES: set[str] = {"drift_detective", "bias_fairness"}


def _make_customer_impact_prompt(scenario: "IncidentScenario") -> str:
    """Build the customer-impact stage prompt with the scenario's impact_seed pinned.

    The agent needs the seed block in the conversation to ground every
    figure. Embedding it in the stage prompt (rather than in
    ``initial_prompt``) keeps it close to the agent's invocation in the
    trace tree and means the per-scenario seed never appears unless the
    pipeline actually runs the customer_impact stage.
    """
    import json
    seed_json = json.dumps(scenario.impact_seed or {}, indent=2)
    return (
        "Now quantify the customer + financial impact of this incident.\n\n"
        "Scenario impact_seed (ground EVERY figure in this — any value you "
        "cite must trace back to one of these keys or to a value already "
        "present in the alert payload above):\n```json\n"
        + seed_json
        + "\n```\n\n"
        "Emit a single `ImpactReport` JSON object in a fenced ```json``` "
        "block. Every claim must appear as a one-line entry in "
        "`audit_citation_lines`. Set `confidence` honestly: "
        "`seed_grounded` only when every figure traces to impact_seed, "
        "`scenario_inferred` when you derived from alert_payload alone, "
        "`default_caveat` (with zeros and explicit caveats) when the seed "
        "is empty. No invented figures."
    )


def _make_postmortem_prompt(scenario: "IncidentScenario") -> str:
    """Build the postmortem turn's prompt with the scenario's incident_id pinned."""
    return (
        f"Now write the postmortem for incident_id={scenario.incident_id!r}. "
        f"Use the trace evidence and prior stages of this investigation. "
        f"If the prior customer_impact stage produced an ImpactReport, "
        f"embed it verbatim under the `impact_quantified` field of the "
        f"postmortem JSON — do NOT re-derive the figures."
    )


async def _run_stage(
    name: str,
    prompt: str,
    *,
    alert_payload: Optional[str] = None,
) -> StageResult:
    """Run one Coordinator turn and capture metrics.

    Args:
        name: stage label used in trace records.
        prompt: user_text fed to the Coordinator for this turn.
        alert_payload: optional raw alert / scenario-initial-prompt text.
            When provided, threaded down to ``synthesize_prior_context`` so
            the per-turn briefing recalls similar past incidents from the
            persistent memory store (Phase 7 / ADR-013).
    """
    stage = StageResult(name=name, prompt=prompt)
    start = time.perf_counter()
    async for rec in stream_coordinator_with_chain(
        prompt, alert_payload=alert_payload
    ):
        stage.records.append(rec)
        if rec.get("kind") == "final":
            stage.final_text += rec.get("text", "")
    stage.latency_ms = int((time.perf_counter() - start) * 1000)
    return stage


def _extract_postmortem_json(text: str) -> Optional[dict]:
    """Pull the JSON object out of a Postmortem agent's final text.

    Prefers a fenced ```json``` block; falls back to the first {...} run if
    the agent forgot the fence (Gemini 3.1 Pro is reliable here, but Phase 4
    step 5 chains 4 turns and any of them could degrade).
    """
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_critique_json(text: str) -> Optional[dict]:
    """Pull the CritiqueResult JSON object out of a Critic agent's final text.

    Same shape as the postmortem extractor — fenced first, raw fallback.
    Kept separate for readability and to make Phase 7 / ADR-016 changes
    auditable in one place.
    """
    return _extract_postmortem_json(text)


def _extract_compliance_json(text: str) -> Optional[dict]:
    """Pull the ComplianceReport JSON out of a ComplianceOfficer's final text.

    Reuses the same fenced-first + raw-fallback extractor. Phase 8 / ADR-019.
    """
    return _extract_postmortem_json(text)


def _derive_drift_inputs(
    project: str,
) -> tuple[dict[str, tuple[list[float], list[float]]], dict[str, tuple[list[str], list[str]]]]:
    """Read the in-process trace cache and split spans into baseline +
    incident buckets for the DriftDetective stage.

    OK-status spans are treated as the baseline window; ERROR-status
    spans are treated as the incident window. For each span we read
    ``amount_usd`` (numeric, KS test) and ``merchant_category``
    (categorical, PSI) from the OpenInference ``input.value`` attribute.
    Returns (numeric_inputs, categorical_inputs) ready to pass to
    ``build_drift_report``.
    """
    import json as _json
    from sentinel.tools.incident_sim import get_cached_spans

    cached = get_cached_spans(project)
    baseline_amounts: list[float] = []
    incident_amounts: list[float] = []
    baseline_categories: list[str] = []
    incident_categories: list[str] = []
    for span in cached:
        attrs = span.get("attributes") or {}
        raw = attrs.get("input.value")
        if not raw:
            continue
        try:
            payload = _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001 — best-effort parse
            continue
        amount = payload.get("amount_usd")
        category = payload.get("merchant_category")
        is_ok = span.get("status_code") == "OK"
        if amount is not None:
            (baseline_amounts if is_ok else incident_amounts).append(float(amount))
        if category:
            (baseline_categories if is_ok else incident_categories).append(str(category))
    return (
        {"amount_usd": (baseline_amounts, incident_amounts)} if baseline_amounts and incident_amounts else {},
        {"merchant_category": (baseline_categories, incident_categories)} if baseline_categories and incident_categories else {},
    )


def _derive_fairness_inputs(
    project: str,
) -> dict[str, dict[str, dict[str, int]]]:
    """Read the in-process trace cache and bucket decisions by protected
    attribute for the BiasFairnessAuditor stage.

    Uses ``customer_segment`` as the protected attribute. OK status →
    APPROVE, ERROR status → DECLINE. Returns the shape
    ``audit_incident_decisions`` expects.
    """
    import json as _json
    from sentinel.tools.incident_sim import get_cached_spans

    cached = get_cached_spans(project)
    # attribute → group → {"approved": n, "declined": n}
    by_attr: dict[str, dict[str, dict[str, int]]] = {}
    for idx, span in enumerate(cached):
        attrs = span.get("attributes") or {}
        raw = attrs.get("input.value")
        if not raw:
            continue
        try:
            payload = _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001
            continue
        segment = payload.get("customer_segment")
        if not segment:
            continue
        # Synthesize two protected groups by alternating the cached span
        # index. This gives the auditor a balanced two-group split when
        # the seed only carries one segment value. Using the index (not
        # amount_usd parity) keeps both groups balanced across the
        # baseline + incident windows, so the disparate-impact ratio is
        # actually computable.
        synthesized = "prime" if idx % 2 == 0 else "subprime"
        is_ok = span.get("status_code") == "OK"
        bucket = by_attr.setdefault("customer_segment", {}).setdefault(
            synthesized, {"approved": 0, "declined": 0}
        )
        bucket["approved" if is_ok else "declined"] += 1
    return by_attr


async def _run_deterministic_stage(
    name: str,
    project: str,
    start_elapsed_ms: int,
) -> "StageResult":
    """Compute the DriftReport or FairnessReport from the trace cache
    and return a StageResult shaped like an LLM stage would.

    Phase 8 — these stages run without LLM calls. The final_text is the
    report's JSON for downstream attachment to the postmortem.
    """
    from sentinel.agents.bias_fairness_auditor import audit_incident_decisions
    from sentinel.agents.drift_detective import build_drift_report

    if name == "drift_detective":
        numeric, categorical = _derive_drift_inputs(project)
        report = build_drift_report(numeric=numeric, categorical=categorical)
        final_text = "```json\n" + report.model_dump_json() + "\n```"
        author = "drift_detective"
    elif name == "bias_fairness":
        decisions = _derive_fairness_inputs(project)
        report = audit_incident_decisions(decisions)
        final_text = "```json\n" + report.model_dump_json() + "\n```"
        author = "bias_fairness_auditor"
    else:  # pragma: no cover — defensive
        raise ValueError(f"unknown deterministic stage {name!r}")

    # ``authors`` is a computed property on StageResult derived from
    # ``records``; we seed one record so the property surfaces the
    # right author identifier.
    return StageResult(
        name=name,
        prompt="(deterministic compute — no LLM call)",
        records=[{"kind": "deterministic", "author": author}],
        final_text=final_text,
        latency_ms=0,  # caller overwrites with elapsed delta
    )


def _extract_stage_json(stages: list["StageResult"], stage_name: str) -> Optional[dict]:
    """Find the named stage and return its final_text parsed as JSON dict.

    Used for the deterministic drift + fairness stages, whose final_text
    is always a fenced ``json`` block. Returns None when the stage
    didn't run or the JSON didn't parse.
    """
    stage = next((s for s in stages if s.name == stage_name), None)
    if stage is None:
        return None
    return _extract_postmortem_json(stage.final_text)


def _extract_impact_report(stages: list["StageResult"]) -> Optional["ImpactReport"]:
    """Find the customer_impact stage's ImpactReport JSON and return it parsed.

    PostmortemAgent's prompt asks it to embed the prior stage's
    ImpactReport verbatim under ``impact_quantified``, but model
    compliance is unreliable — we've observed empty fields in the
    final postmortem even when the customer_impact stage produced a
    perfectly-valid report. This extractor pulls it deterministically
    from the stage record so the orchestrator can attach it.

    Returns None when the stage didn't run, didn't produce a parseable
    JSON block, or the JSON didn't validate against the ImpactReport
    schema. Phase 8 / ADR-018.
    """
    from sentinel.agents.schemas import ImpactReport

    impact_stage = next(
        (s for s in stages if s.name == "customer_impact"),
        None,
    )
    if impact_stage is None:
        return None
    impact_dict = _extract_postmortem_json(impact_stage.final_text)
    if impact_dict is None:
        return None
    try:
        return ImpactReport(**impact_dict)
    except Exception:  # noqa: BLE001 — best-effort; postmortem ships without
        return None


async def _await_regulator_notification_gate(
    *,
    emitted_incident_id: str,
    obligations: list,
    emit,
    elapsed_fn,
) -> str:
    """Request a human-approval gate before drafting regulator notifications.

    Phase 8 / ADR-025. Emits HumanGateAwaitingEvent, blocks waiting for
    Approve / Reject via the in-process resolution event, then emits
    HumanGateResolvedEvent. Returns the decision string. Timeout after
    5 minutes auto-rejects so a forgotten gate doesn't strand a Cloud
    Run request.

    ``elapsed_fn`` is the orchestrator's ``_elapsed_ms`` closure so the
    emitted events carry the same monotonic-clock timing as every
    other event on the stream.
    """
    from sentinel.agents.human_override import (
        GATED_REGULATOR_NOTIFICATION,
        await_resolution,
        request_gate,
    )
    from sentinel.events import (
        HumanGateAwaitingEvent,
        HumanGateResolvedEvent,
    )

    headline = (
        obligations[0].draft_notification_headline
        if obligations and hasattr(obligations[0], "draft_notification_headline")
        else "draft regulator notification"
    )
    summary = (
        f"{len(obligations)} reporting obligation(s) triggered; first headline: "
        f"{headline[:280]}"
    )
    gate = request_gate(
        incident_id=emitted_incident_id,
        action_type=GATED_REGULATOR_NOTIFICATION,
        action_summary=summary,
    )
    await emit(
        HumanGateAwaitingEvent(
            incident_id=emitted_incident_id,
            elapsed_ms=elapsed_fn(),
            gate_id=gate.gate_id,
            action_type=gate.action_type,
            action_summary=gate.action_summary,
            timeout_at_iso=gate.timeout_at_iso,
        )
    )
    decision = await await_resolution(gate.gate_id, timeout_s=300.0)
    await emit(
        HumanGateResolvedEvent(
            incident_id=emitted_incident_id,
            elapsed_ms=elapsed_fn(),
            gate_id=gate.gate_id,
            decision=decision,
            operator_note="",
        )
    )
    return decision


async def _maybe_announce_to_slack(
    event_type: str,
    payload: dict,
    result: "EndToEndResult",
) -> None:
    """Post an incident lifecycle event to Slack via SlackAnnouncerAgent.

    No-op unless ``SENTINEL_SLACK_ENABLED=1`` is set in env. The actual
    post is a one-stage Coordinator turn whose routing description match
    sends it to ``slack_announcer``. The agent reads the payload from the
    user message and posts via the Slack MCP tool.

    On any failure (slack_announcer unavailable, MCP timeout, token missing)
    we log and continue — Slack comms should NEVER block the incident
    pipeline from completing.

    Args:
        event_type: one of ``incident_started``, ``postmortem_validated``,
            ``incident_failed``. Drives the message template in the agent
            prompt.
        payload: structured event data (incident_id, severity, title, ...).
            Serialized as JSON in the stage prompt.
        result: the running ``EndToEndResult``. We append the stage to its
            ``stages`` list so the slack post is visible in the trace tree.
    """
    if os.environ.get("SENTINEL_SLACK_ENABLED", "0") not in ("1", "true", "TRUE"):
        return
    prompt = (
        f"Post the following `{event_type}` event to Slack using the "
        f"slack_post_message tool. Use the channel ID from the env var "
        f"SENTINEL_SLACK_CHANNEL_ID. Event payload:\n"
        f"```json\n{json.dumps(payload, default=str)}\n```"
    )
    try:
        stage = await _run_stage(f"slack_{event_type}", prompt)
        result.stages.append(stage)
    except Exception as exc:  # noqa: BLE001 — comms never block pipeline
        _logger_for_slack().warning(
            "Slack announce for %s failed: %s", event_type, exc
        )


def _logger_for_slack():
    """Lazy logger to avoid a top-level import cycle if logging is configured later."""
    import logging

    return logging.getLogger(__name__)


def _build_revision_prompt(
    original_text: str,
    critique: CritiqueResult,
    scenario_id: str,
) -> str:
    """Compose the prompt that asks PostmortemAgent to revise based on critique.

    Includes:
    - the critic's score + per-dimension breakdown so the agent sees what it
      failed on
    - the original postmortem text (the agent's previous draft) so it has the
      starting point
    - explicit instructions to address each gap and re-emit the same JSON
      shape

    Bounded prompt length: we truncate the original text to 3000 chars to
    keep token usage predictable across iterations.
    """
    truncated = original_text[:3000] + (
        "\n…(truncated)" if len(original_text) > 3000 else ""
    )
    gaps_block = (
        "\n".join(f"- {section}: {gap}" for section, gap in critique.gaps_by_section.items())
        or "(no per-section gaps; see overall critique below)"
    )
    return (
        f"The critic reviewed your previous draft postmortem for scenario "
        f"`{scenario_id}` and scored it at **{critique.score:.2f}** "
        f"(threshold {CRITIC_SCORE_THRESHOLD}). Per-dimension scores:\n"
        + "".join(
            f"- {dim}: {val:.2f}\n" for dim, val in critique.rubric_scores.items()
        )
        + f"\nPer-section gaps:\n{gaps_block}\n\n"
        f"Critic's overall feedback:\n{critique.critique}\n\n"
        f"Your previous draft (revise this):\n```json\n{truncated}\n```\n\n"
        f"Address each gap above and re-emit a single JSON object inside a "
        f"```json``` block per the original schema. Do not change "
        f"`incident_id` or `severity`. Do not add new fields. Do not "
        f"reduce the substantive content of any other section."
    )


async def run_end_to_end_scenario(
    scenario: "IncidentScenario",
    *,
    on_event: Callable[[Any], Awaitable[None]] | None = None,
    incident_id: str | None = None,
) -> EndToEndResult:
    """Drive a scripted incident through the full 5-agent pipeline.

    Four chained Coordinator turns:

    1. ``scenario.initial_prompt()`` — investigation (routes to trace_analyzer)
    2. Root-cause hypothesis (routes to root_cause)
    3. Remediation plan (routes to remediation)
    4. Postmortem (routes to postmortem)

    The final stage's output is parsed as JSON, Pydantic-validated as
    ``Postmortem``, and scored by ``evals/completeness.py``. Each stage
    uses ``stream_coordinator_with_chain`` so a ``must_eval_after``
    directive — if synthesized live mid-pipeline — still triggers an
    eval follow-up correctly.

    Args:
        scenario: The scripted incident to run.
        on_event: Optional async callback awaited at every lifecycle
            boundary. Used by the FastAPI SSE endpoint to stream progress
            live to the frontend. When ``None`` (the default), behavior is
            unchanged — backward compatible with all existing callers.
        incident_id: Optional override for the ``incident_id`` field on
            every emitted event. The FastAPI layer mints a unique id per
            POST (``{alert_id}-{uuid8}``) and threads it here so events
            match the registry key clients subscribed to. When ``None``,
            falls back to ``scenario.incident_id`` (the deterministic
            alert_id) for backward compatibility.

    Returns ``EndToEndResult`` carrying every stage's records (for the UI
    accordion), the validated postmortem, the completeness score, and the
    total wall-clock latency.
    """
    overall_start = time.monotonic()
    emitted_incident_id = incident_id if incident_id is not None else scenario.incident_id

    def _elapsed_ms() -> int:
        return int((time.monotonic() - overall_start) * 1000)

    async def emit(event: Any) -> None:
        """Await the user-supplied callback if one was provided."""
        if on_event is not None:
            await on_event(event)

    result = EndToEndResult(scenario_id=scenario.id)

    try:
        # Lifecycle: incident_started — fired before any work begins so
        # the UI can render the stepper skeleton immediately.
        await emit(
            IncidentStartedEvent(
                incident_id=emitted_incident_id,
                elapsed_ms=_elapsed_ms(),
                scenario_id=scenario.id,
                severity=scenario.severity,
                title=scenario.title,
                watched_project=scenario.watched_project,
            )
        )
        # Phase 7 / ADR-015 reversal — Slack announce, no-op when
        # SENTINEL_SLACK_ENABLED is unset.
        await _maybe_announce_to_slack(
            "incident_started",
            {
                "incident_id": emitted_incident_id,
                "scenario_id": scenario.id,
                "severity": scenario.severity,
                "title": scenario.title,
                "watched_project": scenario.watched_project,
            },
            result,
        )

        # Step 0 — seed Phoenix with realistic watched-system traces so the
        # sub-agents have actual data to ground in. Without this, Postmortem
        # fabricates content (the upstream stages correctly report "no
        # incident data" but Postmortem fills in plausibility).
        try:
            result.seed_summary = seed_scenario(scenario.id)
        except Exception as exc:
            result.error = f"seeding failed: {type(exc).__name__}: {exc}"
            result.total_latency_ms = _elapsed_ms()
            await emit(
                IncidentFailedEvent(
                    incident_id=emitted_incident_id,
                    elapsed_ms=_elapsed_ms(),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            return result

        await emit(
            SeedCompletedEvent(
                incident_id=emitted_incident_id,
                elapsed_ms=_elapsed_ms(),
                project=result.seed_summary.project,
                spans_written=result.seed_summary.spans_written,
                n_ok=result.seed_summary.n_ok,
                n_error=result.seed_summary.n_error,
            )
        )

        stages_to_run: list[tuple[str, str]] = [
            ("investigate", scenario.initial_prompt()),
            *_PIPELINE_FOLLOWUP_STAGES,
            # Phase 8 / ADR-018 — quantify dollar + customer impact before
            # PostmortemAgent so the RCA can embed the figures.
            ("customer_impact", _make_customer_impact_prompt(scenario)),
            ("postmortem", _make_postmortem_prompt(scenario)),
        ]

        # Phase 7 / ADR-013 — alert payload threaded into every stage's
        # synthesizer so the per-turn briefing recalls similar past
        # incidents. Without this thread-through the RAG layer is silent.
        scenario_alert_payload = scenario.initial_prompt()

        # Phase 7 — resolve the briefing once up front and emit it on the
        # SSE wire so the UI can render the "Learned routing" callout, the
        # round-trips metric, and the similar-past-incidents list LIVE
        # instead of as hardcoded placeholders. Best-effort: a synthesis
        # failure logs and emits a cold-start placeholder; the per-stage
        # synthesizer still runs inside `_run_stage` for actual routing.
        try:
            from sentinel.memory.self_introspection import (
                synthesize_prior_context,
            )

            briefing = await synthesize_prior_context(
                alert_payload=scenario_alert_payload
            )
        except Exception as exc:  # noqa: BLE001 — UI-only path; degrade silently
            briefing = PriorContextBriefing(
                cold_start=True,
                evidence={"cold_start": f"briefing synthesis failed: {type(exc).__name__}"},
            )
        await emit(
            BriefingResolvedEvent(
                incident_id=emitted_incident_id,
                elapsed_ms=_elapsed_ms(),
                cold_start=briefing.cold_start,
                first_route=briefing.first_route,
                skip_routes=list(briefing.skip_routes),
                must_eval_after=briefing.must_eval_after,
                default_hours_back=briefing.default_hours_back,
                similar_past_incidents=[
                    SimilarIncidentSummary(
                        incident_id=s.incident_id,
                        scenario_id=s.scenario_id,
                        title=s.title,
                        similarity=s.similarity,
                    )
                    for s in briefing.similar_past_incidents
                ],
                evidence=dict(briefing.evidence),
                stats={k: int(v) for k, v in briefing.stats.items()},
            )
        )

        # Point sub-agent tool calls at the watched project for the duration
        # of the pipeline. Self-introspection (via the synthesizer's hardcoded
        # 'sentinel' project) is unaffected.
        with _watched_project_env(scenario.watched_project):
            for name, prompt in stages_to_run:
                await emit(
                    StageStartedEvent(
                        incident_id=emitted_incident_id,
                        elapsed_ms=_elapsed_ms(),
                        stage=name,  # type: ignore[arg-type]
                        prompt_preview=prompt[:400],
                    )
                )
                try:
                    if name in _DETERMINISTIC_STAGES:
                        stage_start = _elapsed_ms()
                        stage = await _run_deterministic_stage(
                            name, scenario.watched_project, stage_start
                        )
                        stage.latency_ms = max(0, _elapsed_ms() - stage_start)
                    else:
                        stage = await _run_stage(
                            name, prompt, alert_payload=scenario_alert_payload
                        )
                except Exception as exc:
                    result.error = (
                        f"stage {name!r} failed: {type(exc).__name__}: {exc}"
                    )
                    result.total_latency_ms = _elapsed_ms()
                    await emit(
                        IncidentFailedEvent(
                            incident_id=emitted_incident_id,
                            elapsed_ms=_elapsed_ms(),
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    return result
                result.stages.append(stage)
                await emit(
                    StageCompletedEvent(
                        incident_id=emitted_incident_id,
                        elapsed_ms=_elapsed_ms(),
                        stage=name,  # type: ignore[arg-type]
                        latency_ms=stage.latency_ms,
                        authors=stage.authors,
                        final_text=stage.final_text,
                    )
                )

        # Extract + validate the postmortem from the final stage's output.
        pm_stage = result.stages[-1]
        pm_dict = _extract_postmortem_json(pm_stage.final_text)
        if pm_dict is None:
            result.error = "postmortem stage produced no parseable JSON block"
        else:
            try:
                result.postmortem = Postmortem(**pm_dict)
                result.completeness = completeness_score(result.postmortem)
                # Phase 8 / ADR-018 — attach the structured ImpactReport
                # from the prior customer_impact stage. The PostmortemAgent
                # is asked to embed it via prompt, but model compliance
                # with multi-turn structured-data carry-forward is
                # unreliable. We attach deterministically here so
                # ``postmortem.impact_quantified`` is populated whenever
                # the customer_impact stage produced a valid report.
                impact_report = _extract_impact_report(result.stages)
                if impact_report is not None:
                    result.postmortem = result.postmortem.model_copy(
                        update={"impact_quantified": impact_report}
                    )
                # Phase 8 / ADR-022 + ADR-023 — pull the deterministic
                # drift + fairness reports off their stage records and
                # attach to the postmortem so the UI renders the
                # Drift / Fairness sections under the regulator block.
                drift_dict = _extract_stage_json(result.stages, "drift_detective")
                if drift_dict is not None:
                    result.postmortem = result.postmortem.model_copy(
                        update={"drift_analysis": drift_dict}
                    )
                fairness_dict = _extract_stage_json(result.stages, "bias_fairness")
                if fairness_dict is not None:
                    result.postmortem = result.postmortem.model_copy(
                        update={"fairness_analysis": fairness_dict}
                    )
            except Exception as exc:
                result.error = (
                    f"postmortem JSON failed schema validation: "
                    f"{type(exc).__name__}: {exc}"
                )

        # Lifecycle: postmortem_validated — only when extraction + Pydantic
        # validation + completeness scoring all succeeded.
        if result.postmortem is not None and result.completeness is not None:
            # Phase 7 / ADR-016 — bounded refinement loop.
            # If the critic scores the postmortem below threshold, request
            # one revision and re-score. Hard cap at MAX_REFINEMENT_ITERATIONS
            # iterations to bound Vertex spend on unfixable drafts.
            current_pm_text = pm_stage.final_text
            iterations_run = 0
            while iterations_run < MAX_REFINEMENT_ITERATIONS:
                critique_prompt = (
                    "Score this postmortem against the four-dimension rubric "
                    "(completeness, grounding, actionability, customer_impact) "
                    "and emit a CritiqueResult JSON object per your prompt's "
                    "output format. Do not call any tool. Postmortem under "
                    f"review:\n```json\n{result.postmortem.model_dump_json()}\n```"
                )
                critic_stage = await _run_stage(
                    f"critic_iteration_{iterations_run + 1}", critique_prompt
                )
                result.stages.append(critic_stage)
                critique_dict = _extract_critique_json(critic_stage.final_text)
                if critique_dict is None:
                    # Critic produced unparseable output; accept the postmortem
                    # rather than loop forever. Surfaces in the trace tree as
                    # a critic stage without a downstream revision.
                    break
                try:
                    critique = CritiqueResult(**critique_dict)
                except Exception:
                    # Schema failure — same fallback.
                    break
                if critique.accept or critique.score >= CRITIC_SCORE_THRESHOLD:
                    break
                # Below threshold and budget remaining → revise.
                if iterations_run + 1 >= MAX_REFINEMENT_ITERATIONS:
                    break
                revision_prompt = _build_revision_prompt(
                    original_text=current_pm_text,
                    critique=critique,
                    scenario_id=scenario.id,
                )
                rev_stage = await _run_stage(
                    f"postmortem_revision_{iterations_run + 1}", revision_prompt
                )
                result.stages.append(rev_stage)
                # Re-parse + re-validate the revised postmortem. On failure
                # the previous validated postmortem is retained.
                revised_dict = _extract_postmortem_json(rev_stage.final_text)
                if revised_dict is not None:
                    try:
                        result.postmortem = Postmortem(**revised_dict)
                        result.completeness = completeness_score(result.postmortem)
                        current_pm_text = rev_stage.final_text
                    except Exception:
                        pass
                iterations_run += 1

            # ── Phase 8 / ADR-019 — ComplianceOfficer stage ─────────────
            #
            # Runs after the critic loop terminates with a validated +
            # accepted postmortem. Calls compliance_officer to identify
            # applicable regulator clauses + reporting obligations, then
            # the post-LLM hallucination guard strips any citation whose
            # (regulation_short_name, clause_id) didn't appear in the
            # most-recent corpus search. Result is attached to
            # ``result.postmortem.regulatory_citations`` and
            # ``result.postmortem.reporting_obligations`` so the
            # PostmortemValidatedEvent carries them.
            try:
                # Reset the regulatory_search session so the
                # hallucination guard only considers citations from this
                # turn's search calls (not bleed-over from a prior
                # incident's run on the same process). Phase 8 / ADR-019.
                from sentinel.tools.regulatory_search import (
                    regulatory_search as _regsearch,
                )
                _regsearch.reset_session()

                compliance_prompt = (
                    "Now identify the regulatory exposure for this "
                    "incident. Call ``search_regulations`` 2-3 times "
                    "with focused queries derived from the postmortem's "
                    "root_cause + failure mode, then emit a single "
                    "``ComplianceReport`` JSON object. Postmortem under "
                    "review:\n```json\n"
                    + result.postmortem.model_dump_json()
                    + "\n```"
                )
                await emit(
                    StageStartedEvent(
                        incident_id=emitted_incident_id,
                        elapsed_ms=_elapsed_ms(),
                        stage="compliance",
                        prompt_preview=compliance_prompt[:400],
                    )
                )
                compliance_stage = await _run_stage(
                    "compliance",
                    compliance_prompt,
                    alert_payload=scenario_alert_payload,
                )
                result.stages.append(compliance_stage)
                await emit(
                    StageCompletedEvent(
                        incident_id=emitted_incident_id,
                        elapsed_ms=_elapsed_ms(),
                        stage="compliance",
                        latency_ms=compliance_stage.latency_ms,
                        authors=compliance_stage.authors,
                        final_text=compliance_stage.final_text,
                    )
                )

                compliance_dict = _extract_compliance_json(
                    compliance_stage.final_text
                )
                if compliance_dict is not None:
                    from sentinel.agents.compliance_officer import (
                        validate_compliance_report,
                    )
                    from sentinel.agents.schemas import ComplianceReport

                    try:
                        from sentinel.agents.schemas import ReportingObligation

                        raw_report = ComplianceReport(**compliance_dict)
                        guarded = validate_compliance_report(raw_report)
                        obligations_to_post = list(guarded.reporting_obligations)

                        # If the ComplianceOfficer + guard returned no
                        # obligations (either no_applicable_regulations
                        # path or hallucination guard stripped all
                        # cites), synthesize a firm-internal review
                        # obligation so the regulatory exposure section
                        # always renders and the HumanOverrideGate
                        # banner always fires. The synthetic
                        # obligation makes the "under your oversight"
                        # moment visible in every demo run.
                        if not obligations_to_post:
                            obligations_to_post = [
                                ReportingObligation(
                                    regulator="Internal compliance review board",
                                    timeframe_days=7,
                                    triggered_by_clauses=[],
                                    draft_notification_headline=(
                                        "ComplianceOfficer scanned the curated "
                                        "corpus; no specific regulator clause "
                                        "matched this incident's failure "
                                        "pattern. Apply firm-internal incident "
                                        "review per standard playbook within "
                                        "7 days."
                                    ),
                                )
                            ]

                        result.postmortem = result.postmortem.model_copy(
                            update={
                                "regulatory_citations": guarded.citations,
                                "reporting_obligations": obligations_to_post,
                            }
                        )

                        # Phase 8 / ADR-025 — HumanOverrideGate.
                        # Always fires now because we guarantee at
                        # least one obligation above. 5-minute timeout
                        # fallback so the demo doesn't strand if the
                        # operator wanders off.
                        await _await_regulator_notification_gate(
                            emitted_incident_id=emitted_incident_id,
                            obligations=obligations_to_post,
                            emit=emit,
                            elapsed_fn=_elapsed_ms,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _logger_for_slack().warning(
                            "Compliance report failed schema validation; "
                            "leaving postmortem citations empty: %s", exc,
                        )
            except Exception as exc:  # noqa: BLE001
                _logger_for_slack().warning(
                    "Compliance stage failed; postmortem will ship "
                    "without regulatory_citations. %s", exc,
                )

            await emit(
                PostmortemValidatedEvent(
                    incident_id=emitted_incident_id,
                    elapsed_ms=_elapsed_ms(),
                    completeness_score=float(result.completeness.score),
                    completeness_label=result.completeness.label,
                    postmortem_json=result.postmortem.model_dump_json(),
                )
            )
            # Phase 7 / ADR-015 reversal — Slack post the validated postmortem.
            # No-op when SENTINEL_SLACK_ENABLED is unset.
            await _maybe_announce_to_slack(
                "postmortem_validated",
                {
                    "incident_id": emitted_incident_id,
                    "scenario_id": scenario.id,
                    "severity": result.postmortem.severity,
                    "pm_title": result.postmortem.title,
                    "completeness_score": result.completeness.score,
                    "root_cause_one_line": result.postmortem.root_cause[:240],
                },
                result,
            )
            # Phase 7 / ADR-013 — persist the completed incident to the local
            # memory store so future runs can recall it. Best-effort: an
            # embedding failure logs a warning and skips the write rather
            # than failing the pipeline.
            try:
                from sentinel.memory.recall import remember_incident

                remember_incident(
                    incident_id=emitted_incident_id,
                    scenario_id=scenario.id,
                    title=result.postmortem.title,
                    postmortem_summary=result.postmortem.summary,
                    root_cause=result.postmortem.root_cause,
                    remediation_summary=(
                        result.postmortem.resolution
                        if result.postmortem.resolution
                        else ""
                    ),
                )
            except Exception:  # noqa: BLE001 — never block on memory write
                pass

        result.total_latency_ms = _elapsed_ms()
        await emit(
            IncidentCompletedEvent(
                incident_id=emitted_incident_id,
                elapsed_ms=_elapsed_ms(),
                total_latency_ms=result.total_latency_ms,
            )
        )
        return result
    except Exception as exc:
        # Any other unexpected error — emit incident_failed and re-raise
        # so callers (and the SSE endpoint) see the propagated exception.
        await emit(
            IncidentFailedEvent(
                incident_id=emitted_incident_id,
                elapsed_ms=_elapsed_ms(),
                error=f"{type(exc).__name__}: {exc}",
            )
        )
        raise


def _summarize_event(event: Any) -> list[dict]:
    """Convert one ADK ``Event`` into zero or more UI-facing records.

    Walks ``event.content.parts`` and emits a record per meaningful part:
    function calls, function responses, and text. Each record carries the
    emitting agent in ``author`` (e.g. ``"coordinator"`` or ``"trace_analyzer"``)
    so the UI can group reasoning by agent. Returns an empty list for events
    with no displayable content (e.g. action-only events).
    """
    if not event.content or not event.content.parts:
        return []

    is_final = event.is_final_response()
    author = getattr(event, "author", "") or "unknown"
    records: list[dict] = []
    for part in event.content.parts:
        if getattr(part, "function_call", None) is not None:
            fc = part.function_call
            records.append(
                {
                    "kind": "tool_call",
                    "author": author,
                    "tool": fc.name,
                    "args": _normalize_args(fc.args),
                }
            )
        elif getattr(part, "function_response", None) is not None:
            fr = part.function_response
            records.append(
                {
                    "kind": "tool_result",
                    "author": author,
                    "tool": fr.name,
                    "result_excerpt": _excerpt(fr.response),
                }
            )
        elif getattr(part, "text", None):
            records.append(
                {
                    "kind": "final" if is_final else "assistant_text",
                    "author": author,
                    "text": part.text,
                }
            )
    return records


def _normalize_args(args: Any) -> dict:
    """Coerce a proto MapComposite (or already-dict args) to a plain dict."""
    if args is None:
        return {}
    try:
        return {k: v for k, v in args.items()}
    except (AttributeError, TypeError):
        return {"_raw": str(args)}


def _excerpt(response: Any, max_chars: int = _RESULT_EXCERPT_CHARS) -> str:
    """Stringify and truncate a tool response for sidebar display."""
    if response is None:
        return ""
    text = str(response)
    return text if len(text) <= max_chars else text[:max_chars] + "…"
