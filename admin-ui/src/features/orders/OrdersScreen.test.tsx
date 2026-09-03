import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { MASK, type OrdersPage } from "@/api";
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
  type OrdersFilter,
} from "./ordersFilters";

function page(
  items: OrdersPage["items"],
  total: number | null = null,
  isTotalExact: boolean | null = null,
): OrdersPage {
  return { items, meta: { nextCursor: null, total, isTotalExact } };
}

function renderOrders(
  items: OrdersPage["items"],
  options: {
    filter?: Partial<OrdersFilter>;
    route?: string;
    total?: number | null;
    isTotalExact?: boolean | null;
  } = {},
) {
  const filter = { ...ORDERS_FILTER_FALLBACK, ...options.filter };
  const client = makeTestQueryClient();
  client.setQueryData(
    queryKeys.orders.list(toOrdersQuery(filter)),
    page(items, options.total ?? null, options.isTotalExact ?? null),
  );
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

    const bar = screen.getByRole("img", { name: /orders by state on this page/i });
    const grid = screen.getByRole("table", { name: "orders" });
    const filters = screen.getByRole("region", { name: "order filters" });

    // DOCUMENT_POSITION_FOLLOWING === 4: the bar follows the filter bar and precedes the grid.
    expect(filters.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(bar.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("describes the page's own shape, and says so", () => {
    renderOrders([
      makeOrder({ id: "1", state: "delivered" }),
      makeOrder({ id: "2", state: "delivered" }),
      makeOrder({ id: "3", state: "failed" }),
    ]);
    const bar = screen.getByRole("img", { name: /orders by state on this page/i });
    expect(bar.parentElement).toHaveAttribute("data-total", "3");
    expect(screen.getByText("state distribution · this page")).toBeInTheDocument();
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
