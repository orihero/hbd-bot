import type { JSX } from "react";

import { cn } from "@/lib/cn";

/**
 * A placeholder for a value that has been asked for and has not arrived.
 *
 * It is a SHAPE, never a number: the one thing a dashboard must not do while it is loading is
 * show a figure that later changes. Callers size it to the slot it stands in — a card whose
 * skeleton is a different height from its number would resize the moment the number lands,
 * which reads as the page rearranging itself under the operator's eyes.
 *
 * `aria-hidden` because it says nothing; the section that owns it carries `aria-busy` instead,
 * which is the fact a screen reader can act on. `motion-reduce` drops the pulse for anyone who
 * has asked the OS for less motion — a shimmer is decoration, and decoration is the first
 * thing to go.
 */
export function Skeleton({ className }: { readonly className?: string }): JSX.Element {
  return (
    <span
      aria-hidden
      className={cn("block animate-pulse rounded bg-d6 motion-reduce:animate-none", className)}
    />
  );
}
