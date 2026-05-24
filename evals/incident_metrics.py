"""Per-run incident metrics — Phase 3 step 3 demo measurement.

Extracts plan-shape metrics from a streamed Coordinator run so the
cold-vs-warm demo panel can show the delta visually:

- wall-clock latency
- number of tool calls (excluding ``transfer_to_agent``)
- number of sub-agent transfers
- ordered author path (which agents emitted records, in order)
- whether the active directive actually fired

The numbers come from records yielded by ``stream_coordinator``; latency is
caller-supplied (wall-clock around the streamed iteration). This module is
pure — no Phoenix or LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sentinel.memory.briefing import PriorContextBriefing


@dataclass
class IncidentRun:
    """Metrics + outputs for a single scripted Coordinator run."""

    label: str
    prompt: str
    latency_ms: int
    n_tool_calls: int
    n_transfers: int
    n_llm_calls: int = 0
    authors: list[str] = field(default_factory=list)
    final_text: str = ""
    directive_fired: bool = False
    briefing: Optional[PriorContextBriefing] = None

    @property
    def authors_unique(self) -> list[str]:
        """Author list preserving first-occurrence order, no duplicates."""
        seen: set[str] = set()
        ordered: list[str] = []
        for author in self.authors:
            if author and author not in seen:
                seen.add(author)
                ordered.append(author)
        return ordered

    @property
    def path(self) -> str:
        """Human-readable agent path, e.g. ``coordinator -> trace_analyzer``."""
        return " -> ".join(self.authors_unique) or "(no records)"


def summarize_run(
    *,
    label: str,
    prompt: str,
    records: list[dict],
    latency_ms: int,
    briefing: Optional[PriorContextBriefing],
    n_llm_calls: int = 0,
) -> IncidentRun:
    """Build an ``IncidentRun`` from streamed Coordinator records.

    Args:
        label: Human-readable run label (e.g. ``"cold"`` / ``"warm"``).
        prompt: The user prompt the run was given.
        records: Event records yielded by ``stream_coordinator``.
        latency_ms: Caller-measured wall-clock for the run, in milliseconds.
        briefing: The active briefing during the run (whether real or
            override-injected), used to determine ``directive_fired``.

    Returns:
        An ``IncidentRun`` with all metrics derived from ``records``.
    """
    tool_calls = [r for r in records if r.get("kind") == "tool_call"]
    n_transfers = sum(1 for t in tool_calls if t.get("tool") == "transfer_to_agent")
    n_tool_calls = sum(1 for t in tool_calls if t.get("tool") != "transfer_to_agent")
    authors = [r.get("author", "") for r in records if r.get("author")]
    final_text = next(
        (r.get("text", "") for r in records if r.get("kind") == "final"), ""
    )
    directive_fired = (
        briefing is not None
        and (
            briefing.first_route is not None
            or briefing.must_eval_after
            or bool(briefing.skip_routes)
        )
    )
    return IncidentRun(
        label=label,
        prompt=prompt,
        latency_ms=latency_ms,
        n_tool_calls=n_tool_calls,
        n_transfers=n_transfers,
        n_llm_calls=n_llm_calls,
        authors=authors,
        final_text=final_text,
        directive_fired=directive_fired,
        briefing=briefing,
    )
