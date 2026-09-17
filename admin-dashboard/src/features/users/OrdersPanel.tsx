/**
 * This customer's orders: the per-state breakdown from the user record, and one keyset page of
 * the orders themselves.
 *
 * ## No reveal control in the table
 *
 * `recipientName` is masked and the brief behind it CAN be revealed — but not from here, and
 * that is a decision rather than an omission. A reveal button per row offers the same charged,
 * audited disclosure from eight places at once and makes it easy to unmask the wrong order's
 * recipient while reading the right one's reference. `POST /api/reveal` takes an ORDER subject,
 * so the affordance belongs on a screen that is about one order. What this table owes the
 * operator is the mask, and the purge stamp when the clock has already run.
 *
 * ## The two counts are not derivable from the bar
 *
 * `ordersByState` omits states with no orders (never zero-filled), and `deliveredOrderCount` /
 * `failedOrderCount` are counted server-side over the whole history — not over this page. They
 * are shown beside the bar rather than under the table for that reason.
 *
 * ## `withTotal`
 *
 * Asked for, because "3 of 41" is the difference between a customer who ordered once and one
 * who has been ordering for a year. The server caps its count; `rangeLabelOf` prints a capped
 * total with a `+` rather than as an exact figure.
 */

import { useMemo, type JSX } from "react";

import { DEFAULT_PAGE_LIMIT, nextCursorOf } from "@/api/pagination";
import type { OrderState, OrderStateCount, OrderView } from "@/api/users";
import { Badge, type BadgeTone } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import {
  MONO_CLASS,
  PANEL_NOTE_CLASS,
  Panel,
  PurgedValue,
  QueryErrorNote,
  SectionHeading,
  rangeLabelOf,
  useCursorStack,
} from "./detailKit";
import { formatInteger, formatTimestamp, humaniseEnum, shortId } from "./detailFormat";
import { useUserOrders } from "./useUsers";

/** The bar's swatch per state. Every segment also carries its name and count in the legend. */
const STATE_SWATCH: Readonly<Record<OrderState, string>> = {
  draft: "bg-d6",
  brief_ready: "bg-d5",
  lyrics_ready: "bg-d4",
  authorized: "bg-d2",
  generating: "bg-warn",
  delivered: "bg-accent",
  failed: "bg-required",
  cancelled: "bg-d3",
};

/** The table's pill per state. The WORD carries the meaning; the ground only groups. */
const STATE_TONE: Readonly<Record<OrderState, BadgeTone>> = {
  draft: "neutral",
  brief_ready: "neutral",
  lyrics_ready: "neutral",
  authorized: "warning",
  generating: "warning",
  delivered: "accent",
  failed: "danger",
  cancelled: "muted",
};

export interface OrdersPanelProps {
  /** `null` disables the query — the subject is not known yet. */
  readonly telegramUserId: number | null;
  /** From the user record. `undefined` while it loads or after it failed. */
  readonly ordersByState?: readonly OrderStateCount[] | undefined;
  readonly deliveredOrderCount?: number | undefined;
  readonly failedOrderCount?: number | undefined;
}

export function OrdersPanel({
  telegramUserId,
  ordersByState,
  deliveredOrderCount,
  failedOrderCount,
}: OrdersPanelProps): JSX.Element {
  const { t } = useI18n();
  const page = useCursorStack();
  const orders = useUserOrders(telegramUserId, {
    limit: DEFAULT_PAGE_LIMIT,
    cursor: page.cursor,
    withTotal: true,
  });

  const items = orders.data?.items ?? [];
  const nextCursor = orders.data === undefined ? null : nextCursorOf(orders.data);

  const columns = useMemo<readonly Column<OrderView>[]>(
    () => [
      {
        key: "order",
        header: t("users.ordersPanel.order"),
        width: "12rem",
        render: (row) => (
          <span className="flex flex-col gap-0.5">
            <span className={MONO_CLASS} title={row.id}>
              {shortId(row.id)}
            </span>
            <span className={cn(CELL_SECONDARY_CLASS, MONO_CLASS)} title={t("audit.table.correlation")}>
              {row.correlationId}
            </span>
          </span>
        ),
      },
      {
        key: "state",
        header: t("users.orders.state"),
        width: "8rem",
        render: (row) => <Badge tone={STATE_TONE[row.state]}>{humaniseEnum(row.state)}</Badge>,
      },
      {
        key: "recipient",
        header: t("users.orders.recipient"),
        width: "10rem",
        render: (row) => (
          <PurgedValue
            purgedAt={row.identityPurgedAt}
            isPurged={row.isIdentityPurged}
            clock="identity retention"
          >
            {/* Masked, and revealed only from an order's own screen — see the header note. */}
            {row.recipientName === null ? (
              <span className="text-ink-400">—</span>
            ) : (
              <span className="break-words">{row.recipientName}</span>
            )}
          </PurgedValue>
        ),
      },
      {
        key: "paid",
        header: t("users.orders.paid"),
        width: "8rem",
        render: (row) => (
          <span className="flex flex-col gap-0.5">
            <span>{row.isPaid ? "yes" : "no"}</span>
            <span className={CELL_SECONDARY_CLASS}>
              {`${humaniseEnum(row.ledgerStatus)} · ${humaniseEnum(row.paymentRail)}`}
            </span>
          </span>
        ),
      },
      {
        key: "cost",
        header: t("users.ordersPanel.credits"),
        width: "5rem",
        align: "right",
        render: (row) => formatInteger(row.creditCost),
      },
      {
        key: "assets",
        header: t("users.ordersPanel.assets"),
        width: "5rem",
        align: "right",
        render: (row) => formatInteger(row.assetCount),
      },
      {
        key: "failure",
        header: t("users.orders.failure"),
        width: "12rem",
        render: (row) =>
          row.failedReason === null ? (
            <span className="text-ink-400">—</span>
          ) : (
            <span className="flex flex-col gap-0.5">
              <Badge tone="danger" title={row.failedReason}>
                {row.failedReason}
              </Badge>
              {/* Tri-state on purpose: nobody decided is not the same as "terminal". */}
              <span className={CELL_SECONDARY_CLASS}>
                {row.isFailedReasonRetryable === null
                  ? "retryable: not recorded"
                  : row.isFailedReasonRetryable
                    ? "retryable"
                    : "terminal"}
              </span>
            </span>
          ),
      },
      {
        key: "created",
        header: t("users.orders.created"),
        width: "11rem",
        render: (row) => (
          <span className="flex flex-col gap-0.5">
            <span>{formatTimestamp(row.createdAt)}</span>
            <span className={CELL_SECONDARY_CLASS}>
              {row.retryCount === 0
                ? "no retries"
                : `${formatInteger(row.retryCount)} ${row.retryCount === 1 ? "retry" : "retries"}`}
            </span>
          </span>
        ),
      },
      {
        key: "delivered",
        header: t("users.ordersPanel.delivered"),
        width: "11rem",
        render: (row) =>
          row.deliveredAt === null ? (
            <span className="text-ink-400">—</span>
          ) : (
            formatTimestamp(row.deliveredAt)
          ),
      },
    ],
    [t],
  );

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-label="orders">
      <SectionHeading>{t("users.orders.title")}</SectionHeading>

      <Panel ariaLabel="orders by state">
        <StateBreakdown
          counts={ordersByState}
          deliveredOrderCount={deliveredOrderCount}
          failedOrderCount={failedOrderCount}
        />
      </Panel>

      {orders.error === null ? null : (
        <QueryErrorNote
          error={orders.error}
          noun={t("users.ordersPanel.noun")}
          onRetry={() => {
            void orders.refetch();
          }}
          isRetrying={orders.isFetching}
        />
      )}

      {/* `isLoading` rather than `isPending`: a disabled query stays "pending" for ever, and a
          table shimmering with no request in flight reads as a hang. */}
      <DataTable
        caption={t("users.ordersPanel.caption")}
        columns={columns}
        rows={items}
        getRowKey={(row) => row.id}
        isLoading={orders.isLoading}
        skeletonRows={DEFAULT_PAGE_LIMIT}
        /* Dimmed rather than blanked while the next page is in flight: what is on screen is
           still the previous answer, and presenting it as this one is the failure a table
           cannot recover from, because nothing looks wrong. */
        className={orders.isPlaceholderData ? "opacity-60 transition-opacity" : undefined}
        emptyMessage={
          <EmptyState
            title={t("users.ordersPanel.nonePage")}
            message={
              page.hasPrev
                ? t("users.ordersPanel.goBackPage")
                : t("users.ordersPanel.neverConfirmed")
            }
          />
        }
      />

      <CursorPager
        hasPrev={page.hasPrev}
        hasNext={nextCursor !== null}
        isFetching={orders.isFetching}
        onPrev={page.toPrev}
        onNext={
          nextCursor === null
            ? undefined
            : () => {
                page.toNext(nextCursor);
              }
        }
        rangeLabel={rangeLabelOf(page.pageIndex, DEFAULT_PAGE_LIMIT, items.length, orders.data?.meta)}
      />
    </section>
  );
}

/**
 * The distribution, plus the two whole-history counts.
 *
 * `ordersByState` lists only the states that have at least one order, so the bar is built from
 * what is there rather than from the eight-member enum — a zero-width segment for every state
 * this customer never reached would be six invisible legend entries.
 */
function StateBreakdown({
  counts,
  deliveredOrderCount,
  failedOrderCount,
}: {
  readonly counts: readonly OrderStateCount[] | undefined;
  readonly deliveredOrderCount: number | undefined;
  readonly failedOrderCount: number | undefined;
}): JSX.Element {
  if (counts === undefined) {
    return (
      <p className={PANEL_NOTE_CLASS}>
        The per-state breakdown is part of the user record, which has not loaded. The table below
        is a separate request and may still be readable.
      </p>
    );
  }

  const total = counts.reduce((sum, entry) => sum + entry.count, 0);

  if (total === 0) {
    return <p className={PANEL_NOTE_CLASS}>No orders in any state.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        className="flex h-2 w-full overflow-hidden rounded-pill bg-bg"
        role="img"
        aria-label={counts
          .map((entry) => `${humaniseEnum(entry.state)}: ${formatInteger(entry.count)}`)
          .join(", ")}
      >
        {counts.map((entry) => (
          <span
            key={entry.state}
            className={STATE_SWATCH[entry.state]}
            style={{ width: `${String((entry.count / total) * 100)}%` }}
          />
        ))}
      </div>

      <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-2 p-0">
        {counts.map((entry) => (
          <li key={entry.state} className="flex items-center gap-2">
            <span aria-hidden className={cn("h-2 w-2 rounded-full", STATE_SWATCH[entry.state])} />
            <span className="text-[12px] leading-4 text-ink-800">
              {`${humaniseEnum(entry.state)} ${formatInteger(entry.count)}`}
            </span>
          </li>
        ))}
      </ul>

      <p className={PANEL_NOTE_CLASS}>
        {`${formatInteger(deliveredOrderCount ?? 0)} delivered and ${formatInteger(failedOrderCount ?? 0)} failed over the whole history — counted by the server, not from the page below.`}
      </p>
    </div>
  );
}
