/**
 * The last N plan purchases, each with a meter of what the plan has actually been used for.
 *
 * ## What the list claims
 *
 * That these purchases were RECORDED, newest first, and how much of each one has been sung.
 * The meter is one mark per song included, filled as songs are delivered against it, so a
 * plan's state is a thing you count rather than a percentage you trust.
 *
 * ## It takes no window, and the caption has to say so
 *
 * Everything else on this page is windowed and a reader will assume this is too. It is not:
 * `recentSubscribers` is a RECENCY list with a `limit` and no `window` field, and the page's
 * range picker must never be wired to it. So it is captioned "the last N" and never "this
 * week" — the same rows would be shown on a one-day window and a one-year one, and a period
 * label over them would be a false statement about which sales are on screen.
 *
 * ## The row that is easiest to misread: an ENDED plan with songs left
 *
 * `songsRemaining` means opposite things on the two sides of `isPlanEnded`. On a RUNNING plan
 * it is an obligation — songs this deployment still owes and expects to deliver. On an ENDED
 * plan it is BREAKAGE: money taken for songs that will never be sung. Same subtraction, two
 * facts, and a meter that drew them alike would report a customer who was short-changed as a
 * customer with headroom. So an ended plan is de-emphasised and its unsung marks are DASHED —
 * the same thing a dash means on the funnel, which is a loss — and the leftover is printed
 * with the word "breakage" beside it. `isPlanEnded` is the server's, decided against the one
 * `asOf` instant the block echoes, so two rows either side of a boundary were judged by one
 * clock; this component never compares `planEndsAt` to the browser's.
 *
 * ## Money here is recorded, not necessarily banked
 *
 * `isStubRail` travels with every amount and is never collapsed into it. The stub provider
 * stamps a purchase paid having contacted no bank, so a demo sale is identical to a real one
 * on every field but that flag — the flag is therefore printed as a word on the row, not as a
 * tint. Amounts are never summed here either: they are per-sale, each under its own currency,
 * and a total across two currencies is a figure in an invented unit.
 *
 * ## An erased customer is still a row
 *
 * `telegramUserId: null` is a `/forget` erasure: the receipt survives, the identity does not.
 * The row stays, unlinked and named as erased, because a receipt that vanished when somebody
 * exercised a right is a hole in the money record — and a list that quietly drops those rows
 * answers "what did we take money for?" wrongly, in the direction that flatters us.
 */

import type { JSX, ReactNode } from "react";
import { Link } from "react-router-dom";

import type { RecentSubscriberView, RecentSubscribersView } from "@/api/dashboard";
import { userDetailPath } from "@/app/paths";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { formatCount, money } from "@/features/dashboard/adapt";
import { usePalette, type Palette } from "@/features/dashboard/svg";

/**
 * The meter, in CSS pixels and NOT scaled — same reasoning as the ranking's lane: it sits
 * beside 11px HTML type, and a `<text>` scaled to a column beside unscaled type reads as a
 * different face. The counts are printed in HTML underneath rather than inside the drawing,
 * so they are selectable, and so the drawing carries no type at all.
 */
const METER_W = 132;
const METER_H = 18;
const METER_MID = METER_H / 2;
const TICK_H = 11;

/**
 * Above this many songs a per-song tick is finer than a hairline and stops being countable, so
 * the meter switches to two rules of proportional length. Starter is twelve, which counts.
 */
const TICK_MAX = 24;

export interface RecentSubscribersProps {
  /**
   * The `recentSubscribers` block off `GET /api/metrics/dashboard/audience-lists`, verbatim.
   *
   * `undefined` means it has NOT arrived — in flight, failed, or refused because this admin
   * lacks `RECORDS_READ`. Never substituted with an empty list: "nothing has sold" and "we
   * were not allowed to look" are different answers, and `isPlanRevenue` on the block is what
   * tells the two EMPTY answers apart once it has arrived.
   */
  readonly data: RecentSubscribersView | undefined;
  /**
   * True while the read is in flight. The only thing that separates "loading" from "nothing
   * sold": with `data` undefined and this false, the card says the list was not read.
   */
  readonly isLoading: boolean;
  /**
   * Rendered in the list's place when the read failed or was refused — typically the 403 note
   * for `RECORDS_READ`, which is this card's own denial and must not blank its neighbours.
   */
  readonly notice?: ReactNode;
}

/**
 * Date AND time, in the reader's own zone. A purchase is read against "it stopped working
 * after lunch" and against a deploy log, both of which the operator has in local time. An
 * unparseable stamp is printed verbatim so a contract change is visible rather than becoming
 * "Invalid Date".
 */
const STAMP = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function formatStamp(at: string): string {
  const ms = Date.parse(at);
  return Number.isNaN(ms) ? at : STAMP.format(ms);
}

/**
 * `planEndsAt` is a BUSINESS clock the server decided, not an instant anybody acts on, so it
 * is printed as the day it arrived as. Re-rendering it in the reader's zone can walk it across
 * midnight and make two operators disagree about the day a plan ran out.
 */
function dayOf(at: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(at) ? at.slice(0, 10) : at;
}

/** `@handle`, else the first name, else the bare id, else the erasure. Never a mask. */
function identityOf(item: RecentSubscriberView): string {
  if (item.telegramUsername !== null && item.telegramUsername !== "") {
    return `@${item.telegramUsername}`;
  }
  if (item.firstName !== null && item.firstName !== "") return item.firstName;
  return item.telegramUserId === null ? "erased customer" : String(item.telegramUserId);
}

export function RecentSubscribers({
  data,
  isLoading,
  notice,
}: RecentSubscribersProps): JSX.Element {
  const items = data?.items ?? [];

  return (
    <article className="flex flex-col overflow-hidden rounded-card bg-card px-5 py-[18px]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="m-0 text-base font-semibold leading-[1.35] tracking-[-.32px] text-ink-900">
            Recent subscribers
            {data !== undefined && (
              <span className="ml-[6px] whitespace-nowrap rounded-md bg-bg px-[6px] py-[3px] text-[9px] font-bold uppercase tracking-[.06em] text-ink-300">
                {`the last ${String(data.limit)}`}
              </span>
            )}
          </h3>
          {/* "The last N", never a period: this block carries no window and the page's picker
              is not wired to it. */}
          <p className="mb-0 mt-[2px] text-xs font-normal leading-[1.3] text-ink-400">
            {data === undefined
              ? "The most recent plan purchases. Not a window — a recency list."
              : `The most recent plan purchases — not a window · plans judged ended as of ${formatStamp(data.asOf)}`}
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
                title="The purchase list was not read"
                message="This list has its own permission and its own request."
              />
            ))
          )
        ) : items.length === 0 ? (
          <EmptyState
            title={data.isPlanRevenue ? "No purchase in the recent list" : "No plan has ever sold"}
            message={
              data.isPlanRevenue
                ? "Plans have sold on this deployment before, but the recent list came back empty."
                : "No plan purchase has ever been recorded here."
            }
          />
        ) : (
          <ul className="m-0 list-none p-0">
            {items.map((item, i) => (
              <SubscriberRow key={`${String(item.telegramUserId ?? "erased")}-${item.purchasedAt}-${String(i)}`} item={item} />
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function SubscriberRow({ item }: { readonly item: RecentSubscriberView }): JSX.Element {
  const erased = item.telegramUserId === null;
  const ended = item.isPlanEnded;
  /* `money` is `adapt.ts`'s, deliberately: it owns the ISO minor-exponent table, and a
     second copy of that table here would eventually disagree with it and quote a receipt at
     a hundredth or a hundred times what the customer paid. UZS reads in soʻm; anything
     else reads in major units under its own ISO code. */
  const amount = money(item.amountMinor, item.currency);

  const identity = (
    <span className="flex min-w-0 flex-col justify-center">
      <span
        className={
          erased
            ? "truncate text-[13px] font-semibold leading-[1.25] tracking-[-.2px] text-ink-300"
            : ended
              ? "truncate text-[13px] font-semibold leading-[1.25] tracking-[-.2px] text-ink-400"
              : "truncate text-[13px] font-semibold leading-[1.25] tracking-[-.2px] text-ink-900"
        }
      >
        {identityOf(item)}
      </span>
      <span className="truncate text-[11px] font-normal leading-[1.25] text-ink-400">
        {`${item.plan} · bought ${formatStamp(item.purchasedAt)} · ${
          ended ? "ended" : "ends"
        } ${dayOf(item.planEndsAt)}`}
        {erased ? " · identity erased by /forget, the receipt remains" : ""}
      </span>
    </span>
  );

  return (
    <li className="border-t border-stroke first:border-t-0">
      <div className="flex min-h-[52px] items-center gap-3 py-2 pr-1">
        <span className="min-w-0 flex-1">
          {/* An erased purchase has no account left to open, so it is not a link. Everything
              else opens the customer's record — through the path builder, never a template. */}
          {item.telegramUserId === null ? (
            identity
          ) : (
            <Link
              to={userDetailPath(item.telegramUserId)}
              className="flex min-w-0 no-underline hover:bg-row-hover focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-deep"
            >
              {identity}
            </Link>
          )}
        </span>

        <span className="flex w-[124px] shrink-0 flex-col items-end gap-[3px]">
          <span className="flex items-baseline gap-[4px] whitespace-nowrap">
            <span
              className={
                ended
                  ? "text-[13px] font-bold tracking-[-.2px] text-ink-400"
                  : "text-[13px] font-bold tracking-[-.2px] text-ink-900"
              }
            >
              {amount.value}
            </span>
            <span className="text-[10px] font-medium text-ink-300">{amount.unit}</span>
          </span>
          {/* The rail as a WORD. A stub sale is a sale on the record and no money in a bank,
              and the two are identical on every other field of this row. */}
          {item.isStubRail ? (
            <Badge
              tone="warning"
              className="px-[6px] py-[2px] text-[10px] leading-[1.2]"
              title="Recorded by the stub checkout rail — a sale on the record, not money banked."
            >
              stub rail
            </Badge>
          ) : (
            <span className="truncate text-[10px] font-normal leading-[1.2] text-ink-300">
              {item.provider}
            </span>
          )}
        </span>

        <span className="flex w-[132px] shrink-0 flex-col items-start gap-[3px]">
          <SongMeter item={item} />
          <MeterWords item={item} />
        </span>
      </div>
    </li>
  );
}

/**
 * `songsUsed` against `songsIncluded`, one mark per song while they are countable.
 *
 * Nothing here is a filled shape: the track is a rule, a sung song is a solid tick and an
 * unsung one is either a faint tick (still owed) or a DASHED tick (an ended plan — a loss, the
 * way a dash reads on the funnel). Above `TICK_MAX` songs the ticks stop being countable and
 * the same statement is made as two rules of proportional length, which is a weaker drawing
 * but an honest one.
 */
function SongMeter({ item }: { readonly item: RecentSubscriberView }): JSX.Element {
  // The ramp for the palette on screen. A figure drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  const included = item.songsIncluded;
  const used = Math.max(0, item.songsUsed);
  const ended = item.isPlanEnded;

  /*
   * A plan that included no songs has no ratio: `used / 0` is not a full meter, an empty one
   * or infinity, it is a question with no denominator. Draw the empty statement, not a bar.
   */
  if (!Number.isFinite(included) || included <= 0) {
    return (
      <svg
        className="block"
        width={METER_W}
        height={METER_H}
        viewBox={`0 0 ${String(METER_W)} ${String(METER_H)}`}
        role="img"
        aria-label="This plan included no songs, so there is no ratio to draw"
      >
        <line
          x1={1}
          y1={METER_MID}
          x2={METER_W - 1}
          y2={METER_MID}
          stroke={PAL.GRID}
          strokeWidth={0.8}
          strokeDasharray="2 3"
        />
      </svg>
    );
  }

  const drawnUsed = Math.min(used, included);
  // More sung than sold: the plan was over-drawn, which is a real state and not a rounding
  // error. The lane is full and a dashed tail says the overrun continued past it; the words
  // under the meter print the two raw counts, which stay the measurement.
  const overdrawn = used > included;
  const label = `${formatCount(used)} of ${formatCount(included)} songs sung${
    ended ? ", plan ended" : ""
  }${overdrawn ? ", more sung than the plan included" : ""}`;

  return (
    <svg
      className="block"
      width={METER_W}
      height={METER_H}
      viewBox={`0 0 ${String(METER_W)} ${String(METER_H)}`}
      role="img"
      aria-label={label}
    >
      <line
        x1={1}
        y1={METER_MID}
        x2={METER_W - 1}
        y2={METER_MID}
        stroke={PAL.GRID}
        strokeWidth={0.8}
      />

      {included <= TICK_MAX ? (
        Array.from({ length: included }, (_, k) => {
          const pitch = (METER_W - 2) / included;
          const x = 1 + pitch * (k + 0.5);
          const sung = k < drawnUsed;
          return (
            <line
              key={k}
              x1={x}
              y1={METER_MID - TICK_H / 2}
              x2={x}
              y2={METER_MID + TICK_H / 2}
              /* Unsung-and-owed is D4, not D5: a D5 hairline is decoration weight in both
                 palettes, and this mark is a measurement — a plan read as three songs long
                 instead of three-of-twelve is exactly the misreading the meter exists to
                 stop. Unsung-and-ENDED is a step darker AND dashed, because a dash is what a
                 loss looks like everywhere else on this page. */
              stroke={sung ? PAL.D0 : ended ? PAL.D3 : PAL.D4}
              strokeWidth={sung ? 1.6 : 1}
              strokeDasharray={!sung && ended ? "2 2" : undefined}
            />
          );
        })
      ) : (
        <ProportionalMeter used={drawnUsed} included={included} ended={ended} palette={PAL} />
      )}

      {/* The overrun, drawn INSIDE the box as a dashed continuation above the lane rather
          than as a longer meter: the lane is `included` songs wide, and a mark past its end
          would be a song the plan never sold. The words below print both raw counts. */}
      {overdrawn && (
        <line
          x1={METER_W - 13}
          y1={1.6}
          x2={METER_W - 1}
          y2={1.6}
          stroke={PAL.D3}
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}
    </svg>
  );
}

/** The fallback drawing for a plan with more songs than a reader can count: two rules. */
function ProportionalMeter({
  used,
  included,
  ended,
  palette,
}: {
  readonly used: number;
  readonly included: number;
  readonly ended: boolean;
  readonly palette: Palette;
}): JSX.Element {
  const lane = METER_W - 2;
  const cut = 1 + (lane * used) / included;
  return (
    <>
      {used > 0 && (
        <line
          x1={1}
          y1={METER_MID}
          x2={cut}
          y2={METER_MID}
          stroke={palette.D0}
          strokeWidth={1.8}
          strokeLinecap="butt"
        />
      )}
      {used < included && (
        <line
          x1={cut}
          y1={METER_MID}
          x2={METER_W - 1}
          y2={METER_MID}
          stroke={ended ? palette.D3 : palette.D4}
          strokeWidth={1}
          strokeDasharray={ended ? "2 2" : undefined}
        />
      )}
      <line
        x1={cut}
        y1={METER_MID - TICK_H / 2}
        x2={cut}
        y2={METER_MID + TICK_H / 2}
        stroke={palette.D2}
        strokeWidth={0.8}
      />
    </>
  );
}

/**
 * The meter's caption, and the only place the two meanings of `songsRemaining` are named.
 *
 * Colour is never the channel: "breakage" is a word first, and the amber it is printed in only
 * repeats it. `--th-warn` rather than a Tailwind utility because there are no `text-th-*`
 * classes — `tokens.css` publishes the variable and this is how HTML reaches it.
 */
function MeterWords({ item }: { readonly item: RecentSubscriberView }): JSX.Element {
  const included = item.songsIncluded;
  const used = item.songsUsed;
  const left = item.songsRemaining;

  if (!Number.isFinite(included) || included <= 0) {
    return (
      <span className="text-[10px] font-semibold leading-[1.2] text-ink-300">
        no songs in this plan
      </span>
    );
  }

  const counted = `${formatCount(used)} of ${formatCount(included)} sung`;

  /* More sung than sold. A real state, and neither "fully used" nor breakage: the plan was
     over-drawn, and the two raw counts stay on screen so the size of the overrun is readable. */
  if (left < 0) {
    return (
      <span className="text-[10px] font-semibold leading-[1.2] text-ink-400">
        {`${counted} · ${formatCount(-left)} more than the plan included${
          item.isPlanEnded ? ", plan ended" : ""
        }`}
      </span>
    );
  }

  if (item.isPlanEnded && left > 0) {
    return (
      <span className="text-[10px] font-semibold leading-[1.2] text-ink-400">
        {`${counted} · `}
        <span style={{ color: "var(--th-warn)" }}>{`${formatCount(left)} unsung — breakage`}</span>
      </span>
    );
  }

  if (item.isPlanEnded) {
    return (
      <span className="text-[10px] font-semibold leading-[1.2] text-ink-400">
        {`${counted} · plan ended, nothing left over`}
      </span>
    );
  }

  return (
    <span className="text-[10px] font-semibold leading-[1.2] text-ink-400">
      {left > 0 ? `${counted} · ${formatCount(left)} still owed` : `${counted} · plan fully used`}
    </span>
  );
}

/**
 * Rows of shape, sized to the row they stand in. A meter drawn at zero while the read is in
 * flight would be a plan nobody has used, which is a measurement — and the wrong one.
 */
function LoadingRows(): JSX.Element {
  return (
    <ul className="m-0 list-none p-0">
      {[0, 1, 2].map((k) => (
        <li key={k} className="border-t border-stroke first:border-t-0">
          <div className="flex min-h-[52px] items-center gap-3 py-2">
            <span className="flex min-w-0 flex-1 flex-col gap-[5px]">
              <Skeleton className="h-[11px] w-[42%]" />
              <Skeleton className="h-[9px] w-[68%]" />
            </span>
            <span className="flex w-[124px] shrink-0 flex-col items-end gap-[5px]">
              <Skeleton className="h-[11px] w-[64px]" />
              <Skeleton className="h-[9px] w-[42px]" />
            </span>
            {/* `w-[132px]` is METER_W where Tailwind can see it, so nothing shifts on arrival. */}
            <span className="flex w-[132px] shrink-0 flex-col gap-[5px]">
              <Skeleton className="h-[11px] w-[132px]" />
              <Skeleton className="h-[9px] w-[86px]" />
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
