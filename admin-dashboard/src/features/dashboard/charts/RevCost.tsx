import type { JSX } from "react";

import { CH, CW } from "@/features/dashboard/data";
import { rnd, usePalette, uzs, type Palette } from "@/features/dashboard/svg";

const BASE = 140;
const TOP = 22;
const HW = 11;

/** Both series arrive in minor soʻm (tiyin) so they can share an axis; labels read in soʻm. */
const MINOR_PER_SOM = 100;

/**
 * The mockup carried a hand-tuned rung-worth per grain (10k / 50k / 100k soʻm). Real windows
 * have no such table, so the unit is derived: the smallest 1–2–5 step that keeps the tallest
 * ladder near this many rungs. On the mock's own daily and weekly numbers it lands on exactly
 * the units the mock hardcoded.
 */
const TARGET_RUNGS = 24;

function rungUnit(maxSom: number): number {
  if (!(maxSom > 0)) return 1;
  const rough = maxSom / TARGET_RUNGS;
  const mag = 10 ** Math.floor(Math.log10(rough));
  for (const m of [1, 2, 5]) if (rough <= m * mag) return m * mag;
  return 10 * mag;
}

export interface RevCostProps {
  /** `null` = this bucket has no point in that series. Money is never zero-filled. */
  readonly revenue: readonly (number | null)[];
  readonly cost: readonly (number | null)[];
  readonly ticks: readonly string[];
  /** Why a whole series is missing. Printed on the figure — an absent ladder alone reads as
   * a window in which nothing was earned or nothing was spent. */
  readonly revenueNote?: string | null;
  readonly costNote?: string | null;
}

/** The two notes, as the line the figure prints above the axis. */
function noteLines(revenueNote: string | null, costNote: string | null): readonly string[] {
  const out: string[] = [];
  if (revenueNote !== null) out.push(`revenue not drawn — ${revenueNote}`);
  if (costNote !== null) out.push(`cost not drawn — ${costNote}`);
  return out;
}

/**
 * One stack of rungs. Returns the y of its topmost rung so the caller can hang the value
 * label above it; the jitter seeds are per-column so neighbouring ladders never rhyme.
 */
function ladder(
  cx: number,
  n: number,
  ink: string,
  seed: number,
  hero: boolean,
  step: number,
  key: string,
  // Passed in rather than read here: this is a plain function, not a component, so it cannot
  // subscribe to the theme itself. The caller already holds the ramp.
  palette: Palette,
): { top: number; lines: JSX.Element[] } {
  const lines: JSX.Element[] = [];
  for (let k = 0; k < n; k++) {
    const y = BASE - k * step;
    const w = HW - 1.2 + rnd(k + 1, seed) * 2.4;
    lines.push(
      <line
        key={`${key}-${String(k)}`}
        x1={cx - w}
        y1={y}
        x2={cx + w}
        y2={y}
        stroke={hero && k === n - 1 ? palette.DEEP : ink}
        strokeWidth={1}
        opacity={ink === palette.D0 ? 0.6 + rnd(k + 2, seed + 3) * 0.4 : 0.5 + rnd(k + 2, seed + 5) * 0.4}
      />,
    );
  }
  // A ladder of no rungs still needs somewhere to hang its label: the baseline, never below it.
  return { top: BASE - Math.max(0, n - 1) * step, lines };
}

/** F6 · paired rungs — revenue against cost. */
export function RevCost({
  revenue,
  cost,
  ticks,
  revenueNote = null,
  costNote = null,
}: RevCostProps): JSX.Element {
  const PAL = usePalette();
  const revSom = revenue.map((v) => (v === null ? null : Math.round(v / MINOR_PER_SOM)));
  const costSom = cost.map((v) => (v === null ? null : Math.round(v / MINOR_PER_SOM)));
  // The two series are indexed on the same axis but either can be absent whole: an empty cost
  // array is "nothing in this window was priced", which is a gap, not a column of zeros.
  const N = Math.max(revSom.length, costSom.length);
  const present = [...revSom, ...costSom].filter((v): v is number => v !== null);
  const peak = present.length === 0 ? 0 : Math.max(0, ...present);
  const notes = noteLines(revenueNote, costNote);

  if (N === 0 || peak <= 0) {
    const empty = notes.length === 0 ? ["no revenue or priced cost in this window"] : notes;
    return (
      <svg
        viewBox={`0 0 ${String(CW)} ${String(CH)}`}
        preserveAspectRatio="xMidYMid meet"
        fontFamily="var(--font)"
        width="100%"
        height="100%"
        role="img"
        aria-label={empty.join("; ")}
      >
        {empty.map((line, i) => (
          <text
            key={line}
            x={CW / 2}
            y={CH / 2 + (i - (empty.length - 1) / 2) * 14}
            fontSize={10}
            fontWeight={600}
            fill={PAL.D3}
            textAnchor="middle"
            letterSpacing=".08em"
          >
            {line}
          </text>
        ))}
      </svg>
    );
  }

  const unit = rungUnit(peak);
  const rev = revSom.map((v) => (v === null ? 0 : Math.round(v / unit)));
  const cst = costSom.map((v) => (v !== null && v > 0 ? Math.max(1, Math.round(v / unit)) : 0));

  const maxR = Math.max(1, ...rev, ...cst);
  const step = Math.min(5.4, (BASE - TOP) / maxR);
  const colW = (CW - 30) / N;
  const x0 = (i: number): number => 15 + colW * (i + 0.5);

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label="Revenue against cost per bucket, paired rung ladders"
    >
      <line x1={10} y1={BASE + 4} x2={CW - 10} y2={BASE + 4} stroke={PAL.D6} strokeWidth={1} />

      {/* A missing series is stated, never left to the reader: an absent cost ladder and a
          window we spent nothing in look exactly alike. */}
      {notes.map((line, i) => (
        <text
          key={line}
          x={10}
          y={10 + i * 11}
          fontSize={8}
          fontWeight={700}
          fill={PAL.D3}
          letterSpacing=".06em"
        >
          {line}
        </text>
      ))}

      {Array.from({ length: N }, (_, i) => {
        const revRaw = revSom[i] ?? null;
        const costRaw = costSom[i] ?? null;
        const cx = x0(i);
        const xa = cx - 13;
        const xb = cx + 13;
        const hero = i === N - 1;
        const a = ladder(xa, rev[i] ?? 0, PAL.D0, i + 2, hero, step, `rev-${String(i)}`, PAL);
        const b = ladder(xb, cst[i] ?? 0, PAL.D4, i + 7, false, step, `cost-${String(i)}`, PAL);

        return (
          <g key={`col-${String(i)}`}>
            {revRaw !== null && a.lines}
            {costRaw !== null && b.lines}
            {revRaw !== null && (
              <text
                x={xa}
                y={a.top - 8}
                fontSize={9.5}
                fontWeight={700}
                fill={hero ? PAL.DEEP : PAL.D0}
                textAnchor="middle"
              >
                {uzs(revRaw)}
                <title>{`${String(revRaw)} soʻm revenue`}</title>
              </text>
            )}
            {costRaw !== null && (
              <text x={xb} y={b.top - 8} fontSize={8.5} fontWeight={700} fill={PAL.D3} textAnchor="middle">
                {uzs(costRaw)}
                <title>{`${String(costRaw)} soʻm cost`}</title>
              </text>
            )}
            <text
              x={cx}
              y={BASE + 18}
              fontSize={8}
              fontWeight={700}
              fill={PAL.MUT}
              textAnchor="middle"
              letterSpacing=".08em"
            >
              {ticks[i] ?? ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
