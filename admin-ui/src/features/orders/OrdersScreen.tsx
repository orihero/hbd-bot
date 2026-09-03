/**
 * `/orders` — **What is the shape of what I just filtered to?**
 *
 * §11.2's dominant signal is *"a full-width 8px stacked state-distribution bar under the
 * filter bar, before the eye reaches row one"*, and the DOM order here is exactly that
 * sentence: `PageHeader` (with the `FilterBar` as its children) → `StateDistributionBar` →
 * the peek panel, if one is open → `DataTable`. The bar is full width, 8px and stacked
 * because `StateDistributionBar` has no props for any of those — the shape is fixed by the
 * component, and the screen only chooses the data.
 *
 * That data is the CURRENT PAGE's states. No endpoint returns per-state counts for an
 * arbitrary filter (`ordersByState` exists on `UserDetailView` and nowhere else), so the bar
 * describes the rows on screen and says so above itself. Inventing a whole-result-set shape
 * out of one page would be a wrong number wearing the dominant signal's clothes.
 *
 * ## The poll
 *
 * §11.5: *"Orders list — 15 s, only when no row is expanded."* `DataTable` has no expandable
 * rows, so "expanded" here is the peek panel: activating a row (click, `Enter`, or `o`)
 * opens a summary of it above the table and STOPS the poll, because rows shifting under an
 * operator who is reading one is the exact hostility that rule exists to prevent. Closing it
 * resumes the 15 s tick.
 *
 * ## The window
 *
 * `TimeRangePicker` emits a preset as `{from, to: undefined}` and `/api/orders` 422s on half
 * a window, so `completeWindow` fills the missing end before it reaches the URL. See
 * `ordersFilters.ts`.
 *
 * ## The reskin
 *
 * The table is a card now — `DataTable` supplies its own `--surface-card` at a 28px radius
 * under `--shadow-card`, so this screen wraps it in nothing. Same for `FilterBar`. What this
 * file owns is the space between them and the two surfaces it draws itself:
 *
 *  - **The dominant signal gets a card of its own**, under a plain `state distribution ·
 *    this page` label on the page ground. It was a bare bar on the ground before, which in a
 *    borderless language reads as a stray graphic; giving it paper is what keeps it looking
 *    like the loudest thing above row one. Its position in the DOM is unchanged and the
 *    label's text is unchanged.
 *  - **The peek panel is an elevated card**: the same paper, lifted by
 *    `--shadow-card-hover`, with no accent border. Elevation is what says "this one is
 *    open"; the table's own `--brand-fill` rail on the highlighted row says which one.
 *
 * The filter controls became soft pills with grounds rather than outlined boxes. The active
 * state filter is `--brand-tint` + `--brand`, the design's active-pill idiom, and it keeps
 * both `aria-pressed` and its §11.3 glyph, so "which states am I looking at" survives
 * greyscale and a screen reader.
 */

import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState, type ReactElement, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import {
  DEFAULT_PAGE_LIMIT,
  ORDER_STATE_VALUES,
  getOrders,
  unwrapAsync,
  type OrderState,
  type OrderView,
} from "@/api";
import {
  CursorPager,
  DataTable,
  FilterBar,
  StateDistributionBar,
  TimeRangePicker,
  Timestamp,
  buildFilterChips,
  type TimeRange,
} from "@/components/data";
import {
  CorrelationChip,
  NameText,
  OrderRefChip,
  PurgedValue,
  StatusPill,
  TelegramUserChip,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Button, segmentVariant, SkeletonTable } from "@/components/util";
import {
  POLL_MS,
  formatInteger,
  formatTotal,
  humaniseEnum,
  pollWhileVisible,
  queryKeys,
  statusGlyph,
  useSearchParamsState,
} from "@/lib";
import { href } from "@/routes";

import { IDENTITY_CLOCK_LABEL, ORDER_COLUMNS } from "./orderColumns";
import {
  ORDERS_FILTER_FALLBACK,
  ORDER_FILTER_FIELDS,
  completeWindow,
  countByState,
  ordersFilterParser,
  toOrdersQuery,
  type OrdersFilter,
} from "./ordersFilters";

export function OrdersScreen(): ReactElement {
  const navigate = useNavigate();
  const filters = useSearchParamsState<OrdersFilter>(ordersFilterParser, ORDERS_FILTER_FALLBACK);

  /** The peek panel's subject. Non-null means "a row is expanded", which stops the poll. */
  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);

  const query = useMemo(() => toOrdersQuery(filters.value), [filters.value]);

  const orders = useQuery({
    queryKey: queryKeys.orders.list(query),
    queryFn: ({ signal }) => unwrapAsync(getOrders(query, { signal })),
    refetchInterval: pollWhileVisible(expandedOrderId === null ? POLL_MS.ordersList : false),
  });

  const items = useMemo(() => orders.data?.items ?? [], [orders.data]);
  const counts = useMemo(() => countByState(items), [items]);
  const chips = useMemo(
    () => buildFilterChips(filters, ORDER_FILTER_FIELDS),
    [filters],
  );

  const expanded = items.find((order) => order.id === expandedOrderId) ?? null;

  const onRangeChange = useCallback(
    (range: TimeRange) => {
      const complete = completeWindow(range);
      filters.patch({ from: complete.from, to: complete.to });
    },
    [filters],
  );

  const toggleState = useCallback(
    (state: OrderState) => {
      const current = filters.value.state ?? [];
      const next = current.includes(state)
        ? current.filter((member) => member !== state)
        : [...current, state];
      filters.patch({ state: next.length === 0 ? undefined : next });
    },
    [filters],
  );

  const meta = orders.data?.meta ?? null;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Orders"
        description="What is the shape of what I just filtered to?"
        signal={
          <p className="type-body-sm text-ink-muted">
            <span className="num text-ink">{formatInteger(items.length)}</span>
            {" on this page"}
            {meta?.total === null || meta?.total === undefined ? null : (
              <>
                {" of "}
                <span className="num text-ink">
                  {formatTotal(meta.total, meta.isTotalExact)}
                </span>
                {" matching"}
              </>
            )}
          </p>
        }
      >
        <FilterBar
          chips={chips}
          onClear={() => {
            setExpandedOrderId(null);
            filters.clear();
          }}
          activeCount={filters.activeCount}
          label="order filters"
        >
          <TimeRangePicker
            value={{ from: filters.value.from, to: filters.value.to }}
            onChange={onRangeChange}
          />
          <StateFilter selected={filters.value.state ?? []} onToggle={toggleState} />
          <TriStateSelect
            label="paid"
            value={filters.value.isPaid}
            onChange={(next) => {
              filters.patch({ isPaid: next });
            }}
          />
          <TriStateSelect
            label="assets"
            value={filters.value.hasAssets}
            onChange={(next) => {
              filters.patch({ hasAssets: next });
            }}
          />
        </FilterBar>
      </PageHeader>

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        {/* The dominant signal. Directly under the filter bar, before row one. */}
        <div className="flex flex-col gap-3">
          <p className="type-h3 text-ink">state distribution · this page</p>
          <div className="rounded-card bg-surface-card p-card shadow-card">
            <StateDistributionBar
              counts={counts}
              isRefetching={orders.isFetching}
              label="orders by state on this page"
            />
          </div>
        </div>

        {expanded === null ? null : (
          <PeekPanel
            order={expanded}
            onClose={() => {
              setExpandedOrderId(null);
            }}
            onOpen={() => {
              navigate(href.order(expanded.id));
            }}
          />
        )}

        <AsyncBoundary
          status={orders.status}
          hasData={orders.data !== undefined}
          isEmpty={items.length === 0}
          activeFilterCount={filters.activeCount}
          onClearFilters={filters.clear}
          error={orders.error}
          onRetry={() => {
            void orders.refetch();
          }}
          dataUpdatedAt={orders.dataUpdatedAt}
          noun="orders"
          emptyTitle="no orders yet"
          emptyBody="Nothing has been ordered on this deployment."
          skeleton={<SkeletonTable rows={12} columns={ORDER_COLUMNS.length} withHeader />}
        >
          <DataTable
            data={items}
            columns={ORDER_COLUMNS}
            label="orders"
            getRowId={(order) => order.id}
            isRefetching={orders.isFetching}
            isRowHighlighted={(order) => order.id === expandedOrderId}
            onRowActivate={(order) => {
              setExpandedOrderId((current) => (current === order.id ? null : order.id));
            }}
            footer={
              <CursorPager
                meta={meta}
                itemCount={items.length}
                cursor={filters.value.cursor ?? null}
                onCursorChange={(cursor) => {
                  setExpandedOrderId(null);
                  filters.patch({ cursor: cursor ?? undefined }, { keepCursor: true });
                }}
                limit={filters.value.limit ?? DEFAULT_PAGE_LIMIT}
                onLimitChange={(limit) => {
                  filters.patch({ limit });
                }}
                isFetching={orders.isFetching}
                label="orders"
              />
            }
          />
        </AsyncBoundary>
      </div>
    </div>
  );
}

/**
 * The state filter, as toggles rather than a menu.
 *
 * Eight states fit in a row, and a multi-select behind a popover would hide the one fact an
 * operator most wants at a glance: which states they are currently looking at. Order is
 * `ORDER_STATE_VALUES` — the lifecycle — never count order and never alphabetical.
 *
 * A selected chip takes the design's active-pill treatment: `--brand-tint` as the ground
 * with `--brand` as the label, one hue for "selected" rather than each chip wearing its own
 * state colour. Nine states tinted nine ways would say which state a chip IS, which the
 * glyph and the word already say, while leaving "is it on" to be guessed from two adjacent
 * greys — and `draft` and `cancelled` are two adjacent greys by construction.
 */
function StateFilter({
  selected,
  onToggle,
}: {
  readonly selected: readonly OrderState[];
  readonly onToggle: (state: OrderState) => void;
}): ReactElement {
  return (
    <div role="group" aria-label="state" className="flex flex-wrap items-center gap-1.5">
      {ORDER_STATE_VALUES.map((state) => {
        const isOn = selected.includes(state);
        return (
          /* Pressed is the secondary idiom, unpressed is `quiet` — the same pairing the tab
             strip and the nav rail use, from the same helper. `aria-pressed` is the channel
             that needs neither. */
          <Button
            key={state}
            variant={segmentVariant(isOn)}
            size="xs"
            shape="pill"
            aria-pressed={isOn}
            data-state-filter={state}
            onClick={() => {
              onToggle(state);
            }}
          >
            <span aria-hidden="true">{statusGlyph(state) ?? "•"}</span>
            {humaniseEnum(state)}
          </Button>
        );
      })}
    </div>
  );
}

/**
 * `any` / `yes` / `no` for a tri-state boolean parameter.
 *
 * `undefined` is not `false`: an absent parameter means the API applies no filter, and
 * conflating the two would quietly hide every unpaid order the moment the control rendered.
 */
function TriStateSelect({
  label,
  value,
  onChange,
}: {
  readonly label: string;
  readonly value: boolean | undefined;
  readonly onChange: (next: boolean | undefined) => void;
}): ReactElement {
  const id = `filter-${label}`;
  return (
    <span className="flex items-center gap-2">
      <label htmlFor={id} className="type-body-sm text-ink-muted">
        {label}
      </label>
      {/* A control carries a ground here instead of a border. */}
      <select
        id={id}
        value={value === undefined ? "any" : value ? "yes" : "no"}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === "any" ? undefined : next === "yes");
        }}
        className="type-body-sm rounded-control bg-surface-control px-3 py-1.5 text-ink"
      >
        <option value="any">any</option>
        <option value="yes">yes</option>
        <option value="no">no</option>
      </select>
    </span>
  );
}

/**
 * The expanded row.
 *
 * Everything here comes from the row already in hand — opening it costs no request, which is
 * what lets it be the thing that pauses the poll rather than a second thing competing with
 * it. The full answer is `/orders/:id`, one click away.
 */
function PeekPanel({
  order,
  onClose,
  onOpen,
}: {
  readonly order: OrderView;
  readonly onClose: () => void;
  readonly onOpen: () => void;
}): ReactElement {
  return (
    <section
      data-testid="order-peek"
      data-order-id={order.id}
      aria-label="expanded order"
      // Lifted rather than outlined: the deeper shadow is what says "this one is open".
      className="flex flex-col gap-5 rounded-card bg-surface-card p-card shadow-card-hover"
    >
      <header className="flex flex-wrap items-center gap-2">
        <StatusPill state={order.state} size="md" />
        <OrderRefChip orderId={order.id} />
        <span className="type-body-sm ml-auto text-ink-muted">polling paused while expanded</span>
      </header>

      <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
        <Fact label="recipient">
          <NameText
            value={order.recipientName}
            isToggleable
            fallback={
              <PurgedValue
                purgedAt={order.identityPurgedAt}
                isPurged={order.isIdentityPurged}
                clock={IDENTITY_CLOCK_LABEL}
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
          <PurgedValue purgedAt={order.notePurgedAt} clock="note retention">
            <span className="text-ink-muted">
              {order.isBriefPresent ? "brief recorded" : "no brief"}
            </span>
          </PurgedValue>
        </Fact>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        {/* The design's primary button: solid brand, white label, 16px corners. */}
        <Button variant="primary" onClick={onOpen}>
          open full detail
        </Button>
        {/* Dismissive, so `quiet` — no ground of its own beside the primary. Two filled
            buttons side by side read as two primaries, whatever colour the second one is. */}
        <Button variant="quiet" onClick={onClose}>
          close
        </Button>
      </div>
    </section>
  );
}

function Fact({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-col gap-1">
      <dt className="type-body-sm text-ink-muted">{label}</dt>
      <dd className="type-body text-ink">{children}</dd>
    </div>
  );
}

export const Component = OrdersScreen;
