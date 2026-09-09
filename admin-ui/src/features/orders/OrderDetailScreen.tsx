/**
 * `/orders/:orderId` — **Where is it, or exactly where did it die?**
 *
 * §11.2's dominant signal is the `PipelineTimeline` across the top third, and everything
 * else on the page is subordinate to it. Four facts it must convey, each of which is a way
 * an operator otherwise ends up with a wrong belief:
 *
 * 1. **Nine stages, not eleven.** `greetings_per_kit=0` is shipped, so the two greeting
 *    stages are unplanned and render GHOSTED — dimmed, dashed, captioned "not planned in
 *    this deployment". `PipelineTimeline` owns that rendering; this screen's job is to hand
 *    it `stagePlan` unaltered and never to filter the array.
 * 2. **The failed stage is highlighted with its error code and retryability**, tri-state:
 *    `null` is "unknown", never "terminal".
 * 3. **An absent timeline section is a missing writer, not silence.** The
 *    `TimelineSourceLegend` sits beside the pipeline, not behind a tab, because
 *    `SOURCE_UNAVAILABLE_LABEL` ("not enabled in this deployment") on `chat` and `payments`
 *    is the difference between "the customer never replied" and "we do not capture chat",
 *    and only one of those closes a ticket correctly. `stateTransitions` is labelled
 *    `inferred` — a third answer, distinct from both available and unavailable.
 * 4. **The plan is inferred.** Seven of the eleven stages write no attempt row at all, so
 *    most of a healthy plan is `not_observed`.
 *
 * ## The poll
 *
 * §11.5: 3 s while the order is in flight, off otherwise. `IN_FLIGHT_ORDER_STATES` is the
 * shipped enum's answer to §11.5's `{authorized, generating, held_for_review}` — there is no
 * held state on this build, so the condition is two states, and `enums.ts` says so where the
 * constant is defined. A delivered order polls at NO interval: nothing about it will change
 * again, and a 3 s tick on a finished order is a request per operator per second for
 * nothing.
 *
 * The attempt ledger reads the SUB-COLLECTION endpoint (`/orders/{id}/attempts`) rather than
 * `OrderDetailView.attempts`, because that is an unpaged whole-collection array and a busy
 * order's attempt ledger is not a thing to render in full.
 *
 * ## No tabs
 *
 * The ledger used to sit behind an `attempts` tab whose query was `enabled` only while the
 * tab was open — with `timeline` the default. So the operator who opened an order to ask
 * "how many times did this fail?" saw nothing, and nothing was even fetched. It is a sibling
 * of the stepper and the deliverables card now, on the page on arrival. The `assets` tab went
 * with it: it rendered the same rows the deliverables card above it already rendered, and two
 * answers to one question is the "three disjointed tabs" defect this page was reskinned to
 * remove. `orderDetailParams.ts` says what happens to a link that still names one.
 *
 * ## The reskin
 *
 * The page is a stack of borderless cards grouped under plain sentence-case labels —
 * `Pipeline`, `Order`, `Record` — set on the page ground above them. The labels are `<p>`s,
 * not headings: `PipelineTimeline`, `TimelineSourceLegend` and `LyricSheetPanel` each own their
 * own `<h2>`/`<h3>` inside their own card, and the screen still has exactly one `<h1>`.
 *
 * Three things the new geometry changed, each for a reason:
 *
 *  - **The tab strip left the card, and then left altogether.** It was a row of outlined
 *    boxes above a `border-b` inside the panel, then a segmented row of soft pills on the
 *    ground; now each section's own content is simply the card — the attempt ledger renders a
 *    `DataTable`, which supplies one, and a card inside a card would have been the result of
 *    keeping the wrapper either way.
 *  - **The timeline list lost its rules.** `divide-y divide-line` is gone: events are
 *    separated by space and a hover ground, which is this design's list idiom. `inferred` is
 *    a tinted pill rather than a bare cyan word, so the one flag on the row that changes what
 *    the row MEANS is not carried by hue alone.
 *  - **The attempt ledger's ✓/✗ moved onto the semantic families.** `--success` and
 *    `--error` are text-safe on every ground in both palettes; the old `--green` / `--red`
 *    are gone from the palette entirely. The glyph is still doing the work — those two hues
 *    are within a point of the same luminance in the light theme by construction, so a
 *    greyscale reader has the mark and nothing else.
 *
 * The breadcrumb under the title reads `Home / Orders / Detail`. It is derived from the
 * route by `breadcrumbs.ts`, whose stated rule is that a crumb is one of our own labels and
 * never an id — see this task's report for the one place that rule and the brief disagree.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, type ReactElement, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import {
  DEFAULT_PAGE_LIMIT,
  IN_FLIGHT_ORDER_STATES,
  MIN_PAGE_LIMIT,
  getOrder,
  getOrderAttempts,
  getOrderTimeline,
  getUser,
  getUserCredits,
  unwrapAsync,
  type AssetWireView,
  type AttemptWireView,
  type OrderAttemptsQuery,
  type OrderLedgerStatus,
  type OrderPaymentRail,
  type PageQuery,
  type TimelineEventView,
  type UserCreditsQuery,
} from "@/api";
import {
  CursorPager,
  DataTable,
  Timestamp,
  type DataColumn,
} from "@/components/data";
import {
  ATTEMPT_REVEAL_FIELDS,
  BRIEF_REVEAL_FIELDS,
  CorrelationChip,
  CreditBalanceChip,
  ErrorCodeBadge,
  GrantCreditsButton,
  NameText,
  OrderRefChip,
  PipelineTimeline,
  PurgedValue,
  RetentionClocks,
  RevealButton,
  StatusPill,
  TelegramUserChip,
  TimelineSourceLegend,
  assetTrack,
  briefRetentionClocks,
  isAudioAsset,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import {
  AsyncBoundary,
  Button,
  EmptyState,
  Skeleton,
  SkeletonTable,
} from "@/components/util";
import { LyricSheetPanel } from "@/features/assets/LyricSheetPanel";
import { usePlayerStore } from "@/lib/stores";
import {
  EMPTY_VALUE,
  NO_POLLING,
  POLL_MS,
  cn,
  formatCostUsd,
  formatDurationS,
  formatInteger,
  formatLatencyMs,
  formatRate,
  humaniseEnum,
  pollWhileVisible,
  queryKeys,
  useSearchParamsState,
} from "@/lib";

import { IDENTITY_CLOCK_LABEL } from "./orderColumns";
import {
  ORDER_DETAIL_FALLBACK,
  orderDetailParser,
  type OrderDetailParams,
} from "./orderDetailParams";

/**
 * The Customer 360 card wants the ACCOUNT, not the ledger, so it asks for the smallest legal
 * page. The movements themselves are the user screen's table, and duplicating them here would
 * be a second place for them to disagree.
 */
const CUSTOMER_CREDITS_QUERY: UserCreditsQuery = { limit: MIN_PAGE_LIMIT };

/**
 * The companion to `isAudioAsset`: what the artefact is FOR, not what it is stored as.
 *
 * `isAudioAsset` selects `song` / `greeting` and therefore excludes the lyric sheet, which is
 * why the deliverables card rendered an approval badge and never a word of the lyric. Whether
 * `/assets/{id}/text` will actually serve the row is a MIME question, and `LyricSheetPanel`
 * asks it — the same split `mediaKinds.ts` argues.
 */
function isLyricAsset(asset: AssetWireView): boolean {
  return asset.kind === "lyric_sheet";
}

/**
 * No `lyric_sheet` row, said as a fact rather than drawn as a missing panel.
 *
 * It is not the same fact as "the lyrics are not approved", which the badge above it states,
 * and it is not an error: the sheet is written by the lyric stage, so an order that has not
 * reached it has nothing to show.
 */
const LYRIC_SHEET_ABSENT_LABEL =
  "No lyric sheet has been rendered for this order, so there is nothing to reveal.";

/** What each ledger status means, in the algebra the authorisation gate itself uses. */
const LEDGER_STATUS_TITLES: Readonly<Record<OrderLedgerStatus, string>> = {
  unmetered: "No ledger row references this order at all. Unmetered — which is not the same as free.",
  pending:
    "A debit stands open with no consume: the render is in flight, or it died without settling. This holds a credit the customer cannot see.",
  settled: "The charge stands and was closed by a consume row.",
  refunded:
    "Net zero or better, with a refund. This is NOT an ending — net 0 is precisely what makes the order chargeable again on its next attempt.",
};

/** What paid, restricted to what the ledger can actually prove. */
const PAYMENT_RAIL_TITLES: Readonly<Record<OrderPaymentRail, string>> = {
  none: "No ledger row references this order. Unmetered, NOT free.",
  credits: "A charge stands or stood against this order: the customer's balance paid.",
  unenforced:
    "credits_enforced was off and the account could not afford the render, so the shortfall was minted. Nobody paid — a configuration flag did.",
};

/**
 * The two things a bare `retryCount` would let an operator believe, both wrong.
 *
 * It counts ATTEMPTS, so one clean render is `1` rather than `0`; and every row it can count
 * today is a name-verification verdict, because nothing in `src/` writes a vendor-render
 * attempt yet. A delivered three-song order therefore reports `0` honestly. Rendered as a
 * bare number beside "retries", that reads as "this order never had any trouble".
 */
const ATTEMPTS_RECORDED_CAVEAT =
  "Attempts, not retries — one clean render is 1. And only name-verification attempts are written today, so a delivered order can honestly read 0 until the render pipeline records its own.";

/**
 * What a FAILED credits request says, which is nothing about the account.
 *
 * `<CreditBalanceChip balance={null}>` is a positive claim — "no `credit_accounts` row at
 * all" — and a query that errored has `data === undefined`, which a `?? null` would launder
 * into exactly that claim. The endpoint 404s for an id neither table has heard of and 5xxs
 * on a blip, and "never metered" read off either is how a customer holding four credits gets
 * comped a second time. Unknown is its own answer, and it is this one.
 */
const CREDIT_BALANCE_UNREADABLE = "could not read the balance";

const CREDIT_BALANCE_UNREADABLE_HINT =
  "The credits request failed, so this account's balance is unknown. It is NOT 'never metered' and NOT 0 — neither of those has been established.";

export function OrderDetailScreen(): ReactElement {
  const routeParams = useParams<{ orderId: string }>();
  const orderId = routeParams.orderId ?? "";
  const isRoutable = orderId !== "";

  const view = useSearchParamsState<OrderDetailParams>(
    orderDetailParser,
    ORDER_DETAIL_FALLBACK,
  );
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: queryKeys.orders.detail(orderId),
    queryFn: ({ signal }) => unwrapAsync(getOrder(orderId, { signal })),
    enabled: isRoutable,
    // Read from the query's OWN state rather than from a render-scoped variable: on the
    // render that first receives a `generating` order there is no variable yet, and one
    // missed tick on the screen that exists to watch an order move is the wrong default.
    refetchInterval: (query) => {
      const state = query.state.data?.order.state;
      const isInFlight = state !== undefined && IN_FLIGHT_ORDER_STATES.includes(state);
      return pollWhileVisible(isInFlight ? POLL_MS.orderDetail : NO_POLLING)();
    },
  });

  const order = detail.data?.order ?? null;
  const isInFlight = order !== null && IN_FLIGHT_ORDER_STATES.includes(order.state);
  const detailInterval = pollWhileVisible(isInFlight ? POLL_MS.orderDetail : NO_POLLING);

  const timeline = useQuery({
    queryKey: queryKeys.orders.timeline(orderId),
    queryFn: ({ signal }) => unwrapAsync(getOrderTimeline(orderId, { signal })),
    enabled: isRoutable,
    refetchInterval: detailInterval,
  });

  const pageQuery: PageQuery = useMemo(
    () => ({ limit: view.value.limit ?? DEFAULT_PAGE_LIMIT, cursor: view.value.cursor }),
    [view.value.limit, view.value.cursor],
  );
  const attemptsQuery: OrderAttemptsQuery = pageQuery;

  // No longer `enabled` on a tab: "how many times did this fail, and why" is one of the two
  // questions this screen exists for, and gating its fetch on a tab nobody opens by default
  // meant the answer was never even requested.
  const attempts = useQuery({
    queryKey: queryKeys.orders.attempts(orderId, attemptsQuery),
    queryFn: ({ signal }) => unwrapAsync(getOrderAttempts(orderId, attemptsQuery, { signal })),
    enabled: isRoutable,
    refetchInterval: detailInterval,
  });

  /*
   * The customer's side of the order, which `OrderDetailView` does not carry: `GET
   * /users/{id}/credits` for the balance and `GET /users/{id}` for how many orders this is
   * one of. Both are keyed off the order's own Telegram id, so neither can run until the
   * order has arrived — `customerId` is `null` until then and both queries are disabled.
   *
   * The credits page is asked for ONE row: the account is what the card renders, and the
   * ledger itself lives on the user's own screen. `account: null` there is "never metered"
   * and NOT a balance of 0 — `<CreditBalanceChip>` is the component that keeps those apart.
   */
  const customerId = order?.telegramUserId ?? null;

  const credits = useQuery({
    queryKey: queryKeys.users.credits(customerId ?? 0, CUSTOMER_CREDITS_QUERY),
    queryFn: ({ signal }) =>
      unwrapAsync(getUserCredits(customerId ?? 0, CUSTOMER_CREDITS_QUERY, { signal })),
    enabled: customerId !== null,
  });

  // 404s for a Telegram id with no `users` row — which a credited account can legitimately
  // be — so the order count is rendered as absent rather than as zero when this fails.
  const customer = useQuery({
    queryKey: queryKeys.users.detail(customerId ?? 0),
    queryFn: ({ signal }) => unwrapAsync(getUser(customerId ?? 0, { signal })),
    enabled: customerId !== null,
    retry: false,
  });

  if (!isRoutable) {
    return (
      <EmptyState
        title="no order id"
        body="This URL carries no order id. Open an order from /orders."
      />
    );
  }

  const brief = detail.data?.brief ?? null;
  const audioAssets = (detail.data?.assets ?? []).filter(isAudioAsset);
  const lyricAsset = detail.data?.assets.find(isLyricAsset) ?? null;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Order"
        description="Where is it, or exactly where did it die?"
        signal={
          order === null ? null : (
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill state={order.state} size="md" />
              {order.failedReason === null ? null : (
                <ErrorCodeBadge
                  code={order.failedReason}
                  isRetryable={order.isFailedReasonRetryable}
                />
              )}
            </div>
          )
        }
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <OrderRefChip orderId={orderId} visibleChars={36} />
            {/*
              §12.3's two reveal shapes, as two controls rather than one, because the server
              refuses a request that mixes them: one `recordCount` cannot honestly describe
              both a brief column (ONE record, whichever of the six are ticked) and a page of
              attempt free text (fifty records plus a conversation). Two buttons is the honest
              shape of that rule; a single dialog with a hidden mode switch would let an
              operator build a request the server was always going to refuse.

              `RevealButton` carries its own `PermissionGate`, so a VIEWER sees neither —
              §11.4's rule is HIDING, and a greyed control here would invite the click that
              writes a `permission.denied` audit row out of curiosity.

              `subjectLabel` is the order reference: OUR text. A recipient name must never be
              the label of the dialog that exists to reveal it.
            */}
            <RevealButton
              subjectType="order"
              subjectId={orderId}
              subjectLabel={`${orderId.slice(0, 8)}\u2026`}
              fields={BRIEF_REVEAL_FIELDS}
              label="Reveal the brief"
            />
            <RevealButton
              subjectType="order"
              subjectId={orderId}
              subjectLabel={`${orderId.slice(0, 8)}\u2026`}
              fields={ATTEMPT_REVEAL_FIELDS}
              label="Reveal attempt free text"
            />
          </div>
        }
      />

      <div className="px-gutter pb-gutter">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left column (65-70%): Fulfillment Stepper Timeline + Deliverables Card + Attempts table */}
          <div className="flex flex-col gap-6 lg:col-span-8">
            {/* Fulfillment Stepper Timeline */}
            <section
              className="flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card"
              aria-label="fulfillment pipeline"
            >
              <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-hairline pb-3">
                <h3 className="type-h3 text-ink">Fulfillment & Generation Pipeline</h3>
                <span className="type-caption text-ink-muted">Nine-stage generation plan</span>
              </header>
              <AsyncBoundary
                status={detail.status}
                hasData={detail.data !== undefined}
                dataUpdatedAt={detail.dataUpdatedAt}
                error={detail.error}
                onRetry={() => {
                  void detail.refetch();
                }}
                noun="the pipeline"
                skeleton={<Skeleton height="14rem" />}
              >
                {detail.data === undefined ? null : (
                  <PipelineTimeline plan={detail.data.stagePlan} />
                )}
              </AsyncBoundary>
            </section>

            {/* Deliverables Card with inline audio player & lyric sheet preview */}
            <section
              className="flex flex-col gap-4 rounded-card bg-surface-card p-card shadow-card"
              aria-label="deliverables"
            >
              <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-hairline pb-3">
                <h3 className="type-h3 text-ink">Deliverables & Media Preview</h3>
                <span className="type-caption text-ink-muted num">
                  {formatInteger(order?.assetCount ?? 0)}{" "}
                  {(order?.assetCount ?? 0) === 1 ? "asset" : "assets"}
                </span>
              </header>

              {/* Audio deliverables. The emptiness that matters is "no AUDIO", not "no
                  assets": an order whose only row is the lyric sheet has assets and no song,
                  and the sentence below has to be the one about the song. */}
              {audioAssets.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {audioAssets.map((asset) => (
                    <div
                      key={asset.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-control bg-surface-sunken p-3"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="text-xl" aria-hidden="true">
                          🎵
                        </span>
                        <div className="min-w-0">
                          <p className="type-body font-medium truncate text-ink">
                            Birthday Song{" "}
                            {asset.variantIndex > 0 ? `(Variant ${String(asset.variantIndex)})` : ""}
                          </p>
                          <p className="type-caption text-ink-muted">
                            {formatDurationS(asset.durationS)} · {asset.mime}
                          </p>
                        </div>
                      </div>
                      <Button
                        variant="secondary"
                        size="xs"
                        shape="pill"
                        onClick={() => {
                          usePlayerStore.getState().requestPlay(assetTrack(asset));
                        }}
                      >
                        ▶ Play in player
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="type-body-sm flex items-center gap-3 rounded-control bg-surface-sunken p-4 text-ink-muted">
                  <span className="text-lg" aria-hidden="true">
                    🎵
                  </span>
                  <span>
                    {order?.state === "delivered"
                      ? "No audio assets recorded in this view."
                      : "Song rendering in progress or not yet completed."}
                  </span>
                </div>
              )}

              {/*
                Lyrics. The approval badge is the HEADER of this block and stays exactly where
                it was — `hasApprovedLyrics` is a brief fact and answers a different question
                from the sheet ("is this signed off" vs "what does it say"). Underneath it,
                the sheet itself: `LyricSheetPanel` carries its own `reveal.media` gate, its
                own step-up prompt and its own Hide, and none of that is re-implemented here.
                Every read of it is charged and audited, so nothing is fetched until the
                operator asks.
              */}
              <div className="flex flex-col gap-2 rounded-control bg-surface-sunken p-3">
                <div className="flex items-center justify-between">
                  <span className="type-caption font-semibold uppercase tracking-wider text-ink-muted">
                    Approved Lyrics
                  </span>
                  {brief === null ? null : (
                    <span
                      className={cn(
                        "type-caption rounded-pill px-2 py-0.5 font-medium",
                        brief.hasApprovedLyrics
                          ? "bg-success-tint text-success"
                          : "bg-caution-tint text-caution",
                      )}
                    >
                      {brief.hasApprovedLyrics ? "✓ Approved" : "Pending Approval"}
                    </span>
                  )}
                </div>
                {brief === null ? null : (
                  <div className="type-body-sm flex flex-wrap gap-x-4 gap-y-1 text-ink-muted">
                    <span>
                      Language:{" "}
                      <strong className="font-medium text-ink">
                        {humaniseEnum(brief.outputLanguage)}
                      </strong>
                    </span>
                    {brief.noteChars !== null && (
                      <span>
                        Note length:{" "}
                        <strong className="num font-medium text-ink">
                          {formatInteger(brief.noteChars)} chars
                        </strong>
                      </span>
                    )}
                  </div>
                )}

                {lyricAsset === null ? (
                  <p className="type-body-sm text-ink-muted" data-testid="lyric-sheet-absent">
                    <span className="text-ink-muted">{EMPTY_VALUE}</span>{" "}
                    {LYRIC_SHEET_ABSENT_LABEL}
                  </p>
                ) : (
                  <LyricSheetPanel asset={lyricAsset} className="shadow-none" />
                )}
              </div>
            </section>

            {/*
              The attempt ledger, hoisted out of the retired tabset: on the page on arrival,
              beside the stepper and the deliverables card, because "where did it die" is
              answered here and nowhere else.
            */}
            <section className="flex flex-col gap-3" aria-label="attempt ledger">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                <p className="type-h3 text-ink">Attempts</p>
                <span className="type-caption text-ink-muted">
                  Seven of the eleven stages write no attempt row
                </span>
              </div>
              <AsyncBoundary
                status={attempts.status}
                hasData={attempts.data !== undefined}
                isEmpty={(attempts.data?.items.length ?? 0) === 0}
                dataUpdatedAt={attempts.dataUpdatedAt}
                error={attempts.error}
                onRetry={() => {
                  void attempts.refetch();
                }}
                noun="attempts"
                emptyTitle="no attempts recorded"
                emptyBody="Seven of the eleven pipeline stages write no attempt row, so an empty ledger does not mean nothing ran."
                skeleton={<SkeletonTable rows={8} columns={ATTEMPT_COLUMNS.length} withHeader />}
              >
                <DataTable
                  data={attempts.data?.items ?? []}
                  columns={ATTEMPT_COLUMNS}
                  label="generation attempts"
                  getRowId={(attempt) => attempt.id}
                  isRefetching={attempts.isFetching}
                  footer={
                    <CursorPager
                      meta={attempts.data?.meta ?? null}
                      itemCount={attempts.data?.items.length ?? 0}
                      cursor={view.value.cursor ?? null}
                      onCursorChange={(cursor) => {
                        view.patch({ cursor: cursor ?? undefined }, { keepCursor: true });
                      }}
                      limit={view.value.limit ?? DEFAULT_PAGE_LIMIT}
                      onLimitChange={(limit) => {
                        view.patch({ limit });
                      }}
                      isFetching={attempts.isFetching}
                      label="attempts"
                    />
                  }
                />
              </AsyncBoundary>
            </section>

            {/* Record — the merged timeline, no longer one of three tabs */}
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                <p className="type-h3 text-ink">Record</p>
                <span className="type-caption text-ink-muted">Merged event timeline</span>
              </div>

              <AsyncBoundary
                status={timeline.status}
                hasData={timeline.data !== undefined}
                isEmpty={(timeline.data?.events.length ?? 0) === 0}
                dataUpdatedAt={timeline.dataUpdatedAt}
                error={timeline.error}
                onRetry={() => {
                  void timeline.refetch();
                }}
                noun="timeline events"
                emptyTitle="nothing recorded"
                emptyBody="No source in this deployment recorded an event for this order. See the sources legend above — an empty section is a missing writer, not silence."
                skeleton={<SkeletonTable rows={6} columns={4} withHeader />}
              >
                <TimelineEvents events={timeline.data?.events ?? []} />
              </AsyncBoundary>
            </div>
          </div>

          {/* Right column (30-35%): Customer 360 Card + Retention Clocks + Correlation/Diagnostics */}
          <div className="flex flex-col gap-6 lg:col-span-4">
            {/* Customer 360 Card */}
            <AsyncBoundary
              status={detail.status}
              hasData={detail.data !== undefined}
              dataUpdatedAt={detail.dataUpdatedAt}
              error={detail.error}
              onRetry={() => {
                void detail.refetch();
              }}
              noun="this order"
              skeleton={<Skeleton height="18rem" />}
            >
              {order === null ? null : (
                <section
                  aria-label="order facts"
                  className="flex flex-col gap-4 rounded-card bg-surface-card p-card shadow-card"
                >
                  <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-hairline pb-3">
                    <h3 className="type-h3 text-ink">Customer 360</h3>
                    {/*
                      The same dialog the users screen offers, gated on `credit.grant.write`
                      inside the button, so a VIEWER sees nothing here at all (§11.4 hides).
                      It invalidates everything under `users` itself — the balance chip beside
                      this header included — and `onSuccess` is for the key it cannot know
                      about: this order, whose own financial row moves with the account.
                    */}
                    <GrantCreditsButton
                      telegramUserId={order.telegramUserId}
                      subjectLabel={order.telegramUserIdMasked}
                      onSuccess={() => {
                        void queryClient.invalidateQueries({
                          queryKey: queryKeys.orders.detail(orderId),
                        });
                      }}
                    />
                  </header>

                  <dl className="flex flex-col gap-3">
                    <Fact label="customer">
                      <TelegramUserChip
                        telegramUserId={order.telegramUserId}
                        telegramUserIdMasked={order.telegramUserIdMasked}
                      />
                    </Fact>
                    <Fact label="credit balance">
                      {/*
                        `account: null` is "never metered" and NOT a balance of 0 — a customer
                        who was never charged or granted anything, or one whose `/forget`
                        deleted the row. The chip is the component that keeps the three states
                        apart; `undefined` while the page is still in flight claims nothing.
                      */}
                      {credits.isPending ? (
                        // A `<Fact>`'s value is a paragraph, so this placeholder is inline
                        // text rather than a block skeleton — and it claims nothing about the
                        // account while the answer is still in flight.
                        <span className="type-body-sm text-ink-muted">{"checking\u2026"}</span>
                      ) : credits.data === undefined ? (
                        // Settled with no answer \u2014 a 404, a 5xx, a dropped connection. The
                        // chip is deliberately NOT drawn: see `CREDIT_BALANCE_UNREADABLE`.
                        <span className="flex flex-wrap items-center gap-2">
                          <span
                            data-testid="credit-balance-unreadable"
                            title={CREDIT_BALANCE_UNREADABLE_HINT}
                            className="type-body-sm text-ink-muted"
                          >
                            {`${EMPTY_VALUE} ${CREDIT_BALANCE_UNREADABLE}`}
                          </span>
                          <Button
                            variant="quiet"
                            size="xs"
                            onClick={() => {
                              void credits.refetch();
                            }}
                          >
                            Try again
                          </Button>
                        </span>
                      ) : (
                        <CreditBalanceChip balance={credits.data.account?.balance ?? null} size="md" />
                      )}
                    </Fact>
                    <Fact label="orders placed">
                      {customer.data === undefined ? (
                        <span className="text-ink-muted">{EMPTY_VALUE}</span>
                      ) : (
                        <span className="num">{formatInteger(customer.data.user.orderCount)}</span>
                      )}
                    </Fact>
                    <Fact label="recipient">
                      <NameText
                        value={order.recipientName}
                        isToggleable
                        fallback={
                          <PurgedValue
                            purgedAt={order.identityPurgedAt}
                            isPurged={order.isIdentityPurged}
                            clock={IDENTITY_CLOCK_LABEL}
                            isBreakable
                          />
                        }
                      />
                    </Fact>
                    <Fact label="financial status">
                      <span className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-pill px-2.5 py-0.5 type-caption font-medium",
                            order.isPaid ? "bg-success-tint text-success" : "bg-neutral-tint text-neutral",
                          )}
                        >
                          {order.isPaid ? "✓ Paid" : "Unpaid"}
                        </span>
                        {/*
                          The ledger's own answer, which is not the same question as `isPaid`:
                          `refunded` is net zero WITH a refund, and net zero is precisely what
                          makes the order chargeable again — so it is not drawn as an ending.
                          The word carries the state; the title carries the algebra.
                        */}
                        <span
                          data-testid="ledger-status"
                          data-status={order.ledgerStatus}
                          title={LEDGER_STATUS_TITLES[order.ledgerStatus]}
                          className="inline-flex items-center rounded-pill bg-surface-sunken px-2.5 py-0.5 type-caption font-medium text-ink"
                        >
                          {humaniseEnum(order.ledgerStatus)}
                        </span>
                      </span>
                    </Fact>
                    <Fact label="credits charged">
                      {/* "charged", never "spent": this is `-SUM(delta)` as it stands RIGHT
                          NOW, so a refunded order reads 0 — history has not been rounded off,
                          the charge has been reversed. */}
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="num" data-testid="credit-cost">
                          {formatInteger(order.creditCost)}
                        </span>
                        <span
                          data-testid="payment-rail"
                          data-rail={order.paymentRail}
                          title={PAYMENT_RAIL_TITLES[order.paymentRail]}
                          className="type-caption text-ink-muted"
                        >
                          {`rail: ${humaniseEnum(order.paymentRail)}`}
                        </span>
                      </span>
                    </Fact>
                    <Fact label="attempts recorded">
                      {/* A bare `0` here would read as "this order never had any trouble",
                          which is the one thing it does not mean. The caveat travels with the
                          number rather than living in a doc nobody opens. */}
                      <span className="flex flex-col gap-1">
                        <span className="num" data-testid="retry-count">
                          {formatInteger(order.retryCount)}
                        </span>
                        <span className="type-caption text-ink-muted">
                          {ATTEMPTS_RECORDED_CAVEAT}
                        </span>
                      </span>
                    </Fact>
                    <Fact label="occasion & genre">
                      <span className="text-ink">
                        {order.occasion === null ? EMPTY_VALUE : humaniseEnum(order.occasion)}
                        {" · "}
                        {order.genre === null ? EMPTY_VALUE : humaniseEnum(order.genre)}
                      </span>
                    </Fact>
                    <Fact label="output language">
                      <span className="text-ink">
                        {order.outputLanguage === null
                          ? EMPTY_VALUE
                          : humaniseEnum(order.outputLanguage)}
                      </span>
                    </Fact>
                    <Fact label="assets count">
                      <span className="num">{formatInteger(order.assetCount)}</span>
                    </Fact>
                    <Fact label="created">
                      <Timestamp at={order.createdAt} seconds />
                    </Fact>
                    <Fact label="updated">
                      <Timestamp at={order.updatedAt} seconds />
                    </Fact>
                    <Fact label="delivered">
                      {order.deliveredAt === null ? (
                        <span className="text-ink-muted">{EMPTY_VALUE}</span>
                      ) : (
                        <Timestamp at={order.deliveredAt} seconds />
                      )}
                    </Fact>
                    <Fact label="note">
                      <PurgedValue purgedAt={order.notePurgedAt} clock="note retention" isBreakable>
                        <span>
                          {brief === null || brief.noteChars === null ? (
                            EMPTY_VALUE
                          ) : (
                            <>
                              <span className="num">{formatInteger(brief.noteChars)}</span>
                              {" characters"}
                            </>
                          )}
                        </span>
                      </PurgedValue>
                    </Fact>
                  </dl>
                </section>
              )}
            </AsyncBoundary>

            {/* Retention Clocks */}
            {brief !== null && (
              <section
                aria-label="retention clocks"
                className="flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card"
              >
                <header className="border-b border-hairline pb-2">
                  <h3 className="type-h3 text-ink">Retention & Privacy Clocks</h3>
                </header>
                <RetentionClocks clocks={briefRetentionClocks(brief)} />
              </section>
            )}

            {/* Correlation & Diagnostics */}
            <section
              aria-label="diagnostics"
              className="flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card"
            >
              <header className="border-b border-hairline pb-2">
                <h3 className="type-h3 text-ink">Correlation & Diagnostics</h3>
              </header>
              <dl className="flex flex-col gap-3">
                <Fact label="correlation id">
                  <CorrelationChip correlationId={order?.correlationId ?? ""} />
                </Fact>
                <Fact label="order reference">
                  <OrderRefChip orderId={orderId} visibleChars={16} />
                </Fact>
                {order?.failedReason != null && (
                  <Fact label="failure code">
                    <ErrorCodeBadge
                      code={order.failedReason}
                      isRetryable={order.isFailedReasonRetryable}
                    />
                  </Fact>
                )}
              </dl>

              <div className="border-t border-hairline pt-3">
                <p className="type-caption text-ink-muted mb-2 font-semibold uppercase tracking-wider">
                  Timeline Sources
                </p>
                <AsyncBoundary
                  status={timeline.status}
                  hasData={timeline.data !== undefined}
                  dataUpdatedAt={timeline.dataUpdatedAt}
                  error={timeline.error}
                  onRetry={() => {
                    void timeline.refetch();
                  }}
                  noun="the timeline sources"
                  skeleton={<Skeleton height="8rem" />}
                >
                  {timeline.data === undefined ? null : (
                    <TimelineSourceLegend
                      availableSources={timeline.data.availableSources}
                      unavailableSources={timeline.data.unavailableSources}
                    />
                  )}
                </AsyncBoundary>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}



/**
 * The merged timeline.
 *
 * `isInferred` is on the row, not in a footnote: an inferred event is derived from what
 * other sources recorded, and an operator reading the list as a log will treat an absence as
 * evidence. `label` is a closed vocabulary, never free text.
 *
 * Rows are separated by space and a hover ground rather than by a `divide-y` rule. The hover
 * ground is safe here and is NOT safe under a status pill or an error badge: `--ink` on
 * `--info-tint` is 6.38:1 over `--surface-control`, whereas a family's own hue on its own
 * tint drops to about 4.2:1 on that ground — the token layer measures tints over
 * `--surface-card` and `--surface` only. That is exactly why the `inferred` chip is the
 * palette's recommended shape: the WORD in `--ink` on `--info-tint`, with the hue on the
 * aria-hidden mark, where 1.4.11's 3:1 governs. The flag that changes what a row MEANS is a
 * shape and a word before it is a colour.
 */
function TimelineEvents({
  events,
}: {
  readonly events: readonly TimelineEventView[];
}): ReactElement {
  return (
    // The list supplies its own card: the tab strip left the panel, so each tab's content is
    // the surface now.
    <ol className="flex flex-col gap-0.5 rounded-card bg-surface-card p-4 shadow-card">
      {events.map((event, index) => (
        <li
          key={`${event.at}:${event.kind}:${String(index)}`}
          data-testid="timeline-event"
          data-kind={event.kind}
          data-source={event.source}
          className={cn(
            "flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-control px-2 py-2",
            "transition-colors duration-fast ease-standard hover:bg-surface-control",
          )}
        >
          <span className="type-body-sm num min-w-[13rem] text-ink-muted">
            <Timestamp at={event.at} seconds />
          </span>
          <span className="type-body-sm text-ink">{humaniseEnum(event.kind)}</span>
          <span className="type-body-sm text-ink-muted">{humaniseEnum(event.source)}</span>
          {event.isInferred && (
            <span className="type-body-sm inline-flex items-center gap-1 rounded-pill bg-info-tint px-2 py-0.5 text-ink">
              {/* `≈` — derived, not recorded. Deliberately NOT one of §11.3's nine status
                  glyphs: those name an order state and this names a provenance. */}
              <span aria-hidden="true" className="text-info">
                ≈
              </span>
              inferred
            </span>
          )}
          {event.label === null ? null : (
            <span className="type-body-sm text-ink-muted">{humaniseEnum(event.label)}</span>
          )}
        </li>
      ))}
    </ol>
  );
}

/**
 * The attempt ledger.
 *
 * `costUsd` and `latencyMs` are `null` — never `0` — when `isInstrumented` is false, which is
 * every row in production today; `formatCostUsd`/`formatLatencyMs` render "not instrumented"
 * rather than `$0.00 / 0 ms`, which would tell an operator the call was free and instant.
 * `nameCandidate` arrives masked (`G•••`) and goes through `NameText` all the same — the
 * mask is still a name-shaped string and the codepoint toggle is still the answer to "which
 * apostrophe did they type".
 */
const ATTEMPT_COLUMNS: readonly DataColumn<AttemptWireView>[] = [
  {
    id: "kind",
    header: "kind",
    isNumeric: false,
    width: "9rem",
    cell: (attempt) => humaniseEnum(attempt.kind),
  },
  {
    id: "sequence",
    header: "seq",
    isNumeric: true,
    width: "4.5rem",
    headerTitle: "sequence.attempt",
    cell: (attempt) => `${String(attempt.sequence)}.${String(attempt.attempt)}`,
  },
  {
    id: "provider",
    header: "provider",
    isNumeric: false,
    width: "8rem",
    cell: (attempt) => attempt.provider ?? EMPTY_VALUE,
  },
  {
    id: "isSuccess",
    header: "ok",
    isNumeric: false,
    width: "3.5rem",
    cell: (attempt) => (
      /* `--success` / `--error`, the text-safe members of the two semantic families: both
         clear 4.5:1 on every ground in both palettes, so neither is a policed token. They
         are also within a point of the same luminance in the light theme by construction,
         which is exactly why the ✓ / ✗ glyph — not the hue — is what says which this is. */
      <span className={attempt.isSuccess ? "text-success" : "text-error"}>
        {attempt.isSuccess ? "✓" : "✗"}
      </span>
    ),
  },
  {
    id: "nameCandidate",
    header: "candidate",
    isNumeric: false,
    width: "10rem",
    cell: (attempt) => (
      <NameText
        value={attempt.nameCandidate}
        fallback={
          <PurgedValue purgedAt={attempt.identityPurgedAt} clock={IDENTITY_CLOCK_LABEL} />
        }
      />
    ),
  },
  {
    id: "isNameVerified",
    header: "verified",
    isNumeric: false,
    width: "8rem",
    cell: (attempt) =>
      attempt.isNameVerified === null ? (
        <span className="text-ink-muted">{EMPTY_VALUE}</span>
      ) : (
        <span className="flex items-baseline gap-1.5">
          {/* `--caution` is the softer attention hue: an unverified candidate is a thing to
              look at, not a partial outage. Both members are text-safe. */}
          <span className={attempt.isNameVerified ? "text-success" : "text-caution"}>
            {attempt.isNameVerified ? "verified" : "not verified"}
          </span>
          {attempt.matchConfidence === null ? null : (
            <span className="num text-ink-muted">{formatRate(attempt.matchConfidence, 0)}</span>
          )}
        </span>
      ),
  },
  {
    id: "error",
    header: "error",
    isNumeric: false,
    width: "16rem",
    cell: (attempt) =>
      attempt.errorCode === null && attempt.errorMessage === null ? (
        <span className="text-ink-muted">{EMPTY_VALUE}</span>
      ) : (
        <ErrorCodeBadge
          code={attempt.errorCode}
          isRetryable={attempt.isRetryable}
          message={attempt.errorMessage}
          size="sm"
        />
      ),
  },
  {
    id: "latency",
    header: "latency",
    isNumeric: true,
    width: "8rem",
    cell: (attempt) => formatLatencyMs(attempt.latencyMs, attempt.isInstrumented),
  },
  {
    id: "cost",
    header: "cost",
    isNumeric: true,
    width: "8rem",
    cell: (attempt) => formatCostUsd(attempt.costUsd, attempt.isInstrumented),
  },
  {
    id: "createdAt",
    header: "created",
    isNumeric: true,
    width: "11rem",
    cell: (attempt) => <Timestamp at={attempt.createdAt} seconds />,
  },
];

function Fact({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    /*
     * `min-w-0` and `break-words`: a grid item's default `min-width: auto` is its content's
     * min-content width, so one long unbreakable value (a purged cell's sentence, a raw id)
     * used to push its ink out of a `minmax(0,1fr)` track and print over the next column.
     * The track is fixed; the CELL has to be the thing that gives.
     */
    <div className="flex min-w-0 flex-col gap-1">
      {/* A muted label over the value, in sentence case rather than uppercase micro-caps. */}
      <p className="type-body-sm text-ink-muted">{label}</p>
      <p className="type-body break-words text-ink">{children}</p>
    </div>
  );
}

export const Component = OrderDetailScreen;
