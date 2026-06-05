"""Regulatory corpus extension tool.

Phase 8 / ADR-019. The corpus at ``data/regulatory/corpus.jsonl`` is the
single source of truth for what the ComplianceOfficerAgent may cite.
This builder lets an operator extend the corpus from a JSON manifest of
new clauses without modifying the JSONL by hand.

Run via:

    python -m sentinel.regulatory.corpus_builder \\
        --manifest path/to/new_clauses.json

Each manifest entry must include ``regulation_short_name``, ``clause_id``,
``clause_text``, and ``source_url``. The builder validates the schema,
checks for duplicate ``(regulation_short_name, clause_id)`` pairs against
the existing corpus, and appends in JSONL form.

Why human-curated rather than auto-fetched: every entry is what the
ComplianceOfficerAgent can later cite to a regulator. Auto-extracted
text from PDFs introduces transcription drift; a human-curated copy
with a documented ``source_url`` and ``retrieved_at`` date is the safer
posture for a financial-services compliance feature.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# Schema fields every manifest entry must have.
REQUIRED_FIELDS: tuple[str, ...] = (
    "regulation_short_name",
    "regulation_full_name",
    "clause_id",
    "clause_title",
    "clause_text",
    "source_url",
    "retrieved_at",
    "applicable_workflows",
)


def _load_existing_corpus(corpus_path: Path) -> list[dict[str, Any]]:
    """Read the existing JSONL corpus into a list of dicts."""
    if not corpus_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with corpus_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _validate_entry(entry: dict[str, Any]) -> list[str]:
    """Return a list of validation errors; empty list = valid."""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in entry:
            errors.append(f"missing required field {field!r}")
    if "applicable_workflows" in entry and not isinstance(
        entry["applicable_workflows"], list
    ):
        errors.append("applicable_workflows must be a list of strings")
    if "clause_text" in entry and len(entry["clause_text"]) < 50:
        errors.append("clause_text too short (<50 chars) — likely truncated")
    if "source_url" in entry and not str(entry["source_url"]).startswith(
        ("http://", "https://")
    ):
        errors.append("source_url must be an http(s) URL")
    return errors


def extend_corpus(manifest_path: Path, corpus_path: Path) -> int:
    """Append all validated entries from ``manifest_path`` to ``corpus_path``.

    Returns the count of entries appended. Skips entries whose
    ``(regulation_short_name, clause_id)`` already appears in the
    corpus (idempotent extension).
    """
    with manifest_path.open("r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    if not isinstance(manifest, list):
        raise ValueError(
            "manifest must be a JSON list of clause objects; "
            f"got {type(manifest).__name__}"
        )

    existing = _load_existing_corpus(corpus_path)
    seen: set[tuple[str, str]] = {
        (r["regulation_short_name"], r["clause_id"]) for r in existing
    }

    to_append: list[dict[str, Any]] = []
    for i, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest entry {i} is not an object")
        errors = _validate_entry(entry)
        if errors:
            raise ValueError(
                f"manifest entry {i} failed validation: {errors}"
            )
        key = (entry["regulation_short_name"], entry["clause_id"])
        if key in seen:
            _logger.info(
                "Skipping duplicate clause (%s, %s) — already in corpus",
                *key,
            )
            continue
        seen.add(key)
        to_append.append(entry)

    if not to_append:
        return 0

    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    with corpus_path.open("a", encoding="utf-8") as fp:
        for entry in to_append:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(to_append)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append validated regulatory clauses to the Sentinel corpus."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to a JSON file containing a list of clause objects.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/regulatory/corpus.jsonl"),
        help="Target corpus JSONL (default: data/regulatory/corpus.jsonl).",
    )
    args = parser.parse_args(argv)

    appended = extend_corpus(args.manifest, args.corpus)
    print(f"Appended {appended} entries to {args.corpus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
