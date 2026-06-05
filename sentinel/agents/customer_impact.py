"""CustomerImpactQuantifier — Phase 8 / ADR-018.

Reads the alert payload + the scenario's ``impact_seed`` block + the
RootCauseAgent hypothesis, and emits a typed ``ImpactReport`` JSON
object. Slotted between ``root_cause`` and ``postmortem`` stages so the
final RCA renders a dollar figure + customer count in its header.

Why a discrete agent and not inline in PostmortemAgent: keeping
quantification separate (a) shows up as its own span in the Phoenix
trace tree so reviewers can verify the citation trail, (b) protects the
postmortem completeness score on the rendering dimension, (c) lets the
``audit_citation_lines`` field be enforced as a hard schema requirement
rather than a soft prompt instruction.

The agent has no tools — it reasons only from the user-provided seed +
payload + root_cause hypothesis. Tool-less is the right shape here
because tools would let it invent figures the seed didn't ground.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.prompts import load_prompt

# Temperature 0.1 for the quantifier: deterministic enough that the same
# inputs produce the same figures across replays (critical for the
# regression test surface), but with a tiny amount of variation so the
# caveat wording reads natural.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.1)


customer_impact_quantifier = LlmAgent(
    name="customer_impact_quantifier",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("customer_impact"),
    description=(
        "Specialist sub-agent that quantifies the financial + customer "
        "impact of an incident. Reads the alert payload, the scenario "
        "impact_seed block, and the RootCauseAgent hypothesis; emits an "
        "ImpactReport JSON object with dollars at risk, customers "
        "affected, transactions affected, estimated revenue loss, "
        "customer-trust delta, and per-claim audit citations. Runs "
        "between root_cause and postmortem stages so PostmortemAgent can "
        "embed the figures verbatim. Tool-less by design — quantifications "
        "must trace to the seed/payload, never to invented evidence."
    ),
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)
