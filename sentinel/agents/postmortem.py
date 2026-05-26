"""Postmortem sub-agent — Phase 4 step 3.

Produces a **structured Google-SRE-format ``Postmortem``** consumable by
ticketing systems, audit logs (FinServ compliance), wiki renderers, and the
``evals/completeness.py`` scorer.

Per the real-system-not-just-demo framing: the output is a strict JSON
object matching the Pydantic schema in ``sentinel.agents.schemas``. The
``completeness`` eval immediately scores how substantive the postmortem
is, and Phoenix sees both the postmortem trace AND the completeness
annotation — judges can audit the linkage.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.prompts import load_prompt
from sentinel.tools.phoenix_traces import get_recent_traces

# Low temperature: postmortems are records of truth — they must be stable
# across runs of the same incident context. Wiki / audit-log consumers
# expect reproducibility.
_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)

postmortem = LlmAgent(
    name="postmortem",
    model=SUBAGENT_MODEL,
    instruction=load_prompt("postmortem"),
    description=(
        "Specialist sub-agent for writing Google-SRE-format Postmortem JSON "
        "from incident context. Used when the user asks for an RCA, "
        "postmortem doc, or incident report."
    ),
    tools=[get_recent_traces],
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)
