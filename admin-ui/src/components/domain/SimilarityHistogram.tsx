/**
 * `<SimilarityHistogram>` — where the verifier's scores pile up, against the threshold.
 *
 * §11.2 pairs this with the bake-off bars on `/generations/names` and says it must mark the
 * threshold and link "straight to `/config`". That link is the point: the histogram is only
 * actionable if the number it argues about is one click away. A healthy verifier is bimodal
 * with the threshold in the trough; a single lump straddling the threshold means
 * `name_match_min_similarity` is deciding coin flips, and moving it is the fix.
 *
 * ## The four channels the threshold is marked in
 *
 * dataviz's non-negotiable is that hue is never the only channel, and §11.3 says the same
 * ("Series also differ by dash pattern and marker shape"). Here the two sides of the
 * threshold are a **semantic** pair, so they take the STATUS colours — below is the failing
 * side (`--red`), at-or-above the passing side (`--green`), because green must mean the same
 * thing on every surface. That hue is then backed by three encodings that survive greyscale,
 * a red-green reader and a bad projector:
 *
 *  1. **Position** — a dashed rule at the threshold, and the axis names its value.
 *  2. **Texture** — the failing side is hatched at 45°, the passing side is solid fill.
 *  3. **A legend, plus direct labels** — two series means a legend is always present
 *     (§11.4, and dataviz's accessibility pass), each entry carrying its own count.
 *
 * ## The band is the number the screen exists for
 *
 * `band` shades the interval within which a move of the threshold changes verdicts, and
 * `nearThreshold` is how many attempts are inside it. That count is what tells an operator
 * whether moving `name_match_min_similarity` is safe — a distribution with an empty band is
 * a threshold sitting in a trough, and one with a quarter of the sample inside it is a
 * threshold deciding coin flips. Both come from the server so the chart and the tile beside
 * it cannot count different populations.
 *
 * ## Two things this refuses to draw
 *
 * `matchConfidence` is `null` on every attempt where verification did not run; those rows
 * are never bucketed at zero. A pile at 0.0 built out of rows that never ran would be an
 * argument to LOWER the threshold, which is exactly the wrong action.
 *
 * And `threshold === null` renders the distribution honestly with **no marker, no band, no
 * status colours** rather than inventing a default. `null` means this deployment publishes
 * no threshold — it never means zero. With nothing to compare against, the bars carry no
 * verdict, so they take the categorical slot rather than red and green.
 */

import type { CSSProperties, ReactElement } from "react";
import { Link } from "react-router-dom";

// The module, not the `@/components/data` barrel: `chartTokens` is a pure colour decision
// with no component imports, and pulling the barrel in would drag DataTable and the whole
// chart frame into every screen that renders a histogram.
import { chartToneVar } from "@/components/data/chartTokens";
import { cn, formatInteger } from "@/lib";
import { href } from "@/routes";

import { formatSimilarity, type SimilarityBucket } from "./similarity";

export interface SimilarityHistogramProps {
  buckets: readonly SimilarityBucket[];
  /** `name_match_min_similarity`. `null` when this deployment publishes none. */
  threshold: number | null;
  /**
   * Half-width of the "a move of this size would change these verdicts" band, from the
   * server (`thresholdBand`). Ignored when there is no threshold to centre it on.
   */
  band?: number | undefined;
  /**
   * How many scored attempts sit inside that band, from the server. `null` exactly when
   * `threshold` is — the two are published together or not at all.
   */
  nearThreshold?: number | null | undefined;
  /** Height of the plot area in px. Bars are proportional inside it. */
  height?: number | undefined;
  className?: string | undefined;
}

/** §11.2 links the histogram straight at the field it argues about. */
export const THRESHOLD_LINK_LABEL = "threshold in config →";
export const THRESHOLD_UNKNOWN_LABEL = "threshold not published by this deployment";

/** The two sides, named. A legend entry is text as well as a swatch. */
export const BELOW_THRESHOLD_LABEL = "below — verification fails";
export const AT_OR_ABOVE_THRESHOLD_LABEL = "at or above — verification passes";

/** 45° hatch, so the failing side is distinguishable with the colour removed. */
const HATCH_45 =
  "repeating-linear-gradient(45deg, rgb(0 0 0 / 0) 0 3px, var(--surface-card) 3px 4px)";

/** Keep an edge inside the plot: a threshold of 1.0 must not draw a rule off the end. */
function clampUnit(value: number): number {
  return Math.max(0, Math.min(1, value));
}

/**
 * A unit fraction as a CSS percentage, rounded to four decimals.
 *
 * The rounding is not cosmetic: `0.9 - 0.8` is `0.09999999999999998` in IEEE doubles, so an
 * unrounded band width reaches the DOM as `width: 10.000000000000009%`. That renders
 * identically and reads like a bug in every screenshot, diff and test.
 */
function percent(value: number): string {
  return `${String(Math.round(clampUnit(value) * 1e6) / 1e4)}%`;
}

export function SimilarityHistogram({
  buckets,
  threshold,
  band,
  nearThreshold,
  height = 120,
  className,
}: SimilarityHistogramProps): ReactElement {
  const peak = buckets.reduce((largest, bucket) => Math.max(largest, bucket.count), 0);
  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

  const belowCount = buckets.reduce(
    (sum, bucket) => (isBelow(bucket, threshold) ? sum + bucket.count : sum),
    0,
  );
  const aboveCount = total - belowCount;

  // The band only exists once there is a threshold to centre it on, and it is clamped into
  // [0, 1] so a threshold of 0.98 does not claim to describe scores past a perfect match.
  const bandFrom = threshold === null || band === undefined ? null : clampUnit(threshold - band);
  const bandTo = threshold === null || band === undefined ? null : clampUnit(threshold + band);

  return (
    <section
      data-testid="similarity-histogram"
      aria-label="name match confidence distribution"
      className={cn("flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card", className)}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="type-h2 text-ink">match confidence</h2>
        {threshold === null ? (
          <span className="type-body-sm text-ink-muted">{THRESHOLD_UNKNOWN_LABEL}</span>
        ) : (
          <Link
            to={href.config()}
            data-testid="similarity-threshold-link"
            className="type-body-sm text-brand underline-offset-4 hover:underline"
          >
            {`${THRESHOLD_LINK_LABEL} ${formatSimilarity(threshold)}`}
          </Link>
        )}
      </header>

      {/* Two series ⇒ a legend is always present, and each entry carries its own count so
          the sides are readable without measuring the bars. */}
      {threshold === null ? null : (
        <ul
          data-testid="similarity-legend"
          className="type-caption flex flex-wrap items-center gap-x-4 gap-y-1 text-ink-muted"
        >
          <LegendEntry label={BELOW_THRESHOLD_LABEL} count={belowCount} isBelow />
          <LegendEntry label={AT_OR_ABOVE_THRESHOLD_LABEL} count={aboveCount} isBelow={false} />
        </ul>
      )}

      <div className="flex items-baseline justify-between">
        <span className="type-caption num text-ink-muted">
          {peak === 0 ? "" : `peak ${formatInteger(peak)}`}
        </span>
      </div>

      <div className="relative" style={{ height: `${String(height)}px` }}>
        {/* The band sits UNDER the bars: it is context, not a mark. */}
        {bandFrom === null || bandTo === null ? null : (
          <span
            data-testid="similarity-threshold-band"
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 rounded-2xs bg-caution-tint"
            style={{ left: percent(bandFrom), width: percent(bandTo - bandFrom) }}
          />
        )}

        <div className="relative flex h-full items-end gap-[2px]">
          {buckets.map((bucket) => {
            const share = peak === 0 ? 0 : bucket.count / peak;
            return (
              <div
                key={`${formatSimilarity(bucket.from)}-${formatSimilarity(bucket.to)}`}
                data-testid="similarity-bucket"
                data-from={formatSimilarity(bucket.from)}
                data-count={String(bucket.count)}
                data-side={sideOf(bucket, threshold)}
                title={`${formatSimilarity(bucket.from)}–${formatSimilarity(bucket.to)}: ${formatInteger(bucket.count)}`}
                className="flex h-full flex-1 items-end"
              >
                <span
                  className="block w-full rounded-t-xs"
                  style={{
                    height: `${String(Math.round(share * 100))}%`,
                    minHeight: bucket.count > 0 ? "2px" : "0",
                    ...barFill(bucket, threshold),
                  }}
                />
              </div>
            );
          })}
        </div>

        {threshold === null ? null : (
          <span
            data-testid="similarity-threshold-marker"
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 border-l border-dashed border-ink-muted"
            style={{ left: percent(threshold) }}
          />
        )}
      </div>

      {/* The axis. The threshold's own value is printed on it, so the marker is readable
          without hovering and without the legend. */}
      <div className="type-caption relative h-4 text-ink-muted">
        <span className="num absolute left-0">0.00</span>
        {threshold === null ? null : (
          <span
            data-testid="similarity-threshold-tick"
            className="num absolute -translate-x-1/2 whitespace-nowrap text-ink"
            style={{ left: percent(threshold) }}
          >
            {formatSimilarity(threshold)}
          </span>
        )}
        <span className="num absolute right-0">1.00</span>
      </div>

      <footer className="type-body-sm flex flex-wrap items-baseline justify-between gap-2 text-ink-muted">
        <span className="num">{`${formatInteger(total)} scored attempts`}</span>
        {nearThreshold === null || nearThreshold === undefined || band === undefined ? null : (
          <span className="num" data-testid="similarity-near-threshold">
            {`${formatInteger(nearThreshold)} within ±${formatSimilarity(band)} of the threshold`}
          </span>
        )}
      </footer>
    </section>
  );
}

/** A bucket is on the failing side when every score in it is under the threshold. */
function isBelow(bucket: SimilarityBucket, threshold: number | null): boolean {
  return threshold !== null && bucket.to <= threshold;
}

function sideOf(bucket: SimilarityBucket, threshold: number | null): string {
  if (threshold === null) return "unjudged";
  return isBelow(bucket, threshold) ? "below" : "at-or-above";
}

/**
 * Colour AND texture. With no threshold there is no verdict to encode, so the bars take the
 * categorical slot rather than a status colour — green must not appear on a chart that is
 * not saying anything passed.
 */
function barFill(bucket: SimilarityBucket, threshold: number | null): CSSProperties {
  if (threshold === null) return { backgroundColor: chartToneVar("c-1") };
  return isBelow(bucket, threshold)
    ? { backgroundColor: chartToneVar("bad"), backgroundImage: HATCH_45 }
    : { backgroundColor: chartToneVar("good") };
}

function LegendEntry({
  label,
  count,
  isBelow: isFailing,
}: {
  readonly label: string;
  readonly count: number;
  readonly isBelow: boolean;
}): ReactElement {
  return (
    <li className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="inline-block h-2.5 w-4 rounded-4xs"
        style={
          isFailing
            ? { backgroundColor: chartToneVar("bad"), backgroundImage: HATCH_45 }
            : { backgroundColor: chartToneVar("good") }
        }
      />
      <span>{label}</span>
      <span className="num text-ink">{formatInteger(count)}</span>
    </li>
  );
}
