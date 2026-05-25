"""Remediation sub-agent — Phase 4 step 2.

Takes incident context (typically a RootCause hypothesis + the original
alert payload) and drafts a **structured ``RemediationPlan``** consumable
by ticketing / paging systems and by the downstream Postmortem agent.

Per the real-system-not-just-demo framing: the output is a strict JSON
object matching the Pydantic schema in ``sentinel.agents.schemas``. Real
ops consumers depend on that contract, so the prompt is rigid about shape
and the schema validators reject malformed plans at construction time.

ADK ``output_schema`` would enforce structure at the SDK layer but
disables tool calls — we keep tools enabled (Remediation needs
``get_recent_traces`` to ground its plan in real evidence) and rely on
prompt-side discipline + receiver-side Pydantic validation.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.prompts import load_prompt
from sentinel.tools.phoenix_traces import get_recent_traces

# Low temperature: JSON output and remediation rationale must be stable so
# Postmortem and any ticketing-system consumer see consistent shape.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)

remediation = LlmAgent(
    name="remediation",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("remediation"),
    description=(
        "Specialist sub-agent for drafting structured RemediationPlan JSON "
        "from incident context. Used when the user asks for a fix, rollback "
        "recommendation, or remediation plan."
    ),
    tools=[get_recent_traces],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)
