"""Tests for SlackAnnouncerAgent + the orchestrator's env-gated announce
helper (ADR-015 reversal / Phase 7).

Wiring is asserted statically; the orchestrator gate is exercised with
``SENTINEL_SLACK_ENABLED`` toggled both ways.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset

from sentinel.agents.slack_announcer import slack_announcer
from sentinel.constants import SUBAGENT_MODEL


# ── Agent wiring ─────────────────────────────────────────────────────────


def test_slack_announcer_is_an_llm_agent() -> None:
    assert isinstance(slack_announcer, LlmAgent)
    assert slack_announcer.name == "slack_announcer"


def test_slack_announcer_uses_subagent_model() -> None:
    assert slack_announcer.model == SUBAGENT_MODEL


def test_slack_announcer_includes_slack_mcp_toolset() -> None:
    toolsets = [t for t in slack_announcer.tools if isinstance(t, McpToolset)]
    assert len(toolsets) >= 1, (
        "slack_announcer must include the Slack MCP toolset in its tools"
    )


def test_slack_announcer_disallows_transfers() -> None:
    assert slack_announcer.disallow_transfer_to_parent is True
    assert slack_announcer.disallow_transfer_to_peers is True


def test_slack_announcer_description_lists_lifecycle_triggers() -> None:
    desc = slack_announcer.description.lower()
    assert "slack" in desc
    # Each of the three lifecycle event types it handles must be named so
    # the Coordinator's routing can match them.
    assert "incident_started" in desc
    assert "postmortem_validated" in desc
    assert "incident_failed" in desc


def test_slack_announcer_prompt_loads_and_documents_event_templates() -> None:
    from sentinel.prompts import load_prompt

    text = load_prompt("slack_announcer")
    assert "incident_started" in text
    assert "postmortem_validated" in text
    assert "incident_failed" in text
    assert "SENTINEL_SLACK_CHANNEL_ID" in text


# ── Orchestrator gate: SENTINEL_SLACK_ENABLED ─────────────────────────────


@pytest.mark.asyncio
async def test_announce_is_noop_when_env_flag_unset(monkeypatch) -> None:
    """The Slack announce helper must do nothing when the env flag is
    unset. Existing pipelines (and CI) stay clean by default."""
    from sentinel.coordinator import _maybe_announce_to_slack, EndToEndResult

    monkeypatch.delenv("SENTINEL_SLACK_ENABLED", raising=False)
    result = EndToEndResult(scenario_id="fraud-fp-burst")

    with patch("sentinel.coordinator._run_stage") as mock_stage:
        await _maybe_announce_to_slack(
            "incident_started", {"incident_id": "x"}, result
        )
    mock_stage.assert_not_called()
    assert result.stages == []


@pytest.mark.asyncio
async def test_announce_runs_stage_when_env_flag_set(monkeypatch) -> None:
    """When the env flag is set, the helper runs a `slack_<event_type>`
    stage and appends it to ``result.stages``."""
    from sentinel.coordinator import (
        _maybe_announce_to_slack,
        EndToEndResult,
        StageResult,
    )

    monkeypatch.setenv("SENTINEL_SLACK_ENABLED", "1")
    result = EndToEndResult(scenario_id="fraud-fp-burst")

    fake_stage = StageResult(name="slack_incident_started", prompt="x")
    fake_stage.latency_ms = 10
    fake_stage.final_text = "Posted incident_started notification."

    with patch(
        "sentinel.coordinator._run_stage", return_value=fake_stage
    ) as mock_stage:
        await _maybe_announce_to_slack(
            "incident_started",
            {"incident_id": "x", "severity": "P1"},
            result,
        )
    mock_stage.assert_called_once()
    # Verify the stage name follows the slack_<event> convention.
    args, _ = mock_stage.call_args
    assert args[0] == "slack_incident_started"
    # The payload should appear in the prompt as JSON.
    assert '"incident_id"' in args[1]
    assert "slack_post_message" in args[1]
    # And the stage gets recorded for trace-tree visibility.
    assert len(result.stages) == 1


@pytest.mark.asyncio
async def test_announce_swallows_stage_exceptions(monkeypatch) -> None:
    """Comms failures must never block the pipeline. The helper catches
    any exception from `_run_stage` and continues."""
    from sentinel.coordinator import _maybe_announce_to_slack, EndToEndResult

    monkeypatch.setenv("SENTINEL_SLACK_ENABLED", "1")
    result = EndToEndResult(scenario_id="fraud-fp-burst")

    with patch(
        "sentinel.coordinator._run_stage",
        side_effect=RuntimeError("simulated MCP outage"),
    ):
        # Must not raise.
        await _maybe_announce_to_slack(
            "postmortem_validated", {"incident_id": "x"}, result
        )
    # No stage was appended because the call failed.
    assert result.stages == []
