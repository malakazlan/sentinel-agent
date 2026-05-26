"""IncidentEvent — the wire schema between the FastAPI backend and the
Next.js frontend.

A discriminated union over event types. The frontend's TypeScript mirror
in `web/lib/types.ts` MUST match these field names exactly. Drift here
breaks the frontend; the unit tests are the contract.

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

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, RootModel


StageName = Literal["investigate", "root_cause", "remediation", "postmortem"]
Severity = Literal["P0", "P1", "P2", "P3"]


class _EventBase(BaseModel):
    """Common fields shared by every event in the lifecycle."""

    incident_id: str = Field(..., min_length=1, max_length=120)
    elapsed_ms: int = Field(..., ge=0)


class IncidentStartedEvent(_EventBase):
    type: Literal["incident_started"] = "incident_started"
    scenario_id: str
    severity: Severity
    title: str
    watched_project: str


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
        SeedCompletedEvent,
        StageStartedEvent,
        StageCompletedEvent,
        PostmortemValidatedEvent,
        IncidentCompletedEvent,
        IncidentFailedEvent,
    ],
    Field(discriminator="type"),
]


class IncidentEvent(RootModel[_EVENT_UNION]):
    """Discriminated union — `IncidentEvent.model_validate_json(payload)`
    returns the right subclass based on the `type` field."""

    @classmethod
    def model_validate_json(cls, payload: str | bytes) -> _EVENT_UNION:  # type: ignore[override]
        return super().model_validate_json(payload).root
