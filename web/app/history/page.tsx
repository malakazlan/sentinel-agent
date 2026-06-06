"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/topbar";
import { Badge } from "@/components/ui/badge";
import {
  EmptyState,
  ErrorBlock,
  PageShell,
  SkeletonRows,
} from "@/components/page-shell";
import { fetchIncidentsHistory, type PastIncident } from "@/lib/api";
import { severityVariant } from "@/lib/severity";
import type { Severity } from "@/lib/types";

const SEVERITY_OPTIONS: Severity[] = ["P0", "P1", "P2", "P3"];

export default function HistoryPage() {
  const [severity, setSeverity] = useState<Severity | "">("");
  const [scenarioId, setScenarioId] = useState("");

  const { data, isPending, error } = useQuery({
    queryKey: ["incidents-history", severity, scenarioId],
    queryFn: ({ signal }) =>
      fetchIncidentsHistory(
        {
          ...(severity ? { severity } : {}),
          ...(scenarioId ? { scenario_id: scenarioId } : {}),
        },
        signal,
      ),
    retry: 0,
  });

  return (
    <div className="min-h-screen">
      <Topbar active="history" />
      <PageShell
        title="Incident history"
        subtitle="Past incidents from the memory store. Filter by severity or scenario."
      >
        <div className="mb-6 flex flex-wrap gap-3">
          <FilterChips
            label="Severity"
            value={severity}
            options={["", ...SEVERITY_OPTIONS]}
            onChange={(v) => setSeverity(v as Severity | "")}
          />
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <span>Scenario id:</span>
            <input
              type="text"
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              placeholder="e.g. fraud-fp-burst"
              className="rounded-sm border border-border bg-bg px-2 py-1 font-mono text-xs"
            />
          </label>
        </div>

        {isPending && <SkeletonRows />}
        {error && (
          <ErrorBlock
            message={`Failed to load history: ${error instanceof Error ? error.message : String(error)}`}
          />
        )}
        {data && data.incidents.length === 0 && (
          <EmptyState message="No incidents match the current filters." />
        )}
        {data && data.incidents.length > 0 && (
          <div className="overflow-hidden rounded-md border border-border bg-bg">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border bg-bg-subtle">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                    Severity
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                    Title
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                    Scenario
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                    Completeness
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                    Incident id
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.incidents.map((i: PastIncident, idx: number) => (
                  <tr
                    key={i.incident_id ?? idx}
                    className="border-b border-border last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      {i.severity ? (
                        <Badge variant={severityVariant(i.severity as Severity)}>
                          {i.severity}
                        </Badge>
                      ) : (
                        <span className="text-text-tertiary">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[13.5px]">
                      {i.title ?? "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-text-secondary">
                      {i.scenario_id ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] tabular-nums">
                      {i.completeness_score != null
                        ? i.completeness_score.toFixed(3)
                        : "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-text-tertiary">
                      {i.incident_id ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageShell>
    </div>
  );
}

function FilterChips({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-2 text-xs text-text-secondary">
      <span>{label}:</span>
      <div className="flex gap-1">
        {options.map((opt) => {
          const selected = value === opt;
          return (
            <button
              key={opt || "any"}
              type="button"
              onClick={() => onChange(opt)}
              className={`rounded-sm border px-2 py-1 font-mono text-xs ${
                selected
                  ? "border-cta-bg bg-cta-bg text-cta-text"
                  : "border-border bg-bg hover:bg-bg-inset"
              }`}
            >
              {opt || "any"}
            </button>
          );
        })}
      </div>
    </div>
  );
}
