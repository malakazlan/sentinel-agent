"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import {
  EmptyState,
  ErrorBlock,
  PageShell,
  SkeletonRows,
} from "@/components/page-shell";
import { fetchEvalsTrends, type EvalTrendAgent } from "@/lib/api";

function scoreVariant(score: number): "ok" | "p2" | "p1" {
  if (score >= 0.9) return "ok";
  if (score >= 0.8) return "p2";
  return "p1";
}

export default function EvalsPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["evals-trends"],
    queryFn: ({ signal }) => fetchEvalsTrends(signal),
    retry: 0,
  });

  return (
    <div className="min-h-screen">
      <Topbar active="evals" />
      <PageShell
        title="Evals"
        subtitle="CriticAgent rubric scores over time, per agent + per dimension."
      >
        {isPending && <SkeletonRows />}
        {error && (
          <ErrorBlock
            message={`Failed to load eval trends: ${error instanceof Error ? error.message : String(error)}`}
          />
        )}
        {data && data.agents.length === 0 && (
          <EmptyState message="No eval data yet — run incidents to populate the critic-score history." />
        )}
        {data && data.agents.length > 0 && (
          <div className="grid gap-4">
            {data.agents.map((a: EvalTrendAgent) => (
              <article
                key={a.agent_name}
                className="rounded-md border border-border bg-bg p-5"
              >
                <header className="mb-3 flex items-baseline justify-between">
                  <h2 className="text-[15px] font-semibold">{a.agent_name}</h2>
                  <div className="flex items-center gap-2 text-xs text-text-tertiary">
                    <span>{a.point_count} runs</span>
                    <span>·</span>
                    <Badge variant={scoreVariant(a.avg_aggregate)}>
                      avg {a.avg_aggregate.toFixed(3)}
                    </Badge>
                  </div>
                </header>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {Object.entries(a.avg_rubric).map(([dim, score]) => (
                    <div
                      key={dim}
                      className="rounded border border-border bg-bg-subtle px-3 py-2"
                    >
                      <div className="text-xs text-text-tertiary">{dim}</div>
                      <div className="font-mono text-[14px] tabular-nums">
                        {score.toFixed(3)}
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </PageShell>
    </div>
  );
}
