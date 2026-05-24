"""TraceAnalyzer sub-agent — Phase 2.

Specialist for deep statistical analysis of Phoenix traces. Coordinator
transfers to TraceAnalyzer (via ADK A2A) when the user asks for more than a
one-line summary. Reuses the ``get_recent_traces`` tool — Phase 2 step 1 is
about proving A2A wire-up, not adding new capabilities. New analysis tools
arrive when there's a concrete need.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.prompts import load_prompt
from sentinel.tools.phoenix_traces import get_recent_traces

# Same low-temperature reasoning as the Coordinator: analysis outputs need to
# be reproducible across runs so judges and evals see consistent numbers.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)

trace_analyzer = LlmAgent(
    name="trace_analyzer",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("trace_analyzer"),
    description=(
        "Specialist sub-agent for deep statistical analysis of recent Phoenix "
        "traces — volume, success rate, latency distribution, failure clustering, "
        "concrete recommendations. Coordinator transfers to this agent when a "
        "user wants depth beyond a one-line summary."
    ),
    tools=[get_recent_traces],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
