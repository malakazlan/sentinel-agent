"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/metric-card";
import {
  EmptyState,
  ErrorBlock,
  PageShell,
  SkeletonRows,
} from "@/components/page-shell";
import { fetchSentinelHealth, type SentinelHealthAgent } from "@/lib/api";

function flagVariant(flag: string): "ok" | "p2" | "p1" | "p0" {
  switch (flag) {
    case "healthy":
      return "ok";
    case "watch":
      return "p2";
    case "degraded":
      return "p1";
    default:
      return "p0";
  }
}

function trendArrow(slope: number): string {
  if (slope > 0.005) return "↗";
  if (slope < -0.005) return "↘";
  return "→";
}

export default function SentinelHealthPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["sentinel-health"],
    queryFn: ({ signal }) => fetchSentinelHealth(signal),
    retry: 0,
  });

  return (
    <div className="min-h-screen">
      <Topbar active="health" />
      <PageShell
        title="Sentinel health"
        subtitle="Recursive observability: Sentinel watches its own per-agent critic scores + trend slopes. Phase 8 / ADR-026."
      >
        {isPending && <SkeletonRows />}
        {error && (
          <ErrorBlock
            message={`Failed to load health: ${error instanceof Error ? error.message : String(error)}`}
          />
        )}
        {data && data.agents.length === 0 && (
          <EmptyState message="No agent telemetry yet — run some incidents to populate the prompt-history store." />
        )}
        {data && data.agents.length > 0 && (
          <>
            <div className="mb-8 grid grid-cols-4 gap-4">
              <MetricCard label="Healthy" value={`${data.healthy_count}`} />
              <MetricCard label="Watch" value={`${data.watch_count}`} />
              <MetricCard label="Degraded" value={`${data.degraded_count}`} />
              <MetricCard
                label="Underperforming"
                value={`${data.underperforming_count}`}
              />
            </div>
            <section>
              <div className="mb-3.5 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Per-agent snapshot
              </div>
              <div className="grid gap-2">
                {data.agents.map((a: SentinelHealthAgent) => (
                  <div
                    key={a.agent_name}
                    className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-4 rounded-md border border-border bg-bg px-4 py-3"
                  >
                    <div>
                      <div className="text-[14px] font-medium">{a.agent_name}</div>
                      <div className="text-xs text-text-tertiary">
                        {a.sample_count} runs · {a.last_record_timestamp || "—"}
                      </div>
                    </div>
                    <div className="font-mono text-[15px] tabular-nums">
                      {a.avg_aggregate_score.toFixed(3)}
                    </div>
                    <div
                      className="font-mono text-sm text-text-secondary"
                      title={`trend slope = ${a.trend_slope}`}
                    >
                      {trendArrow(a.trend_slope)}
                    </div>
                    <Badge variant={flagVariant(a.health_flag)}>
                      {a.health_flag}
                    </Badge>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </PageShell>
    </div>
  );
}
