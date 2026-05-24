"""Schema and validator tests for ``PriorContextBriefing``.

These cover the contract surface — the directive shape that ADR-009 makes
load-bearing for plan determinism. They run without any external service.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.memory.briefing import PriorContextBriefing


def test_cold_start_defaults_are_inert() -> None:
    b = PriorContextBriefing(cold_start=True)
    assert b.cold_start is True
    assert b.first_route is None
    assert b.skip_routes == []
    assert b.must_eval_after is False
    assert b.default_hours_back == 1
    assert b.evidence == {}
    assert b.stats == {}


def test_warm_first_route_preserves_evidence() -> None:
    b = PriorContextBriefing(
        first_route="trace_analyzer",
        evidence={"first_route": "5 of last 8 traces ERROR"},
        stats={"n_total": 8, "n_error": 5},
    )
    assert b.first_route == "trace_analyzer"
    assert b.evidence["first_route"] == "5 of last 8 traces ERROR"
    assert b.stats["n_error"] == 5


def test_skip_routes_accepts_subagent_names() -> None:
    b = PriorContextBriefing(skip_routes=["trace_analyzer", "eval_runner"])
    assert "trace_analyzer" in b.skip_routes
    assert "eval_runner" in b.skip_routes


def test_must_eval_after_with_eval_runner_skip_is_rejected() -> None:
    """Demo-critical correctness: cannot both force and forbid eval."""
    with pytest.raises(ValidationError) as exc_info:
        PriorContextBriefing(
            must_eval_after=True,
            skip_routes=["eval_runner"],
        )
    assert "must_eval_after" in str(exc_info.value)


def test_must_eval_after_with_trace_analyzer_skip_is_allowed() -> None:
    """Only the eval_runner + must_eval_after combo is contradictory."""
    b = PriorContextBriefing(
        must_eval_after=True,
        skip_routes=["trace_analyzer"],
    )
    assert b.must_eval_after is True
    assert b.skip_routes == ["trace_analyzer"]


def test_default_hours_back_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        PriorContextBriefing(default_hours_back=0)


def test_default_hours_back_rejects_above_one_week() -> None:
    with pytest.raises(ValidationError):
        PriorContextBriefing(default_hours_back=169)


def test_default_hours_back_accepts_bounds() -> None:
    PriorContextBriefing(default_hours_back=1)
    PriorContextBriefing(default_hours_back=168)


def test_first_route_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        PriorContextBriefing(first_route="some_unknown_route")


def test_skip_routes_rejects_direct_tool() -> None:
    """`direct_tool` is a valid first_route but not a sub-agent — can't be skipped."""
    with pytest.raises(ValidationError):
        PriorContextBriefing(skip_routes=["direct_tool"])
