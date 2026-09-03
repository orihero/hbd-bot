/**
 * `<PurgedValue>` — a lawfully purged field, rendered as a fact.
 *
 * §11.4's sixth async state and §14's Slice 1d acceptance criterion, verbatim: an
 * identity-purged order renders as **`🔒 purged 2026-05-14`** — *"never an error, never a
 * blank"*. §12.3 is the reason: `identity_purged_at` is ALWAYS displayed, because "no name"
 * and "name purged on schedule 2026-05-14" are different facts and only one of them is
 * defensible. A blank cell reads as a rendering bug and sends support hunting for a value
 * the system deliberately destroyed; an error banner reads as an outage.
 *
 * The two nulls are different, and this component keeps them apart:
 *
 * - `purgedAt !== null` → the retention sweep ran on that date. Say so, with the date.
 * - `isPurged === true` with `purgedAt === null` → purged, timestamp not recorded. Still a
 *   lock, still not a blank, but no invented date.
 * - neither → not purged. Render `children` (which may itself be `null` for a genuinely
 *   absent value — `recipientName === "•••"` means the stored name was EMPTY, which is a
 *   third fact again).
 *
 * ## Why it is `--ink-muted` and not something quieter
 *
 * This string is graded — by an acceptance test and by a Playwright assertion — so "quiet"
 * must not become "unreadable". It is drawn in `--ink-muted`, MEASURED against the surfaces
 * it actually lands on: a table cell or a detail panel on `--surface-card` is **6.01:1** in
 * light (`#636363` on `#ffffff`) and **7.16:1** in dark (`#b2b2ba` on `#26262a`); the page
 * ground `--surface` is 5.76:1 / 7.72:1; a hovered row, the worst ground it can reach, is
 * **4.87:1** / 5.95:1. Every one clears 1.4.3's 4.5:1. It is deliberately NOT `--ink-mark`
 * (3.52:1 worst-case) and NOT `--ink-rule` (2.23:1 at its ceiling), both of which would put
 * a graded fact under the text bar.
 */

import type { ReactElement, ReactNode } from "react";

import { cn, EMPTY_VALUE, formatDate, type TimeZoneMode } from "@/lib";

import { useTimeZoneMode } from "./useTimeZoneMode";

/** U+1F512 CLOSED LOCK. §14 pins the rendering `🔒 purged <date>`. */
export const PURGE_GLYPH = "🔒";
export const PURGED_LABEL = "purged";

export interface PurgedValueProps {
  /** When the sweep purged it. The date is the point of the whole component. */
  purgedAt: string | null;
  /** Purged, but without a recorded timestamp. Ignored when `purgedAt` is set. */
  isPurged?: boolean | undefined;
  /** What to render when nothing was purged. */
  children?: ReactNode;
  /** Which clock did it, when the surface shows more than one. */
  clock?: string | undefined;
  /**
   * Let a RUN break inside itself when its container is narrower than the run.
   *
   * Off by default, which is the shape a 44px table row needs: the cell's min-content stays
   * the width of `🔒 purged 2026-05-14`, so auto table layout gives the column that much and
   * the date is never broken across a line. A fact grid pins its tracks at `minmax(0,1fr)`
   * and can be narrower than any content at all, so it turns this ON — it has a third line
   * to give, and a date that wraps is still legible where a date printed over the next
   * column is not.
   */
  isBreakable?: boolean | undefined;
  timeZoneMode?: TimeZoneMode | undefined;
  className?: string | undefined;
}

export function PurgedValue({
  purgedAt,
  isPurged = false,
  children,
  clock,
  isBreakable = false,
  timeZoneMode,
  className,
}: PurgedValueProps): ReactElement {
  const mode = useTimeZoneMode(timeZoneMode);

  if (purgedAt === null && !isPurged) {
    return <>{children ?? <span className="text-ink-muted">{EMPTY_VALUE}</span>}</>;
  }

  return (
    <span
      data-testid="purged-value"
      data-purged-at={purgedAt ?? ""}
      className={cn(
        /*
         * WRAPS, and this is load-bearing. The two runs used to sit on one `whitespace-nowrap`
         * line, which made the element's min-content width the width of the whole sentence:
         * in the `/orders/:id` fact grid (`grid-cols-4`, tracks pinned at `minmax(0,1fr)`) the
         * recipient cell's box measured 312→582 while its ink ran to 627 — 45px into the
         * `user` column that starts at 606, so "…RETENTION CLOCK" printed ON TOP OF the masked
         * Telegram id. §14 grades this string as one an operator can READ; text over text is
         * not read.
         *
         * So the container wraps, and the break lands BETWEEN the runs: the clock drops to a
         * second line, which a fact grid cell has to give. Each run stays whole unless the
         * caller says otherwise (`isBreakable`) — a table column is sized from its cells'
         * min-content, so a run that can break lets auto layout squeeze the column until the
         * date itself splits across lines, which no operator should have to read.
         *
         * What §14 pins is the STRING, and glyph, word and date are still one element:
         * `textContent` is `🔒 purged 2026-05-14` wherever the line box falls.
         */
        "inline-flex flex-wrap items-baseline gap-x-1 text-ink-muted",
        className,
      )}
      // Not a warning colour: a purge that ran on schedule is the system working.
    >
      {/* One text run, not a glyph node beside a word node: §14 pins the rendering
          `🔒 purged 2026-05-14`, and a flex gap is not a space in `textContent`. */}
      <span className={isBreakable ? undefined : "whitespace-nowrap"}>
        {`${PURGE_GLYPH} ${PURGED_LABEL}`}
        {purgedAt === null ? "" : ` ${formatDate(purgedAt, mode)}`}
      </span>
      {clock === undefined ? null : (
        <span className={cn("type-caption text-ink-muted", !isBreakable && "whitespace-nowrap")}>
          {`${clock} clock`}
        </span>
      )}
    </span>
  );
}
