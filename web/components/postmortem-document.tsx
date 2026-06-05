import { Badge } from "@/components/ui/badge";
import type { ImpactReport, Postmortem } from "@/lib/types";
import { severityVariant } from "@/lib/severity";

const TIMELINE_SEPARATOR = " — ";

const USD_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const INT_FORMATTER = new Intl.NumberFormat("en-US");

function formatUsd(value: number): string {
  return USD_FORMATTER.format(Math.round(value));
}

function formatTrustDelta(delta: number): string {
  const sign = delta < 0 ? "" : "+";
  return `${sign}${(delta * 100).toFixed(1)} pts`;
}

function confidenceLabel(c: ImpactReport["confidence"]): string {
  switch (c) {
    case "seed_grounded":
      return "Seed-grounded";
    case "scenario_inferred":
      return "Scenario-inferred";
    case "default_caveat":
      return "Default (caveat)";
  }
}

function confidenceVariant(
  c: ImpactReport["confidence"],
): "ok" | "p1" | "p2" {
  // Map provenance to existing Badge variants without inventing a new one:
  //   seed_grounded → "ok" (green / validated)
  //   scenario_inferred → "p2" (amber / treat with caution)
  //   default_caveat → "p1" (red-leaning / suspect figures)
  if (c === "seed_grounded") return "ok";
  if (c === "scenario_inferred") return "p2";
  return "p1";
}

interface PostmortemDocumentProps {
  pm: Postmortem;
  completenessLabel?: string;
  completenessScore?: number;
  generatedRelative?: string;
  watchedProject?: string;
  watchedModel?: string;
}

export function PostmortemDocument({
  pm,
  completenessLabel,
  completenessScore,
  generatedRelative,
  watchedProject,
  watchedModel,
}: PostmortemDocumentProps) {
  return (
    <div className="mx-auto max-w-[820px]">
      <header className="mb-8 border-b border-border pb-6">
        <div className="mb-3.5 flex items-center gap-2.5">
          <Badge variant={severityVariant(pm.severity)}>{pm.severity}</Badge>
          {completenessScore !== undefined && (
            <Badge variant="ok">
              Validated · {completenessScore.toFixed(3)}
              {completenessLabel && ` · ${completenessLabel}`}
            </Badge>
          )}
          <span className="font-mono text-xs text-text-tertiary">{pm.incident_id}</span>
        </div>
        <h1 className="mb-3 text-[32px] font-semibold leading-tight tracking-tight">{pm.title}</h1>
        <div className="flex items-center gap-4 text-[13px] text-text-tertiary">
          {generatedRelative && <span>Generated {generatedRelative}</span>}
          {watchedModel && (
            <>
              <span>·</span>
              <span>{watchedModel}</span>
            </>
          )}
          {watchedProject && (
            <>
              <span>·</span>
              <span>{watchedProject}</span>
            </>
          )}
        </div>
      </header>

      {pm.impact_quantified && (
        <ImpactHero impact={pm.impact_quantified} />
      )}

      <Section label="Summary">{pm.summary}</Section>
      <Section label="Impact">{pm.impact}</Section>

      {pm.impact_quantified && (
        <ImpactQuantifiedSection impact={pm.impact_quantified} />
      )}

      <section className="mb-7">
        <SectionLabel>Timeline</SectionLabel>
        <ul>
          {pm.timeline.map((entry, idx) => {
            const splitIdx = entry.indexOf(TIMELINE_SEPARATOR);
            const time = splitIdx > 0 ? entry.slice(0, splitIdx) : entry;
            const text = splitIdx > 0 ? entry.slice(splitIdx + TIMELINE_SEPARATOR.length) : "";
            return (
              <li
                key={idx}
                className="grid grid-cols-[130px_1fr] gap-4 border-b border-border py-2 last:border-b-0"
              >
                <span className="pt-0.5 font-mono text-[12.5px] text-text-secondary">{time}</span>
                <span>{text}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <Section label="Root cause">{pm.root_cause}</Section>
      <Section label="Detection">{pm.detection}</Section>
      <Section label="Resolution">{pm.resolution}</Section>

      <section className="mb-7">
        <SectionLabel>Action items</SectionLabel>
        <div className="grid gap-3">
          {pm.action_items.map((ai, idx) => (
            <div
              key={idx}
              className="grid grid-cols-[1fr_auto] items-start gap-4 rounded border border-border px-4 py-3.5"
            >
              <div className="text-sm leading-relaxed">{ai.description}</div>
              <div className="flex flex-col items-end gap-1 whitespace-nowrap text-xs text-text-tertiary">
                <Badge variant={severityVariant(ai.severity)}>{ai.severity}</Badge>
                <span>{ai.owner_role}</span>
                <span>{ai.due_within_days} days</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-7">
        <SectionLabel>Lessons learned</SectionLabel>
        <ul>
          {pm.lessons_learned.map((l, idx) => (
            <li
              key={idx}
              className="relative border-b border-border py-2.5 pl-[18px] last:border-b-0"
            >
              <span
                aria-hidden="true"
                className="absolute left-0 top-[18px] block h-1.5 w-1.5 rounded-full bg-text-tertiary"
              />
              {l}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
      {children}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="mb-7">
      <SectionLabel>{label}</SectionLabel>
      <p className="text-[14.5px] leading-relaxed">{children}</p>
    </section>
  );
}

/** Hero strip: four metrics + confidence badge. Renders right under the title. */
function ImpactHero({ impact }: { impact: ImpactReport }) {
  return (
    <section className="mb-8 rounded-md border border-border bg-bg p-6">
      <div className="mb-4 flex items-center justify-between">
        <SectionLabel>Quantified impact</SectionLabel>
        <Badge variant={confidenceVariant(impact.confidence)}>
          {confidenceLabel(impact.confidence)}
        </Badge>
      </div>
      <div className="grid grid-cols-4 gap-6">
        <HeroMetric
          label="Dollars at risk"
          value={formatUsd(impact.dollars_at_risk_usd)}
          sub={`est. loss ${formatUsd(impact.estimated_revenue_loss_usd)}`}
        />
        <HeroMetric
          label="Customers affected"
          value={INT_FORMATTER.format(impact.customers_affected)}
        />
        <HeroMetric
          label="Transactions affected"
          value={INT_FORMATTER.format(impact.transactions_affected)}
        />
        <HeroMetric
          label="Trust index Δ"
          value={formatTrustDelta(impact.customer_trust_score_delta)}
          sub="modeled"
        />
      </div>
      {impact.caveats.length > 0 && (
        <div className="mt-5 rounded border border-accent-border bg-accent-bg p-3 text-[13px] text-accent-text">
          <div className="mb-1 font-semibold">Caveats</div>
          <ul className="list-disc space-y-1 pl-5">
            {impact.caveats.map((c, idx) => (
              <li key={idx}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function HeroMetric({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-text-tertiary">{label}</div>
      <div className="text-[22px] font-semibold leading-none tracking-tight tabular-nums">
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-text-tertiary">{sub}</div>}
    </div>
  );
}

/**
 * Audit-citation section: every figure the quantifier cited.
 * Rendered below the prose Impact section so a reader can verify the
 * hero metrics trace back to scenario seed values.
 */
function ImpactQuantifiedSection({ impact }: { impact: ImpactReport }) {
  return (
    <section className="mb-7">
      <SectionLabel>Audit citations</SectionLabel>
      <ul className="rounded-md border border-border bg-bg">
        {impact.audit_citation_lines.map((line, idx) => (
          <li
            key={idx}
            className="border-b border-border px-4 py-2 font-mono text-[12.5px] leading-relaxed text-text-secondary last:border-b-0"
          >
            {line}
          </li>
        ))}
      </ul>
    </section>
  );
}
