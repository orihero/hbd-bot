/**
 * `/users/:telegramUserId` — "What happened to my song?" (§11.2)
 *
 * ## The banner is the screen
 *
 * §11.2's dominant signal is "Full-width banner: status of their most recent order". Support
 * is on the phone with somebody whose song has not arrived; the answer is one order's state,
 * and it must be readable before the eye reaches a table. So the banner reads from its OWN
 * query — `GET /users/{tg}/orders?limit=1` — and not from `items[0]` of the paged list
 * below. Page two of that list starts with an order that is not the most recent one, and a
 * banner that changes meaning when somebody clicks "next" is worse than no banner.
 *
 * ## The route key is the INTEGER telegram id
 *
 * `:telegramUserId`, never `users.id`. `UserView` carries both and only the integer is a
 * route key (contract D3/D10). The integer is used to build requests and links and is never
 * drawn — `telegramUserIdMasked` is what reaches the DOM, through `<TelegramUserChip>`.
 *
 * ## Polling (§11.5)
 *
 * The banner polls at 3 s while the order is in flight (`authorized`, `generating`) and not
 * at all otherwise — the same rule §11.5 gives order detail, because during that call this
 * banner *is* an order detail. The order list polls at the orders-list interval. The
 * per-state breakdown and the wizard draft are on demand.
 *
 * ## The shape of the page
 *
 * Header → "Most recent order" (the hero card) → "Orders" (the distribution bar and the
 * table) → the wizard aside. Each group carries a plain section label above its cards, and
 * the cards separate themselves with `--shadow-card`; there is not a border on this screen.
 *
 * The banner is a full card of its own rather than a strip, because §11.2's signal is what
 * support reads aloud and the reskin's answer to "make this the loudest thing" is size and
 * air, not a rule around it. Everything below it is narrower or quieter.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { z } from "zod";

import {
  DEFAULT_PAGE_LIMIT,
  IN_FLIGHT_ORDER_STATES,
  MAX_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  getUser,
  getUserOrders,
  getWizardState,
  unwrapAsync,
  type OrderView,
  type PageQuery,
} from "@/api";
import {
  CursorPager,
  DataTable,
  StateDistributionBar,
  TimeZoneCaption,
  Timestamp,
  type DataColumn,
} from "@/components/data";
import {
  BRIEF_REVEAL_FIELDS,
  ErrorCodeBadge,
  NameText,
  OrderRefChip,
  PurgedValue,
  RevealButton,
  StatusPill,
  TelegramUserChip,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import {
  AsyncBoundary,
  buttonVariants,
  EmptyState,
  PermissionGate,
  Skeleton,
  SkeletonTable,
  SkeletonText,
} from "@/components/util";
import {
  EMPTY_VALUE,
  POLL_MS,
  formatInteger,
  humaniseEnum,
  pollWhileVisible,
  queryKeys,
  useSearchParamsState,
  usePrefsStore,
  zIntParam,
  zStringParam,
  type SearchParamsSchema,
} from "@/lib";
import { href } from "@/routes";

import { WizardStatePanel } from "./WizardStatePanel";

/** Only paging lives in the URL here — the subject is the path parameter. */
const userOrdersFilterSchema = z.object({
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
  cursor: zStringParam,
}) satisfies SearchParamsSchema<UserOrdersFilters>;

/** The codecs' OUTPUT. See the long note in `UsersScreen.tsx` for why it is not inferred. */
type UserOrdersFilters = {
  limit?: number | undefined;
  cursor?: string | undefined;
};

const USER_ORDERS_FALLBACK: UserOrdersFilters = {};

/** The banner's query: the single most recent order. */
const LATEST_ORDER_QUERY: PageQuery = { limit: MIN_PAGE_LIMIT };

export function UserDetailScreen(): ReactElement {
  const params = useParams<{ telegramUserId: string }>();
  const density = usePrefsStore((state) => state.density);
  const paging = useSearchParamsState(userOrdersFilterSchema, USER_ORDERS_FALLBACK);
  const { value, patch } = paging;

  /*
   * The route parameter is a string until proven otherwise. A hand-edited URL must produce a
   * legible refusal rather than `/api/users/NaN/orders`, which is a 422 the operator cannot
   * act on.
   */
  const raw = params.telegramUserId ?? "";
  const telegramUserId = /^\d+$/.test(raw) ? Number(raw) : null;

  const ordersQuery = useMemo<PageQuery>(
    () => ({
      limit: value.limit ?? DEFAULT_PAGE_LIMIT,
      cursor: value.cursor,
      withTotal: true,
    }),
    [value],
  );

  const isEnabled = telegramUserId !== null;
  const id = telegramUserId ?? 0;

  const latest = useQuery({
    queryKey: queryKeys.users.orders(id, LATEST_ORDER_QUERY),
    queryFn: ({ signal }) => unwrapAsync(getUserOrders(id, LATEST_ORDER_QUERY, { signal })),
    enabled: isEnabled,
    refetchInterval: (query) => {
      const state = query.state.data?.items[0]?.state;
      const isInFlight = state !== undefined && IN_FLIGHT_ORDER_STATES.includes(state);
      return pollWhileVisible(isInFlight ? POLL_MS.orderDetail : false)();
    },
  });

  const detail = useQuery({
    queryKey: queryKeys.users.detail(id),
    queryFn: ({ signal }) => unwrapAsync(getUser(id, { signal })),
    enabled: isEnabled,
  });

  const orders = useQuery({
    queryKey: queryKeys.users.orders(id, ordersQuery),
    queryFn: ({ signal }) => unwrapAsync(getUserOrders(id, ordersQuery, { signal })),
    enabled: isEnabled,
    refetchInterval: pollWhileVisible(POLL_MS.ordersList),
  });

  const wizard = useQuery({
    queryKey: queryKeys.users.wizardState(id),
    queryFn: ({ signal }) => unwrapAsync(getWizardState(id, { signal })),
    enabled: isEnabled,
  });

  const columns = useMemo<readonly DataColumn<OrderView>[]>(
    () => [
      {
        id: "order",
        header: "order",
        isNumeric: false,
        width: "13rem",
        cell: (row) => <OrderRefChip orderId={row.id} state={row.state} />,
      },
      {
        id: "state",
        header: "state",
        isNumeric: false,
        width: "10rem",
        cell: (row) => <StatusPill state={row.state} />,
      },
      {
        id: "recipient",
        header: "recipient",
        isNumeric: false,
        width: "10rem",
        cell: (row) => (
          <PurgedValue
            purgedAt={row.identityPurgedAt}
            isPurged={row.isIdentityPurged}
            clock="identity retention"
          >
            <NameText value={row.recipientName} />
          </PurgedValue>
        ),
      },
      {
        id: "isPaid",
        header: "paid",
        isNumeric: false,
        width: "5rem",
        cell: (row) => (row.isPaid ? "yes" : "no"),
      },
      {
        id: "assetCount",
        header: "assets",
        isNumeric: true,
        width: "5rem",
        cell: (row) => formatInteger(row.assetCount),
      },
      {
        id: "failure",
        header: "failure",
        isNumeric: false,
        width: "14rem",
        /* `<ErrorCodeBadge code={null}>` is a real badge — it groups failures whose writer
           recorded no code. A delivered order has no failure at all, which is a different
           fact and renders as the em dash. */
        cell: (row) =>
          row.failedReason === null ? (
            <span className="text-ink-muted">{EMPTY_VALUE}</span>
          ) : (
            <ErrorCodeBadge code={row.failedReason} isRetryable={row.isFailedReasonRetryable} />
          ),
      },
      {
        id: "createdAt",
        header: (
          <span>
            created <TimeZoneCaption />
          </span>
        ),
        isNumeric: false,
        width: "12rem",
        cell: (row) => <Timestamp at={row.createdAt} />,
      },
      {
        id: "deliveredAt",
        header: (
          <span>
            delivered <TimeZoneCaption />
          </span>
        ),
        isNumeric: false,
        width: "12rem",
        cell: (row) => <Timestamp at={row.deliveredAt} />,
      },
    ],
    [],
  );

  if (telegramUserId === null) {
    return (
      <div className="flex min-h-0 flex-col">
        <PageHeader title="user" description="What happened to my song?" />
        <section className="px-gutter pb-gutter">
          {/*
            The design's shape for an absence, composed rather than hand-rolled: a centred
            card, a glyph, a short line, one pill button. `EmptyState` already is that card,
            so this branch does not invent a second one.

            `raw` is whatever was in the URL bar. It reaches the DOM as a text child and
            nothing else — no `dangerouslySetInnerHTML`, no attribute, and no folding: it is
            quoted back verbatim so an operator can see the character that broke the route.
          */}
          <EmptyState
            glyph="⊘"
            title="That is not a user id"
            body={`“${raw}” is not a Telegram user id.`}
            action={
              <Link
                className={buttonVariants({ variant: "primary", shape: "pill" })}
                to={href.users()}
              >
                Back to users
              </Link>
            }
          />
        </section>
      </div>
    );
  }

  const user = detail.data?.user;
  const latestOrder = latest.data?.items[0] ?? null;
  const items = orders.data?.items ?? [];

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        title="user"
        description="What happened to my song?"
        signal={
          user === undefined ? null : (
            <div className="flex flex-col items-end gap-1">
              <TelegramUserChip
                telegramUserId={user.telegramUserId}
                telegramUserIdMasked={user.telegramUserIdMasked}
                isBlocked={user.isBlocked}
              />
              <span className="type-body-sm num text-ink-muted">
                {`${formatInteger(user.orderCount)} orders · ${formatInteger(user.paidOrderCount)} paid · ${humaniseEnum(user.uiLanguage)}`}
              </span>
            </div>
          )
        }
      />

      {/* §11.2's dominant signal: full width, above everything, one order's status. */}
      <section
        className="flex flex-col gap-3 px-gutter pb-6"
        aria-label="most recent order"
      >
        <h2 className="type-h3 text-ink">Most recent order</h2>
        <AsyncBoundary
          status={latest.status}
          hasData={latest.data !== undefined}
          isEmpty={latestOrder === null}
          error={latest.error}
          onRetry={() => {
            void latest.refetch();
          }}
          dataUpdatedAt={latest.dataUpdatedAt}
          noun="the most recent order"
          emptyTitle="No orders yet"
          emptyBody="This person has a users row, so an order was confirmed at some point — but none is readable now."
          skeleton={<Skeleton height="9.5rem" className="w-full rounded-card" />}
        >
          {latestOrder === null ? null : <LatestOrderBanner order={latestOrder} />}
        </AsyncBoundary>
      </section>

      <div className="grid grid-cols-1 gap-gutter px-gutter pb-gutter xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="flex min-w-0 flex-col gap-3" aria-label="orders">
          <h2 className="type-h3 text-ink">Orders</h2>
          <AsyncBoundary
            status={detail.status}
            hasData={detail.data !== undefined}
            isEmpty={(detail.data?.ordersByState.length ?? 0) === 0}
            error={detail.error}
            onRetry={() => {
              void detail.refetch();
            }}
            dataUpdatedAt={detail.dataUpdatedAt}
            noun="the state breakdown"
            emptyTitle="No orders to break down"
            skeleton={<Skeleton height="5.5rem" className="w-full rounded-card" />}
          >
            {detail.data === undefined ? null : (
              /* The bar has no card of its own — it is an 8px track and a legend — so it
                 gets one here, at the same 28px radius as everything else on the page. */
              <div className="rounded-card bg-surface-card p-card shadow-card">
                <StateDistributionBar
                  counts={detail.data.ordersByState}
                  label="this person's orders by state"
                  isRefetching={detail.isFetching}
                />
              </div>
            )}
          </AsyncBoundary>

          <AsyncBoundary
            status={orders.status}
            hasData={orders.data !== undefined}
            isEmpty={items.length === 0}
            error={orders.error}
            onRetry={() => {
              void orders.refetch();
            }}
            dataUpdatedAt={orders.dataUpdatedAt}
            noun="orders"
            emptyTitle="No orders"
            skeleton={<SkeletonTable rows={6} columns={columns.length} density={density} />}
          >
            <DataTable
              label="this person's orders"
              data={items}
              columns={columns}
              getRowId={(row) => row.id}
              isRefetching={orders.isFetching}
              footer={
                <CursorPager
                  label="orders"
                  meta={orders.data?.meta}
                  itemCount={items.length}
                  cursor={value.cursor ?? null}
                  onCursorChange={(cursor) => {
                    patch({ cursor: cursor ?? undefined }, { keepCursor: true });
                  }}
                  limit={value.limit ?? DEFAULT_PAGE_LIMIT}
                  onLimitChange={(limit) => {
                    patch({ limit });
                  }}
                  isFetching={orders.isFetching}
                />
              }
            />
          </AsyncBoundary>
        </section>

        {/*
          Its own permission (`wizard_state.read`), on its own router server-side. The gate
          mirrors that so a role without the cell never sees the panel rather than seeing it
          fail — §11.4's rule is hiding, not disabling.
        */}
        <PermissionGate permission="wizard_state.read">
          <aside className="flex flex-col gap-3" aria-label="wizard session">
            <h2 className="type-h3 text-ink">Wizard session</h2>
            <AsyncBoundary
              status={wizard.status}
              hasData={wizard.data !== undefined}
              error={wizard.error}
              onRetry={() => {
                void wizard.refetch();
              }}
              dataUpdatedAt={wizard.dataUpdatedAt}
              noun="the wizard session"
              skeleton={
                <div className="rounded-card bg-surface-card p-card shadow-card">
                  <SkeletonText lines={5} />
                </div>
              }
            >
              {wizard.data === undefined ? null : <WizardStatePanel state={wizard.data} />}
            </AsyncBoundary>
          </aside>
        </PermissionGate>
      </div>
    </div>
  );
}

/**
 * The banner itself — the reskin's hero card.
 *
 * §11.2 asks for "a full-width banner: status of their most recent order", and this design
 * says "loudest" with size, air and a 28px card rather than with a rule around a strip. So:
 * one row of identity (the `md` status pill, the order reference, the reveal), then the
 * facts as a label/value grid with generous gutters. It is the one thing on the screen
 * support reads aloud on the phone, and it should be readable from across a desk.
 *
 * No border anywhere: `--surface-card` plus `--shadow-card` is the whole separation from the
 * page ground, which is what every other card on the console does.
 *
 * The failure badge is present whenever `failedReason` is — `isRetryable` is tri-state and
 * `<ErrorCodeBadge>` already renders "unknown" as an absent decision rather than as
 * "terminal".
 */
function LatestOrderBanner({ order }: { readonly order: OrderView }): ReactElement {
  return (
    <article
      data-testid="latest-order-banner"
      data-state={order.state}
      className="flex w-full flex-col gap-6 rounded-card bg-surface-card p-card shadow-card"
    >
      <header className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <StatusPill state={order.state} size="md" />
        <OrderRefChip orderId={order.id} />

        {/*
          The reveal belongs HERE rather than in the orders table below, and the reason is the
          subject: `POST /api/reveal` takes an ORDER id, and this banner is the one order on
          the screen an operator is certainly talking about — §11.2 put it here precisely
          because it is what support reads aloud on the call. A reveal control per table row
          would offer the same charge from eight places at once and make it easy to unmask the
          wrong order's recipient while reading the right one's reference.

          `PermissionGate` is inside `RevealButton`: a VIEWER sees nothing at all (§11.4).
        */}
        <span className="ml-auto">
          <RevealButton
            subjectType="order"
            subjectId={order.id}
            subjectLabel={`${order.id.slice(0, 8)}\u2026`}
            fields={BRIEF_REVEAL_FIELDS}
            label="Reveal this order's brief"
          />
        </span>
      </header>

      <dl className="grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-3 xl:grid-cols-5">
        <BannerFact label="recipient">
          <PurgedValue
            purgedAt={order.identityPurgedAt}
            isPurged={order.isIdentityPurged}
            clock="identity retention"
          >
            <NameText value={order.recipientName} isToggleable />
          </PurgedValue>
        </BannerFact>

        <BannerFact label="created">
          <Timestamp at={order.createdAt} />
        </BannerFact>

        <BannerFact label="delivered">
          {order.deliveredAt === null ? (
            <span className="text-ink-muted">{EMPTY_VALUE}</span>
          ) : (
            <Timestamp at={order.deliveredAt} />
          )}
        </BannerFact>

        <BannerFact label="paid">{order.isPaid ? "yes" : "no"}</BannerFact>

        {order.failedReason === null ? null : (
          <BannerFact label="failure">
            <ErrorCodeBadge
              code={order.failedReason}
              isRetryable={order.isFailedReasonRetryable}
              size="md"
            />
          </BannerFact>
        )}
      </dl>
    </article>
  );
}

/**
 * One label/value pair in the hero card.
 *
 * The label is `--ink-muted` at 13px and the value is `--ink` at 14px — both clear the text
 * bar. `.type-caption` is deliberately NOT used here: it uppercases, and one of these values
 * is a recipient's name, where a `text-transform` would alter the mark the whole `NameText`
 * fence exists to preserve. Keeping the label class off the caption scale means nobody has
 * to remember which of these `<div>`s is safe to restyle.
 */
function BannerFact({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="type-body-sm text-ink-muted">{label}</dt>
      <dd className="type-body text-ink">{children}</dd>
    </div>
  );
}

export const Component = UserDetailScreen;
