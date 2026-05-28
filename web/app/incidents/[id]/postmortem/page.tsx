"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import { Button } from "@/components/ui/button";
import { PostmortemDocument } from "@/components/postmortem-document";
import { getIncident } from "@/lib/api";
import type { IncidentResult, IncidentResultCompleted } from "@/lib/types";

function isCompleted(r: IncidentResult): r is IncidentResultCompleted {
  return "succeeded" in r && r.succeeded === true;
}

export default function PostmortemPage({ params }: { params: { id: string } }) {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["incident", params.id],
    queryFn: ({ signal }) => getIncident(params.id, signal),
    retry: 0,
  });

  return (
    <div className="min-h-screen">
      <Topbar
        active="postmortem"
        status={
          data && isCompleted(data) && data.completeness
            ? { label: `Validated · completeness ${data.completeness.score.toFixed(3)}` }
            : { label: "—" }
        }
        incidentId={params.id}
      />
      <main className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-10">
        {isPending && <p className="text-text-secondary">Loading postmortem…</p>}
        {error && (
          <div className="rounded-md border border-error/30 bg-error-bg p-4 text-sm text-error">
            Failed to load postmortem: {error instanceof Error ? error.message : String(error)}.
            <Button variant="ghost" className="ml-2" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        )}
        {data && !isCompleted(data) && "status" in data && data.status === "running" && (
          <p className="text-text-secondary">Pipeline still running — refresh in a moment.</p>
        )}
        {data && !isCompleted(data) && "error" in data && (
          <div className="rounded-md border border-error/30 bg-error-bg p-4 text-sm text-error">
            Pipeline failed: {data.error}
          </div>
        )}
        {data && isCompleted(data) && data.postmortem && (
          <>
            <PostmortemDocument
              pm={data.postmortem}
              {...(data.completeness?.score !== undefined ? { completenessScore: data.completeness.score } : {})}
              {...(data.completeness?.label ? { completenessLabel: data.completeness.label } : {})}
              {...(data.seed_summary?.project ? { watchedProject: data.seed_summary.project } : {})}
            />
            <div className="mx-auto mt-12 flex max-w-[820px] items-center justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  if (data.postmortem) {
                    navigator.clipboard.writeText(JSON.stringify(data.postmortem, null, 2));
                  }
                }}
              >
                Copy JSON
              </Button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
