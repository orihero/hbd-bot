import type { JSX } from "react";

import { formatUsd, type CostSplitRow } from "@/features/dashboard/adapt";
import { CH, CW } from "@/features/dashboard/data";
import { COST_SPLIT_LANE, rnd, usePalette, type Palette } from "@/features/dashboard/svg";

const X0 = 158;
const PX = 13;
const PITCH = 32;
const Y0 = 30;
/**
 * The four inks a row can be drawn in, darkest first — or lightest first on the dark palette,
 * which is the same statement about DISTANCE FROM THE GROUND. A function rather than a
 * constant because the ramp now depends on the theme, and a module-level array would freeze
 * whichever palette was loaded first.
 */
function shadesOf(palette: Palette): readonly [string, string, string, string] {
  return [palette.D0, palette.D1, palette.D2, palette.D3];
}

/**
 * The lane a row's ticks live in, in ticks — it is the guide rule's own length (the line is
 * drawn to `X0 + LANE * PX`), so the cap is the geometry's. Shared with the adapter, which
 * sizes the tick unit against it, and with the caption, which prints that unit.
 */
const LANE = COST_SPLIT_LANE;

/**
 * How many rows the 176-unit box holds: row `i` puts its last mark at `Y0 + i*PITCH + 13`,
 * so the fifth row (i = 4) is the last one wholly on the canvas.
 */
const MAX_ROWS = 5;

export interface CostSplitProps {
  readonly rows: readonly CostSplitRow[];
  /** What one tick is worth, chosen per window by the adapter. The caption prints the same. */
  readonly tickUsd: number;
}

/**
 * F5 · one tick per `tickUsd` of vendor spend, rows ordered heaviest first so the hero row is
 * always the one worth arguing about. The unit is the adapter's, chosen off the heaviest row
 * so the ladder encodes the ratio between vendors instead of saturating at a fixed $75.
 *
 * The mock's "over the last 30 days" is gone from the copy: `vendor_spend_split` is computed
 * over the REQUEST window, so the span is whatever the period picker says, and printing a
 * fixed 30 days beside it would misdate every figure in the chart.
 *
 * Order is a CORRECTNESS precondition here, not a preference: the hero styling and the ink
 * ramp are both positional, so an unsorted response would paint the smallest vendor as the
 * one to argue about. The adapter sorts; this sorts again rather than trust it, which costs
 * nothing on an already-ordered list.
 */
export function CostSplit({ rows, tickUsd }: CostSplitProps): JSX.Element {
  const PAL = usePalette();
  const SHADES = shadesOf(PAL);
  // A non-finite or zero unit would make every ladder a division by nothing; the adapter
  // floors it, and this floors it again rather than trust a prop.
  const unit = Number.isFinite(tickUsd) && tickUsd > 0 ? tickUsd : 1;
  const drawn = fold(
    [...rows].filter((r) => Number.isFinite(r.usd) && r.usd > 0).sort((a, b) => b.usd - a.usd),
    unit,
  );

  if (drawn.length === 0) {
    return <Empty note="no priced vendor spend in this window" />;
  }

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`Vendor cost split in the selected window, one tick per ${formatUsd(unit)}`}
    >
      {drawn.map((r, i) => {
        const y = Y0 + i * PITCH;
        const hero = i === 0;
        // Past the fourth row the ramp is spent. Rows five and beyond keep the FAINTEST ink
        // rather than cycling back to the darkest, which would paint a tail vendor as a hero.
        const shade = SHADES[Math.min(i, SHADES.length - 1)] ?? PAL.D3;
        const total = "$" + r.usd.toFixed(2);
        // A row always draws at least one tick: it is spend that happened, and an empty lane
        // beside a dollar figure reads as a vendor we were billed by and never called.
        // One value feeds both the drawing and the overflow marker: reading `over` off the
        // raw count while drawing from a fallback let a non-finite `ticks` clip a row
        // silently.
        const wanted = Number.isFinite(r.ticks) ? Math.round(r.ticks) : Math.round(r.usd / unit);
        const ticks = Math.max(1, Math.min(LANE, wanted));
        const over = wanted > LANE;
        const laneEnd = X0 + LANE * PX;

        return (
          <g key={`${r.vendor}-${String(i)}`}>
            <text
              x={X0 - 12}
              y={y + 3}
              fontSize={8}
              fontWeight={700}
              fill={hero ? PAL.DEEP : PAL.MUT}
              textAnchor="end"
              letterSpacing=".08em"
            >
              {r.vendor}
            </text>
            <line
              x1={X0}
              y1={y + 9}
              x2={laneEnd}
              y2={y + 9}
              stroke={PAL.GRID}
              strokeWidth={0.8}
            />
            {Array.from({ length: ticks }, (_, k) => {
              const x = X0 + k * PX + PX / 2;
              const h = 10 + rnd(k + 1, i + 2) * 6;
              return (
                <g key={k}>
                  <line
                    x1={x}
                    y1={y + 9}
                    x2={x}
                    y2={y + 9 - h}
                    stroke={shade}
                    strokeWidth={hero ? 1.4 : 1}
                    opacity={0.55 + rnd(k + 3, i + 5) * 0.45}
                  />
                  {k % 5 === 4 ? <circle cx={x} cy={y + 13} r={0.8} fill={PAL.D5} /> : null}
                </g>
              );
            })}
            {/* A row wider than the lane is drawn to the lane and then says so: the printed
                total is the measurement, and a silently clipped ladder would read as a tie
                with every other row that happened to run off the same edge. */}
            {over && (
              <line
                x1={laneEnd + 3}
                y1={y + 9}
                x2={laneEnd + 18}
                y2={y + 9}
                stroke={PAL.D3}
                strokeWidth={0.8}
                strokeDasharray="2 2"
              />
            )}
            <text
              x={over ? laneEnd + 22 : X0 + ticks * PX + 12}
              y={y + 4}
              fontSize={11}
              fontWeight={700}
              fill={hero ? PAL.DEEP : PAL.D0}
            >
              {total}
              <title>{r.vendor + " — " + total + " in this window"}</title>
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/**
 * The box holds five rows; the API can return a dozen vendors. The overflow is SUMMED into a
 * last row rather than dropped, because a dropped row is spend that leaves the chart without
 * leaving the bill.
 */
function fold(rows: readonly CostSplitRow[], tickUsd: number): readonly CostSplitRow[] {
  if (rows.length <= MAX_ROWS) return rows;
  const tail = rows.slice(MAX_ROWS - 1);
  const usd = tail.reduce((sum, r) => sum + r.usd, 0);
  return [
    ...rows.slice(0, MAX_ROWS - 1),
    { vendor: `+${String(tail.length)} MORE`, usd, ticks: Math.max(1, Math.round(usd / tickUsd)) },
  ];
}

/** Bare rows with no ticks would read as vendors we used and paid nothing for. */
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
