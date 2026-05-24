"""Phase 1 baseline Coordinator: a single LlmAgent with one observability tool.

Exposes two entry points:

- ``stream_coordinator(text)`` — async generator yielding structured event
  records (tool calls, tool results, final text). Used by the Streamlit UI to
  populate the agent-reasoning sidebar.
- ``run_coordinator(text)`` — convenience wrapper that drains the stream and
  returns the final response text. Used by smoke tests and any caller that
  only wants the final answer.

Both share the same module-level ``Runner`` + ``InMemorySessionService`` and
go through the OpenInference instrumentor wired in
``sentinel.observability.instrumentation``.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from sentinel.agents.eval_runner import eval_runner
from sentinel.agents.trace_analyzer import trace_analyzer
from sentinel.constants import COORDINATOR_MODEL
from sentinel.prompts import load_prompt
from sentinel.tools.phoenix_traces import get_recent_traces

_APP_NAME = "sentinel"
_USER_ID = "local-dev"
_RESULT_EXCERPT_CHARS = 280

# Low temperature: tool-calling decisions should be near-deterministic. Default
# Gemini temperature (~1.0) made the model sometimes greet instead of calling
# the tool on the first turn — Phase 1 demands consistent tool use.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)

coordinator = LlmAgent(
    name="coordinator",
    model=COORDINATOR_MODEL,
    instruction=load_prompt("coordinator"),
    description=(
        "Sentinel root agent. In Phase 2, routes between a direct tool call for "
        "quick lookups, the TraceAnalyzer sub-agent (deep statistical analysis), "
        "and the EvalRunner sub-agent (quality evaluators). In later phases, "
        "adds RootCause, Remediation, and Postmortem sub-agents."
    ),
    tools=[get_recent_traces],
    sub_agents=[trace_analyzer, eval_runner],
    generate_content_config=_GENERATE_CONFIG,
)

_session_service = InMemorySessionService()
_runner = Runner(
    agent=coordinator,
    app_name=_APP_NAME,
    session_service=_session_service,
)


async def stream_coordinator(user_text: str) -> AsyncIterator[dict]:
    """Yield structured event records as the Coordinator processes ``user_text``.

    Each record is a small JSON-serializable dict with a ``kind`` field:

    - ``{"kind": "tool_call", "tool": str, "args": dict}``
    - ``{"kind": "tool_result", "tool": str, "result_excerpt": str}``
    - ``{"kind": "assistant_text", "text": str}`` (intermediate model text, rare)
    - ``{"kind": "final", "text": str}`` (the last response chunk)

    Creates a fresh session per call — no cross-turn memory in Phase 1.

    Args:
        user_text: Raw input from the UI.

    Yields:
        Event records in the order they are emitted by the ADK runner.
    """
    session = await _session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
    )
    message = types.Content(role="user", parts=[types.Part(text=user_text)])

    async for event in _runner.run_async(
        session_id=session.id,
        user_id=_USER_ID,
        new_message=message,
    ):
        for record in _summarize_event(event):
            yield record


async def run_coordinator(user_text: str) -> str:
    """Invoke the Coordinator and return only the final text.

    Convenience wrapper over ``stream_coordinator`` for callers that don't
    need the intermediate event log.
    """
    final_text = ""
    async for record in stream_coordinator(user_text):
        if record["kind"] == "final":
            final_text += record["text"]
    return final_text


def _summarize_event(event: Any) -> list[dict]:
    """Convert one ADK ``Event`` into zero or more UI-facing records.

    Walks ``event.content.parts`` and emits a record per meaningful part:
    function calls, function responses, and text. Each record carries the
    emitting agent in ``author`` (e.g. ``"coordinator"`` or ``"trace_analyzer"``)
    so the UI can group reasoning by agent. Returns an empty list for events
    with no displayable content (e.g. action-only events).
    """
    if not event.content or not event.content.parts:
        return []

    is_final = event.is_final_response()
    author = getattr(event, "author", "") or "unknown"
    records: list[dict] = []
    for part in event.content.parts:
        if getattr(part, "function_call", None) is not None:
            fc = part.function_call
            records.append(
                {
                    "kind": "tool_call",
                    "author": author,
                    "tool": fc.name,
                    "args": _normalize_args(fc.args),
                }
            )
        elif getattr(part, "function_response", None) is not None:
            fr = part.function_response
            records.append(
                {
                    "kind": "tool_result",
                    "author": author,
                    "tool": fr.name,
                    "result_excerpt": _excerpt(fr.response),
                }
            )
        elif getattr(part, "text", None):
            records.append(
                {
                    "kind": "final" if is_final else "assistant_text",
                    "author": author,
                    "text": part.text,
                }
            )
    return records


def _normalize_args(args: Any) -> dict:
    """Coerce a proto MapComposite (or already-dict args) to a plain dict."""
    if args is None:
        return {}
    try:
        return {k: v for k, v in args.items()}
    except (AttributeError, TypeError):
        return {"_raw": str(args)}


def _excerpt(response: Any, max_chars: int = _RESULT_EXCERPT_CHARS) -> str:
    """Stringify and truncate a tool response for sidebar display."""
    if response is None:
        return ""
    text = str(response)
    return text if len(text) <= max_chars else text[:max_chars] + "…"
