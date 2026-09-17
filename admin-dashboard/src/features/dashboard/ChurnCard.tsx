import type { JSX } from "react";

import type { ChurnView, SubscriptionChurnView } from "@/api/dashboard";
import { Skeleton } from "@/components/Skeleton";
import { formatCount, formatDelta } from "@/features/dashboard/adapt";
import {
  dirOf,
  hatchLines,
  niceStep,
  rnd,
  segmentedShare,
  usePalette,
  type Palette,
  type ShareSegment,
} from "@/features/dashboard/svg";
import { cn } from "@/lib/cn";

/**
 * TWO CHURNS, ONE CARD — and the whole job of this component is to stop them being read as
 * one number.
 *
 * The owner asked for both in a single card, which is also the single place a reader is most
 * likely to add them, average them, or take the larger one as "the" churn. They are not two
 * views of one quantity:
 *
 *  * **Bot blocks** (`churn`) is a count of PASSAGES through the membership log — people who
 *    blocked the bot inside the window, and, counted separately, people who unblocked it. It
 *    has no denominator at all. Somebody who left and came back inside one window is in BOTH
 *    counts, on purpose, and the two are never netted: two passages happened. Its gauge
 *    counterpart, `botBlockedAccounts`, is a third question again — who is blocking RIGHT
 *    NOW — and is a stock, not a flow.
 *  * **Subscription churn** (`subscriptionChurn`) is a RATE over the plans that ENDED in the
 *    window: `lapsed ÷ endedPlans`, in plans, about a population whose renewal decision has
 *    actually been made. A customer can block the bot with a plan still running, and can let
 *    a plan lapse while using the bot every day. Neither number bounds or corrects the other.
 *
 * So the two halves keep their own units, their own denominators, their own drawings and
 * their own empty states, and there is no arithmetic anywhere that touches both. They are
 * never plotted on one axis: one is people, the other is a percentage of plans, and a shared
 * axis is a claim that they are commensurable.
 *
 * What the card deliberately does NOT claim:
 *  * that either figure is a churn RATE over the customer base — nothing here divides by the
 *    number of accounts, because the wire never measured that;
 *  * that the subscription rate is exact. `anonymisedEnded` are `/forget`-erased endings that
 *    nobody can follow to a renewal, so the printed rate is a FLOOR and says so in words the
 *    moment that count is non-zero;
 *  * that a small denominator is a stable percentage. `endedPlans` is printed beside the rate
 *    everywhere, and under twenty endings the card prints how far the percentage would move
 *    if ONE of those endings had gone the other way — this product has been selling a
 *    30-day plan for weeks, so a single-digit denominator is the expected case here, not an
 *    edge case.
 */

/* -------------------------------------------------------------------------- */
/* Props                                                                       */
/* -------------------------------------------------------------------------- */

export interface ChurnCardProps {
  /**
   * `AudienceResponse.churn`. Blocks and unblocks IN the window, each a `TrendView`.
   *
   * `null` means the membership log has NEVER recorded a transition here — "never watched",
   * not "nobody left". `{blocked: 0, unblocked: 0}` is the other thing entirely: a real
   * reading of no passages, which this card prints as a measurement.
   */
  readonly churn: ChurnView | null;
  /**
   * `AudienceResponse.isChurnInstrumented`. False is the same statement as a null `churn` and
   * is honoured the same way: the flow half goes to its "never recorded" rendering. It is
   * read separately because a deployment can be uninstrumented and still return a
   * zero-filled block — trusting the counts alone would print "nobody blocked us" there.
   */
  readonly isChurnInstrumented: boolean;
  /**
   * `AudienceResponse.botBlockedAccounts`. The GAUGE: accounts blocking the bot right now.
   * Never null — it is a flag on the accounts themselves, so it answers even where the
   * transition log does not, which is why it is still printed in the untracked arm. It is not
   * a window figure and must never be differenced against `churn.blocked`.
   */
  readonly botBlockedAccounts: number;
  /**
   * `AudienceResponse.subscriptionChurn`.
   *
   * `null` means no plan has EVER been sold on this deployment, so nothing has ever ended —
   * four zeroes would read as "nobody renews" on a shop that has never taken money. Distinct
   * from `endedPlans === 0`, which is "plans exist, none ended in this window"; the card
   * prints different words for each. A null here must not blank the bot-block half, and vice
   * versa: they come from different tables and fail independently.
   */
  readonly subscriptionChurn: SubscriptionChurnView | null;
  /**
   * True while the audience section has never answered. Drives the skeletons only — an
   * absence that has been MEASURED is a pill with words in it, and this is not that.
   */
  readonly isLoading: boolean;
}

/* -------------------------------------------------------------------------- */
/* Card chrome                                                                 */
/* -------------------------------------------------------------------------- */

/** `StatCard`'s delta inks, so a chip means the same thing on every card of the page. */
const DELTA_CLASS: Record<"" | "up" | "down", string> = {
  "": "",
  up: "text-accent-deep",
  down: "text-ink-400",
};

/** The value slot of a half with no value. */
const NO_VALUE = "—";

/**
 * A percentage from a `RatioView.value` fraction. Same shape as `formatDelta`'s magnitude —
 * one decimal under ten, whole numbers above — so 4.2% and 42% read as the same kind of
 * figure on the same page. Unsigned: a rate is not a change.
 */
function formatPct(fraction: number): string {
  const pct = fraction * 100;
  return `${pct < 10 ? String(Math.round(pct * 10) / 10) : String(Math.round(pct))}%`;
}

/** The eyebrow over each half: the quantity's name and, always, its UNIT. */
function Eyebrow({ label, unit }: { readonly label: string; readonly unit: string }): JSX.Element {
  return (
    <div className="flex items-baseline gap-[6px]">
      <span className="text-[11px] font-semibold tracking-[-.1px] text-ink-400">{label}</span>
      <span className="text-[9px] font-bold uppercase tracking-[.06em] text-ink-300">{unit}</span>
    </div>
  );
}

/** A half with nothing measured behind it: the dash, and nothing else. */
function Absent(): JSX.Element {
  return (
    <div className="mt-1 flex h-8 items-baseline text-[28px] font-bold leading-none tracking-[-1.6px] text-ink-300">
      {NO_VALUE}
    </div>
  );
}

/** Sized to the rows it stands in, so nothing moves a pixel when the numbers land. */
function HalfSkeleton(): JSX.Element {
  return (
    <>
      <div className="mt-1 flex h-8 items-center">
        <Skeleton className="h-[22px] w-[104px]" />
      </div>
      <div className="mt-[6px] flex h-[13px] items-center">
        <Skeleton className="h-[9px] w-[76%]" />
      </div>
      <div className="mt-[14px]">
        <Skeleton className="h-[52px] w-full" />
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* The card                                                                    */
/* -------------------------------------------------------------------------- */

export function ChurnCard({
  churn,
  isChurnInstrumented,
  botBlockedAccounts,
  subscriptionChurn,
  isLoading,
}: ChurnCardProps): JSX.Element {
  /* The two halves are resolved independently and rendered independently. There is no shared
     branch, no shared total and no "if either is missing" path: a 403 or a null on one side
     of this card must leave the other side standing. */
  const flow = churn === null || !isChurnInstrumented ? null : churn;

  return (
    <article aria-busy={isLoading} className="overflow-hidden rounded-card bg-card p-4">
      <div className="flex items-baseline justify-between gap-3">
        {/* An h3 for the same reason the chart titles are h3s: the page's group labels are
            the h2s, so this sits under one rather than beside it in the outline. */}
        <h3 className="m-0 text-base font-semibold leading-[1.35] tracking-[-.32px] text-ink-900">
          Churn
        </h3>
        <span className="text-[11px] font-normal leading-[1.3] text-ink-300">
          two measurements · never one number
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-5">
        <section className="min-w-0">
          <Eyebrow label="Bot blocks" unit="people · passages" />
          {isLoading && churn === null ? (
            <HalfSkeleton />
          ) : flow === null ? (
            <>
              <Absent />
              {/* The gauge is a flag on the accounts themselves, not a row in the transition
                  log, so it answers even where the flow does not. Printed here rather than
                  suppressed, and worded as its own question so it cannot be read as the
                  window count that is missing above it. */}
              <p className="mb-0 mt-[6px] text-[11px] font-normal leading-[1.35] text-ink-300">
                {formatCount(botBlockedAccounts)} blocking right now
              </p>
            </>
          ) : (
            <BotBlockHalf churn={flow} botBlockedAccounts={botBlockedAccounts} />
          )}
        </section>

        {/* The separator is the point of the card: two halves, two denominators. A rule on
            small screens too, where the halves stack and would otherwise read as one column
            of related numbers. */}
        <section className="min-w-0 border-t border-stroke pt-4 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
          <Eyebrow label="Subscription churn" unit="plans · rate" />
          {isLoading && subscriptionChurn === null ? (
            <HalfSkeleton />
          ) : subscriptionChurn === null ? (
            <Absent />
          ) : (
            <PlanChurnHalf churn={subscriptionChurn} />
          )}
        </section>
      </div>
    </article>
  );
}

/* -------------------------------------------------------------------------- */
/* Half one — bot blocks, in people                                            */
/* -------------------------------------------------------------------------- */

function BotBlockHalf({
  churn,
  botBlockedAccounts,
}: {
  readonly churn: ChurnView;
  readonly botBlockedAccounts: number;
}): JSX.Element {
  const blocked = churn.blocked.current;
  const unblocked = churn.unblocked.current;
  const blockedDelta = formatDelta(churn.blocked.change);
  /* `invert` is per NUMBER, not per card. A rise in blocks is a loss, so that chip is
     inverted; a rise in unblocks is people COMING BACK, so that one is not. Inverting both
     because they live in one half would paint every return red. */
  const unblockedDelta = formatDelta(churn.unblocked.change);

  return (
    <>
      <div className="mt-1 flex items-baseline gap-[6px] whitespace-nowrap text-[28px] font-bold leading-none tracking-[-1.6px] text-ink-800">
        <span>{formatCount(blocked)}</span>
        <u className="text-[13px] font-medium tracking-[-.2px] text-ink-400 no-underline">
          blocked
        </u>
        <em
          className={cn(
            "text-[11px] font-semibold not-italic tracking-[-.1px]",
            DELTA_CLASS[dirOf(blockedDelta, true)],
          )}
        >
          {blockedDelta}
        </em>
      </div>

      <p className="mb-0 mt-[6px] text-[11px] font-normal leading-[1.35] text-ink-300">
        {formatCount(unblocked)} unblocked
        {unblockedDelta === "" ? "" : " "}
        <em className={cn("not-italic font-semibold", DELTA_CLASS[dirOf(unblockedDelta)])}>
          {unblockedDelta}
        </em>{" "}
        · {formatCount(botBlockedAccounts)} blocking right now
      </p>

      <div className="mt-[10px] aspect-[300/78] w-full [&>svg]:h-full [&>svg]:w-full">
        <BlockLanes blocked={blocked} unblocked={unblocked} />
      </div>
    </>
  );
}

/* The tally lanes. 20 ticks of 8.9 units, so the drawing is ~300 wide at ~1:1 in a half card
   — the type here is 8 and 9, and a figure sized off the 651-wide chart box would render it
   at four screen pixels in this column. */
const A_X0 = 78;
const A_LANE = 178;
const A_TICKS = 20;
const A_PITCH = A_LANE / A_TICKS;
const A_W = 300;
const A_H = 78;

interface LaneRow {
  readonly word: string;
  readonly value: number;
  readonly y: number;
  readonly ink: string;
  readonly weight: number;
  /** The returning row is capped with a hollow dot: mark shape, not hue, tells them apart. */
  readonly hollow: boolean;
  readonly title: string;
}

/**
 * Two tally lanes in one unit — people — sharing a tick size so the rows are comparable to
 * each other and to nothing else on this card. They are two counts of DIFFERENT events, so
 * they are drawn as two rows rather than one bar split in two: a split bar would make them
 * parts of a total, and there is no total here to be part of.
 */
function BlockLanes({
  blocked,
  unblocked,
}: {
  readonly blocked: number;
  readonly unblocked: number;
}): JSX.Element {
  const PAL = usePalette();
  const peak = Math.max(blocked, unblocked);

  /* Zero blocks and zero unblocks is a READING — the log was watching and nobody moved — but
     two bare lanes with no ticks on them read as a lane we forgot to draw. Say it in words.
     (Written before the geometry below, which is the house rule that keeps an empty axis from
     being published as a measurement of nothing.) */
  if (peak <= 0) {
    return (
      <Note note="no block or unblock recorded in this window" width={A_W} height={A_H} />
    );
  }

  /* One tick per person until that overflows the lane, then the smallest 1–2–5 step that
     fits. The unit is printed under the lanes or the ticks are a count of nothing. */
  const unit = niceStep(peak, A_TICKS);
  const rows: readonly LaneRow[] = [
    {
      word: "BLOCKED",
      value: blocked,
      y: 26,
      ink: PAL.D0,
      weight: 1.3,
      hollow: false,
      title: `${formatCount(blocked)} blocked the bot in this window`,
    },
    {
      word: "UNBLOCKED",
      value: unblocked,
      y: 56,
      ink: PAL.D2,
      weight: 1,
      hollow: true,
      title: `${formatCount(unblocked)} unblocked the bot in this window — returns, only ever by an account that had blocked`,
    },
  ];

  return (
    <svg
      viewBox={`0 0 ${String(A_W)} ${String(A_H)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`Bot-block passages in this window: ${formatCount(blocked)} blocked, ${formatCount(unblocked)} unblocked, counted separately and never netted`}
    >
      {rows.map((row) => {
        /* A row with a real count always draws at least one tick: it is a passage that
           happened, and an empty lane beside a printed number reads as a lane that failed to
           draw. A row of a true zero draws none, which is what zero looks like. */
        const wanted = row.value > 0 ? Math.max(1, Math.round(row.value / unit)) : 0;
        const ticks = Math.min(A_TICKS, wanted);
        const over = wanted > A_TICKS;

        return (
          <g key={row.word}>
            <title>{row.title}</title>
            <text
              x={A_X0 - 10}
              y={row.y + 3}
              fontSize={8}
              fontWeight={700}
              fill={PAL.MUT}
              textAnchor="end"
              letterSpacing=".08em"
            >
              {row.word}
            </text>
            <line
              x1={A_X0}
              y1={row.y}
              x2={A_X0 + A_LANE}
              y2={row.y}
              stroke={PAL.GRID}
              strokeWidth={0.8}
            />
            {Array.from({ length: ticks }, (_, k) => {
              const x = A_X0 + k * A_PITCH + A_PITCH / 2;
              const h = 11 + rnd(k + 1, row.y) * 5;
              return (
                <g key={k}>
                  <line
                    x1={x}
                    y1={row.y}
                    x2={x}
                    y2={row.y - h}
                    stroke={row.ink}
                    strokeWidth={row.weight}
                    opacity={0.6 + rnd(k + 3, row.y + 2) * 0.4}
                  />
                  {row.hollow && (
                    <circle
                      cx={x}
                      cy={row.y - h - 1.6}
                      r={1.4}
                      fill={PAL.PAPER}
                      stroke={row.ink}
                      strokeWidth={0.9}
                    />
                  )}
                </g>
              );
            })}
            {/* Clipped rather than shrunk, and it says so: two lanes silently cut at the same
                edge would read as a tie. */}
            {over && (
              <line
                x1={A_X0 + A_LANE + 2}
                y1={row.y}
                x2={A_X0 + A_LANE + 12}
                y2={row.y}
                stroke={PAL.D3}
                strokeWidth={0.8}
                strokeDasharray="2 2"
              />
            )}
            <text
              x={A_X0 + A_LANE + (over ? 16 : 8)}
              y={row.y + 4}
              fontSize={11}
              fontWeight={700}
              fill={row.ink}
            >
              {formatCount(row.value)}
            </text>
          </g>
        );
      })}

      <text x={2} y={A_H - 4} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".06em">
        {unit === 1 ? "ONE TICK = ONE PASSAGE" : `ONE TICK = ${String(unit)} PASSAGES`}
      </text>
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Half two — subscription churn, in plans                                     */
/* -------------------------------------------------------------------------- */

/**
 * Under this many endings the card prints the point swing ONE ending decided the other way is
 * worth. At twelve endings that is 8.3 points; at three it is a third of the scale, which is
 * the fact the percentage on its own hides.
 */
const FRAGILE_DENOMINATOR = 20;

function PlanChurnHalf({ churn }: { readonly churn: SubscriptionChurnView }): JSX.Element {
  const { endedPlans, renewed, lapsed, anonymisedEnded, rate } = churn;

  /* `rate.value` is null if and only if the denominator is zero, and this is the case that
     must never print a percentage: "0% churn" on a window where nothing ended is the most
     flattering lie the panel could tell, and it would be told exactly on the deployments too
     young to have measured anything. Written before the geometry, again on purpose. */
  if (rate.value === null || endedPlans <= 0) {
    return (
      <Absent />
    );
  }

  const floored = anonymisedEnded > 0;
  /* The blind spot has a WIDTH, so the honest statement is an interval: everything erased
     could have renewed, or none of it could. `lapsed / ended` is the floor and
     `(lapsed + erased) / ended` is the ceiling. */
  const ceiling = (lapsed + anonymisedEnded) / endedPlans;
  /* One ending moved from lapsed to renewed (or the reverse) is worth exactly this many
     percentage points — the numerator moves by one over the same denominator. */
  const swing = 100 / endedPlans;
  /* The contract says the three parts sum to `endedPlans` on every window. If they ever do
     not, the drawing is of the parts and the denominator is the server's — and the card says
     the two disagree rather than quietly picking one. */
  const parts = renewed + lapsed + anonymisedEnded;

  return (
    <>
      <div className="mt-1 flex items-baseline gap-[6px] whitespace-nowrap text-[28px] font-bold leading-none tracking-[-1.6px] text-ink-800">
        {floored && (
          <span
            className="text-[15px] font-semibold tracking-[-.2px] text-ink-400"
            title="at least — erased endings cannot be followed to a renewal"
          >
            ≥
          </span>
        )}
        <span>{formatPct(rate.value)}</span>
        <u className="text-[13px] font-medium tracking-[-.2px] text-ink-400 no-underline">
          lapsed
        </u>
      </div>

      {/* The denominator rides beside the rate everywhere it is printed. At these volumes the
          COUNT is the measurement and the percentage is the decoration. */}
      <p className="mb-0 mt-[6px] text-[11px] font-normal leading-[1.35] text-ink-300">
        {formatCount(lapsed)} of {formatCount(endedPlans)}{" "}
        {endedPlans === 1 ? "plan that ended" : "plans that ended"} in this window
      </p>

      <div className="mt-[10px] aspect-[300/62] w-full [&>svg]:h-full [&>svg]:w-full">
        <EndedPlansLane renewed={renewed} lapsed={lapsed} erased={anonymisedEnded} />
      </div>

      {floored && (
        <p className="mb-0 mt-[6px] text-[11px] font-normal leading-[1.35] text-ink-300">
          Between {formatPct(rate.value)} and {formatPct(ceiling)}: {formatCount(anonymisedEnded)}{" "}
          {anonymisedEnded === 1 ? "ending was" : "endings were"} erased by /forget.
        </p>
      )}

      {endedPlans <= FRAGILE_DENOMINATOR && (
        <p className="mb-0 mt-[6px] text-[11px] font-normal leading-[1.35] text-ink-300">
          One ending decided the other way moves this{" "}
          {String(Math.round(swing * 10) / 10)} points.
        </p>
      )}

      {parts !== endedPlans && (
        <p className="mb-0 mt-[6px] text-[11px] font-semibold leading-[1.35] text-ink-400">
          The parts sum to {formatCount(parts)}, not the {formatCount(endedPlans)} the server
          says ended.
        </p>
      )}
    </>
  );
}

/* The lane. Same reasoning as the tally box above: ~300 units wide so its 9pt legend is
   legible in a half card rather than scaled down from a full-width chart box. */
const B_W = 300;
const B_H = 62;
const B_X = 6;
const B_LANE = 288;
const B_Y = 20;
const B_THICK = 9;
const B_LEGEND_X: readonly number[] = [6, 104, 202];
const B_LEGEND_Y = 48;

/** Stand-in for a segment the geometry did not return. Never drawn: length 0, value 0. */
const NO_SEGMENT: ShareSegment = {
  index: -1,
  value: 0,
  share: 0,
  offset: 0,
  length: 0,
  tooSmall: false,
};

interface LanePart {
  readonly word: string;
  readonly count: number;
  readonly seg: ShareSegment;
  readonly ink: string;
  /** The erased run is HATCHED, because it is not a third outcome — it is an unmeasured one. */
  readonly unmeasured: boolean;
  readonly title: string;
}

/**
 * How the ended plans split, as one hairline lane: lapsed, then the erased blind spot, then
 * renewed. That ORDER is the argument — the dark run is the numerator of the printed rate,
 * the hatch immediately after it is how far that rate could still extend, and everything past
 * the hatch came back. Reading the rate's floor and its ceiling is reading the lane
 * left-to-right.
 *
 * The erased run carries no ink of its own: it is the same hatch this dashboard uses for
 * every unmeasured quantity, because an erased ending is not a renewal and not a lapse — it
 * is an outcome nobody can ever look up. Painting it as either would invent the answer.
 *
 * Told apart by ink darkness and by texture, never by hue, and every run prints its word and
 * its count in the legend below, so the drawing is not carrying the meaning alone.
 */
function EndedPlansLane({
  renewed,
  lapsed,
  erased,
}: {
  readonly renewed: number;
  readonly lapsed: number;
  readonly erased: number;
}): JSX.Element {
  const PAL = usePalette();
  const share = segmentedShare([lapsed, erased, renewed], B_LANE);

  if (share.total <= 0) {
    return <Note note="no plan endings to split" width={B_W} height={B_H} />;
  }

  const at = (i: number): ShareSegment => share.segments[i] ?? NO_SEGMENT;
  const parts: readonly LanePart[] = [
    {
      word: "lapsed",
      count: lapsed,
      seg: at(0),
      ink: PAL.D0,
      unmeasured: false,
      title: `${formatCount(lapsed)} ended, identified, and bought nothing since — the rate's numerator`,
    },
    {
      word: "erased",
      count: erased,
      seg: at(1),
      ink: PAL.HATCH,
      unmeasured: true,
      title: `${formatCount(erased)} ended and were erased by /forget — nobody can follow them to a renewal, so the rate is a floor`,
    },
    {
      word: "renewed",
      count: renewed,
      seg: at(2),
      /* Two steps down the ramp from the numerator, not four: `D4` is a gridline ink here
         (2:1 on the light card) and this is a category with a count, not a rule. */
      ink: PAL.D2,
      unmeasured: false,
      title: `${formatCount(renewed)} ended and bought again — inferred from a later purchase, with no recency bound`,
    },
  ];

  return (
    <svg
      viewBox={`0 0 ${String(B_W)} ${String(B_H)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`How the plans that ended split: ${formatCount(lapsed)} lapsed, ${formatCount(erased)} erased and unfollowable, ${formatCount(renewed)} renewed`}
    >
      {parts.map((part) => {
        const x1 = B_X + part.seg.offset;
        const x2 = x1 + part.seg.length;
        const top = B_Y - B_THICK / 2;

        return (
          <g key={part.word}>
            <title>{part.title}</title>
            {part.unmeasured
              ? hatchLines({ x: x1, y: top, width: part.seg.length, height: B_THICK }, 3.5).map(
                  (h, k) => (
                    <line
                      key={k}
                      x1={h.x1}
                      y1={h.y1}
                      x2={h.x2}
                      y2={h.y2}
                      stroke={PAL.HATCH}
                      strokeWidth={0.7}
                    />
                  ),
                )
              : part.seg.length > 0 && (
                  <line
                    x1={x1}
                    y1={B_Y}
                    x2={x2}
                    y2={B_Y}
                    stroke={part.ink}
                    strokeWidth={B_THICK}
                    strokeLinecap="butt"
                  />
                )}
            {/* A run too thin to see is still a run: it keeps its place on the lane as a full
                -height tick, and its count is printed in the legend either way. Dropping it
                would turn "two customers we cannot follow" into "none". */}
            {part.seg.tooSmall && (
              <line
                x1={x1}
                y1={top - 2}
                x2={x1}
                y2={top + B_THICK + 2}
                stroke={part.ink}
                strokeWidth={1}
              />
            )}
          </g>
        );
      })}

      {/* Cuts between two runs that were both drawn. `segmentedShare` emits none at the lane's
          own ends and none beside an invisible neighbour. */}
      {share.dividers.map((d) => (
        <line
          key={d}
          x1={B_X + d}
          y1={B_Y - B_THICK / 2}
          x2={B_X + d}
          y2={B_Y + B_THICK / 2}
          stroke={PAL.PAPER}
          strokeWidth={1.2}
        />
      ))}

      {parts.map((part, i) => {
        const x = B_LEGEND_X[i] ?? B_X;
        return (
          <g key={`legend-${part.word}`}>
            {part.unmeasured ? (
              [0, 1, 2].map((k) => (
                <line
                  key={k}
                  x1={x + k * 4}
                  y1={B_LEGEND_Y + 2}
                  x2={x + k * 4 + 5}
                  y2={B_LEGEND_Y - 4}
                  stroke={PAL.HATCH}
                  strokeWidth={0.7}
                />
              ))
            ) : (
              <line
                x1={x}
                y1={B_LEGEND_Y - 1}
                x2={x + 13}
                y2={B_LEGEND_Y - 1}
                stroke={part.ink}
                strokeWidth={5}
              />
            )}
            <text
              x={x + 18}
              y={B_LEGEND_Y + 2}
              fontSize={9}
              fontWeight={600}
              fill={PAL.MUT}
              letterSpacing=".04em"
            >
              {`${part.word} ${formatCount(part.count)}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* The empty rendering both figures share                                      */
/* -------------------------------------------------------------------------- */

/**
 * Words in the figure's own box. A lane with no marks on it is the drawing of a measurement
 * that did not happen, and on this page that is indistinguishable from a measurement of zero
 * unless it says which it is.
 */
function Note({
  note,
  width,
  height,
}: {
  readonly note: string;
  readonly width: number;
  readonly height: number;
}): JSX.Element {
  const PAL: Palette = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={note}
    >
      <text
        x={width / 2}
        y={height / 2 + 3}
        fontSize={10}
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
