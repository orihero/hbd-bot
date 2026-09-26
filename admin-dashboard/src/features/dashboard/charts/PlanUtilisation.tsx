import type { JSX } from "react";

import { CW } from "@/features/dashboard/data";
import { usePalette } from "@/features/dashboard/svg";

/**
 * A taller box than the 176 the full-width figures use. This chart is destined for a two-up
 * row, where a 651-wide viewBox renders its `fontSize` 8 ticks at roughly 3.7 screen pixels.
 * The type does not shrink (house rule 3), so the BOX grows instead: at 651×244 the same
 * label is drawn 39% larger relative to the width, and the tick row is cut to three.
 */
const VH = 244;
const L = 26;
const R = 26;
const BASE = 186;
const TOP = 40;

/**
 * Below this many ended plans the comb is a row of 1s and 0s — a shape a reader will
 * happily interpret as bimodal when it is nothing but the arrival order of seven customers.
 * Under the floor the figure prints the counts instead and says why.
 */
export const SPARSE_MIN_PLANS = 20;

export interface PlanUtilisationBin {
  /** Lower edge of the bin, 0..1 — the wire's `from`. */
  readonly from: number;
  /** Upper edge of the bin, 0..1 — the wire's `to`. The LAST bin is closed above. */
  readonly to: number;
  /**
   * Ended plans landing in this bin. A `0` here is an EMPTY BIN, which is a measurement:
   * the route returns all ten bins always, so a zero is "nobody finished at this ratio",
   * never "we did not look". There is no null.
   */
  readonly count: number;
}

export interface PlanUtilisationProps {
  /**
   * The bins, lowest edge first, exactly as the route publishes them. Ten of them today;
   * the component reads `bins.length` rather than assuming, and treats the LAST bin as the
   * closed one (`songs_used >= songs_included`) because that is what the route folds into it.
   */
  readonly bins: readonly PlanUtilisationBin[];
  /**
   * The histogram's denominator: plans that have ENDED. Not live plans — a running plan's
   * ratio is not final, and the route deliberately leaves it out. `0` means no plan has
   * finished yet, which is a different sentence from "no plan was ever sold".
   */
  readonly endedPlans: number;
  /**
   * False means no plan has ever been sold on this deployment, so ten empty bins are
   * "nothing to show" rather than "everybody used nothing".
   */
  readonly isPlanRevenue: boolean;
  /**
   * Preformatted instant the route computed the histogram at. The chart does not format
   * dates — pass the page's own rendering of the wire's `asOf`. Printed because this figure
   * takes NO window and must not be read as obeying the page's range picker.
   */
  readonly asOfLabel: string;
}

/**
 * F10 · comb histogram — how much of an ended plan its holder actually claimed.
 *
 * Ten hairline stems off one baseline, ordered by `songs_used ÷ songs_included`. The claim
 * is narrow and worth stating: of the plans that have ALREADY ENDED, this is where their
 * final consumption ratio fell. It says nothing about running plans, whose ratio is not
 * final, and the route excludes them for exactly that reason — counting them would move a
 * finished bar every time somebody claims a song.
 *
 * **No mean and no median is printed beside it, deliberately.** The distribution here is
 * expected to be bimodal — plans bought and barely touched pile up against 0%, plans burnt
 * to the last song pile up against 100% — and the average of those two piles names a plan
 * that does not exist. A reader given one number will use the number; the shape is the
 * finding, so only the shape is offered.
 *
 * The closed top bin is drawn in ACCENT because it is the bin the figure is about: a plan
 * at `used >= included` is a customer who wanted more than they bought, and it is the only
 * bin that answers a pricing question. It is closed above, so it also absorbs any plan whose
 * `songs_used` overran its allowance; the caption says so rather than letting the last stem
 * pass as just another tenth.
 *
 * **This figure takes no window.** `GET /api/metrics/plans` publishes a state, not a flow,
 * and sits in a page that has a range picker at the top of it. So the instant is printed on
 * the figure and the caption says the range does not reach it — an unlabelled chart under a
 * picker is a chart the picker is assumed to control.
 */
export function PlanUtilisation({
  bins,
  endedPlans,
  isPlanRevenue,
  asOfLabel,
}: PlanUtilisationProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  // Nothing was ever sold: ten empty bins would read as ten measurements of zero usage.
  if (!isPlanRevenue) {
    return <Empty note="no plan has ever been sold here" sub="nothing to bin" />;
  }
  // Plans exist but none has finished. Not the same sentence, so not the same rendering: the
  // histogram is over ENDED plans, and none has ended.
  if (bins.length === 0 || endedPlans <= 0) {
    return (
      <Empty
        note="no plan has ended yet"
        sub="a running plan's ratio is not final"
      />
    );
  }

  const counts = bins.map((b) => (Number.isFinite(b.count) && b.count > 0 ? b.count : 0));
  const total = counts.reduce((sum, c) => sum + c, 0);

  // The denominator says plans have ended and every bin is empty: the two disagree, and the
  // honest rendering says which one it trusts rather than drawing a flat comb.
  if (total <= 0) {
    return (
      <Empty
        note={`${String(endedPlans)} plans ended, none binned`}
        sub="the histogram and its denominator disagree"
      />
    );
  }

  // Too few endings for a shape. A comb of 1s reads as structure; the counts do not pretend.
  if (endedPlans < SPARSE_MIN_PLANS) {
    return <Sparse bins={bins} counts={counts} endedPlans={endedPlans} asOfLabel={asOfLabel} />;
  }

  const N = bins.length;
  const slot = (CW - L - R) / N;
  const cx = (i: number): number => L + slot * (i + 0.5);
  const peak = Math.max(...counts);
  const scale = peak || 1;
  const map = (c: number): number => BASE - ((BASE - TOP) * c) / scale;
  const closed = N - 1;

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`Plan utilisation of ${String(endedPlans)} ended plans, ${String(N)} bins of songs used divided by songs included; the last bin is closed and holds plans that used their whole allowance`}
    >
      {/* The peak rule, dashed, so a stem's height is readable as a count and not just as
          taller-than-its-neighbour. */}
      <line
        x1={L - 8}
        y1={map(peak)}
        x2={CW - R + 8}
        y2={map(peak)}
        stroke={PAL.GRID}
        strokeWidth={1}
        strokeDasharray="2 2"
      />
      <text x={L - 10} y={map(peak) + 3} fontSize={8} fontWeight={600} fill={PAL.MUT} textAnchor="end">
        {peak}
      </text>

      <line x1={L - 8} y1={BASE} x2={CW - R + 8} y2={BASE} stroke={PAL.D6} strokeWidth={1} />

      {bins.map((bin, i) => {
        const c = counts[i] ?? 0;
        const isClosed = i === closed;
        const label = binLabel(bin, isClosed);
        return (
          <g key={`bin-${String(i)}`}>
            {/* Every bin gets its foot tick, empty or not: the slot is a measured bin and an
                unmarked gap would read as a bin the route did not return. */}
            <line
              x1={cx(i)}
              y1={BASE}
              x2={cx(i)}
              y2={BASE + 5}
              stroke={PAL.D5}
              strokeWidth={0.8}
            />
            {c > 0 ? (
              <line
                x1={cx(i)}
                y1={BASE}
                x2={cx(i)}
                y2={map(c)}
                stroke={isClosed ? PAL.ACCENT : PAL.D0}
                strokeWidth={isClosed ? 1.8 : 1.1}
                strokeLinecap="round"
              >
                <title>{`${label} — ${String(c)} of ${String(endedPlans)} ended plans`}</title>
              </line>
            ) : (
              // An empty bin is a measurement of zero. It gets a hollow dot on the baseline
              // rather than nothing at all, so "no plan finished here" is drawn.
              <circle cx={cx(i)} cy={BASE} r={1.6} fill={PAL.PAPER} stroke={PAL.D3} strokeWidth={0.9}>
                <title>{`${label} — no ended plan`}</title>
              </circle>
            )}
            {c > 0 && (
              <text
                x={cx(i)}
                y={map(c) - 7}
                fontSize={9}
                fontWeight={isClosed ? 700 : 600}
                fill={isClosed ? PAL.DEEP : PAL.D0}
                textAnchor="middle"
              >
                {c}
              </text>
            )}
          </g>
        );
      })}

      {/* Three ticks, not ten. At half width a tenth-by-tenth axis is 3.7px type; the bins
          are ordered and evenly spaced, so the two ends and the middle place every one. */}
      <text x={L} y={BASE + 18} fontSize={8} fontWeight={600} fill={PAL.MUT} textAnchor="start" letterSpacing=".1em">
        0%
      </text>
      <text x={(L + CW - R) / 2} y={BASE + 18} fontSize={8} fontWeight={600} fill={PAL.MUT} textAnchor="middle" letterSpacing=".1em">
        50%
      </text>
      <text x={CW - R} y={BASE + 18} fontSize={8} fontWeight={600} fill={PAL.MUT} textAnchor="end" letterSpacing=".1em">
        100%
      </text>

      <text x={L} y={BASE + 34} fontSize={9} fontWeight={600} fill={PAL.D2}>
        {`${String(endedPlans)} ended plans · songs used ÷ songs included · last bin is closed (used ≥ included)`}
      </text>
      <text x={L} y={BASE + 48} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".04em">
        {`state as of ${asOfLabel} · every plan that has ever ended`}
      </text>
    </svg>
  );
}

/** `0–10%`, and the closed bin says it is closed rather than passing as another tenth. */
function binLabel(bin: PlanUtilisationBin, isClosed: boolean): string {
  const lo = Math.round(bin.from * 100);
  const hi = Math.round(bin.to * 100);
  return `${String(lo)}–${String(hi)}%${isClosed ? "+" : ""}`;
}

interface SparseProps {
  readonly bins: readonly PlanUtilisationBin[];
  readonly counts: readonly number[];
  readonly endedPlans: number;
  readonly asOfLabel: string;
}

/**
 * Under `SPARSE_MIN_PLANS` endings the comb is noise a reader will over-read, so the counts
 * are printed instead. This is not an empty state — the data is here and all of it is
 * shown; only the DRAWING is withheld, and the note says which.
 */
function Sparse({ bins, counts, endedPlans, asOfLabel }: SparseProps): JSX.Element {
  const PAL = usePalette();
  const last = bins.length - 1;
  const cells = bins.map((bin, i) => ({
    label: binLabel(bin, i === last),
    count: counts[i] ?? 0,
    closed: i === last,
  }));
  const perRow = Math.ceil(cells.length / 2);
  const colW = (CW - L - R) / perRow;

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`Only ${String(endedPlans)} plans have ended, too few to draw a distribution; the per-bin counts are printed instead`}
    >
      <text x={L} y={54} fontSize={11} fontWeight={700} fill={PAL.DEEP} letterSpacing=".02em">
        {`${String(endedPlans)} ended plans — too few for a shape`}
      </text>
      {[0, 1].map((row) => (
        <g key={`row-${String(row)}`}>
          {cells.slice(row * perRow, row * perRow + perRow).map((cell, k) => {
            const x = L + colW * (k + 0.5);
            const y = 116 + row * 46;
            return (
              <g key={cell.label}>
                <text
                  x={x}
                  y={y}
                  fontSize={14}
                  fontWeight={700}
                  fill={cell.count > 0 ? (cell.closed ? PAL.ACCENT : PAL.D0) : PAL.D3}
                  textAnchor="middle"
                >
                  {cell.count}
                </text>
                <text
                  x={x}
                  y={y + 13}
                  fontSize={8}
                  fontWeight={600}
                  fill={PAL.MUT}
                  textAnchor="middle"
                  letterSpacing=".06em"
                >
                  {cell.label}
                </text>
              </g>
            );
          })}
        </g>
      ))}

      <text x={L} y={VH - 14} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".04em">
        {`songs used ÷ songs included · last bin is closed (used ≥ included) · state as of ${asOfLabel}`}
      </text>
    </svg>
  );
}

/**
 * Ten stems standing on a baseline at zero would read as ten plans that used nothing. Write
 * the reason instead, in words, before any geometry exists (house rule 5).
 */
function Empty({ note, sub }: { readonly note: string; readonly sub: string }): JSX.Element {
  const PAL = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`${note} — ${sub}`}
    >
      <text
        x={CW / 2}
        y={VH / 2 - 6}
        fontSize={12}
        fontWeight={700}
        fill={PAL.D3}
        textAnchor="middle"
        letterSpacing=".06em"
      >
        {note}
      </text>
      <text
        x={CW / 2}
        y={VH / 2 + 12}
        fontSize={9}
        fontWeight={600}
        fill={PAL.MUT}
        textAnchor="middle"
        letterSpacing=".02em"
      >
        {sub}
      </text>
    </svg>
  );
}
