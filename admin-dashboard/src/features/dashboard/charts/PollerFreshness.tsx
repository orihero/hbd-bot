import type { JSX } from "react";

import type { VendorBalanceView } from "@/api/dashboard";
import { CH, CW } from "@/features/dashboard/data";
import {
  BALANCE_STALE_MS,
  VENDOR_LABEL,
  ageLabel,
  hatchLines,
  parseInstant,
  thresholdInk,
  usePalette,
  type ThresholdState,
} from "@/features/dashboard/svg";

/* ===========================================================================
 * Geometry — the same 651x176 as every other figure, and the same full-width
 * assumption as the meters this sits under: three lines of type per row at the
 * 8px floor, and a time axis that has to hold a "3d ago" tick and a "now".
 * ======================================================================== */

/** The far end of the axis: the oldest instant on the figure. */
const X0 = 122;
/** The near end: the clock everything is aged against. */
const X1 = 424;
/** The right-hand column — the verdict, the two clocks, and the failure detail. */
const RX = 440;

const LABEL_Y = 20;
const AXIS_Y = 30;
const ROW_Y0 = 52;
const PITCH = 30;
/** Four rows is what the height holds with three lines of type beside each. */
const MAX_ROWS = 4;
/** Height of the hatched run drawn for an account that has never answered. */
const TRACK_H = 8;

/**
 * The shortest axis this figure will draw. Without a floor, a deployment whose polls all
 * answered in the last minute would get an axis spanning ninety seconds, on which a
 * four-second scheduling jitter is drawn as a dumbbell the width of the card — a picture of
 * an outage assembled entirely out of a healthy poller.
 */
const MIN_SPAN_MS = 3_600_000;

/** Enough consecutive failures that the poller is not going to answer without help. */
const LOUD_FAILURES = 3;

/**
 * Error codes that name a REJECTED account rather than a bad afternoon: a rotated key, a
 * revoked token, a plan that no longer authorises the endpoint. These never come back on
 * their own, and that is the whole distinction this figure exists to draw — a transient
 * outage is a poll to wait for, and this is a poll to go and fix.
 *
 * It is a heuristic over a free-text field, deliberately: `errorCode` is `z.string()` on the
 * wire, so there is no enum to switch on and there will be codes this pattern does not know.
 * An unmatched code still renders as a failure with its count and its text — it just is not
 * promoted to the loudest state, which is the safe direction to be wrong in.
 */
const NON_RECOVERING = /config|auth|unauthor|forbidden|invalid[_-]?(api[_-]?)?key|revoked|credential/i;

function isNonRecovering(errorCode: string | null): boolean {
  return errorCode !== null && NON_RECOVERING.test(errorCode);
}

/**
 * `12m ago`, and `just now` under a minute.
 *
 * The special case is not decoration. When the payload carries no window the axis is anchored
 * on the most recent ASK, so exactly one row is aged zero against it, and `0m ago` is a
 * measurement of the anchor rather than of the poll — it reads as a stopped clock. "Just now"
 * says the same thing without printing a number nobody measured.
 */
function agoPhrase(ms: number): string {
  return ms < 60_000 ? "just now" : `${ageLabel(ms)} ago`;
}

/** The detail line's budget at `fontSize` 8 in the right-hand column. Full text in the title. */
const DETAIL_CHARS = 46;

function clip(text: string): string {
  return text.length <= DETAIL_CHARS ? text : `${text.slice(0, DETAIL_CHARS - 1)}…`;
}

/** One vendor account's two clocks, the verdict on them, and the words that go beside it. */
interface Row {
  readonly key: string;
  readonly vendor: string;
  readonly isFallback: boolean;
  /** Age of the last ASK. `null` only when `checkedAt` could not be parsed at all. */
  readonly askedAgeMs: number | null;
  /** Age of the last ANSWER. `null` = this account has never answered a poll. */
  readonly answeredAgeMs: number | null;
  readonly consecutiveFailures: number;
  readonly state: ThresholdState;
  /**
   * The failure detail is printed in the alarm ink even though the track may be achromatic.
   * A key that was rejected on every poll it ever made has no freshness to grade — the track
   * is honestly hatched — but the rejection itself is not an unknown, and it is the loudest
   * fact on the figure.
   */
  readonly isLoud: boolean;
  readonly headline: string;
  readonly clocks: string;
  readonly detail: string;
  readonly title: string;
}

/** Worst first. Only ever applied when the list is too long to draw — see the component. */
const URGENCY: Record<ThresholdState, number> = { bad: 0, warn: 1, unknown: 2, ok: 3 };

function buildRow(b: VendorBalanceView, nowMs: number): Row {
  const label = VENDOR_LABEL[b.vendor];
  const named = b.isFallback ? `${label} fallback (${b.provider})` : `${label} (${b.provider})`;
  const checked = parseInstant(b.checkedAt);
  const fetched = b.fetchedAt === null ? null : parseInstant(b.fetchedAt);
  // Clamped at zero: a poll instant a few seconds ahead of the window's `to` is clock skew
  // between two processes, and a negative age would draw a dot off the right of the axis.
  const askedAgeMs = checked === null ? null : Math.max(0, nowMs - checked);
  const answeredAgeMs = fetched === null ? null : Math.max(0, nowMs - fetched);
  const never = answeredAgeMs === null;
  const stale = answeredAgeMs !== null && answeredAgeMs > BALANCE_STALE_MS;
  const rejected = isNonRecovering(b.errorCode) && b.consecutiveFailures > 0;
  const fails = `${String(b.consecutiveFailures)} failed poll${b.consecutiveFailures === 1 ? "" : "s"}`;

  const state: ThresholdState = never
    ? "unknown"
    : stale || rejected || b.consecutiveFailures >= LOUD_FAILURES
      ? "bad"
      : b.consecutiveFailures > 0 || !b.isLastPollOk
        ? "warn"
        : "ok";

  let headline: string;
  let headlineHasFails = false;
  if (never) {
    headline = rejected ? "never answered · key rejected" : "never answered";
  } else if (stale) {
    headline = `${ageLabel(answeredAgeMs)} stale`;
  } else if (rejected) {
    headline = "key rejected · no self-heal";
  } else if (b.consecutiveFailures > 0) {
    headline = fails;
    headlineHasFails = true;
  } else if (!b.isLastPollOk) {
    headline = "last poll failed";
  } else {
    headline = "fresh";
  }

  const asked =
    askedAgeMs === null ? "asked — unreadable clock" : `asked ${agoPhrase(askedAgeMs)}`;
  const answered =
    answeredAgeMs === null ? "never answered" : `answered ${agoPhrase(answeredAgeMs)}`;
  const clocks = `${asked} · ${answered}`;

  const parts: string[] = [];
  if (b.errorCode !== null) parts.push(b.errorCode);
  if (b.httpStatus !== null) parts.push(`HTTP ${String(b.httpStatus)}`);
  if (b.consecutiveFailures > 0 && !headlineHasFails) parts.push(fails);
  const detail = parts.join(" · ");

  return {
    key: `${b.vendor}:${b.provider}:${String(b.isFallback)}`,
    vendor: label,
    isFallback: b.isFallback,
    askedAgeMs,
    answeredAgeMs,
    consecutiveFailures: b.consecutiveFailures,
    state,
    isLoud: rejected || state === "bad",
    headline,
    clocks,
    detail: clip(detail),
    title:
      `${named}: ${clocks}. ${headline}.` +
      (detail === "" ? "" : ` ${detail}.`) +
      (rejected
        ? " A rejected key does not recover on its own."
        : ""),
  };
}

export interface PollerFreshnessProps {
  /**
   * The SAME `vendorBalances` array `VendorBalanceMeters` is given, unchanged and in the
   * server's order — one row per account, and the two figures must be drawn from one array
   * or they will disagree about which accounts exist.
   *
   * Every row carries two clocks and they are not interchangeable: `checkedAt` is when the
   * poller last ASKED and is always present, `fetchedAt` is when the account last ANSWERED
   * and is `null` for an account that never has. An empty array is a poller that has never
   * run at all.
   */
  readonly balances: readonly VendorBalanceView[];
  /**
   * The clock the two ages are measured against — pass `vendor.window.to`, the same value
   * given to the meters, so the two figures cannot age the same poll differently.
   *
   * `null` when the response carried no window, and then the axis is anchored on the most
   * recent ASK instead and says so ("latest ask" rather than "now"). Do not substitute the
   * browser's clock: the ages must be the server's, or an operator in another timezone reads
   * a five-hour-old poll as fresh.
   */
  readonly asOf: string | null;
  /**
   * `capabilities.isVendorBalance`. `false` means no account is polled here at all, which is
   * not the same sentence as a poller that has run and failed, and gets its own rendering.
   */
  readonly isVendorBalance: boolean;
}

/**
 * One dumbbell per vendor account: when the poller last ASKED, when the account last
 * ANSWERED, and the gap between the two drawn as the mark.
 *
 * **This is the figure that makes the meters above it honest.** A failed poll does not clear
 * the cached balance — it leaves the last good numbers sitting exactly where they were — so a
 * green "plenty remaining" lane over a three-day-old `fetchedAt` is the most dangerous single
 * thing this section can show, and it is a thing the meters alone cannot show at all. Here
 * the gap between the two dots IS the failure: a healthy account draws asked and answered at
 * the same instant, one small concentric mark on the right of the axis, and there is nothing
 * to see. Everything you can see on this figure is a poll that did not answer.
 *
 * **What it claims.** Two instants per account and the arithmetic between them. Nothing about
 * the balance itself: an old answer is not a wrong answer, it is an answer that stopped being
 * evidence, and this figure is careful to say only that.
 *
 * **What it will not average.** There is no "poll success rate" here, and no cadence assumed.
 * The interval the poller runs at is configuration this payload does not carry, so a bar
 * measured against an invented "should have polled by now" would be a claim built out of a
 * constant somebody guessed. Everything drawn is the difference between two timestamps the
 * server sent, plus the one absolute boundary the meters already use — seven days, past which
 * a reading is a memory rather than a balance.
 *
 * **A rejected key is drawn louder than an outage, because it never ends.** `config_invalid`
 * and its relatives beside a climbing `consecutiveFailures` mean a rotated, revoked or
 * unauthorised credential: no amount of waiting fixes it, and every hour it stays that way
 * the balance above it drifts further from the truth while still looking like a measurement.
 * That row says "no self-heal" in words and takes the alarm ink even when its track is
 * hatched. A transient failure takes the amber and the count, and is left to recover.
 *
 * **`fetchedAt: null` is a state, not a missing value.** "We have never successfully measured
 * this account" is a real, common condition — a key configured but never valid, a provider
 * enabled this morning — and it is drawn as a hatched run off the left edge of the axis with
 * one dot at the ask end. It is not zero, not fresh, and not an error unless the error codes
 * beside it say so.
 */
export function PollerFreshness({
  balances,
  asOf,
  isVendorBalance,
}: PollerFreshnessProps): JSX.Element {
  // The ramp for the palette on screen. A chart drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  // House rule 5: the nothing-measured renderings come before the geometry, and they are
  // three different sentences that must not collapse into one another.
  if (!isVendorBalance) {
    return <Empty note="no vendor balance is polled in this deployment" />;
  }
  if (balances.length === 0) {
    return <Empty note="the balance poller has never run — there is no poll to date" />;
  }

  // The anchor for both ages. `window.to` when there is one; otherwise the most recent ASK,
  // which makes the axis relative rather than absolute — honest, and labelled as such.
  const asOfMs = asOf === null ? null : parseInstant(asOf);
  const asks = balances
    .map((b) => parseInstant(b.checkedAt))
    .filter((ms): ms is number => ms !== null);
  const nowMs = asOfMs ?? (asks.length > 0 ? Math.max(...asks) : null);
  if (nowMs === null) {
    return <Empty note="the poll clocks could not be read — no instant on this payload parses" />;
  }

  const rows = balances.map((b) => buildRow(b, nowMs));
  // Wire order while every account fits — a row that moves between renders is noise. Only a
  // list too long to draw is reordered, and then worst first, so truncation can never be the
  // reason a rejected key went unseen.
  const shown =
    rows.length <= MAX_ROWS
      ? rows
      : [...rows].sort((a, b) => URGENCY[a.state] - URGENCY[b.state]).slice(0, MAX_ROWS);
  const hidden = rows.length - shown.length;

  const ages = shown.flatMap((r) => [r.askedAgeMs ?? 0, r.answeredAgeMs ?? 0]);
  const span = Math.max(MIN_SPAN_MS, ...ages);
  const xOf = (ageMs: number): number =>
    X1 - ((X1 - X0) * Math.min(Math.max(ageMs, 0), span)) / span;
  const bottom = ROW_Y0 + (shown.length - 1) * PITCH + 9;
  const staleInside = BALANCE_STALE_MS < span;

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={
        "Balance poller freshness, one account per row: the left dot is when the account last " +
        "answered, the right dot is when the poller last asked, and the bar between them is a " +
        "poll that has not answered since. A hatched run is an account that has never answered."
      }
    >
      <text
        x={X0 - 10}
        y={LABEL_Y}
        fontSize={8}
        fontWeight={700}
        fill={PAL.MUT}
        textAnchor="end"
        letterSpacing=".08em"
      >
        ASKED · ANSWERED
      </text>
      <line x1={X0} y1={AXIS_Y} x2={X1} y2={AXIS_Y} stroke={PAL.D6} strokeWidth={1} />
      <text x={X0} y={LABEL_Y} fontSize={8} fontWeight={600} fill={PAL.D3} textAnchor="start">
        {`${ageLabel(span)} ago`}
      </text>
      <text x={X1} y={LABEL_Y} fontSize={8} fontWeight={700} fill={PAL.MUT} textAnchor="end">
        {asOfMs === null ? "latest ask" : "now"}
      </text>

      {/* The one absolute boundary on the figure, and it is the meters' own: an answer older
          than this is what turns a lane there from a reading into a memory. Drawn as POSITION
          so the reason a lane went grey is visible here rather than only asserted there. */}
      {staleInside && (
        <g>
          <line
            x1={xOf(BALANCE_STALE_MS)}
            y1={AXIS_Y}
            x2={xOf(BALANCE_STALE_MS)}
            y2={bottom}
            stroke={PAL.GRID}
            strokeWidth={1}
            strokeDasharray="2 3"
          />
          <text
            x={xOf(BALANCE_STALE_MS)}
            y={LABEL_Y}
            fontSize={8}
            fontWeight={600}
            fill={PAL.D3}
            textAnchor="middle"
            letterSpacing=".06em"
          >
            stale
          </text>
        </g>
      )}

      {shown.map((row, i) => {
        const y = ROW_Y0 + i * PITCH;
        const ink = thresholdInk(PAL, row.state);
        const loudInk = row.isLoud ? PAL.BAD : ink;
        const asked = row.askedAgeMs === null ? null : xOf(row.askedAgeMs);
        const answered = row.answeredAgeMs === null ? null : xOf(row.answeredAgeMs);
        // Two dots less than a mark apart are one mark. Drawn concentric rather than as a
        // zero-length bar, because a bar of no length reads as a missing bar.
        const together = asked !== null && answered !== null && Math.abs(asked - answered) < 1.6;
        const bad = row.state === "bad";

        return (
          <g key={row.key}>
            <line x1={X0} y1={y} x2={X1} y2={y} stroke={PAL.GRID} strokeWidth={0.8} />

            <text
              x={X0 - 10}
              y={row.isFallback ? y - 3 : y + 3}
              fontSize={8}
              fontWeight={700}
              fill={PAL.MUT}
              textAnchor="end"
              letterSpacing=".08em"
            >
              {row.vendor}
            </text>
            {row.isFallback && (
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

            {/* Never answered: the run has no left end, because the thing that would end it
                has not happened. Hatched, achromatic, and off the edge of the axis — an
                account with no answer has no freshness to grade, only a reason. */}
            {answered === null && asked !== null && (
              <>
                {hatchLines({
                  x: X0,
                  y: y - TRACK_H / 2,
                  width: Math.max(0, asked - X0),
                  height: TRACK_H,
                }).map((h, k) => (
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
                ))}
                <line
                  x1={X0}
                  y1={y - 5}
                  x2={X0}
                  y2={y + 5}
                  stroke={PAL.HATCH}
                  strokeWidth={0.8}
                  strokeDasharray="2 2"
                />
              </>
            )}

            {/* The clock itself is unreadable: no dot can be placed, so nothing is placed. */}
            {asked === null &&
              hatchLines({
                x: X0,
                y: y - TRACK_H / 2,
                width: X1 - X0,
                height: TRACK_H,
              }).map((h, k) => (
                <line
                  key={`nohatch-${String(k)}`}
                  x1={h.x1}
                  y1={h.y1}
                  x2={h.x2}
                  y2={h.y2}
                  stroke={PAL.HATCH}
                  strokeWidth={0.6}
                  opacity={0.85}
                />
              ))}

            {answered !== null && asked !== null && !together && (
              <>
                <line
                  x1={answered}
                  y1={y}
                  x2={asked}
                  y2={y}
                  stroke={ink}
                  strokeWidth={bad ? 2.2 : 1.6}
                  strokeLinecap="butt"
                />
                {/* Whiskers on an alarm row: the same bar, heavier, so the loudest state is
                    louder in WEIGHT as well as in ink — the three threshold inks are near
                    isoluminant, so ink alone is not a channel a monochrome reader has. */}
                {bad && (
                  <>
                    <line x1={answered} y1={y - 4} x2={answered} y2={y + 4} stroke={ink} strokeWidth={1} />
                    <line x1={asked} y1={y - 4} x2={asked} y2={y + 4} stroke={ink} strokeWidth={1} />
                  </>
                )}
              </>
            )}

            {/* Answered: hollow, because it is the older of the two and the one that stopped. */}
            {answered !== null && !together && (
              <circle cx={answered} cy={y} r={3.4} fill={PAL.PAPER} stroke={ink} strokeWidth={1.2}>
                <title>{row.title}</title>
              </circle>
            )}
            {asked !== null && !together && (
              <circle cx={asked} cy={y} r={3} fill={ink}>
                <title>{row.title}</title>
              </circle>
            )}
            {/* `together` already carries "both dots exist" — it is built out of that test. */}
            {together && (
              <>
                <circle cx={asked} cy={y} r={4.2} fill="none" stroke={ink} strokeWidth={1.2} />
                <circle cx={asked} cy={y} r={1.6} fill={ink}>
                  <title>{row.title}</title>
                </circle>
              </>
            )}

            {/* The count at the tip — the ask end, the most recent thing that happened. Set
                below the dot rather than beside it so a poll from a minute ago does not push
                it into the words at the right. */}
            {row.consecutiveFailures > 0 && asked !== null && (
              <text
                x={asked}
                y={y + 12}
                fontSize={8}
                fontWeight={700}
                fill={loudInk}
                textAnchor="middle"
              >
                {`×${String(row.consecutiveFailures)}`}
              </text>
            )}

            <text x={RX} y={y - 5} fontSize={10} fontWeight={700} fill={row.isLoud ? PAL.BAD : ink}>
              {row.headline}
              <title>{row.title}</title>
            </text>
            <text x={RX} y={y + 5} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".04em">
              {row.clocks}
            </text>
            {row.detail !== "" && (
              <text
                x={RX}
                y={y + 15}
                fontSize={8}
                fontWeight={600}
                fill={loudInk}
                letterSpacing=".04em"
              >
                {row.detail}
              </text>
            )}
          </g>
        );
      })}

      {hidden > 0 && (
        <text x={X0} y={CH - 6} fontSize={8} fontWeight={600} fill={PAL.D3} letterSpacing=".06em">
          {`+${String(hidden)} further account${hidden === 1 ? "" : "s"} not drawn — the rows above are the ones failing hardest`}
        </text>
      )}
    </svg>
  );
}

/**
 * No rows. An empty time axis would read as a poller that ran and found nothing to say, which
 * is the one thing an absent poll never means.
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
