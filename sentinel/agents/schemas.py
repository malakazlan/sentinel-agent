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
