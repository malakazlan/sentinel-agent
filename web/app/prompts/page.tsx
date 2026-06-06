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
import { fetchPromptsOverview, type PromptRollup } from "@/lib/api";

function scoreVariant(score: number): "ok" | "p2" | "p1" {
  if (score >= 0.9) return "ok";
  if (score >= 0.8) return "p2";
  return "p1";
}

export default function PromptsPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["prompts"],
    queryFn: ({ signal }) => fetchPromptsOverview(signal),
    retry: 0,
  });

  return (
    <div className="min-h-screen">
      <Topbar active="prompts" />
      <PageShell
        title="Prompts"
        subtitle="Per-agent prompt versions + rolling critic scores. PromptEvolver proposes refinements when an agent's rolling average dips below 0.80. Phase 8 / ADR-020."
      >
        {isPending && <SkeletonRows />}
        {error && (
          <ErrorBlock
            message={`Failed to load prompts overview: ${error instanceof Error ? error.message : String(error)}`}
          />
        )}
        {data && data.agents.length === 0 && (
          <EmptyState message="No prompt history yet — run incidents to populate the rolling window." />
        )}
        {data && data.agents.length > 0 && (
          <section>
            <div className="mb-3.5 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
              Per-agent rolling rollup
            </div>
            <div className="overflow-hidden rounded-md border border-border bg-bg">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-bg-subtle">
                    <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                      Agent
                    </th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                      Prompt
                    </th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                      Samples
                    </th>
                    <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                      Avg score
                    </th>
                    <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                      Last run
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.agents.map((a: PromptRollup) => (
                    <tr
                      key={a.agent_name}
                      className="border-b border-border last:border-b-0"
                    >
                      <td className="px-4 py-3 text-[14px] font-medium">
                        {a.agent_name}
                      </td>
                      <td className="px-4 py-3 font-mono text-[12.5px] text-text-secondary">
                        {a.current_prompt_version}
                      </td>
                      <td className="px-4 py-3 text-[13px] tabular-nums text-text-secondary">
                        {a.sample_count}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Badge variant={scoreVariant(a.avg_aggregate_score)}>
                          {a.avg_aggregate_score.toFixed(3)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-text-tertiary">
                        {a.last_record_timestamp || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </PageShell>
    </div>
  );
}
