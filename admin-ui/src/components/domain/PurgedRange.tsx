/**
 * `<PurgedRange>` — a gap in a sequence, explained.
 *
 * §11.2, `/chat/:tgId`: "purged ranges shown as `PurgedRange` **with the clock that did
 * it**". A transcript with three months missing in the middle is either a retention sweep
 * doing its job or a data loss incident, and those two readings lead to opposite actions.
 * The clock's name is what separates them, so it is required, not optional.
 *
 * The chat surface itself is Phase 3 (there is no chat endpoint on this build), but the
 * same shape is needed wherever a bounded window of records was destroyed on schedule: an
 * order's attempt list after `textPurgedAt`, an audit page after the 90-day reason clock.
 *
 * A count of what went is deliberately optional and deliberately not invented: the sweep
 * deletes rows, so a surface that cannot count them must say nothing rather than "0
 * messages", which reads as "there was nothing here".
 */

import type { ReactElement } from "react";

import { cn, formatDate, formatInteger, type TimeZoneMode } from "@/lib";

import { PURGE_GLYPH, PURGED_LABEL } from "./PurgedValue";
import { useTimeZoneMode } from "./useTimeZoneMode";

export interface PurgedRangeProps {
  /** When the sweep ran. */
  purgedAt: string;
  /** WHICH clock did it — `chat log`, `brief text`, `audit reason`. Never omitted. */
  clock: string;
  /** The window that was destroyed, where the surface knows it. */
  from?: string | null | undefined;
  to?: string | null | undefined;
  /** How many records went, where the surface can count them. Never guessed. */
  recordCount?: number | null | undefined;
  timeZoneMode?: TimeZoneMode | undefined;
  className?: string | undefined;
}

export function PurgedRange({
  purgedAt,
  clock,
  from,
  to,
  recordCount,
  timeZoneMode,
  className,
}: PurgedRangeProps): ReactElement {
  const mode = useTimeZoneMode(timeZoneMode);
  const hasWindow =
    from !== null && from !== undefined && to !== null && to !== undefined && from !== "";

  return (
    <div
      data-testid="purged-range"
      data-clock={clock}
      className={cn(
        // The dashed outline survives the reskin on purpose. This design draws no 1px
        // boxes, but a DASHED one is not chrome here — it is the component's meaning: a
        // window of records that is missing rather than empty. It is `--hairline-strong`,
        // decoration under 1.4.11, with the words carrying the fact. The radius and the
        // padding are the Gogo scale.
        "flex flex-col gap-1 rounded-2xl border border-dashed border-hairline-strong px-4 py-3",
        "text-ink-muted",
        className,
      )}
    >
      <span className="type-body-sm inline-flex items-baseline gap-1">
        <span>{`${PURGE_GLYPH} ${PURGED_LABEL} ${formatDate(purgedAt, mode)}`}</span>
        <span className="text-ink-muted">{`· ${clock} clock`}</span>
      </span>
      {hasWindow ? (
        <span className="type-body-sm num text-ink-muted">
          {`${formatDate(from, mode)} → ${formatDate(to, mode)}`}
        </span>
      ) : null}
      {recordCount === null || recordCount === undefined ? null : (
        <span className="type-body-sm num text-ink-muted">
          {`${formatInteger(recordCount)} ${recordCount === 1 ? "record" : "records"}`}
        </span>
      )}
    </div>
  );
}
