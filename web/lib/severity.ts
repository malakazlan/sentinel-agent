import type { Severity } from "@/lib/types";

export type SeverityVariant = "p0" | "p1" | "p2" | "p3";

/**
 * Maps the wire-format Severity literal (`P0`..`P3`) to the Badge variant
 * name (`p0`..`p3`). Centralized so adding `P4` to the wire schema is a
 * single-file edit and breaks every consumer at typecheck time.
 */
export const SEVERITY_TO_VARIANT: Record<Severity, SeverityVariant> = {
  P0: "p0",
  P1: "p1",
  P2: "p2",
  P3: "p3",
};

export function severityVariant(sev: Severity): SeverityVariant {
  return SEVERITY_TO_VARIANT[sev];
}
