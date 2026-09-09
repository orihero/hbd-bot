import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MASK,
  ORDER_STATE_VALUES,
  type OrderState,
  type OrderStateCountsView,
  type OrdersPage,
} from "@/api";
import { makeOrder } from "@/components/domain/fixtures";
import {
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { OrdersScreen } from "./OrdersScreen";
import {
  ORDERS_FILTER_FALLBACK,
  toOrdersQuery,
  toStateCountsQuery,
  type OrdersFilter,
} from "./ordersFilters";

function page(
  items: OrdersPage["items"],
  total: number | null = null,
  isTotalExact: boolean | null = null,
): OrdersPage {
  return { items, meta: { nextCursor: null, total, isTotalExact } };
}

/**
 * An aggregate the way the route sends one: EVERY state, in declaration order, zeros
 * included, and `total` as the exact sum. Callers pass only the states they care about.
 */
function counts(byState: Partial<Record<OrderState, number>>): OrderStateCountsView {
  const rows = ORDER_STATE_VALUES.map((state) => ({ state, count: byState[state] ?? 0 }));
  return { counts: rows, total: rows.reduce((sum, row) => sum + row.count, 0) };
}

/** The aggregate a page of rows would have produced, for tests that are about something else. */
function countsOfPage(items: OrdersPage["items"]): OrderStateCountsView {
  const tally: Partial<Record<OrderState, number>> = {};
  for (const order of items) tally[order.state] = (tally[order.state] ?? 0) + 1;
  return counts(tally);
}

/** Seed BOTH of the screen's queries for one filter, the way the server answers them. */
function seed(
  client: QueryClient,
  filter: OrdersFilter,
  items: OrdersPage["items"],
  options: { total?: number | null; isTotalExact?: boolean | null; counts?: OrderStateCountsView } = {},
): void {
  client.setQueryData(
    queryKeys.orders.list(toOrdersQuery(filter)),
    page(items, options.total ?? null, options.isTotalExact ?? null),
  );
  client.setQueryData(
    queryKeys.orders.stateCounts(toStateCountsQuery(filter)),
    options.counts ?? countsOfPage(items),
  );
}

function renderOrders(
  items: OrdersPage["items"],
  options: {
    filter?: Partial<OrdersFilter>;
    route?: string;
    total?: number | null;
    isTotalExact?: boolean | null;
    /** The aggregate to seed. `null` leaves it UNSEEDED, so the bar is pending. */
    counts?: OrderStateCountsView | null;
  } = {},
) {
  const filter = { ...ORDERS_FILTER_FALLBACK, ...options.filter };
  const client = makeTestQueryClient();
  client.setQueryData(
    queryKeys.orders.list(toOrdersQuery(filter)),
    page(items, options.total ?? null, options.isTotalExact ?? null),
  );
  if (options.counts !== null) {
    client.setQueryData(
      queryKeys.orders.stateCounts(toStateCountsQuery(filter)),
      options.counts ?? countsOfPage(items),
    );
  }
  return renderWithProviders(<OrdersScreen />, {
    client,
    route: options.route ?? "/orders",
  });
}

const PURGED_ORDER = makeOrder({
  id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
  state: "delivered",
  recipientName: null,
  isIdentityPurged: true,
  identityPurgedAt: "2026-05-14T03:00:00Z",
});

describe("OrdersScreen", () => {
  beforeEach(() => {
    resetPrefs();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /* §14, Slice 1d acceptance, verbatim. */
  it("renders an identity-purged order as `🔒 purged 2026-05-14` — not an error, not a blank", () => {
    renderOrders([PURGED_ORDER]);

    const purged = screen.getByTestId("purged-value");
    expect(purged).toHaveTextContent("🔒 purged 2026-05-14");
    expect(purged).toHaveAttribute("data-purged-at", "2026-05-14T03:00:00Z");
    // Not an error: the table is still a table and the row is still a row.
    expect(screen.getByRole("table", { name: "orders" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the clock that destroyed the name, because a schedule and a request differ", () => {
    renderOrders([PURGED_ORDER]);
    expect(screen.getByTestId("purged-value")).toHaveTextContent("identity retention clock");
  });

  it("keeps `null` and the mask apart — they are different facts", () => {
    renderOrders([
      PURGED_ORDER,
      makeOrder({ id: "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb", recipientName: MASK }),
    ]);
    // One purged cell, and the empty-name row shows the mask rather than a lock.
    expect(screen.getAllByTestId("purged-value")).toHaveLength(1);
    expect(screen.getAllByTestId("name-text").some((node) => node.textContent === MASK)).toBe(true);
  });

  /* §11.2's dominant signal. */
  it("puts the stacked state bar under the filters and before row one", () => {
    renderOrders([
      makeOrder({ id: "1", state: "delivered" }),
      makeOrder({ id: "2", state: "failed" }),
    ]);

    const bar = screen.getByRole("img", { name: /orders by state/i });
    const grid = screen.getByRole("table", { name: "orders" });
    const filters = screen.getByRole("region", { name: "order filters" });

    // DOCUMENT_POSITION_FOLLOWING === 4: the bar follows the filter bar and precedes the grid.
    expect(filters.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(bar.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("draws the bar from the filtered aggregate, not from the fifty rows on screen", () => {
    // Two delivered rows in hand; the whole filtered set is 3 delivered and 400 failed.
    renderOrders([makeOrder({ id: "1", state: "delivered" }), makeOrder({ id: "2", state: "delivered" })], {
      counts: counts({ delivered: 3, failed: 400 }),
    });

    const bar = screen.getByRole("img", { name: /orders by state/i });
    expect(bar.parentElement).toHaveAttribute("data-total", "403");
    // The page's own shape (2 delivered, no failed) is NOT what is drawn.
    expect(bar.querySelector('[data-state="failed"]')).not.toBeNull();
    expect(bar).toHaveAccessibleName(/failed 400/i);
  });

  it("labels the bar with the aggregate's exact total, and no longer says `this page`", () => {
    // The list's meta.total is capped at 10,000; the aggregate's is not, and the bar reads
    // from the aggregate.
    renderOrders([makeOrder({ id: "1", state: "failed" })], {
      total: 10_000,
      isTotalExact: false,
      counts: counts({ failed: 12_483 }),
    });

    expect(screen.getByText(/state distribution/i)).toHaveTextContent("12,483");
    expect(screen.queryByText(/state distribution · this page/i)).toBeNull();
    expect(screen.queryByRole("img", { name: /on this page/i })).toBeNull();
  });

  it("re-keys BOTH queries on a filter change, so the bar and the table never disagree", () => {
    const client = makeTestQueryClient();
    const unfiltered: OrdersFilter = { ...ORDERS_FILTER_FALLBACK };
    const failedOnly: OrdersFilter = { ...ORDERS_FILTER_FALLBACK, state: ["failed"] };

    seed(client, unfiltered, [makeOrder({ id: "1", state: "delivered" })], {
      counts: counts({ delivered: 90, failed: 10 }),
    });
    seed(client, failedOnly, [makeOrder({ id: "2", state: "failed" })], {
      counts: counts({ failed: 10 }),
    });

    renderWithProviders(<OrdersScreen />, { client, route: "/orders" });
    expect(screen.getByText(/state distribution/i)).toHaveTextContent("100");
    expect(screen.getByRole("img", { name: /orders by state/i }).parentElement).toHaveAttribute(
      "data-total",
      "100",
    );

    fireEvent.click(screen.getByRole("button", { name: /failed/i }));

    // The table moved to the filtered page AND the bar moved to the filtered aggregate.
    expect(screen.getByText(/state distribution/i)).toHaveTextContent("10");
    expect(screen.getByRole("img", { name: /orders by state/i }).parentElement).toHaveAttribute(
      "data-total",
      "10",
    );
    expect(client.getQueryData(queryKeys.orders.stateCounts(toStateCountsQuery(failedOnly)))).toBeDefined();
  });

  it("shows a skeleton for a loading aggregate without blanking the table", () => {
    renderOrders([makeOrder({ id: "1", state: "delivered" })], { counts: null });

    expect(screen.getByTestId("state-distribution-skeleton")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /orders by state/i })).toBeNull();
    // The rows are unaffected: the aggregate is the second query, never the gate.
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);
  });

  it("keeps every row on screen when the aggregate fails, and offers a retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderOrders([makeOrder({ id: "1", state: "delivered" })], { counts: null });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/state distribution/i);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("table", { name: "orders" })).toBeInTheDocument();
    });
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);
  });

  /* §11.5: 15s, only when no row is expanded. */
  it("expands a row on activate and says the poll is paused", () => {
    renderOrders([makeOrder({ id: "cccccccc-3333-4333-8333-cccccccccccc" })]);
    expect(screen.queryByTestId("order-peek")).toBeNull();

    fireEvent.click(screen.getAllByRole("row")[1] as HTMLElement);

    const peek = screen.getByTestId("order-peek");
    expect(peek).toHaveAttribute("data-order-id", "cccccccc-3333-4333-8333-cccccccccccc");
    expect(peek).toHaveTextContent("polling paused while expanded");
  });

  it("collapses the same row on a second activate", () => {
    renderOrders([makeOrder({ id: "dddddddd-4444-4444-8444-dddddddddddd" })]);
    const row = screen.getAllByRole("row")[1] as HTMLElement;
    fireEvent.click(row);
    expect(screen.getByTestId("order-peek")).toBeInTheDocument();
    fireEvent.click(row);
    expect(screen.queryByTestId("order-peek")).toBeNull();
  });

  it("distinguishes empty-virgin from empty-filtered", () => {
    const virgin = renderOrders([]);
    expect(screen.getByText("no orders yet")).toBeInTheDocument();
    virgin.unmount();

    renderOrders([], { filter: { state: ["failed"] }, route: "/orders?state=failed" });
    // The filtered copy names the filter rather than claiming the deployment is empty.
    expect(screen.getByText("No orders match these filters")).toBeInTheDocument();
    expect(screen.queryByText("no orders yet")).toBeNull();
  });

  it("reports the capped total honestly", () => {
    renderOrders([makeOrder({ id: "1" })], { total: 10_000, isTotalExact: false });
    expect(screen.getAllByText(/10,000\+/).length).toBeGreaterThan(0);
  });
});
