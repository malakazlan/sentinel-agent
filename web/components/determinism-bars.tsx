import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface BarRow {
  label: string;
  fillPct: number;
  count: string;
}

interface DeterminismSide {
  title: string;
  badge: { label: string; variant?: "default" | "ok" };
  caption: string;
  rows: BarRow[];
  variant: "cold" | "warm";
}

interface DeterminismBarsProps {
  cold: DeterminismSide;
  warm: DeterminismSide;
}

export function DeterminismBars({ cold, warm }: DeterminismBarsProps) {
  return (
    <div className="grid grid-cols-2 gap-6">
      <Side {...cold} />
      <Side {...warm} />
    </div>
  );
}

function Side({ title, badge, caption, rows, variant }: DeterminismSide) {
  const fill = variant === "warm" ? "bg-cta-bg" : "bg-text-tertiary";
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </div>
      {rows.map((row) => (
        <div key={row.label} className="mb-3 grid grid-cols-[100px_1fr_80px] items-center gap-3">
          <div className="text-[13px] font-medium text-text-secondary">{row.label}</div>
          <div className="relative h-2 overflow-hidden rounded bg-bg-inset">
            <div
              className={cn("absolute inset-y-0 left-0 rounded", fill)}
              style={{ width: `${Math.min(100, Math.max(0, row.fillPct))}%` }}
            />
          </div>
          <div className="text-right font-mono text-xs text-text-secondary">{row.count}</div>
        </div>
      ))}
      <p className="mt-2 text-xs leading-relaxed text-text-tertiary">{caption}</p>
    </div>
  );
}
