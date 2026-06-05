"""CORS allow-list resolution for the FastAPI app.

Local dev origins are always included. Cloud Run / production passes
``SENTINEL_ALLOWED_ORIGINS`` (comma-separated) to whitelist the deployed
web origin so EventSource requests from the browser are not blocked.
"""

from __future__ import annotations

import pytest

from sentinel.api.main import _allowed_origins


def test_defaults_to_localhost_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTINEL_ALLOWED_ORIGINS", raising=False)
    origins = _allowed_origins()
    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins
    assert len(origins) == 2


def test_env_value_unioned_with_localhost_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production web origin coexists with dev origins so both paths keep working."""
    monkeypatch.setenv(
        "SENTINEL_ALLOWED_ORIGINS",
        "https://sentinel-web-586014642476.us-central1.run.app",
    )
    origins = _allowed_origins()
    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins
    assert "https://sentinel-web-586014642476.us-central1.run.app" in origins


def test_multiple_comma_separated_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SENTINEL_ALLOWED_ORIGINS",
        "https://a.example.com, https://b.example.com ,https://c.example.com",
    )
    origins = _allowed_origins()
    assert "https://a.example.com" in origins
    assert "https://b.example.com" in origins
    assert "https://c.example.com" in origins


def test_blank_and_whitespace_entries_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_ALLOWED_ORIGINS", " , ,https://only.example.com,  ")
    origins = _allowed_origins()
    assert "https://only.example.com" in origins
    assert "" not in origins
    assert " " not in origins


def test_duplicates_are_collapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """If someone re-adds localhost via the env var, don't double it."""
    monkeypatch.setenv(
        "SENTINEL_ALLOWED_ORIGINS",
        "http://localhost:3000,https://web.run.app",
    )
    origins = _allowed_origins()
    assert origins.count("http://localhost:3000") == 1
    assert "https://web.run.app" in origins
