import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-[1.5] tracking-wide",
  {
    variants: {
      variant: {
        default: "border-border bg-bg text-text-secondary",
        ok: "border-[#bbf7d0] bg-[#f0fdf4] text-ok",
        error: "border-[#fecaca] bg-[#fef2f2] text-error",
        running: "border-accent-border bg-accent-bg text-running",
        p0: "border-p0 bg-p0 text-cta-text",
        p1: "border-p1 bg-p1 text-cta-text",
        p2: "border-p2 bg-p2 text-cta-text",
        p3: "border-p3 bg-p3 text-cta-text",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { badgeVariants };
