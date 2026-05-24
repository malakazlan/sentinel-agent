"""Runtime enforcement of self-introspection directives (ADR-009).

Prompt-side MUST/MUST-NOT language is too soft for the dev model
(``gemini-2.5-flash-lite``) to honor reliably. This module enforces the
two demo-critical directives at the ADK callback layer, so plan
determinism does not depend on LLM instruction-following:

- ``enforce_first_route`` (``before_model_callback``) short-circuits the
  Coordinator's LLM on the first turn when ``first_route`` is set,
  returning a synthetic ``LlmResponse`` that contains a forced
  ``transfer_to_agent`` function call. ADK executes the transfer; the
  Coordinator's model never decides routing for that turn.

- ``enforce_skip_routes`` (``before_tool_callback``) intercepts
  ``transfer_to_agent`` calls whose target is in ``skip_routes`` and
  returns a "blocked by directive" tool result so the sub-agent never
  runs, regardless of what the LLM tried to do.

``must_eval_after`` remains prompt-driven for now (see
``07-known-issues.md``); it's a post-action directive that benefits more
from Gemini 3 (ADR-008 axis A) than from runtime enforcement.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.genai import types

from sentinel.memory.briefing import PriorContextBriefing

_FIRST_ROUTE_CONSUMED_KEY = "_first_route_consumed"


def _active_briefing(ctx: Any) -> Optional[PriorContextBriefing]:
    """Return the directive briefing on the callback context, if any."""
    state = getattr(ctx, "state", None)
    if state is None:
        return None
    raw = state.get("prior_context_briefing")
    return raw if isinstance(raw, PriorContextBriefing) else None


async def enforce_first_route(
    callback_context: Any,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """``before_model_callback`` — force a transfer when ``first_route`` is set.

    On the Coordinator's FIRST model turn of an invocation, if the active
    briefing's ``first_route`` names a sub-agent, return a synthetic
    ``LlmResponse`` containing a ``transfer_to_agent`` function call
    targeting that sub-agent. ADK uses the synthetic response in place of
    the real LLM call and executes the transfer.

    Subsequent model turns (e.g. final wrap-up after the sub-agent
    returns) proceed normally so the LLM can phrase the response.
    """
    briefing = _active_briefing(callback_context)
    if briefing is None:
        return None
    if briefing.first_route not in ("trace_analyzer", "eval_runner"):
        return None
    if callback_context.state.get(_FIRST_ROUTE_CONSUMED_KEY):
        return None

    callback_context.state[_FIRST_ROUTE_CONSUMED_KEY] = True
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="transfer_to_agent",
                        args={"agent_name": briefing.first_route},
                    ),
                ),
            ],
        ),
    )


async def enforce_skip_routes(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: Any,
) -> Optional[dict]:
    """``before_tool_callback`` — reject transfer to a sub-agent in ``skip_routes``.

    When the LLM emits a ``transfer_to_agent`` call whose target appears
    in the active briefing's ``skip_routes``, return a synthetic tool
    result reporting the block. The sub-agent never runs; the Coordinator
    sees the rejection and must phrase a response directly to the user
    citing the directive's evidence.

    ADK calls this with ``tool_context=``, not ``callback_context=`` — the
    kwarg name matters.
    """
    if tool.name != "transfer_to_agent":
        return None
    briefing = _active_briefing(tool_context)
    if briefing is None or not briefing.skip_routes:
        return None
    target = args.get("agent_name")
    if target not in briefing.skip_routes:
        return None
    reason = briefing.evidence.get(
        "skip_routes", "directive: route blocked by self-introspection policy"
    )
    return {
        "result": (
            f"Transfer to '{target}' BLOCKED by active skip_routes directive. "
            f"Reason: {reason} — respond directly to the user explaining this."
        ),
    }
