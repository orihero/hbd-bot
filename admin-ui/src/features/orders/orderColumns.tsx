/**
 * The `/orders` grid, column by column.
 *
 * A module of constants, not components, so `OrdersScreen.tsx` stays a pure component module
 * for Fast Refresh.
 *
 * Two cells carry the weight of this screen's acceptance criteria:
 *
 * **recipient.** `recipientName === null` and `recipientName === "•••"` are DIFFERENT FACTS.
 * `null` means the identity was purged — §14: *"Orders list renders an identity-purged order
 * as `🔒 purged 2026-05-14`, not an error and not a blank"* — so the cell's fallback is
 * `<PurgedValue>` carrying `identityPurgedAt` and the clock that fired. `"•••"` means the
 * stored name was empty and is drawn as the mask it is. A third case, no name and no purge,
 * is an em dash. A `??` collapsing any two of them is the bug this cell exists to avoid.
 *
 * **failure.** `failedReason` is closed-vocabulary operator triage text and
 * `isFailedReasonRetryable` is TRI-state: `null` means no class in `hbd.errors` claims the
 * code, which `ErrorCodeBadge` renders as `?` unknown — never as "terminal". "Is retrying
 * worth anything" is the operator's real decision and it is one glyph away.
 *
 * Every column declares a width so a 15 s poll cannot reflow the grid under the cursor, and
 * `isNumeric` is stated explicitly on every one — that is what applies `.num`
 * (`tabular-nums slashed-zero`), so a digit does not change width as counts tick.
 */

import type { OrderView } from "@/api";
import type { DataColumn } from "@/components/data";
import { Timestamp } from "@/components/data";
import {
  ErrorCodeBadge,
  NameText,
  OrderRefChip,
  PurgedValue,
  StatusPill,
  TelegramUserChip,
} from "@/components/domain";
import { EMPTY_VALUE, formatInteger } from "@/lib";

/** Which clock destroyed a recipient name. §12.3: a purge on schedule and a purge on
 *  request are different facts about the same absent value. */
export const IDENTITY_CLOCK_LABEL = "identity retention";

export const ORDER_COLUMNS: readonly DataColumn<OrderView>[] = [
  {
    id: "state",
    header: "state",
    isNumeric: false,
    width: "8.5rem",
    cell: (order) => <StatusPill state={order.state} />,
  },
  {
    id: "order",
    header: "order",
    isNumeric: false,
    width: "9rem",
    cell: (order) => <OrderRefChip orderId={order.id} />,
  },
  {
    id: "recipient",
    header: "recipient",
    isNumeric: false,
    width: "12rem",
    cell: (order) => (
      <NameText
        value={order.recipientName}
        fallback={
          <PurgedValue
            purgedAt={order.identityPurgedAt}
            isPurged={order.isIdentityPurged}
            clock={IDENTITY_CLOCK_LABEL}
          />
        }
      />
    ),
  },
  {
    id: "user",
    header: "user",
    isNumeric: false,
    width: "9rem",
    cell: (order) => (
      <TelegramUserChip
        telegramUserId={order.telegramUserId}
        telegramUserIdMasked={order.telegramUserIdMasked}
      />
    ),
  },
  {
    id: "paid",
    header: "paid",
    isNumeric: false,
    width: "4.5rem",
    cell: (order) => (
      <span className={order.isPaid ? "text-ink" : "text-ink-muted"}>
        {order.isPaid ? "yes" : "no"}
      </span>
    ),
  },
  {
    id: "assets",
    header: "assets",
    isNumeric: true,
    width: "5rem",
    cell: (order) => formatInteger(order.assetCount),
  },
  {
    id: "failure",
    header: "failure",
    isNumeric: false,
    width: "14rem",
    cell: (order) =>
      order.failedReason === null ? (
        <span className="text-ink-muted">{EMPTY_VALUE}</span>
      ) : (
        <ErrorCodeBadge
          code={order.failedReason}
          isRetryable={order.isFailedReasonRetryable}
          size="sm"
        />
      ),
  },
  {
    id: "createdAt",
    header: "created",
    isNumeric: true,
    width: "11rem",
    cell: (order) => <Timestamp at={order.createdAt} />,
  },
  {
    id: "updatedAt",
    header: "updated",
    isNumeric: true,
    width: "8rem",
    cell: (order) => <Timestamp at={order.updatedAt} relative />,
  },
];
