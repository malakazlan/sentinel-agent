"""IncidentEvent — the wire schema between the FastAPI backend and the
Next.js frontend.

A discriminated union over event types. The frontend's TypeScript mirror
in `web/lib/types.ts` MUST match these field names exactly. Drift here
breaks the frontend; the unit tests are the contract.

Parse a payload with `IncidentEvent.validate_json(payload)` — it returns
the right concrete subclass based on the `type` discriminator.

Event lifecycle (one incident):
  incident_started
  seed_completed
  stage_started("investigate")
  stage_completed("investigate")
  stage_started("root_cause")
  stage_completed("root_cause")
  stage_started("remediation")
  stage_completed("remediation")
  stage_started("postmortem")
  stage_completed("postmortem")
  postmortem_validated
  incident_completed

Or on error at any point:
  ...
  incident_failed
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


StageName = Literal[
    "investigate",
    "eval_fanout",  # Phase 7 / ADR-012 — ParallelEvalRunner fan-out stage
    "deploy_correlation",  # Phase 7 / ADR-014 — DeployCorrelator stage
    "root_cause",
    "remediation",
    "customer_impact",  # Phase 8 / ADR-018 — CustomerImpactQuantifier stage
    "postmortem",
    "compliance",  # Phase 8 / ADR-019 — ComplianceOfficer stage
]
Severity = Literal["P0", "P1", "P2", "P3"]


class _EventBase(BaseModel):
    """Common fields shared by every event in the lifecycle."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(..., min_length=1, max_length=120)
    elapsed_ms: int = Field(..., ge=0)


class IncidentStartedEvent(_EventBase):
    type: Literal["incident_started"] = "incident_started"
    scenario_id: str
    severity: Severity
    title: str
    watched_project: str


class SimilarIncidentSummary(BaseModel):
    """One past incident the briefing recalled, in the wire-compact shape.

    Phase 7 / ADR-013 — surfaced on the SSE protocol so the frontend can
    render the "Similar past incidents" section under the learned-routing
    callout. Mirrors ``sentinel.memory.incident_memory.SimilarIncident``
    minus the long-form fields that don't belong in a streaming event.
    """

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    scenario_id: str
    title: str = Field(..., max_length=400)
    similarity: float = Field(..., ge=0.0, le=1.0)


class BriefingResolvedEvent(_EventBase):
    """The Coordinator's self-introspection briefing for this incident.

    Phase 7 — emitted by ``run_end_to_end_scenario`` once after the seed
    step, before any agent stage runs. Carries the typed directives the
    Coordinator will honor (``first_route``, ``skip_routes``,
    ``must_eval_after``, ``default_hours_back``), the stats that triggered
    them, and the top-K similar past incidents from the RAG layer.

    The frontend renders this as: the "Learned routing" callout, the
    "Round-trips" metric, and a "Similar past incidents" precedent list.
    """

    type: Literal["briefing_resolved"] = "briefing_resolved"
    cold_start: bool
    first_route: Optional[str] = None
    skip_routes: list[str] = Field(default_factory=list)
    must_eval_after: bool = False
    default_hours_back: int = Field(..., ge=1, le=168)
    similar_past_incidents: list[SimilarIncidentSummary] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    stats: dict[str, int] = Field(default_factory=dict)


class SeedCompletedEvent(_EventBase):
    type: Literal["seed_completed"] = "seed_completed"
    project: str
    spans_written: int
    n_ok: int
    n_error: int


class StageStartedEvent(_EventBase):
    type: Literal["stage_started"] = "stage_started"
    stage: StageName
    prompt_preview: str = Field(..., max_length=400)


class StageCompletedEvent(_EventBase):
    type: Literal["stage_completed"] = "stage_completed"
    stage: StageName
    latency_ms: int = Field(..., ge=0)
    authors: list[str]
    final_text: str


class PostmortemValidatedEvent(_EventBase):
    type: Literal["postmortem_validated"] = "postmortem_validated"
    completeness_score: float = Field(..., ge=0.0, le=1.0)
    completeness_label: str
    postmortem_json: str


class IncidentCompletedEvent(_EventBase):
    type: Literal["incident_completed"] = "incident_completed"
    total_latency_ms: int = Field(..., ge=0)


class IncidentFailedEvent(_EventBase):
    type: Literal["incident_failed"] = "incident_failed"
    error: str


_EVENT_UNION = Annotated[
    Union[
        IncidentStartedEvent,
        BriefingResolvedEvent,
        SeedCompletedEvent,
        StageStartedEvent,
        StageCompletedEvent,
        PostmortemValidatedEvent,
        IncidentCompletedEvent,
        IncidentFailedEvent,
    ],
    Field(discriminator="type"),
]


IncidentEvent = TypeAdapter(_EVENT_UNION)
"""TypeAdapter for the discriminated union. Use:

    parsed = IncidentEvent.validate_json(payload)  # returns the right subclass
"""
