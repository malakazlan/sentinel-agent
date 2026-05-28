import { Check } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export type StepStatus = "done" | "running" | "queued" | "skipped";

export interface AgentStep {
  name: string;
  model?: string;
  status: StepStatus;
  action: string;
  meta: string;
  badge?: { label: string; variant?: "default" | "running" };
}

interface AgentStepperProps {
  steps: AgentStep[];
}

export function AgentStepper({ steps }: AgentStepperProps) {
  return (
    <div className="relative">
      {steps.map((step, idx) => (
        <div
          key={`${step.name}-${idx}`}
          className="relative grid grid-cols-[32px_1fr_auto] gap-4 py-3.5"
        >
          {idx < steps.length - 1 && (
            <span className="absolute left-[15px] top-[38px] bottom-[-6px] w-px bg-border" aria-hidden />
          )}
          <Dot status={step.status} idx={idx + 1} />
          <div>
            <div className="flex items-center gap-2">
              <span
                className={
                  step.status === "queued" ? "text-text-tertiary font-medium" : "font-semibold text-text"
                }
              >
                {step.name}
              </span>
              {step.model && <Badge>{step.model}</Badge>}
              {step.badge && <Badge variant={step.badge.variant ?? "default"}>{step.badge.label}</Badge>}
            </div>
            <div
              className={`mt-0.5 text-[13px] ${
                step.status === "queued" ? "text-text-tertiary" : "text-text-secondary"
              }`}
            >
              {step.action}
            </div>
          </div>
          <div className="whitespace-nowrap pt-0.5 text-right font-mono text-xs text-text-tertiary">
            {step.meta}
          </div>
        </div>
      ))}
    </div>
  );
}

function Dot({ status, idx }: { status: StepStatus; idx: number }) {
  if (status === "done") {
    return (
      <div className="relative z-[1] grid h-8 w-8 place-items-center rounded-full border border-ok bg-ok text-cta-text">
        <Check className="h-3.5 w-3.5" strokeWidth={2.25} />
      </div>
    );
  }
  if (status === "running") {
    return (
      <div className="relative z-[1] grid h-8 w-8 place-items-center rounded-full border border-running bg-bg text-running">
        <span className="block h-1.5 w-1.5 animate-pulse rounded-full bg-running" />
        <span className="absolute inset-[-4px] rounded-full border border-running opacity-35" aria-hidden />
      </div>
    );
  }
  return (
    <div className="relative z-[1] grid h-8 w-8 place-items-center rounded-full border border-border bg-bg text-xs font-semibold text-text-tertiary">
      {status === "skipped" ? "—" : idx}
    </div>
  );
}
