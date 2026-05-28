import { Sparkles } from "lucide-react";

interface RoutingCalloutProps {
  label?: string;
  body: string;
  source: string;
}

export function RoutingCallout({ label = "Learned routing", body, source }: RoutingCalloutProps) {
  return (
    <div className="ml-12 my-2 flex items-start gap-2.5 rounded border border-accent-border bg-accent-bg px-3.5 py-3">
      <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" strokeWidth={1.75} />
      <div className="text-[13px] leading-relaxed text-accent-text">
        <span className="mr-1.5 font-semibold text-accent">{label}</span>
        {body}
        <div className="mt-1 text-xs text-text-tertiary">{source}</div>
      </div>
    </div>
  );
}
