# Sentinel — System Architecture

A multi-agent incident response system for production AI in financial-services workflows (fraud detection, KYC/AML, lending, wealth management). The differentiator is a runtime **self-improvement loop**: Sentinel queries its own Phoenix traces via MCP and uses trace-derived directives to deterministically shape the plan it executes on each invocation.

This document is the canonical view of how the pieces fit together. All diagrams are [Mermaid](https://mermaid.live/) — they render natively on GitHub, in VS Code's Markdown preview (Ctrl+Shift+V; install the "Markdown Preview Mermaid Support" extension if a diagram shows as raw text), and at [mermaid.live](https://mermaid.live/).

---

## 1. System topology

The full production topology — five sub-agents, one root Coordinator, two observability surfaces (REST + MCP), three eval suites.

```mermaid
flowchart TB
    User["👤 User / Alert webhook<br/>(structured JSON incident payload)"]

    subgraph UI["Streamlit UI (:8501)"]
        direction TB
        ChatBox["Chat input"]
        DemoPanel["Cold-vs-Warm demo panel<br/>(briefing_override for demo control)"]
        Sidebar["Agent-reasoning sidebar<br/>(per-author tagging)"]
    end

    subgraph Coord["Coordinator (gemini-3.1-pro-preview)"]
        direction TB
        BAC["before_agent_callback<br/>synthesize_prior_context()"]
        BMC["before_model_callback chain:<br/>[enforce_first_route,<br/> count_real_llm_calls]"]
        BTC["before_tool_callback<br/>enforce_skip_routes"]
        CL["Coordinator LLM<br/>(or synthetic LlmResponse if enforced)"]
        BAC --> BMC --> CL
        CL -.tool calls.-> BTC
    end

    subgraph Sub["Sub-agents (gemini-3.1-flash-lite)"]
        direction LR
        TA["TraceAnalyzer<br/>statistical description"]
        ER["EvalRunner<br/>hallucination eval"]
        RC["RootCause<br/>ranked hypotheses<br/>+ data-gap honesty"]
        RM["Remediation<br/>RemediationPlan JSON<br/>(strict schema)"]
        PM["Postmortem<br/>Postmortem JSON<br/>(Google-SRE format)"]
    end

    subgraph Tools["Tools surface"]
        direction TB
        GRT["get_recent_traces<br/>(Phoenix REST)"]
        MCP["Phoenix MCP toolset<br/>27 tools via npx stdio"]
        RHE["run_hallucination_eval<br/>(LLM-as-judge)"]
    end

    subgraph Phx["Phoenix (self-hosted, port 6006)"]
        direction TB
        PhxAPI["Phoenix REST + UI"]
        PhxMCP["Phoenix MCP server<br/>@arizeai/phoenix-mcp"]
        PhxDB[("Trace store +<br/>annotations")]
    end

    subgraph Evals["Evals (post-run annotations)"]
        direction LR
        TTR["time_to_response<br/>annotator=CODE"]
        HAL["hallucination<br/>annotator=LLM"]
        COMP["postmortem_completeness<br/>annotator=CODE"]
    end

    User --> UI
    UI --> Coord

    Coord -->|"transfer_to_agent (A2A)"| Sub
    Coord --> GRT
    Coord --> MCP

    TA --> GRT
    ER --> RHE
    RC --> GRT
    RM --> GRT
    PM --> GRT

    GRT --> PhxAPI
    MCP --> PhxMCP
    RHE -.reads spans.-> PhxAPI
    PhxAPI <--> PhxDB
    PhxMCP <--> PhxDB

    Coord -.OpenInference spans.-> PhxAPI
    Sub -.OpenInference spans.-> PhxAPI

    BAC -.queries past traces.-> MCP

    Evals -.write annotations.-> PhxAPI
    PM -.scored by.-> COMP
    Coord -.scored by.-> TTR
    Sub -.scored by.-> HAL
```

---

## 2. Per-request flow (sequence)

What happens between the user hitting Send and the response landing back.

```mermaid
sequenceDiagram
    actor U as User / Webhook
    participant ST as Streamlit
    participant CO as Coordinator
    participant BAC as before_agent<br/>callback
    participant MCP as Phoenix MCP
    participant BMC as before_model<br/>callback (enforce_first_route)
    participant SA as Sub-agent<br/>(e.g. trace_analyzer)
    participant PHX as Phoenix

    U->>ST: incident JSON / chat message
    ST->>CO: stream_coordinator(text)
    CO->>BAC: invoke
    BAC->>MCP: list-traces, get-span-annotations
    MCP->>PHX: query traces + annotations
    PHX-->>MCP: data
    MCP-->>BAC: data
    BAC->>BAC: derive PriorContextBriefing<br/>(directive rules)
    BAC-->>CO: state["prior_context_briefing"] = briefing

    CO->>BMC: invoke (about to call LLM)
    alt briefing.first_route is set AND not skipped by explicit user intent
        BMC-->>CO: synthetic LlmResponse<br/>(forced transfer_to_agent)
        Note over CO: real LLM call SKIPPED<br/>counter NOT incremented
    else
        BMC-->>CO: None (proceed)
        CO->>CO: real LLM call (counter +1)
    end

    CO->>SA: transfer_to_agent
    SA->>PHX: get_recent_traces (tool)
    PHX-->>SA: trace summary
    SA->>SA: LLM synthesizes final<br/>(counter +1)
    SA-->>CO: final response (text or JSON)
    CO-->>ST: streamed events
    ST-->>U: rendered response + sidebar

    Note over PHX: OpenInference auto-traces<br/>every LLM call + tool call

    ST->>PHX: annotate latest root span<br/>(time_to_response eval)
```

---

## 3. The self-improvement loop (the differentiator — ADR-009)

This is the load-bearing piece for Arize judging criteria #1 ("self-improvement loop") and #2 ("Phoenix MCP load-bearing, not bolted on"). The loop is **deterministic** because directives are enforced at runtime, not just suggested in a prompt.

```mermaid
flowchart LR
    subgraph Past["Past traces (Phoenix)"]
        Errs["ERROR root spans<br/>(failed invocations)"]
        Halluc["hallucination annotations<br/>(from past EvalRunner runs)"]
        Latency["span durations<br/>(time_to_response)"]
    end

    subgraph Synth["synthesize_prior_context()"]
        Q1["list-traces<br/>(via MCP)"]
        Q2["get-span-annotations<br/>(via MCP)"]
        Rules["directive extraction rules<br/>(n_error≥3 → first_route=trace_analyzer;<br/> any hallucinated → must_eval_after;<br/> n_total<3 → default_hours_back=24)"]
        Q1 --> Rules
        Q2 --> Rules
    end

    Briefing["PriorContextBriefing<br/>(typed Pydantic)<br/>+ evidence trail"]

    subgraph Enforce["Runtime enforcement"]
        IP["_coordinator_instruction<br/>renders directive block<br/>into Coordinator prompt"]
        EFR["enforce_first_route<br/>(before_model_callback)<br/>→ synthetic LlmResponse<br/>with forced transfer"]
        ESR["enforce_skip_routes<br/>(before_tool_callback)<br/>→ blocks rejected transfers"]
    end

    NewRun["Coordinator invocation<br/>(deterministic plan)"]
    NewTrace["New trace<br/>(spans + annotations)"]

    Errs --> Q1
    Latency --> Q1
    Halluc --> Q2

    Rules --> Briefing
    Briefing --> IP
    Briefing --> EFR
    Briefing --> ESR

    IP --> NewRun
    EFR --> NewRun
    ESR --> NewRun

    NewRun -->|emits OpenInference spans| NewTrace
    NewTrace -.feeds next invocation.-> Past

    classDef loop fill:#0d9488,stroke:#0a7269,color:#fff;
    class NewTrace,Past loop;
```

**Why this works on camera (the supervisor's gate):** the 5-run cold-vs-warm reproduction (in `scripts/repro_cold_vs_warm.py`, table in `docs/repro-cold-vs-warm.md`) shows a **strict 3→2 LLM-round-trip delta on 5/5 runs** when warm runs the live synthesizer against real Phoenix data. Both sides of the comparison are reproducible because the directive enforcement bypasses the Coordinator's routing LLM call entirely when active.

---

## 4. Data contracts (Pydantic schemas)

Cross-agent contracts in `sentinel/agents/schemas.py`. These are the production-shape outputs that ticketing systems, audit logs, and downstream sub-agents consume. Each is validated at construction time — bad data fails loud.

```mermaid
classDiagram
    class RemediationPlan {
        +severity: Severity (P0|P1|P2|P3)
        +confidence: Confidence (low|medium|high)
        +patched_prompt: Optional[str]
        +rollback_target: Optional[str]
        +eval_guardrail: Optional[EvalGuardrail]
        +rationale: str (20-600)
        +risks: list[str]
        +rollback_plan_if_remediation_fails: str (15-400)
        +_at_least_one_action()
        +_low_confidence_requires_risks()
    }

    class EvalGuardrail {
        +name: str (3-80, snake_case)
        +trigger_metric: str
        +threshold: float
        +severity_on_breach: Severity
        +why_this_eval: str (10-300)
    }

    class Postmortem {
        +title: str (10-120)
        +incident_id: str (3-80)
        +severity: Severity
        +summary: str (50-500)
        +impact: str (30-500)
        +timeline: list[str] (min 2)
        +root_cause: str (30-500)
        +detection: str (20-400)
        +resolution: str (20-500)
        +action_items: list[ActionItem] (min 1)
        +lessons_learned: list[str] (min 1)
        +_timeline_entries_nonempty()
        +_lessons_nonempty()
    }

    class ActionItem {
        +description: str (20-300)
        +owner_role: str (3-50, team-not-person)
        +severity: Severity
        +due_within_days: int (1-90)
    }

    class PriorContextBriefing {
        +cold_start: bool
        +first_route: Optional[Route]
        +skip_routes: list[SubAgentRoute]
        +must_eval_after: bool
        +default_hours_back: int (1-168)
        +evidence: dict[str, str]
        +stats: dict[str, int]
        +_no_contradictions()
    }

    RemediationPlan --> EvalGuardrail : contains?
    Postmortem --> ActionItem : contains (1..n)
```

---

## 5. Component map (where each piece lives)

| Layer | Component | Path | Tests |
|---|---|---|---|
| **UI** | Streamlit app | `sentinel/ui/app.py` | — |
| **Coordinator** | LlmAgent, instruction provider, callbacks | `sentinel/coordinator.py` | covered via `tests/unit/memory/test_instruction.py` |
| **Sub-agent** | TraceAnalyzer | `sentinel/agents/trace_analyzer.py` + `sentinel/prompts/trace_analyzer.md` | — |
| **Sub-agent** | EvalRunner | `sentinel/agents/eval_runner.py` + `sentinel/prompts/eval_runner.md` | — |
| **Sub-agent** | RootCause | `sentinel/agents/root_cause.py` + `sentinel/prompts/root_cause.md` | — |
| **Sub-agent** | Remediation | `sentinel/agents/remediation.py` + `sentinel/prompts/remediation.md` | schema in `tests/unit/agents/test_schemas.py` |
| **Sub-agent** | Postmortem | `sentinel/agents/postmortem.py` + `sentinel/prompts/postmortem.md` | schema in `tests/unit/agents/test_schemas.py` |
| **Schemas** | RemediationPlan, EvalGuardrail, Postmortem, ActionItem, POSTMORTEM_REQUIRED_SECTIONS | `sentinel/agents/schemas.py` | 23 unit tests |
| **Self-improvement** | PriorContextBriefing schema | `sentinel/memory/briefing.py` | 10 unit tests |
| **Self-improvement** | synthesize_prior_context, briefing_override | `sentinel/memory/self_introspection.py` | 10 unit tests (with mocked MCP) |
| **Self-improvement** | enforce_first_route, enforce_skip_routes, count_real_llm_calls | `sentinel/memory/enforcement.py` | 3 integration tests on real LLM |
| **Tool** | get_recent_traces (Phoenix REST) | `sentinel/tools/phoenix_traces.py` | — |
| **Tool** | run_hallucination_eval (orchestrator) | `sentinel/tools/run_eval.py` | — |
| **Observability** | OpenInference → Phoenix wiring | `sentinel/observability/instrumentation.py` | — |
| **Observability** | Phoenix MCP toolset factory | `sentinel/observability/phoenix_mcp.py` | — |
| **Eval** | time_to_response (latency annotation) | `evals/time_to_response.py` | — |
| **Eval** | hallucination (LLM-as-judge) | `evals/hallucination.py` | — |
| **Eval** | postmortem_completeness (code scorer) | `evals/completeness.py` | 11 unit tests |
| **Eval** | per-incident metrics dataclass | `evals/incident_metrics.py` | 9 unit tests |
| **Demo** | 5-run cold-vs-warm repro script | `scripts/repro_cold_vs_warm.py` | — |
| **Docs (judge-facing)** | Repro evidence | `docs/repro-cold-vs-warm.md` | — |
| **Docs (judge-facing)** | This architecture | `docs/architecture.md` | — |

**Test totals:** 81 unit + 3 integration = **84 tests passing**.

---

## 6. Models + region

| Role | Model ID | Region | Note |
|---|---|---|---|
| `COORDINATOR_MODEL` | `gemini-3.1-pro-preview` | `global` | Pro for routing + drafting. Preview status — see ADR-010. Fallback documented in `sentinel/constants.py`. |
| `SUBAGENT_MODEL` | `gemini-3.1-flash-lite` | `global` | GA. Flash sufficient for tool-heavy sub-agents. |
| Hallucination judge | `gemini-3.1-flash-lite` | `global` | Used by `evals/hallucination.py` via google-genai direct (not ADK). |

All inference routes through Vertex AI in the `global` multi-regional endpoint. The Gemini 3 family is not served in `us-central1` (404). See ADR-010 in `context/04-decisions.md`.

---

## 7. Known limitations (current)

- **P2 — `must_eval_after` multi-transfer:** when the active directive sets `must_eval_after=True` AND the user explicitly requests a non-eval sub-agent, the Coordinator's LLM may emit BOTH `transfer_to_agent(<requested>)` AND `transfer_to_agent(eval_runner)` in one model turn. ADK appears to honor only one transfer per turn, so the primary intent can drop. Detailed entry in `context/07-known-issues.md`. Fix is `after_agent_callback`-based enforcement parallel to `enforce_first_route`. Workaround: the cold-vs-warm demo panel forces `cold_start=True` to bypass.
- **Multi-transfer in chained scenarios** (Phase 4 step 5 will hit this — three-incident end-to-end flow needs the P2 fix to chain cleanly).
- **`scripts/_repro.log`** is regeneratable runtime output (gitignored). To produce a fresh table: `RUN_INTEGRATION_TESTS=1 uv run python scripts/repro_cold_vs_warm.py --runs 5`.

---

## 8. How to view / regenerate this doc

**Render the diagrams:**
- **GitHub:** push the file — Mermaid renders inline automatically.
- **VS Code:** `Ctrl+Shift+V` for Markdown Preview. If a diagram shows as raw text, install the extension "Markdown Preview Mermaid Support" (publisher: `bierner`) — one-time setup.
- **Standalone, no install:** copy any \`\`\`mermaid block into [https://mermaid.live/](https://mermaid.live/).
- **PNG export:** use Mermaid Live's export button, or `npx -p @mermaid-js/mermaid-cli mmdc -i docs/architecture.md -o docs/architecture.png` (requires Node).

**Update this doc when:**
- A sub-agent is added/removed (Section 1, Section 5 component map).
- A schema field changes (Section 4 class diagram + cross-reference `tests/unit/agents/test_schemas.py`).
- The model swap happens again (Section 6 model table — link the new ADR).
- A known limitation is resolved (Section 7).
