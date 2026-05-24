"""Phoenix MCP toolset — Phase 3 self-improvement-loop foundation.

Spawns the official ``@arizeai/phoenix-mcp`` server as a stdio subprocess via
``npx -y`` and exposes its tool surface (list-projects, get-prompts, etc.) to
the Coordinator. Phase 3 step 1 just plumbs the connection; the actual
self-introspection-at-session-start logic lands in step 2.

The Phoenix MCP server reads ``PHOENIX_BASE_URL`` and ``PHOENIX_API_KEY`` from
its environment. For our self-hosted Phoenix (ADR-003), the URL is the same
``localhost:6006`` and there is no API key.
"""

from __future__ import annotations

import os

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters

_DEFAULT_PHOENIX_URL = "http://localhost:6006"
# Tool-call timeout for MCP requests. Phoenix MCP queries hit our local
# Phoenix backend which is fast (<200 ms typical), but a few seconds of
# headroom protects against cold-start span fetches.
_MCP_TOOL_TIMEOUT_S = 15.0


def make_phoenix_mcp_toolset() -> McpToolset:
    """Return a configured ``McpToolset`` connected to the Phoenix MCP server.

    The toolset launches ``npx -y @arizeai/phoenix-mcp`` as a stdio subprocess
    and forwards ``PHOENIX_COLLECTOR_ENDPOINT`` (our self-hosted Phoenix URL)
    as ``PHOENIX_BASE_URL`` — the env var the MCP server actually reads.

    Returns:
        A ready-to-attach ``McpToolset`` whose tools (``list-projects``,
        ``get-prompts``, ``list-experiments``, etc.) become directly callable
        by any ``LlmAgent`` that includes the toolset in its ``tools=[...]``.
    """
    phoenix_url = os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", _DEFAULT_PHOENIX_URL
    ).rstrip("/")

    server_env = {
        **os.environ,
        "PHOENIX_BASE_URL": phoenix_url,
    }

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@arizeai/phoenix-mcp"],
                env=server_env,
            ),
            timeout=_MCP_TOOL_TIMEOUT_S,
        ),
    )
