"""Postmortem-completeness eval — Phase 4 step 3.

Scores how complete a generated postmortem is against the
``Postmortem`` schema's required sections. The score is a deterministic
fraction: count of populated, non-trivial sections divided by total
required sections. Phoenix annotation written with ``annotator_kind="CODE"``
(this is a code-eval, not LLM-as-judge — there's no judgment, just
mechanical section accounting).

This is a **real production-grade scorer**, not demo theater:

- The required-sections list comes from ``Postmortem`` via the shared
  ``POSTMORTEM_REQUIRED_SECTIONS`` tuple — no drift possible (a unit
  test asserts the equivalence).
- "Non-trivial" means: passes the schema's own min_length and is not
  composed entirely of whitespace or filler placeholders.
- The eval works on either a typed ``Postmortem`` object OR a raw JSON
  dict (production may receive postmortems through either path).

Public API:

- ``completeness_score(postmortem)`` — pure computation, returns
  ``CompletenessResult`` with score and per-section verdict.
- ``annotate_span(span_id, result)`` — writes the annotation to Phoenix.
- ``score_and_annotate(span_id, postmortem)`` — convenience composing
  both for the typical end-of-Postmortem-turn flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from phoenix.client import Client

from sentinel.agents.schemas import POSTMORTEM_REQUIRED_SECTIONS, Postmortem

ANNOTATION_NAME = "postmortem_completeness"

# Tokens that, if they make up most of a section's content, mark the section
# as a stub even if length passes the schema's floor. Production reviewers
# treat these as red flags; the scorer matches.
_STUB_TOKENS: tuple[str, ...] = (
    "tbd",
    "todo",
    "to be determined",
    "to be filled",
    "placeholder",
    "n/a",
    "...",
    "lorem ipsum",
)

# Per-section minimum character lengths for string fields. Aligned with the
# Postmortem schema's own ``min_length`` floors (see ``schemas.py``). A unit
# test asserts equivalence so drift is caught immediately.
_SECTION_MIN_CHARS: dict[str, int] = {
    "title": 10,
    "incident_id": 3,
    "severity": 1,  # Severity is a Literal enum; any non-empty value is OK
    "summary": 50,
    "impact": 30,
    "root_cause": 30,
    "detection": 20,
    "resolution": 20,
}


@dataclass
class SectionVerdict:
    """Per-section completeness verdict."""

    section: str
    present: bool
    nontrivial: bool
    reason: str = ""


@dataclass
class CompletenessResult:
    """Aggregate result of one completeness-score computation."""

    score: float  # 0.0-1.0
    n_required: int
    n_present_and_nontrivial: int
    sections: list[SectionVerdict] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Coarse-grained label for at-a-glance dashboards."""
        if self.score >= 0.95:
            return "complete"
        if self.score >= 0.75:
            return "mostly_complete"
        if self.score >= 0.50:
            return "partial"
        return "stub"


def completeness_score(
    postmortem: Union[Postmortem, dict[str, Any]],
) -> CompletenessResult:
    """Score a postmortem's completeness; return ``CompletenessResult``.

    Args:
        postmortem: A validated ``Postmortem`` object OR a raw dict (e.g.
            parsed JSON from a span output). When a dict is given, the
            scorer does NOT validate it against the schema — it only
            checks presence + non-triviality of each required section.

    Returns:
        ``CompletenessResult`` with overall score, counts, and per-section
        verdicts (useful for the UI to highlight which sections need work).
    """
    if isinstance(postmortem, Postmortem):
        payload = postmortem.model_dump()
    elif isinstance(postmortem, dict):
        payload = postmortem
    else:
        raise TypeError(
            f"postmortem must be Postmortem or dict, got {type(postmortem).__name__}"
        )

    verdicts: list[SectionVerdict] = []
    n_present_and_nontrivial = 0
    for section in POSTMORTEM_REQUIRED_SECTIONS:
        value = payload.get(section)
        present = value is not None and value != "" and value != []
        nontrivial, reason = _is_nontrivial(section, value)
        if present and nontrivial:
            n_present_and_nontrivial += 1
        verdicts.append(
            SectionVerdict(
                section=section,
                present=present,
                nontrivial=nontrivial,
                reason=reason,
            )
        )

    n_required = len(POSTMORTEM_REQUIRED_SECTIONS)
    score = n_present_and_nontrivial / n_required if n_required else 0.0
    return CompletenessResult(
        score=round(score, 3),
        n_required=n_required,
        n_present_and_nontrivial=n_present_and_nontrivial,
        sections=verdicts,
    )


def annotate_span(span_id: str, result: CompletenessResult) -> None:
    """Write a ``postmortem_completeness`` annotation to a Phoenix span.

    Score is the primary numeric; explanation lists any sections that
    failed the present-and-nontrivial check so the Phoenix UI surfaces
    actionable feedback alongside the score.
    """
    failed = [
        v.section
        for v in result.sections
        if not (v.present and v.nontrivial)
    ]
    explanation = (
        f"score {result.score:.2f} ({result.label}); "
        f"{result.n_present_and_nontrivial}/{result.n_required} sections complete"
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )
    Client().spans.add_span_annotation(
        span_id=span_id,
        annotation_name=ANNOTATION_NAME,
        annotator_kind="CODE",
        score=float(result.score),
        label=result.label,
        explanation=explanation,
        sync=True,
    )


def score_and_annotate(
    span_id: str,
    postmortem: Union[Postmortem, dict[str, Any]],
) -> CompletenessResult:
    """Convenience: score the postmortem and annotate the span in one call."""
    result = completeness_score(postmortem)
    annotate_span(span_id, result)
    return result


_DEFAULT_LIST_ENTRY_MIN_CHARS = 5


def _is_nontrivial(section: str, value: Any) -> tuple[bool, str]:
    """Decide whether a section's value counts as substantive content.

    Per-section length floors come from ``_SECTION_MIN_CHARS`` (which mirrors
    the schema's ``min_length`` floors). List sections check element count
    plus per-element non-triviality.

    Returns ``(nontrivial: bool, reason: str)``. ``reason`` is empty on pass.
    """
    if value is None:
        return False, "missing"
    if isinstance(value, str):
        stripped = value.strip().lower()
        floor = _SECTION_MIN_CHARS.get(section, _DEFAULT_LIST_ENTRY_MIN_CHARS)
        if len(stripped) < floor:
            return False, f"too short (<{floor} chars)"
        for token in _STUB_TOKENS:
            if token in stripped and len(token) >= len(stripped) * 0.5:
                return False, f"dominated by stub token '{token}'"
        return True, ""
    if isinstance(value, list):
        if not value:
            return False, "empty list"
        # All-empty or all-stub lists are not non-trivial
        nontrivial_entries = 0
        for entry in value:
            if isinstance(entry, str):
                stripped = entry.strip().lower()
                if len(stripped) >= _DEFAULT_LIST_ENTRY_MIN_CHARS and not any(
                    token in stripped and len(token) >= len(stripped) * 0.5
                    for token in _STUB_TOKENS
                ):
                    nontrivial_entries += 1
            elif entry:
                # dicts (e.g. ActionItem) — any truthy entry counts
                nontrivial_entries += 1
        if nontrivial_entries == 0:
            return False, "no non-trivial entries"
        return True, ""
    if isinstance(value, dict):
        return bool(value), "" if value else "empty dict"
    return bool(value), "" if value else "falsy"
