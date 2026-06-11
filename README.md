# Sentinel

> Sentinel is an open-source AI Site Reliability Engineer for production AI in financial services — it detects incidents, generates regulator-grade postmortems with quantified customer impact, and measurably improves itself by evolving its own prompts from observed outcomes.

**Live URLs:**
- **App:** https://sentinel-web-586014642476.us-central1.run.app
- **API:** https://sentinel-api-586014642476.us-central1.run.app
- **Phoenix (trace explorer):** https://sentinel-phoenix-586014642476.us-central1.run.app

[![Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
![Tests: 334 backend + 25 frontend](https://img.shields.io/badge/tests-334%20backend%20%2B%2025%20frontend-brightgreen)

---

## Three things that are novel

1. **Prompt evolution loop.** Every postmortem is critic-scored on a four-dimension rubric. The `PromptEvolver` sub-agent watches rolling per-agent averages, and when an agent's score dips below 0.80 for at least 5 runs, it proposes 2–3 prompt variants, replay-scores each against the last K stored incidents, and surfaces the winner behind an *Approve evolution* gate. Auto-promotion is off by default — judges click the button. Hard ceilings: 1 evolution per agent per 24h, ≥0.05 score delta required, full rollback path. ([ADR-020](#adrs))
2. **Pattern mining over past incidents.** The `PatternMiner` agent embeds every completed incident's `root_cause + remediation` text (Vertex `text-embedding-004`, 768-dim) and groups them with greedy centroid clustering. Clusters of size ≥3 with cohesion ≥0.65 become `PatternProposal` objects on the `/patterns` page; operators accept (added as a Coordinator directive) or reject. No HDBSCAN / sklearn dep — pure-Python so it runs in the Cloud Run image. ([ADR-021](#adrs))
3. **Regulatory grounding with a hallucination guard.** The `ComplianceOfficer` agent cites regulator clauses from a curated, hand-verified corpus (SR 11-7, OCC 2011-12, EU AI Act Articles 9/14/15/26, NIST AI RMF, FFIEC, FCA SS1/23, FCA SUP 15.3, EU 5MLD Article 33, ECOA Reg B). A post-LLM validator strips any citation whose `(regulation_short_name, clause_id)` tuple was not in the most recent search result and replaces it with the literal *"no specific regulation matched, generic guidance applied"* fallback. Hallucinated cites are mechanically impossible to ship. ([ADR-019](#adrs))

---

## Quick start

### Docker Compose (api + web local)

```bash
git clone https://github.com/<you>/sentinel-agent.git
cd sentinel-agent
cp .env.example .env
# Fill in: GOOGLE_CLOUD_PROJECT, GOOGLE_GENAI_USE_VERTEXAI=true
# Either run `gcloud auth application-default login` once,
# or set GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json.

docker compose up --build
# api  → http://localhost:8000  (FastAPI + SSE)
# web  → http://localhost:3000  (Next.js 14)
```

### Native dev (no Docker)

```bash
# Backend
uv sync
uv run uvicorn sentinel.api.main:app --reload --port 8000

# Frontend (in a second shell)
cd web && npm install && npm run dev
```

Click any scenario card on the web app and the full 9-stage pipeline runs end-to-end.

### Cloud Run deploy

See [`docs/deploy.md`](docs/deploy.md) for the runbook. Both services idle to $0 with `min-instances=0`. Vector Search backend (`SENTINEL_MEMORY_BACKEND=vector_search`) is optional and bills hourly while deployed.

---

## What runs end-to-end

Each scenario triggers the 7-stage pipeline plus the bounded critic loop and the compliance pass:

```
investigate → eval_fanout → deploy_correlation → root_cause → remediation
            → customer_impact → postmortem → critic loop → compliance
```

- **`investigate`** — `TraceAnalyzer` pulls the trace window from Phoenix.
- **`eval_fanout`** — `ParallelEvalRunner` (Phase 7) fans out across 4 evals: faithfulness, drift, prompt-injection, toxicity.
- **`deploy_correlation`** — `DeployCorrelator` queries the GitHub MCP for commits + PRs in the window around the incident onset.
- **`root_cause`** — `RootCause` (Gemini 3.1 Pro) emits ranked causal hypotheses.
- **`remediation`** — `Remediation` (Gemini 3.1 Pro) drafts a structured `RemediationPlan`.
- **`customer_impact`** *(Phase 8)* — `CustomerImpactQuantifier` reads the scenario's seed and emits a typed `ImpactReport`: dollars at risk, customers affected, transactions affected, estimated revenue loss, customer-trust delta. Every figure carries a per-line audit citation.
- **`postmortem`** — `PostmortemAgent` emits a Google-SRE-format RCA JSON.
- **Critic loop** — `CriticAgent` scores against a 4-dimension rubric. If score < 0.85 the loop revises (max 2 iterations).
- **`compliance`** *(Phase 8)* — `ComplianceOfficer` queries the regulatory RAG and emits `ComplianceReport` with cited clauses + reporting obligations (24h / 72h / 30d). Hallucinated cites are stripped by the post-LLM validator.

Telemetry from every agent flows into a `prompt_history` JSONL store. `SentinelMonitor` reads this to surface per-agent rolling scores + trend slopes on the `/sentinel-health` page. The `PromptEvolver` reads the same store to decide which agent's prompt is underperforming.

---

## Architecture at a glance

Full diagrams in [`docs/architecture.md`](docs/architecture.md). Component map below.

| Layer | Where it lives |
|---|---|
| FastAPI + SSE | [`sentinel/api/`](sentinel/api/) |
| Coordinator + directive enforcement | [`sentinel/coordinator.py`](sentinel/coordinator.py), [`sentinel/memory/enforcement.py`](sentinel/memory/enforcement.py) |
| 18 sub-agents | [`sentinel/agents/`](sentinel/agents/) |
| Phoenix MCP + GitHub MCP + Slack MCP toolset factories | [`sentinel/observability/`](sentinel/observability/) |
| Regulatory corpus + RAG search + corpus builder | [`sentinel/regulatory/`](sentinel/regulatory/) and [`data/regulatory/corpus.jsonl`](data/regulatory/corpus.jsonl) |
| Distribution stats (KS, PSI), fairness metrics (4/5ths) | [`sentinel/tools/distribution_stats.py`](sentinel/tools/distribution_stats.py), [`sentinel/tools/fairness_metrics.py`](sentinel/tools/fairness_metrics.py) |
| Memory: local JSONL + cosine; Vertex Vector Search dual-write | [`sentinel/memory/`](sentinel/memory/) |
| Prompt evolution: history store + evolver + audit log | [`sentinel/memory/prompt_history.py`](sentinel/memory/prompt_history.py), [`sentinel/agents/prompt_evolver.py`](sentinel/agents/prompt_evolver.py) |
| Pattern mining + accept/reject persistence | [`sentinel/agents/pattern_miner.py`](sentinel/agents/pattern_miner.py) |
| Next.js 14 App Router UI (9 pages) | [`web/app/`](web/app/) |
| Cross-agent Pydantic schemas | [`sentinel/agents/schemas.py`](sentinel/agents/schemas.py) |
| Architecture decisions | [`context/04-decisions.md`](context/04-decisions.md) (local), summarized in [`docs/architecture.md`](docs/architecture.md) |

The judge-facing live demo is the web URL above. Click *fraud-fp-burst* and watch the agent stepper populate in real time.

---

## How we built it

### Operating principles

- Multi-agent on Google's Agent Development Kit (ADK Python). A2A between Coordinator and sub-agents — never visual Agent Builder. ADK requirement: code-owned runtime for the Arize track.
- Pydantic schemas as the contract between agents. A response that fails validation is the agent's bug, not a downstream chore.
- Prompts live as `.md` files under [`sentinel/prompts/`](sentinel/prompts/). The orchestrator loads them at runtime; updates are auditable as standalone diffs.
- Tests covering happy and unhappy paths for every schema validator + every deterministic utility. 334 backend + 25 frontend tests pass at HEAD.
- No silent failures: every catch is logged, every degraded path emits a structured caveat (ImpactReport caveats, OTLP `spans_written=0` warning, etc.).
- Graceful degradation when the observability layer is offline. Real Sentinel deploys point at the customer's OTLP collector (Cloud Trace, Datadog, Tempo, Honeycomb) — Phoenix is the dev convenience. See [ADR-017](context/04-decisions.md).

### ADRs (architecture decision records) <a name="adrs"></a>

All 27 ADRs live in [`context/04-decisions.md`](context/04-decisions.md). The Phase 7 baseline (ADR-001 through ADR-017) + the Phase 8 deltas:

| ADR | What | Where |
|---|---|---|
| 012 | ParallelAgent eval fan-out | [`sentinel/agents/parallel_eval.py`](sentinel/agents/parallel_eval.py) |
| 013 | Persistent incident memory + RAG | [`sentinel/memory/`](sentinel/memory/) |
| 014 | GitHub MCP + DeployCorrelator | [`sentinel/agents/deploy_correlator.py`](sentinel/agents/deploy_correlator.py) |
| 015 | Slack MCP + SlackAnnouncer | [`sentinel/agents/slack_announcer.py`](sentinel/agents/slack_announcer.py) |
| 016 | CriticAgent + bounded refinement loop | [`sentinel/agents/critic.py`](sentinel/agents/critic.py) |
| 017 | Graceful degradation when OTLP collector unreachable | [`sentinel/tools/incident_sim.py`](sentinel/tools/incident_sim.py) |
| 018 | CustomerImpactQuantifier | [`sentinel/agents/customer_impact.py`](sentinel/agents/customer_impact.py) |
| 019 | Regulatory citations RAG + ComplianceOfficer | [`sentinel/regulatory/`](sentinel/regulatory/), [`sentinel/agents/compliance_officer.py`](sentinel/agents/compliance_officer.py) |
| 020 | Prompt evolution loop (dry-run + replay + approval gate) | [`sentinel/agents/prompt_evolver.py`](sentinel/agents/prompt_evolver.py) |
| 021 | PatternMiner (greedy clustering + cohesion floor) | [`sentinel/agents/pattern_miner.py`](sentinel/agents/pattern_miner.py) |
| 022 | DriftDetective (KS + PSI thresholds) | [`sentinel/agents/drift_detective.py`](sentinel/agents/drift_detective.py) |
| 023 | BiasFairnessAuditor (4/5ths + parity + EO) | [`sentinel/agents/bias_fairness_auditor.py`](sentinel/agents/bias_fairness_auditor.py) |
| 024 | SLOGuardian (Google SRE Workbook §5) | [`sentinel/agents/slo_guardian.py`](sentinel/agents/slo_guardian.py) |
| 025 | HumanOverrideGate ("under your oversight" gate) | [`sentinel/agents/human_override.py`](sentinel/agents/human_override.py) |
| 026 | Sentinel-watches-Sentinel | [`sentinel/agents/sentinel_monitor.py`](sentinel/agents/sentinel_monitor.py) |
| 027 | UI surface (9 pages + global nav + additive routes) | [`web/app/`](web/app/), [`sentinel/api/phase8_routes.py`](sentinel/api/phase8_routes.py) |

### Stack (locked)

| Layer | Choice |
|---|---|
| Agent framework | Google ADK Python |
| Models | Gemini 3.1 Pro (Coordinator, Drafter, PromptEvolver); Gemini 3.1 Flash Lite (extraction sub-agents) — all via Vertex AI `global` region |
| Observability | Arize Phoenix self-hosted + Phoenix MCP (dev); customer's OTLP collector (prod) |
| Embeddings | Vertex `text-embedding-004` (768-dim) |
| Vector search | local JSONL + cosine (default) or Vertex AI Vector Search (production, `SENTINEL_MEMORY_BACKEND=vector_search`) |
| Frontend | Next.js 14 App Router + TanStack Query + Tailwind |
| Backend | FastAPI + sse-starlette + uvicorn |
| Runtime | Cloud Run (both services) |

### Run the tests

```bash
uv run pytest                  # 334 passing + 4 skipped
cd web && npm run test:run     # 25 Vitest tests
cd web && npx tsc --noEmit     # strict typecheck
```

---

## License

Apache 2.0. See [`LICENSE`](LICENSE). The codebase is a hackathon submission and a starting point for production deployment — fork it, point it at your real OTLP collector, swap the curated corpus for the regulations applicable to your jurisdiction.

Built with Google ADK, Gemini, Arize Phoenix, and Google Cloud.
