/**
 * `<StatusPill>` — an order's state, as glyph + text + colour.
 *
 * §11.3: **status pills are never colour alone**, so they survive greyscale, a bad
 * projector, and the eight percent of male operators with a red-green deficiency. The
 * glyphs are pinned by the plan and live in `STATUS_GLYPH`: `○` draft, `◔` brief_ready,
 * `◑` lyrics_ready, `◆` authorized, `◉` generating, `✓` delivered, `✗` failed, `⊘`
 * cancelled, `⚑` held. **`◉ generating` is the only animated one** — motion means "this is
 * moving right now", and a pill that pulses for a delivered order teaches an operator to
 * ignore the animation.
 *
 * `held` is in `STATUS_GLYPH` but is NOT an `OrderState` member on this build; the state
 * arrives with the moderation phase. The prop type is `StatusGlyphKey` so both spell.
 *
 * ## Where the colour goes, under the Gogo reskin
 *
 * The pill is now the soft badge idiom: a `--r-full` capsule with a light TINT of the
 * state's own hue as its ground, no border at all, and the WORD in `--ink`. The hue paints
 * the GLYPH, not the sentence. That is not a stylistic preference — it is what keeps the
 * component legible in a light-first palette, and it is measured over all nine states on
 * both the card and the page ground:
 *
 *   - the WORD, `--ink` on `--st-*-tint`: worst **6.62:1** in light (`held` on `--surface`),
 *     worst **7.97:1** in dark (`generating` on `--surface-card`). Text bar, cleared.
 *   - the GLYPH, `--st-*` on its own tint: worst **4.54:1** in light (`draft` on
 *     `--surface`), worst **4.59:1** in dark (`authorized` on `--surface-card`). That
 *     clears the 4.5:1 TEXT bar even though an `aria-hidden` mark beside its own word only
 *     owes 1.4.11's 3:1.
 *
 * The alternative — the old design's colour-as-text — does not survive the light palette:
 * Gogo's own hues at their own lightness are 2.0–2.4:1 on `#FAFAFA`.
 *
 * The colours come from `--st-*` via `orderStateColorVar`, never from a hardcoded hex —
 * that is what makes the theme switch work without touching this file. The `-tint` member
 * is derived from the same token name for the same reason: one source, two members.
 */

import type { ReactElement } from "react";

import { cn, humaniseEnum, orderStateColorVar, statusGlyph, type StatusGlyphKey } from "@/lib";

import { tintVar } from "./colors";

export interface StatusPillProps {
  state: StatusGlyphKey;
  /** `sm` for a table row, `md` for a header banner. */
  size?: "sm" | "md" | undefined;
  /** Hide the words and keep the glyph — ONLY where a visible label sits beside it. */
  isGlyphOnly?: boolean | undefined;
  className?: string | undefined;
}

export function StatusPill({
  state,
  size = "sm",
  isGlyphOnly = false,
  className,
}: StatusPillProps): ReactElement {
  const glyph = statusGlyph(state);
  const label = humaniseEnum(state);
  const color = orderStateColorVar(state);
  // `var(--st-delivered)` → `var(--st-delivered-tint)`. Derived rather than spelled so the
  // ground can never drift onto a different state from the glyph above it.
  const tint = tintVar(color);
  const isAnimated = state === "generating";

  return (
    <span
      data-testid="status-pill"
      data-state={state}
      // The label goes on the element even when the words are visible: a screen reader
      // reading "◔ brief ready" would otherwise announce the glyph as punctuation.
      aria-label={label}
      title={label}
      className={cn(
        // No border: in this language a chip is a tinted capsule, and the tint IS the edge.
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-pill text-ink",
        size === "sm" ? "type-body-sm px-2.5 py-0.5" : "type-body px-3 py-1",
        className,
      )}
      style={{ backgroundColor: tint }}
    >
      <span
        aria-hidden="true"
        className={cn("leading-none", isAnimated && "animate-pulse-ring")}
        data-testid="status-pill-glyph"
        // The hue lives on the glyph. `--st-x` is the text-safe member of its family, so it
        // clears 4.5:1 on its own tint even though the bar for an aria-hidden mark is 3:1.
        style={{ color }}
      >
        {glyph ?? "·"}
      </span>
      {isGlyphOnly ? null : <span>{label}</span>}
    </span>
  );
}
