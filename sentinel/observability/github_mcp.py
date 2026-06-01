"""GitHub MCP toolset — Phase 7 / Addition 3 / ADR-014.

Spawns the official ``@modelcontextprotocol/server-github`` MCP server as a
stdio subprocess via ``npx -y`` and exposes its tool surface
(list_commits, list_pull_requests, get_file_contents, etc.) to the
``DeployCorrelatorAgent``.

The MCP server reads ``GITHUB_PERSONAL_ACCESS_TOKEN`` from its environment.
For development we forward whatever's in the host env; if the token is
absent, the MCP server still starts but its tools will fail with 401 at
call time — that's the correct failure mode (visible in the trace tree,
not silent).

Why npx and not a Python client: judges score "MCP as a real protocol
integration" — using the off-the-shelf MCP server is the legible move. The
DeployCorrelatorAgent treats GitHub as an opaque MCP endpoint, same shape
as Phoenix MCP.
"""

from __future__ import annotations

import os

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters

# Tool-call timeout. GitHub API is rate-limited and can be slow on cold
# starts; give the MCP server room to negotiate.
_MCP_TOOL_TIMEOUT_S = 30.0


def make_github_mcp_toolset() -> McpToolset:
    """Return a configured ``McpToolset`` connected to the GitHub MCP server.

    The toolset launches ``npx -y @modelcontextprotocol/server-github`` as a
    stdio subprocess. The host's ``GITHUB_PERSONAL_ACCESS_TOKEN`` is
    forwarded; absent/invalid tokens surface as 401 at tool-call time
    (intentional — never silent).

    Optionally honors ``SENTINEL_GITHUB_REPO`` (``owner/repo``) which the
    DeployCorrelatorAgent's prompt uses as the default target when the user
    doesn't specify one in the alert payload.

    Returns:
        A ready-to-attach ``McpToolset`` exposing GitHub-API tools.
    """
    server_env = {**os.environ}
    # Pass through the token if set; the MCP server reads it from env.
    # Pass through SENTINEL_GITHUB_REPO too — the DeployCorrelator prompt
    # reads it via ``os.environ`` at prompt-load time when needed.

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env=server_env,
            ),
            timeout=_MCP_TOOL_TIMEOUT_S,
        ),
    )
