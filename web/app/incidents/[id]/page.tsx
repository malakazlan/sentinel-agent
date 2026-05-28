"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo } from "react";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/metric-card";
import { AgentStepper, type AgentStep, type StepStatus } from "@/components/agent-stepper";
import { RoutingCallout } from "@/components/routing-callout";
import { DeterminismBars } from "@/components/determinism-bars";
import { useIncidentStream } from "@/lib/sse";
import type { IncidentEvent, StageName } from "@/lib/types";

const STAGES_IN_ORDER: { stage: StageName; name: string; model: string }[] = [
  { stage: "investigate", name: "Trace analyzer", model: "gemini-3.1-flash-lite" },
  { stage: "root_cause", name: "Root cause", model: "gemini-3.1-pro" },
  { stage: "remediation", name: "Remediation", model: "gemini-3.1-pro" },
  { stage: "postmortem", name: "Postmortem", model: "gemini-3.1-flash-lite" },
];

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function severityVariant(sev: string): "p0" | "p1" | "p2" | "p3" {
  const lc = sev.toLowerCase();
  if (lc === "p0" || lc === "p1" || lc === "p2" || lc === "p3") return lc;
  return "p1";
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
  const seedCompleted = stream.events.find(
    (e): e is Extract<IncidentEvent, { type: "seed_completed" }> => e.type === "seed_completed"
  );
  const postmortemValidated = stream.events.find(
    (e): e is Extract<IncidentEvent, { type: "postmortem_validated" }> => e.type === "postmortem_validated"
  );
  const completed = stream.events.find(
    (e) => e.type === "incident_completed" || e.type === "incident_failed"
  );

  const elapsedMs = stream.events.length > 0
    ? stream.events[stream.events.length - 1]?.elapsed_ms ?? 0
    : 0;

  const steps = useMemo(() => deriveStepper(stream.events), [stream.events]);

  const tracesValue = seedCompleted ? `${seedCompleted.spans_written}` : "—";
  const tracesSub = seedCompleted ? `${seedCompleted.n_ok} OK · ${seedCompleted.n_error} ERROR` : undefined;
  const errorRate = seedCompleted
    ? ((seedCompleted.n_error / Math.max(1, seedCompleted.n_error + seedCompleted.n_ok)) * 100).toFixed(1)
    : "—";

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
              Watched system: {incidentStarted?.watched_project ?? "—"}. Stream status: {stream.status}.
              {stream.error && ` Error: ${stream.error}`}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2 text-right">
            <div className="text-[11px] uppercase tracking-wider text-text-tertiary">Elapsed</div>
            <div className="font-mono text-[22px] font-medium tracking-tight">{formatMs(elapsedMs)}</div>
          </div>
        </div>

        {/* Metric row */}
        <div className="mb-8 grid grid-cols-4 gap-4">
          <MetricCard label="Round-trips" value="2" delta={{ value: "−1 vs cold (3)", positive: true }} />
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
              body="Skip eval_runner on first turn — hallucination eval is no-op when traces lack tool calls (observed in 12 of 17 prior runs)."
              source="Source: Phoenix MCP · runs of last 30 days · confidence high"
            />
            <AgentStepper steps={steps.slice(1)} />
          </div>
        </section>

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
            <span className="font-mono text-text-secondary">localhost:6006</span>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={!completed}>
              {completed ? "View Phoenix" : "Waiting for run to finish…"}
            </Button>
            <Link href={`/incidents/${encodeURIComponent(params.id)}/postmortem` as Route}>
              <Button variant="primary" disabled={!completed}>
                {completed ? "View postmortem →" : "Pipeline running…"}
              </Button>
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
