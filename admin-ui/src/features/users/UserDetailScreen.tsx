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
 * Header → "Profile" (the contact facts) → "Most recent order" (the hero card) → "Orders"
 * (the distribution bar and the table) → the wizard aside. Each group carries a plain section
 * label above its cards, and the cards separate themselves with `--shadow-card`; there is not
 * a border on this screen.
 *
 * "Profile" sits above the banner even though the banner is §11.2's dominant signal, because
 * it answers the question asked FIRST on a support call — "is this the person I am speaking
 * to, and can they order at all?" — and because it is four short facts rather than a card the
 * eye has to work through. It is also where the honest sentence about erasure lives: `/forget`
 * DELETEs the `user_profiles` row and the table has no retention clock, so an erased profile
 * and one that never existed are the same absence and this screen must not pretend otherwise.
 * See `./profile`, which words that once for this panel and for the users list both.
 *
 * The banner is a full card of its own rather than a strip, because §11.2's signal is what
 * support reads aloud and the reskin's answer to "make this the loudest thing" is size and
 * air, not a rule around it. Everything below it is narrower or quieter.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { z } from "zod";

import {
  DEFAULT_PAGE_LIMIT,
  IN_FLIGHT_ORDER_STATES,
  MAX_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  failureOf,
  getUser,
  getUserCredits,
  getUserOrders,
  getWizardState,
  postUserBlock,
  unwrapAsync,
  type OrderView,
  type PageQuery,
  type UserBlockRequest,
  type UserCreditsQuery,
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
  CreditBalanceChip,
  CreditLedgerTable,
  ErrorCodeBadge,
  GrantCreditsButton,
  NameText,
  NEVER_METERED_LABEL,
  OrderRefChip,
  PurgedValue,
  ReasonConfirmDialog,
  RevealButton,
  StatusPill,
  StepUpPrompt,
  stepUpTargetOf,
  TelegramUserChip,
  USER_PROFILE_REVEAL_FIELDS,
  UserAvatar,
  useRevealCeilings,
  type ReasonValue,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import {
  AsyncBoundary,
  Button,
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

import {
  PROFILE_STANDING_HINT,
  PROFILE_STANDING_LABEL,
  displayNameOf,
  profileStandingOf,
} from "./profile";
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

/**
 * The ledger's page size, deliberately smaller than the orders table's fifty.
 *
 * It is the explanation beside a balance rather than a working list: the question it answers
 * — "was this account comped, and by whom?" — is nearly always answered by the newest few
 * rows, and a fifty-row grid under the order table would push the wizard aside off the fold
 * on the screens support actually uses. The pager's own size control is still there for the
 * argument that needs the whole history.
 */
const LEDGER_PAGE_LIMIT = 10;

/** What the three credit numbers each mean, for an operator who hovers them. */
const BALANCE_HINT =
  "credit_accounts.balance — what the ledger below can prove. Absent when there is no account row at all, which is not a balance of 0.";
const PROJECTED_HINT =
  "What the bot would tell this customer right now: the stored balance plus a rolling allowance that is due and has not been minted yet. This is the number they were shown on the Confirm screen.";
const IN_FLIGHT_HINT =
  "Debits this account has not settled yet, inside the settlement grace window. A render whose worker died holds a credit that neither the balance nor the ledger shows as spent — this is the only number here that explains why a customer with credits is being refused.";
const LIFETIME_HINT =
  "Every credit ever added, allowances included — whether this account has already been comped, without reading the ledger.";
const ALLOWANCE_HINT =
  "The last rolling-allowance window this account was minted for. Absent for two reasons — no account row, or an account that has never had an allowance — and the balance beside it is what tells them apart.";

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

  /*
   * The ledger's page is component state and NOT in the URL, which is the one place this
   * screen departs from its own paging idiom. The URL's `cursor` and `limit` belong to the
   * orders table; a second pager sharing those keys would turn both tables' pages at once,
   * and giving the ledger its own pair would put two opaque keyset cursors into the link
   * support pastes into a ticket. The ledger is the explanation beside a balance rather than
   * the thing this route is addressed by, so it does not earn a share of the address.
   */
  const [ledgerCursor, setLedgerCursor] = useState<string | null>(null);
  const [ledgerLimit, setLedgerLimit] = useState(LEDGER_PAGE_LIMIT);

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

  const creditsQuery = useMemo<UserCreditsQuery>(
    () => ({ limit: ledgerLimit, cursor: ledgerCursor ?? undefined, withTotal: true }),
    [ledgerCursor, ledgerLimit],
  );

  /*
   * The balance and its movements are ONE response, so they are one query — see the note on
   * `queryKeys.users.credits`. It sits under `users.detail`, which is what lets a grant
   * invalidate `queryKeys.users.all` and move `creditsProjected` and `account.balance`
   * together; refreshing one without the other would show the pair this panel exists to
   * compare disagreeing with itself.
   *
   * No polling. A ledger row is written by an operator or by a render that has just
   * finished, and the orders table beside it is already the thing that polls.
   */
  const credits = useQuery({
    queryKey: queryKeys.users.credits(id, creditsQuery),
    queryFn: ({ signal }) => unwrapAsync(getUserCredits(id, creditsQuery, { signal })),
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

  /*
   * Computed once, read twice — the header stack and the profile panel would otherwise each
   * join the two masked names, and two joiners are two chances for one of them to acquire a
   * `.trim()`. `null` when neither name was shared, which is a different fact from `""`.
   */
  const displayName = user === undefined ? null : displayNameOf(user);

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        title="user"
        description="What happened to my song?"
        /*
          The CONTACT reveal, and it belongs in the header rather than beside the profile
          facts or inside a card, because its SUBJECT is the person — who is the subject of
          this whole screen. (The order-brief reveal on the banner below is a different
          subject with a different id; see the note there.)

          `subjectId` is `user.id`, the `users` PK UUID, and never `telegramUserId`:
          `revealRequestSchema.subjectId` is a uuid and the server compares the composed
          `reveal:<subjectId>` step-up scope WHOLE, so an integer here is a permanent, silent
          403 that no client-side test would ever see.

          `subjectLabel` is OUR words for the subject — the masked id. The label of a dialog
          that exists to reveal somebody's name must not be their name.

          No `<PermissionGate>` around any of the three: `RevealButton` carries
          `reveal.personal_data` internally, `<GrantCreditsButton>` carries
          `credit.grant.write` and `<BlockUserAction>` carries `user.block.write` — each
          gated where it is drawn, so a screen cannot wire one in and forget it. §11.4's rule
          is hiding, not disabling, so a role without the cell sees no button at all rather
          than one that answers 403.

          The two writes come first and the reveal last. The reveal is the only one of the
          three that spends a metered budget, and it is the one an operator should have to
          travel furthest to press by accident.
        */
        actions={
          user === undefined ? null : (
            <div className="flex flex-wrap items-center gap-2">
              <GrantCreditsButton
                telegramUserId={telegramUserId}
                subjectLabel={user.telegramUserIdMasked}
                onSuccess={() => {
                  /*
                   * The dialog has already invalidated `queryKeys.users.all`, which is a
                   * PREFIX of both `users.detail(id)` and `users.credits(id, …)` — so the
                   * balance, the projection and the ledger all refetch without a second
                   * call from here.
                   *
                   * What it cannot know is which page of the ledger this screen is on. The
                   * ledger is newest-first, so the row just written is on page one; a
                   * refetched page three would come back perfectly correct and still not
                   * contain the grant the operator is looking for. Going home is the only
                   * part of this that is the caller's business.
                   */
                  setLedgerCursor(null);
                }}
              />
              <BlockUserAction
                telegramUserId={telegramUserId}
                subjectLabel={user.telegramUserIdMasked}
                isBlocked={user.isBlocked}
              />
              <RevealButton
                subjectType="user"
                subjectId={user.id}
                subjectLabel={user.telegramUserIdMasked}
                fields={USER_PROFILE_REVEAL_FIELDS}
                label="Reveal this person's contact details"
              />
            </div>
          )
        }
        signal={
          user === undefined ? null : (
            /*
              Two columns: the face, then the identity stack that was already here. The photo
              earns the left-hand slot because it is what an operator matches against a caller
              before they can read anything; the counts line stays last because it is the one
              part of this block nobody reads aloud.
            */
            <div className="flex items-center gap-4">
              <UserAvatar
                size="lg"
                avatarUrl={user.avatarUrl}
                firstNameMasked={user.firstNameMasked}
                lastNameMasked={user.lastNameMasked}
              />
              <div className="flex flex-col items-end gap-1">
                <TelegramUserChip
                  telegramUserId={user.telegramUserId}
                  telegramUserIdMasked={user.telegramUserIdMasked}
                  isBlocked={user.isBlocked}
                />
                {/*
                  `isToggleable` is right HERE and wrong in the users table. This is the one
                  place a masked name is read aloud on a call, and the `U+` toggle is what
                  answers "which apostrophe" — U+02BB, U+02BC, U+2019 and U+0027 are the same
                  picture at this size. Fifty such buttons in a table would be noise.
                */}
                {displayName === null ? null : <NameText value={displayName} isToggleable />}
                {user.telegramUsernameMasked === null ? null : (
                  <NameText
                    value={user.telegramUsernameMasked}
                    className="type-mono text-ink-muted"
                  />
                )}
                <span className="type-body-sm num text-ink-muted">
                  {`${formatInteger(user.orderCount)} orders · ${formatInteger(user.paidOrderCount)} paid · ${humaniseEnum(user.uiLanguage)}`}
                </span>
              </div>
            </div>
          )
        }
      />

      {/*
        The contact profile, above the order banner because it answers "is this the person on
        the phone, and can they order at all?" — which is the question asked before "what
        happened to their song?".

        Five facts and no lock. There is no `<PurgedValue>` anywhere in here: `/forget` DELETEs
        the `user_profiles` row rather than nulling it, and the table carries no `*_expires_at`,
        so "erased" and "never onboarded" are one absence with no stamp to separate them. A
        lock-and-date would be an invented fact and a blank panel would read as a bug; the
        `standing` fact names which of the three things is true and its `title` admits which two
        it cannot distinguish.

        The `photo` fact is why `hasAvatar` is on the wire at all: when the picture in the
        header does not draw — a 404, an expired session, a broken proxy — this is what says
        whether a photo was ever captured. The `<img>` itself cannot tell an operator that.
      */}
      {user === undefined ? null : (
        <section className="flex flex-col gap-3 px-gutter pb-6" aria-label="contact profile">
          <h2 className="type-h3 text-ink">Profile</h2>
          <div
            data-testid="profile-panel"
            className="rounded-card bg-surface-card p-card shadow-card"
          >
            <dl className="grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-3 xl:grid-cols-5">
              <BannerFact label="standing">
                <span title={PROFILE_STANDING_HINT[profileStandingOf(user)]}>
                  {PROFILE_STANDING_LABEL[profileStandingOf(user)]}
                </span>
              </BannerFact>

              <BannerFact label="phone">
                {/* OUR mask, not customer content, so `type-mono` is safe and `<NameText>`
                    does not apply. The plaintext is on this wire at no role at all — the
                    header's reveal is the one path to it, and it costs a step-up and an
                    audit row. */}
                {user.phoneMasked === null ? (
                  <span className="text-ink-muted">{EMPTY_VALUE}</span>
                ) : (
                  <span className="type-mono">{user.phoneMasked}</span>
                )}
              </BannerFact>

              <BannerFact label="phone shared">
                <Timestamp at={user.phoneSharedAt} />
              </BannerFact>

              <BannerFact label="photo">
                {user.hasAvatar ? (
                  <span className="inline-flex items-baseline gap-2">
                    captured <Timestamp at={user.avatarFetchedAt} />
                  </span>
                ) : (
                  <span className="text-ink-muted">none</span>
                )}
              </BannerFact>

              <BannerFact label="@username">
                {/* A handle the customer chose, so it is customer-written text and reaches
                    the DOM the only way such text may. */}
                <NameText value={user.telegramUsernameMasked} />
              </BannerFact>
            </dl>
          </div>
        </section>
      )}

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

      {/*
        Credits — "can this person order again, and have we already comped them?"

        It sits BELOW the banner and above the order list, which is the order the support
        call takes: who is this (Profile), what happened to their song (the banner), and only
        then why they can or cannot start another one.

        The panel's whole job is to keep two numbers apart that a single "credits" field would
        merge. `creditBalance` is the stored column — what the ledger below can prove — and
        `creditsProjected` is what the bot would tell this customer right now, the stored
        balance plus a rolling allowance that is due and has not been minted yet. An operator
        handed only one of them cannot answer "they say they have three songs and your panel
        says zero", which is the ticket this pair exists for. `inFlightRenderCount` is the
        third number and it belongs beside the projection rather than the balance: it is the
        only figure on the screen that explains a customer with credits being refused.

        Nothing here is masked or reveal-gated, and that is a property of the tables rather
        than a relaxation — `credit_accounts` and `credit_ledger` hold a Telegram id, two
        closed enums and integers, with no free text for `POST /reveal` to gate.
      */}
      <section className="flex flex-col gap-3 px-gutter pb-6" aria-label="credits">
        <h2 className="type-h3 text-ink">Credits</h2>
        <div
          data-testid="credits-panel"
          className="flex flex-col gap-6 rounded-card bg-surface-card p-card shadow-card"
        >
          {detail.data === undefined ? (
            /* The facts come from the user record, so they have no boundary of their own —
               the Orders section below already owns that query's error and retry. What they
               must not do is shimmer forever on a failure, which reads as a hang rather than
               as the refusal it is. */
            detail.status === "error" ? (
              <p data-testid="credits-facts-unavailable" className="type-body-sm text-ink-muted">
                The balance and the projection are part of the user record, which did not
                load. The ledger below is a separate request and may still be readable.
              </p>
            ) : (
              <Skeleton height="4.5rem" className="w-full rounded-card" />
            )
          ) : (
            <div className="flex flex-col gap-4">
              <dl className="grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-3 xl:grid-cols-5">
                <BannerFact label="balance">
                  {/* The chip and not a number: `null` is "no account row" and must not be
                      drawn as 0, which is the opposite claim. */}
                  <span title={BALANCE_HINT}>
                    <CreditBalanceChip balance={detail.data.user.creditBalance} size="md" />
                  </span>
                </BannerFact>

                <BannerFact label="projected">
                  <span className="num" title={PROJECTED_HINT}>
                    {formatInteger(detail.data.creditsProjected)}
                  </span>
                </BannerFact>

                <BannerFact label="renders in flight">
                  <span className="num" title={IN_FLIGHT_HINT}>
                    {formatInteger(detail.data.inFlightRenderCount)}
                  </span>
                </BannerFact>

                <BannerFact label="lifetime granted">
                  {/* `null` here is the same absent account row the balance chip names, so
                      it says so in words rather than falling back to the em dash — which on
                      this row would read as "we did not measure it". */}
                  {detail.data.user.lifetimeCreditsGranted === null ? (
                    <span className="text-ink-muted" title={LIFETIME_HINT}>
                      {NEVER_METERED_LABEL}
                    </span>
                  ) : (
                    <span className="num" title={LIFETIME_HINT}>
                      {formatInteger(detail.data.user.lifetimeCreditsGranted)}
                    </span>
                  )}
                </BannerFact>

                <BannerFact label="allowance period">
                  {/* Genuinely two absences with one spelling — no account row, or an
                      account that has never had an allowance — so this one IS the em dash,
                      and the balance chip beside it is what tells them apart. */}
                  {detail.data.user.allowancePeriod === null ? (
                    <span className="text-ink-muted" title={ALLOWANCE_HINT}>
                      {EMPTY_VALUE}
                    </span>
                  ) : (
                    <span className="num" title={ALLOWANCE_HINT}>
                      {formatInteger(detail.data.user.allowancePeriod)}
                    </span>
                  )}
                </BannerFact>
              </dl>

              <ProjectionNote
                balance={detail.data.user.creditBalance}
                projected={detail.data.creditsProjected}
                inFlightRenderCount={detail.data.inFlightRenderCount}
              />
            </div>
          )}

          {/*
            `isEmpty` is deliberately NOT passed. An empty `items` array means two different
            things here — "this account exists and nothing has moved on this page" and "there
            is no account row at all" — and the table already draws both, keyed on
            `page.account`. `AsyncBoundary`'s single empty state would flatten the pair the
            panel above exists to keep apart.

            `isSummaryHidden` for the same reason in reverse: the balance, the lifetime total
            and the allowance period are the facts grid above, and printing them twice invites
            the two copies to disagree.
          */}
          <AsyncBoundary
            status={credits.status}
            hasData={credits.data !== undefined}
            error={credits.error}
            onRetry={() => {
              void credits.refetch();
            }}
            dataUpdatedAt={credits.dataUpdatedAt}
            noun="the credit ledger"
            skeleton={<SkeletonTable rows={4} columns={7} density={density} />}
          >
            <CreditLedgerTable
              page={credits.data}
              cursor={ledgerCursor}
              onCursorChange={setLedgerCursor}
              limit={ledgerLimit}
              onLimitChange={setLedgerLimit}
              isFetching={credits.isFetching}
              isSummaryHidden
            />
          </AsyncBoundary>
        </div>
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

          There are now TWO reveals on this screen and they are in different regions on
          purpose: the CONTACT reveal in the page header takes a different subject — the
          person, `subjectType: "user"` keyed on `users.id` — because the person is the
          subject of the whole screen while this order is the subject of one card on it.
          Both instances carry `RevealButton`'s own `data-testid="reveal-button"`, so a test
          that means this one must scope itself to the banner rather than query globally.
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
 * One label/value pair — in the hero card, and in the profile panel above it.
 *
 * The label is `--ink-muted` at 13px and the value is `--ink` at 14px — both clear the text
 * bar. `.type-caption` is deliberately NOT used here: it uppercases, and the values passed to
 * it include a recipient's name, a customer's own masked name and a `@username`, where a
 * `text-transform` would alter the mark the whole `NameText` fence exists to preserve — on
 * screen, with the right string still in the DOM, which is the hardest version of that bug to
 * see. Keeping the label class off the caption scale means nobody has to remember which of
 * these `<div>`s is safe to restyle.
 *
 * Shared between the two panels rather than twinned, because a twin is how one of them
 * acquires `.type-caption` later and the other does not.
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

/**
 * The sentence that stops the two credit numbers reading as a contradiction.
 *
 * A balance of `null` beside a projection of 3 is the NORMAL reading for a brand-new
 * customer: `credit_accounts` has no row yet and the whole rolling allowance is still ahead
 * of them. A stored 0 beside a projection of 3 is the same story one step later. Neither is a
 * bug, and an operator who has just been told "the panel says zero" by a customer holding
 * three songs needs that said in words — the two figures alone, however well labelled, are
 * exactly what the argument is about.
 *
 * Silent when the two agree, because then there is nothing to reconcile. The in-flight line
 * is separate and appears on its own terms: it explains a refusal rather than a difference,
 * and the two can be true at once.
 */
function ProjectionNote({
  balance,
  projected,
  inFlightRenderCount,
}: {
  readonly balance: number | null;
  readonly projected: number;
  readonly inFlightRenderCount: number;
}): ReactElement | null {
  const isDifferent = projected !== (balance ?? 0);
  if (!isDifferent && inFlightRenderCount === 0) return null;

  return (
    <div
      data-testid="credits-projection-note"
      className="flex flex-col gap-1 type-body-sm text-ink-muted"
    >
      {isDifferent ? (
        <p>
          {balance === null
            ? `There is no credit_accounts row, so nothing is stored — the ${formatInteger(projected)} above is a rolling allowance this account has never drawn on. That is the normal reading for a customer who has not ordered yet, not a contradiction.`
            : `The customer would be told ${formatInteger(projected)} and the ledger can prove ${formatInteger(balance)}. The difference is a rolling allowance that is due and has not been minted; it becomes a ledger row the moment they order.`}
        </p>
      ) : null}
      {inFlightRenderCount > 0 ? (
        <p data-testid="credits-in-flight-note">
          {`${formatInteger(inFlightRenderCount)} ${inFlightRenderCount === 1 ? "render is" : "renders are"} debited and not settled yet. Those credits are spent as far as the gate is concerned, which is why this account can be refused while the numbers above still look healthy.`}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Block / unblock, the destructive half of the two operator actions on this screen.
 *
 * Four properties of `POST /users/{id}/block` and `/unblock` shape this, and each one is a
 * defect if it is dropped:
 *
 * 1. **`isBlocked` picks the ROUTE, never a body field.** The two routes write different
 *    audit actions — `user.block` and `user.unblock` — so a single endpoint taking a boolean
 *    would be an unblock that audits as a block. `postUserBlock` takes the flag and chooses;
 *    what is passed here is the state being MOVED TO, which is the negation of the state on
 *    screen.
 * 2. **`user.block.write` is the gate**, not `user.block`. The first is what the router
 *    guards (the role half); the second is the step-up cell, enforced inside the handler and
 *    a different thing. Gating on the wrong one would be the same two roles today and would
 *    drift the moment the matrix splits them.
 * 3. **A `403 STEP_UP_REQUIRED` is recovered, not reported** — the same seam the grant uses,
 *    with the subject id taken from `details.subjectId` verbatim. `check_step_up` compares
 *    the composed `user.block:<subjectId>` scope WHOLE, so a re-formatted id is a permanent,
 *    silent 403. The typed reason survives, because `ReasonConfirmDialog` hides its fields
 *    rather than unmounting them, and the SAME body goes again.
 * 4. **Pressing it twice is information.** Blocking an already-blocked account is a no-op
 *    that still writes an audit row, so this does not disable itself on the strength of the
 *    state it is showing — the state can be stale, and refusing the second press client-side
 *    would suppress the record of an operator who meant it.
 */
function BlockUserAction({
  telegramUserId,
  subjectLabel,
  isBlocked,
}: {
  readonly telegramUserId: number;
  /** OUR words for the subject — the masked id. Never a name. */
  readonly subjectLabel: string;
  /** The state on screen. The action moves to its opposite. */
  readonly isBlocked: boolean;
}): ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  /** The body actually sent, kept so a step-up retry can resend it UNCHANGED. */
  const [pending, setPending] = useState<UserBlockRequest | null>(null);
  const queryClient = useQueryClient();
  const ceilings = useRevealCeilings(isOpen);

  /* What pressing the button DOES, which is the negation of what it is showing. */
  const isBlocking = !isBlocked;

  const action = useMutation({
    mutationFn: (body: UserBlockRequest) =>
      unwrapAsync(postUserBlock(telegramUserId, isBlocking, body)),
    onSuccess: () => {
      /* One prefix: the users list's blocked chip, this screen's header chip and the detail
         all carry `isBlocked`, and a screen that refreshed one of them would keep offering
         "Block" for an account it had just blocked. */
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      setIsOpen(false);
    },
  });

  const { reset } = action;
  /* A reopened dialog starts clean — a previous subject's reason carried into the next
     action is how "abuse report" ends up on somebody else's audit row. */
  useEffect(() => {
    if (isOpen) return;
    reset();
    setPending(null);
  }, [isOpen, reset]);

  const failure = failureOf(action.error);
  const stepUpTarget = stepUpTargetOf(failure);
  const verb = isBlocking ? "Block" : "Unblock";

  return (
    <PermissionGate permission="user.block.write">
      <Button
        variant={isBlocking ? "danger" : "secondary"}
        data-testid="block-user-button"
        onClick={() => {
          setIsOpen(true);
        }}
      >
        {verb}
      </Button>

      <ReasonConfirmDialog
        isOpen={isOpen}
        onOpenChange={setIsOpen}
        testId="block-user-dialog"
        title={`${verb} this account`}
        description={
          isBlocking
            ? `${subjectLabel} will be refused by the bot. The block is recorded on the audit log with the reason you give; pressing it again later is a no-op that still writes a row.`
            : `${subjectLabel} will be able to order again. The unblock is recorded on the audit log with the reason you give.`
        }
        confirmLabel={action.isPending ? `${verb}ing…` : `${verb} ${subjectLabel}`}
        confirmVariant={isBlocking ? "danger" : "primary"}
        isPending={action.isPending}
        isFieldsHidden={stepUpTarget !== null}
        onConfirm={(reason: ReasonValue) => {
          const body: UserBlockRequest = { ...reason };
          setPending(body);
          action.mutate(body);
        }}
        banner={
          <>
            {stepUpTarget === null ? null : (
              <StepUpPrompt
                action={stepUpTarget.action}
                /* Verbatim from the refusal: the Telegram id as a bare decimal string, not
                   a UUID and not a number this component re-formatted. */
                subjectId={stepUpTarget.subjectId}
                subjectLabel={subjectLabel}
                graceS={ceilings.stepUpGraceS}
                note={<span>{`${verb}ing this account needs a grant scoped to it.`}</span>}
                onGranted={() => {
                  if (pending !== null) action.mutate(pending);
                }}
                onCancel={() => {
                  setIsOpen(false);
                }}
              />
            )}

            {failure !== null && stepUpTarget === null ? (
              <p
                role="alert"
                data-testid="block-failure"
                data-code={failure.code}
                className="type-body-sm rounded-2xl bg-surface-control p-4 text-error"
              >
                <span className="type-mono">{failure.code}</span>
                {` — ${failure.message}`}
              </p>
            ) : null}
          </>
        }
      />
    </PermissionGate>
  );
}

export const Component = UserDetailScreen;
