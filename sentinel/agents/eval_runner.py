"""EvalRunner sub-agent — Phase 2 step 2.

Specialist for running evaluator suites against recent Phoenix traces.
Coordinator transfers here (via ADK A2A) when the user asks for a quality
check, hallucination eval, or any other named eval suite.

Phase 2 ships one suite (``run_hallucination_eval``); more arrive in later
phases.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.prompts import load_prompt
from sentinel.tools.run_eval import run_hallucination_eval

_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)

eval_runner = LlmAgent(
    name="eval_runner",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("eval_runner"),
    description=(
        "Specialist sub-agent for running quality evaluators against recent "
        "Phoenix traces. Phase 2 ships hallucination; later phases add "
        "toxicity, faithfulness, drift, jailbreak per CLAUDE.md §5."
    ),
    tools=[run_hallucination_eval],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
