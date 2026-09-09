import type { JSX } from "react";

import type { ActivityPointView } from "@/api/dashboard";
import { formatCount } from "@/features/dashboard/adapt";
import { CH, CW } from "@/features/dashboard/data";
import { hatchLines, stepPoints, usePalette, type Palette } from "@/features/dashboard/svg";

/**
 * F10 · DAU / WAU / MAU — the recorded history of the active-accounts gauge.
 *
 * The figure claims one thing: on each night the snapshot job ran, this many accounts had been
 * seen inside the last day, the last week and the last month. Three NESTED CUTOFFS on one
 * population — `day ⊆ week ⊆ month` — taken from one predicate at one instant, which is why
 * they are three lines on one shared scale and never a stack. Stacking would triple-count
 * everybody active today and put a top line on the card that no query can produce; the faint
 * ties between the three lines are drawn to make the containment visible, so nobody reads the
 * distance between two lines as a fourth quantity. It is not one either: the gap between the
 * day line and the week line is "seen this week but not today", which is a number this chart
 * does not measure and does not print.
 *
 * What it deliberately does NOT claim:
 *
 *  * that a night with no mark had no activity. `users.last_seen_at` is a gauge that gets
 *    overwritten, so this history exists only from the first night the job ran and cannot be
 *    back-filled. A missed night is ABSENT from the payload; here it becomes a HOLE — the
 *    line stops, the band is hatched the way every unmeasured thing in this folder is hatched,
 *    and the footnote counts the holes in words. `stepPoints` never joins across one.
 *  * that the readings are samples of a smooth curve. They are nightly snapshots, so each is
 *    drawn as a tread across its own night and the change between two nights is a riser at the
 *    boundary — a slope through it would invent twenty-three hours of readings nobody took.
 *  * that the window's last day is the last reading. If the job missed last night the labels
 *    sit on the last night it did record, and the leader line shows where that was.
 *
 * A zero IS a reading here: the job ran, counted nobody, and said so. That is the one case in
 * this folder where a flat line at the axis is a measurement rather than an empty state, and
 * it gets its own words rather than the "nothing here" rendering.
 */

/** Plot box. The right gutter holds the direct labels — a legend would cost a lookup. */
const L = 14;
const GUTTER = 96;
const RIGHT = CW - GUTTER;
const BASE = 138;
const TOP = 22;

const DAY_MS = 86_400_000;

/**
 * Above this many nights between the first and last reading the stamps are not a daily series
 * at all — they are wrong — and a dense axis built from them would be tens of thousands of
 * empty slots. Past it the chart falls back to drawing the readings in the order they arrived
 * and says so, rather than rendering a decade of hatch.
 */
const MAX_SPAN_NIGHTS = 800;

/** Roughly how many containment ties to draw. Enough to read as structure, few enough to ignore. */
const TIE_COUNT = 8;

/** A gap wide enough to carry the words inside the plot rather than only in the footnote. */
const GAP_LABEL_MIN = 46;

export interface ActiveAccountsProps {
  /**
   * `AudienceResponse.activityHistory`, verbatim and oldest first — one entry per night the
   * snapshot job ran, each carrying that night's `day` / `week` / `month` counts.
   *
   * A night the job MISSED is not in this array: there is no zero row and no null row for it,
   * which is why this component re-lays the entries onto a dense nightly axis off their own
   * `startedAt` and leaves the misses as holes. Empty means "no snapshot in this window" — a
   * different sentence from `isActivityHistory: false`, and both are rendered.
   *
   * The route's grain is always `day` (`activityBucket` echoes it and takes no `?bucket=`),
   * so the nightly arithmetic here is baked in rather than passed: three gauges cannot be
   * re-bucketed by summing without counting one person once per day.
   */
  readonly history: readonly ActivityPointView[];
  /**
   * `AudienceResponse.isActivityHistory` — whether this deployment has ANY recorded history.
   *
   * `false` means the nightly job has never run here, so no range change can produce a line;
   * the remedy is to schedule the job. `true` with an empty `history` means it runs but
   * recorded nothing inside the requested window; the remedy is to widen the range. Painting
   * both as "no data" would send the operator to the wrong one.
   */
  readonly isActivityHistory: boolean;
}

/** One of the three cutoffs, ready to draw. */
interface Series {
  readonly short: string;
  readonly long: string;
  readonly ink: string;
  readonly width: number;
  readonly dash: string | undefined;
  readonly values: readonly (number | null)[];
}

/** The readings laid out on a dense nightly axis, holes and all. */
interface Dense {
  /** One slot per night between the first and last reading. `null` = the job missed it. */
  readonly slots: readonly (ActivityPointView | null)[];
  /** False = the stamps could not be trusted, so slots are the payload's own order. */
  readonly byDate: boolean;
  /** Nights inside the span with no reading. Always 0 when `byDate` is false. */
  readonly missing: number;
}

export function ActiveAccounts({ history, isActivityHistory }: ActiveAccountsProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  // The empty states come first, and they are two different sentences with two different
  // remedies. "The recorder was never installed" is not "the recorder saw nothing lately".
  if (!isActivityHistory) {
    return (
      <Empty
        headline="no activity history recorded here"
        note="the nightly DAU/WAU/MAU snapshot has never run — nothing to draw at any range"
      />
    );
  }
  if (history.length === 0) {
    return (
      <Empty
        headline="no nights recorded in this window"
        note="the snapshot job runs here — widen the range to reach the nights it wrote"
      />
    );
  }

  const dense = densify(history);
  const slots = dense.slots;
  const n = slots.length;

  const day = slots.map((s) => s?.day ?? null);
  const week = slots.map((s) => s?.week ?? null);
  const month = slots.map((s) => s?.month ?? null);

  // The scale is shared across all three — it is what makes the containment legible — and it
  // is taken off the month line, which by definition contains the other two.
  const peak = month.reduce<number>((m, v) => (v === null ? m : Math.max(m, v)), 0);
  const scale = peak > 0 ? peak : 1;

  const x = (i: number): number => (n < 2 ? L + (RIGHT - L) / 2 : L + ((RIGHT - L) * i) / (n - 1));
  const y = (v: number): number => BASE - ((BASE - TOP) * v) / scale;

  const series: readonly Series[] = [
    { short: "MAU", long: "seen in the last 30 days", ink: PAL.D4, width: 0.9, dash: "5 3", values: month },
    { short: "WAU", long: "seen in the last 7 days", ink: PAL.D2, width: 1, dash: undefined, values: week },
    { short: "DAU", long: "seen in the last 24 hours", ink: PAL.D0, width: 1.3, dash: undefined, values: day },
  ];

  // Every series has the same holes — one missed night misses all three counts — so the gaps
  // are read off the month line once and hatched once.
  const stepped = series.map((s) => stepPoints(s.values, x, y));
  const gaps = stepped[0]?.gaps ?? [];

  const present = slots.flatMap((s, i) => (s === null ? [] : [i]));
  const lastIdx = present[present.length - 1] ?? 0;
  const firstIdx = present[0] ?? 0;
  const midIdx = nearestPresent(present, Math.floor((n - 1) / 2));

  const labels = spread(
    series.map((s) => {
      const v = s.values[lastIdx] ?? 0;
      return { short: s.short, long: s.long, ink: s.ink, value: v, y: y(v) };
    }),
  );

  const stride = Math.max(1, Math.ceil(present.length / TIE_COUNT));
  const ties = present.filter((_, k) => k % stride === 0);

  const ticks: readonly (readonly [number, string, "start" | "middle" | "end"])[] = [
    [firstIdx, slots[firstIdx]?.bucket ?? "", "start"],
    ...(midIdx !== firstIdx && midIdx !== lastIdx
      ? ([[midIdx, slots[midIdx]?.bucket ?? "", "middle"]] as const)
      : []),
    ...(lastIdx !== firstIdx ? ([[lastIdx, slots[lastIdx]?.bucket ?? "", "end"]] as const) : []),
  ];

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label="Daily, weekly and monthly active accounts per night, three nested step lines; hatched bands are nights the snapshot job did not record"
    >
      <line x1={L - 6} y1={BASE} x2={RIGHT + 6} y2={BASE} stroke={PAL.D6} strokeWidth={1} />

      {/* Nights with no reading. Hatched, never interpolated and never drawn at zero — the
          same texture every unmeasured thing on this page carries. */}
      {gaps.map((g) => (
        <g key={`gap-${String(g.from)}`}>
          {hatchLines({ x: g.x1, y: TOP, width: g.x2 - g.x1, height: BASE - TOP }, 7).map((h, k) => (
            <line
              key={k}
              x1={h.x1}
              y1={h.y1}
              x2={h.x2}
              y2={h.y2}
              stroke={PAL.HATCH}
              strokeWidth={0.6}
              opacity={0.5}
            />
          ))}
          {g.x2 - g.x1 >= GAP_LABEL_MIN && (
            <text
              x={(g.x1 + g.x2) / 2}
              y={TOP - 6}
              fontSize={8}
              fontWeight={700}
              fill={PAL.D3}
              textAnchor="middle"
              letterSpacing=".08em"
            >
              not recorded
            </text>
          )}
          <title>
            {gapTitle(g.from, g.to, slots)}
          </title>
        </g>
      ))}

      {/* The containment ties: one vertical hairline from the day line to the month line at a
          handful of nights. All three counts are cutoffs on the same population at the same
          instant, and the tie says so — the lines cannot cross and are never summed. */}
      {ties.map((i) => {
        const d = day[i];
        const m = month[i];
        if (d === null || d === undefined || m === null || m === undefined) return null;
        return (
          <line
            key={`tie-${String(i)}`}
            x1={x(i)}
            y1={y(d)}
            x2={x(i)}
            y2={y(m)}
            stroke={PAL.D6}
            strokeWidth={0.8}
          />
        );
      })}

      {/* One path per unbroken run, per series. Concatenating two runs would draw the join
          this whole component exists to refuse. */}
      {series.map((s, si) => (
        <g key={s.short}>
          {(stepped[si]?.runs ?? []).map((run) => (
            <path
              key={`${s.short}-${String(run.from)}`}
              d={run.d}
              fill="none"
              stroke={s.ink}
              strokeWidth={s.width}
              strokeDasharray={s.dash}
              strokeLinejoin="round"
              strokeLinecap="butt"
            >
              <title>{`${s.short} — ${s.long}`}</title>
            </path>
          ))}
        </g>
      ))}

      {/* Direct labels instead of a legend: the reader should not have to carry an ink from a
          key to a line. They sit on the LAST RECORDED night, with a leader back to it. */}
      {labels.map((lb) => (
        <g key={lb.short}>
          <line
            x1={x(lastIdx)}
            y1={y(lb.value)}
            x2={RIGHT + 5}
            y2={lb.y}
            stroke={PAL.D5}
            strokeWidth={0.7}
            strokeDasharray="1.5 2"
          />
          <text x={RIGHT + 9} y={lb.y + 3} fontSize={9} fontWeight={700} fill={lb.ink}>
            {`${lb.short} ${formatCount(lb.value)}`}
            <title>{`${lb.short} — ${lb.long} — ${formatCount(lb.value)} accounts on the last recorded night`}</title>
          </text>
        </g>
      ))}

      {ticks.map(([i, label, anchor]) => (
        <text
          key={`tick-${anchor}`}
          x={x(i)}
          y={BASE + 16}
          fontSize={8}
          fontWeight={600}
          fill={PAL.MUT}
          textAnchor={anchor}
          letterSpacing=".1em"
        >
          {label}
        </text>
      ))}

      <text x={L} y={CH - 4} fontSize={8} fontWeight={600} fill={PAL.D3} letterSpacing=".04em">
        {footnote(dense, peak)}
      </text>
    </svg>
  );
}

/**
 * The payload's readings, re-laid onto one slot per night so a missed night becomes a hole
 * the drawing can break at. The array itself is dense in INDICES and sparse in DATES, which
 * is the one shape a step line cannot tell the truth about.
 *
 * Anything that makes the stamps untrustworthy — one that will not parse, two readings landing
 * on the same night, a span so long it cannot be a nightly series — falls back to the payload's
 * own order. That drawing is honest about the readings and silent about the misses, so the
 * footnote says which of the two the reader is looking at.
 */
function densify(history: readonly ActivityPointView[]): Dense {
  const asIs: Dense = { slots: history, byDate: false, missing: 0 };
  const stamped = history.map((p) => ({ p, ms: Date.parse(p.startedAt) }));
  if (stamped.some((s) => !Number.isFinite(s.ms))) return asIs;

  const ordered = [...stamped].sort((a, b) => a.ms - b.ms);
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  if (first === undefined || last === undefined) return asIs;

  const span = Math.round((last.ms - first.ms) / DAY_MS) + 1;
  if (span > MAX_SPAN_NIGHTS || span < history.length) return asIs;

  const slots: (ActivityPointView | null)[] = Array.from({ length: span }, () => null);
  for (const s of ordered) {
    const i = Math.round((s.ms - first.ms) / DAY_MS);
    // Two readings on one night: the stamps are not nightly, so the axis they imply is not
    // one either. Better a drawing with no holes than a drawing with invented ones.
    if (slots[i] !== null) return asIs;
    slots[i] = s.p;
  }
  return { slots, byDate: true, missing: span - history.length };
}

/** The recorded night nearest a wanted index — a tick label must name a night that exists. */
function nearestPresent(present: readonly number[], wanted: number): number {
  let best = present[0] ?? wanted;
  for (const i of present) {
    if (Math.abs(i - wanted) < Math.abs(best - wanted)) best = i;
  }
  return best;
}

interface Label {
  readonly short: string;
  readonly long: string;
  readonly ink: string;
  readonly value: number;
  readonly y: number;
}

/**
 * Three labels that would otherwise print on top of each other on a night when the three
 * counts are close — a young deployment where everybody active this month was active today.
 * Pushed apart downward from the top, which keeps their ORDER (month above week above day)
 * and so keeps them readable as the nesting they describe.
 */
function spread(labels: readonly Label[]): readonly Label[] {
  const MIN = 11;
  const CEIL = TOP - 8;
  const FLOOR = CH - 6;
  const sorted = [...labels].sort((a, b) => a.y - b.y);

  const placed: Label[] = [];
  let previous = CEIL - MIN;
  for (const lb of sorted) {
    const y = Math.max(previous + MIN, lb.y);
    placed.push({ ...lb, y });
    previous = y;
  }
  // Three counts within a few accounts of each other — a young deployment where everybody
  // active this month was active today — pushes the stack off the bottom. Lift the whole
  // block rather than clamping the last label onto its neighbour, which is how three labels
  // become one unreadable smudge.
  const overflow = (placed[placed.length - 1]?.y ?? 0) - FLOOR;
  const lift = Math.max(0, Math.min(overflow, (placed[0]?.y ?? 0) - CEIL));
  return lift > 0 ? placed.map((lb) => ({ ...lb, y: lb.y - lift })) : placed;
}

/** What a hatched band is, in words, for the reader who hovers it. */
function gapTitle(from: number, to: number, slots: readonly (ActivityPointView | null)[]): string {
  const nights = to - from + 1;
  const before = slots[from - 1]?.bucket;
  const after = slots[to + 1]?.bucket;
  const between =
    before !== undefined && after !== undefined ? ` between ${before} and ${after}` : "";
  return `${String(nights)} night${nights === 1 ? "" : "s"} not recorded${between} — the snapshot job did not run`;
}

/** One line under the axis, and it is always about what is MISSING or what was measured. */
function footnote(dense: Dense, peak: number): string {
  if (!dense.byDate) {
    return "night stamps unusable — readings drawn in the order received";
  }
  const nights = dense.slots.length;
  if (dense.missing > 0) {
    return `${formatCount(dense.missing)} of ${formatCount(nights)} nights not recorded — the line breaks there`;
  }
  if (peak === 0) {
    return `every one of ${formatCount(nights)} nights recorded — nobody was active on any of them`;
  }
  return `every one of ${formatCount(nights)} nights recorded · day ⊆ week ⊆ month, never summed`;
}

/**
 * The two "nothing to draw" renderings. An axis under three flat lines at zero would be a
 * measurement of nothing, and the reason it is empty decides what the operator does next —
 * so the reason is the drawing.
 */
function Empty({ headline, note }: { readonly headline: string; readonly note: string }): JSX.Element {
  const PAL: Palette = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`${headline} — ${note}`}
    >
      <text
        x={CW / 2}
        y={CH / 2 - 6}
        fontSize={11}
        fontWeight={600}
        fill={PAL.D3}
        textAnchor="middle"
        letterSpacing=".04em"
      >
        {headline}
      </text>
      <text
        x={CW / 2}
        y={CH / 2 + 12}
        fontSize={8}
        fontWeight={600}
        fill={PAL.D4}
        textAnchor="middle"
        letterSpacing=".06em"
      >
        {note}
      </text>
    </svg>
  );
}
