import { describe, expect, it } from "vitest";

import { parseSearchParams } from "@/lib";

import {
  ORDERS_FILTER_FALLBACK,
  completeWindow,
  ordersFilterSchema,
  toOrdersQuery,
  toStateCountsQuery,
  type OrdersFilter,
} from "./ordersFilters";

function parse(search: string) {
  return parseSearchParams(ordersFilterSchema, new URLSearchParams(search), ORDERS_FILTER_FALLBACK);
}

describe("ordersFilterSchema", () => {
  it("reads a repeated state parameter as an OR", () => {
    expect(parse("state=failed&state=cancelled").state).toEqual(["failed", "cancelled"]);
  });

  it("drops an unknown state rather than failing the whole parse", () => {
    // A stale bookmark naming a state this build no longer has must still show the rest.
    expect(parse("state=failed&state=held_for_review&isPaid=true")).toMatchObject({
      state: ["failed"],
      isPaid: true,
    });
  });

  it("refuses a naive instant, which every windowed endpoint 422s on", () => {
    expect(parse("from=2026-09-01T00:00:00&to=2026-09-02T00:00:00Z").from).toBeUndefined();
  });

  it("clamps a limit outside the API's bounds to absent, not to a guess", () => {
    expect(parse("limit=5000").limit).toBeUndefined();
    expect(parse("limit=100").limit).toBe(100);
  });

  it("falls back to the default view on a hand-mangled URL", () => {
    expect(parse("telegramUserId=not-a-number").telegramUserId).toBeUndefined();
  });
});

describe("completeWindow", () => {
  const NOW = Date.parse("2026-09-02T12:00:00Z");

  it("fills the end TimeRangePicker's presets leave open", () => {
    // The picker emits `{from, to: undefined}`. /api/orders accepts that now; the end is
    // filled so the URL names a fixed pair a paste can reproduce, not to dodge a refusal.
    const range = completeWindow({ from: "2026-09-01T12:00:00Z", to: undefined }, NOW);
    expect(range.to).toBe("2026-09-02T12:00:00Z");
    expect(range.from).toBe("2026-09-01T12:00:00Z");
  });

  it("fills a missing lower bound with the epoch rather than guessing one", () => {
    const range = completeWindow({ from: undefined, to: "2026-09-02T12:00:00Z" }, NOW);
    expect(range.from).toBe("1970-01-01T00:00:00Z");
  });

  it("leaves a complete window and an empty one alone", () => {
    const complete = { from: "2026-09-01T00:00:00Z", to: "2026-09-02T00:00:00Z" };
    expect(completeWindow(complete, NOW)).toEqual(complete);
    expect(completeWindow({}, NOW)).toEqual({});
  });
});

describe("toOrdersQuery", () => {
  it("asks for the total, because this screen is about the shape of a set", () => {
    expect(toOrdersQuery(ORDERS_FILTER_FALLBACK).withTotal).toBe(true);
  });

  it("sends a window only when both bounds are present", () => {
    const half = toOrdersQuery({ ...ORDERS_FILTER_FALLBACK, from: "2026-09-01T00:00:00Z" });
    expect(half.from).toBeUndefined();
    expect(half.to).toBeUndefined();

    const whole = toOrdersQuery({
      ...ORDERS_FILTER_FALLBACK,
      from: "2026-09-01T00:00:00Z",
      to: "2026-09-02T00:00:00Z",
    });
    expect(whole.from).toBe("2026-09-01T00:00:00Z");
    expect(whole.to).toBe("2026-09-02T00:00:00Z");
  });

  it("pins a limit so the query key does not depend on a server default", () => {
    expect(toOrdersQuery(ORDERS_FILTER_FALLBACK).limit).toBe(50);
  });
});

describe("toStateCountsQuery", () => {
  const FILTER: OrdersFilter = {
    ...ORDERS_FILTER_FALLBACK,
    state: ["failed"],
    isPaid: true,
    hasAssets: false,
    telegramUserId: 4242,
    correlationId: "corr-1",
    from: "2026-09-01T00:00:00Z",
    to: "2026-09-02T00:00:00Z",
  };

  it("carries every filter the list carries, so the bar and the table agree", () => {
    const counts = toStateCountsQuery(FILTER);
    const list = toOrdersQuery(FILTER);
    for (const key of Object.keys(counts) as (keyof typeof counts)[]) {
      expect(counts[key]).toEqual(list[key]);
    }
  });

  it("sends no paging, so turning a page does not refetch the aggregate", () => {
    // The route ignores all three; sending them would still change the query KEY.
    const counts = toStateCountsQuery({ ...FILTER, limit: 100, cursor: "opaque" });
    expect(counts).not.toHaveProperty("limit");
    expect(counts).not.toHaveProperty("cursor");
    expect(counts).not.toHaveProperty("withTotal");
    expect(counts).toEqual(toStateCountsQuery(FILTER));
  });

  it("drops a half window, exactly as the list query does", () => {
    const half = toStateCountsQuery({ ...ORDERS_FILTER_FALLBACK, from: "2026-09-01T00:00:00Z" });
    expect(half.from).toBeUndefined();
    expect(half.to).toBeUndefined();
  });
});
