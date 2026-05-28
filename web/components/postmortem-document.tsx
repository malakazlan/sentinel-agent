import { Badge } from "@/components/ui/badge";
import type { Postmortem } from "@/lib/types";
import { severityVariant } from "@/lib/severity";

const TIMELINE_SEPARATOR = " — ";

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

      <Section label="Summary">{pm.summary}</Section>
      <Section label="Impact">{pm.impact}</Section>

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
