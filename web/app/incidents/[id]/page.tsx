"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/metric-card";
import { AgentStepper, type AgentStep, type StepStatus } from "@/components/agent-stepper";
import { RoutingCallout } from "@/components/routing-callout";
import { DeterminismBars } from "@/components/determinism-bars";
import { useIncidentStream } from "@/lib/sse";
import { getIncident } from "@/lib/api";
import { severityVariant } from "@/lib/severity";
import type { IncidentEvent, IncidentResult, StageName } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Phoenix trace-tree URL surfaced on the incident footer + the "View
// Phoenix" button. Defaults to the dev port; production deploys
// override via NEXT_PUBLIC_PHOENIX_URL (baked into the bundle at build
// time, same pattern as NEXT_PUBLIC_API_BASE_URL).
const PHOENIX_URL =
  process.env.NEXT_PUBLIC_PHOENIX_URL ?? "http://localhost:6006";

const STAGES_IN_ORDER: { stage: StageName; name: string; model: string }[] = [
  { stage: "investigate", name: "Trace analyzer", model: "gemini-3.1-flash-lite" },
  // Phase 7 / ADR-012 — ParallelEvalRunner fan-out over 4 code-eval suites.
  { stage: "eval_fanout", name: "Eval fan-out", model: "ParallelAgent · 4 suites" },
  // Phase 7 / ADR-014 — DeployCorrelator queries GitHub MCP for commits/PRs.
  { stage: "deploy_correlation", name: "Deploy correlator", model: "gemini-3.1-flash-lite · GitHub MCP" },
  // Phase 8 / ADR-022 — deterministic KS + PSI compute on cached spans.
  { stage: "drift_detective", name: "Drift detective", model: "deterministic · KS + PSI" },
  // Phase 8 / ADR-023 — deterministic 4/5ths + statistical parity + EO.
  { stage: "bias_fairness", name: "Bias / fairness audit", model: "deterministic · 4/5ths + parity + EO" },
  { stage: "root_cause", name: "Root cause", model: "gemini-3.1-pro" },
  { stage: "remediation", name: "Remediation", model: "gemini-3.1-pro" },
  { stage: "postmortem", name: "Postmortem", model: "gemini-3.1-flash-lite" },
];

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function deriveStepper(events: IncidentEvent[]): AgentStep[] {
  const incidentStarted = events.find((e): e is Extract<IncidentEvent, { type: "incident_started" }> => e.type === "incident_started");
  const seedCompleted = events.find((e): e is Extract<IncidentEvent, { type: "seed_completed" }> => e.type === "seed_completed");
  const stageStarted = new Map<StageName, Extract<IncidentEvent, { type: "stage_started" }>>();
  const stageCompleted = new Map<StageName, Extract<IncidentEvent, { type: "stage_completed" }>>();

  for (const event of events) {
    if (event.type === "stage_started") stageStarted.set(event.stage, event);
    if (event.type === "stage_completed") stageCompleted.set(event.stage, event);
  }

  const coordinatorStatus: StepStatus = incidentStarted ? "done" : "queued";
  const coordinatorAction = seedCompleted
    ? `Seeded ${seedCompleted.spans_written} spans into watched project; routing the pipeline.`
    : "Synthesizing prior context and deriving routing directives.";

  const steps: AgentStep[] = [
    {
      name: "Coordinator",
      model: "gemini-3.1-pro",
      status: coordinatorStatus,
      action: coordinatorAction,
      meta: incidentStarted ? `+0s · ${formatMs(incidentStarted.elapsed_ms)}` : "queued",
    },
  ];

  for (const { stage, name, model } of STAGES_IN_ORDER) {
    const start = stageStarted.get(stage);
    const end = stageCompleted.get(stage);
    let status: StepStatus = "queued";
    if (end) status = "done";
    else if (start) status = "running";

    const action = end
      ? end.final_text.slice(0, 240) + (end.final_text.length > 240 ? "…" : "")
      : start
      ? "Running…"
      : "Awaiting upstream stage.";

    const meta = end
      ? `+${formatMs(start ? start.elapsed_ms : end.elapsed_ms)} · ${formatMs(end.latency_ms)}`
      : start
      ? `+${formatMs(start.elapsed_ms)} · running`
      : "queued";

    const step: AgentStep = { name, model, status, action, meta };
    if (status === "running") {
      step.badge = { label: "running", variant: "running" };
    }
    steps.push(step);
  }

  return steps;
}

export default function IncidentPage({ params }: { params: { id: string } }) {
  const stream = useIncidentStream(params.id);

  const incidentStarted = stream.events.find(
    (e): e is Extract<IncidentEvent, { type: "incident_started" }> => e.type === "incident_started"
  );
  const briefing = stream.events.find(
    (e): e is Extract<IncidentEvent, { type: "briefing_resolved" }> => e.type === "briefing_resolved"
  );
  const seedCompleted = stream.events.find(
    (e): e is Extract<IncidentEvent, { type: "seed_completed" }> => e.type === "seed_completed"
  );
  const postmortemValidated = stream.events.find(
    (e): e is Extract<IncidentEvent, { type: "postmortem_validated" }> => e.type === "postmortem_validated"
  );
  const completedEvent = stream.events.find(
    (e) => e.type === "incident_completed" || e.type === "incident_failed"
  );

  // Phase 8 / ADR-025 — HumanOverrideGate banner. We surface ONLY the
  // latest unresolved gate. A resolved (approved / rejected / timeout)
  // gate is dismissed automatically.
  const gateAwaiting = stream.events
    .filter((e): e is Extract<IncidentEvent, { type: "human_gate_awaiting" }> => e.type === "human_gate_awaiting")
    .slice()
    .reverse()[0];
  const gateResolved = stream.events
    .filter((e): e is Extract<IncidentEvent, { type: "human_gate_resolved" }> => e.type === "human_gate_resolved")
    .slice()
    .reverse()[0];
  const showGateBanner = Boolean(
    gateAwaiting && (!gateResolved || gateResolved.gate_id !== gateAwaiting.gate_id),
  );
  const [gateActing, setGateActing] = useState(false);

  async function resolveGate(decision: "approve" | "reject") {
    if (!gateAwaiting) return;
    setGateActing(true);
    try {
      await fetch(
        `${API_BASE_URL}/incidents/${encodeURIComponent(params.id)}/gate/${encodeURIComponent(gateAwaiting.gate_id)}/${decision}`,
        { method: "POST" },
      );
    } finally {
      setGateActing(false);
    }
  }

  // ── SSE-drop fallback ──────────────────────────────────────────────
  //
  // Cloud Run / browser idle timeouts have been observed killing the
  // SSE connection during the long post-postmortem stages (critic loop,
  // compliance, memory write). When the EventSource fires onerror
  // before a terminal event arrives, we kick over to polling
  // GET /incidents/{id} so the page can still render the finished
  // postmortem button instead of stalling on "Pipeline running…".
  //
  // The poll runs only when SSE is in an error state AND we haven't
  // seen a terminal event yet. It backs off automatically once the
  // backend reports the run finished.
  const sseDroppedBeforeTerminal =
    stream.status === "error" && !completedEvent;
  const fallbackResult = useQuery<IncidentResult>({
    queryKey: ["incident-fallback", params.id],
    queryFn: ({ signal }) => getIncident(params.id, signal),
    enabled: sseDroppedBeforeTerminal,
    refetchInterval: (q) => {
      const r = q.state.data as IncidentResult | undefined;
      if (!r) return 5000;
      // Stop polling once the backend reports either a final result
      // (succeeded true/false) — running stays polled.
      if ("succeeded" in r) return false;
      return 5000;
    },
    retry: 0,
  });
  const fallbackFinished =
    fallbackResult.data && "succeeded" in fallbackResult.data;
  const completed = completedEvent || fallbackFinished;

  const elapsedMs = stream.events.length > 0
    ? stream.events[stream.events.length - 1]?.elapsed_ms ?? 0
    : 0;

  const steps = useMemo(() => deriveStepper(stream.events), [stream.events]);

  const tracesValue = seedCompleted ? `${seedCompleted.spans_written}` : "—";
  const tracesSub = seedCompleted ? `${seedCompleted.n_ok} OK · ${seedCompleted.n_error} ERROR` : undefined;
  const errorRate = seedCompleted
    ? ((seedCompleted.n_error / Math.max(1, seedCompleted.n_error + seedCompleted.n_ok)) * 100).toFixed(1)
    : "—";

  // ── Phase 7 / ADR-013: derive live briefing-driven UI from the wire ──
  //
  // The Coordinator emits ``briefing_resolved`` once before any stage runs.
  // Three places on this page hydrate from it:
  //   1. "Round-trips" metric  — cold start runs the full 6-stage chain;
  //      a warm briefing with ``skip_routes`` shaves stages off.
  //   2. "Learned routing" callout — first_route + skip_routes + evidence,
  //      or a cold-start fallback message.
  //   3. "Similar past incidents" precedent list — only rendered when the
  //      RAG layer returned non-empty matches.
  const totalPipelineStages = STAGES_IN_ORDER.length;  // 6 (investigate → postmortem)
  const roundTripsValue = briefing
    ? `${totalPipelineStages - briefing.skip_routes.length}`
    : "—";
  const roundTripsDelta =
    briefing && !briefing.cold_start && briefing.skip_routes.length > 0
      ? {
          value: `−${briefing.skip_routes.length} vs cold (${totalPipelineStages})`,
          positive: true,
        }
      : briefing && briefing.cold_start
      ? { value: "cold start", positive: false }
      : undefined;

  const routingBody = briefing
    ? briefing.cold_start
      ? `Cold start — no prior context indexed. Running the full default chain (${totalPipelineStages} stages).`
      : (() => {
          const parts: string[] = [];
          if (briefing.first_route) {
            const reason =
              briefing.evidence["first_route"] ?? "matches the dominant pattern from prior runs";
            parts.push(`Open with ${briefing.first_route} — ${reason}.`);
          }
          if (briefing.skip_routes.length > 0) {
            const skipReason =
              briefing.evidence["skip_routes"] ?? "redundant given prior coverage";
            parts.push(`Skip ${briefing.skip_routes.join(", ")} — ${skipReason}.`);
          }
          if (briefing.must_eval_after) {
            parts.push("Force an eval pass before sign-off.");
          }
          return parts.length > 0
            ? parts.join(" ")
            : "Warm briefing returned no directive — running default chain.";
        })()
    : "Awaiting briefing…";
  const routingSource = briefing
    ? `Source: Phoenix MCP · last ${briefing.default_hours_back}h · ` +
      `${briefing.stats["n_total"] ?? 0} prior incidents · ` +
      `${briefing.similar_past_incidents.length} similar`
    : "Source: Phoenix MCP";

  return (
    <div className="min-h-screen">
      <Topbar
        active="console"
        status={
          completed
            ? { dot: "ok", label: "Pipeline finished" }
            : { dot: "running", label: "Pipeline running" }
        }
        context={incidentStarted?.watched_project ?? ""}
        incidentId={params.id}
      />
      <main className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-10">
        {/* Incident header */}
        <div className="mb-7 flex items-start justify-between gap-6">
          <div>
            <div className="mb-2.5 flex items-center gap-3 text-[13px] text-text-tertiary">
              <Badge variant={incidentStarted ? severityVariant(incidentStarted.severity) : "p1"}>
                {incidentStarted?.severity ?? "…"}
              </Badge>
              <span className="font-mono text-text-secondary">{params.id}</span>
            </div>
            <h1 className="mb-2 text-2xl font-semibold tracking-tight">
              {incidentStarted?.title ?? "Loading incident…"}
            </h1>
            <p className="mt-3.5 max-w-[760px] text-text-secondary">
              Watched system: {incidentStarted?.watched_project ?? "—"}.{" "}
              {sseDroppedBeforeTerminal && !fallbackFinished
                ? "Live updates dropped — recovering from backend…"
                : sseDroppedBeforeTerminal && fallbackFinished
                ? "Live updates dropped — recovered final state from backend."
                : `Stream status: ${stream.status}.`}
              {stream.error && !sseDroppedBeforeTerminal && ` Error: ${stream.error}`}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2 text-right">
            <div className="text-[11px] uppercase tracking-wider text-text-tertiary">Elapsed</div>
            <div className="font-mono text-[22px] font-medium tracking-tight">{formatMs(elapsedMs)}</div>
          </div>
        </div>

        {/* Phase 8 / ADR-025 — HumanOverrideGate banner */}
        {showGateBanner && gateAwaiting && (
          <section className="mb-8 rounded-md border border-accent-border bg-accent-bg p-5">
            <div className="mb-1 flex items-center gap-2">
              <Badge variant="p1">Awaiting human approval</Badge>
              <span className="text-[13px] font-semibold text-accent-text">
                {gateAwaiting.action_type === "regulator_notification"
                  ? "Regulator notification draft"
                  : gateAwaiting.action_type}
              </span>
            </div>
            <p className="mt-1 max-w-[860px] text-[14px] leading-relaxed text-text">
              {gateAwaiting.action_summary}
            </p>
            <div className="mt-3 flex items-center gap-2">
              <Button
                variant="primary"
                onClick={() => resolveGate("approve")}
                disabled={gateActing}
              >
                Approve
              </Button>
              <Button
                variant="secondary"
                onClick={() => resolveGate("reject")}
                disabled={gateActing}
              >
                Reject
              </Button>
              <span className="ml-2 text-xs text-text-tertiary">
                Auto-rejects at {gateAwaiting.timeout_at_iso}
              </span>
            </div>
          </section>
        )}
        {gateResolved && (
          <section className="mb-6 rounded-md border border-border bg-bg-subtle px-4 py-2.5 text-[13px] text-text-secondary">
            Gate {gateResolved.gate_id} resolved:{" "}
            <span className="font-semibold text-text">{gateResolved.decision}</span>
            {gateResolved.operator_note && ` · ${gateResolved.operator_note}`}
          </section>
        )}

        {/* Metric row */}
        <div className="mb-8 grid grid-cols-4 gap-4">
          <MetricCard
            label="Round-trips"
            value={roundTripsValue}
            {...(roundTripsDelta ? { delta: roundTripsDelta } : {})}
          />
          <MetricCard label="Traces analyzed" value={tracesValue} {...(tracesSub ? { sub: tracesSub } : {})} />
          <MetricCard label="Error rate" value={`${errorRate}%`} sub="baseline 7.2%" />
          <MetricCard
            label="Completeness"
            value={postmortemValidated ? postmortemValidated.completeness_score.toFixed(3) : "—"}
            sub="scored after postmortem"
          />
        </div>

        {/* Stepper */}
        <section className="mb-8">
          <div className="mb-3.5 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
              Agent activity
            </span>
            <span className="text-xs text-text-tertiary">live · server-sent events</span>
          </div>
          <div className="rounded-md border border-border bg-bg px-6 py-2">
            {/* Stepper split with RoutingCallout interleaved between Coordinator and the rest. */}
            <AgentStepper steps={steps.slice(0, 1)} />
            <RoutingCallout
              label={briefing?.cold_start ? "Cold start" : "Learned routing"}
              body={routingBody}
              source={routingSource}
            />
            <AgentStepper steps={steps.slice(1)} />
          </div>
        </section>

        {/* Similar past incidents — only rendered when the RAG layer found matches. */}
        {briefing && briefing.similar_past_incidents.length > 0 && (
          <section className="mb-8">
            <div className="mb-3.5 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Similar past incidents
              </span>
              <span className="text-xs text-text-tertiary">
                top {briefing.similar_past_incidents.length} · cosine similarity over
                Vertex text-embedding-004
              </span>
            </div>
            <div className="rounded-md border border-border bg-bg">
              <ul className="divide-y divide-border">
                {briefing.similar_past_incidents.map((sim) => (
                  <li
                    key={sim.incident_id}
                    className="flex items-center justify-between gap-4 px-5 py-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[13px] text-text">{sim.title}</div>
                      <div className="mt-0.5 font-mono text-xs text-text-tertiary">
                        {sim.scenario_id} · {sim.incident_id}
                      </div>
                    </div>
                    <div className="shrink-0 font-mono text-[13px] text-text-secondary tabular-nums">
                      {sim.similarity.toFixed(3)}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}

        {/* Determinism — static demo data; faithful to the design */}
        <section className="mb-10">
          <div className="mb-3.5 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
              Self-improvement loop · determinism delta
            </span>
            <span className="text-xs text-text-tertiary">across last 5 reproduction runs</span>
          </div>
          <div className="rounded-md border border-border bg-bg p-6">
            <DeterminismBars
              cold={{
                title: "Cold start",
                badge: { label: "no prior context" },
                caption:
                  "Without Phoenix MCP introspection, coordinator picks root_cause first and runs the full chain.",
                variant: "cold",
                rows: [
                  { label: "Round trips", fillPct: 75, count: "3 of 4" },
                  { label: "First route", fillPct: 100, count: "root_cause" },
                  { label: "Wall clock", fillPct: 100, count: "~32s" },
                ],
              }}
              warm={{
                title: "Warm",
                badge: { label: "5 / 5 deterministic", variant: "ok" },
                caption:
                  "With prior-run directive: skips eval_runner, opens with trace_analyzer. Identical path 5/5.",
                variant: "warm",
                rows: [
                  { label: "Round trips", fillPct: 50, count: "2 of 4" },
                  { label: "First route", fillPct: 100, count: "trace_analyzer" },
                  { label: "Wall clock", fillPct: 47, count: "~15s" },
                ],
              }}
            />
          </div>
        </section>

        {/* Footer action bar */}
        <div className="mt-10 flex items-center justify-between border-t border-border py-5">
          <div className="text-[13px] text-text-tertiary">
            Phoenix trace tree available at{" "}
            <a
              href={PHOENIX_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-text-secondary underline-offset-2 hover:underline"
            >
              {new URL(PHOENIX_URL).host}
            </a>
          </div>
          <div className="flex gap-2">
            <a
              href={PHOENIX_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="secondary" disabled={!completed}>
                {completed ? "View Phoenix" : "Waiting for run to finish…"}
              </Button>
            </a>
            {completed ? (
              <Link href={`/incidents/${encodeURIComponent(params.id)}/postmortem` as Route}>
                <Button variant="primary">View postmortem →</Button>
              </Link>
            ) : (
              <Button variant="primary" disabled>
                Pipeline running…
              </Button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
