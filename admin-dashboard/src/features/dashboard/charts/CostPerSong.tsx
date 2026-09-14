import type { JSX } from "react";

import { formatCents } from "@/features/dashboard/adapt";
import { CH, CW } from "@/features/dashboard/data";
import { RUNG_CAP, rnd, rungIndices, usePalette } from "@/features/dashboard/svg";

const BASE = 140;
const TOP = 20;
const HW = 16;

/* `RUNG_CAP` and `rungIndices` are shared with the funnel ladder in `svg.ts`: past the cap
   every `stride`-th rung is drawn, so the column keeps its exact height and its printed
   figure and only the texture thins. */

export interface CostPerSongProps {
  /** Attributed vendor spend per delivered song, in USD, oldest bucket first. */
  readonly values: readonly number[];
  readonly ticks: readonly string[];
  /** The published price a song sells for, in USD. Null = this deployment publishes none. */
  readonly priceLine: number | null;
}

interface Column {
  readonly usd: number;
  /**
   * Whole cents, floored at one: a sub-cent song is cheap, not absent.
   *
   * The LADDER stays in cents even though the labels are finer, and the stubby columns that
   * produces are the honest picture rather than a scaling bug: the ladder is sized off the
   * price line on purpose, so a column one rung tall against a fifty-rung rule is a song
   * costing a hundredth of what it sells for. Re-scaling to make the columns tall would be
   * drawing the margin away.
   */
  readonly rungs: number;
  readonly tick: string;
}

/**
 * F1 · one rung per cent of unit cost, against the dashed price the song sells for. The
 * rung ladder is sized off the price line, not off the data, so a column that ever crosses
 * the rule reads as a loss at a glance.
 *
 * Two things the fixture never had to survive. A deployment that has published no price gets
 * NO rule and no label — a rule at zero would be a price of nothing, and every column would
 * read as a loss. And a column that costs more than the price is now sized in: the ladder
 * takes the taller of price and data so the crossing is still visible instead of being drawn
 * off the top of the box where nobody sees it at all.
 */
export function CostPerSong({ values, ticks, priceLine }: CostPerSongProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps
  // its light ink on a dark card; see `usePalette`.
  const PAL = usePalette();
  const cols: Column[] = [];
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    // A negative or non-finite cost per song is two queries disagreeing, not a measurement.
    if (v === undefined || !Number.isFinite(v) || v < 0) continue;
    cols.push({ usd: v, rungs: Math.max(1, Math.round(v * 100)), tick: ticks[i] ?? "" });
  }

  if (cols.length === 0) {
    return <Empty note="no priced songs in this window" />;
  }

  // A price of zero is not a ceiling anything can be measured against, so it is treated as
  // the same silence a null is.
  const priceRungs =
    priceLine === null || !Number.isFinite(priceLine) || priceLine <= 0
      ? null
      : Math.round(priceLine * 100);

  const N = cols.length;
  const tallest = cols.reduce((m, c) => Math.max(m, c.rungs), priceRungs ?? 0);
  const step = (BASE - TOP) / (tallest + 3);
  const stride = Math.max(1, Math.ceil(tallest / RUNG_CAP));
  const colW = (CW - 60) / N;
  const x0 = (i: number): number => 30 + colW * (i + 0.5);
  const py = priceRungs === null ? 0 : BASE - priceRungs * step;
  const priceMoney = priceLine === null ? "" : formatCents(priceLine);

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={
        priceRungs === null
          ? "Cost per song, one rung per cent, no published price to compare against"
          : `Cost per song, one rung per cent, against the ${priceMoney} price line`
      }
    >
      <line x1={14} y1={BASE + 4} x2={CW - 14} y2={BASE + 4} stroke={PAL.D6} strokeWidth={1} />

      {priceRungs !== null && (
        <>
          <line
            x1={14}
            y1={py}
            x2={CW - 90}
            y2={py}
            stroke={PAL.D3}
            strokeWidth={1}
            strokeDasharray="4 4"
          />
          <text
            x={CW - 84}
            y={py + 3}
            fontSize={8}
            fontWeight={700}
            fill={PAL.D3}
            letterSpacing=".06em"
          >
            {priceMoney} PRICE
          </text>
        </>
      )}

      {cols.map((col, i) => {
        const cx = x0(i);
        const n = col.rungs;
        const hero = i === N - 1;
        // Cents, like every other unit-economics figure on this tab. `toFixed(2)` on a
        // DOLLAR rendered all three columns `$0.00` — a song costs a fraction of a cent, so
        // two decimals of a dollar is no precision at all and the labels said nothing.
        const money = formatCents(col.usd);

        return (
          <g key={i}>
            {rungIndices(n, stride).map((k) => {
              const y = BASE - k * step;
              const w = HW - 2 + rnd(k + 1, i + 2) * 3;
              return (
                <g key={k}>
                  <line
                    x1={cx - w}
                    y1={y}
                    x2={cx + w}
                    y2={y}
                    stroke={hero && k === n - 1 ? PAL.DEEP : PAL.D0}
                    strokeWidth={1}
                    opacity={0.5 + rnd(k + 2, i + 4) * 0.5}
                  />
                  {k % 5 === 4 ? <circle cx={cx + HW + 4} cy={y} r={0.8} fill={PAL.D5} /> : null}
                </g>
              );
            })}
            <text
              x={cx}
              y={BASE - (n - 1) * step - 9}
              fontSize={10}
              fontWeight={700}
              fill={hero ? PAL.DEEP : PAL.D0}
              textAnchor="middle"
            >
              {money}
              <title>{money + " per song"}</title>
            </text>
            <text
              x={cx}
              y={BASE + 18}
              fontSize={8}
              fontWeight={700}
              fill={PAL.MUT}
              textAnchor="middle"
              letterSpacing=".08em"
            >
              {col.tick}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** No axis and no columns: an empty grid would read as a window in which songs cost nothing. */
function Empty({ note }: { readonly note: string }): JSX.Element {
  const PAL = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={note}
    >
      <text
        x={CW / 2}
        y={CH / 2}
        fontSize={11}
        fontWeight={600}
        fill={PAL.D3}
        textAnchor="middle"
        letterSpacing=".04em"
      >
        {note}
      </text>
    </svg>
  );
}
