import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  sub?: string;
  delta?: { value: string; positive: boolean };
}

export function MetricCard({ label, value, sub, delta }: MetricCardProps) {
  return (
    <div className="rounded-md border border-border bg-bg px-5 py-[18px]">
      <div className="mb-2 text-xs font-medium text-text-tertiary">{label}</div>
      <div className="text-[26px] font-semibold leading-none tracking-tight">{value}</div>
      {delta && (
        <div className={cn("mt-1.5 text-xs font-medium", delta.positive ? "text-ok" : "text-error")}>
          {delta.value}
        </div>
      )}
      {sub && <div className="mt-1.5 text-xs text-text-tertiary">{sub}</div>}
    </div>
  );
}
