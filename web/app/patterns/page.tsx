"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorBlock,
  PageShell,
  SkeletonRows,
} from "@/components/page-shell";
import {
  acceptPattern,
  fetchPatterns,
  rejectPattern,
  type PatternProposalDto,
} from "@/lib/api";

export default function PatternsPage() {
  const qc = useQueryClient();
  const { data, isPending, error } = useQuery({
    queryKey: ["patterns"],
    queryFn: ({ signal }) => fetchPatterns(signal),
    retry: 0,
  });

  const accept = useMutation({
    mutationFn: acceptPattern,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["patterns"] }),
  });
  const reject = useMutation({
    mutationFn: rejectPattern,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["patterns"] }),
  });

  return (
    <div className="min-h-screen">
      <Topbar active="patterns" />
      <PageShell
        title="Mined patterns"
        subtitle="Recurring incident clusters surfaced by the PatternMiner (Phase 8 / ADR-021). Operator-gated promotion: accept to add as a Coordinator directive; reject to suppress."
      >
        {isPending && <SkeletonRows />}
        {error && (
          <ErrorBlock
            message={`Failed to load patterns: ${error instanceof Error ? error.message : String(error)}`}
          />
        )}
        {data && data.length === 0 && (
          <EmptyState message="No recurring patterns detected yet — incident corpus is too small or clusters are below the size/cohesion floor." />
        )}
        {data && data.length > 0 && (
          <div className="grid gap-4">
            {data.map((p: PatternProposalDto) => (
              <article
                key={p.cluster_id}
                className="rounded-md border border-border bg-bg p-5"
              >
                <header className="mb-3 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge variant="ok">{p.proposed_mitigation_type}</Badge>
                      <span className="font-mono text-xs text-text-tertiary">
                        {p.cluster_id}
                      </span>
                      {p.status !== "proposed" && (
                        <Badge variant={p.status === "accepted" ? "ok" : "p1"}>
                          {p.status}
                        </Badge>
                      )}
                    </div>
                    <h2 className="text-[15px] font-semibold leading-snug">
                      {p.representative_root_cause}
                    </h2>
                  </div>
                  <div className="shrink-0 text-right text-xs text-text-tertiary">
                    <div>
                      {p.member_count} incidents · cohesion{" "}
                      {p.avg_pair_similarity.toFixed(2)}
                    </div>
                  </div>
                </header>
                <p className="mb-3 text-[13.5px] leading-relaxed text-text-secondary">
                  {p.proposed_mitigation_text}
                </p>
                <div className="mb-3 font-mono text-xs text-text-tertiary">
                  Members: {p.member_incident_ids.join(", ")}
                </div>
                {p.status === "proposed" && (
                  <div className="flex gap-2">
                    <Button
                      variant="primary"
                      onClick={() => accept.mutate(p.cluster_id)}
                      disabled={accept.isPending || reject.isPending}
                    >
                      Accept
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => reject.mutate(p.cluster_id)}
                      disabled={accept.isPending || reject.isPending}
                    >
                      Reject
                    </Button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </PageShell>
    </div>
  );
}
