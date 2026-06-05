"""ComplianceOfficerAgent — Phase 8 / ADR-019.

Runs after PostmortemAgent. Reads the validated postmortem JSON, calls
the ``search_regulations`` tool against the curated corpus, and emits a
``ComplianceReport`` with the citations + reporting obligations.

The post-LLM hallucination guard lives in
``validate_compliance_report`` — the orchestrator calls it after the
agent returns. Citations whose ``(regulation_short_name, clause_id)``
tuple did NOT appear in the most recent ``RegulatorySearch`` results
are stripped and the report is downgraded to the generic-guidance
fallback. This is the ADR-019 disqualifier-mitigation in code.
"""

from __future__ import annotations

import logging

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from sentinel.agents.schemas import ComplianceReport
from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.prompts import load_prompt
from sentinel.tools.regulatory_search import (
    regulatory_search,
    search_regulations,
)

_logger = logging.getLogger(__name__)

# Temperature 0.0 — citation reasoning must be as deterministic as the
# LLM allows. We want the same incident to produce the same cite set.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.0)


compliance_officer = LlmAgent(
    name="compliance_officer",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("compliance_officer"),
    description=(
        "Specialist sub-agent that identifies regulator clauses "
        "applicable to an incident and drafts the reporting obligation "
        "block. Uses search_regulations against a curated corpus (SR "
        "11-7, OCC 2011-12, EU AI Act 9/14/15/26, NIST AI RMF, FFIEC, "
        "FCA SS1/23, FCA SUP 15.3, EU 5MLD, ECOA Reg B) and emits a "
        "ComplianceReport JSON. Every citation is grounded in the "
        "corpus — hallucinated cites are rejected by a post-LLM "
        "validator and replaced with the generic-guidance fallback. "
        "Coordinator routes to this agent on phrases like 'regulatory "
        "exposure', 'compliance', 'reporting obligation'."
    ),
    tools=[FunctionTool(func=search_regulations)],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)


# ── Post-LLM hallucination guard ──────────────────────────────────────────


def validate_compliance_report(report: ComplianceReport) -> ComplianceReport:
    """Strip any citation that did not appear in the most recent search.

    Returns either the input report (when every citation is grounded)
    OR a downgraded report with ``no_applicable_regulations=True`` and
    a fallback ``generic_guidance`` string when every citation failed
    the guard.

    ADR-019: this is the enforcement of the "hallucinated cites are a
    disqualifier" promise. The schema enforces shape; this enforces
    content traceability to the corpus.
    """
    grounded_citations = []
    rejected_keys: list[tuple[str, str]] = []
    for c in report.citations:
        if regulatory_search.is_citation_grounded(
            c.regulation_short_name, c.clause_id
        ):
            grounded_citations.append(c)
        else:
            rejected_keys.append((c.regulation_short_name, c.clause_id))

    if rejected_keys:
        _logger.warning(
            "ComplianceOfficer hallucinated %d citation(s) not in corpus "
            "search result: %r. These are stripped per ADR-019.",
            len(rejected_keys), rejected_keys,
        )

    # Strip reporting obligations that referenced rejected clauses.
    grounded_clause_ids = {c.clause_id for c in grounded_citations}
    grounded_obligations = [
        o for o in report.reporting_obligations
        if all(cid in grounded_clause_ids for cid in o.triggered_by_clauses)
    ]

    if not grounded_citations:
        # Every citation was rejected (or there were none to start) → fall
        # back to generic guidance. Use the agent's own fallback string if
        # it provided one, else emit a standard line.
        return ComplianceReport(
            incident_id=report.incident_id,
            citations=[],
            reporting_obligations=[],
            no_applicable_regulations=True,
            generic_guidance=(
                report.generic_guidance
                or "no specific regulation matched, generic guidance applied"
            ),
        )

    return ComplianceReport(
        incident_id=report.incident_id,
        citations=grounded_citations,
        reporting_obligations=grounded_obligations,
        no_applicable_regulations=False,
        generic_guidance=None,
    )
