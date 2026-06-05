"""Tests for sentinel.regulatory.corpus_builder.

Validates the schema gates (required fields, URL prefix, min text length),
idempotent extension (duplicates skipped), and the JSONL append shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinel.regulatory.corpus_builder import (
    REQUIRED_FIELDS,
    extend_corpus,
)


def _full_entry() -> dict:
    return {
        "regulation_short_name": "TEST REG 1",
        "regulation_full_name": "Test Regulation 1 — Full Name",
        "clause_id": "1.A",
        "clause_title": "Test clause title",
        "clause_text": (
            "This is a sample clause text that is longer than the 50-character "
            "minimum required by the validator. It represents one regulator clause."
        ),
        "source_url": "https://example.gov/test-reg-1",
        "retrieved_at": "2026-05-01",
        "applicable_workflows": ["fraud detection"],
    }


def test_appends_new_entries(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([_full_entry()]))
    count = extend_corpus(manifest, corpus)
    assert count == 1
    lines = corpus.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["regulation_short_name"] == "TEST REG 1"


def test_skips_duplicate_entries(tmp_path: Path) -> None:
    """Same (regulation_short_name, clause_id) tuple is idempotent."""
    corpus = tmp_path / "corpus.jsonl"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([_full_entry(), _full_entry()]))
    count = extend_corpus(manifest, corpus)
    # Both manifest entries are duplicates of each other → only one written.
    assert count == 1


def test_skip_when_entry_already_in_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps(_full_entry()) + "\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([_full_entry()]))
    count = extend_corpus(manifest, corpus)
    assert count == 0


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    manifest = tmp_path / "manifest.json"
    bad = _full_entry()
    del bad["source_url"]
    manifest.write_text(json.dumps([bad]))
    with pytest.raises(ValueError, match="missing required field"):
        extend_corpus(manifest, corpus)


def test_short_clause_text_rejected(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    manifest = tmp_path / "manifest.json"
    bad = _full_entry()
    bad["clause_text"] = "too short"
    manifest.write_text(json.dumps([bad]))
    with pytest.raises(ValueError, match="clause_text"):
        extend_corpus(manifest, corpus)


def test_non_http_source_url_rejected(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    manifest = tmp_path / "manifest.json"
    bad = _full_entry()
    bad["source_url"] = "/local/path/to/file.pdf"
    manifest.write_text(json.dumps([bad]))
    with pytest.raises(ValueError, match="source_url"):
        extend_corpus(manifest, corpus)


def test_required_fields_constant_is_complete() -> None:
    """Sanity check that the constants list matches what an entry contains."""
    entry = _full_entry()
    for field in REQUIRED_FIELDS:
        assert field in entry, f"REQUIRED_FIELDS contains {field!r} but _full_entry has no such key"
