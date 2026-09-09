import type { JSX } from "react";

import { CH, CW } from "@/features/dashboard/data";
import { rnd, usePalette } from "@/features/dashboard/svg";

const L = 16;
const R = 16;
const BASE = 140;
const TOP = 18;

type Anchor = "start" | "middle" | "end";

export interface DeliveredProps {
  readonly points: readonly number[];
  readonly ticks: readonly [string, string, string];
}

/** F3 · hairline area — songs delivered. */
export function Delivered({ points, ticks: tk }: DeliveredProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps
  // its light ink on a dark card; see `usePalette`.
  const PAL = usePalette();
  const vs = points;
  const N = vs.length;
  // Two separate uses, deliberately two names: `scale` is a divisor and needs a floor,
  // `peakV` is a value in the series and must not be invented. Conflating them made an
  // all-zero series (an hourly window before the first delivery) search for a 1 that is not
  // there, and paint the peak marker at x(-1), outside the viewBox.
  const peakV = N > 0 ? Math.max(...vs) : 0;

  // An empty window and a window whose every bucket is zero are the same sentence to a
  // reader — "nothing was delivered" — and neither of them is an axis with a curve on it.
  if (N === 0 || peakV <= 0) {
    return (
      <svg
        viewBox={`0 0 ${String(CW)} ${String(CH)}`}
        preserveAspectRatio="xMidYMid meet"
        fontFamily="var(--font)"
        width="100%"
        height="100%"
        role="img"
        aria-label="No songs delivered in this window"
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
          no songs delivered in this window
        </text>
      </svg>
    );
  }

  const x = (i: number): number => (N < 2 ? L : L + ((CW - L - R) * i) / (N - 1));
  const scale = peakV || 1;
  const map = (v: number): number => BASE - ((BASE - TOP) * v) / scale;

  const peak = peakV > 0 ? vs.indexOf(peakV) : -1;
  const lastV = vs[N - 1] ?? 0;

  const d = vs.map((v, k) => (k ? "L" : "M") + x(k).toFixed(1) + " " + map(v).toFixed(1)).join(" ");

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
      aria-label="Songs delivered per bucket, hairline area chart"
    >
      <line x1={L - 8} y1={BASE} x2={CW - R + 8} y2={BASE} stroke={PAL.D6} strokeWidth={1} />

      {vs.map((v, k) => {
        const last = k === N - 1;
        const isPeak = k === peak;
        return (
          <line
            key={`stem-${String(k)}`}
            x1={x(k)}
            y1={BASE}
            x2={x(k)}
            y2={map(v)}
            stroke={last ? PAL.D0 : isPeak ? PAL.D0 : PAL.D2}
            strokeWidth={isPeak || last ? 1.2 : 0.6}
            strokeDasharray={last ? "2 2" : undefined}
            opacity={isPeak || last ? 1 : 0.5 + rnd(k + 1, 7) * 0.45}
          />
        );
      })}

      <path d={d} fill="none" stroke={PAL.D0} strokeWidth={1.2} strokeLinejoin="round" strokeLinecap="round" />

      {peak >= 0 && peak !== N - 1 && (
        <>
          <circle cx={x(peak)} cy={map(peakV)} r={3.6} fill={PAL.D0}>
            <title>{`${String(peakV)} delivered`}</title>
          </circle>
          <text
            x={x(peak)}
            y={Math.max(12, map(peakV) - 9)}
            fontSize={9.5}
            fontWeight={700}
            fill={PAL.D0}
            textAnchor="middle"
          >
            {peakV}
          </text>
        </>
      )}

      <circle cx={x(N - 1)} cy={map(lastV)} r={4.2} fill={PAL.ACCENT} stroke={PAL.D0} strokeWidth={1.1}>
        <title>{`${String(lastV)} delivered`}</title>
      </circle>
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
