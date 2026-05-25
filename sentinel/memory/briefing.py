"""Typed briefing schema — the self-improvement loop's contract (ADR-009).

The output of ``synthesize_prior_context`` is a ``PriorContextBriefing``
object whose fields are consumed as **concrete plan-shaping directives** by
the Coordinator, not as prose for the LLM to interpret. This typed contract
is what makes the differentiator demo-reproducible: every non-default
directive forces an observable, deterministic change in the executed plan.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Closed set of routes the Coordinator can take. Anything outside this
# enumeration is a bug.
Route = Literal["trace_analyzer", "eval_runner", "root_cause", "remediation", "direct_tool"]
SubAgentRoute = Literal["trace_analyzer", "eval_runner", "root_cause", "remediation"]


class PriorContextBriefing(BaseModel):
    """Trace-derived directives for the Coordinator's next turn.

    Distinct from a memory recap: every field is plan-shaping, evidence-
    backed, and consumed as a concrete directive — not a vague hint the
    LLM has to weigh. See ADR-009.
    """

    cold_start: bool = Field(
        default=False,
        description=(
            "True when no usable history was extractable from Phoenix MCP. "
            "Coordinator routes per defaults and does not invent context."
        ),
    )

    # ── ROUTING (plan-shape directives) ───────────────────────────────────
    first_route: Optional[Route] = Field(
        default=None,
        description=(
            "Override the Coordinator's default routing for the current "
            "non-trivial request. When set, the Coordinator's first action "
            "MUST be this route. Greetings and capability questions still "
            "bypass."
        ),
    )
    skip_routes: list[SubAgentRoute] = Field(
        default_factory=list,
        description=(
            "Sub-agents the Coordinator must NOT transfer to this turn even "
            "if the user phrasing matches their trigger list. Used for "
            "legitimate redundancy (eval already ran clean on near-identical "
            "input). Per ADR-009 narrative discipline, this is an audit/"
            "capability feature, not the demo's headline mechanism."
        ),
    )

    # ── POST-ACTION (forced follow-ups) ───────────────────────────────────
    must_eval_after: bool = Field(
        default=False,
        description=(
            "If true, after the main response, the Coordinator MUST also "
            "trigger eval_runner. Set when recent traces show any "
            "hallucination signal — doubles down on safety."
        ),
    )

    # ── PARAMETER OVERRIDES (tool-arg directives) ─────────────────────────
    default_hours_back: int = Field(
        default=1,
        ge=1,
        le=168,
        description=(
            "Default time window for get_recent_traces, derived from "
            "observed volume. Widen when activity is low; keep narrow when "
            "high. Capped at 1 week (168h)."
        ),
    )

    # ── EVIDENCE TRAIL (the WHY — what makes it a loop, not a guess) ──────
    evidence: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Maps each non-default directive field to a one-sentence "
            "'because <trace-derived fact>'. Surfaces in the Coordinator's "
            "prompt next to each directive and in Phoenix span attributes."
        ),
    )

    # ── RAW STATS (transparency, not for routing logic) ───────────────────
    stats: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Aggregations the Coordinator may reference if asked to "
            "explain itself: n_total, n_error, n_hallucinated, n_faithful, "
            "median_latency_ms, lookback_hours."
        ),
    )

    @model_validator(mode="after")
    def _no_contradictions(self) -> "PriorContextBriefing":
        """Reject incoherent directive combinations at construction time.

        ``must_eval_after=True`` and ``eval_runner`` in ``skip_routes`` cannot
        coexist: the synthesizer would be both forcing and forbidding the
        same action. Better to fail loudly at construction than to ship a
        contradictory plan and have the Coordinator silently pick one rule.
        """
        if self.must_eval_after and "eval_runner" in self.skip_routes:
            raise ValueError(
                "must_eval_after=True is incompatible with eval_runner in "
                "skip_routes: cannot both force and forbid the eval pass. "
                "Fix the synthesizer rule that produced both directives."
            )
        return self
