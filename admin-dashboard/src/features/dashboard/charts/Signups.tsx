import type { JSX } from "react";

import { CH, CW } from "@/features/dashboard/data";
import { usePalette } from "@/features/dashboard/svg";

const L = 14;
const R = 14;
const BASE = 140;
const TOP = 16;

type Anchor = "start" | "middle" | "end";

export interface SignupsProps {
  readonly points: readonly number[];
  readonly ticks: readonly [string, string, string];
  /**
   * Per-bucket weekend flags from the adapter, which reads each point's own `startedAt`.
   * Empty on any bucket but the day — and then the hollow dot marks the tip instead, because
   * `index % 7` is a weekend only when the series happens to start on a Monday.
   */
  readonly weekend: readonly boolean[];
}

/** F2 · hairline line — sign-ups. */
export function Signups({ points, ticks: tk, weekend }: SignupsProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps
  // its light ink on a dark card; see `usePalette`.
  const PAL = usePalette();
  const vs = points;
  const N = vs.length;
  // `scale` is a divisor and needs a floor; `peakV` is a value in the series. Keeping them
  // apart is what stops an all-zero window drawing its max gridline at the top of the chart,
  // captioning a scale of 1 nothing in the data supports.
  const peakV = N > 0 ? Math.max(...vs) : 0;

  // No buckets, or no sign-up in any of them: say so. An axis drawn under a flat line at zero
  // reads as a measurement, and this one would be a measurement of nothing.
  if (N === 0 || peakV <= 0) {
    return (
      <svg
        viewBox={`0 0 ${String(CW)} ${String(CH)}`}
        preserveAspectRatio="xMidYMid meet"
        fontFamily="var(--font)"
        width="100%"
        height="100%"
        role="img"
        aria-label="No sign-ups in this window"
      >
        <text
          x={CW / 2}
          y={CH / 2}
          fontSize={10}
          fontWeight={600}
          fill={PAL.D3}
          textAnchor="middle"
          letterSpacing=".08em"
        >
          no sign-ups in this window
        </text>
      </svg>
    );
  }

  const x = (i: number): number => (N < 2 ? L : L + ((CW - L - R) * i) / (N - 1));
  const scale = peakV || 1;
  const map = (v: number): number => BASE - ((BASE - TOP) * v) / scale;

  const lastV = vs[N - 1] ?? 0;
  const d = vs.map((v, k) => (k ? "L" : "M") + x(k).toFixed(1) + " " + map(v).toFixed(1)).join(" ");

  const daily = weekend.length === N;
  const ticks: ReadonlyArray<readonly [number, string, Anchor]> = [
    [0, tk[0], "start"],
    [Math.floor((N - 1) / 2), tk[1], "middle"],
    [N - 1, tk[2], "end"],
  ];

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label="Sign-ups per bucket, hairline line chart"
    >
      {vs.map((_, i) => (
        <line
          key={`tick-${String(i)}`}
          x1={x(i)}
          y1={BASE}
          x2={x(i)}
          y2={BASE - 6}
          stroke={PAL.D5}
          strokeWidth={0.8}
        />
      ))}
      <line x1={L - 6} y1={BASE} x2={CW - R + 6} y2={BASE} stroke={PAL.D6} strokeWidth={1} />
      {peakV > 0 && (
        <line
          x1={L - 6}
          y1={map(peakV)}
          x2={CW - R + 6}
          y2={map(peakV)}
          stroke={PAL.GRID}
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}

      <path d={d} fill="none" stroke={PAL.D0} strokeWidth={1.1} strokeLinejoin="round" strokeLinecap="round" />

      {vs.map((v, k) => {
        const last = k === N - 1;
        // Weekends read as hollow dots on the daily series; coarser buckets only hollow the tip.
        const hollow = daily ? (weekend[k] ?? false) : last;
        return (
          <circle
            key={`pt-${String(k)}`}
            cx={x(k)}
            cy={map(v)}
            r={last ? 4.2 : 2.1}
            fill={last ? PAL.ACCENT : hollow ? PAL.PAPER : PAL.D0}
            stroke={last || hollow ? PAL.D0 : "none"}
            strokeWidth={last || hollow ? 1.1 : 0}
          >
            <title>{`${String(v)} sign-ups`}</title>
          </circle>
        );
      })}

      <text
        x={x(N - 1)}
        y={Math.max(12, map(lastV) - 11)}
        fontSize={10}
        fontWeight={700}
        fill={PAL.DEEP}
        textAnchor="end"
      >
        {lastV}
      </text>

      {ticks.map(([i, label, anchor]) => (
        <text
          key={anchor}
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
    </svg>
  );
}
