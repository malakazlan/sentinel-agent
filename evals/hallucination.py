"""Hallucination eval — LLM-as-judge over Coordinator outputs.

The eval checks whether the Coordinator's final response stayed faithful to
the data its tool returned, or fabricated specific claims (numbers, statuses,
timestamps) beyond what the tool provided. The judge is a separate Gemini call
via google-genai (Vertex-routed); annotator_kind is ``LLM`` on the resulting
Phoenix annotation.

Out of scope: traces without a tool call (greetings, intros) are skipped —
there's no source-of-truth to compare against.

Public API:

- ``judge(tool_output, response)`` — pure single-call LLM-as-judge.
- ``evaluate_trace(trace_id)`` — fetch a trace from Phoenix, run the judge,
  write back an annotation. Returns ``None`` for skipped traces.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from google import genai
from google.genai import types
from phoenix.client import Client

from sentinel.constants import SUBAGENT_MODEL

ANNOTATION_NAME = "hallucination"
_DEFAULT_PROJECT = "sentinel"

_JUDGE_PROMPT = """You are evaluating whether an AI assistant's final response stayed faithful to the data its tool returned, or whether it hallucinated information beyond what the tool provided.

Tool output (the only data the assistant should reference):
---
{tool_output}
---

Assistant's final response:
---
{response}
---

Did the assistant introduce specific claims (numbers, status, timestamps, error counts, latencies) that are NOT supported by the tool output?

Classify as exactly one of these two labels and reply with the label only, no other text:
- faithful : response only restates or summarizes information present in the tool output
- hallucinated : response contains specific claims not derivable from the tool output
"""


def judge(tool_output: str, response: str) -> dict:
    """Run a single LLM-as-judge classification.

    Args:
        tool_output: The text the assistant was given (source of truth).
        response: The assistant's text to evaluate.

    Returns:
        ``{"label": "faithful"|"hallucinated"|"unknown", "score": 1.0|0.0|None,
        "explanation": str}``. ``unknown`` is returned if the judge replies
        with anything unparseable.
    """
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    result = client.models.generate_content(
        model=SUBAGENT_MODEL,
        contents=_JUDGE_PROMPT.format(tool_output=tool_output, response=response),
        config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=10),
    )
    raw = (result.text or "").strip().lower()
    if "faithful" in raw:
        return {
            "label": "faithful",
            "score": 1.0,
            "explanation": "Response stayed within the tool output.",
        }
    if "hallucinat" in raw:
        return {
            "label": "hallucinated",
            "score": 0.0,
            "explanation": "Response contained claims unsupported by the tool output.",
        }
    return {
        "label": "unknown",
        "score": None,
        "explanation": f"Judge returned unparseable text: {raw!r}",
    }


def evaluate_trace(trace_id: str, *, project: Optional[str] = None) -> Optional[dict]:
    """Run the hallucination eval on a single Phoenix trace and annotate it.

    Args:
        trace_id: Hex trace ID from a Phoenix span's ``context.trace_id``.
        project: Phoenix project name. Defaults to ``PHOENIX_PROJECT_NAME`` env
            var, then to ``"sentinel"``.

    Returns:
        ``{"trace_id": str, "label": str, "score": float|None, "explanation": str}``
        on success, or ``None`` if the trace has no tool call (eval not applicable)
        or the tool/root spans are missing required attributes.
    """
    project_name = project or os.environ.get("PHOENIX_PROJECT_NAME", _DEFAULT_PROJECT)
    client = Client()

    spans = client.spans.get_spans(
        project_identifier=project_name,
        trace_ids=[trace_id],
        limit=100,
    )
    tool_spans = [s for s in spans if s.get("span_kind") == "TOOL"]
    root_spans = [s for s in spans if not s.get("parent_id")]
    if not tool_spans or not root_spans:
        return None

    tool_output = _extract_tool_output(tool_spans[0])
    response = _extract_response_text(root_spans[0])
    if not tool_output or not response:
        return None

    verdict = judge(tool_output, response)
    if verdict["score"] is None:
        # Unknown — still record the annotation so it's not silently lost.
        client.spans.add_span_annotation(
            span_id=root_spans[0]["context"]["span_id"],
            annotation_name=ANNOTATION_NAME,
            annotator_kind="LLM",
            label=verdict["label"],
            explanation=verdict["explanation"],
            sync=True,
        )
    else:
        client.spans.add_span_annotation(
            span_id=root_spans[0]["context"]["span_id"],
            annotation_name=ANNOTATION_NAME,
            annotator_kind="LLM",
            label=verdict["label"],
            score=verdict["score"],
            explanation=verdict["explanation"],
            sync=True,
        )

    return {"trace_id": trace_id, **verdict}


def _extract_tool_output(tool_span: dict) -> str:
    """Pull the tool's textual result out of its ``output.value`` attribute."""
    raw = tool_span.get("attributes", {}).get("output.value", "")
    if not raw:
        return ""
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return str(raw)
    # ADK wraps tool returns in {"result": ...}.
    if isinstance(obj, dict) and "result" in obj:
        return str(obj["result"])
    return str(obj)


def _extract_response_text(root_span: dict) -> str:
    """Pull the assistant's final text from the root span's ``output.value``."""
    raw = root_span.get("attributes", {}).get("output.value", "")
    if not raw:
        return ""
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return str(raw)
    if isinstance(obj, dict):
        content = obj.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        joined = " ".join(t for t in texts if t)
        if joined:
            return joined
    return str(obj)
