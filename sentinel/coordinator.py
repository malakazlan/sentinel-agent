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
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

if TYPE_CHECKING:
    from evals.completeness import CompletenessResult
    from sentinel.agents.schemas import Postmortem
    from sentinel.scenarios import IncidentScenario

from google.adk.agents.readonly_context import ReadonlyContext

from sentinel.agents.eval_runner import eval_runner
from sentinel.agents.postmortem import postmortem
from sentinel.agents.remediation import remediation
from sentinel.agents.root_cause import root_cause
from sentinel.agents.trace_analyzer import trace_analyzer
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
        "Sentinel root agent — full 5-agent topology. Self-introspects via "
        "Phoenix MCP before every invocation and routes to one of five "
        "sub-agents (TraceAnalyzer, EvalRunner, RootCause, Remediation, "
        "Postmortem) or to a direct tool call, depending on whether the user "
        "wants statistical description, quality evaluation, causal hypotheses, "
        "a remediation plan, a postmortem RCA, or a quick lookup."
    ),
    tools=[get_recent_traces, make_phoenix_mcp_toolset()],
    sub_agents=[trace_analyzer, eval_runner, root_cause, remediation, postmortem],
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
        active_briefing = await synthesize_prior_context()

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
    ("root_cause", "Now hypothesize the root cause for this incident."),
    ("remediation", "Now draft a remediation plan for this incident."),
)


def _make_postmortem_prompt(scenario: "IncidentScenario") -> str:
    """Build the postmortem turn's prompt with the scenario's incident_id pinned."""
    return (
        f"Now write the postmortem for incident_id={scenario.incident_id!r}. "
        f"Use the trace evidence and prior stages of this investigation."
    )


async def _run_stage(name: str, prompt: str) -> StageResult:
    """Run one Coordinator turn and capture metrics."""
    stage = StageResult(name=name, prompt=prompt)
    start = time.perf_counter()
    async for rec in stream_coordinator_with_chain(prompt):
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


async def run_end_to_end_scenario(
    scenario: "IncidentScenario",
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

    Returns ``EndToEndResult`` carrying every stage's records (for the UI
    accordion), the validated postmortem, the completeness score, and the
    total wall-clock latency.
    """
    # Lazy imports avoid a circular dependency: schemas live in
    # sentinel.agents, which transitively imports parts of memory which
    # imports parts of coordinator on some paths.
    from evals.completeness import completeness_score
    from sentinel.agents.schemas import Postmortem
    from sentinel.tools.incident_sim import seed_scenario

    overall_start = time.perf_counter()
    result = EndToEndResult(scenario_id=scenario.id)

    # Step 0 — seed Phoenix with realistic watched-system traces so the
    # sub-agents have actual data to ground in. Without this, Postmortem
    # fabricates content (the upstream stages correctly report "no
    # incident data" but Postmortem fills in plausibility).
    try:
        result.seed_summary = seed_scenario(scenario.id)
    except Exception as exc:
        result.error = f"seeding failed: {type(exc).__name__}: {exc}"
        result.total_latency_ms = int((time.perf_counter() - overall_start) * 1000)
        return result

    stages_to_run: list[tuple[str, str]] = [
        ("investigate", scenario.initial_prompt()),
        *_PIPELINE_FOLLOWUP_STAGES,
        ("postmortem", _make_postmortem_prompt(scenario)),
    ]

    # Point sub-agent tool calls at the watched project for the duration
    # of the pipeline. Self-introspection (via the synthesizer's hardcoded
    # 'sentinel' project) is unaffected.
    with _watched_project_env(scenario.watched_project):
        for name, prompt in stages_to_run:
            try:
                stage = await _run_stage(name, prompt)
            except Exception as exc:
                result.error = f"stage {name!r} failed: {type(exc).__name__}: {exc}"
                result.total_latency_ms = int((time.perf_counter() - overall_start) * 1000)
                return result
            result.stages.append(stage)

    # Extract + validate the postmortem from the final stage's output.
    pm_stage = result.stages[-1]
    pm_dict = _extract_postmortem_json(pm_stage.final_text)
    if pm_dict is None:
        result.error = "postmortem stage produced no parseable JSON block"
    else:
        try:
            result.postmortem = Postmortem(**pm_dict)
            result.completeness = completeness_score(result.postmortem)
        except Exception as exc:
            result.error = f"postmortem JSON failed schema validation: {type(exc).__name__}: {exc}"

    result.total_latency_ms = int((time.perf_counter() - overall_start) * 1000)
    return result


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
