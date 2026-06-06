import { Badge } from "@/components/ui/badge";
import type {
  CitedClause,
  DriftReport,
  FairnessReport,
  ImpactReport,
  PerFeatureDrift,
  Postmortem,
  ReportingObligation,
} from "@/lib/types";
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

      <RegulatoryExposureSection
        citations={pm.regulatory_citations ?? []}
        obligations={pm.reporting_obligations ?? []}
      />

      {pm.drift_analysis && <DriftSection report={pm.drift_analysis} />}
      {pm.fairness_analysis && <FairnessSection report={pm.fairness_analysis} />}

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
 * Regulatory exposure panel — Phase 8 / ADR-019. Renders:
 *   - the cited regulator clauses (clause id, full name, applicability,
 *     quoted excerpt, source URL)
 *   - the triggered reporting obligations (regulator, timeframe, headline)
 *
 * Omits itself entirely when no citations + no obligations (the legacy
 * postmortem case).
 */
function RegulatoryExposureSection({
  citations,
  obligations,
}: {
  citations: CitedClause[];
  obligations: ReportingObligation[];
}) {
  const cites = citations;
  const obls = obligations;
  if (cites.length === 0 && obls.length === 0) {
    return null;
  }
  return (
    <section className="mb-7">
      <SectionLabel>Regulatory exposure</SectionLabel>

      {obls.length > 0 && (
        <div className="mb-4 grid gap-2">
          {obls.map((o, idx) => (
            <div
              key={idx}
              className="rounded-md border border-accent-border bg-accent-bg p-4"
            >
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[13px] font-semibold text-accent-text">
                  {o.regulator}
                </div>
                <Badge variant="p1">
                  {o.timeframe_days === 0
                    ? "Immediate"
                    : `${o.timeframe_days}d window`}
                </Badge>
              </div>
              <div className="text-[13.5px] leading-relaxed text-text">
                {o.draft_notification_headline}
              </div>
              {o.triggered_by_clauses.length > 0 && (
                <div className="mt-2 font-mono text-xs text-text-tertiary">
                  Triggered by: {o.triggered_by_clauses.join(", ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {cites.length > 0 && (
        <div className="grid gap-3">
          {cites.map((c, idx) => (
            <div
              key={idx}
              className="rounded-md border border-border bg-bg px-4 py-3.5"
            >
              <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2">
                <Badge variant="ok">{c.regulation_short_name}</Badge>
                <span className="font-mono text-xs text-text-secondary">
                  {c.clause_id}
                </span>
                <span className="text-[13px] text-text-secondary">
                  · {c.clause_title}
                </span>
              </div>
              <div className="mb-2 text-[13px] text-text-tertiary">
                {c.regulation_full_name}
              </div>
              <blockquote className="mb-2 border-l-2 border-border pl-3 text-[13px] italic leading-relaxed text-text-secondary">
                {c.quoted_excerpt}
              </blockquote>
              <div className="text-[13px] leading-relaxed text-text">
                {c.applicability_rationale}
              </div>
              <div className="mt-2 truncate text-xs text-text-tertiary">
                Source:{" "}
                <a
                  href={c.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-accent underline-offset-2 hover:underline"
                >
                  {c.source_url}
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * Drift analysis section — Phase 8 / ADR-022. Renders one row per
 * feature with the test stat, p-value (KS) or PSI value, and a
 * severity badge. Empty / insufficient-data rows are still surfaced
 * so the reader knows the auditor looked at the feature.
 */
function DriftSection({ report }: { report: DriftReport }) {
  return (
    <section className="mb-7">
      <SectionLabel>Distribution drift (KS + PSI)</SectionLabel>
      <div className="mb-2.5 flex items-center gap-2 text-[13px] text-text-secondary">
        <span>Aggregate severity:</span>
        <Badge variant={severityBadgeVariant(report.aggregate_severity)}>
          {report.aggregate_severity}
        </Badge>
        {report.insufficient_baseline_data && (
          <span className="text-xs text-text-tertiary">
            (insufficient baseline data on every feature)
          </span>
        )}
      </div>
      <div className="overflow-hidden rounded-md border border-border bg-bg">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-bg-subtle">
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Feature
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Test
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Statistic
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                p-value
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Severity
              </th>
            </tr>
          </thead>
          <tbody>
            {report.per_feature.map((f: PerFeatureDrift) => (
              <tr
                key={f.feature_name}
                className="border-b border-border last:border-b-0"
              >
                <td className="px-4 py-2.5 font-mono text-[12.5px]">
                  {f.feature_name}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-text-secondary">
                  {f.test.toUpperCase()}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-[12.5px] tabular-nums">
                  {f.statistic.toFixed(4)}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-[12.5px] tabular-nums text-text-tertiary">
                  {f.p_value != null ? f.p_value.toFixed(4) : "—"}
                </td>
                <td className="px-4 py-2.5">
                  <Badge variant={severityBadgeVariant(f.severity)}>
                    {f.severity}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * Fairness analysis section — Phase 8 / ADR-023. Renders per-attribute
 * findings: reference group, disparate-impact ratios per group, parity
 * differences, equalized-odds deltas. The methodology note grounds the
 * metrics in EEOC + EU AI Act terms.
 */
function FairnessSection({ report }: { report: FairnessReport }) {
  return (
    <section className="mb-7">
      <SectionLabel>Disparate impact + fairness audit</SectionLabel>
      <div className="mb-2.5 flex items-center gap-2 text-[13px] text-text-secondary">
        <span>Aggregate flag:</span>
        <Badge variant={severityBadgeVariant(report.aggregate_flag)}>
          {report.aggregate_flag}
        </Badge>
      </div>
      <div className="mb-3 text-xs text-text-tertiary">
        {report.methodology_note}
      </div>
      <div className="grid gap-3">
        {report.by_attribute.map((finding) => (
          <div
            key={finding.attribute_name}
            className="rounded-md border border-border bg-bg p-4"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[13.5px] font-semibold">
                {finding.attribute_name}
              </div>
              <Badge variant={severityBadgeVariant(finding.flag)}>
                {finding.flag}
              </Badge>
            </div>
            <div className="mb-3 text-xs text-text-tertiary">
              Reference group:{" "}
              <span className="font-mono">{finding.reference_group}</span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <FairnessMetricBlock
                label="Disparate impact (4/5ths)"
                values={finding.disparate_impact_ratios}
                threshold={0.8}
                lowerIsBad
              />
              <FairnessMetricBlock
                label="Statistical parity Δ"
                values={finding.statistical_parity_differences}
              />
              <FairnessMetricBlock
                label="Equalized odds Δ"
                values={finding.equalized_odds_deltas}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function FairnessMetricBlock({
  label,
  values,
  threshold,
  lowerIsBad,
}: {
  label: string;
  values: Record<string, number>;
  threshold?: number;
  lowerIsBad?: boolean;
}) {
  return (
    <div className="rounded border border-border bg-bg-subtle p-3">
      <div className="mb-1.5 text-xs text-text-tertiary">{label}</div>
      <ul className="space-y-1">
        {Object.entries(values).map(([group, val]) => {
          const bad =
            threshold != null &&
            (lowerIsBad ? val < threshold : Math.abs(val) > threshold);
          return (
            <li
              key={group}
              className={`flex items-baseline justify-between font-mono text-[12.5px] tabular-nums ${
                bad ? "text-error" : ""
              }`}
            >
              <span>{group}</span>
              <span>{val.toFixed(3)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function severityBadgeVariant(
  severity: string,
): "ok" | "p2" | "p1" | "p0" {
  switch (severity) {
    case "none":
    case "clean":
    case "healthy":
      return "ok";
    case "watch":
      return "p2";
    case "significant":
    case "degraded":
      return "p1";
    case "severe":
    case "underperforming":
    case "insufficient_baseline_data":
    case "insufficient_data":
      return "p0";
    default:
      return "p2";
  }
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
