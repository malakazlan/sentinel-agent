"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import {
  EmptyState,
  ErrorBlock,
  PageShell,
  SkeletonRows,
} from "@/components/page-shell";
import { fetchArchitecture, type ArchitectureAgent } from "@/lib/api";

export default function ArchitecturePage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["architecture"],
    queryFn: ({ signal }) => fetchArchitecture(signal),
    retry: 0,
  });

  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="min-h-screen">
      <Topbar active="architecture" />
      <PageShell
        title="Architecture"
        subtitle="Sentinel's multi-agent topology — click an agent to see its role, model, and the ADR justifying it."
      >
        {isPending && <SkeletonRows />}
        {error && (
          <ErrorBlock
            message={`Failed to load architecture: ${error instanceof Error ? error.message : String(error)}`}
          />
        )}
        {data && data.agents.length === 0 && (
          <EmptyState message="No agents registered." />
        )}
        {data && data.agents.length > 0 && (
          <div className="grid grid-cols-[260px_1fr] gap-6">
            <nav className="overflow-hidden rounded-md border border-border bg-bg">
              {data.agents.map((a: ArchitectureAgent) => {
                const isSelected = selected === a.name;
                return (
                  <button
                    key={a.name}
                    type="button"
                    onClick={() => setSelected(a.name)}
                    className={`block w-full border-b border-border px-4 py-2.5 text-left last:border-b-0 ${
                      isSelected
                        ? "bg-bg-inset text-text"
                        : "text-text-secondary hover:bg-bg-subtle"
                    }`}
                  >
                    <div className="text-[13px] font-medium">{a.name}</div>
                    <div className="mt-0.5 font-mono text-xs text-text-tertiary">
                      {a.adr}
                    </div>
                  </button>
                );
              })}
            </nav>
            <div>
              {selected ? (
                <AgentDetail
                  agent={data.agents.find((a) => a.name === selected) as ArchitectureAgent}
                />
              ) : (
                <EmptyState message="Select an agent on the left to view its role + ADR." />
              )}
            </div>
          </div>
        )}
      </PageShell>
    </div>
  );
}

function AgentDetail({ agent }: { agent: ArchitectureAgent }) {
  return (
    <article className="rounded-md border border-border bg-bg p-6">
      <h2 className="mb-1 text-xl font-semibold">{agent.name}</h2>
      <div className="mb-4 font-mono text-xs text-text-tertiary">
        {agent.model} · {agent.adr}
      </div>
      <p className="text-[14px] leading-relaxed">{agent.role}</p>
    </article>
  );
}
