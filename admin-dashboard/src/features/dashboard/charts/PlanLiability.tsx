import type { JSX } from "react";

import { CW } from "@/features/dashboard/data";
import { usePalette } from "@/features/dashboard/svg";

/**
 * Taller than the 176 the full-width figures use, for the reason its neighbour in this row
 * is: at 651 wide in a two-up column a `fontSize` 8 tick renders at about 3.7 screen pixels.
 * The type is not shrunk (house rule 3) — the box grows and the axis carries three ticks.
 */
const VH = 244;
/** Left gutter: the row labels are words ("LIVE PLANS"), not codes, so they need the room. */
const X0 = 168;
/** Right gutter: every dot prints its count AND its word beside it, never a bare mark. */
const RGUT = 138;
const ROW_LIVE = 72;
const ROW_ENDED = 130;
const AXIS = 164;
/**
 * The captions start at the box edge, not at the lane origin: with two currencies on the
 * money line the sentence is long enough that starting it 168 units in ran it off the right
 * edge, and a caption that names a currency must not be the half that gets clipped.
 */
const CAP_X = 24;

export interface PlanLiabilityAmount {
  /** ISO currency of the measured sale total, e.g. `UZS`. */
  readonly currency: string;
  /**
   * The page's own money formatter applied to that currency's `amountMinor`. Preformatted
   * because a minor-unit exponent is a currency fact, not a drawing fact, and a chart that
   * guessed one would misprint a two-decimal currency by a factor of a hundred.
   */
  readonly label: string;
}

export interface PlanLiabilityProps {
  /**
   * Preformatted instant the route computed this state at. The chart does not format dates —
   * pass the page's rendering of the wire's `asOf`. Printed because `GET /api/metrics/plans`
   * takes NO window and must not be read as obeying the page's range picker.
   */
  readonly asOfLabel: string;
  /** Plans whose `planEndsAt` is still in the future. */
  readonly livePlans: number;
  /**
   * Distinct IDENTIFIED holders of those plans. Understates by exactly `liveAnonymisedPlans`,
   * because `COUNT(DISTINCT)` does not count the nulls `/forget` leaves behind.
   */
  readonly liveHolders: number;
  /** Live plans whose holder erased themselves. The exact width of the holder undercount. */
  readonly liveAnonymisedPlans: number;
  /** Live plans with at least one song left. Printed, never drawn as a share of `livePlans`. */
  readonly livePlansWithSongsLeft: number;
  /**
   * Songs paid for and not yet claimed on LIVE plans — the outstanding liability, in songs.
   * `null` means NO PLAN IS LIVE; `0` means plans are live and owe nothing. Two different
   * screens, and this component renders them differently.
   */
  readonly unconsumedSongs: number | null;
  /**
   * What the RUNNING plans were sold for, one entry per currency, in the route's order.
   * Never summed across currencies — there is no honest scalar here, and today's
   * one-element list is not a licence to collapse it. Empty when nothing is live.
   */
  readonly liveAmounts: readonly PlanLiabilityAmount[];
  /** Plans whose `planEndsAt` has passed. The population breakage is measured over. */
  readonly endedPlans: number;
  /**
   * Songs paid for and never claimed on plans that have ENDED. `null` means NO PLAN HAS
   * ENDED yet; `0` means plans ended and every song was claimed.
   */
  readonly breakageSongs: number | null;
  /** The expiry horizon the route used, in days. Printed — never assumed to be 7. */
  readonly expiringWithinDays: number;
  /** Live plans ending inside that horizon. A SUBSET of `livePlans`, never added to it. */
  readonly expiringPlans: number;
  /**
   * Songs still owed on those expiring plans. `null` means no plan expires inside the
   * horizon; `0` means some do and they owe nothing. A SUBSET of `unconsumedSongs`.
   */
  readonly expiringSongsLeft: number | null;
  /**
   * False means no plan has ever been sold here, so an empty lane is "nothing to show"
   * rather than "nothing is owed".
   */
  readonly isPlanRevenue: boolean;
}

/**
 * F11 · dumbbell — what the plan book still owes, and what it will never have to deliver.
 *
 * **The liability is in SONGS, and there is no money figure for it anywhere on this
 * figure.** Valuing an unclaimed song means dividing what a plan was sold for by the songs
 * it included, which is an accounting allocation policy nobody in this codebase has chosen;
 * a chart that quietly picked one would publish an invented soʻm number in the same
 * typeface as the measured ones. So the lane is a song count. The only money printed is
 * `liveAmounts` — the measured total the running plans were SOLD for, per currency, which
 * is a different and honest number and is captioned as one.
 *
 * The route publishes REMAINDERS, not totals: it says how many songs are still owed and how
 * many were forfeited, and it does not publish songs-sold or songs-claimed. So the dumbbell
 * is drawn over what is measured. The live row is a genuine nested pair — the songs owed on
 * every live plan, with the songs owed on the subset expiring inside the horizon marked on
 * the same hairline — and that nesting is the question worth asking of a liability: how much
 * of it is about to walk out the door. The two rows are two DISJOINT populations of plans on
 * one shared song axis; they are never stacked and never added.
 *
 * Breakage is the dashed D3 stub, drawn apart from the live hairline because it is not part
 * of the liability at all — it is the part that stopped being owed. Dashing it is the same
 * statement the funnel makes with its drop-off rungs: this length is not a commitment.
 *
 * **This figure takes no window.** Liability is a state, not a flow, and it sits under a
 * page-level range picker that does not reach it — so the instant is printed and the caption
 * says so.
 */
export function PlanLiability({
  asOfLabel,
  livePlans,
  liveHolders,
  liveAnonymisedPlans,
  livePlansWithSongsLeft,
  unconsumedSongs,
  liveAmounts,
  endedPlans,
  breakageSongs,
  expiringWithinDays,
  expiringPlans,
  expiringSongsLeft,
  isPlanRevenue,
}: PlanLiabilityProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  const owed = finite(unconsumedSongs);
  const expiring = finite(expiringSongsLeft);
  const breakage = finite(breakageSongs);

  // Nothing was ever sold. An axis with two dots on its origin would read as a book that
  // owes nothing, which is a measurement; this is the absence of one.
  if (!isPlanRevenue || (livePlans === 0 && endedPlans === 0)) {
    return <Empty note="no plan has ever been sold here" sub="nothing is owed and nothing lapsed" />;
  }

  const peak = Math.max(owed ?? 0, expiring ?? 0, breakage ?? 0);

  // Every measured song count is zero, or every partition is empty. Both end in a lane with
  // no extent, and the difference between them is the whole finding — so it is written out.
  if (peak <= 0) {
    return (
      <Empty
        note="nothing outstanding"
        sub={[
          owed === null
            ? "no plan is live"
            : `${String(livePlans)} live plans owe no song`,
          breakage === null
            ? "no plan has ended yet"
            : `${String(endedPlans)} ended plans forfeited none`,
        ].join(" · ")}
      />
    );
  }

  const x = (v: number): number => X0 + ((CW - X0 - RGUT) * v) / peak;
  const mid = Math.round(peak / 2);

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label="Plan liability in songs: songs still owed on live plans, the part of that expiring soon, and songs forfeited on ended plans. Two separate populations on one song axis, never added."
    >
      {/* ── live plans ─────────────────────────────────────────────────────────────── */}
      <RowLabel y={ROW_LIVE} title="LIVE PLANS" sub={`${String(livePlans)} on the book`} />

      {owed === null ? (
        <text x={X0} y={ROW_LIVE + 4} fontSize={10} fontWeight={600} fill={PAL.D3} letterSpacing=".04em">
          no plan is live — nothing is owed
        </text>
      ) : (
        <g>
          {/* The hairline IS the liability: origin to the songs still owed. The expiring dot
              sits on it because the expiring plans are a subset of the live ones — the two
              dots are nested, not rival, and nothing here is ever summed. */}
          <line
            x1={x(0)}
            y1={ROW_LIVE}
            x2={x(owed)}
            y2={ROW_LIVE}
            stroke={PAL.D0}
            strokeWidth={1.2}
            strokeLinecap="round"
          />
          {expiring !== null && (
            <>
              <circle
                cx={x(expiring)}
                cy={ROW_LIVE}
                r={3.4}
                fill={PAL.PAPER}
                stroke={PAL.D0}
                strokeWidth={1.2}
              >
                <title>{`${String(expiring)} songs owed on ${String(expiringPlans)} plans ending within ${String(expiringWithinDays)} days`}</title>
              </circle>
              <text
                x={x(expiring)}
                y={ROW_LIVE - 12}
                fontSize={9}
                fontWeight={700}
                fill={PAL.D0}
                textAnchor="middle"
              >
                {`${String(expiring)} expiring ≤ ${String(expiringWithinDays)}d`}
              </text>
            </>
          )}
          <circle cx={x(owed)} cy={ROW_LIVE} r={4.2} fill={PAL.ACCENT} stroke={PAL.D0} strokeWidth={1}>
            <title>{`${String(owed)} songs still owed on ${String(livePlans)} live plans`}</title>
          </circle>
          <text x={x(owed) + 10} y={ROW_LIVE + 1} fontSize={13} fontWeight={700} fill={PAL.DEEP}>
            {owed}
          </text>
          <text x={x(owed) + 10} y={ROW_LIVE + 13} fontSize={8} fontWeight={700} fill={PAL.MUT} letterSpacing=".08em">
            songs still owed
          </text>
        </g>
      )}
      {expiring === null && owed !== null && (
        <text x={X0} y={ROW_LIVE + 20} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".04em">
          {`no live plan ends within ${String(expiringWithinDays)} days`}
        </text>
      )}

      {/* ── ended plans ────────────────────────────────────────────────────────────── */}
      <RowLabel y={ROW_ENDED} title="ENDED PLANS" sub={`${String(endedPlans)} finished`} />

      {breakage === null ? (
        <text x={X0} y={ROW_ENDED + 4} fontSize={10} fontWeight={600} fill={PAL.D3} letterSpacing=".04em">
          no plan has ended yet — breakage is not measurable
        </text>
      ) : (
        <g>
          {/* Dashed, and in the faintest working ink, because this length is the opposite of
              a commitment: songs that were paid for and can no longer be claimed. Drawing it
              solid beside the live hairline would read as more of the same liability. */}
          <line
            x1={x(0)}
            y1={ROW_ENDED}
            x2={x(breakage)}
            y2={ROW_ENDED}
            stroke={PAL.D3}
            strokeWidth={1.2}
            strokeDasharray="3 3"
            strokeLinecap="round"
          />
          <circle
            cx={x(breakage)}
            cy={ROW_ENDED}
            r={3.4}
            fill={PAL.PAPER}
            stroke={PAL.D3}
            strokeWidth={1.4}
          >
            <title>{`${String(breakage)} songs paid for and never claimed on ${String(endedPlans)} ended plans`}</title>
          </circle>
          <text x={x(breakage) + 10} y={ROW_ENDED + 1} fontSize={13} fontWeight={700} fill={PAL.D2}>
            {breakage}
          </text>
          <text x={x(breakage) + 10} y={ROW_ENDED + 13} fontSize={8} fontWeight={700} fill={PAL.MUT} letterSpacing=".08em">
            never claimed
          </text>
        </g>
      )}

      {/* ── axis: three ticks, in songs ─────────────────────────────────────────────── */}
      <line x1={x(0)} y1={AXIS} x2={CW - RGUT} y2={AXIS} stroke={PAL.D6} strokeWidth={1} />
      {([[0, "0"], [mid, String(mid)], [peak, `${String(peak)} songs`]] as const).map(
        ([v, label], i) => (
          <g key={`tick-${String(i)}`}>
            <line x1={x(v)} y1={AXIS} x2={x(v)} y2={AXIS + 5} stroke={PAL.D5} strokeWidth={0.8} />
            <text
              x={x(v)}
              y={AXIS + 16}
              fontSize={8}
              fontWeight={600}
              fill={PAL.MUT}
              textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
              letterSpacing=".1em"
            >
              {label}
            </text>
          </g>
        ),
      )}

      {/* ── captions ───────────────────────────────────────────────────────────────── */}
      <text x={CAP_X} y={AXIS + 30} fontSize={9} fontWeight={600} fill={PAL.D2}>
        {holdersLine(livePlans, livePlansWithSongsLeft, liveHolders, liveAnonymisedPlans)}
      </text>
      <text x={CAP_X} y={AXIS + 43} fontSize={9} fontWeight={600} fill={PAL.D2}>
        {moneyLine(liveAmounts)}
      </text>
      {/* The qualifier gets its own line rather than trailing the totals: a third currency
          would push it off the edge, and the clipped half would be the half that says this
          money is NOT the value of the songs still owed. */}
      <text x={CAP_X} y={AXIS + 56} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".02em">
        measured sale total
      </text>
      <text x={CAP_X} y={AXIS + 69} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".04em">
        {`state as of ${asOfLabel}`}
      </text>
    </svg>
  );
}

/** A row's name and its plan count, in the left gutter, right-aligned onto the lane origin. */
function RowLabel({
  y,
  title,
  sub,
}: {
  readonly y: number;
  readonly title: string;
  readonly sub: string;
}): JSX.Element {
  const PAL = usePalette();
  return (
    <g>
      <text x={X0 - 14} y={y + 1} fontSize={9} fontWeight={700} fill={PAL.D0} textAnchor="end" letterSpacing=".1em">
        {title}
      </text>
      <text x={X0 - 14} y={y + 13} fontSize={8} fontWeight={600} fill={PAL.MUT} textAnchor="end" letterSpacing=".04em">
        {sub}
      </text>
    </g>
  );
}

/**
 * The holder count is published beside the plan count because it is SMALLER by exactly the
 * erased plans, and a reader who sees only one of the two will read the gap as churn.
 */
function holdersLine(
  livePlans: number,
  withSongsLeft: number,
  holders: number,
  anonymised: number,
): string {
  const head = `${String(withSongsLeft)} of ${String(livePlans)} live plans still have a song · ${String(holders)} identified holders`;
  return anonymised > 0
    ? `${head} (+${String(anonymised)} erased)`
    : head;
}

/**
 * The measured sale total, per currency, never collapsed to a scalar and never divided by a
 * song. The sentence says which of the two it is, because a money figure printed under a
 * liability chart will otherwise be read as the value of the liability.
 */
function moneyLine(amounts: readonly PlanLiabilityAmount[]): string {
  if (amounts.length === 0) return "no money on live plans";
  const totals = amounts.map((a) => `${a.label} ${a.currency}`).join(" · ");
  return `live plans were sold for ${totals}`;
}

/** A count we can draw, or `null`. Non-finite is not a reading; negative is not a song count. */
function finite(v: number | null): number | null {
  if (v === null || !Number.isFinite(v) || v < 0) return null;
  return v;
}

/**
 * Two dots on the origin of an empty lane read as a book that owes nothing. Say which
 * nothing it is, in words, before any geometry exists (house rule 5).
 */
function Empty({ note, sub }: { readonly note: string; readonly sub: string }): JSX.Element {
  const PAL = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={`${note} — ${sub}`}
    >
      <text
        x={CW / 2}
        y={VH / 2 - 6}
        fontSize={12}
        fontWeight={700}
        fill={PAL.D3}
        textAnchor="middle"
        letterSpacing=".06em"
      >
        {note}
      </text>
      <text
        x={CW / 2}
        y={VH / 2 + 12}
        fontSize={9}
        fontWeight={600}
        fill={PAL.MUT}
        textAnchor="middle"
        letterSpacing=".02em"
      >
        {sub}
      </text>
    </svg>
  );
}
