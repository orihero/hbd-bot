/**
 * `ChartFrame` — **the only file in the SPA that imports Recharts** (§11.1).
 *
 * "Recharts 2.13 behind a local `<ChartFrame>` so a swap to uPlot is one file." That is why
 * the API here is declarative data + a series list rather than a `children` slot taking
 * `<Line>` elements: the moment a screen renders a Recharts component, the swap stops being
 * one file. If you need a chart shape this does not support, add a `kind` here — do not
 * import Recharts there.
 *
 * ## What the frame guarantees, so no screen has to
 *
 *  - **One y-axis. Always.** There is no prop for a second scale. Two measures of different
 *    magnitude are two charts or one indexed series; a dual axis invents a correlation that
 *    is not in the data.
 *  - **Three channels per series.** Colour (`chartToneVar`), dash (`seriesDash`) and marker
 *    shape (`seriesMarker`). See `chartTokens.ts` for why the pinned ramp makes the second
 *    and third mandatory rather than decorative.
 *  - **Semantic series keep the status colour.** Pass `tone: "delivered"` and the series is
 *    `--st-delivered`, not ramp slot 3, on every chart in the console.
 *  - **A legend whenever there are two or more series, and a table twin always.** The
 *    `<details>` table is the WCAG-clean equivalent: every value the tooltip shows is
 *    reachable without hovering, so the tooltip enhances and never gates.
 *  - **Solid hairline grid, no vertical rules, recessive axes.** Recharts defaults the grid
 *    to `3 3` dashes; a dashed grid reads as a threshold. Overridden here once.
 *  - **`linear` interpolation, not `monotone`.** A smoothed curve between two daily buckets
 *    draws values that were never measured. These are counts per day, not a continuum.
 *  - **Refetch holds the frame.** `isRefetching` drops the plot to 70% and keeps the
 *    previous render — no skeleton flash, no layout jump.
 */

import { type ReactElement, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";

import { cn, EMPTY_VALUE, formatInteger } from "@/lib";

import {
  chartToneVar,
  markerPath,
  seriesDash,
  seriesMarker,
  type ChartTone,
} from "./chartTokens";

/** One row of plotted data. Values only — the frame formats, it never parses. */
export type ChartDatum = Readonly<Record<string, string | number | null>>;

export type ChartKind = "line" | "area" | "bar" | "stacked-bar";

export interface ChartSeriesSpec {
  /** The key in each `ChartDatum`. */
  readonly key: string;
  /** The legend and tooltip label. Our copy, never user content. */
  readonly label: string;
  /** `"delivered"`/`"failed"`/an order state for a semantic series; `"c-1"…"c-8"` otherwise. */
  readonly tone: ChartTone;
}

export interface ChartFrameProps {
  readonly title: string;
  readonly subtitle?: string;
  readonly kind: ChartKind;
  readonly data: readonly ChartDatum[];
  /** The category/time key. */
  readonly xKey: string;
  /** In render order. Slot n takes dash n and marker n. */
  readonly series: readonly ChartSeriesSpec[];
  /** The plot box INCLUDING the x-axis band, so the card never grows a nested scrollbar. */
  readonly height?: number;
  readonly formatX?: (value: string | number) => string;
  readonly formatY?: (value: number) => string;
  /** Overrides the tooltip and table rendering of one value. */
  readonly formatValue?: (value: number, seriesKey: string) => string;
  readonly isRefetching?: boolean;
  /** Copy for a chart with no rows. Distinct from an error — see §11.4's six states. */
  readonly emptyLabel?: string;
  /** A `TimeRangePicker` or a link, in the header. */
  readonly actions?: ReactNode;
  /** The `<details>` table twin. On by default; turn it off only when the same table is
   *  already on screen beside the chart. */
  readonly isTableView?: boolean;
  readonly className?: string;
}

export function ChartFrame({
  title,
  subtitle,
  kind,
  data,
  xKey,
  series,
  height = 220,
  formatX,
  formatY,
  formatValue,
  isRefetching = false,
  emptyLabel = "no data in this window",
  actions,
  isTableView = true,
  className,
}: ChartFrameProps): ReactElement {
  const rows = [...data];
  const renderValue = (value: number, key: string): string =>
    formatValue === undefined ? formatInteger(value) : formatValue(value, key);
  const renderX = (value: string | number): string =>
    formatX === undefined ? String(value) : formatX(value);

  return (
    <figure
      className={cn(
        "flex flex-col gap-4 rounded-card bg-surface-card p-card shadow-card",
        className,
      )}
      data-chart-kind={kind}
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h3 className="type-h2 text-ink">{title}</h3>
          {subtitle !== undefined && <p className="type-body-sm text-ink-muted">{subtitle}</p>}
        </div>
        {actions}
      </figcaption>

      {/* A single series needs no legend box — the title already names it. */}
      {series.length >= 2 && <ChartLegend series={series} kind={kind} />}

      <div
        style={{ height }}
        className={cn(
          "w-full",
          isRefetching && "opacity-70 transition-opacity duration-base ease-standard",
        )}
      >
        {rows.length === 0 ? (
          /* A sunken well, not a dashed outline: this design says "nothing here" with a
             recessed surface and space, and draws no dashed borders at all. */
          <div className="flex h-full flex-col items-center justify-center gap-2 rounded-2xl bg-surface-sunken px-6">
            <span aria-hidden="true" className="text-metric text-ink-muted">
              ◌
            </span>
            <p className="type-body-sm text-center text-ink-muted">{emptyLabel}</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            {renderChart({ kind, rows, xKey, series, renderX, formatY, renderValue })}
          </ResponsiveContainer>
        )}
      </div>

      {isTableView && rows.length > 0 && (
        <ChartTableView
          rows={rows}
          xKey={xKey}
          series={series}
          renderX={renderX}
          renderValue={renderValue}
          title={title}
        />
      )}
    </figure>
  );
}

/* -------------------------------------------------------------------------- */
/* The Recharts half                                                           */
/* -------------------------------------------------------------------------- */

interface RenderChartInput {
  readonly kind: ChartKind;
  readonly rows: ChartDatum[];
  readonly xKey: string;
  readonly series: readonly ChartSeriesSpec[];
  readonly renderX: (value: string | number) => string;
  readonly formatY: ((value: number) => string) | undefined;
  readonly renderValue: (value: number, key: string) => string;
}

function renderChart(input: RenderChartInput): ReactElement {
  const { kind, rows, xKey, series, renderX, formatY, renderValue } = input;

  const axes = (
    <>
      {/*
       * Solid hairline, horizontal only. Never dashed — see the header note. `--hairline` is
       * the palette's decorative rule and is explicitly exempt from the contrast bars: a
       * gridline is a positioning aid behind the data, and a grid dark enough to "pass" 3:1
       * competes with the marks it is there to support.
       */}
      <CartesianGrid stroke="var(--hairline)" strokeDasharray="0" vertical={false} />
      <XAxis
        dataKey={xKey}
        tickLine={false}
        axisLine={{ stroke: "var(--hairline-strong)" }}
        /* Tick labels are TEXT, so they take a text token, never the recessive rule colour. */
        tick={{ fill: "var(--ink-muted)", fontSize: 11 }}
        tickFormatter={(value: string | number) => renderX(value)}
        minTickGap={16}
      />
      <YAxis
        width={48}
        tickLine={false}
        axisLine={false}
        tick={{ fill: "var(--ink-muted)", fontSize: 11 }}
        tickFormatter={(value: number) => (formatY === undefined ? formatInteger(value) : formatY(value))}
      />
      <Tooltip
        cursor={
          kind === "bar" || kind === "stacked-bar"
            ? { fill: "var(--surface-control-hover)", fillOpacity: 0.7, radius: 8 }
            : { stroke: "var(--hairline-strong)", strokeWidth: 1 }
        }
        content={<ChartTooltip series={series} renderX={renderX} renderValue={renderValue} />}
      />
    </>
  );

  if (kind === "bar" || kind === "stacked-bar") {
    const isStacked = kind === "stacked-bar";
    return (
      <BarChart data={rows} margin={CHART_MARGIN}>
        {axes}
        {series.map((spec) => (
          <Bar
            key={spec.key}
            dataKey={spec.key}
            name={spec.label}
            fill={chartToneVar(spec.tone)}
            /* The 2px surface gap, painted: it separates stacked segments and adjacent
               bars alike without adding a data-weight outline. */
            stroke="var(--surface-card)"
            strokeWidth={2}
            maxBarSize={24}
            /* Rounded data-ends, anchored to the baseline. 6px rather than the dataviz
               default 4px because this design has no 4px corner anywhere; the end that
               touches the axis stays square either way, so the bar still reads from zero. */
            radius={isStacked ? 0 : [6, 6, 0, 0]}
            {...(isStacked ? { stackId: "stack" } : {})}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    );
  }

  if (kind === "area") {
    return (
      <AreaChart data={rows} margin={CHART_MARGIN}>
        {axes}
        {series.map((spec, index) => {
          const color = chartToneVar(spec.tone);
          return (
            <Area
              key={spec.key}
              type="linear"
              dataKey={spec.key}
              name={spec.label}
              stroke={color}
              strokeWidth={2}
              strokeDasharray={seriesDash(index)}
              fill={color}
              fillOpacity={0.1}
              dot={markerDot(index, color, rows.length)}
              activeDot={{ r: 5, fill: color, stroke: "var(--surface-card)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          );
        })}
      </AreaChart>
    );
  }

  return (
    <LineChart data={rows} margin={CHART_MARGIN}>
      {axes}
      {series.map((spec, index) => {
        const color = chartToneVar(spec.tone);
        return (
          <Line
            key={spec.key}
            type="linear"
            dataKey={spec.key}
            name={spec.label}
            stroke={color}
            strokeWidth={2}
            strokeDasharray={seriesDash(index)}
            strokeLinecap="round"
            strokeLinejoin="round"
            dot={markerDot(index, color, rows.length)}
            activeDot={{ r: 5, fill: color, stroke: "var(--surface-card)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        );
      })}
    </LineChart>
  );
}

/** Room for the y tick labels on the left and the x band at the bottom. */
const CHART_MARGIN = { top: 8, right: 12, bottom: 4, left: 0 } as const;

/** Past this many points a marker on every one is noise; the dash carries the channel. */
const MAX_MARKED_POINTS = 40;

/**
 * The per-point marker, as a shape — the third channel, and on this palette a necessary
 * one rather than a nicety (see `chartTokens.ts`).
 *
 * `false` past `MAX_MARKED_POINTS`: a marker on each of ninety days is a solid band, and
 * the dash pattern still separates the series.
 */
function markerDot(
  index: number,
  color: string,
  pointCount: number,
): false | ((props: { cx?: number; cy?: number }) => ReactElement) {
  if (pointCount > MAX_MARKED_POINTS) return false;
  const shape = seriesMarker(index);
  return function SeriesMarker(props: { cx?: number; cy?: number }): ReactElement {
    const { cx, cy } = props;
    if (cx === undefined || cy === undefined) return <g />;
    return (
      <path
        d={markerPath(shape, cx, cy)}
        fill={color}
        /* The 2px surface ring, so a marker stays legible where it crosses its own line. */
        stroke="var(--surface-card)"
        strokeWidth={2}
      />
    );
  };
}

/* -------------------------------------------------------------------------- */
/* Legend, tooltip, table twin — plain HTML, so they are readable and testable  */
/* -------------------------------------------------------------------------- */

function ChartLegend({
  series,
  kind,
}: {
  readonly series: readonly ChartSeriesSpec[];
  readonly kind: ChartKind;
}): ReactElement {
  const isBar = kind === "bar" || kind === "stacked-bar";
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="series legend">
      {series.map((spec, index) => (
        <li
          key={spec.key}
          /* Series labels wear a TEXT token, never the series colour — the swatch beside
             them is what carries identity. */
          className="type-body-sm flex items-center gap-2 rounded-pill bg-surface-control px-2.5 py-1 text-ink"
        >
          {/* The legend mirrors the mark: a rect for bars and areas, a keyed line for
              lines — carrying the same dash and the same marker shape. */}
          <SeriesSwatch tone={spec.tone} index={index} isBlock={isBar} />
          <span>{spec.label}</span>
        </li>
      ))}
    </ul>
  );
}

function SeriesSwatch({
  tone,
  index,
  isBlock,
}: {
  readonly tone: ChartTone;
  readonly index: number;
  readonly isBlock: boolean;
}): ReactElement {
  const color = chartToneVar(tone);
  if (isBlock) {
    return (
      <svg width={12} height={12} aria-hidden="true" className="shrink-0">
        <rect x={0} y={0} width={12} height={12} rx={4} fill={color} />
      </svg>
    );
  }
  return (
    <svg width={24} height={12} aria-hidden="true" className="shrink-0">
      <line
        x1={0}
        y1={6}
        x2={24}
        y2={6}
        stroke={color}
        strokeWidth={2}
        strokeDasharray={seriesDash(index)}
        strokeLinecap="round"
      />
      <path d={markerPath(seriesMarker(index), 12, 6, 3.4)} fill={color} />
    </svg>
  );
}

interface ChartTooltipProps extends Partial<TooltipProps<number, string>> {
  readonly series: readonly ChartSeriesSpec[];
  readonly renderX: (value: string | number) => string;
  readonly renderValue: (value: number, key: string) => string;
}

/**
 * One tooltip, every series — the pointer never has to land on a line to get a value, and
 * the value leads while the series name follows.
 */
function ChartTooltip({
  active,
  label,
  payload,
  series,
  renderX,
  renderValue,
}: ChartTooltipProps): ReactElement | null {
  if (active !== true) return null;

  /*
   * Recharts hands the hovered row through `payload`, one entry per series. A series that
   * is ABSENT from that row is a real gap — the series endpoints omit empty days rather
   * than zero-filling them — so it renders as `—` rather than as a zero the operator would
   * read as "nothing was delivered that day".
   */
  const valueOf = (key: string): number | null => {
    const entry = payload?.find((item) => item.dataKey === key);
    return typeof entry?.value === "number" ? entry.value : null;
  };

  return (
    /* A floating surface, so it takes `--shadow-overlay` — which carries the 1px `--edge`
       ring. A plain card shadow would leave the tooltip unedged against the card behind it. */
    <div className="rounded-control bg-surface-card px-3 py-2 shadow-overlay">
      <p className="type-caption text-ink-muted">
        {typeof label === "string" || typeof label === "number" ? renderX(label) : ""}
      </p>
      <ul className="mt-1 space-y-0.5">
        {series.map((spec, index) => {
          const value = valueOf(spec.key);
          return (
            <li key={spec.key} className="type-body-sm flex items-center gap-2">
              <SeriesSwatch tone={spec.tone} index={index} isBlock={false} />
              {/* Value leads, label follows: the reader already has the series. */}
              <span className="num font-semibold text-ink">
                {value === null ? EMPTY_VALUE : renderValue(value, spec.key)}
              </span>
              <span className="text-ink-muted">{spec.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ChartTableView({
  rows,
  xKey,
  series,
  renderX,
  renderValue,
  title,
}: {
  readonly rows: readonly ChartDatum[];
  readonly xKey: string;
  readonly series: readonly ChartSeriesSpec[];
  readonly renderX: (value: string | number) => string;
  readonly renderValue: (value: number, key: string) => string;
  readonly title: string;
}): ReactElement {
  return (
    /* The twin sits in a sunken well inside the card — recessed rather than boxed, and with
       no rule between it and the plot above. */
    <details className="overflow-hidden rounded-2xl bg-surface-sunken">
      <summary className="type-body-sm cursor-pointer px-4 py-2.5 text-ink-muted transition-colors duration-fast ease-standard hover:text-ink">
        table view
      </summary>
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-left" aria-label={`${title} as a table`}>
          <thead className="sticky top-0 bg-surface-sunken">
            <tr>
              <th scope="col" className="type-caption border-b border-hairline px-4 pb-1.5 text-ink-muted">
                {xKey}
              </th>
              {series.map((spec) => (
                <th
                  key={spec.key}
                  scope="col"
                  className="type-caption border-b border-hairline px-4 pb-1.5 text-right text-ink-muted"
                >
                  {spec.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const x = row[xKey];
              return (
                <tr key={String(x ?? index)}>
                  <td className="type-body-sm num px-4 py-1 text-ink-muted">
                    {x === null || x === undefined ? EMPTY_VALUE : renderX(x)}
                  </td>
                  {series.map((spec) => {
                    const value = row[spec.key];
                    return (
                      <td key={spec.key} className="type-body-sm num px-4 py-1 text-right text-ink">
                        {typeof value === "number" ? renderValue(value, spec.key) : EMPTY_VALUE}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
