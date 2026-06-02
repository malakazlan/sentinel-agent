"""SlackAnnouncer sub-agent — Phase 7 / ADR-015 reversal.

LlmAgent wired to the Slack MCP toolset. Posts incident lifecycle events
to the configured channel (incident_started, postmortem_validated,
incident_failed). The orchestrator (``run_end_to_end_scenario``) invokes
this agent at the corresponding lifecycle boundaries when
``SENTINEL_SLACK_ENABLED=1`` is set.

See ``sentinel/prompts/slack_announcer.md`` for the prompt contract and
``sentinel/observability/slack_mcp.py`` for the MCP factory.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.observability.slack_mcp import make_slack_mcp_toolset
from sentinel.prompts import load_prompt

# Low temperature: announcer posts are templated; we want consistency, not
# creativity. Bot-speak is the goal.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.1)


slack_announcer = LlmAgent(
    name="slack_announcer",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("slack_announcer"),
    description=(
        "Specialist sub-agent that posts incident lifecycle events "
        "(incident_started, postmortem_validated, incident_failed) to a "
        "configured Slack channel via the Slack MCP server. Coordinator "
        "routes here on explicit triggers: 'post to slack', 'notify the "
        "team', 'announce the incident'. Orchestrator also invokes "
        "this agent automatically at lifecycle boundaries when "
        "SENTINEL_SLACK_ENABLED=1."
    ),
    tools=[make_slack_mcp_toolset()],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)
