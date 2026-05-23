"""Phase 0 hello-world Coordinator: a single LlmAgent that proves traces flow into Phoenix.

In later phases this module grows into the root agent that plans investigations and
dispatches to sub-agents via A2A. Right now it has one job: produce one OpenInference
span per invocation so the Phase 0 milestone gate can be verified visually.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from sentinel.prompts import load_prompt

_APP_NAME = "sentinel"
_USER_ID = "local-dev"
_MODEL = "gemini-2.5-flash"

coordinator = LlmAgent(
    name="coordinator",
    model=_MODEL,
    instruction=load_prompt("coordinator"),
    description=(
        "Sentinel root agent. In Phase 0, a hello-world. In later phases, plans "
        "investigations and delegates to sub-agents via A2A."
    ),
)

_session_service = InMemorySessionService()
_runner = Runner(
    agent=coordinator,
    app_name=_APP_NAME,
    session_service=_session_service,
)


async def run_coordinator(user_text: str) -> str:
    """Invoke the Coordinator on a single user message and return its final reply.

    Creates a fresh session per call — no cross-turn memory in Phase 0. Memory
    is added in Phase 3 via Phoenix MCP self-introspection.

    Args:
        user_text: Raw input from the UI.

    Returns:
        The Coordinator's final-response text, or an empty string if the model
        produced no textual final response.
    """
    session = await _session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
    )
    message = types.Content(role="user", parts=[types.Part(text=user_text)])

    final_text = ""
    async for event in _runner.run_async(
        session_id=session.id,
        user_id=_USER_ID,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text += part.text
    return final_text
