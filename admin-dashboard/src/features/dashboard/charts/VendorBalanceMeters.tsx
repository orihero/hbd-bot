import type { JSX } from "react";

import type { BalanceEstimateBasis, BalanceUnit, VendorBalanceView } from "@/api/dashboard";
import {
  BASIS_BOUND,
  BOUND_SIGN,
  formatCount,
  formatUsd,
  type Bound,
} from "@/features/dashboard/adapt";
import { CH, CW } from "@/features/dashboard/data";
import {
  BALANCE_STALE_MS,
  VENDOR_LABEL,
  ageLabel,
  hatchLines,
  parseInstant,
  THRESHOLD_BAD_BELOW,
  THRESHOLD_WARN_BELOW,
  thresholdInk,
  thresholdLabel,
  thresholdOf,
  usePalette,
  type ThresholdState,
} from "@/features/dashboard/svg";

/* ===========================================================================
 * Geometry. Fixed 651x176 like every other figure in this folder — the card
 * scales it, it does not reflow — and sized for a FULL-WIDTH slot: each lane
 * carries two lines of type at the sizes rule 3 sets as the floor, and there
 * is no version of this drawing that survives being halved.
 * ======================================================================== */

/** Where a lane starts. Everything left of it is the vendor's name. */
const X0 = 132;
/** Where the axis ends — `AXIS_SONGS` of cover. Everything right of it is words. */
const X1 = 452;
/** The right-hand text column: the figure, then the state word and the native balance. */
const RX = X1 + 14;

/**
 * The axis ceiling, in songs of cover, and it is FIXED rather than fitted to the data.
 *
 * A fitted axis is the obvious choice and it is the wrong one here. The whole point of the
 * lane is that the operator can see the verdict as POSITION — the 30 and 100 boundaries have
 * to sit somewhere the eye can find them — and one vendor holding 4 000 songs of cover would
 * push both boundaries into the first 2% of the lane, where the difference between critical
 * and healthy is a pixel and a half. 150 is one and a half times the green boundary, so a
 * healthy account still has visible headroom above the rule it cleared.
 *
 * A balance past the ceiling is drawn to the end with a dashed stub and prints its true
 * figure, the way an over-long cost row does in `CostSplit` — clipped, and saying so.
 */
const AXIS_SONGS = 150;

const LABEL_Y = 20;
const AXIS_Y = 30;
const LANE_Y0 = 48;
const PITCH = 30;
/** Four lanes is what 176 units of height holds with two lines of type under each. */
const MAX_LANES = 4;
/** Height of the hatched box an unmeasured lane is drawn as. */
const LANE_H = 8;
/** How far past the axis the "there is more of this" stub runs. */
const OVERFLOW = 14;

/**
 * The native balance, in the unit the vendor actually quoted — `$0.93`, `112.6k chars`.
 *
 * Shortened above ten thousand only: `4 312` is a number an operator reads as a number, and
 * `4.3k` throws away the digits that decide whether it is an afternoon or a week.
 */
function nativeFigure(remaining: number | null, unit: BalanceUnit): string | null {
  if (remaining === null || !Number.isFinite(remaining)) return null;
  if (unit === "usd") return formatUsd(remaining);
  const abs = Math.abs(remaining);
  if (abs >= 1e6) return `${(remaining / 1e6).toFixed(1)}M chars`;
  if (abs >= 1e4) return `${(remaining / 1e3).toFixed(1)}k chars`;
  return `${formatCount(remaining)} chars`;
}

function xOf(songs: number): number {
  const clamped = Math.min(Math.max(songs, 0), AXIS_SONGS);
  return X0 + ((X1 - X0) * clamped) / AXIS_SONGS;
}

/**
 * How the divisor is described in the lane's HOVER TITLE, which is the one place on this page
 * a full sentence still belongs: it costs no pixels until asked for.
 */
const BASIS_PHRASE: Record<BalanceEstimateBasis, string> = {
  trailing_spend_usd: "estimated from trailing spend",
  trailing_tts_characters: "upper bound, divided by trailing TTS characters",
  quota_period_credit_burn: "lower bound, divided by credits burned this quota period",
};

/** One drawn lane: the verdict, the geometry it is drawn at, and the words beside it. */
interface Lane {
  readonly key: string;
  readonly vendor: string;
  readonly isFallback: boolean;
  readonly state: ThresholdState;
  /** Songs of cover, or `null` — the lane is hatched and `reason` says why. */
  readonly songs: number | null;
  /** Which way the basis is biased, so the headline can carry the inequality it earns. */
  readonly bound: Bound;
  /** `$0.93` / `112.6k chars`, or `null` when the vendor reported no remaining figure. */
  readonly native: string | null;
  /** Empty for a measured lane; otherwise the reason there is no reading, in words. */
  readonly reason: string;
  readonly title: string;
}

/**
 * One row of the wire's `vendorBalances` into a lane, with the UNMEASURED cases decided
 * first because they are the common ones — see the component's docstring.
 *
 * The order of the tests is the whole of the logic and it is not arbitrary:
 *  1. never answered outranks everything, because with no answer there is no age to state;
 *  2. STALE outranks the figure itself — a green meter over a three-day-old reading is the
 *     single most expensive thing this section could draw;
 *  3. a real `songsRemaining` is honoured next, even when `remaining` is null, so a vendor
 *     that reports an estimate without a raw balance is never thrown away;
 *  4. only then the three silences, which differ from each other in what the operator should
 *     do about them: an uncapped key needs nothing, an unreported balance needs the poller
 *     looked at, and a missing per-song rate needs a rate configured.
 */
function buildLane(b: VendorBalanceView, asOfMs: number | null): Lane {
  const label = VENDOR_LABEL[b.vendor];
  const named = b.isFallback ? `${label} fallback (${b.provider})` : `${label} (${b.provider})`;
  const native = nativeFigure(b.remaining, b.unit);
  const fetched = b.fetchedAt === null ? null : parseInstant(b.fetchedAt);
  const ageMs = fetched === null || asOfMs === null ? null : Math.max(0, asOfMs - fetched);
  const failing =
    b.consecutiveFailures > 0
      ? ` · ${String(b.consecutiveFailures)} failed poll${b.consecutiveFailures === 1 ? "" : "s"}`
      : "";
  const coded = b.errorCode === null ? "" : ` · ${b.errorCode}`;
  const identity = {
    key: `${b.vendor}:${b.provider}:${String(b.isFallback)}`,
    vendor: label,
    isFallback: b.isFallback,
  } as const;

  const unmeasured = (reason: string, why: string): Lane => ({
    ...identity,
    state: "unknown",
    songs: null,
    bound: "none",
    native,
    reason,
    title: `${named}: ${why}${coded}${failing}`,
  });

  if (b.fetchedAt === null) {
    return unmeasured(
      "never answered",
      "this account has never answered a poll.",
    );
  }
  if (ageMs !== null && ageMs > BALANCE_STALE_MS) {
    return unmeasured(
      `${ageLabel(ageMs)} stale`,
      `last answered ${ageLabel(ageMs)} ago.`,
    );
  }
  if (b.songsRemaining !== null) {
    const state = thresholdOf(b.songsRemaining);
    const bound: Bound = b.estimateBasis === null ? "none" : BASIS_BOUND[b.estimateBasis];
    const basis = b.estimateBasis === null ? "" : ` · ${BASIS_PHRASE[b.estimateBasis]}`;
    const held = native === null ? "" : ` · ${native} remaining`;
    const age = ageMs === null ? "" : ` · answered ${ageLabel(ageMs)} ago`;
    const ok = b.isLastPollOk ? "" : " · last poll failed";
    return {
      ...identity,
      state,
      songs: b.songsRemaining,
      bound,
      native,
      reason: "",
      title:
        `${named}: ${String(b.songsRemaining)} songs of cover — ${thresholdLabel(state)}` +
        `${basis}${held}${age}${ok}${failing}${coded}`,
    };
  }
  if (b.isUnbounded === true) {
    return unmeasured(
      "uncapped key",
      "the key reports no cap.",
    );
  }
  if (b.remaining === null) {
    return unmeasured("not reported", "the poll answered, but no remaining figure came back.");
  }
  return unmeasured(
    "no per-song rate",
    "there is a balance, but no measured per-song rate to divide it by.",
  );
}

/** Worst first. Only ever applied when the list is too long to draw — see the component. */
const URGENCY: Record<ThresholdState, number> = { bad: 0, warn: 1, unknown: 2, ok: 3 };

export interface VendorBalanceMetersProps {
  /**
   * `vendorBalances` from `GET /api/metrics/dashboard/vendor`, unchanged and in the server's
   * own order. ONE LANE PER ROW: two OpenRouter keys are two accounts and two lanes, told
   * apart by `isFallback`. An EMPTY array is not "$0" — it is a poller that has never run,
   * and it gets its own rendering.
   */
  readonly balances: readonly VendorBalanceView[];
  /**
   * The clock every age on this figure is measured against — pass `vendor.window.to`.
   * `null` when the response carried no window, and then NO age is computed and no lane can
   * be called stale: an unknown age is not a fresh one, so the reasons stay whatever else the
   * row says. Do not substitute the browser's clock; the ages must be the server's.
   */
  readonly asOf: string | null;
  /**
   * `capabilities.isVendorBalance`. `false` means this deployment polls no vendor for a
   * balance at all, which is a different sentence from "the poller has not run yet" and gets
   * a different empty state. Never let it collapse into an empty `balances` array.
   */
  readonly isVendorBalance: boolean;
}

/**
 * One meter lane per vendor account: how many more songs this deployment can deliver before
 * that account runs out, against the owner's 30 / 100 boundaries.
 *
 * **What it claims.** Only this: `songsRemaining` songs of cover, at the per-song rate the
 * backend divided by, as of the last answered poll. That is an ESTIMATE of a runway and the
 * drawing says so — a lane whose divisor came from trailing TTS characters prints `≤` in
 * front of its figure, because music renders bill the same pool without writing characters,
 * so that divisor undercounts and the songs figure it produces is a ceiling.
 *
 * **What it refuses to claim.** That the two vendors are comparable in their own units. They
 * are not, and the axis is the only place that could go wrong: OpenRouter answers in dollars,
 * ElevenLabs in characters, and `BalanceUnit`'s own docstring is the argument — "4 312
 * remaining is a fortune in dollars and an afternoon in ElevenLabs characters". So the LANE
 * is songs of cover for every vendor, which is the one quantity that means the same thing on
 * both rows, and the native figure is printed as TEXT in its own unit beside it, where it can
 * be read but not measured against anything. There is no combined usage axis here and there
 * is no token balance anywhere on this figure: tokens are something we spent, never something
 * we have left.
 *
 * **The unmeasured state was designed first, because it is the common one.** In the shipped
 * configuration most vendor rate settings default to 0.0, so there is no per-song divisor and
 * `songsRemaining` is null — the majority of lanes on a fresh deployment are hatched, and a
 * figure that treated that as an edge case would be a figure that is wrong most of the time.
 * Uncapped keys, unreported balances, polls that have never answered and readings too old to
 * plan against all land in the same achromatic hatched track with the reason in words. None
 * of them is a level: painting them green makes an empty account look funded, and painting
 * them red sends the operator to top up an account that was never low.
 *
 * **Read it with `PollerFreshness`, which is what makes it honest.** A failed poll leaves the
 * last known balance sitting here untouched, so this lane can be green for a week after the
 * measurement stopped. The staleness cutoff above is what stops that inside this figure; the
 * dumbbell below is where the operator sees why.
 */
export function VendorBalanceMeters({
  balances,
  asOf,
  isVendorBalance,
}: VendorBalanceMetersProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  // House rule 5: the empty renderings come before any geometry, and they are two different
  // sentences. A deployment that polls nothing has not failed at anything.
  if (!isVendorBalance) {
    return <Empty note="no vendor balance is polled in this deployment" />;
  }
  if (balances.length === 0) {
    return <Empty note="the balance poller has not run — no account has been asked yet" />;
  }

  const asOfMs = asOf === null ? null : parseInstant(asOf);
  const lanes = balances.map((b) => buildLane(b, asOfMs));
  // The wire order is kept whenever every account fits, because a lane that moves between
  // renders is noise. Only a list too long to draw is reordered, and then by urgency — so a
  // truncation can never be the reason the vendor that is out went unseen.
  const shown =
    lanes.length <= MAX_LANES
      ? lanes
      : [...lanes].sort((a, b) => URGENCY[a.state] - URGENCY[b.state]).slice(0, MAX_LANES);
  const hidden = lanes.length - shown.length;
  const guideBottom = LANE_Y0 + (shown.length - 1) * PITCH + 9;

  const gate = (songs: number, word: string): JSX.Element => (
    <g key={word}>
      <line
        x1={xOf(songs)}
        y1={AXIS_Y}
        x2={xOf(songs)}
        y2={guideBottom}
        stroke={PAL.GRID}
        strokeWidth={1}
        strokeDasharray="2 3"
      />
      <line
        x1={xOf(songs)}
        y1={AXIS_Y - 4}
        x2={xOf(songs)}
        y2={AXIS_Y}
        stroke={PAL.D4}
        strokeWidth={1}
      />
      <text
        x={xOf(songs)}
        y={LABEL_Y}
        fontSize={8}
        fontWeight={700}
        fill={PAL.MUT}
        textAnchor="middle"
        letterSpacing=".06em"
      >
        {word}
      </text>
    </g>
  );

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={
        `Remaining vendor credit, one lane per account, measured in songs of cover: ` +
        `under ${String(THRESHOLD_BAD_BELOW)} is critical, under ${String(THRESHOLD_WARN_BELOW)} ` +
        `is low, and a hatched lane is an account nothing has been measured for`
      }
    >
      {/* The unit, named once. It is the reason the lanes are comparable at all, and leaving
          it to a caption would let this figure be read as dollars against characters. */}
      <text
        x={X0 - 10}
        y={LABEL_Y}
        fontSize={8}
        fontWeight={700}
        fill={PAL.MUT}
        textAnchor="end"
        letterSpacing=".08em"
      >
        SONGS OF COVER
      </text>
      <line x1={X0} y1={AXIS_Y} x2={X1} y2={AXIS_Y} stroke={PAL.D6} strokeWidth={1} />
      <text x={X0} y={LABEL_Y} fontSize={8} fontWeight={600} fill={PAL.D3} textAnchor="middle">
        0
      </text>
      {gate(THRESHOLD_BAD_BELOW, String(THRESHOLD_BAD_BELOW))}
      {gate(THRESHOLD_WARN_BELOW, String(THRESHOLD_WARN_BELOW))}
      <text x={X1} y={LABEL_Y} fontSize={8} fontWeight={600} fill={PAL.D3} textAnchor="middle">
        {`${String(AXIS_SONGS)}+`}
      </text>

      {shown.map((lane, i) => {
        const y = LANE_Y0 + i * PITCH;
        const ink = thresholdInk(PAL, lane.state);
        const songs = lane.songs;
        const over = songs !== null && songs > AXIS_SONGS;
        const headline =
          songs === null
            ? thresholdLabel("unknown")
            : `${BOUND_SIGN[lane.bound]}${formatCount(songs)} songs`;
        const sub = songs === null ? lane.reason : thresholdLabel(lane.state);

        return (
          <g key={lane.key}>
            {/* The lane exists whether or not anything was measured in it: an account with no
                reading still has an account's worth of space, and dropping the rule would let
                a hatched row read as a missing vendor rather than an unmeasured one. */}
            <line x1={X0} y1={y} x2={X1} y2={y} stroke={PAL.GRID} strokeWidth={0.8} />

            <text
              x={X0 - 10}
              y={lane.isFallback ? y - 3 : y + 3}
              fontSize={8}
              fontWeight={700}
              fill={PAL.MUT}
              textAnchor="end"
              letterSpacing=".08em"
            >
              {lane.vendor}
            </text>
            {lane.isFallback && (
              <text
                x={X0 - 10}
                y={y + 8}
                fontSize={8}
                fontWeight={600}
                fill={PAL.D3}
                textAnchor="end"
                letterSpacing=".06em"
              >
                fallback
              </text>
            )}

            {songs === null ? (
              hatchLines({ x: X0, y: y - LANE_H / 2, width: X1 - X0, height: LANE_H }).map(
                (h, k) => (
                  <line
                    key={`hatch-${String(k)}`}
                    x1={h.x1}
                    y1={h.y1}
                    x2={h.x2}
                    y2={h.y2}
                    stroke={PAL.HATCH}
                    strokeWidth={0.6}
                    opacity={0.85}
                  />
                ),
              )
            ) : (
              <>
                <line
                  x1={X0}
                  y1={y}
                  x2={over ? X1 : xOf(songs)}
                  y2={y}
                  stroke={ink}
                  strokeWidth={1.7}
                  strokeLinecap="round"
                />
                {over ? (
                  /* Drawn to the axis and then saying so, the way an over-long cost row does:
                     a silently clipped lane would tie a vendor holding 4 000 songs with one
                     holding 151. The printed figure is the measurement. */
                  <line
                    x1={X1 + 3}
                    y1={y}
                    x2={X1 + OVERFLOW}
                    y2={y}
                    stroke={ink}
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />
                ) : (
                  <circle cx={xOf(songs)} cy={y} r={3.2} fill={ink} />
                )}
              </>
            )}

            <text x={RX} y={y + 1} fontSize={10} fontWeight={700} fill={ink}>
              {headline}
              <title>{lane.title}</title>
            </text>
            {/* The WORD, always, beside the colour: the three threshold inks are near
                isoluminant by design, so for a monochrome or dichromatic reader this line is
                not a caption, it is the measurement. */}
            <text x={RX} y={y + 12} fontSize={8} fontWeight={600} fill={ink} letterSpacing=".05em">
              {sub}
              {lane.native !== null && <tspan fill={PAL.MUT}>{` · ${lane.native}`}</tspan>}
            </text>
          </g>
        );
      })}

      {hidden > 0 && (
        <text
          x={X0}
          y={CH - 8}
          fontSize={8}
          fontWeight={600}
          fill={PAL.D3}
          letterSpacing=".06em"
        >
          {`+${String(hidden)} further account${hidden === 1 ? "" : "s"} not drawn — the lanes above are the ones nearest running out`}
        </text>
      )}
    </svg>
  );
}

/**
 * No lanes at all. An axis with four empty tracks under it would read as four accounts we
 * polled and found empty, which is the opposite of what an absent poll means.
 */
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
      {hatchLines({ x: CW / 2 - 110, y: CH / 2 + 6, width: 220, height: 8 }).map((h, k) => (
        <line
          key={`hatch-${String(k)}`}
          x1={h.x1}
          y1={h.y1}
          x2={h.x2}
          y2={h.y2}
          stroke={PAL.HATCH}
          strokeWidth={0.6}
          opacity={0.8}
        />
      ))}
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
