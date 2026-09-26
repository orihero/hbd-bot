import type { JSX } from "react";

import type { FunnelStep } from "@/features/dashboard/adapt";
import { CH, CW } from "@/features/dashboard/data";
import { RUNG_CAP, rnd, rungIndices, usePalette } from "@/features/dashboard/svg";

const BASE = 140;
const TOP = 24;
const HW = 16;

export interface FunnelProps {
  /** Orders one rung is worth. The adapter picks it off the tallest column. */
  readonly unit: number;
  readonly steps: readonly FunnelStep[];
}

interface Row {
  label: string;
  v: number;
  /** Rung level the column starts at; `from` > `to` on a drop, so the pair also carries direction. */
  from: number;
  to: number;
}

/**
 * A waterfall in rung levels: a `total` step is an absolute column off zero, anything else
 * hangs off the running level so the drops read as the gap between two totals.
 */
function buildRows(unit: number, steps: readonly FunnelStep[]): Row[] {
  const rows: Row[] = [];
  let lv = 0;
  for (const st of steps) {
    if (!Number.isFinite(st.delta)) continue;
    // EVERY total resets the running level, not just the first. Letting a later total draw
    // at the previous level made the column's height disagree with the number printed on it
    // — invisible only while the fixture happens to be arithmetically closed.
    if (st.total) {
      lv = Math.max(0, st.delta / unit);
      rows.push({ label: st.label, v: st.delta, from: 0, to: lv });
    } else {
      // The running level is floored at zero. A drop bigger than what is left of the cohort
      // means the counts came from scans that disagree; the printed delta stays the true
      // number, but a column drawn BELOW the axis would draw that disagreement as a negative
      // order count, which is not a thing that exists.
      const nxt = Math.max(0, lv + st.delta / unit);
      rows.push({ label: st.label, v: st.delta, from: nxt, to: lv });
      lv = nxt;
    }
  }
  return rows;
}

/**
 * F9 · rung waterfall — where orders drop off, dashed rungs are losses.
 *
 * The mock's fixed "25 orders" a rung and its "last 30 days" are both gone: the unit is the
 * one the adapter picked off this window's tallest column, and `order_funnel` is computed
 * over the REQUEST window, so both would be stated wrong the moment the picker moved.
 */
export function Funnel({ unit, steps }: FunnelProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps
  // its light ink on a dark card; see `usePalette`.
  const PAL = usePalette();
  // A unit of zero or less is a divisor that produces no drawing at all, and one rung per
  // order is the finest honest fallback there is.
  const u = Number.isFinite(unit) && unit > 0 ? unit : 1;
  const rows = buildRows(u, steps);

  if (rows.length === 0) {
    return <Empty note="no orders in this window" />;
  }

  const maxR = rows.reduce((m, r) => Math.max(m, r.from, r.to), 0);
  const step = (BASE - TOP) / (maxR + 1);
  const stride = Math.max(1, Math.ceil(maxR / RUNG_CAP));
  const colW = (CW - 40) / rows.length;
  const x0 = (i: number): number => 20 + colW * (i + 0.5);
  const yOf = (k: number): number => BASE - k * step;

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`Order funnel in the selected window, one rung per ${String(u)} orders, dashed rungs are drop-offs`}
    >
      <line x1={14} y1={BASE + 4} x2={CW - 14} y2={BASE + 4} stroke={PAL.D6} strokeWidth={1} />

      {rows.map((r, i) => {
        const cx = x0(i);
        const neg = r.v < 0;
        const hero = i === rows.length - 1;
        const lo = Math.min(r.from, r.to);
        // A step that moved nothing still gets its one rung: it is a stage the cohort passed
        // through, and an empty slot would read as a stage that does not exist.
        const n = Math.max(1, Math.round(Math.abs(r.to - r.from)));
        const topY = yOf(Math.max(r.from, r.to));
        const label = (neg ? "−" : "") + String(Math.abs(r.v));
        // hand-off sits at the level the next column starts from
        const yl = yOf(i === 0 ? r.to : Math.min(r.from, r.to));

        return (
          <g key={`${r.label}-${String(i)}`}>
            {rungIndices(n, stride).map((k) => {
              const y = yOf(lo + k);
              const w = HW - 1.2 + rnd(k + 1, i + 2) * 2.4;
              return neg ? (
                <line
                  key={k}
                  x1={cx - w}
                  y1={y}
                  x2={cx + w}
                  y2={y}
                  stroke={PAL.D3}
                  strokeWidth={1}
                  strokeDasharray="2.5 2.5"
                  opacity={0.75}
                />
              ) : (
                <line
                  key={k}
                  x1={cx - w}
                  y1={y}
                  x2={cx + w}
                  y2={y}
                  stroke={hero && k === n - 1 ? PAL.DEEP : PAL.D0}
                  strokeWidth={1}
                  opacity={0.6 + rnd(k + 2, i + 4) * 0.4}
                />
              );
            })}
            {i < rows.length - 1 ? (
              <line
                x1={cx + HW + 3}
                y1={yl}
                x2={x0(i + 1) - HW - 3}
                y2={yl}
                stroke={PAL.D5}
                strokeWidth={0.8}
                strokeDasharray="2 3"
              />
            ) : null}
            <text
              x={cx}
              y={topY - 9}
              fontSize={10}
              fontWeight={700}
              fill={neg ? PAL.D3 : hero ? PAL.DEEP : PAL.D0}
              textAnchor="middle"
            >
              {label}
              <title>{r.label + " — " + label + " orders"}</title>
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
              {r.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** An axis with no columns would read as a funnel nobody entered, which is a measurement. */
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
