/**
 * `/users` — "Who are they and are they blocked?" (§11.2)
 *
 * ## The column header reads "last order"
 *
 * The old reason for this — "`last_seen_at` has no real writer until Phase 3" — is dead and
 * must not be restated: `db/credits.py::touch` upserts a `users` row and advances
 * `last_seen_at` on **every inbound update**, and that drain ships. The reason that survives
 * is narrower and will keep being true: **`UserView` carries no `lastSeenAt` field at all**,
 * so this screen has nothing to draw and a column headed "last seen" would be a claim about
 * presence read off `MAX(orders.created_at)` — a measurement of purchases. §11.2 pins the
 * string, §14 makes it an acceptance criterion, and `LAST_ORDER_COLUMN_LABEL` is the one place
 * it is spelled. If the field ever lands on the wire, this is the paragraph to reopen; until
 * then the words "last seen" appear nowhere on this screen, header titles included.
 *
 * ## What a row means, now that three writers create one
 *
 * Not "somebody confirmed an order". `users` rows are written from three places —
 * `users_sql.ensure_user` from `_create_order`, the same function from `record_language` when
 * a customer answers the language question, and `db/credits.py::touch` on every inbound
 * update — so a row is born at FIRST CONTACT for anyone who has spoken to the bot since that
 * shipped, and at the first order for accounts that predate it. `accountCreatedAt` therefore
 * means two things depending on the row's age, and both the empty state and that column's
 * `headerTitle` say so rather than repeating the old, simpler, false sentence.
 *
 * ## The avatar column is a bare `<img>` and is bounded here
 *
 * Every `/api/**` response is `Cache-Control: no-store` and the middleware replaces rather
 * than appends the header, so there is no freshness to tune and nothing to cache-bust. The
 * cost of fifty faces is bounded at this end instead: `<UserAvatar>` renders no `<img>` at all
 * unless `avatarUrl` is non-null, the element is `loading="lazy"`, and `getRowId` gives the
 * table a stable key so a refetch re-renders rather than remounts. That is one request per
 * distinct avatar per page load and none for a customer who never shared a photo.
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
 * ## Credits are a column, and `null` is a third state
 *
 * `creditBalance` is `null` when `credit_accounts` holds no row — a customer nobody has
 * charged or granted, or one whose `/forget` deleted it — and rendering that as `0` says the
 * opposite: that the account has spent everything it had. `<CreditBalanceChip>` is the one
 * place those three readings are drawn, so the column, the peek drawer and the order screen's
 * 360 card cannot drift apart. The number the BOT quotes the customer is a fourth thing again
 * (`creditsProjected`), it is not on this wire, and it is on the full record.
 *
 * ## Search is by Telegram id, and the copy has to say so
 *
 * `?q=` matches the id and nothing else. That is a privacy decision in `UserFilters`, not an
 * unfinished feature — a substring filter over the masked `user_profiles` columns would be a
 * reveal an operator could perform three characters at a time, with no step-up and no audit
 * row. `Q_PLACEHOLDER` and `Q_HINT` are where that is worded; nothing on this screen may
 * imply a name search, because an operator who believes names are searchable reads an empty
 * result as "this customer does not exist".
 *
 * ## Activating a row opens a peek, not a route
 *
 * An operator working a filtered directory checks one person and moves to the next. A route
 * change throws away the scroll position and the keyset page every time; the drawer throws
 * away nothing, because nothing about the table changes when it opens. See
 * `UserPeekDrawer.tsx` for what it draws from the row already in hand and the two things it
 * is worth a request for. The full record is one link away in its footer.
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
import { useMemo, useState, type ReactElement } from "react";
import { z } from "zod";

import {
  DEFAULT_PAGE_LIMIT,
  LANGUAGE_VALUES,
  LAST_ORDER_COLUMN_LABEL,
  MAX_PAGE_LIMIT,
  MAX_SEARCH_CHARS,
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
import { CreditBalanceChip, NameText, TelegramUserChip, UserAvatar } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, SkeletonTable } from "@/components/util";
import {
  EMPTY_VALUE,
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

import {
  DebouncedTextInput,
  EnumToggleGroup,
  QuickFilterChip,
  TriStateSelect,
} from "./filterControls";
import { NEW_USER_WINDOW_DAYS, buildNewUserSeries, newUserWindow } from "./newUsers";
import {
  PROFILE_STANDING_HINT,
  PROFILE_STANDING_LABEL,
  displayNameOf,
  profileStandingOf,
} from "./profile";
import { UserPeekDrawer } from "./UserPeekDrawer";

/**
 * The `q` box's placeholder, spelled once.
 *
 * It has to say what is searchable and it must not imply a name search, because the server
 * REFUSES to be one: `UserFilters` matches the Telegram id and nothing else, deliberately, so
 * that a substring filter over the masked `user_profiles` columns cannot become a reveal
 * bypass an operator performs three characters at a time. A placeholder reading "search
 * users" would send every operator looking for a name and quietly teach them the list is
 * broken.
 */
export const Q_PLACEHOLDER = "by telegram id";

/** Said on hover, where the placeholder has no room for the reason. */
export const Q_HINT =
  "Matches the Telegram id only. Names, handles and phone numbers are masked at every role and are deliberately not searchable — a substring filter over them would be a reveal with no step-up and no audit row.";

/**
 * §6.6's filter set for `/api/users`, as URL parameters.
 *
 * Module scope, not inside the component: `useSearchParamsState` memoises on the schema's
 * identity, and a schema rebuilt every render would reparse the URL every render.
 */
const usersFilterSchema = z.object({
  telegramUserId: zIntParam({ min: 1 }),
  /**
   * `?q=` — free text, and it matches the TELEGRAM ID and nothing else.
   *
   * That is a privacy decision on the server (`UserFilters` in `db/admin/users.py`), not an
   * unfinished feature: every other text column this list can reach lives on `user_profiles`
   * and is masked at all four roles, so a substring filter over it would let an operator with
   * no reveal cell confirm a customer's name three characters at a time — no step-up, no audit
   * row. `Q_PLACEHOLDER` is why no copy on this screen may imply a name search.
   */
  q: zStringParam,
  isBlocked: zBoolParam,
  /** `credit_accounts.balance > 0`, behind the quick-filter chip. Absent ≠ `false`. */
  hasBalance: zBoolParam,
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
  q?: string | undefined;
  isBlocked?: boolean | undefined;
  hasBalance?: boolean | undefined;
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
  const density = usePrefsStore((state) => state.density);
  const filters = useSearchParamsState(usersFilterSchema, USERS_FILTER_FALLBACK);
  const { value, patch } = filters;

  /*
   * The peeked row, held as the ROW rather than as an id in the URL. Deliberately not URL
   * state: the peek is a reading position, not a slice of the data — a pasted `/users?...`
   * link is meant to reproduce the FILTERED LIST (§11.1), and reopening somebody's drawer for
   * the recipient of that link is not what they were sent. The row also carries every profile
   * fact the panel draws, so holding it costs no second request.
   */
  const [peeked, setPeeked] = useState<UserView | null>(null);

  const listQuery = useMemo<UsersQuery>(
    () => ({
      telegramUserId: value.telegramUserId,
      q: value.q,
      isBlocked: value.isBlocked,
      hasBalance: value.hasBalance,
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
        /*
         * `search`, not `name` — the chip is read back by an operator who did not type it.
         * VERBATIM, because the default string formatter is `humaniseEnum`, which is for our
         * own closed vocabularies: it would retitle whatever the operator typed.
         */
        { key: "q", label: "search", format: (value) => String(value) },
        { key: "isBlocked", label: "blocked" },
        { key: "hasBalance", label: "has balance" },
        { key: "uiLanguage", label: "language" },
        { key: "from", label: "from" },
        { key: "to", label: "to" },
      ]),
    [filters],
  );

  const columns = useMemo<readonly DataColumn<UserView>[]>(
    () => [
      {
        /*
         * The face, first, because it is what an operator scanning a directory recognises
         * before they can read an id. The `width` is rendered into a real `<colgroup>` by
         * `DataTable`, so a photo that arrives late cannot reflow the grid around it — which
         * is the whole reason a fixed column beats an inline avatar inside the `user` cell.
         *
         * The header is screen-reader-only: a visible "avatar" label above a 28px picture is
         * chrome nobody needs, but the column still has to be nameable in the grid.
         * `isNumeric: false` is stated rather than omitted — `DataColumn` asks for the
         * decision explicitly so that "it looked numeric enough" cannot right-align a cell.
         */
        id: "avatar",
        header: <span className="sr-only">avatar</span>,
        isNumeric: false,
        width: "3.5rem",
        cell: (row) => (
          <UserAvatar
            size="sm"
            avatarUrl={row.avatarUrl}
            firstNameMasked={row.firstNameMasked}
            lastNameMasked={row.lastNameMasked}
          />
        ),
      },
      {
        /*
         * Widened from 16rem because this cell is now a stack of three: the masked id, the
         * name, and the handle. All three are the same person's identity, so they belong in
         * one column an eye reads top-to-bottom rather than in three the eye has to correlate
         * across the row.
         *
         * The name AND the handle go through `<NameText>` — both are customer-written and
         * that component is the only way such a string reaches the DOM. No `isToggleable`
         * here: fifty `U+` buttons is noise, and the toggle earns its place only where a
         * value is being read aloud, which is the detail screen.
         */
        id: "user",
        header: "user",
        isNumeric: false,
        width: "20rem",
        cell: (row) => {
          const displayName = displayNameOf(row);
          return (
            <div className="flex flex-col gap-0.5">
              <TelegramUserChip
                telegramUserId={row.telegramUserId}
                telegramUserIdMasked={row.telegramUserIdMasked}
                isBlocked={row.isBlocked}
              />
              {displayName === null ? null : <NameText value={displayName} />}
              {row.telegramUsernameMasked === null ? null : (
                <NameText
                  value={row.telegramUsernameMasked}
                  className="type-mono text-ink-muted"
                />
              )}
            </div>
          );
        },
      },
      {
        id: "uiLanguage",
        header: "language",
        isNumeric: false,
        width: "8rem",
        cell: (row) => <span className="text-ink-muted">{humaniseEnum(row.uiLanguage)}</span>,
      },
      {
        /*
         * The masked number is OUR construction, not customer content — the same reasoning
         * `TelegramUserChip` gives for the masked id — so it is not a `<NameText>` case and
         * `type-mono` is safe on it. The mask carries no country prefix on purpose: a fixed
         * `+998` head would publish two subscriber digits of a foreign number while hiding
         * its country code, which is the mask leaking what it exists to protect.
         */
        id: "phone",
        header: "phone",
        headerTitle: "masked at the response boundary; the number itself is a reveal",
        isNumeric: false,
        width: "9rem",
        cell: (row) =>
          row.phoneMasked === null ? (
            <span className="text-ink-muted">{EMPTY_VALUE}</span>
          ) : (
            <span className="type-mono">{row.phoneMasked}</span>
          ),
      },
      {
        /*
         * A named standing, not a lock and not a blank. `/forget` DELETEs the profile row, so
         * "erased" and "never onboarded" are one absence with no stamp to tell them apart —
         * a `<PurgedValue>` here would invent a date, and an empty cell would read as a
         * rendering bug. The hint on `title` is where that is admitted; `./profile` is where
         * it is worded, once, for this column and the detail panel both.
         */
        id: "profile",
        header: "profile",
        isNumeric: false,
        width: "10rem",
        cell: (row) => {
          const standing = profileStandingOf(row);
          return (
            <span className="text-ink-muted" title={PROFILE_STANDING_HINT[standing]}>
              {PROFILE_STANDING_LABEL[standing]}
            </span>
          );
        },
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
        /*
         * §11.2's headline operator question — "does this customer have credits?" — answered
         * on the row rather than one navigation away.
         *
         * THREE states, never two. `creditBalance` is `null` when `credit_accounts` holds no
         * row at all: a customer nobody has charged or granted (who is still owed their whole
         * rolling allowance the moment they order) or one whose `/forget` deleted the row.
         * Rendering either as `0` would say the opposite — that this account has spent
         * everything it had — so the distinction is `<CreditBalanceChip>`'s whole job and it is
         * asserted in this screen's test.
         */
        id: "credits",
        header: "credits",
        headerTitle:
          "credit_accounts.balance. “never metered” is no account row at all, which is a different fact from a balance of 0 — and neither is the number the bot quotes the customer (that is creditsProjected, on the full record).",
        isNumeric: false,
        width: "10rem",
        cell: (row) => <CreditBalanceChip balance={row.creditBalance} />,
      },
      {
        id: "accountCreatedAt",
        header: (
          <span>
            account created <TimeZoneCaption />
          </span>
        ),
        /*
         * The old title said "when this person's first order was created". That was already
         * false before this change — `db/credits.py::touch` upserts a `users` row on every
         * inbound update — and this release adds a third writer, `users_sql.ensure_user`
         * called from `record_language`. The column now means two things depending on how old
         * the row is, and the honest thing is to say which two rather than to pick one.
         */
        headerTitle:
          "when the users row was created — first contact for anyone onboarded since this release, the first order for accounts that predate it",
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
        headerTitle: `${LAST_ORDER_COLUMN_LABEL}: MAX(orders.created_at). Not presence — UserView carries no such field for this screen to draw.`,
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
          {/* The two text controls first: this is the bar's leftmost, and an operator who
              arrives with an id in their clipboard should not have to hunt for the box. */}
          <DebouncedTextInput
            label="search"
            value={value.q}
            placeholder={Q_PLACEHOLDER}
            title={Q_HINT}
            maxLength={MAX_SEARCH_CHARS}
            onChange={(next) => {
              patch({ q: next });
            }}
          />
          <DebouncedTextInput
            label="telegram id"
            value={value.telegramUserId === undefined ? undefined : String(value.telegramUserId)}
            placeholder="exact match"
            title="The exact integer, which is a different filter from the search box: this one is an equality and matches one account or none."
            isNumeric
            widthClassName="w-36"
            onChange={(next) => {
              /*
               * The control emits digits or nothing — it strips everything else as it is
               * typed — so this parse cannot fail on a non-numeric string. `0` and a value
               * that overflows the schema's `min: 1` still drop the parameter rather than
               * asking the API for an id that cannot exist.
               */
              const parsed = next === undefined ? Number.NaN : Number.parseInt(next, 10);
              patch({
                telegramUserId: Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : undefined,
              });
            }}
          />
          <TimeRangePicker
            value={{ from: value.from, to: value.to }}
            onChange={(next: TimeRange) => {
              /*
               * `TimeRangePicker` emits presets with `to` undefined. `/api/users` accepts
               * that now — `resolve_window` closes a missing end at the instant the request
               * was served — so closing it here is no longer about dodging a 422. It is
               * about WHERE the end is decided: pinned in the URL, one instant answers every
               * page of the walk; left to the server, each request closes at its own `now`
               * and the filter widens between page one and page two.
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
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="type-h3 text-ink">Directory</h2>
          {/*
            Presets, not a second filter store. Each chip writes the SAME URL parameter its
            control in the bar above writes, so the two always agree and a chip left on is
            visible as a removal chip up there as well.

            There is deliberately no "In Wizard" chip, and it is not an oversight. Wizard state
            is per-user Redis (`hbd/admin/wizard_state.py`, read one id at a time through
            `GET /users/{id}/wizard-state`); there is no list-level source and no `users`
            column to filter on, so the chip could only be built by fetching every row's Redis
            key — which is a scan, not a filter. It arrives when a list-level source does.
          */}
          <div role="group" aria-label="quick filters" className="flex flex-wrap items-center gap-2">
            <QuickFilterChip
              label="Blocked"
              isActive={value.isBlocked === true}
              title="isBlocked=true — the same filter as the blocked control above, in one click."
              onToggle={(isActive) => {
                patch({ isBlocked: isActive ? true : undefined });
              }}
            />
            <QuickFilterChip
              label="Has balance > 0"
              isActive={value.hasBalance === true}
              title="credit_accounts.balance > 0. Turning it off asks for everyone again, not for the accounts with no balance — absence is not false."
              onToggle={(isActive) => {
                patch({ hasBalance: isActive ? true : undefined });
              }}
            />
          </div>
        </div>
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
          emptyBody="A row appears the first time somebody speaks to the bot — there is no signup event to count."
          skeleton={<SkeletonTable rows={10} columns={columns.length} density={density} />}
        >
          <DataTable
            label="users"
            data={items}
            columns={columns}
            getRowId={(row) => row.id}
            isRefetching={users.isFetching}
            /*
             * Peek, do not navigate. The filters, the keyset page and the row the operator is
             * on all survive a peek and none of them survives a route change — and the drawer
             * carries an "open full record" link for the times the full page is what is
             * wanted. See `UserPeekDrawer.tsx` for what it does and does not refetch.
             */
            onRowActivate={(row) => {
              setPeeked(row);
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

      {/* Outside the table's section and outside `AsyncBoundary`: a refetch that empties the
          list must not take the panel an operator is reading with it. */}
      <UserPeekDrawer
        user={peeked}
        onClose={() => {
          setPeeked(null);
        }}
      />
    </div>
  );
}

export const Component = UsersScreen;
