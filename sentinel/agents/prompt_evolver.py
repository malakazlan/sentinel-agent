"""PromptEvolver — Phase 8 / ADR-020.

The meta-agent that proposes 2-3 prompt variants for an underperforming
sub-agent, plus the replay/scoring loop that picks a winner. Auto-
promotion is OFF by default (``SENTINEL_PROMPT_EVOLUTION_AUTOPROMOTE``);
in dry-run mode the evolver emits a ``PromptEvolutionProposal`` for the
UI's "Approve evolution" gate.

The replay machinery here is intentionally minimal: replay scoring runs
the Critic on a candidate prompt's PROPOSED output text against a
stored postmortem's input. The variant whose Critic aggregate score is
highest wins. The evolver is bounded:

- Max 1 evolution per agent per 24h (lock file).
- Max 2 prompt versions kept simultaneously per agent.
- Promotion requires score delta >= ``MIN_PROMOTION_DELTA`` (default 0.05).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from sentinel.constants import COORDINATOR_MODEL
from sentinel.memory.enforcement import count_real_llm_calls
from sentinel.memory.prompt_history import (
    AgentRollup,
    PromptHistoryStore,
    shared_store,
)
from sentinel.prompts import load_prompt

_logger = logging.getLogger(__name__)


# ── Bounds ────────────────────────────────────────────────────────────────


# Default rolling avg threshold below which an agent is "underperforming."
TRIGGER_SCORE_THRESHOLD: float = 0.80

# Minimum samples in the rolling window before evolver will even consider.
TRIGGER_MIN_SAMPLES: int = 5

# Minimum score delta a variant must beat the current prompt by before
# promotion is recommended. Smaller deltas are noise.
MIN_PROMOTION_DELTA: float = 0.05

# Hard cap on parallel prompt versions per agent (current + 1 candidate).
MAX_VERSIONS_PER_AGENT: int = 2

# 24-hour cooldown between evolutions per agent.
COOLDOWN_SECONDS: int = 24 * 60 * 60

# Lock-file directory; one file per (agent_name) tracks last evolution time.
_LOCK_DIR = Path("data/memory/prompt_evolution_locks")


# ── Schemas ───────────────────────────────────────────────────────────────


class PromptVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: str = Field(..., min_length=3, max_length=80)
    prompt_text: str = Field(..., min_length=50)
    rationale: str = Field(..., min_length=20, max_length=400)


class PromptVariantSet(BaseModel):
    """Raw evolver output — before scoring."""

    model_config = ConfigDict(extra="forbid")
    target_agent: str = Field(..., min_length=2)
    current_prompt_version: str = Field(..., min_length=1)
    proposed_variants: list[PromptVariant] = Field(..., min_length=2, max_length=3)


class ScoredVariant(BaseModel):
    """Variant + the score the replay returned."""

    model_config = ConfigDict(extra="forbid")
    variant: PromptVariant
    replay_aggregate_score: float = Field(..., ge=0.0, le=1.0)
    replay_rubric_scores: dict[str, float] = Field(default_factory=dict)
    replay_incident_id: str = ""


class PromptEvolutionProposal(BaseModel):
    """Final evolver output — what the UI surfaces to the operator."""

    model_config = ConfigDict(extra="forbid")
    target_agent: str
    current_prompt_version: str
    current_prompt_hash: str
    baseline_avg_score: float
    proposed_winner: Optional[ScoredVariant] = None
    all_scored_variants: list[ScoredVariant] = Field(default_factory=list)
    score_delta_over_baseline: float = 0.0
    promotion_recommended: bool = False
    decision_rationale: str = Field(..., min_length=10)


# ── Agent wiring ──────────────────────────────────────────────────────────


_GENERATE_CONFIG = types.GenerateContentConfig(temperature=0.2)


prompt_evolver = LlmAgent(
    name="prompt_evolver",
    model=COORDINATOR_MODEL,  # full-reasoning model: variant authoring needs depth
    instruction=load_prompt("prompt_evolver"),
    description=(
        "Meta sub-agent that authors 2-3 prompt variants for an "
        "underperforming sub-agent based on the rolling critic-score "
        "history. Does NOT promote variants itself — emits a "
        "PromptVariantSet for the orchestrator's replay loop to score "
        "and (gated) promote. Phase 8 / ADR-020."
    ),
    generate_content_config=_GENERATE_CONFIG,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=count_real_llm_calls,
)


# ── Decision logic ────────────────────────────────────────────────────────


def should_trigger_evolution(rollup: Optional[AgentRollup]) -> bool:
    """True iff the rolling avg is below threshold + sample count is
    sufficient + no cooldown is active."""
    if rollup is None:
        return False
    if rollup.sample_count < TRIGGER_MIN_SAMPLES:
        return False
    if rollup.avg_aggregate_score >= TRIGGER_SCORE_THRESHOLD:
        return False
    return not _cooldown_active(rollup.agent_name)


def _cooldown_active(agent_name: str) -> bool:
    """Returns True if an evolution ran for ``agent_name`` within
    ``COOLDOWN_SECONDS``."""
    lock_file = _LOCK_DIR / f"{_slug(agent_name)}.lock"
    if not lock_file.exists():
        return False
    try:
        last_ts = float(lock_file.read_text().strip())
    except (ValueError, OSError):
        return False
    return (time.time() - last_ts) < COOLDOWN_SECONDS


def _stamp_cooldown(agent_name: str) -> None:
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = _LOCK_DIR / f"{_slug(agent_name)}.lock"
    lock_file.write_text(str(time.time()))


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower())


def hash_prompt(text: str) -> str:
    """Short 12-char hex hash — used as the prompt_hash dedup key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ── Promotion decision ────────────────────────────────────────────────────


def evaluate_proposal(
    *,
    target_agent: str,
    current_prompt_version: str,
    current_prompt_text: str,
    baseline_avg_score: float,
    scored_variants: list[ScoredVariant],
) -> PromptEvolutionProposal:
    """Apply the promotion gate: best variant must beat baseline by
    ``MIN_PROMOTION_DELTA``."""
    if not scored_variants:
        return PromptEvolutionProposal(
            target_agent=target_agent,
            current_prompt_version=current_prompt_version,
            current_prompt_hash=hash_prompt(current_prompt_text),
            baseline_avg_score=baseline_avg_score,
            proposed_winner=None,
            all_scored_variants=[],
            score_delta_over_baseline=0.0,
            promotion_recommended=False,
            decision_rationale=(
                "No variants were scored — evolver produced no usable "
                "candidates or the replay framework returned no data."
            ),
        )

    winner = max(scored_variants, key=lambda v: v.replay_aggregate_score)
    delta = winner.replay_aggregate_score - baseline_avg_score
    if delta >= MIN_PROMOTION_DELTA:
        rationale = (
            f"Winner variant {winner.variant.variant_id!r} scored "
            f"{winner.replay_aggregate_score:.3f} vs baseline "
            f"{baseline_avg_score:.3f} (delta +{delta:.3f} >= "
            f"{MIN_PROMOTION_DELTA}). Promotion gated on operator "
            "approval per ADR-020 dry-run posture."
        )
        return PromptEvolutionProposal(
            target_agent=target_agent,
            current_prompt_version=current_prompt_version,
            current_prompt_hash=hash_prompt(current_prompt_text),
            baseline_avg_score=baseline_avg_score,
            proposed_winner=winner,
            all_scored_variants=scored_variants,
            score_delta_over_baseline=delta,
            promotion_recommended=True,
            decision_rationale=rationale,
        )
    return PromptEvolutionProposal(
        target_agent=target_agent,
        current_prompt_version=current_prompt_version,
        current_prompt_hash=hash_prompt(current_prompt_text),
        baseline_avg_score=baseline_avg_score,
        proposed_winner=winner,
        all_scored_variants=scored_variants,
        score_delta_over_baseline=delta,
        promotion_recommended=False,
        decision_rationale=(
            f"Best variant {winner.variant.variant_id!r} scored "
            f"{winner.replay_aggregate_score:.3f} but did not beat "
            f"baseline {baseline_avg_score:.3f} by the required "
            f"{MIN_PROMOTION_DELTA} margin (delta {delta:+.3f}). No "
            "promotion this cycle."
        ),
    )


# ── Promotion application (gated on operator approval) ────────────────────


def autopromote_enabled() -> bool:
    """Whether evolutions auto-apply without an explicit approval click."""
    return os.environ.get("SENTINEL_PROMPT_EVOLUTION_AUTOPROMOTE", "0") == "1"


def apply_promotion(
    proposal: PromptEvolutionProposal,
    *,
    prompts_dir: Optional[Path] = None,
) -> bool:
    """Apply a recommended promotion by writing the winner's prompt text
    to disk under a versioned filename. The orchestrator routes the
    underperforming agent to the new prompt on subsequent runs.

    Returns True if the promotion was written; False on a no-op (e.g.,
    proposal does not recommend promotion).

    Stamps the cooldown lock so this agent won't be re-evolved for 24h.
    Archives the prior version to ``prompts/<agent>_v<n>.archived.md``
    so rollback is mechanically straightforward.
    """
    if not proposal.promotion_recommended or proposal.proposed_winner is None:
        return False
    prompts_dir = prompts_dir or Path("sentinel/prompts")
    target_file = prompts_dir / f"{_slug(proposal.target_agent)}.md"
    if target_file.exists():
        archive_name = (
            f"{_slug(proposal.target_agent)}_"
            f"{_slug(proposal.current_prompt_version)}.archived.md"
        )
        archive_target = prompts_dir / archive_name
        archive_target.write_text(
            target_file.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(
        proposal.proposed_winner.variant.prompt_text,
        encoding="utf-8",
    )
    # Stamp + record + audit-log.
    _stamp_cooldown(proposal.target_agent)
    _write_audit(proposal)
    return True


def _write_audit(proposal: PromptEvolutionProposal) -> None:
    audit_dir = Path("data/memory/prompt_promotions")
    audit_dir.mkdir(parents=True, exist_ok=True)
    fname = (
        f"{_slug(proposal.target_agent)}_"
        f"{_slug(proposal.proposed_winner.variant.variant_id)}_"  # type: ignore[union-attr]
        f"{int(time.time())}.json"
    )
    (audit_dir / fname).write_text(
        proposal.model_dump_json(indent=2),
        encoding="utf-8",
    )
