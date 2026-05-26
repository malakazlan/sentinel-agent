"""Tests for the completeness scorer.

Pure unit tests — the scorer is a deterministic function over a Postmortem
(or dict). The Phoenix annotation side is exercised separately in
integration tests if needed.
"""

from __future__ import annotations

import pytest

from evals.completeness import (
    ANNOTATION_NAME,
    CompletenessResult,
    completeness_score,
)
from sentinel.agents.schemas import POSTMORTEM_REQUIRED_SECTIONS, Postmortem


# Import the schema test helpers via the test module's own fixture builder.
from tests.unit.agents.test_schemas import _valid_postmortem  # type: ignore


# ── full-postmortem scoring ────────────────────────────────────────────────


def test_complete_postmortem_scores_1_0() -> None:
    pm = _valid_postmortem()
    result = completeness_score(pm)
    assert result.score == 1.0
    assert result.label == "complete"
    assert result.n_present_and_nontrivial == result.n_required
    assert all(v.present and v.nontrivial for v in result.sections)


def test_complete_postmortem_via_dict_scores_1_0() -> None:
    """Scorer accepts plain dicts (e.g. parsed JSON not yet validated)."""
    pm = _valid_postmortem()
    result = completeness_score(pm.model_dump())
    assert result.score == 1.0


# ── partial / stub scoring ─────────────────────────────────────────────────


def test_missing_optional_payload_keys_drop_score() -> None:
    pm = _valid_postmortem().model_dump()
    del pm["lessons_learned"]
    result = completeness_score(pm)
    expected_score = round((len(POSTMORTEM_REQUIRED_SECTIONS) - 1) / len(POSTMORTEM_REQUIRED_SECTIONS), 3)
    assert result.score == expected_score
    failed = [v for v in result.sections if not (v.present and v.nontrivial)]
    assert len(failed) == 1 and failed[0].section == "lessons_learned"


def test_stub_text_section_marked_nontrivial_false() -> None:
    """A section dominated by stub tokens fails the non-trivial check."""
    pm = _valid_postmortem().model_dump()
    pm["root_cause"] = "TBD"
    result = completeness_score(pm)
    rc_verdict = next(v for v in result.sections if v.section == "root_cause")
    assert rc_verdict.present is True   # length > 0 so present
    assert rc_verdict.nontrivial is False
    assert "stub token" in rc_verdict.reason or "too short" in rc_verdict.reason


def test_too_short_string_section_fails() -> None:
    pm = _valid_postmortem().model_dump()
    pm["root_cause"] = "hi"
    result = completeness_score(pm)
    rc_verdict = next(v for v in result.sections if v.section == "root_cause")
    assert rc_verdict.nontrivial is False
    assert "too short" in rc_verdict.reason


def test_empty_list_section_fails() -> None:
    pm = _valid_postmortem().model_dump()
    pm["timeline"] = []
    result = completeness_score(pm)
    tl_verdict = next(v for v in result.sections if v.section == "timeline")
    assert tl_verdict.present is False
    assert tl_verdict.nontrivial is False


def test_list_with_only_stub_entries_fails() -> None:
    pm = _valid_postmortem().model_dump()
    pm["timeline"] = ["TBD", "...", "n/a"]
    result = completeness_score(pm)
    tl_verdict = next(v for v in result.sections if v.section == "timeline")
    assert tl_verdict.nontrivial is False


# ── label mapping ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected_label",
    [
        (1.0, "complete"),
        (0.95, "complete"),
        (0.90, "mostly_complete"),
        (0.75, "mostly_complete"),
        (0.70, "partial"),
        (0.50, "partial"),
        (0.40, "stub"),
        (0.0, "stub"),
    ],
)
def test_label_thresholds(score: float, expected_label: str) -> None:
    result = CompletenessResult(score=score, n_required=10, n_present_and_nontrivial=int(score * 10))
    assert result.label == expected_label


# ── input validation ───────────────────────────────────────────────────────


def test_scorer_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError, match="must be Postmortem or dict"):
        completeness_score("not a postmortem")  # type: ignore[arg-type]


def test_annotation_name_is_postmortem_completeness() -> None:
    """Annotation name is a stable contract for Phoenix consumers."""
    assert ANNOTATION_NAME == "postmortem_completeness"


# ── drift detector: scorer min-lengths align with schema min_length ───────


def test_section_min_chars_align_with_schema_min_length() -> None:
    """If you change ``min_length`` in ``Postmortem`` schema, update the scorer too.

    Pydantic exposes per-field metadata via ``model_fields[name].metadata``.
    For string fields with a ``min_length`` constraint, we assert the
    scorer's per-section floor matches (severity is an enum exempt; lists
    are not in the table because they're scored by element-count + per-
    element non-triviality, not character length).
    """
    from evals.completeness import _SECTION_MIN_CHARS

    # Fields with min_length in the schema, that the scorer also enforces
    string_fields_with_min = {
        "title": 10,
        "incident_id": 3,
        "summary": 50,
        "impact": 30,
        "root_cause": 30,
        "detection": 20,
        "resolution": 20,
    }
    for section, expected_min in string_fields_with_min.items():
        assert section in _SECTION_MIN_CHARS, (
            f"scorer missing min-chars entry for `{section}` — schema declares "
            f"min_length={expected_min}, scorer must mirror"
        )
        assert _SECTION_MIN_CHARS[section] == expected_min, (
            f"scorer drift: `{section}` has floor {_SECTION_MIN_CHARS[section]} "
            f"but schema declares min_length={expected_min}"
        )
