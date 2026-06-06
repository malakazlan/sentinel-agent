"""Cross-agent output schemas — Phase 4.

Schemas in this module define the **contracts between sub-agents** so each
agent's output is parseable by downstream consumers (other sub-agents, the
Streamlit UI, or any real ticketing / alerting system Sentinel feeds).

Per the real-system-not-just-demo framing: these schemas are designed to be
consumable by production tools (PagerDuty incident enrichments, Jira/Linear
ticket fields, internal SRE templates). They are NOT demo theater — they
reflect what a real ops team would expect to see in an incident response.

Phase 4 contains:

- ``RemediationPlan`` — what the Remediation sub-agent produces
- ``EvalGuardrail`` — nested in RemediationPlan; describes a new eval that
  should run post-deploy to detect recurrence
- ``Postmortem`` — Google-SRE-format RCA produced by the Postmortem sub-agent
- ``ActionItem`` — nested in Postmortem; one tracked follow-up with owner + due date
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Severity = Literal["P0", "P1", "P2", "P3"]
Confidence = Literal["low", "medium", "high"]


class EvalGuardrail(BaseModel):
    """A named eval suite that should run post-deploy to catch regression.

    Designed to be consumed by an evals registry / CI pipeline that
    schedules these as continuous post-deploy checks.
    """

    name: str = Field(
        ..., min_length=3, max_length=80,
        description="snake_case identifier the evals registry can hash on, e.g. 'fp_rate_spike_5m'.",
    )
    trigger_metric: str = Field(
        ..., min_length=2,
        description="Metric or signal the eval watches, e.g. 'fp_rate_5m' or 'kyc_sanctions_match_rate'.",
    )
    threshold: float = Field(
        ...,
        description="Numeric breach threshold for ``trigger_metric``. Units match the metric's natural scale.",
    )
    severity_on_breach: Severity = Field(
        ...,
        description="What severity the eval should page at if it breaches.",
    )
    why_this_eval: str = Field(
        ..., min_length=10, max_length=300,
        description="One sentence linking this eval back to the incident being remediated.",
    )


class RemediationPlan(BaseModel):
    """Structured remediation plan produced by the Remediation sub-agent.

    Designed to be the payload an incident-management system can ingest:
    severity sets paging, confidence guides automation thresholds, the
    three action fields are the concrete things on-call would execute, and
    ``rollback_plan_if_remediation_fails`` is required so no remediation
    ships without an escape hatch.
    """

    severity: Severity = Field(
        ...,
        description="Incident severity tier this remediation targets. Aligns with on-call paging tiers.",
    )
    confidence: Confidence = Field(
        ...,
        description=(
            "Confidence in the proposed plan. ``low`` means a human MUST review "
            "before applying; ``high`` means safe for automated rollout in a "
            "guarded pipeline."
        ),
    )

    # At least one action — enforced by model_validator below
    patched_prompt: Optional[str] = Field(
        default=None,
        description=(
            "Replacement prompt text if root cause is a bad prompt change. "
            "Must be specific enough to apply directly — no placeholders."
        ),
    )
    rollback_target: Optional[str] = Field(
        default=None,
        description=(
            "Version / commit / model identifier to roll back to. Format is "
            "deploy-pipeline-specific (e.g. 'fraud-classifier-v2.2.7', "
            "'commit:a3f9e22', 'model:fraud-classifier@2025-05-23')."
        ),
    )
    eval_guardrail: Optional[EvalGuardrail] = Field(
        default=None,
        description="A new post-deploy eval suite to catch recurrence of this failure mode.",
    )

    rationale: str = Field(
        ..., min_length=20, max_length=600,
        description=(
            "1-3 sentences linking the proposed action(s) back to the RootCause "
            "hypothesis or trace evidence. No fabrication — must reference real signals."
        ),
    )
    risks: list[str] = Field(
        default_factory=list,
        description=(
            "Specific risks to consider before applying. Empty list is acceptable "
            "only when confidence='high' and the action is a pure rollback."
        ),
    )
    rollback_plan_if_remediation_fails: str = Field(
        ..., min_length=15, max_length=400,
        description=(
            "What on-call should do if this remediation worsens the incident. "
            "Required — no remediation ships without an escape hatch."
        ),
    )

    @model_validator(mode="after")
    def _at_least_one_action(self) -> "RemediationPlan":
        """A plan with no actions is not a plan — reject at construction."""
        if not (self.patched_prompt or self.rollback_target or self.eval_guardrail):
            raise ValueError(
                "RemediationPlan must propose at least ONE action: "
                "patched_prompt, rollback_target, or eval_guardrail. "
                "A plan with no actions is not a plan."
            )
        return self

    @model_validator(mode="after")
    def _low_confidence_requires_risks(self) -> "RemediationPlan":
        """Low-confidence plans without explicit risks are dangerous — reject."""
        if self.confidence == "low" and not self.risks:
            raise ValueError(
                "confidence='low' requires at least one entry in `risks`. "
                "An honest low-confidence plan must surface what could go wrong."
            )
        return self


# ── Postmortem (Google-SRE format) ────────────────────────────────────────


class ActionItem(BaseModel):
    """One follow-up action emerging from a postmortem.

    Owner is a **role / team identifier**, not a person — production
    postmortems should not bind to individual humans (they rotate).
    """

    description: str = Field(
        ..., min_length=20, max_length=300,
        description="What needs to be done. Specific and verifiable — not a vague aspiration.",
    )
    owner_role: str = Field(
        ..., min_length=3, max_length=50,
        description="Team or role responsible, e.g. 'fraud-ml-team', 'platform-sre'.",
    )
    severity: Severity = Field(
        ...,
        description="Priority of this follow-up. Aligns with ticketing severity.",
    )
    due_within_days: int = Field(
        ..., ge=1, le=90,
        description="Calendar days from postmortem date by which this should land.",
    )


class Postmortem(BaseModel):
    """Google-SRE-format Root Cause Analysis document, schema-validated.

    Every field is required and has a length floor to prevent stub sections.
    A postmortem with zero action items or zero lessons-learned is not a
    postmortem — those are explicitly rejected at construction time.

    Designed to be ingestable as a structured ticket attachment, an
    audit-log artifact for FinServ compliance, or rendered as Markdown for
    a wiki / shared doc — the schema is the contract; rendering is a view.
    """

    title: str = Field(
        ..., min_length=10, max_length=120,
        description="One-line incident title, e.g. 'Fraud-detection false-positive burst 2026-05-24'.",
    )
    incident_id: str = Field(
        ..., min_length=3, max_length=80,
        description="Stable identifier linking to the alerting system (e.g. PagerDuty alert id).",
    )
    severity: Severity = Field(
        ...,
        description="Severity at peak impact. Aligns with on-call paging tier.",
    )
    summary: str = Field(
        ..., min_length=50, max_length=500,
        description="2-3 sentence executive overview that a VP could read in 15 seconds.",
    )
    impact: str = Field(
        ..., min_length=30, max_length=500,
        description=(
            "User-facing impact with specific numbers (accounts affected, transactions "
            "blocked, revenue at risk, regulatory exposure). No fabricated figures."
        ),
    )
    timeline: list[str] = Field(
        ..., min_length=2,
        description=(
            "Ordered list of 'HH:MM UTC — what happened' lines, from earliest signal "
            "to resolution. At least 2 entries (one for onset, one for resolution)."
        ),
    )
    root_cause: str = Field(
        ..., min_length=30, max_length=500,
        description=(
            "2-4 sentences naming the proximate cause. Must link to a RootCause "
            "hypothesis or to trace evidence — no fabrication."
        ),
    )
    detection: str = Field(
        ..., min_length=20, max_length=400,
        description=(
            "How was this discovered? What signal fired, how many minutes elapsed "
            "between onset and detection?"
        ),
    )
    resolution: str = Field(
        ..., min_length=20, max_length=500,
        description=(
            "What was done to mitigate. Links to the RemediationPlan if applicable. "
            "States whether the fix is durable or a stop-gap."
        ),
    )
    action_items: list[ActionItem] = Field(
        ..., min_length=1,
        description=(
            "Tracked follow-ups. A postmortem with zero action items is suspect — "
            "if nothing comes out of this incident, why did we write it up?"
        ),
    )
    lessons_learned: list[str] = Field(
        ..., min_length=1,
        description=(
            "Plain-language insights that should outlive this incident. At least one."
        ),
    )

    # Phase 8 / ADR-018 — optional structured impact section. Optional so
    # legacy postmortems (and tests authored before Phase 8) still validate.
    impact_quantified: Optional["ImpactReport"] = Field(
        default=None,
        description=(
            "Structured impact: dollars, customer count, revenue estimate. "
            "Populated by CustomerImpactQuantifier between root_cause and "
            "postmortem stages. None when the agent is disabled or unavailable."
        ),
    )

    # Phase 8 / ADR-019 — regulatory exposure populated by the
    # ComplianceOfficerAgent that runs after PostmortemAgent. Optional so
    # legacy postmortems still validate.
    regulatory_citations: list["CitedClause"] = Field(
        default_factory=list,
        description=(
            "List of cited regulator clauses, each grounded in the "
            "curated corpus. Empty list is acceptable only when the "
            "ComplianceOfficer determined no specific regulation matched."
        ),
    )
    reporting_obligations: list["ReportingObligation"] = Field(
        default_factory=list,
        description=(
            "List of regulator notifications this incident triggers, "
            "with timeframes (24h / 72h / 30d) and one-line draft "
            "headlines. May be empty when no obligations apply."
        ),
    )

    # Phase 8 / ADR-022 + ADR-023 — drift + fairness sections produced
    # deterministically by the DriftDetective + BiasFairnessAuditor
    # pipeline stages. Stored as dicts (rather than typed sub-models)
    # to avoid a forward-reference cycle between this schema and the
    # agent-side report models. The orchestrator attaches the agent's
    # ``report.model_dump()`` result. Optional so legacy postmortems
    # still validate.
    drift_analysis: Optional[dict] = Field(
        default=None,
        description=(
            "KS (numeric) + PSI (categorical) drift analysis between the "
            "baseline window and the incident window. Populated by the "
            "DriftDetective stage. None when the stage didn't run or "
            "insufficient baseline data was available."
        ),
    )
    fairness_analysis: Optional[dict] = Field(
        default=None,
        description=(
            "Disparate-impact (4/5ths rule) + statistical parity + "
            "equalized odds analysis across protected attributes. "
            "Populated by the BiasFairnessAuditor stage. None when the "
            "stage didn't run or there was insufficient per-group data."
        ),
    )

    @model_validator(mode="after")
    def _timeline_entries_nonempty(self) -> "Postmortem":
        """No empty strings in the timeline."""
        empty = [i for i, entry in enumerate(self.timeline) if not entry.strip()]
        if empty:
            raise ValueError(
                f"timeline contains empty entries at positions {empty}; "
                "every timeline line must have content."
            )
        return self

    @model_validator(mode="after")
    def _lessons_nonempty(self) -> "Postmortem":
        """No empty strings in lessons_learned."""
        empty = [i for i, lesson in enumerate(self.lessons_learned) if not lesson.strip()]
        if empty:
            raise ValueError(
                f"lessons_learned contains empty entries at positions {empty}."
            )
        return self


# Required section keys for completeness scoring (used by evals/completeness.py).
# Single source of truth — the eval doesn't redefine this; it imports the tuple.
POSTMORTEM_REQUIRED_SECTIONS: tuple[str, ...] = (
    "title",
    "incident_id",
    "severity",
    "summary",
    "impact",
    "timeline",
    "root_cause",
    "detection",
    "resolution",
    "action_items",
    "lessons_learned",
)


# ── Phase 8 / ADR-018 — CustomerImpactQuantifier output ───────────────────


ImpactConfidence = Literal["seed_grounded", "scenario_inferred", "default_caveat"]
"""Provenance tag for an ``ImpactReport``.

- ``seed_grounded`` — every figure trace-able to a Scenario.impact_seed value.
- ``scenario_inferred`` — figures derived from alert_payload data, no seed.
- ``default_caveat`` — neither seed nor payload had usable data; zeros + caveats.
"""


class ImpactReport(BaseModel):
    """Quantified customer + financial impact of an incident.

    Read by VP / Finance / Customer Ops, not just engineering. Postmortems
    without a dollar figure get filed and ignored; this schema fixes that
    while constraining the LLM to grounded numbers via the
    ``audit_citation_lines`` field (every claim must cite where it came from).
    """

    dollars_at_risk_usd: float = Field(
        ..., ge=0,
        description=(
            "Total dollar exposure during the incident window. "
            "Non-negative. Zero is acceptable only with caveat citation."
        ),
    )
    customers_affected: int = Field(
        ..., ge=0,
        description="Distinct customer count impacted. Non-negative integer.",
    )
    transactions_affected: int = Field(
        ..., ge=0,
        description=(
            "Affected transaction / decision / interaction count. "
            "Non-negative integer."
        ),
    )
    estimated_revenue_loss_usd: float = Field(
        ..., ge=0,
        description=(
            "Estimated unrecoverable revenue (after refunds, retries). "
            "May be smaller than ``dollars_at_risk_usd`` — the latter is "
            "exposure, the former is realized loss."
        ),
    )
    customer_trust_score_delta: float = Field(
        ..., ge=-1.0, le=1.0,
        description=(
            "Modeled change in a 0-1 customer-trust index. Negative = trust "
            "loss. Bounded in [-1, 1]. Source for figure must be in "
            "audit_citation_lines."
        ),
    )
    audit_citation_lines: list[str] = Field(
        ..., min_length=1,
        description=(
            "One citation line per claim in this report. Each line names "
            "the source (e.g. 'scenario.impact_seed.avg_transaction_usd=120'). "
            "Required — a report without citations is rejected at schema time."
        ),
    )
    confidence: ImpactConfidence = Field(
        ...,
        description="Provenance tag — how grounded the figures are.",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description=(
            "Plain-language caveats the reader must know — missing data, "
            "estimation method, etc. Empty list allowed only when confidence "
            "is ``seed_grounded``."
        ),
    )

    @model_validator(mode="after")
    def _caveats_required_when_not_seed_grounded(self) -> "ImpactReport":
        if self.confidence != "seed_grounded" and not self.caveats:
            raise ValueError(
                f"ImpactReport with confidence={self.confidence!r} must "
                "include at least one caveat — figures are not seed-grounded."
            )
        return self


# ── Phase 8 / ADR-019 — Regulatory citations + reporting obligations ──────


class CitedClause(BaseModel):
    """One regulator clause the ComplianceOfficer judged applicable.

    The post-LLM validator enforces that the ``(regulation_short_name,
    clause_id)`` tuple appeared in the most recent
    ``RegulatorySearch.semantic_search`` result. Any cite that doesn't
    resolve is replaced with the fallback "no specific regulation
    matched, generic guidance applied" block. Hallucinated cites are a
    disqualifier (ADR-019).
    """

    regulation_short_name: str = Field(..., min_length=2, max_length=40)
    regulation_full_name: str = Field(..., min_length=2, max_length=200)
    clause_id: str = Field(..., min_length=1, max_length=40)
    clause_title: str = Field(..., min_length=2, max_length=200)
    quoted_excerpt: str = Field(
        ..., min_length=20, max_length=800,
        description=(
            "Verbatim excerpt from the clause that the agent judged "
            "applicable. Must be a substring of the corpus's clause_text "
            "(the validator does NOT enforce substring at schema time, "
            "but the post-LLM check verifies the (short_name, clause_id) "
            "tuple appeared in the most recent search result)."
        ),
    )
    source_url: str = Field(..., min_length=10, max_length=500)
    applicability_rationale: str = Field(
        ..., min_length=20, max_length=400,
        description=(
            "1-2 sentences explaining why this clause applies to the "
            "specific incident under review. No fabrication — must "
            "reference the incident's failure mode."
        ),
    )


class ReportingObligation(BaseModel):
    """One regulator notification this incident triggers."""

    regulator: str = Field(..., min_length=3, max_length=120)
    timeframe_days: int = Field(
        ..., ge=0, le=365,
        description=(
            "Reporting window in calendar days from incident detection. "
            "0 = immediate; e.g. FCA SUP 15.3 = 1 day; EU AI Act = 3."
        ),
    )
    triggered_by_clauses: list[str] = Field(
        ..., min_length=1,
        description=(
            "List of clause ids that triggered this obligation. Each "
            "must appear in the report's citations."
        ),
    )
    draft_notification_headline: str = Field(
        ..., min_length=20, max_length=300,
        description=(
            "One-line draft headline for the regulator notification. "
            "Specific enough to anchor a longer drafted notification but "
            "does NOT include sensitive customer detail."
        ),
    )


class ComplianceReport(BaseModel):
    """The ComplianceOfficer's output — citations + obligations.

    When the corpus search returns no applicable clauses, the agent emits
    ``no_applicable_regulations=True`` plus a single ``generic_guidance``
    string. The schema rejects the empty-citations + empty-guidance
    combination — the agent must say something.
    """

    incident_id: str = Field(..., min_length=3, max_length=80)
    citations: list[CitedClause] = Field(default_factory=list)
    reporting_obligations: list[ReportingObligation] = Field(default_factory=list)
    no_applicable_regulations: bool = Field(
        default=False,
        description=(
            "True only when the corpus search returned no clauses the "
            "agent judged applicable. Pair with a non-empty "
            "``generic_guidance`` string."
        ),
    )
    generic_guidance: Optional[str] = Field(
        default=None,
        description=(
            "Fallback guidance string when no specific regulation "
            "matched. Required when ``no_applicable_regulations=True``."
        ),
    )

    @model_validator(mode="after")
    def _empty_combo_is_invalid(self) -> "ComplianceReport":
        if (
            not self.citations
            and not self.no_applicable_regulations
        ):
            raise ValueError(
                "ComplianceReport with no citations must set "
                "no_applicable_regulations=True and include "
                "generic_guidance."
            )
        if self.no_applicable_regulations and not self.generic_guidance:
            raise ValueError(
                "no_applicable_regulations=True requires non-empty "
                "generic_guidance."
            )
        return self


# ── Phase 7 / Addition 4 / ADR-016 — CriticAgent output ───────────────────


class CritiqueResult(BaseModel):
    """Rubric-scored critique of a draft Postmortem.

    Produced by ``CriticAgent`` after PostmortemAgent drafts. When ``score``
    is below the configured threshold (default 0.85), the orchestrator
    feeds ``critique`` + ``gaps_by_section`` back to PostmortemAgent for
    one revision iteration. Max 2 iterations to bound cost.
    """

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate quality score on [0, 1]. >=0.85 = acceptable.",
    )
    rubric_scores: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-dimension scores (completeness, grounding, actionability, "
            "customer_impact). Each in [0, 1]. The aggregate is computed by "
            "the critic; consumers may inspect individual dimensions to "
            "decide whether to escalate or accept."
        ),
    )
    critique: str = Field(
        ...,
        min_length=20,
        description=(
            "Plain-language critique aimed at the PostmortemAgent for "
            "revision. References specific sections by name and cites the "
            "rubric dimension that failed."
        ),
    )
    gaps_by_section: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of postmortem section name → one-line gap description. "
            "Empty dict when no section gaps were identified (e.g. when "
            "the critique is about cross-cutting issues like grounding)."
        ),
    )
    accept: bool = Field(
        ...,
        description=(
            "Whether the critic recommends accepting the postmortem as-is. "
            "True iff score >= threshold. Set by the consumer based on the "
            "configured threshold."
        ),
    )

    @model_validator(mode="after")
    def _rubric_scores_in_unit_interval(self) -> "CritiqueResult":
        for dim, val in self.rubric_scores.items():
            if not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"rubric_scores[{dim!r}]={val} outside [0, 1]"
                )
        return self
