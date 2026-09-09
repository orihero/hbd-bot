/**
 * One vendor's balance, as a mark inside a ring beside a number.
 *
 * The dashboard's own `BalanceStrip` writes the vendor's NAME on every chip and says why:
 * "a bare `$0.93` in a header is a number with no owner". This pill answers the same
 * objection with a logo instead of a word, because it lives in the global bar on every screen
 * — seven pages, not one — and three named chips is a header that reads as a sentence nobody
 * asked for. Everything the word carried is still there: the ring's `title`, the pill's
 * `aria-label`, and the strip on `/` which keeps its words.
 *
 * ## The ring
 *
 * One circle, drawn as two arcs from the top, clockwise:
 *
 *   * **solid** for what is LEFT — the fraction the operator can still spend;
 *   * **dashed** for what is USED — the same circle, marked out rather than absent.
 *
 * Solid-for-remaining is the direction that survives being glanced at: a ring that fills as
 * you spend looks fullest at the moment you are about to run out. The dashes are the second
 * channel, so the two arcs are distinguishable in greyscale and to a red-green deficiency
 * without reading the hue — the rule the credits chips in the sibling console already follow.
 *
 * **A ring with no fraction is entirely dashed, and that is a third state, not zero.** An
 * uncapped key, a vendor that reported no total, a stale figure, a poll that never answered:
 * all of them mean "there is no denominator", which is not the same claim as "nothing left".
 * A fully dashed muted ring cannot be mistaken for either a full one or an empty one, and the
 * value beside it says which of the four it is in words.
 *
 * ## The colour is a second opinion, never the fact
 *
 * Below a fifth the ring goes amber, below a twentieth red. The number beside it is the fact;
 * the hue is what makes a nearly-empty account catch an eye that was reading something else.
 * Both tokens are the READABLE member of their family (`--warn-deep`, `--required-deep`), so
 * they hold up on the dark palette as well as the light one.
 */

import type { JSX } from "react";

import { percentLabel, type BalanceChip } from "@/features/dashboard/adapt";
import { cn } from "@/lib/cn";

import { VendorLogo } from "./vendorLogos";

/** Ring geometry, in the SVG's own units. The pill scales it with `width`/`height`. */
const BOX = 28;
const RADIUS = 12;
const STROKE = 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** Under a fifth left is worth a colour; under a twentieth is worth the loud one. */
const LOW_FRACTION = 0.2;
const CRITICAL_FRACTION = 0.05;

/** The dash pattern the USED arc is drawn with: 2 on, 3 off, in user units. */
const USED_DASHES = "2 3";

function ringColor(pct: number | null): string {
  if (pct === null) return "var(--ink-300)";
  if (pct <= CRITICAL_FRACTION) return "var(--required-deep)";
  if (pct <= LOW_FRACTION) return "var(--warn-deep)";
  return "var(--accent-deep)";
}

/**
 * The two arcs.
 *
 * Drawn with `stroke-dasharray` on one circle each rather than as two `<path>` arcs: a circle
 * with a rotated origin and a dash offset is exact at any fraction, where an arc path has to
 * choose a `large-arc-flag` and gets the choice wrong at exactly 50%.
 *
 * The USED arc's pattern is a repeating dash, so its own `dasharray` cannot also carry the
 * span. It is clipped by drawing it UNDER the solid arc over the full circle instead: the
 * remaining arc is opaque and paints over the head of it. That is why the order of these two
 * elements matters and why the used arc is first.
 */
function Ring({ pct }: { readonly pct: number | null }): JSX.Element {
  const centre = BOX / 2;
  const left = pct ?? 0;
  const color = ringColor(pct);

  return (
    <svg
      aria-hidden="true"
      width={BOX}
      height={BOX}
      viewBox={`0 0 ${String(BOX)} ${String(BOX)}`}
      className="absolute inset-0"
      focusable="false"
    >
      {/* USED — the whole circle, dashed, in the muted ink. Where there is no fraction at
          all this is the only arc drawn, which is the "no denominator" state. */}
      <circle
        cx={centre}
        cy={centre}
        r={RADIUS}
        fill="none"
        stroke="var(--ink-300)"
        strokeWidth={STROKE}
        strokeDasharray={USED_DASHES}
        opacity={0.75}
      />
      {/* REMAINING — solid, from twelve o'clock, clockwise. `pathLength` is not used: the
          dash offset is in user units and the circumference is the one we computed. */}
      {pct === null ? null : (
        <circle
          cx={centre}
          cy={centre}
          r={RADIUS}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeLinecap="butt"
          strokeDasharray={`${String(CIRCUMFERENCE * left)} ${String(CIRCUMFERENCE)}`}
          transform={`rotate(-90 ${String(centre)} ${String(centre)})`}
        />
      )}
    </svg>
  );
}

export interface BalancePillProps {
  readonly chip: BalanceChip;
}

/**
 * The number the ring is drawn from, shown where the mark was.
 *
 * Sized by digit count rather than at one size, because the ring's inner diameter is 22px and
 * `100%` at the size `9%` wants would touch the arc on both sides. Three digits is the only
 * case that needs the smaller step, and it is also the least interesting one — an account at
 * 100% is not the one anybody is hovering.
 */
function PercentBadge({ pct }: { readonly pct: number }): JSX.Element {
  const whole = Math.round(pct * 100);
  return (
    <span
      aria-hidden="true"
      className="font-bold leading-none tabular-nums"
      style={{ color: ringColor(pct), fontSize: whole >= 100 ? 8 : 9.5, letterSpacing: "-.02em" }}
    >
      {whole}%
    </span>
  );
}

/**
 * The pill: ring + mark, then the figure.
 *
 * ## Hover swaps the mark for the number
 *
 * The ring says roughly how much is left; the exact fraction is one hover away, and it appears
 * INSIDE the ring rather than in a tooltip beside it — the number lands on the same 28px the
 * eye is already looking at, framed by the arc it belongs to, so "how full is that ring" is
 * answered in place instead of somewhere the pointer has dragged the reader's attention to.
 *
 * Done as a CSS cross-fade on `group-hover` rather than with React state: three pills would
 * otherwise re-render the whole bar on every pointer entry and exit, and a hover that depends
 * on a render is a hover that stutters. Both layers are always mounted and absolutely
 * positioned in the same box, so neither the pill nor the bar reflows when they swap.
 *
 * **A pill with no fraction never swaps.** There is nothing to show — an uncapped key, a stale
 * figure, a poll that never answered — so the mark stays put and hovering changes nothing,
 * which is the honest answer to "what percentage is that?" for a row that has none.
 *
 * `title` still carries the long form (poll age, last-poll outcome, error code) for anything
 * the ring cannot draw, and `aria-label` carries the percentage in words, because the swap is
 * a pointer affordance and a screen reader never hovers.
 */
export function BalancePill({ chip }: BalancePillProps): JSX.Element {
  const share = chip.pct === null ? "" : `, ${percentLabel(chip.pct)}`;
  const swaps = chip.pct !== null;

  return (
    <div
      title={chip.title}
      aria-label={`${chip.vendor}: ${chip.value}${share}`}
      className={cn(
        "group flex h-9 items-center gap-2 rounded-chip bg-card pl-1 pr-3",
        "text-xs font-semibold",
        chip.isMeasured ? "text-ink-900" : "font-medium text-ink-400",
      )}
    >
      <span
        className="relative flex shrink-0 items-center justify-center"
        style={{ width: BOX, height: BOX }}
      >
        <Ring pct={chip.pct} />
        {/* The mark takes the ring's colour only when the ring is saying something loud;
            otherwise it stays ink, so a healthy row is not three greens in a circle. */}
        <span
          className={cn(
            "relative flex items-center justify-center transition-opacity duration-100",
            chip.isMeasured ? "text-ink-900" : "text-ink-300",
            swaps && "group-hover:opacity-0",
          )}
          style={
            chip.pct !== null && chip.pct <= LOW_FRACTION
              ? { color: ringColor(chip.pct) }
              : undefined
          }
        >
          <VendorLogo vendor={chip.vendorKey} size={13} />
        </span>
        {chip.pct === null ? null : (
          <span
            className={cn(
              "absolute inset-0 flex items-center justify-center",
              "opacity-0 transition-opacity duration-100 group-hover:opacity-100",
            )}
          >
            <PercentBadge pct={chip.pct} />
          </span>
        )}
      </span>
      <span className="whitespace-nowrap tabular-nums">{chip.value}</span>
      {/* The one thing a logo cannot say: WHICH of two keys on the same vendor this is. The
          strip on the dashboard spells it "OPENROUTER fallback"; here it is a single mark
          beside the logo, because two identical logos side by side is the failure mode a
          title-less pill has and a named chip does not. */}
      {chip.isFallback ? (
        <span
          aria-hidden="true"
          className="rounded-[4px] bg-row-hover px-1 text-[9px] font-bold uppercase tracking-[.06em] text-ink-300"
        >
          2
        </span>
      ) : null}
    </div>
  );
}
