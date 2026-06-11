"""Bake demo seed data into ``data/memory/`` for the live Cloud Run image.

Phase 8 demo prep. Cloud Run containers are stateless — every redeploy
or idle scale-down wipes ``data/memory/``. To make the /prompts,
/sentinel-health, /evals, and /patterns pages render with data on EVERY
fresh container start, this script produces two deterministic seed
files that get COPIED into the Docker image:

  - ``data/memory/prompt_history.jsonl`` — 60 synthetic records across
    8 agents × 2 prompt versions × ~3-5 runs each. Critic scores are
    drawn from realistic per-agent distributions (postmortem clusters
    around 0.92, the deploy_correlator around 0.85, the eval_runner
    around 0.78 — which trips the PromptEvolver threshold on demand).
    No Vertex required.

  - ``data/memory/incidents.jsonl`` — 6 past incidents covering all
    three demo scenarios, each with a real Vertex ``text-embedding-004``
    768-dim vector so the cosine retrieval on the live console returns
    grounded similar-past-incident hits. Vertex creds required (ADC or
    the same auth the api service uses).

Run from the repo root::

  uv run python scripts/bake_demo_seed.py

It is idempotent: re-running overwrites the seed files. Safe to commit.

CAUTION: the seed runs the Vertex embeddings endpoint. Cost is six
single-embedding calls (~$0.0001 total). Use the same project as the
deployed service (``GOOGLE_CLOUD_PROJECT`` in your shell).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env so GOOGLE_CLOUD_PROJECT etc. are present before importing
# the embedder.
load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUT_PROMPT = REPO_ROOT / "data" / "memory" / "prompt_history.jsonl"
OUT_INCIDENTS = REPO_ROOT / "data" / "memory" / "incidents.jsonl"


# ── Per-agent score distributions, hand-tuned for demo realism ────────


AGENT_DISTRIBUTIONS: dict[str, dict] = {
    "postmortem": {
        "prompt_versions": ["v1", "v2"],
        "score_mean": 0.92,
        "score_std": 0.04,
        "dim_means": {
            "completeness": 0.94,
            "grounding": 0.90,
            "actionability": 0.92,
            "customer_impact": 0.91,
        },
    },
    "remediation": {
        "prompt_versions": ["v1"],
        "score_mean": 0.88,
        "score_std": 0.05,
        "dim_means": {
            "completeness": 0.88,
            "grounding": 0.86,
            "actionability": 0.91,
            "customer_impact": 0.86,
        },
    },
    "root_cause": {
        "prompt_versions": ["v1", "v2"],
        "score_mean": 0.86,
        "score_std": 0.06,
        "dim_means": {
            "completeness": 0.88,
            "grounding": 0.83,
            "actionability": 0.85,
            "customer_impact": 0.88,
        },
    },
    "trace_analyzer": {
        "prompt_versions": ["v1"],
        "score_mean": 0.91,
        "score_std": 0.03,
        "dim_means": {
            "completeness": 0.92,
            "grounding": 0.93,
            "actionability": 0.88,
            "customer_impact": 0.90,
        },
    },
    "deploy_correlator": {
        "prompt_versions": ["v1"],
        "score_mean": 0.85,
        "score_std": 0.05,
        "dim_means": {
            "completeness": 0.83,
            "grounding": 0.89,
            "actionability": 0.84,
            "customer_impact": 0.82,
        },
    },
    "compliance_officer": {
        "prompt_versions": ["v1"],
        "score_mean": 0.89,
        "score_std": 0.04,
        "dim_means": {
            "completeness": 0.91,
            "grounding": 0.93,
            "actionability": 0.88,
            "customer_impact": 0.84,
        },
    },
    "customer_impact_quantifier": {
        "prompt_versions": ["v1"],
        "score_mean": 0.93,
        "score_std": 0.03,
        "dim_means": {
            "completeness": 0.95,
            "grounding": 0.94,
            "actionability": 0.89,
            "customer_impact": 0.96,
        },
    },
    "eval_runner": {
        # Intentionally below the 0.80 evolver threshold so /prompts
        # surfaces an "evolution candidate" badge on this agent in the
        # demo.
        "prompt_versions": ["v1"],
        "score_mean": 0.76,
        "score_std": 0.05,
        "dim_means": {
            "completeness": 0.80,
            "grounding": 0.74,
            "actionability": 0.75,
            "customer_impact": 0.77,
        },
    },
}


SCENARIO_IDS = [
    "fraud-fp-burst",
    "kyc-sanctions-hallucination",
    "lending-latency-regression",
]


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _gen_score(mean: float, std: float, rng: random.Random) -> float:
    """Draw a clamped score in [0, 1]."""
    val = rng.gauss(mean, std)
    return max(0.0, min(1.0, round(val, 4)))


def write_prompt_history(seed: int = 17) -> int:
    """Generate ~60 synthetic per-agent records and write to JSONL."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    incident_pool = [
        f"fraud-fp-spike-20260524T204248Z-{rng.choice('abcdef0123456789') * 6}"
        for _ in range(20)
    ] + [
        f"kyc-pep-fabrication-20260525T103015Z-{rng.choice('abcdef0123456789') * 6}"
        for _ in range(20)
    ] + [
        f"lending-p99-regression-20260524T143022Z-{rng.choice('abcdef0123456789') * 6}"
        for _ in range(20)
    ]
    rng.shuffle(incident_pool)

    for agent_name, dist in AGENT_DISTRIBUTIONS.items():
        n_runs = 8 if agent_name == "eval_runner" else 6
        for k in range(n_runs):
            prompt_version = dist["prompt_versions"][
                k % len(dist["prompt_versions"])
            ]
            prompt_text = f"{agent_name}-prompt-{prompt_version}"
            timestamp = now - timedelta(hours=(n_runs - k) * 6 + rng.randint(0, 3))
            incident_id = incident_pool[(k * 3 + len(records)) % len(incident_pool)]
            scenario_id = next(
                (s for s in SCENARIO_IDS if s.split("-")[0] in incident_id),
                rng.choice(SCENARIO_IDS),
            )
            agg = _gen_score(dist["score_mean"], dist["score_std"], rng)
            rubric = {
                k_: _gen_score(v_, dist["score_std"] * 0.8, rng)
                for k_, v_ in dist["dim_means"].items()
            }
            records.append(
                {
                    "agent_name": agent_name,
                    "prompt_version": prompt_version,
                    "prompt_hash": _short_hash(prompt_text),
                    "incident_id": incident_id,
                    "scenario_id": scenario_id,
                    "aggregate_critic_score": agg,
                    "rubric_scores": rubric,
                    "timestamp_iso": timestamp.isoformat(),
                }
            )

    OUT_PROMPT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PROMPT.open("w", encoding="utf-8") as fp:
        for r in records:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(records)


# ── Past-incident seed (real Vertex embeddings) ───────────────────────


PAST_INCIDENTS: list[dict] = [
    {
        "incident_id": "fraud-fp-spike-20260524T204248Z-pastA",
        "scenario_id": "fraud-fp-burst",
        "title": "Fraud detection — false-positive burst (stale feature cache)",
        "postmortem_summary": (
            "fraud-classifier-v2.3 began misclassifying legitimate retail "
            "transactions as fraud after a stale feature cache served outdated "
            "customer-profile vectors. False-positive rate spiked from 0.07 "
            "to 0.21 in under two minutes."
        ),
        "root_cause": (
            "Feature cache for customer-profile vectors failed to invalidate "
            "after the upstream profile-store schema migration. The classifier "
            "received null + default fields where it expected the new shape, "
            "interpreted them as high-risk indicators, and over-blocked."
        ),
        "remediation_summary": (
            "Invalidated the feature cache, forced re-warm, added a guardrail "
            "eval (cache-staleness watcher firing at 60s idle) and rolled the "
            "schema migration with explicit cache-bust hooks."
        ),
        "days_ago": 21,
    },
    {
        "incident_id": "fraud-fp-spike-20260512T091522Z-pastB",
        "scenario_id": "fraud-fp-burst",
        "title": "Fraud detection — threshold misconfiguration (canary skipped)",
        "postmortem_summary": (
            "Threshold parameter update bypassed the canary gate and shipped "
            "directly to 100% traffic. Decline rate jumped 14 percentage points "
            "over a 33-minute window before rollback."
        ),
        "root_cause": (
            "Auto-deploy pipeline did not enforce canary validation on the new "
            "threshold config. The aggressive sensitivity value was uncalibrated "
            "for the current traffic mix."
        ),
        "remediation_summary": (
            "Rolled back to v2.4.1, enforced mandatory canary at 10% traffic "
            "for all threshold updates, and added a pre-deploy decline-rate "
            "shadow test against the last 24h of traffic."
        ),
        "days_ago": 33,
    },
    {
        "incident_id": "kyc-pep-fabrication-20260501T080010Z-pastC",
        "scenario_id": "kyc-sanctions-hallucination",
        "title": "KYC — fabricated OFAC matches from stale corpus",
        "postmortem_summary": (
            "PEP screener returned 7 fabricated sanctions matches in two minutes "
            "against a stale OFAC list. Customer onboarding flow blocked 7 "
            "legitimate high-net-worth applicants."
        ),
        "root_cause": (
            "Upstream OFAC corpus cache was 48 hours stale due to a missed "
            "nightly refresh job. The LLM-based PEP screener confidently cited "
            "obsolete entries with high confidence."
        ),
        "remediation_summary": (
            "Refreshed the corpus, added a corpus-freshness guard rejecting "
            "any cache older than 6 hours, and added the FCA SUP 15.3 reporting "
            "obligation to the compliance playbook."
        ),
        "days_ago": 35,
    },
    {
        "incident_id": "kyc-pep-fabrication-20260418T120440Z-pastD",
        "scenario_id": "kyc-sanctions-hallucination",
        "title": "KYC — LLM hallucinated sanctions citations under context overflow",
        "postmortem_summary": (
            "PEP screener over-cited sanctions clauses after a context-window "
            "overflow truncated the corpus mid-prompt. Five fabricated matches "
            "in a 90-second window."
        ),
        "root_cause": (
            "Prompt template grew unboundedly with the corpus inclusion. Past "
            "120k tokens the corpus tail was silently dropped and the LLM "
            "hallucinated cites from training data."
        ),
        "remediation_summary": (
            "Bounded the corpus injection at 30k tokens with explicit "
            "deterministic chunking, added a hallucination guard that strips "
            "any cite not present in the retrieved chunks."
        ),
        "days_ago": 49,
    },
    {
        "incident_id": "lending-p99-regression-20260510T143022Z-pastE",
        "scenario_id": "lending-latency-regression",
        "title": "Lending — p99 latency regression after model swap",
        "postmortem_summary": (
            "Underwriting model p99 latency jumped from 280ms to 4200ms within "
            "eight minutes of deploying v4.0.0. 89 underwriting decisions "
            "delayed; 12 user-facing timeouts."
        ),
        "root_cause": (
            "v4.0.0 added an additional embedding lookup per request that was "
            "not cached. The model architecture exceeded the inference budget."
        ),
        "remediation_summary": (
            "Rolled back to v3.7.2, added a p99 latency canary gate to the ML "
            "deploy pipeline at 2x SLO threshold, and queued embedding-lookup "
            "caching for v4.1."
        ),
        "days_ago": 26,
    },
    {
        "incident_id": "lending-p99-regression-20260403T091200Z-pastF",
        "scenario_id": "lending-latency-regression",
        "title": "Lending — slow cluster from feature-store cold cache",
        "postmortem_summary": (
            "Underwriting requests routed to a freshly-deployed instance hit "
            "cold feature-store caches and ran at 6-7x baseline latency for "
            "the first 12 minutes after deploy."
        ),
        "root_cause": (
            "The deploy rotated instances without a cache pre-warm step. New "
            "instances accepted live traffic before the feature cache filled."
        ),
        "remediation_summary": (
            "Added a pre-warm step to the deploy pipeline that hits the feature "
            "store with the top-500 features before instance enters the load "
            "balancer pool."
        ),
        "days_ago": 64,
    },
]


def write_incidents_with_embeddings() -> int:
    """Embed each past incident via Vertex and write to JSONL."""
    from sentinel.memory.embedder import embed_text

    now = datetime.now(timezone.utc)
    OUT_INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
    with OUT_INCIDENTS.open("w", encoding="utf-8") as fp:
        for record in PAST_INCIDENTS:
            text_for_embed = (
                f"{record['title']}\n\n"
                f"Summary: {record['postmortem_summary']}\n\n"
                f"Root cause: {record['root_cause']}\n\n"
                f"Remediation: {record['remediation_summary']}"
            )
            embedding = embed_text(text_for_embed)
            ts = now - timedelta(days=record["days_ago"])
            fp.write(
                json.dumps(
                    {
                        "incident_id": record["incident_id"],
                        "scenario_id": record["scenario_id"],
                        "timestamp": ts.isoformat(),
                        "title": record["title"],
                        "postmortem_summary": record["postmortem_summary"],
                        "root_cause": record["root_cause"],
                        "remediation_summary": record["remediation_summary"],
                        "embedding": embedding,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return len(PAST_INCIDENTS)


if __name__ == "__main__":
    n_prompts = write_prompt_history()
    print(f"Wrote {n_prompts} prompt-history records to {OUT_PROMPT}")
    try:
        n_incidents = write_incidents_with_embeddings()
        print(f"Wrote {n_incidents} embedded past incidents to {OUT_INCIDENTS}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: failed to embed past incidents ({type(exc).__name__}: {exc}). "
            "Prompt history seeded successfully; similar-past-incidents recall "
            "will fall back to an empty corpus until you re-run with Vertex auth.",
            file=sys.stderr,
        )
        sys.exit(1)
