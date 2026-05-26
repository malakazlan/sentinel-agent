"""Incident endpoints + in-process incident registry.

For the hackathon UI, all state is in memory — single-user, single-process.
Each running incident has an asyncio.Queue that the SSE endpoint drains.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sentinel.api.events import IncidentFailedEvent
from sentinel.coordinator import EndToEndResult, run_end_to_end_scenario
from sentinel.scenarios import IncidentScenario, get_scenario


router = APIRouter(prefix="/incidents", tags=["incidents"])


@dataclass
class _IncidentState:
    incident_id: str
    scenario_id: str
    severity: str
    title: str
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    result: EndToEndResult | None = None
    failed_with: str | None = None
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


_REGISTRY: dict[str, _IncidentState] = {}


class CreateIncidentRequest(BaseModel):
    """Request body for POST /incidents — identifies which scenario to run."""

    scenario_id: str = Field(..., min_length=3, max_length=80)


class CreateIncidentResponse(BaseModel):
    """Response body confirming an incident was accepted and scheduled."""

    incident_id: str
    scenario_id: str
    severity: str
    title: str
    started_at: datetime


@router.post("", status_code=201, response_model=CreateIncidentResponse)
async def create_incident(req: CreateIncidentRequest) -> CreateIncidentResponse:
    """Start a new incident pipeline run for the given scenario."""
    started_at = datetime.now(timezone.utc)
    try:
        scenario = get_scenario(req.scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {req.scenario_id}") from exc

    base = scenario.alert_payload.get("alert_id") or scenario.id
    incident_id = f"{base}-{uuid.uuid4().hex[:8]}"
    state = _IncidentState(
        incident_id=incident_id,
        scenario_id=scenario.id,
        severity=scenario.severity,
        title=scenario.title,
    )
    _REGISTRY[incident_id] = state

    _run_in_background(state, scenario)

    return CreateIncidentResponse(
        incident_id=incident_id,
        scenario_id=scenario.id,
        severity=scenario.severity,
        title=scenario.title,
        started_at=started_at,
    )


def _run_in_background(state: _IncidentState, scenario: IncidentScenario) -> None:
    """Spawn the pipeline as an asyncio task; events fan out to the state queue.

    The callback wraps queue.put in a no-raise guard so that a queue
    failure (which shouldn't happen with an unbounded queue, but is
    defended against per code-review feedback on Task 2) never masks
    the original agent-side error.
    """

    async def emit(event: Any) -> None:
        try:
            await state.queue.put(event)
        except Exception:  # noqa: BLE001 — defense in depth, never mask
            pass

    async def runner() -> None:
        try:
            state.result = await run_end_to_end_scenario(scenario, on_event=emit)
        except Exception as exc:  # noqa: BLE001 — surface to the client via the queue
            state.failed_with = f"{type(exc).__name__}: {exc}"
            try:
                await state.queue.put(
                    IncidentFailedEvent(
                        incident_id=state.incident_id,
                        elapsed_ms=0,
                        error=state.failed_with,
                    )
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            state.completed.set()

    state.task = asyncio.create_task(runner())
