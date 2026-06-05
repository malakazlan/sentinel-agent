"""Tests for ComplianceOfficer + ComplianceReport schema + hallucination guard.

Phase 8 / ADR-019. The hallucination guard is the contract that makes
"hallucinated cites are a disqualifier" enforceable in code. These
tests bite hard:

- Cites in the corpus → preserved.
- Cites NOT in the corpus → stripped; report downgraded to
  generic-guidance fallback.
- Mixed → only the grounded ones survive; orphaned reporting
  obligations (that referenced the stripped cite) also dropped.
- Empty cites + ``no_applicable_regulations=true`` + generic_guidance →
  legitimate "no match" path.
- Empty cites WITHOUT the no_applicable flag → schema rejects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.agents import LlmAgent
from pydantic import ValidationError

from sentinel.agents.compliance_officer import (
    compliance_officer,
    validate_compliance_report,
)
from sentinel.agents.schemas import (
    CitedClause,
    ComplianceReport,
    ReportingObligation,
)
from sentinel.constants import SUBAGENT_MODEL


# ── Agent wiring ──────────────────────────────────────────────────────────


def test_compliance_officer_is_llm_agent() -> None:
    assert isinstance(compliance_officer, LlmAgent)
    assert compliance_officer.name == "compliance_officer"


def test_compliance_officer_uses_subagent_model() -> None:
    assert compliance_officer.model == SUBAGENT_MODEL


def test_compliance_officer_has_search_tool() -> None:
    """Must have exactly one tool: search_regulations."""
    assert compliance_officer.tools is not None
    assert len(compliance_officer.tools) == 1


def test_compliance_officer_disallows_transfers() -> None:
    assert compliance_officer.disallow_transfer_to_parent is True
    assert compliance_officer.disallow_transfer_to_peers is True


# ── ComplianceReport schema — happy + unhappy ────────────────────────────


def _valid_cite(reg: str = "SR 11-7", clause: str = "V") -> dict:
    return {
        "regulation_short_name": reg,
        "regulation_full_name": "Federal Reserve Supervisory Guidance on Model Risk Management",
        "clause_id": clause,
        "clause_title": "Ongoing monitoring",
        "quoted_excerpt": (
            "Ongoing monitoring confirms that the model is "
            "appropriately implemented and is being used and is "
            "performing as intended."
        ),
        "source_url": "https://www.federalreserve.gov/supervisionreg/srletters/sr1107a1.pdf",
        "applicability_rationale": (
            "The 3x false-positive spike represents the kind of "
            "material performance degradation SR 11-7 requires "
            "ongoing monitoring to detect."
        ),
    }


def _valid_report() -> dict:
    return {
        "incident_id": "fraud-fp-spike-20260524T204248Z",
        "citations": [_valid_cite()],
        "reporting_obligations": [
            {
                "regulator": "Federal Reserve / OCC primary supervisor",
                "timeframe_days": 30,
                "triggered_by_clauses": ["V"],
                "draft_notification_headline": (
                    "Material false-positive rate deviation detected "
                    "in production fraud-detection model; rollback "
                    "completed within 60s."
                ),
            }
        ],
        "no_applicable_regulations": False,
        "generic_guidance": None,
    }


def test_valid_report_validates() -> None:
    r = ComplianceReport.model_validate(_valid_report())
    assert len(r.citations) == 1
    assert r.no_applicable_regulations is False


def test_empty_citations_without_no_applicable_rejected() -> None:
    """A report with no citations must explicitly flag ``no_applicable``."""
    bad = _valid_report()
    bad["citations"] = []
    bad["reporting_obligations"] = []
    # leave no_applicable_regulations=False — should reject
    with pytest.raises(ValidationError, match="no_applicable_regulations"):
        ComplianceReport.model_validate(bad)


def test_no_applicable_without_generic_guidance_rejected() -> None:
    bad = _valid_report()
    bad["citations"] = []
    bad["reporting_obligations"] = []
    bad["no_applicable_regulations"] = True
    bad["generic_guidance"] = None
    with pytest.raises(ValidationError, match="generic_guidance"):
        ComplianceReport.model_validate(bad)


def test_no_applicable_with_guidance_accepted() -> None:
    """The legitimate ``no match in corpus`` fallback path."""
    ok = _valid_report()
    ok["citations"] = []
    ok["reporting_obligations"] = []
    ok["no_applicable_regulations"] = True
    ok["generic_guidance"] = (
        "no specific regulation matched; apply firm-internal incident "
        "review process within 30 days"
    )
    r = ComplianceReport.model_validate(ok)
    assert r.no_applicable_regulations is True
    assert r.generic_guidance is not None


# ── Hallucination guard — the ADR-019 disqualifier check ─────────────────


@pytest.fixture
def fixture_corpus_path(tmp_path: Path) -> Path:
    """Tiny in-test corpus with two real-looking entries."""
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"regulation_short_name": "SR 11-7", "regulation_full_name": "Federal Reserve Supervisory Guidance on Model Risk Management", "clause_id": "V", "clause_title": "Ongoing monitoring", "clause_text": "Ongoing monitoring confirms that the model is appropriately implemented and is being used and is performing as intended in regulated settings.", "source_url": "https://example.gov/sr11-7", "retrieved_at": "2026-05-01", "applicable_workflows": ["fraud detection"]}\n'
        '{"regulation_short_name": "EU AI Act", "regulation_full_name": "Regulation (EU) 2024/1689 on Artificial Intelligence", "clause_id": "Article 14", "clause_title": "Human oversight", "clause_text": "High-risk AI systems shall be designed and developed in such a way that they can be effectively overseen by natural persons during their use to prevent risks.", "source_url": "https://example.eu/ai-act", "retrieved_at": "2026-05-01", "applicable_workflows": ["fraud detection"]}\n',
        encoding="utf-8",
    )
    return corpus


def test_guard_preserves_grounded_citation(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus_path: Path,
) -> None:
    """A cite whose (short_name, clause_id) is in the search result survives."""
    from sentinel.tools import regulatory_search as tool_mod
    from sentinel.regulatory.search import RegulatorySearch

    # Replace the module-level instance with one pointing at the fixture corpus
    # and stub the embedder to deterministic similarity.
    fixture_search = RegulatorySearch.from_corpus(fixture_corpus_path)
    monkeypatch.setattr(tool_mod, "regulatory_search", fixture_search)
    # Mirror change in the compliance officer module too (it imported the name).
    from sentinel.agents import compliance_officer as co_mod
    monkeypatch.setattr(co_mod, "regulatory_search", fixture_search)

    # Run a search to populate last_results.
    fixture_search.semantic_search("model ongoing monitoring", k=2)
    assert ("SR 11-7", "V") in fixture_search.last_results

    # Build a report citing that grounded clause.
    report = ComplianceReport(**_valid_report())
    guarded = validate_compliance_report(report)
    assert len(guarded.citations) == 1
    assert guarded.citations[0].regulation_short_name == "SR 11-7"
    assert guarded.no_applicable_regulations is False


def test_guard_strips_hallucinated_citation(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus_path: Path,
) -> None:
    """A cite whose tuple was NOT in the corpus search result is rejected
    and the report downgrades to the generic-guidance fallback.

    This is the ADR-019 disqualifier mitigation — the test that proves
    the contract.
    """
    from sentinel.tools import regulatory_search as tool_mod
    from sentinel.regulatory.search import RegulatorySearch

    fixture_search = RegulatorySearch.from_corpus(fixture_corpus_path)
    monkeypatch.setattr(tool_mod, "regulatory_search", fixture_search)
    from sentinel.agents import compliance_officer as co_mod
    monkeypatch.setattr(co_mod, "regulatory_search", fixture_search)

    fixture_search.semantic_search("model ongoing monitoring", k=2)

    # Construct a report with a HALLUCINATED cite — looks plausible, doesn't
    # exist in the corpus. The kind of thing a model might dream up from
    # training data.
    hallucinated = _valid_cite(reg="MADE UP ACT 2024", clause="§9999")
    report_dict = _valid_report()
    report_dict["citations"] = [hallucinated]
    report_dict["reporting_obligations"] = []
    report = ComplianceReport(**report_dict)

    guarded = validate_compliance_report(report)
    # Every citation was rejected → report MUST downgrade.
    assert guarded.citations == []
    assert guarded.no_applicable_regulations is True
    assert guarded.generic_guidance is not None
    assert "no specific regulation matched" in guarded.generic_guidance


def test_guard_preserves_mix_of_grounded_and_strips_hallucinated(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus_path: Path,
) -> None:
    """Mixed input: grounded cites survive, hallucinated cites stripped."""
    from sentinel.tools import regulatory_search as tool_mod
    from sentinel.regulatory.search import RegulatorySearch

    fixture_search = RegulatorySearch.from_corpus(fixture_corpus_path)
    monkeypatch.setattr(tool_mod, "regulatory_search", fixture_search)
    from sentinel.agents import compliance_officer as co_mod
    monkeypatch.setattr(co_mod, "regulatory_search", fixture_search)

    fixture_search.semantic_search("model ongoing monitoring", k=2)

    grounded = _valid_cite(reg="SR 11-7", clause="V")
    hallucinated = _valid_cite(reg="MADE UP ACT 2024", clause="§9999")
    report_dict = _valid_report()
    report_dict["citations"] = [grounded, hallucinated]
    report = ComplianceReport(**report_dict)

    guarded = validate_compliance_report(report)
    assert len(guarded.citations) == 1
    assert guarded.citations[0].regulation_short_name == "SR 11-7"
    assert guarded.no_applicable_regulations is False


def test_guard_drops_orphaned_reporting_obligation(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus_path: Path,
) -> None:
    """A reporting_obligation tied to a stripped citation is itself stripped."""
    from sentinel.tools import regulatory_search as tool_mod
    from sentinel.regulatory.search import RegulatorySearch

    fixture_search = RegulatorySearch.from_corpus(fixture_corpus_path)
    monkeypatch.setattr(tool_mod, "regulatory_search", fixture_search)
    from sentinel.agents import compliance_officer as co_mod
    monkeypatch.setattr(co_mod, "regulatory_search", fixture_search)

    fixture_search.semantic_search("model ongoing monitoring", k=2)

    grounded = _valid_cite(reg="SR 11-7", clause="V")
    report_dict = _valid_report()
    report_dict["citations"] = [grounded]
    # Reporting obligation references BOTH the grounded clause AND a phantom.
    report_dict["reporting_obligations"] = [
        {
            "regulator": "Federal Reserve",
            "timeframe_days": 30,
            "triggered_by_clauses": ["V", "PHANTOM-9"],
            "draft_notification_headline": "Material model performance deviation detected and contained.",
        }
    ]
    report = ComplianceReport(**report_dict)

    guarded = validate_compliance_report(report)
    # Grounded cite survives.
    assert len(guarded.citations) == 1
    # The obligation referenced PHANTOM-9 which isn't a grounded clause → dropped.
    assert guarded.reporting_obligations == []


# ── Search tool corpus loading + workflow filter ─────────────────────────


def test_search_loads_default_corpus() -> None:
    """The default corpus path resolves to the shipped JSONL file with >0 entries."""
    from sentinel.regulatory.search import RegulatorySearch
    search = RegulatorySearch.from_corpus()
    assert len(search._records) >= 10


def test_search_workflow_filter_excludes_non_matching(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus_path: Path,
) -> None:
    """workflow_filter excludes clauses whose applicable_workflows list
    doesn't contain the filter value.
    """
    from sentinel.regulatory.search import RegulatorySearch

    search = RegulatorySearch.from_corpus(fixture_corpus_path)
    # Both fixture entries declare "fraud detection" → both candidates.
    matches = search.semantic_search(
        "model ongoing monitoring", k=5, workflow_filter="fraud detection"
    )
    assert len(matches) == 2
    # No fixture entry declares "lending / credit underwriting" → 0 candidates.
    matches = search.semantic_search(
        "model ongoing monitoring", k=5,
        workflow_filter="lending / credit underwriting",
    )
    assert matches == []
