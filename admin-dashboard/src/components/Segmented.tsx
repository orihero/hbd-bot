import type { JSX } from "react";

import { cn } from "@/lib/cn";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

type Variant = "main" | "mini" | "tog";

/** `.seg`, `.seg.mini` and `.seg.tog` from the mockup, in that order. */
const TRACK: Record<Variant, string> = {
  main: "h-8 gap-[2px] rounded-chip bg-card p-[3px]",
  mini: "h-5 w-24 gap-0 rounded-seg bg-bg p-[2px]",
  tog: "h-[22px] gap-0 rounded-seg bg-bg p-[2px]",
};

const ITEM: Record<Variant, string> = {
  main: "rounded-chip px-3 text-xs font-semibold tracking-[-.24px]",
  mini: "flex-1 rounded-lg px-0 text-[9px] font-bold tracking-[.02em]",
  tog: "rounded-lg px-2 text-[9px] font-bold uppercase tracking-[.04em]",
};

/**
 * The design gives these buttons no interactive states at all; the hover/active/focus
 * treatments below are added so the control is usable by keyboard and readable by mouse.
 * `accent-deep` carries the focus ring because `accent` itself is invisible both on white
 * paper and on an already-accent selected pill.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  variant = "main",
  ariaLabel,
}: {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (v: T) => void;
  variant?: Variant;
  ariaLabel?: string;
}): JSX.Element {
  return (
    <div role="group" aria-label={ariaLabel} className={cn("flex", TRACK[variant])}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={cn(
              "cursor-pointer border-0 bg-transparent font-sans leading-none transition-[color,background-color,filter]",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
              ITEM[variant],
              on
                ? "bg-accent text-ink-900 hover:brightness-95 active:brightness-90"
                : "text-ink-400 hover:text-ink-900 active:text-ink-900",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
