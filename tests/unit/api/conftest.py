"""Per-test isolation for sentinel.api.incidents._REGISTRY.

The registry is module-level by design (single-process hackathon demo),
but unit tests share the same process — without this autouse fixture,
state from one test leaks into the next.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_incident_registry() -> None:
    from sentinel.api.incidents import _REGISTRY
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()
