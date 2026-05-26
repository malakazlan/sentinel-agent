"""Per-test isolation for sentinel.api.incidents._REGISTRY.

Mirrors tests/unit/api/conftest.py — the registry is module-level by
design, but tests in this directory will accumulate state without an
autouse clear-fixture, especially as more lifecycle scenarios get added.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_incident_registry() -> None:
    from sentinel.api.incidents import _REGISTRY
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()
