"""ParallelEvalRunner — ADK ParallelAgent fan-out over the four code-eval
suites (Phase 7 / Addition 1 / ADR-012).

Architecture:

    parallel_eval_runner (SequentialAgent)
    ├── parallel_fanout (ParallelAgent)
    │   ├── faithfulness_evaluator (LlmAgent) → state["faithfulness_result"]
    │   ├── drift_evaluator (LlmAgent)        → state["drift_result"]
    │   ├── prompt_injection_evaluator        → state["prompt_injection_result"]
    │   └── toxicity_evaluator                → state["toxicity_result"]
    └── eval_summarizer (LlmAgent)
        consumes the four state slots and emits a single Markdown verdict.

The four leaves run concurrently via ADK's ParallelAgent — the span tree
shows the fan-out and the wall-clock improvement is visible in Phoenix.

Coordinator routes here when the user asks for a full eval sweep ("run all
evals", "fan out evals", "full evaluation"). The single-suite `eval_runner`
(`sentinel/agents/eval_runner.py`) remains for one-off hallucination calls.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.genai import types

from sentinel.constants import SUBAGENT_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.tools.run_eval import (
    run_drift_eval,
    run_faithfulness_eval,
    run_prompt_injection_eval,
    run_toxicity_eval,
)

_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.0)


# ── Leaf evaluators ────────────────────────────────────────────────────────

faithfulness_evaluator = LlmAgent(
    name="faithfulness_evaluator",
    model=SUBAGENT_MODEL,
    instruction=(
        "Call `run_faithfulness_eval` exactly once with hours_back=1 and "
        "limit=10, then return its Markdown summary verbatim. Do not add "
        "commentary, do not call any other tool."
    ),
    description="Runs the faithfulness code-eval over recent spans.",
    tools=[run_faithfulness_eval],
    output_key="faithfulness_result",
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)

drift_evaluator = LlmAgent(
    name="drift_evaluator",
    model=SUBAGENT_MODEL,
    instruction=(
        "Call `run_drift_eval` exactly once with hours_back=1 and limit=25, "
        "then return its Markdown summary verbatim. Do not add commentary."
    ),
    description="Runs the drift code-eval over recent spans.",
    tools=[run_drift_eval],
    output_key="drift_result",
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)

prompt_injection_evaluator = LlmAgent(
    name="prompt_injection_evaluator",
    model=SUBAGENT_MODEL,
    instruction=(
        "Call `run_prompt_injection_eval` exactly once with hours_back=1 and "
        "limit=10, then return its Markdown summary verbatim. Do not add "
        "commentary."
    ),
    description="Scans recent span inputs for prompt-injection signatures.",
    tools=[run_prompt_injection_eval],
    output_key="prompt_injection_result",
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)

toxicity_evaluator = LlmAgent(
    name="toxicity_evaluator",
    model=SUBAGENT_MODEL,
    instruction=(
        "Call `run_toxicity_eval` exactly once with hours_back=1 and "
        "limit=10, then return its Markdown summary verbatim. Do not add "
        "commentary."
    ),
    description="Runs the toxicity code-eval over recent spans.",
    tools=[run_toxicity_eval],
    output_key="toxicity_result",
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)


# ── Parallel fan-out ───────────────────────────────────────────────────────

parallel_fanout = ParallelAgent(
    name="parallel_fanout",
    sub_agents=[
        faithfulness_evaluator,
        drift_evaluator,
        prompt_injection_evaluator,
        toxicity_evaluator,
    ],
    description=(
        "Runs the four eval suites concurrently. Each leaf writes its result "
        "to session state under its declared output_key."
    ),
)


# ── Summarizer ─────────────────────────────────────────────────────────────

eval_summarizer = LlmAgent(
    name="eval_summarizer",
    model=SUBAGENT_MODEL,
    instruction=(
        "You are composing a single concise Markdown summary that aggregates "
        "four eval verdicts. The verdicts are available in session state as:\n"
        "- faithfulness_result: {faithfulness_result}\n"
        "- drift_result: {drift_result}\n"
        "- prompt_injection_result: {prompt_injection_result}\n"
        "- toxicity_result: {toxicity_result}\n\n"
        "Emit a single Markdown block with these sections, in order, each as "
        "a bold header followed by the verdict line:\n\n"
        "**Faithfulness:** <one line>\n"
        "**Drift:** <one line>\n"
        "**Prompt-injection:** <one line>\n"
        "**Toxicity:** <one line>\n\n"
        "Then a final **Overall:** line that flags any non-clean / non-stable / "
        "non-faithful verdicts as items to escalate. Do not call any tool."
    ),
    description="Composes the four parallel eval verdicts into a single summary.",
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)


# ── Public runner ──────────────────────────────────────────────────────────

parallel_eval_runner = SequentialAgent(
    name="parallel_eval_runner",
    sub_agents=[parallel_fanout, eval_summarizer],
    description=(
        "Runs the four eval suites in parallel (faithfulness, drift, "
        "prompt-injection, toxicity), then composes a single Markdown summary. "
        "Coordinator routes here on explicit triggers: 'run all evals', "
        "'fan out evals', 'full evaluation', 'parallel eval'."
    ),
)
