# Regulatory corpus — source curation + refresh policy

Phase 8 / ADR-019 ships Sentinel with a hand-curated regulatory corpus
that the ComplianceOfficerAgent uses to cite obligations. This file
documents the corpus contents, sources, and the refresh process.

The corpus lives at `data/regulatory/corpus.jsonl`. Each line is one
clause object. The full record shape is in
`sentinel/regulatory/corpus_builder.py` (`REQUIRED_FIELDS`).

## Regulations covered (seed corpus)

| Short name | Full title | Clauses indexed | Source |
|---|---|---|---|
| SR 11-7 | Federal Reserve Supervisory Guidance on Model Risk Management | III.A, V, VI | federalreserve.gov/supervisionreg/srletters/sr1107a1.pdf |
| OCC 2011-12 | OCC Supervisory Guidance on Model Risk Management | III | occ.gov/news-issuances/bulletins/2011/bulletin-2011-12.html |
| EU AI Act | Regulation (EU) 2024/1689 on Artificial Intelligence | Articles 9, 14, 15, 26 | eur-lex.europa.eu/eli/reg/2024/1689/oj |
| NIST AI RMF | NIST AI Risk Management Framework 1.0 (NIST AI 100-1) | MEASURE 2.7, MANAGE 4.1 | nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf |
| FFIEC AI | FFIEC IT Examination Handbook — Information Security (AI/ML supplemental) | Booklet IV.B | ithandbook.ffiec.gov |
| FCA SS1/23 | Bank of England / PRA SS1/23 — Model risk management principles | Principle 4 | bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss |
| FCA SUP 15.3 | FCA Handbook — Supervision Manual, Notifications | 15.3.11R | handbook.fca.org.uk/handbook/SUP/15/3.html |
| EU 5MLD | Directive (EU) 2018/843 — 5th Anti-Money Laundering Directive | Article 33 | eur-lex.europa.eu/eli/dir/2018/843/oj |
| ECOA Reg B | Equal Credit Opportunity Act — Regulation B (12 CFR 1002) | 1002.4 | consumerfinance.gov/rules-policy/regulations/1002/4/ |

Each entry's `retrieved_at` is `2026-05-01`. The seed reflects the
state of those documents as of that date.

## Reporting obligations encoded

Some clauses carry a `reporting_obligation` block consumed by
`ComplianceOfficerAgent` to draft regulator notification headlines:

| Regulator | Trigger | Timeframe |
|---|---|---|
| Federal Reserve / OCC primary supervisor | Material model performance degradation | 30 days |
| National supervisory authority (EU Member State, per EU AI Act Article 14) | Serious incident or malfunction breaching fundamental rights | 3 days |
| AI system provider + national supervisory authority (EU AI Act Article 26) | Use presenting risk to health/safety/fundamental rights | 3 days |
| Bank of England / PRA (FCA SS1/23 Principle 4) | Material breach of model performance thresholds | 14 days |
| Financial Conduct Authority (FCA SUP 15.3) | Any matter that could have a significant adverse impact on the firm's reputation or customer service | 1 day |
| National Financial Intelligence Unit (5MLD Article 33) | Material PEP screening FP/FN rate | 1 day |

## Refresh policy

The corpus is curated, not auto-fetched. Curated text protects
Sentinel from transcription drift and from regulator documents being
moved or paywalled — every entry carries a `source_url` so the
operator can verify wording against the live document at any time.

Refresh cadence:

- **Annual review of every entry's `retrieved_at`.** Walk the source
  URLs; if the document has been re-issued (re-numbered clauses,
  updated text), update the affected JSONL entries via
  `python -m sentinel.regulatory.corpus_builder --manifest new.json`.
- **Quarterly check of EU AI Act + FCA pages** — these regulators
  publish amendments more frequently than the US-side regulators.
- **Ad-hoc** when ADR-019 is amended or a new workflow (asset
  management, payments) is added to a Scenario's
  `applicable_workflows`.

## Extending the corpus

Author a manifest JSON file with the same schema as a corpus entry
(see `REQUIRED_FIELDS` in `corpus_builder.py`):

```json
[
  {
    "regulation_short_name": "NEW REG",
    "regulation_full_name": "Full title here",
    "clause_id": "Article X",
    "clause_title": "Title here",
    "clause_text": "Verbatim clause text — at least 50 characters, transcribed accurately from the source document.",
    "source_url": "https://regulator.example/document",
    "retrieved_at": "YYYY-MM-DD",
    "applicable_workflows": ["fraud detection", "lending / credit underwriting"]
  }
]
```

Run:

```bash
python -m sentinel.regulatory.corpus_builder --manifest path/to/new.json
```

The builder validates every entry (required fields, URL scheme, text
length floor) and rejects duplicates against the existing corpus
(`(regulation_short_name, clause_id)` is the dedup key). Entries that
pass validation are appended to `data/regulatory/corpus.jsonl`.

## Why hand-curated

Auto-fetching regulator PDFs is unreliable: paywalls, javascript
rendering, document numbering changes across versions. The
ComplianceOfficerAgent is one bad clause-text excerpt away from a
hallucinated cite that fails the disqualifier guard, so the seed
corpus is hand-curated and the builder is structured around manifest
JSON files that the operator (or a supervised batch agent) authors
against the live source URL.
