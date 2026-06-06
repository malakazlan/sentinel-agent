import type { ReactNode } from "react";

/**
 * Lean shared shell used by the Phase 8 read-only pages
 * (/patterns, /sentinel-health, /prompts, /history, /architecture, /evals).
 * Pages compose: a page title strip, optional subtitle, and a body that
 * handles its own loading/error/empty/data states.
 */
export function PageShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-10">
      <div className="mb-8">
        <h1 className="mb-1.5 text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="text-[14px] text-text-secondary">{subtitle}</p>
        )}
      </div>
      {children}
    </main>
  );
}

/** Skeleton row, used while a fetch is pending. */
export function SkeletonRows({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-2">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="h-10 animate-pulse rounded-md border border-border bg-bg-subtle"
        />
      ))}
    </div>
  );
}

/** Inline error block. */
export function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-error/30 bg-error-bg p-4 text-sm text-error">
      {message}
    </div>
  );
}

/** Empty-state. */
export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-border bg-bg-subtle p-6 text-center text-sm text-text-tertiary">
      {message}
    </div>
  );
}
