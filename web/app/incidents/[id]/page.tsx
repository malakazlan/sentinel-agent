import Link from "next/link";
import type { Route } from "next";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/metric-card";
import { AgentStepper, type AgentStep } from "@/components/agent-stepper";
import { RoutingCallout } from "@/components/routing-callout";
import { DeterminismBars } from "@/components/determinism-bars";

// Static placeholder data — replaced by SSE wiring in Task 7.
const STEPS: AgentStep[] = [
  {
    name: "Coordinator",
    model: "gemini-3.1-pro",
    status: "done",
    action: "Synthesized prior context from Phoenix MCP — 17 past investigations, derived 1 routing directive.",
    meta: "+0s · 4.2s",
  },
  {
    name: "Trace analyzer",
    model: "gemini-3.1-flash-lite",
    status: "done",
    action:
      "Pulled 50 root traces · identified bimodal pattern: 12 ERROR clustered on electronics merchant_category, $800–$1,350 range.",
    meta: "+4.2s · 58.1s",
  },
  {
    name: "Eval runner",
    status: "skipped",
    action: "Skipped per learned routing directive.",
    meta: "—",
    badge: { label: "skipped" },
  },
  {
    name: "Root cause",
    model: "gemini-3.1-pro",
    status: "done",
    action:
      "Hypothesis 1 (high confidence): over-sensitive thresholding for electronics > $800. true_label = APPROVE on every error span.",
    meta: "+62.3s · 60.8s",
  },
  {
    name: "Remediation",
    status: "running",
    action: "Drafting patched prompt + electronics_false_positive_rate eval guardrail…",
    meta: "+123.1s · 40.4s",
    badge: { label: "running", variant: "running" },
  },
  {
    name: "Postmortem",
    status: "queued",
    action: "Awaiting remediation. Will emit validated Google-SRE document.",
    meta: "queued",
  },
];

export default function IncidentPage({ params }: { params: { id: string } }) {
  return (
    <div className="min-h-screen">
      <Topbar
        active="console"
        status={{ dot: "running", label: "Pipeline running" }}
        context="fraud-detector-prod"
      />
      <main className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-10">
        {/* Incident header */}
        <div className="mb-7 flex items-start justify-between gap-6">
          <div>
            <div className="mb-2.5 flex items-center gap-3 text-[13px] text-text-tertiary">
              <Badge variant="p1">P1</Badge>
              <span className="font-mono text-text-secondary">fraud-fp-spike-20260526T133012Z</span>
              <span>·</span>
              <span>Fraud detection</span>
              <span>·</span>
              <span>fraud-detector-prod-us-central1</span>
            </div>
            <h1 className="mb-2 text-2xl font-semibold tracking-tight">
              False-positive burst on electronics classifier
            </h1>
            <p className="mt-3.5 max-w-[760px] text-text-secondary">
              FP rate spiked to 21.3% on the electronics merchant category, 3× the 7.2% baseline.
              1,247 transactions blocked, 312 accounts frozen since onset. Watched system:
              fraud-classifier-v2.3.1, deployed 18 minutes before alert.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2 text-right">
            <div className="text-[11px] uppercase tracking-wider text-text-tertiary">Elapsed</div>
            <div className="font-mono text-[22px] font-medium tracking-tight">02:43</div>
            <Button variant="secondary" className="mt-2">Pause</Button>
          </div>
        </div>

        {/* Metric row */}
        <div className="mb-8 grid grid-cols-4 gap-4">
          <MetricCard label="Round-trips" value="2" delta={{ value: "−1 vs cold (3)", positive: true }} />
          <MetricCard label="Traces analyzed" value="42" sub="30 OK · 12 ERROR" />
          <MetricCard label="Error rate" value="28.6%" sub="baseline 7.2%" />
          <MetricCard label="Completeness" value="—" sub="scored after postmortem" />
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
            <AgentStepper steps={STEPS.slice(0, 1)} />
            <RoutingCallout
              body="Skip eval_runner on first turn — hallucination eval is no-op when traces lack tool calls (observed in 12 of 17 prior runs)."
              source="Source: Phoenix MCP · runs of last 30 days · confidence high"
            />
            <AgentStepper steps={STEPS.slice(1)} />
          </div>
        </section>

        {/* Determinism */}
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
            <span className="font-mono text-text-secondary">localhost:6006/projects/fraud-detector-prod</span>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary">Open in Phoenix</Button>
            <Link href={`/incidents/${params.id}/postmortem` as Route}>
              <Button variant="primary">View postmortem →</Button>
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
