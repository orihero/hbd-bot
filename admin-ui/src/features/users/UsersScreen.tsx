/**
 * `/users` — "Who are they and are they blocked?" (§11.2)
 *
 * ## The column header reads "last order"
 *
 * `UserView` has no `lastSeenAt` and this screen must not invent one. `users.last_seen_at`
 * is written by `repository._ensure_user`, which is called only from `_create_order`, so it
 * advances when an order is *created* and at no other moment — and somebody who walks the
 * whole wizard and never confirms has no `users` row at all. A column headed "last seen"
 * would be a claim about presence read off a measurement of purchases. §11.2 pins the string
 * until Phase 3's inbound middleware gives the column a real writer, §14 makes it an
 * acceptance criterion, and `LAST_ORDER_COLUMN_LABEL` is the one place it is spelled.
 *
 * ## The dominant signal
 *
 * "Total users + 30-day new-user sparkline." Both come from `GET /api/users`, because no
 * accounts-per-day metric exists (see `newUsers.ts`):
 *
 *  - the total is a `?withTotal=true&limit=1` probe — an unfiltered count, deliberately not
 *    the filtered one the pager already shows at the foot of the table;
 *  - the sparkline is one 30-day page folded into daily buckets, and is DROPPED rather than
 *    truncated when the page did not reach the end of the window.
 *
 * ## Polling
 *
 * None. §11.5 puts this surface in "everything else: on demand + `refetchOnWindowFocus`",
 * which the shared client already switches on. A user list does not move fast enough to
 * justify a timer, and the three queries here would be three of them.
 *
 * ## The shape of the page
 *
 * Header (title, breadcrumb, the question, the dominant signal) → the filter card → one
 * section label → the table card. The tile stays in `PageHeader`'s `signal` slot rather than
 * moving into the body: §11.2 requires it to be the first thing the eye reaches, and a stats
 * row below the filters is a row the filters can push off the fold.
 *
 * Nothing here draws a border. `StatTile`, `FilterBar` and `DataTable` each bring their own
 * 28px card and `--shadow-card`, so this file supplies only the gutter, the vertical rhythm
 * and the section label — wrapping any of them in a panel of its own would render a card
 * inside a card.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import {
  DEFAULT_PAGE_LIMIT,
  LANGUAGE_VALUES,
  LAST_ORDER_COLUMN_LABEL,
  MAX_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  getUsers,
  unwrapAsync,
  type Language,
  type UserView,
  type UsersQuery,
} from "@/api";
import {
  CursorPager,
  DataTable,
  FilterBar,
  StatTile,
  TimeRangePicker,
  TimeZoneCaption,
  Timestamp,
  buildFilterChips,
  type DataColumn,
  type TimeRange,
} from "@/components/data";
import { TelegramUserChip } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, SkeletonTable } from "@/components/util";
import {
  formatInteger,
  formatTotal,
  humaniseEnum,
  queryKeys,
  useSearchParamsState,
  usePrefsStore,
  zBoolParam,
  zEnumList,
  zInstantParam,
  zIntParam,
  zStringParam,
  type SearchParamsSchema,
} from "@/lib";
import { href } from "@/routes";

import { EnumToggleGroup, TriStateSelect } from "./filterControls";
import { NEW_USER_WINDOW_DAYS, buildNewUserSeries, newUserWindow } from "./newUsers";

/**
 * §6.6's filter set for `/api/users`, as URL parameters.
 *
 * Module scope, not inside the component: `useSearchParamsState` memoises on the schema's
 * identity, and a schema rebuilt every render would reparse the URL every render.
 */
const usersFilterSchema = z.object({
  telegramUserId: zIntParam({ min: 1 }),
  isBlocked: zBoolParam,
  uiLanguage: zEnumList(LANGUAGE_VALUES),
  from: zInstantParam,
  to: zInstantParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
  cursor: zStringParam,
}) satisfies SearchParamsSchema<UsersFilters>;

/**
 * What the codecs PARSE TO, written out rather than inferred.
 *
 * `useSearchParamsState` takes a `z.ZodType<T>`, and zod's third type parameter defaults to
 * the second — so `ZodType<T>` is a schema whose input and output are both `T`. Every codec
 * in `searchParams.ts` is a transform (`"50"` → `50`, `"true"` → `true`), so inference off
 * the schema alone unifies on the *input* union and hands the screen a `limit` of
 * `string | number`. Naming the output here is what keeps `listQuery` typed, and the
 * assertion above is the one place the mismatch is acknowledged. A `type`, not an
 * `interface`: only a type alias satisfies the hook's `Record<string, unknown>` bound.
 */
type UsersFilters = {
  telegramUserId?: number | undefined;
  isBlocked?: boolean | undefined;
  uiLanguage?: Language[] | undefined;
  from?: string | undefined;
  to?: string | undefined;
  limit?: number | undefined;
  cursor?: string | undefined;
};

const USERS_FILTER_FALLBACK: UsersFilters = {};

/** The unfiltered count behind the dominant signal. One row, for its `meta.total`. */
const TOTAL_PROBE: UsersQuery = { limit: MIN_PAGE_LIMIT, withTotal: true };

export function UsersScreen(): ReactElement {
  const navigate = useNavigate();
  const density = usePrefsStore((state) => state.density);
  const filters = useSearchParamsState(usersFilterSchema, USERS_FILTER_FALLBACK);
  const { value, patch } = filters;

  const listQuery = useMemo<UsersQuery>(
    () => ({
      telegramUserId: value.telegramUserId,
      isBlocked: value.isBlocked,
      uiLanguage: value.uiLanguage,
      from: value.from,
      to: value.to,
      limit: value.limit ?? DEFAULT_PAGE_LIMIT,
      cursor: value.cursor,
      withTotal: true,
    }),
    [value],
  );

  /*
   * Pinned once per mount. A window recomputed on every render would change the query key on
   * every render, and `to` recomputed per request would widen the filter between pages.
   */
  const sparkWindow = useMemo(() => newUserWindow(), []);
  const newUserQueryInput = useMemo<UsersQuery>(
    () => ({ from: sparkWindow.from, to: sparkWindow.to, limit: MAX_PAGE_LIMIT, withTotal: true }),
    [sparkWindow],
  );

  const users = useQuery({
    queryKey: queryKeys.users.list(listQuery),
    queryFn: ({ signal }) => unwrapAsync(getUsers(listQuery, { signal })),
  });

  const total = useQuery({
    queryKey: queryKeys.users.list(TOTAL_PROBE),
    queryFn: ({ signal }) => unwrapAsync(getUsers(TOTAL_PROBE, { signal })),
  });

  const newUsers = useQuery({
    queryKey: queryKeys.users.list(newUserQueryInput),
    queryFn: ({ signal }) => unwrapAsync(getUsers(newUserQueryInput, { signal })),
  });

  const items = users.data?.items ?? [];

  /*
   * Newest account first, so a page that did not reach the end of the window covers the most
   * recent days and drops the older ones. Drawing that would be a cliff nobody caused.
   */
  const page = newUsers.data;
  const series = useMemo(
    () =>
      page !== undefined && page.meta.nextCursor === null
        ? buildNewUserSeries(page.items, sparkWindow)
        : null,
    [page, sparkWindow],
  );
  const newInWindow = newUsers.data?.items.length ?? null;

  const chips = useMemo(
    () =>
      buildFilterChips(filters, [
        { key: "telegramUserId", label: "telegram id" },
        { key: "isBlocked", label: "blocked" },
        { key: "uiLanguage", label: "language" },
        { key: "from", label: "from" },
        { key: "to", label: "to" },
      ]),
    [filters],
  );

  const columns = useMemo<readonly DataColumn<UserView>[]>(
    () => [
      {
        id: "user",
        header: "user",
        isNumeric: false,
        width: "16rem",
        cell: (row) => (
          <TelegramUserChip
            telegramUserId={row.telegramUserId}
            telegramUserIdMasked={row.telegramUserIdMasked}
            isBlocked={row.isBlocked}
          />
        ),
      },
      {
        id: "uiLanguage",
        header: "language",
        isNumeric: false,
        width: "8rem",
        cell: (row) => <span className="text-ink-muted">{humaniseEnum(row.uiLanguage)}</span>,
      },
      {
        id: "orderCount",
        header: "orders",
        isNumeric: true,
        width: "6rem",
        cell: (row) => formatInteger(row.orderCount),
      },
      {
        id: "paidOrderCount",
        header: "paid",
        isNumeric: true,
        width: "6rem",
        cell: (row) => formatInteger(row.paidOrderCount),
      },
      {
        id: "accountCreatedAt",
        header: (
          <span>
            account created <TimeZoneCaption />
          </span>
        ),
        headerTitle: "when this person's first order was created — there is no signup event",
        isNumeric: false,
        width: "12rem",
        cell: (row) => <Timestamp at={row.accountCreatedAt} />,
      },
      {
        /*
         * §11.2 and §14, verbatim: "last order", never "last seen". The constant is the
         * single place the string exists so a well-meaning rename cannot reach it.
         */
        id: "lastOrderAt",
        header: (
          <span>
            {LAST_ORDER_COLUMN_LABEL} <TimeZoneCaption />
          </span>
        ),
        headerTitle: `${LAST_ORDER_COLUMN_LABEL}: MAX(orders.created_at). Not presence — lastSeenAt has no real writer until Phase 3.`,
        isNumeric: false,
        width: "12rem",
        cell: (row) => <Timestamp at={row.lastOrderAt} />,
      },
    ],
    [],
  );

  const signal = (
    <StatTile
      label="total users"
      size="hero"
      value={<span className="num">{formatTotal(total.data?.meta.total ?? null, total.data?.meta.isTotalExact ?? null)}</span>}
      {...(series === null ? {} : { trend: series })}
      trendLabel={`new accounts per day, last ${String(NEW_USER_WINDOW_DAYS)} days`}
      hint={
        series === null
          ? `more than ${String(MAX_PAGE_LIMIT)} new accounts in ${String(NEW_USER_WINDOW_DAYS)} days — the daily series needs an accounts-per-day metric`
          : `${formatInteger(newInWindow)} new in ${String(NEW_USER_WINDOW_DAYS)} days`
      }
    />
  );

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        title="users"
        description="Who are they and are they blocked?"
        signal={signal}
      >
        <FilterBar chips={chips} onClear={filters.clear} activeCount={filters.activeCount}>
          <TimeRangePicker
            value={{ from: value.from, to: value.to }}
            onChange={(next: TimeRange) => {
              /*
               * `/api/users` refuses a half window with a 422 ("from and to are one window;
               * give both or neither"), and `TimeRangePicker` emits presets with `to`
               * undefined. Close it here, and PIN it in the URL rather than recomputing it
               * per request — a `to` that means "now" would widen the filter between page
               * one and page two of a keyset walk.
               */
              patch({
                from: next.from,
                to: next.from === undefined ? undefined : (next.to ?? new Date().toISOString()),
              });
            }}
          />
          <EnumToggleGroup<Language>
            label="language"
            values={LANGUAGE_VALUES}
            selected={value.uiLanguage}
            onChange={(next) => {
              patch({ uiLanguage: next === undefined ? undefined : [...next] });
            }}
            format={humaniseEnum}
          />
          <TriStateSelect
            label="blocked"
            value={value.isBlocked}
            onChange={(next) => {
              patch({ isBlocked: next });
            }}
            trueLabel="blocked"
            falseLabel="not blocked"
          />
        </FilterBar>
      </PageHeader>

      <section
        className="flex min-h-0 flex-1 flex-col gap-3 px-gutter pb-gutter"
        aria-label="user directory"
      >
        {/* A plain section label ABOVE the card, not a heading inside it. */}
        <h2 className="type-h3 text-ink">Directory</h2>
        <AsyncBoundary
          className="flex min-h-0 flex-1 flex-col"
          status={users.status}
          hasData={users.data !== undefined}
          isEmpty={items.length === 0}
          activeFilterCount={filters.activeCount}
          onClearFilters={filters.clear}
          error={users.error}
          onRetry={() => {
            void users.refetch();
          }}
          dataUpdatedAt={users.dataUpdatedAt}
          noun="users"
          emptyTitle="No users yet"
          emptyBody="A row appears the first time somebody confirms an order — there is no signup event to count."
          skeleton={<SkeletonTable rows={10} columns={columns.length} density={density} />}
        >
          <DataTable
            label="users"
            data={items}
            columns={columns}
            getRowId={(row) => row.id}
            isRefetching={users.isFetching}
            onRowActivate={(row) => {
              navigate(href.user(row.telegramUserId));
            }}
            footer={
              <CursorPager
                label="users"
                meta={users.data?.meta}
                itemCount={items.length}
                cursor={value.cursor ?? null}
                onCursorChange={(cursor) => {
                  patch({ cursor: cursor ?? undefined }, { keepCursor: true });
                }}
                limit={value.limit ?? DEFAULT_PAGE_LIMIT}
                onLimitChange={(limit) => {
                  patch({ limit });
                }}
                isFetching={users.isFetching}
              />
            }
          />
        </AsyncBoundary>
      </section>
    </div>
  );
}

export const Component = UsersScreen;
