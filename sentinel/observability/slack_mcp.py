"""Slack MCP toolset — Phase 7 / ADR-015 reversal.

Spawns the official ``@modelcontextprotocol/server-slack`` MCP server as a
stdio subprocess via ``npx -y`` and exposes its tool surface
(slack_post_message, slack_list_channels, slack_get_thread_replies, etc.)
to the ``SlackAnnouncerAgent`` and to any future Slack-integrated agent.

The MCP server reads ``SLACK_BOT_TOKEN`` and ``SLACK_TEAM_ID`` from its
environment. Optionally honors ``SLACK_CHANNEL_IDS`` (comma-separated) to
constrain which channels the bot can read/write.

Why npx and not a Python Slack SDK: same rationale as GitHub MCP (ADR-014)
— the "MCP as a real protocol integration" judging signal. The
SlackAnnouncerAgent treats Slack as an opaque MCP endpoint, same shape as
Phoenix and GitHub MCPs.
"""

from __future__ import annotations

import os

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters

# Tool-call timeout. Slack's API is fast (<1s typical) but cold-start
# token validation + workspace lookup adds latency on first call.
_MCP_TOOL_TIMEOUT_S = 20.0


def make_slack_mcp_toolset() -> McpToolset:
    """Return a configured ``McpToolset`` connected to the Slack MCP server.

    Launches ``npx -y @modelcontextprotocol/server-slack`` as a stdio
    subprocess. Required env: ``SLACK_BOT_TOKEN`` (xoxb-…) and
    ``SLACK_TEAM_ID`` (T…). Without these set, the MCP server starts but
    tool calls fail at runtime — intentional, visible in the trace tree,
    never silent.

    Returns:
        A ready-to-attach ``McpToolset`` exposing Slack tools.
    """
    server_env = {**os.environ}

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-slack"],
                env=server_env,
            ),
            timeout=_MCP_TOOL_TIMEOUT_S,
        ),
    )


# Public constants the orchestrator and agent prompts reference. Centralized
# so changes (renaming the channel, raising the ack timeout) don't require
# greping the codebase.

# Default channel ID for incident broadcasts when the alert payload doesn't
# carry one. Operators set this in .env to map Sentinel to their incident
# channel (e.g. #sre-alerts). Falls back to a placeholder that the
# announcer agent surfaces as a "not configured" verdict.
DEFAULT_INCIDENT_CHANNEL_ENV: str = "SENTINEL_SLACK_CHANNEL_ID"

# When set to a truthy value in env, the orchestrator pauses the pipeline
# after PostmortemAgent drafts but before the postmortem is finalized,
# posts the draft to Slack with an interactive ack request, and waits up
# to ``SENTINEL_SLACK_ACK_TIMEOUT_S`` seconds for a human acknowledgment.
# Non-blocking by default (no gate) per the original brief.
ACK_GATE_ENABLED_ENV: str = "SENTINEL_SLACK_ACK_GATE"
ACK_GATE_TIMEOUT_ENV: str = "SENTINEL_SLACK_ACK_TIMEOUT_S"
ACK_GATE_TIMEOUT_DEFAULT_S: int = 300  # 5 minutes
