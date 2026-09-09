/**
 * The ranking of customers by songs DELIVERED, drawn as hairline whiskers off a shared axis.
 *
 * ## What the figure claims
 *
 * Exactly one thing: how many orders reached delivery, per account, inside the window the
 * server resolved and echoed. The whisker's length is that count and nothing else, the axis
 * every whisker starts from is common to all of them, and the longest whisker is the lane —
 * so the rule under the marks is not a capacity or a target, it is the leader's own length.
 * Two rows can be compared by eye because they are measured off the same edge with the same
 * scale; that is the entire argument for drawing this rather than printing a table.
 *
 * ## What it deliberately does not claim
 *
 * **`ordersCreated` is not a denominator.** It is printed under the name as a second windowed
 * count, never as a percentage, a ratio or a funnel beside `deliveredSongs`. The two are counts
 * on two different columns over the same span: an order created in the window can be delivered
 * after it closes, and one delivered inside it can have been created before it opened. So
 * `ordersCreated` can legitimately read 0 beside a positive delivery count, and a "conversion
 * rate" computed from that pair would be a division of two things that were never a numerator
 * and a denominator of each other. The GAP is worth reading; the QUOTIENT is not a number.
 *
 * **Rank is not painted.** Every whisker is one ink. Position already carries the ordering, and
 * a hue ramp on top of it would be the same fact stated twice — with the second statement
 * indistinguishable, at a glance, from a series of categories.
 *
 * ## Identity here is absent, never withheld
 *
 * This is the one payload on the dashboard that carries real customer identity unmasked, and
 * the decision behind that is already taken: admins see the name, and the READ is what gets
 * audited. So there is no reveal button on these rows, no mask, no lock. A row with no handle
 * and no first name is an account that has none — or one whose profile was erased while its
 * orders survived — and it prints its Telegram id plainly, because a bullet string here would
 * claim there is something behind it that this console is refusing to show. There is not.
 *
 * Recipient names — the person a song is ABOUT — are not on this route and stay reveal-gated
 * where they do appear. Nothing here is a recipient.
 */

import type { JSX, ReactNode } from "react";
import { Link } from "react-router-dom";

import type { TopGeneratorsView, TopGeneratorView } from "@/api/dashboard";
import { userDetailPath } from "@/app/paths";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { formatCount } from "@/features/dashboard/adapt";
import { usePalette } from "@/features/dashboard/svg";

/**
 * The whisker lane, in CSS pixels and NOT scaled.
 *
 * Every other figure on this page draws into the shared 651x176 viewBox and scales to its
 * column; this one must not, because its neighbours are HTML rows of live text at 11px and a
 * scaled `<text>` beside unscaled type reads as a different typeface. Fixed geometry also
 * keeps the tick label at its natural size — house rule 3 forbids shrinking the type, and the
 * cheapest way to obey it is to never scale.
 */
const LANE_W = 268;
/**
 * The row, and therefore the svg. The two must agree or the axis segments stop tiling, and
 * the rows below are `h-10` — Tailwind's 2.5rem, which is this number. Changing one without
 * the other leaves a gap in the axis at every row boundary.
 */
const ROW_H = 40;
const AXIS_X = 1;
const WHISKER_X = AXIS_X + 5;
/** Room at the right for the value: five grouped digits at 11/700 is about 38px. */
const VALUE_W = 44;
const VALUE_GAP = 7;
const LANE_MAX = LANE_W - VALUE_W - VALUE_GAP - WHISKER_X;
const MID = ROW_H / 2;

export interface TopGeneratorsProps {
  /**
   * The `topGenerators` block off `GET /api/metrics/dashboard/audience-lists`, verbatim.
   *
   * `undefined` means it has NOT arrived — still in flight, failed, or refused because this
   * admin lacks `RECORDS_READ`. It is never turned into an empty list: "nobody delivered
   * anything" and "we were not allowed to look" are different answers and this card prints
   * different words for them. `data.items` empty is the first of those; this is the second.
   */
  readonly data: TopGeneratorsView | undefined;
  /**
   * True while the read is in flight. Drives the skeleton, and it is the ONLY thing that
   * distinguishes "loading" from "nothing delivered in this window" — with `data` undefined
   * and this false the card says the list was not read, never that it was empty.
   */
  readonly isLoading: boolean;
  /**
   * What to render in the list's place when the read failed or was refused — typically the
   * permission note for a 403 on `RECORDS_READ`, which is its own denial and must not blank
   * the aggregate cards around it. Ignored while `data` is present.
   */
  readonly notice?: ReactNode;
}

/**
 * The DAY a delivery landed, taken off the front of the stamp rather than through a formatter.
 *
 * The window this list was ranked over is the server's, decided in the server's zone; putting
 * its edge dates through the reader's timezone can move them across midnight and make two
 * operators disagree about which day a ranking covers. A string that is not a date at all is
 * printed as it arrived, so a contract change is visible instead of becoming "Invalid Date".
 */
function dayOf(at: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(at) ? at.slice(0, 10) : at;
}

/** `2026-09-01 → 2026-09-08`, or the words for a window the server left open at one end. */
function windowLabel(window: TopGeneratorsView["window"]): string {
  if (window === null) return "the whole record";
  return window.from === null
    ? `everything up to ${dayOf(window.to)}`
    : `${dayOf(window.from)} → ${dayOf(window.to)}`;
}

/** `@handle`, else the first name, else the bare id. Never a mask — see the file docstring. */
function identityOf(item: TopGeneratorView): string {
  if (item.telegramUsername !== null && item.telegramUsername !== "") {
    return `@${item.telegramUsername}`;
  }
  if (item.firstName !== null && item.firstName !== "") return item.firstName;
  return String(item.telegramUserId);
}

/** True when neither name arrived: the row is an account we can address but cannot name. */
function isUnnamed(item: TopGeneratorView): boolean {
  const handle = item.telegramUsername ?? "";
  const first = item.firstName ?? "";
  return handle === "" && first === "";
}

export function TopGenerators({ data, isLoading, notice }: TopGeneratorsProps): JSX.Element {
  // The ramp for the palette on screen. A figure drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  const items = data?.items ?? [];
  /*
   * The scale. Taken off the largest value rather than off `items[0]`, so a response that
   * arrives out of order draws short whiskers instead of one longer than its own lane. A
   * non-positive peak (nothing delivered, or a count the wire got wrong) leaves every whisker
   * at length zero rather than dividing by it — the printed number stays the measurement.
   */
  const peak = items.reduce((m, it) => Math.max(m, it.deliveredSongs), 0);
  const lengthOf = (v: number): number =>
    peak > 0 && Number.isFinite(v) && v > 0 ? (LANE_MAX * Math.min(v, peak)) / peak : 0;

  return (
    <article className="flex flex-col overflow-hidden rounded-card bg-card px-5 py-[18px]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="m-0 text-base font-semibold leading-[1.35] tracking-[-.32px] text-ink-900">
            Most songs generated
            {data !== undefined && (
              <span className="ml-[6px] whitespace-nowrap rounded-md bg-bg px-[6px] py-[3px] text-[9px] font-bold uppercase tracking-[.06em] text-ink-300">
                {`top ${String(data.limit)}`}
              </span>
            )}
          </h3>
          <p className="mb-0 mt-[2px] text-xs font-normal leading-[1.3] text-ink-400">
            {data === undefined
              ? "Ranked by songs delivered."
              : `Ranked by songs delivered · ${windowLabel(data.window)}`}
          </p>
        </div>
      </div>

      <div className="mt-3" aria-busy={isLoading && data === undefined}>
        {data === undefined ? (
          isLoading ? (
            <LoadingRows />
          ) : (
            (notice ?? (
              <EmptyState
                title="The ranking was not read"
                message="This list has its own permission and its own request."
              />
            ))
          )
        ) : items.length === 0 ? (
          <EmptyState
            title="Nothing delivered in this window"
            message={`No order reached delivery over ${windowLabel(data.window)}.`}
          />
        ) : (
          <ol className="m-0 list-none p-0">
            {items.map((item, i) => {
              const len = lengthOf(item.deliveredSongs);
              const value = formatCount(item.deliveredSongs);
              const unnamed = isUnnamed(item);

              return (
                <li key={item.telegramUserId}>
                  <Link
                    to={userDetailPath(item.telegramUserId)}
                    className="flex h-10 items-center gap-3 pr-1 no-underline hover:bg-row-hover focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-deep"
                  >
                    <span className="w-5 shrink-0 text-right text-[11px] font-semibold tabular-nums text-ink-300">
                      {i + 1}
                    </span>

                    <span className="flex min-w-0 flex-1 flex-col justify-center">
                      <span className="truncate text-[13px] font-semibold leading-[1.25] tracking-[-.2px] text-ink-900">
                        {identityOf(item)}
                      </span>
                      <span className="truncate text-[11px] font-normal leading-[1.25] text-ink-400">
                        {/* Two counts, printed as two counts. Never one over the other. */}
                        {`${formatCount(item.ordersCreated)} orders created`}
                        {item.lastDeliveredAt === null
                          ? ""
                          : ` · last ${dayOf(item.lastDeliveredAt)}`}
                        {` · ${item.uiLanguage}`}
                        {unnamed ? " · no name on the account" : ""}
                      </span>
                    </span>

                    <svg
                      className="block shrink-0"
                      width={LANE_W}
                      height={ROW_H}
                      viewBox={`0 0 ${String(LANE_W)} ${String(ROW_H)}`}
                      fontFamily="var(--font)"
                      role="img"
                      aria-label={`${value} song${item.deliveredSongs === 1 ? "" : "s"} delivered`}
                    >
                      {/* The shared left axis. Each row draws its own full-height segment and
                          the rows sit flush, so the segments tile into one continuous edge —
                          which is what lets two whiskers be compared by eye at all. */}
                      <line
                        x1={AXIS_X}
                        y1={0}
                        x2={AXIS_X}
                        y2={ROW_H}
                        stroke={PAL.D4}
                        strokeWidth={1}
                      />
                      {/* The lane is the LEADER'S length, not a capacity and not a target: the
                          top row fills it exactly, by construction. */}
                      <line
                        x1={WHISKER_X}
                        y1={MID}
                        x2={WHISKER_X + LANE_MAX}
                        y2={MID}
                        stroke={PAL.GRID}
                        strokeWidth={0.8}
                      />
                      {len > 0 && (
                        <>
                          {/* One ink for every row. No jitter either — a wobble is decoration
                              on a rung chart and a measurement error on a length. */}
                          <line
                            x1={WHISKER_X}
                            y1={MID}
                            x2={WHISKER_X + len}
                            y2={MID}
                            stroke={PAL.D0}
                            strokeWidth={1.4}
                            strokeLinecap="round"
                          />
                          <circle cx={WHISKER_X + len} cy={MID} r={1.9} fill={PAL.D0} />
                        </>
                      )}
                      <text
                        x={WHISKER_X + len + VALUE_GAP}
                        y={MID + 4}
                        fontSize={11}
                        fontWeight={700}
                        fill={PAL.D0}
                        textAnchor="start"
                      >
                        {value}
                      </text>
                    </svg>
                  </Link>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </article>
  );
}

/**
 * Three rows of shape, sized to the row they stand in, so nothing moves when the list lands.
 * A skeleton is never a number: a zero-length whisker drawn while the read is in flight would
 * be a ranking of nobody, which is exactly the answer this card must not give by accident.
 */
function LoadingRows(): JSX.Element {
  return (
    <ol className="m-0 list-none p-0">
      {[0, 1, 2].map((k) => (
        <li key={k} className="flex h-10 items-center gap-3">
          <Skeleton className="h-[9px] w-5" />
          <span className="flex min-w-0 flex-1 flex-col gap-[5px]">
            <Skeleton className="h-[11px] w-[46%]" />
            <Skeleton className="h-[9px] w-[62%]" />
          </span>
          {/* `w-[268px]` is LANE_W written where Tailwind can see it, so the loading row is
              exactly the width the drawn row will be and nothing shifts when it lands. */}
          <Skeleton className="h-[3px] w-[268px] shrink-0" />
        </li>
      ))}
    </ol>
  );
}
