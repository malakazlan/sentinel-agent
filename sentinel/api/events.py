"""Backward-compat re-export of the event schemas.

The wire-contract schemas were moved to sentinel/events.py because the
core coordinator imports them; FastAPI is a wrapper layer that depends
on core, not the inverse.

Imports from sentinel.api.events continue to work for the duration of
the hackathon. Frontend codegen + TypeScript mirror should also work
from this path. New core code should import from sentinel.events.
"""

from __future__ import annotations

from sentinel.events import (
    IncidentCompletedEvent,
    IncidentEvent,
    IncidentFailedEvent,
    IncidentStartedEvent,
    PostmortemValidatedEvent,
    SeedCompletedEvent,
    Severity,
    StageCompletedEvent,
    StageName,
    StageStartedEvent,
)

__all__ = [
    "IncidentCompletedEvent",
    "IncidentEvent",
    "IncidentFailedEvent",
    "IncidentStartedEvent",
    "PostmortemValidatedEvent",
    "SeedCompletedEvent",
    "Severity",
    "StageCompletedEvent",
    "StageName",
    "StageStartedEvent",
]
