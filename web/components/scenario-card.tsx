import Link from "next/link";
import type { Route } from "next";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Scenario } from "@/lib/scenarios";
import { severityVariant } from "@/lib/severity";

interface ScenarioCardProps {
  scenario: Scenario;
  href: Route;
}

export function ScenarioCard({ scenario, href }: ScenarioCardProps) {
  return (
    <Link
      href={href}
      className="flex flex-col rounded-md border border-border bg-bg p-6 transition-all hover:border-border-strong hover:shadow"
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          {scenario.workflow}
        </span>
        <Badge variant={severityVariant(scenario.severity)}>{scenario.severity}</Badge>
      </div>
      <h2 className="mb-2 text-base font-semibold leading-snug">{scenario.title}</h2>
      <p className="mb-5 flex-1 text-[13px] leading-relaxed text-text-secondary">
        {scenario.short_description}
      </p>
      <div className="flex items-center justify-between border-t border-border pt-4 text-xs text-text-tertiary">
        <span>
          {scenario.watched_project} · {scenario.seeded_spans} spans seeded
        </span>
        <span className="inline-flex items-center gap-1 font-medium text-text">
          Run pipeline <ArrowRight className="h-3.5 w-3.5" />
        </span>
      </div>
    </Link>
  );
}
