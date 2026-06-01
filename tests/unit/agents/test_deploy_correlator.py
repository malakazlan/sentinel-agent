"""Tests for the DeployCorrelator sub-agent (ADR-014 / Phase 7 Addition 3).

The GitHub MCP server is npx-launched at agent-import time; we don't spin it
up in unit tests. Instead we assert on the agent's wiring (model, prompt,
toolset, transfer rules) — the actual GitHub queries are exercised in
end-to-end smoke tests when a GITHUB_PERSONAL_ACCESS_TOKEN is present.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset

from sentinel.agents.deploy_correlator import deploy_correlator
from sentinel.constants import SUBAGENT_MODEL


def test_deploy_correlator_is_an_llm_agent() -> None:
    assert isinstance(deploy_correlator, LlmAgent)
    assert deploy_correlator.name == "deploy_correlator"


def test_deploy_correlator_uses_subagent_model() -> None:
    # The agent's model attribute is the constant we set; flash-lite for
    # this routine query workload.
    assert deploy_correlator.model == SUBAGENT_MODEL


def test_deploy_correlator_includes_github_mcp_toolset() -> None:
    # The toolset must be present — without it the agent can't query GitHub.
    toolsets = [t for t in deploy_correlator.tools if isinstance(t, McpToolset)]
    assert len(toolsets) >= 1, (
        "deploy_correlator must include the GitHub MCP toolset in its tools"
    )


def test_deploy_correlator_disallows_transfers() -> None:
    # Specialist sub-agents are leaves; they don't peer-transfer or bubble
    # back. Matches the pattern in trace_analyzer, eval_runner etc.
    assert deploy_correlator.disallow_transfer_to_parent is True
    assert deploy_correlator.disallow_transfer_to_peers is True


def test_deploy_correlator_description_lists_explicit_triggers() -> None:
    # The Coordinator routes by matching trigger phrases in sub-agent
    # descriptions; if these change the routing breaks.
    desc = deploy_correlator.description.lower()
    assert "deploy" in desc
    assert "commit" in desc or "pull request" in desc or "pr" in desc


def test_deploy_correlator_prompt_loads_and_mentions_github() -> None:
    # Prompt files live in sentinel/prompts/ per Protocol §2. Load the
    # file content directly (not via the agent) so the test doesn't
    # depend on agent construction. If the prompt is missing this fails
    # loudly rather than the agent silently shipping a placeholder.
    from sentinel.prompts import load_prompt

    text = load_prompt("deploy_correlator")
    assert "GitHub" in text or "github" in text
    assert "DeployCorrelator" in text
