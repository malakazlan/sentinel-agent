"""CriticAgent — Phase 7 / Addition 4 / ADR-016.

Reads a draft Postmortem, scores it against the four-dimension rubric
(completeness, grounding, actionability, customer_impact), and emits a
``CritiqueResult`` JSON object. The orchestrator (``run_end_to_end_scenario``)
uses the score to decide whether to accept the postmortem or feed the
critique back to PostmortemAgent for one revision iteration. Max 2
iterations to bound cost.

The agent has NO tools — it operates purely on the postmortem text
provided in the user message. This keeps the rubric pure and prevents the
critic from inventing trace evidence that the postmortem can't be verified
against.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.prompts import load_prompt

# Temperature 0.0 for the critic: rubric application should be as
# deterministic as the LLM allows. Tested empirically — score drift across
# repeated calls drops sharply at T=0.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.0)


critic = LlmAgent(
    name="critic",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("critic"),
    description=(
        "Specialist sub-agent that scores draft postmortems against a "
        "four-dimension rubric (completeness, grounding, actionability, "
        "customer_impact) and emits a CritiqueResult JSON object. "
        "Orchestrator-only — Coordinator does not directly route to the "
        "critic; the end-to-end scenario runner invokes it after the "
        "postmortem stage. Max 2 refinement iterations bound the cost."
    ),
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)


# Default acceptance threshold. Postmortems scoring at or above this are
# accepted as-is; below triggers one revision iteration.
CRITIC_SCORE_THRESHOLD: float = 0.85

# Hard cap on revision iterations. The orchestrator stops after this many
# attempts regardless of score — bounds Vertex cost on unfixable drafts.
MAX_REFINEMENT_ITERATIONS: int = 2
