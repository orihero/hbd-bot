/**
 * `Sparkline` — §11.4's micro-trend, e.g. `/users`' 30-day new-user line.
 *
 * Hand-drawn SVG rather than Recharts, for two reasons. Recharts lives behind `ChartFrame`
 * so a swap to uPlot is one file (§11.1), and a sparkline dragging a chart library into
 * every `StatTile` would defeat that fence. And a sparkline has no axes, no grid, no
 * tooltip and no legend — it is a path and one end-dot. There is nothing for a chart library
 * to do here except cost 40 KB and a `ResponsiveContainer` measurement pass.
 *
 * Mark spec (dataviz): 2px stroke with round joins, an end marker of at least 8px carrying a
 * 2px ring in the card colour (`--surface-card`) so it stays legible where it crosses the
 * line, and an area wash at ~10% opacity rather than a saturated block.
 *
 * `isFullBleed` is the Gogo stat-tile mode: the line stretches to the container's width and
 * the wash runs into the card's rounded bottom edge. It trades the end marker away and
 * relies on `vector-effect: non-scaling-stroke` to keep the 2px stroke 2px under a
 * non-uniform scale — see the two notes at those lines.
 *
 * It is `role="img"` with a real `aria-label`, because a trend line is genuinely unreadable
 * without one and the numbers behind it belong in the caller's table or tile anyway — a
 * sparkline never gates a value.
 */

import { useId, type ReactElement } from "react";

import { cn, EMPTY_VALUE, formatInteger } from "@/lib";

export interface SparklineProps {
  /** Oldest first. Gaps must already be filled by the caller — the series endpoints omit
   *  empty days rather than zero-filling them, and only the caller knows which it meant. */
  readonly values: readonly number[];
  /** What the line is. Becomes the accessible name; the first and last values are appended. */
  readonly label: string;
  readonly width?: number;
  readonly height?: number;
  /** A CSS colour expression — a token `var()`, never a hex. Defaults to slot 1. */
  readonly colorVar?: string;
  /** Adds the 10% wash under the line. */
  readonly isArea?: boolean;
  /**
   * Stretch to the container's width and run the wash into its edges — the Gogo stat tile's
   * bottom band. See the note below on what this trades away.
   */
  readonly isFullBleed?: boolean;
  readonly className?: string;
}

/** Room for the 2px stroke, the r=4 end dot and its 2px surface ring. */
const PADDING = 6;

export function Sparkline({
  values,
  label,
  width = 120,
  height = 28,
  colorVar = "var(--c-1)",
  isArea = false,
  isFullBleed = false,
  className,
}: SparklineProps): ReactElement {
  const gradientId = useId();
  const finite = values.filter((value) => Number.isFinite(value));

  if (finite.length < 2) {
    return (
      <span className={cn("num text-ink-muted", className)} title={label}>
        {EMPTY_VALUE}
      </span>
    );
  }

  const min = Math.min(...finite);
  const max = Math.max(...finite);
  // A flat series is a real answer, not a divide-by-zero: draw it down the middle.
  const span = max - min === 0 ? 1 : max - min;
  /*
   * Full bleed spends the horizontal padding — the first and last points sit exactly on the
   * edges, which is the whole point of the mode — and keeps the vertical padding, because a
   * 2px stroke at the top of the box is a 1px stroke without it.
   */
  const padX = isFullBleed ? 0 : PADDING;
  const innerWidth = width - padX * 2;
  const innerHeight = height - PADDING * 2;

  const points = finite.map((value, index) => {
    const x = padX + (innerWidth * index) / (finite.length - 1);
    const y =
      max - min === 0
        ? PADDING + innerHeight / 2
        : PADDING + innerHeight - ((value - min) / span) * innerHeight;
    return { x, y };
  });

  const linePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");

  const first = points[0];
  const last = points[points.length - 1];
  const firstValue = finite[0];
  const lastValue = finite[finite.length - 1];
  if (first === undefined || last === undefined || firstValue === undefined || lastValue === undefined) {
    return (
      <span className={cn("num text-ink-muted", className)} title={label}>
        {EMPTY_VALUE}
      </span>
    );
  }

  /* Full bleed carries the wash all the way to the bottom edge; the padded form stops at the
     baseline so the box has a floor. */
  const areaFloor = isFullBleed ? height : height - PADDING;
  const areaPath = `${linePath} L${last.x.toFixed(2)},${String(areaFloor)} L${first.x.toFixed(
    2,
  )},${String(areaFloor)} Z`;

  return (
    <svg
      role="img"
      aria-label={`${label}: ${formatInteger(firstValue)} to ${formatInteger(lastValue)} over ${formatInteger(finite.length)} points`}
      {...(isFullBleed ? {} : { width })}
      height={height}
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      /* Non-uniform scaling is what makes the stretched mode work at all; `vector-effect`
         below is what stops it from also stretching the 2px stroke into a wedge. */
      {...(isFullBleed ? { preserveAspectRatio: "none" as const } : {})}
      className={cn(isFullBleed ? "block w-full" : "overflow-visible", className)}
      data-point-count={finite.length}
      data-full-bleed={isFullBleed ? "true" : undefined}
    >
      {isArea && (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colorVar} stopOpacity={0.18} />
              <stop offset="100%" stopColor={colorVar} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#${gradientId})`} stroke="none" />
        </>
      )}

      <path
        d={linePath}
        fill="none"
        stroke={colorVar}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect={isFullBleed ? "non-scaling-stroke" : undefined}
      />

      {/*
       * The end marker: r=4 (8px), ringed in the CARD colour so it reads where it overlaps
       * the line. Full bleed omits it — the last point sits exactly on the container's edge,
       * where a dot is half-clipped, and a circle is the one mark `preserveAspectRatio="none"`
       * would draw as an ellipse. The label still carries the last value either way.
       */}
      {!isFullBleed && (
        <circle
          cx={last.x}
          cy={last.y}
          r={4}
          fill={colorVar}
          stroke="var(--surface-card)"
          strokeWidth={2}
        />
      )}
    </svg>
  );
}
