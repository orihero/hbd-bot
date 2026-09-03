/**
 * `StateDistributionBar` — the dominant signal on `/orders`.
 *
 * §11.2: "A full-width 8px stacked state-distribution bar under the filter bar, before the
 * eye reaches row one." That sentence fixes four things, and each is a prop this component
 * does not have: it is full width, it is 8px, it is stacked, and it sits above the table.
 * Callers choose the data and nothing else.
 *
 * **Segment order is `ORDER_STATE_VALUES`, always.** That tuple's declaration order is the
 * lifecycle — draft → … → delivered → failed → cancelled — so the bar reads left to right
 * as the pipeline. Sorting by count would repaint the bar every poll and put `failed`
 * somewhere different on every screen; `enums.ts` says a `.sort()` on that tuple is a bug.
 * A state with zero orders is absent from the API's `ordersByState` and is skipped here, so
 * an empty state contributes no segment and no legend row rather than a 0-width sliver.
 *
 * Colour comes from the `--st-*` tokens via `orderStateColorVar`, which is the same colour
 * the row's `StatusPill` uses — green means delivered on this bar, in that pill, and in
 * every chart, and nowhere else does green mean anything.
 *
 * Separation is the dataviz **surface gap**: a 2px gap in the surface colour between
 * segments, never a stroke drawn around them. Proportions survive it because each segment
 * is `flex-grow: count; flex-basis: 0`, so the gaps come out of the container and the
 * remaining space is divided exactly by count.
 */

import { type ReactElement } from "react";

import { ORDER_STATE_VALUES, type OrderState, type OrderStateCount } from "@/api";
import { cn, formatInteger, formatRate, humaniseEnum, orderStateColorVar, statusGlyph } from "@/lib";

import { orderStateTintVar } from "./chartTokens";

export interface StateDistributionBarProps {
  /** From `ordersByState`. States with zero orders are absent, not zero-filled. */
  readonly counts: readonly OrderStateCount[];
  /** Show the glyph + label + count legend beneath. On by default: an 8px band of colour
   *  is not readable on its own, and colour is never the only channel here either. */
  readonly isLegend?: boolean;
  /** Held at 70% while the next page loads — the previous shape stays, never a skeleton. */
  readonly isRefetching?: boolean;
  readonly className?: string;
  /** Names the bar for assistive tech. */
  readonly label?: string;
}

export function StateDistributionBar({
  counts,
  isLegend = true,
  isRefetching = false,
  className,
  label = "orders by state",
}: StateDistributionBarProps): ReactElement {
  const byState = new Map<OrderState, number>();
  for (const entry of counts) {
    byState.set(entry.state, (byState.get(entry.state) ?? 0) + entry.count);
  }

  // Lifecycle order, never count order. See the note above.
  const segments = ORDER_STATE_VALUES.map((state) => ({
    state,
    count: byState.get(state) ?? 0,
  })).filter((segment) => segment.count > 0);

  const total = segments.reduce((sum, segment) => sum + segment.count, 0);

  const summary =
    total === 0
      ? `${label}: none`
      : `${label}: ${segments
          .map(
            (segment) =>
              `${humaniseEnum(segment.state)} ${formatInteger(segment.count)} (${formatRate(
                segment.count / total,
                0,
              )})`,
          )
          .join(", ")}`;

  return (
    <div
      className={cn(
        "flex flex-col gap-2",
        isRefetching && "opacity-70 transition-opacity duration-base ease-standard",
        className,
      )}
      data-total={total}
    >
      <div
        role="img"
        aria-label={summary}
        /*
         * 8px tall and fully round-ended. `rounded-pill` clamps to half the height on an 8px
         * box, so this is a 4px radius drawn by the token that means "round this completely"
         * rather than by a rung that happens to be half of 8 — the bar keeps its ends if the
         * height ever changes. The track is `--surface-control`, the ground a control wears
         * in this design instead of a border.
         */
        className="flex h-2 w-full gap-[2px] overflow-hidden rounded-pill bg-surface-control"
      >
        {segments.map((segment) => (
          <div
            key={segment.state}
            data-state={segment.state}
            title={`${humaniseEnum(segment.state)} · ${formatInteger(segment.count)} · ${formatRate(
              segment.count / total,
              0,
            )}`}
            style={{
              flexGrow: segment.count,
              flexBasis: 0,
              backgroundColor: orderStateColorVar(segment.state),
            }}
          />
        ))}
      </div>

      {isLegend && total > 0 && (
        <ul className="flex flex-wrap items-center gap-2" aria-label={`${label} legend`}>
          {segments.map((segment) => (
            <li
              key={segment.state}
              /*
               * Each legend row is the same pill the palette recommends: the WORD in `--ink`
               * on the state's own `-tint`, with the §11.3 glyph in the state's hue. Colour
               * is never the only channel — the glyph and the word both say which state this
               * is, and both survive greyscale.
               */
              className="type-body-sm flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-ink"
              style={{ backgroundColor: orderStateTintVar(segment.state) }}
            >
              <span aria-hidden="true" style={{ color: orderStateColorVar(segment.state) }}>
                {statusGlyph(segment.state) ?? "•"}
              </span>
              <span>{humaniseEnum(segment.state)}</span>
              <span className="num font-semibold">{formatInteger(segment.count)}</span>
              <span className="num text-ink-muted">{formatRate(segment.count / total, 0)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
