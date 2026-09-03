/**
 * `<RetentionClocks>` — what is scheduled to disappear, and when.
 *
 * A brief runs two independent clocks (the recipient identity and the note) that expire on
 * different days under different settings; an asset runs one, keyed on its
 * `retentionClass`. Rolling them into a single "expires" line loses the answer to "why is
 * the name gone but the note still here", which is a question support gets.
 *
 * Every row is a triple — label, absolute timestamp, and how long is left — because §11.2
 * bans an ambiguous instant and `src/lib/format.ts` bans a relative time as the ONLY label:
 * "in 4d" cannot be correlated with a log line, and "2026-05-14 00:00Z" cannot be triaged
 * at a glance. Both, always.
 *
 * A clock that has already fired renders `<PurgedValue>`: `🔒 purged 2026-05-14`, never a
 * blank and never an error (§12.3).
 */

import type { ReactElement } from "react";

import { cn, daysUntil, EMPTY_VALUE, formatTimestamp, humaniseEnum, type TimeZoneMode } from "@/lib";

import { PurgedValue } from "./PurgedValue";
import {
  retentionUrgency,
  retentionUrgencyColorVar,
  type RetentionClock,
} from "./retention";
import { useTimeZoneMode } from "./useTimeZoneMode";

export interface RetentionClocksProps {
  clocks: readonly RetentionClock[];
  /** Injected in tests so "in 4d" is not a function of the wall clock. */
  now?: number | undefined;
  timeZoneMode?: TimeZoneMode | undefined;
  className?: string | undefined;
}

/** `in 4d`, `expires today`, `4d past expiry`. Our own words, about our own numbers. */
function remainingLabel(daysLeft: number | null): string {
  if (daysLeft === null) return EMPTY_VALUE;
  if (daysLeft > 1) return `in ${String(daysLeft)}d`;
  if (daysLeft === 1) return "in 1d";
  if (daysLeft === 0) return "expires today";
  return `${String(Math.abs(daysLeft))}d past expiry`;
}

export function RetentionClocks({
  clocks,
  now,
  timeZoneMode,
  className,
}: RetentionClocksProps): ReactElement {
  const mode = useTimeZoneMode(timeZoneMode);
  const at = now ?? Date.now();

  return (
    <dl
      data-testid="retention-clocks"
      className={cn("flex flex-col gap-3", className)}
      aria-label="retention clocks"
    >
      {clocks.map((clock) => {
        const daysLeft = clock.purgedAt === null ? daysUntil(clock.expiresAt, at) : null;
        const urgency = retentionUrgency(clock, daysLeft);
        return (
          <div
            key={clock.label}
            data-testid="retention-clock"
            data-clock={clock.label}
            data-urgency={urgency}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
          >
            <dt className="type-caption min-w-[8rem] text-ink-muted">{clock.label}</dt>
            <dd className="flex flex-wrap items-baseline gap-x-2">
              {clock.purgedAt === null ? (
                <>
                  <span className="type-body-sm num text-ink-muted">
                    {formatTimestamp(clock.expiresAt, mode)}
                  </span>
                  <span
                    className="type-body-sm num"
                    style={{ color: retentionUrgencyColorVar(urgency) }}
                    data-testid="retention-remaining"
                  >
                    {remainingLabel(daysLeft)}
                  </span>
                </>
              ) : (
                <PurgedValue purgedAt={clock.purgedAt} timeZoneMode={mode} />
              )}
              {clock.retentionClass === undefined ? null : (
                <span className="type-caption rounded-pill bg-surface-control px-2 py-0.5 text-ink-muted">
                  {humaniseEnum(clock.retentionClass)}
                </span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
