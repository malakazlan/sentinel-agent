import Link from "next/link";
import type { Route } from "next";
import { cn } from "@/lib/utils";

// Phase 8 / ADR-027 — expanded global nav. The per-incident links
// (Live console, Postmortem) are still rendered conditionally on
// ``incidentId`` so non-incident pages keep a clean header.
type NavKey =
  | "scenarios"
  | "console"
  | "postmortem"
  | "patterns"
  | "health"
  | "prompts"
  | "history"
  | "architecture"
  | "evals";

interface TopbarProps {
  active: NavKey;
  status?: { dot?: "ok" | "running" | "error"; label: string };
  context?: string;
  incidentId?: string;
}

type NavLink = { href: Route; label: string; key: NavKey };

function buildNavLinks(incidentId?: string): NavLink[] {
  const links: NavLink[] = [
    { href: "/" as Route, label: "Scenarios", key: "scenarios" },
    { href: "/history" as Route, label: "History", key: "history" },
    { href: "/patterns" as Route, label: "Patterns", key: "patterns" },
    { href: "/sentinel-health" as Route, label: "Health", key: "health" },
    { href: "/prompts" as Route, label: "Prompts", key: "prompts" },
    { href: "/evals" as Route, label: "Evals", key: "evals" },
    { href: "/architecture" as Route, label: "Architecture", key: "architecture" },
  ];
  if (incidentId) {
    const encoded = encodeURIComponent(incidentId);
    links.push({ href: `/incidents/${encoded}` as Route, label: "Live console", key: "console" });
    links.push({ href: `/incidents/${encoded}/postmortem` as Route, label: "Postmortem", key: "postmortem" });
  }
  return links;
}

export function Topbar({ active, status, context, incidentId }: TopbarProps) {
  const navLinks = buildNavLinks(incidentId);
  return (
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-border bg-bg px-8">
      <div className="flex items-center gap-8">
        <Link href="/" className="flex items-center gap-2.5 text-[15px] font-semibold text-text">
          <span
            aria-hidden="true"
            className="grid h-[22px] w-[22px] place-items-center rounded-[5px] bg-cta-bg text-[12px] font-bold text-cta-text"
          >
            S
          </span>
          <span>Sentinel</span>
        </Link>
        <nav className="flex gap-1">
          {navLinks.map((link) => (
            <Link
              key={link.key}
              href={link.href}
              className={cn(
                "rounded-sm px-2.5 py-1.5 text-[13px] font-medium transition-colors",
                active === link.key
                  ? "bg-bg-inset text-text"
                  : "text-text-secondary hover:bg-bg-inset hover:text-text"
              )}
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-4 text-xs text-text-tertiary">
        {status && (
          <span>
            <span
              aria-hidden="true"
              className={cn(
                "mr-1.5 inline-block h-1.5 w-1.5 rounded-full",
                status.dot === "ok"
                  ? "bg-ok"
                  : status.dot === "running"
                  ? "bg-running"
                  : status.dot === "error"
                  ? "bg-error"
                  : "bg-text-tertiary"
              )}
            />
            {status.label}
          </span>
        )}
        {context && <span>{context}</span>}
      </div>
    </header>
  );
}
