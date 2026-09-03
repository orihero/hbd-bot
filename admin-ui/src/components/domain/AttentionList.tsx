/**
 * `<AttentionList>` — the short list on `/` of orders that are not fine.
 *
 * §11.2's Live-Ops question is "is the system fine right now?", and the 24h success rate
 * answers it in aggregate. This answers the follow-up an operator asks half a second later:
 * *which ones*. It is deliberately a SHORT list — everything else is `/orders`, which is
 * filterable — because a dashboard list long enough to scroll stops being read.
 *
 * The ordering is the component's whole opinion, and it is by consequence, not by clock:
 *
 * 1. **failed** first — someone paid and has nothing.
 * 2. **held** next — a person is waiting on a human decision (§11.2 ages that in amber
 *    past 5 minutes; the state arrives with the moderation phase).
 * 3. **in flight** last, OLDEST first — a `generating` order that has sat for an hour is
 *    the one that is actually stuck, and sorting newest-first would bury it.
 *
 * Everything else is dropped: a delivered order does not need attention, and padding the
 * list with healthy rows is how an operator learns to skip it.
 *
 * The recipient name goes through `<NameText>` and a purged identity through
 * `<PurgedValue>` — `🔒 purged 2026-05-14`, never a blank (§14).
 */

import type { ReactElement } from "react";

import type { OrderView } from "@/api";
import { cn, formatRelative, formatTimestamp, type TimeZoneMode } from "@/lib";

import { ErrorCodeBadge } from "./ErrorCodeBadge";
import { NameText } from "./NameText";
import { OrderRefChip } from "./OrderRefChip";
import { PurgedValue } from "./PurgedValue";
import { StatusPill } from "./StatusPill";
import { TelegramUserChip } from "./TelegramUserChip";
import { useTimeZoneMode } from "./useTimeZoneMode";

/**
 * Lower sorts first. Anything not listed does not need attention and is dropped. Rank 1 is
 * left free for `held`, which is in `STATUS_GLYPH` but is not an `OrderState` on this build.
 */
const ATTENTION_RANK: Partial<Record<OrderView["state"], number>> = {
  failed: 0,
  generating: 2,
  authorized: 3,
};

export interface AttentionListProps {
  orders: readonly OrderView[];
  /** How many rows to show before deferring to `/orders`. */
  limit?: number | undefined;
  /** Injected in tests so "2h ago" is not a function of the wall clock. */
  now?: number | undefined;
  timeZoneMode?: TimeZoneMode | undefined;
  className?: string | undefined;
}

export function AttentionList({
  orders,
  limit = 8,
  now,
  timeZoneMode,
  className,
}: AttentionListProps): ReactElement {
  const mode = useTimeZoneMode(timeZoneMode);
  const at = now ?? Date.now();

  const rows = orders
    .filter((order) => ATTENTION_RANK[order.state] !== undefined)
    .slice()
    .sort((left, right) => {
      const leftRank = ATTENTION_RANK[left.state] ?? Number.MAX_SAFE_INTEGER;
      const rightRank = ATTENTION_RANK[right.state] ?? Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) return leftRank - rightRank;
      // Oldest first, and by plain string comparison: RFC 3339 instants sort
      // lexicographically, and a locale-aware collator would make the order depend on the
      // operator's machine.
      if (left.updatedAt < right.updatedAt) return -1;
      if (left.updatedAt > right.updatedAt) return 1;
      return 0;
    })
    .slice(0, limit);

  return (
    <section
      data-testid="attention-list"
      aria-label="needs attention"
      className={cn("flex flex-col rounded-card bg-surface-card shadow-card", className)}
    >
      <header className="px-card pb-3 pt-card">
        <h2 className="type-h2 text-ink">needs attention</h2>
      </header>
      {/* Rows separated by whitespace and a hover ground, not by a `divide-y` rule: this is
          a short feed of eight items, not a dense data grid. */}
      <ol className="flex flex-col gap-1 px-2 pb-3">
        {rows.length === 0 ? (
          <li className="type-body-sm px-3 py-6 text-ink-muted" data-testid="attention-list-empty">
            nothing failed or in flight
          </li>
        ) : (
          rows.map((order) => (
            <li
              key={order.id}
              data-testid="attention-row"
              data-state={order.state}
              className={cn(
                "flex flex-wrap items-center gap-2 rounded-control px-3 py-2.5",
                "transition-colors duration-fast ease-standard hover:bg-surface-control",
              )}
            >
              <StatusPill state={order.state} />
              <OrderRefChip orderId={order.id} />
              <TelegramUserChip
                telegramUserId={order.telegramUserId}
                telegramUserIdMasked={order.telegramUserIdMasked}
              />
              <NameText
                value={order.recipientName}
                fallback={
                  <PurgedValue
                    purgedAt={order.identityPurgedAt}
                    isPurged={order.isIdentityPurged}
                    clock="identity"
                    timeZoneMode={mode}
                  />
                }
              />
              <span
                className="type-body-sm num ml-auto text-ink-muted"
                title={formatTimestamp(order.updatedAt, mode, { seconds: true })}
              >
                {formatRelative(order.updatedAt, at)}
              </span>
              {order.state === "failed" ? (
                <ErrorCodeBadge
                  code={order.failedReason}
                  isRetryable={order.isFailedReasonRetryable}
                  className="basis-full"
                />
              ) : null}
            </li>
          ))
        )}
      </ol>
    </section>
  );
}
