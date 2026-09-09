/**
 * `<UserPeekDrawer>` — a row on `/users`, opened without leaving `/users`.
 *
 * The list used to navigate on row activation, which is the wrong trade for the question this
 * screen answers. An operator working a filtered directory ("blocked, Russian, holding
 * credits") checks one person and goes back to the next; a route change throws away the
 * filters' scroll position and the keyset page, and the browser's back button restores the URL
 * but not the place in the table. The peek keeps every one of those, because nothing about the
 * table's state changes when it opens — the drawer is a sibling of the table, not a route.
 *
 * ## What it shows, and what it deliberately does not fetch
 *
 * The profile facts and the standing come from the `UserView` the table ALREADY
 * has. There is no `GET /users/{id}` here: the detail route adds `creditsProjected`,
 * `inFlightRenderCount` and the per-state breakdown, and every one of those belongs to the
 * question "why is this customer being refused a render" — which is the full record's job, and
 * the reason the footer links to it. A peek that refetched what it was handed would put a
 * spinner in front of facts already on screen behind it.
 *
 * Two things are worth a request, because the list row cannot carry them:
 *
 *  - the **ledger** (`GET /users/{id}/credits`), which is what turns "3 credits" into "comped
 *    by admin:dilnoza on Tuesday"; and
 *  - the customer's **last ten orders**, the other half of "who is this".
 *
 * Both are `enabled` only while the drawer is open, so scrolling a fifty-row table costs
 * nothing, and both are keyed under `queryKeys.users.*` so a grant made from this footer
 * invalidates them along with the row behind it.
 *
 * The ledger's response carries the ACCOUNT as well as the movements, and that is where the
 * balance and the lifetime total are read from — not from the row. The row is frozen at the
 * moment it was activated, so after a grant from the footer below it would still be saying
 * "never metered" under a ledger showing the grant. The row stands in only until the live
 * answer for this subject arrives.
 *
 * ## The title is the masked id
 *
 * `<Drawer>`'s title is its ACCESSIBLE NAME — read aloud, and outside `<NameText>`'s fence — so
 * it is our own masked identifier and never the customer's name. The name, where it exists,
 * sits in the body where the fence applies.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  getUserCredits,
  getUserOrders,
  unwrapAsync,
  type OrderView,
  type UserView,
} from "@/api";
import {
  DataTable,
  Timestamp,
  type DataColumn,
} from "@/components/data";
import {
  CreditBalanceChip,
  CreditLedgerTable,
  GrantCreditsButton,
  NameText,
  OrderRefChip,
  StatusPill,
  TelegramUserChip,
} from "@/components/domain";
import { AsyncBoundary, Drawer, Skeleton } from "@/components/util";
import { EMPTY_VALUE, formatInteger, humaniseEnum, queryKeys } from "@/lib";
import { href } from "@/routes";

import { PROFILE_STANDING_HINT, PROFILE_STANDING_LABEL, displayNameOf, profileStandingOf } from "./profile";

/** Ten orders and ten movements: a peek, not the full record's pager. */
export const PEEK_PAGE_LIMIT = 10;

export const OPEN_FULL_RECORD_LABEL = "Open full record";

export interface UserPeekDrawerProps {
  /** The activated row, or `null` when nothing is being peeked. */
  readonly user: UserView | null;
  readonly onClose: () => void;
}

export function UserPeekDrawer({ user, onClose }: UserPeekDrawerProps): ReactElement | null {
  /*
   * The row is KEPT after `user` goes null so the panel still has something to draw on its way
   * out. Unmounting the whole drawer the instant it closes would skip Radix's close-autofocus,
   * and that event is the one that puts the cursor back on the row the operator pressed Enter
   * on — the whole reason this is a drawer and not a route.
   */
  const [shown, setShown] = useState<UserView | null>(user);
  useEffect(() => {
    if (user !== null) setShown(user);
  }, [user]);

  const isOpen = user !== null;
  const telegramUserId = shown?.telegramUserId ?? null;

  /** Page one of the ledger. The drawer owns the cursor; the URL is the table's, not ours. */
  const [ledgerCursor, setLedgerCursor] = useState<string | null>(null);
  useEffect(() => {
    setLedgerCursor(null);
  }, [telegramUserId]);

  const ledgerQuery = { limit: PEEK_PAGE_LIMIT, cursor: ledgerCursor ?? undefined };
  const credits = useQuery({
    queryKey: queryKeys.users.credits(telegramUserId ?? 0, ledgerQuery),
    queryFn: ({ signal }) => unwrapAsync(getUserCredits(telegramUserId ?? 0, ledgerQuery, { signal })),
    enabled: isOpen && telegramUserId !== null,
  });

  const ordersQuery = { limit: PEEK_PAGE_LIMIT };
  const orders = useQuery({
    queryKey: queryKeys.users.orders(telegramUserId ?? 0, ordersQuery),
    queryFn: ({ signal }) => unwrapAsync(getUserOrders(telegramUserId ?? 0, ordersQuery, { signal })),
    enabled: isOpen && telegramUserId !== null,
  });

  if (shown === null) return null;

  /*
   * The account, preferred over the row the table handed us.
   *
   * The row is a snapshot taken when the operator pressed Enter and nothing re-derives it,
   * so a grant made from this drawer's own footer leaves it stale: the ledger below refetches
   * and shows the `+3`, while a header chip reading off `shown` still says "never metered"
   * and the lifetime fact still says "—". An operator who trusts the chip comps them twice.
   * `credits` is invalidated by that same grant and carries the account the write read back,
   * so it is the fresher of the two.
   *
   * `undefined` means no live answer for THIS subject yet — the query is loading, failed, or
   * (`placeholderData: keepPreviousData` being global) still holding the previous customer's
   * page — and only then does the row stand in. `null` is a live answer: never metered.
   */
  const account =
    credits.isSuccess && !credits.isPlaceholderData ? credits.data.account : undefined;
  const balance = account === undefined ? shown.creditBalance : (account?.balance ?? null);
  const lifetimeGranted =
    account === undefined ? shown.lifetimeCreditsGranted : (account?.lifetimeGranted ?? null);

  const orderItems = orders.data?.items ?? [];
  const displayName = displayNameOf(shown);
  const standing = profileStandingOf(shown);

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      testId="user-peek-drawer"
      widthClassName="max-w-2xl"
      title={`user ${shown.telegramUserIdMasked}`}
      description="A peek. The table behind this panel keeps its filters and its page."
      headerExtra={
        <>
          <TelegramUserChip
            telegramUserId={shown.telegramUserId}
            telegramUserIdMasked={shown.telegramUserIdMasked}
            isBlocked={shown.isBlocked}
          />
          <CreditBalanceChip balance={balance} size="md" />
        </>
      }
      footer={
        <>
          {/* The link, not a second copy of the detail page. Everything this drawer omits —
              the projection, the in-flight debits, the wizard session — is through here. */}
          <Link
            to={href.user(shown.telegramUserId)}
            data-testid="open-full-record"
            className="type-body-sm rounded-pill px-3 py-1.5 text-brand transition-colors duration-fast ease-standard hover:bg-brand-tint"
          >
            {OPEN_FULL_RECORD_LABEL}
          </Link>
          <GrantCreditsButton
            telegramUserId={shown.telegramUserId}
            subjectLabel={shown.telegramUserIdMasked}
            className="ml-auto"
          />
        </>
      }
    >
      <section className="flex flex-col gap-3" aria-label="profile">
        <h3 className="type-h3 text-ink">Profile</h3>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
          <PeekFact label="standing">
            <span title={PROFILE_STANDING_HINT[standing]}>{PROFILE_STANDING_LABEL[standing]}</span>
          </PeekFact>
          <PeekFact label="name">
            {/* Customer-written, so it reaches the DOM the one way such text may. */}
            {displayName === null ? (
              <span className="text-ink-muted">{EMPTY_VALUE}</span>
            ) : (
              <NameText value={displayName} />
            )}
          </PeekFact>
          <PeekFact label="@username">
            <NameText value={shown.telegramUsernameMasked} />
          </PeekFact>
          <PeekFact label="phone">
            {/* OUR mask, not customer content: `type-mono` is safe and the plaintext is on
                this wire at no role at all. */}
            {shown.phoneMasked === null ? (
              <span className="text-ink-muted">{EMPTY_VALUE}</span>
            ) : (
              <span className="type-mono">{shown.phoneMasked}</span>
            )}
          </PeekFact>
          <PeekFact label="language">{humaniseEnum(shown.uiLanguage)}</PeekFact>
          <PeekFact label="orders">
            <span className="num">{`${formatInteger(shown.orderCount)} (${formatInteger(shown.paidOrderCount)} paid)`}</span>
          </PeekFact>
          <PeekFact label="account created">
            <Timestamp at={shown.accountCreatedAt} />
          </PeekFact>
          <PeekFact label="last order">
            <Timestamp at={shown.lastOrderAt} />
          </PeekFact>
          <PeekFact label="lifetime granted">
            {/* `null` here is the same absent `credit_accounts` row the chip is naming, so it
                is a dash rather than a `0` that would claim nobody has ever comped them. */}
            {lifetimeGranted === null ? (
              <span className="text-ink-muted">{EMPTY_VALUE}</span>
            ) : (
              <span className="num">{formatInteger(lifetimeGranted)}</span>
            )}
          </PeekFact>
        </dl>
      </section>

      <section className="flex min-w-0 flex-col gap-3" aria-label="credit ledger">
        <h3 className="type-h3 text-ink">Credits</h3>
        <AsyncBoundary
          status={credits.status}
          hasData={credits.data !== undefined}
          error={credits.error}
          onRetry={() => {
            void credits.refetch();
          }}
          dataUpdatedAt={credits.dataUpdatedAt}
          noun="the credit ledger"
          skeleton={<Skeleton height="9rem" className="w-full rounded-card" />}
        >
          {/* `isSummaryHidden`: the balance chip is already in the header and the lifetime
              total is a fact above, so the table's own summary would be a third copy. */}
          <CreditLedgerTable
            page={credits.data}
            cursor={ledgerCursor}
            onCursorChange={setLedgerCursor}
            limit={PEEK_PAGE_LIMIT}
            isFetching={credits.isFetching}
            isSummaryHidden
          />
        </AsyncBoundary>
      </section>

      <section className="flex min-w-0 flex-col gap-3" aria-label="recent orders">
        <h3 className="type-h3 text-ink">{`Last ${String(PEEK_PAGE_LIMIT)} orders`}</h3>
        <AsyncBoundary
          status={orders.status}
          hasData={orders.data !== undefined}
          isEmpty={orderItems.length === 0}
          error={orders.error}
          onRetry={() => {
            void orders.refetch();
          }}
          dataUpdatedAt={orders.dataUpdatedAt}
          noun="orders"
          emptyTitle="No orders"
          emptyBody="This account has a users row — first contact writes one — and has confirmed nothing."
          skeleton={<Skeleton height="9rem" className="w-full rounded-card" />}
        >
          <DataTable
            label="this person's recent orders"
            data={orderItems}
            columns={PEEK_ORDER_COLUMNS}
            getRowId={(row) => row.id}
            isRefetching={orders.isFetching}
          />
        </AsyncBoundary>
      </section>
    </Drawer>
  );
}

/**
 * Four columns, not the detail screen's seven. A drawer is `max-w-2xl` and the failure code,
 * the recipient and the asset count all need width they cannot have here — they are on the
 * full record, one click away, rather than squeezed until they truncate.
 */
const PEEK_ORDER_COLUMNS: readonly DataColumn<OrderView>[] = [
  {
    id: "order",
    header: "order",
    isNumeric: false,
    width: "10rem",
    cell: (row) => <OrderRefChip orderId={row.id} />,
  },
  {
    id: "state",
    header: "state",
    isNumeric: false,
    width: "9rem",
    cell: (row) => <StatusPill state={row.state} />,
  },
  {
    id: "isPaid",
    header: "paid",
    isNumeric: false,
    width: "4.5rem",
    cell: (row) => (row.isPaid ? "yes" : "no"),
  },
  {
    id: "createdAt",
    header: "created",
    isNumeric: false,
    cell: (row) => <Timestamp at={row.createdAt} />,
  },
];

/** One `<dt>`/`<dd>` pair, in the drawer's smaller type. */
function PeekFact({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="type-caption text-ink-muted">{label}</dt>
      <dd className="type-body-sm min-w-0 text-ink">{children}</dd>
    </div>
  );
}
