/**
 * The small formatting this section does that nothing else in the console already does.
 *
 * Money is deliberately NOT here: `money(minorUnits, currency)` lives in
 * `features/dashboard/adapt.ts` over a `MINOR_EXPONENT` table whose own docstring warns
 * against a second copy, and a second copy is exactly how a receipt comes to be quoted at a
 * hundredth or a hundred times what the customer actually paid. Payme amounts are tiyin —
 * minor units, exponent 2 — so they go through that function unchanged, and this file imports
 * nothing to replace it.
 *
 * What IS here is three things this section needs and no other screen does: an instant with
 * its zone named, a duration in the units an RPC log is read in, and the retention arithmetic
 * that separates "Payme never called about this" from "the journal has aged out".
 */

import type { JSX } from "react";

import { formatInstant } from "@/features/dashboard/adapt";
import { cn } from "@/lib/cn";

/** The reader's zone, named, so a timestamp is not a guess. `UTC+5`, `UTC-3:30`. */
export function localZoneLabel(): string {
  // `getTimezoneOffset` is minutes WEST of UTC, so its sign is inverted from the label's.
  const minutesWest = new Date().getTimezoneOffset();
  const sign = minutesWest <= 0 ? "+" : "-";
  const total = Math.abs(minutesWest);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  const padded = minutes < 10 ? `0${String(minutes)}` : String(minutes);
  return minutes === 0 ? `UTC${sign}${String(hours)}` : `UTC${sign}${String(hours)}:${padded}`;
}

export interface InstantProps {
  /** RFC 3339, from the wire. An unparseable value is printed VERBATIM, never as a dash. */
  readonly at: string;
  readonly className?: string | undefined;
}

/**
 * One instant, in the reader's own zone, with the raw wire value in its `title`.
 *
 * Local rather than UTC because an operator is correlating this against a support conversation
 * and a wall clock. The `title` carries the server's own string so the value that gets pasted
 * into a ticket is the one the server actually sent — three clocks are in play on this screen
 * (ours, Payme's `paymeTime`, and the reader's) and a reformatted stamp in a ticket is how the
 * wrong two get compared.
 */
export function Instant({ at, className }: InstantProps): JSX.Element {
  return (
    <time
      dateTime={at}
      title={`${at} · shown in ${localZoneLabel()}`}
      className={cn("whitespace-nowrap tabular-nums", className)}
    >
      {formatInstant(at)}
    </time>
  );
}

/**
 * A call's duration, in the unit it is actually read in.
 *
 * Milliseconds below a second, because that is the resolution an RPC log is scanned at and
 * `0.4 s` hides the difference between a healthy reply and a slow one. Seconds above, to one
 * decimal, because past a second nobody is counting milliseconds any more.
 */
export function formatMs(ms: number): string {
  if (ms < 1_000) return `${String(Math.round(ms))} ms`;
  return `${(ms / 1_000).toFixed(1)} s`;
}

/**
 * `bayram.config.PAYME_RPC_LOG_RETENTION_DAYS`. The inbound journal is swept at 90 days.
 *
 * Restated here for one screen and one sentence: a payment older than this legitimately shows
 * ZERO calls beside it, and that reads identically to "Payme never called us about this" —
 * which on a live rail is the sentence that means the payment was settled by hand. The two are
 * only separable by the payment's own age, so this number is what the dossier's calls panel
 * decides between them with.
 *
 * `payme_transactions` is on NO retention bound at all and terminal unpaid `payment_intents`
 * are deleted at 400 days, so the three tables age out at three different times and there are
 * no foreign keys anywhere between them. An orphan is ordinary here, not a defect.
 */
export const RPC_LOG_RETENTION_DAYS = 90;

const MS_PER_DAY = 24 * 60 * 60 * 1_000;

/**
 * Whether a payment is old enough that an empty call list means the journal aged out.
 *
 * `now` is a parameter rather than a `Date.now()` read, so the rule is testable and so a panel
 * and a caption cannot straddle midnight from each other. An unparseable stamp answers
 * `false`: claiming "purged" about a date we could not read would be the worse of the two
 * wrong answers, because it explains away an absence that might be real.
 */
export function isBeyondRpcRetention(openedAt: string, now: Date): boolean {
  const ms = Date.parse(openedAt);
  if (Number.isNaN(ms)) return false;
  return now.getTime() - ms > RPC_LOG_RETENTION_DAYS * MS_PER_DAY;
}
