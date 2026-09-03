/**
 * `<CodepointTooltip>` — the full codepoint breakdown of a value, on hover or focus.
 *
 * `<NameText>`'s inline toggle answers "which tick is that". This answers the follow-up:
 * the whole string, one row per codepoint, in a form an operator can read out over a call
 * or paste into a bug report. It is the same data as the toggle, at a different altitude.
 *
 * Built from a button and local state rather than Radix's `Tooltip`: this has to open on
 * FOCUS as well as hover (an operator on a keyboard is the common case during an incident),
 * has to survive inside a table cell without a provider at the root, and has to be
 * assertable in jsdom without faking pointer physics.
 */

import { useId, useState, type ReactElement, type ReactNode } from "react";

import { cn } from "@/lib";

import { toCodepoints } from "./codepoints";

export interface CodepointTooltipProps {
  /** The value to spell out. Rendered into the panel unmodified, one row per codepoint. */
  value: string;
  /** The trigger — usually a `<NameText>`. */
  children: ReactNode;
  className?: string | undefined;
}

export function CodepointTooltip({
  value,
  children,
  className,
}: CodepointTooltipProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  const panelId = useId();
  const points = toCodepoints(value);

  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-expanded={isOpen}
        aria-describedby={isOpen ? panelId : undefined}
        onMouseEnter={() => {
          setIsOpen(true);
        }}
        onMouseLeave={() => {
          setIsOpen(false);
        }}
        onFocus={() => {
          setIsOpen(true);
        }}
        onBlur={() => {
          setIsOpen(false);
        }}
        onClick={() => {
          // Opens, never toggles: a pointer click is preceded by the pointerover that
          // already opened the panel, so a toggle here would close it on the way in.
          setIsOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setIsOpen(false);
        }}
        // The dotted underline stays: it is the affordance that says "there is more here",
        // and it is the one place a hairline still earns its keep. `--hairline-strong` is
        // decoration; the button's own focus ring is what carries the boundary.
        className="cursor-help rounded-4xs border-b border-dotted border-hairline-strong text-left"
      >
        {children}
      </button>
      {isOpen ? (
        <span
          id={panelId}
          role="tooltip"
          className={cn(
            // A floating panel: `--shadow-overlay` carries the 1px `--edge` ring (3.22:1 on
            // a card) that keeps it from dissolving into the surface behind it, so the
            // panel names no border of its own.
            "absolute left-0 top-full z-50 mt-2 min-w-[13rem] rounded-2xl",
            "bg-surface-card p-3 shadow-overlay",
          )}
        >
          <span className="type-caption mb-2 block text-ink-muted">codepoints</span>
          <span className="block">
            {points.map((point, index) => (
              <span
                key={`${String(index)}:${point.label}`}
                className="flex items-baseline justify-between gap-4 py-px"
              >
                <span
                  lang="uz-Latn"
                  dir="ltr"
                  className={cn("type-mono", point.isAmbiguous ? "text-accent" : "text-ink")}
                >
                  {point.isAmbiguous ? INVISIBLE_PLACEHOLDER : point.char}
                </span>
                <span
                  className={cn("type-mono num", point.isAmbiguous ? "text-accent" : "text-ink-muted")}
                >
                  {point.label}
                </span>
              </span>
            ))}
          </span>
        </span>
      ) : null}
    </span>
  );
}

/**
 * What stands in for a character that draws as nothing (or as an indistinguishable tick) in
 * the breakdown's left column. A blank cell there would read as a rendering bug, which is
 * the one reading that must not happen on this panel.
 */
const INVISIBLE_PLACEHOLDER = "◌";
