import * as React from "react";
import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-md border border-border bg-bg p-6", className)} {...props} />
  )
);
Card.displayName = "Card";

export const CardInset = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-md border border-border bg-bg-subtle p-6", className)} {...props} />
  )
);
CardInset.displayName = "CardInset";
