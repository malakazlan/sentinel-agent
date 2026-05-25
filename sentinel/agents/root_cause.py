"""RootCause sub-agent — Phase 4 step 1.

Specialist for proposing **ranked causal hypotheses** about recent failures,
grounded in available Phoenix trace data. Distinct responsibility from
TraceAnalyzer (which describes what happened) and EvalRunner (which scores
output quality): RootCause asks *why*.

Phase 4 baseline uses only ``get_recent_traces`` and is honest about what
signals it lacks (no deploy log, no prompt-version diff). Later steps may
add a real correlation tool against Phoenix MCP's ``list-prompt-versions``
to strengthen hypothesis ranking; for now the prompt requires explicit
acknowledgement of data gaps so users know where to invest investigation
effort next.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.prompts import load_prompt
from sentinel.tools.phoenix_traces import get_recent_traces

# Same low-temperature reasoning as the other sub-agents: causal hypotheses
# need to be reproducible across runs so a follow-up Remediation/Postmortem
# sees stable inputs.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)

root_cause = LlmAgent(
    name="root_cause",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("root_cause"),
    description=(
        "Specialist sub-agent for generating ranked causal hypotheses about "
        "recent failures, grounded in Phoenix trace data. Used when the user "
        "asks 'why did this happen' rather than 'what happened'."
    ),
    tools=[get_recent_traces],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)
