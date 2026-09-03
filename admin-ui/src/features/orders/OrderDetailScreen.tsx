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
 * The attempts and assets tabs read the SUB-COLLECTION endpoints
 * (`/orders/{id}/attempts`, `/orders/{id}/assets`) rather than `OrderDetailView.attempts` /
 * `.assets`, because those are unpaged whole-collection arrays and a busy order's attempt
 * ledger is not a thing to render in full. Each tab's query is `enabled` only while its tab
 * is open, so an operator who never opens assets never fetches them.
 *
 * ## The reskin
 *
 * The page is a stack of borderless cards grouped under plain sentence-case labels —
 * `Pipeline`, `Order`, `Record` — set on the page ground above them. The labels are `<p>`s,
 * not headings: `PipelineTimeline`, `TimelineSourceLegend` and `AssetCard` each own their
 * own `<h2>`/`<h3>` inside their own card, and the screen still has exactly one `<h1>`.
 *
 * Three things the new geometry changed, each for a reason:
 *
 *  - **The tab strip left the card.** It was a row of outlined boxes above a `border-b`
 *    inside the panel; it is now a segmented row of soft pills sitting on the ground, with
 *    the panel below it. That is what lets each tab's own content be the card — the attempts
 *    tab renders a `DataTable`, which supplies one, and a card inside a card would have been
 *    the result of keeping the wrapper.
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

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import {
  DEFAULT_PAGE_LIMIT,
  IN_FLIGHT_ORDER_STATES,
  getOrder,
  getOrderAssets,
  getOrderAttempts,
  getOrderTimeline,
  unwrapAsync,
  type AttemptWireView,
  type OrderAttemptsQuery,
  type PageQuery,
  type TimelineEventView,
} from "@/api";
import {
  CursorPager,
  DataTable,
  Timestamp,
  type DataColumn,
} from "@/components/data";
import {
  ATTEMPT_REVEAL_FIELDS,
  AssetCard,
  BRIEF_REVEAL_FIELDS,
  CorrelationChip,
  ErrorCodeBadge,
  NameText,
  OrderRefChip,
  PipelineTimeline,
  PurgedValue,
  RetentionClocks,
  RevealButton,
  StatusPill,
  TelegramUserChip,
  TimelineSourceLegend,
  briefRetentionClocks,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import {
  AsyncBoundary,
  Button,
  EmptyState,
  segmentVariant,
  Skeleton,
  SkeletonTable,
} from "@/components/util";
import {
  EMPTY_VALUE,
  NO_POLLING,
  POLL_MS,
  cn,
  formatCostUsd,
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
  DETAIL_TABS,
  ORDER_DETAIL_FALLBACK,
  activeTab,
  orderDetailParser,
  type DetailTab,
  type OrderDetailParams,
} from "./orderDetailParams";

export function OrderDetailScreen(): ReactElement {
  const routeParams = useParams<{ orderId: string }>();
  const orderId = routeParams.orderId ?? "";
  const isRoutable = orderId !== "";

  const view = useSearchParamsState<OrderDetailParams>(
    orderDetailParser,
    ORDER_DETAIL_FALLBACK,
  );
  const tab = activeTab(view.value);

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

  const attempts = useQuery({
    queryKey: queryKeys.orders.attempts(orderId, attemptsQuery),
    queryFn: ({ signal }) => unwrapAsync(getOrderAttempts(orderId, attemptsQuery, { signal })),
    enabled: isRoutable && tab === "attempts",
    refetchInterval: detailInterval,
  });

  const assets = useQuery({
    queryKey: queryKeys.orders.assets(orderId, pageQuery),
    queryFn: ({ signal }) => unwrapAsync(getOrderAssets(orderId, pageQuery, { signal })),
    enabled: isRoutable && tab === "assets",
    refetchInterval: detailInterval,
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

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        {/* The top third: the plan, and why a section of the record may be empty. */}
        <Group label="Pipeline">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
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

            <AsyncBoundary
              status={timeline.status}
              hasData={timeline.data !== undefined}
              dataUpdatedAt={timeline.dataUpdatedAt}
              error={timeline.error}
              onRetry={() => {
                void timeline.refetch();
              }}
              noun="the timeline sources"
              skeleton={<Skeleton height="14rem" />}
            >
              {timeline.data === undefined ? null : (
                <TimelineSourceLegend
                  availableSources={timeline.data.availableSources}
                  unavailableSources={timeline.data.unavailableSources}
                />
              )}
            </AsyncBoundary>
          </div>
        </Group>

        <Group label="Order">
          <AsyncBoundary
            status={detail.status}
            hasData={detail.data !== undefined}
            dataUpdatedAt={detail.dataUpdatedAt}
            error={detail.error}
            onRetry={() => {
              void detail.refetch();
            }}
            noun="this order"
            skeleton={<Skeleton height="12rem" />}
          >
            {order === null ? null : (
              <section
                aria-label="order facts"
                className="grid gap-x-6 gap-y-5 rounded-card bg-surface-card p-card shadow-card sm:grid-cols-2 xl:grid-cols-4"
              >
                <Fact label="recipient">
                  <NameText
                    value={order.recipientName}
                    isToggleable
                    fallback={
                      /* `isBreakable`: a fact grid track is `minmax(0,1fr)` and can be
                         narrower than the sentence at a small viewport. It has a third line
                         to give; it has no room to the right. */
                      <PurgedValue
                        purgedAt={order.identityPurgedAt}
                        isPurged={order.isIdentityPurged}
                        clock={IDENTITY_CLOCK_LABEL}
                        isBreakable
                      />
                    }
                  />
                </Fact>
                <Fact label="user">
                  <TelegramUserChip
                    telegramUserId={order.telegramUserId}
                    telegramUserIdMasked={order.telegramUserIdMasked}
                  />
                </Fact>
                <Fact label="correlation">
                  <CorrelationChip correlationId={order.correlationId} />
                </Fact>
                <Fact label="paid">{order.isPaid ? "yes" : "no"}</Fact>
                <Fact label="occasion">
                  {order.occasion === null ? EMPTY_VALUE : humaniseEnum(order.occasion)}
                </Fact>
                <Fact label="genre">
                  {order.genre === null ? EMPTY_VALUE : humaniseEnum(order.genre)}
                </Fact>
                <Fact label="output language">
                  {order.outputLanguage === null ? EMPTY_VALUE : humaniseEnum(order.outputLanguage)}
                </Fact>
                <Fact label="assets">
                  <span className="num">{formatInteger(order.assetCount)}</span>
                </Fact>
                <Fact label="created">
                  <Timestamp at={order.createdAt} seconds />
                </Fact>
                <Fact label="updated">
                  <Timestamp at={order.updatedAt} seconds />
                </Fact>
                <Fact label="delivered">
                  <Timestamp at={order.deliveredAt} seconds />
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
                {brief === null ? null : (
                  <div className="sm:col-span-2 xl:col-span-4">
                    <p className="type-body-sm mb-2 text-ink-muted">retention</p>
                    <RetentionClocks clocks={briefRetentionClocks(brief)} />
                  </div>
                )}
              </section>
            )}
          </AsyncBoundary>
        </Group>

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
            <p className="type-h3 text-ink">Record</p>
            {/* A segmented control on the ground, so each tab's own content can be the card. */}
            <div role="tablist" aria-label="order detail" className="flex flex-wrap gap-1.5">
              {DETAIL_TABS.map((name) => (
                <TabButton
                  key={name}
                  name={name}
                  isActive={tab === name}
                  onSelect={() => {
                    view.patch({ tab: name });
                  }}
                />
              ))}
            </div>
          </div>

          <div role="tabpanel" aria-label={tab}>
            {tab === "timeline" && (
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
            )}

            {tab === "attempts" && (
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
            )}

            {tab === "assets" && (
              <AsyncBoundary
                status={assets.status}
                hasData={assets.data !== undefined}
                isEmpty={(assets.data?.items.length ?? 0) === 0}
                dataUpdatedAt={assets.dataUpdatedAt}
                error={assets.error}
                onRetry={() => {
                  void assets.refetch();
                }}
                noun="assets"
                emptyTitle="no assets"
                emptyBody="Nothing has been rendered for this order yet."
                skeleton={
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {[0, 1, 2].map((slot) => (
                      <Skeleton key={slot} height="13rem" />
                    ))}
                  </div>
                }
              >
                <div className="flex flex-col gap-2">
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {(assets.data?.items ?? []).map((asset) => (
                      <AssetCard key={asset.id} asset={asset} />
                    ))}
                  </div>
                  {/* On the ground rather than in a card: every asset already carries one,
                      and a pager is chrome for the grid, not another panel. */}
                  <CursorPager
                    meta={assets.data?.meta ?? null}
                    itemCount={assets.data?.items.length ?? 0}
                    cursor={view.value.cursor ?? null}
                    onCursorChange={(cursor) => {
                      view.patch({ cursor: cursor ?? undefined }, { keepCursor: true });
                    }}
                    limit={view.value.limit ?? DEFAULT_PAGE_LIMIT}
                    onLimitChange={(limit) => {
                      view.patch({ limit });
                    }}
                    isFetching={assets.isFetching}
                    label="assets"
                  />
                </div>
              </AsyncBoundary>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * A plain section label with the cards it gathers.
 *
 * Deliberately NOT a heading and NOT a landmark: the cards inside carry their own headings
 * and accessible names, and this is a visual grouping in the new layout language rather than
 * a new level of information architecture. `LiveScreen` has the same helper, and the two are
 * duplicated on purpose — a shared `SectionLabel` primitive belongs in `components/layout/`,
 * which this task does not own. It is reported as a gap rather than invented here.
 */
function Group({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-col gap-3">
      <p className="type-h3 text-ink">{label}</p>
      {children}
    </div>
  );
}

function TabButton({
  name,
  isActive,
  onSelect,
}: {
  readonly name: DetailTab;
  readonly isActive: boolean;
  readonly onSelect: () => void;
}): ReactElement {
  return (
    /*
     * One tab, two states, and both come from `segmentVariant` so the strip cannot drift the
     * way it had: ACTIVE is the console's secondary idiom (a tint of the brand with the brand
     * as the label), INACTIVE is `quiet` — no ground at all until hover.
     *
     * The inactive half used to be `bg-surface-control text-ink-muted`: a filled grey chip
     * with a grey label, which is the one thing this design language rules out by name. It is
     * NOT re-pointed at the brand, because then "which tab am I on" would be answered by a
     * shade rather than by the presence of colour. `aria-selected` carries the same fact to
     * anyone who can see neither.
     */
    <Button
      role="tab"
      variant={segmentVariant(isActive)}
      size="xs"
      shape="pill"
      aria-selected={isActive}
      data-tab={name}
      onClick={onSelect}
      className="px-3.5 py-1.5"
    >
      {name}
    </Button>
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
