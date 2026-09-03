/**
 * `StatTile` — §11.4's figure, and on `/` the dominant signal itself.
 *
 * §11.2: "24 h delivery success rate at 44px, colour-driven (green ≥95%, amber 85–95%, red
 * <85%); secondary **in flight** with a pulsing ring". `size="hero"` is that 44px
 * (`.type-hero`), `band` is that colour rule via `rateBand`, and `isPulsing` is that ring.
 *
 * Two rules the tile enforces so no screen has to remember them:
 *
 *  - **Colour is never the only channel.** A band always renders its word — `good`, `at
 *    risk`, `bad` — beside the number, so the tile survives greyscale, a bad projector, and
 *    a red-green reader. The plan applies this to status pills; a 44px number that means
 *    "the system is broken" purely by being reddish is the same failure at four times the
 *    size.
 *  - **`unknown` is not zero, and not bad.** `rateBand(null)` is `"unknown"` and paints
 *    `--fg-2`. `successRate` is `null` when nothing terminated in the window, and a red 0%
 *    on a quiet morning is the most alarming wrong number this console could show.
 *
 * The value is passed pre-formatted (`formatRate`, `formatTotal`, `formatDurationMs`) rather
 * than as a raw number: the tile must not decide that a `null` renders as `0`.
 *
 * ## The shape of the tile
 *
 * Muted label → large figure → a small tinted delta chip beside it → a sparkline across the
 * bottom, on a borderless 28px card. The sparkline is `--brand-fill` regardless of band: it
 * is the tile's own trend, not a semantic series, and painting it the band's colour made a
 * "bad" tile red twice while saying nothing extra. Semantic hue is reserved for the figure,
 * where it is paired with the band's WORD.
 */

import { type ReactElement, type ReactNode } from "react";

import { cn, type RateBand } from "@/lib";

import { Sparkline } from "./Sparkline";

/**
 * The band's colour and its word. The word is not decoration — see the note above.
 *
 * Every entry is a TEXT-bar token (4.5:1 on every ground in both palettes), so the figure is
 * legible at 28px and at 11px alike and none of them is policed. `unknown` used to be
 * `--fg-2` behind a waiver, justified by WCAG 1.4.3's large-text 3:1 allowance — which was
 * true of the 40px figure and false of the "no data" word beside it. `--neutral` is the
 * palette's own "nothing has happened yet" grey and clears 4.5:1 outright, so the exemption
 * is not claimed and no `MARK_WAIVERS` entry is needed for this file.
 *
 * `warn` is `--caution`, the softer of the two attention hues and the one Gogo's amber
 * accent became: §11.2's band is "amber 85–95%", an at-risk reading, not the harder
 * `--warning` that means a partial outage. `tokenContrast.test.ts` measures every one of
 * these against every ground.
 */
export const BAND_PRESENTATION = {
  good: { colorVar: "var(--success)", word: "good" },
  warn: { colorVar: "var(--caution)", word: "at risk" },
  bad: { colorVar: "var(--error)", word: "bad" },
  unknown: { colorVar: "var(--neutral)", word: "no data" },
} as const satisfies Record<RateBand, { colorVar: string; word: string }>;

/** How a delta chip is tinted. `neutral` is the honest default for a movement whose
 *  goodness the tile cannot know. */
export type DeltaTone = "good" | "bad" | "neutral";

/**
 * The Gogo delta chip: a direction arrow, a pre-formatted magnitude, a tinted pill.
 *
 * `direction` and `tone` are separate on purpose — a FALLING failure rate is `down` and
 * `good`, and collapsing the two would have the tile paint that red. The arrow is the second
 * channel so the chip is not colour alone; the magnitude string carries its own sign, so
 * nothing in it is conveyed by hue.
 */
export interface StatDelta {
  /** Already formatted, sign included: `+12.4%`, `−3`, `0`. */
  readonly value: ReactNode;
  /** Which way the number moved. Renders ▲ / ▼ / ▬. */
  readonly direction: "up" | "down" | "flat";
  /** Whether that movement is good news. Defaults to `neutral`. */
  readonly tone?: DeltaTone;
  /** What the comparison is against: `vs. previous 24h`. Goes on the chip's `title` and
   *  into its accessible name, because "+12.4%" alone is not a fact. */
  readonly comparedTo?: string;
}

const DELTA_ARROW = { up: "▲", down: "▼", flat: "▬" } as const;

/**
 * Ground and glyph, split. The palette's own recommendation for a tinted pill is the word in
 * `--ink` and the hue in the GROUND and the GLYPH — so the magnitude is read at 6.61:1 rather
 * than at the hue's 4.5:1 floor, and the colour still lands where the eye catches it.
 */
const DELTA_TONE_CLASS: Record<DeltaTone, { readonly ground: string; readonly glyph: string }> = {
  good: { ground: "bg-success-tint", glyph: "text-success" },
  bad: { ground: "bg-error-tint", glyph: "text-error" },
  neutral: { ground: "bg-surface-control", glyph: "text-ink-muted" },
};

export interface StatTileProps {
  /** Sentence case, no trailing colon. Rendered as a `.type-caption`. */
  readonly label: string;
  /** Already formatted. Pass `formatRate(rate)`, not `rate`. */
  readonly value: ReactNode;
  /** Applies §11.2's colour rule and prints the matching word. Omit for a neutral figure. */
  readonly band?: RateBand;
  /** `hero` is the 44px dominant signal. Exactly one per view. */
  readonly size?: "metric" | "hero";
  /** A second line under the value — the denominator, the window, the caveat. */
  readonly hint?: ReactNode;
  /** A status glyph, an arrow, a count badge. */
  readonly glyph?: ReactNode;
  /** §11.2's "in flight with a pulsing ring". */
  readonly isPulsing?: boolean;
  /** The movement chip beside the figure. Pre-formatted, like `value`. */
  readonly delta?: StatDelta;
  /** A 12-to-30 point trend under the figure. */
  readonly trend?: readonly number[];
  /** What the trend line is; required whenever `trend` is passed. */
  readonly trendLabel?: string;
  readonly className?: string;
}

export function StatTile({
  label,
  value,
  band,
  size = "metric",
  hint,
  glyph,
  isPulsing = false,
  delta,
  trend,
  trendLabel,
  className,
}: StatTileProps): ReactElement {
  const presentation = band === undefined ? null : BAND_PRESENTATION[band];
  const colorVar = presentation?.colorVar ?? "var(--ink)";

  return (
    <article
      /* A card: paper, 28px, a whisper of shadow, and no border anywhere. `overflow-hidden`
         is what lets the sparkline run to the tile's own rounded edge. */
      className={cn(
        "flex flex-col overflow-hidden rounded-card bg-surface-card shadow-card",
        "transition-shadow duration-base ease-standard hover:shadow-card-hover",
        className,
      )}
      data-band={band}
      data-size={size}
    >
      <div className="flex flex-col gap-2 p-card pb-4">
        <header className="flex items-center gap-2">
          <h3 className="type-body-sm text-ink-muted">{label}</h3>
          {isPulsing && (
            <span
              aria-hidden="true"
              className="inline-block size-2 animate-pulse-ring rounded-full"
              style={{ backgroundColor: colorVar }}
            />
          )}
        </header>

        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {glyph !== undefined && (
            <span
              className={cn(
                /*
                 * OPTICALLY aligned to the figure, not sat on its baseline.
                 *
                 * The row is `items-baseline`, which is right for the band word and the delta
                 * chip — they are words beside a word. A glyph is a MARK on the numeral, and
                 * baseline-setting a 14px mark against a 40px numeral put its 10px of ink in
                 * the bottom third of the numeral's 28px cap band (measured: glyph ink
                 * 169.9→180, figure ink 152→180), where it read as a dropped artefact rather
                 * than as part of the figure.
                 *
                 * `self-center` centres it on the line's cross axis instead — which is the
                 * figure's own line box, so the two ink centres coincide — and `leading-none`
                 * makes the glyph's box its own ink so the centring is of the mark and not of
                 * a font's leading. The size is a fixed fraction of the figure (~0.55) so a
                 * `hero` and a `metric` tile read as one family.
                 */
                "shrink-0 self-center",
                /* The line-height rides in the same utility (`/none`) on purpose: written as
                   a separate `leading-none`, tailwind-merge folds it into the arbitrary
                   font-size class and drops it. */
                size === "hero" ? "text-[1.375rem]/none" : "text-[1rem]/none",
                isPulsing && "animate-pulse-ring",
              )}
              style={{ color: colorVar }}
              aria-hidden="true"
            >
              {glyph}
            </span>
          )}
          <span className={size === "hero" ? "type-hero" : "type-metric"} style={{ color: colorVar }}>
            {value}
          </span>
          {delta !== undefined && <DeltaChip delta={delta} />}
          {presentation !== null && (
            /* The word carries the same meaning as the colour — greyscale-safe by design. */
            <span className="type-caption text-ink-muted">{presentation.word}</span>
          )}
        </div>

        {hint !== undefined && <p className="type-body-sm text-ink-muted">{hint}</p>}
      </div>

      {trend !== undefined && trend.length > 0 && (
        /* Across the BOTTOM of the tile, full bleed, in the brand hue — the Gogo idiom. The
           tile's own padding stops above it so the wash meets the card's edge. */
        <Sparkline
          className="-mt-2 w-full"
          values={trend}
          label={trendLabel ?? label}
          colorVar="var(--brand-fill)"
          height={44}
          isFullBleed
          isArea
        />
      )}
    </article>
  );
}

function DeltaChip({ delta }: { readonly delta: StatDelta }): ReactElement {
  const tone = DELTA_TONE_CLASS[delta.tone ?? "neutral"];
  const context = delta.comparedTo;
  return (
    <span
      className={cn(
        "type-caption inline-flex shrink-0 items-center gap-1 rounded-pill px-2 py-0.5 text-ink",
        tone.ground,
      )}
      data-delta-direction={delta.direction}
      data-delta-tone={delta.tone ?? "neutral"}
      {...(context === undefined ? {} : { title: context })}
    >
      {/* Direction is a glyph as well as a tint, so the chip survives greyscale. */}
      <span aria-hidden="true" className={tone.glyph}>
        {DELTA_ARROW[delta.direction]}
      </span>
      <span className="num">{delta.value}</span>
      {context !== undefined && <span className="sr-only">{context}</span>}
    </span>
  );
}
