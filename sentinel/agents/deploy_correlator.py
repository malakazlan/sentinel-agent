"""DeployCorrelator sub-agent — Phase 7 / Addition 3 / ADR-014.

LlmAgent that queries the GitHub MCP server for recent commits/PRs in the
window around an incident's onset, then surfaces likely change-induced
regressions. Coordinator transfers here when the user asks about deploys,
recent changes, or "what changed before this happened".

See ``sentinel/prompts/deploy_correlator.md`` for the prompt contract and
``sentinel/observability/github_mcp.py`` for the MCP factory.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.observability.github_mcp import make_github_mcp_toolset
from sentinel.prompts import load_prompt

_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)


deploy_correlator = LlmAgent(
    name="deploy_correlator",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("deploy_correlator"),
    description=(
        "Specialist sub-agent that queries the GitHub MCP server for recent "
        "commits and pull requests in the window around an incident's onset, "
        "and surfaces likely change-induced regressions. Coordinator routes "
        "here on explicit triggers: 'correlate with recent deploys', 'what "
        "changed before this', 'was this a recent commit', 'check recent "
        "PRs'."
    ),
    tools=[make_github_mcp_toolset()],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)
