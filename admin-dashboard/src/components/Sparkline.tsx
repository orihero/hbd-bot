import type { JSX } from "react";

import { usePalette } from "@/features/dashboard/svg";

const W = 60;
const H = 24;

/**
 * The 60×24 trend line tucked into the corner of a stat card. Decorative: the number it
 * accompanies is the accessible content, so the svg is hidden from assistive tech.
 */
export function Sparkline({ series }: { series: readonly number[] }): JSX.Element | null {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps
  // its light ink on a dark card; see `usePalette`.
  const PAL = usePalette();
  if (series.length < 2) return null;
  const last = series[series.length - 1];
  if (last === undefined) return null;

  const lo = Math.min(...series);
  const hi = Math.max(...series);
  const span = hi - lo || 1;
  const x = (i: number): number => 1 + ((W - 4) * i) / (series.length - 1);
  const y = (v: number): number => H - 3 - ((H - 8) * (v - lo)) / span;

  const d = series
    .map((v, i) => (i ? "L" : "M") + x(i).toFixed(2) + " " + y(v).toFixed(2))
    .join(" ");

  return (
    <svg
      className="block"
      width={W}
      height={H}
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
      focusable={false}
    >
      <path
        d={d}
        fill="none"
        stroke={PAL.D0}
        strokeWidth={1.8}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={x(series.length - 1)}
        cy={y(last)}
        r={2.4}
        fill={PAL.ACCENT}
        stroke={PAL.D0}
        strokeWidth={1}
      />
    </svg>
  );
}
