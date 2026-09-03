import { describe, expect, it, vi } from "vitest";

import type { SearchParamsState } from "@/lib";

import { buildFilterChips, defaultChipFormat, type FilterFieldDescriptor } from "./filterChips";

interface OrdersFilter extends Record<string, unknown> {
  readonly state?: readonly string[] | undefined;
  readonly isPaid?: boolean | undefined;
  readonly telegramUserId?: number | undefined;
  readonly cursor?: string | undefined;
}

function stateOf(value: OrdersFilter): {
  readonly state: SearchParamsState<OrdersFilter>;
  readonly patch: ReturnType<typeof vi.fn>;
} {
  const patch = vi.fn();
  return {
    patch,
    state: {
      value,
      setValue: vi.fn(),
      patch,
      clear: vi.fn(),
      activeCount: 0,
    },
  };
}

const fields: readonly FilterFieldDescriptor<OrdersFilter>[] = [
  { key: "state", label: "state" },
  { key: "isPaid", label: "paid" },
  { key: "telegramUserId", label: "user" },
];

describe("buildFilterChips", () => {
  it("emits one chip per member of a repeated parameter", () => {
    const { state } = stateOf({ state: ["failed", "cancelled"] });
    const chips = buildFilterChips(state, fields);
    expect(chips.map((chip) => chip.value)).toEqual(["failed", "cancelled"]);
    expect(chips.map((chip) => chip.id)).toEqual(["state:failed", "state:cancelled"]);
  });

  it("removing one member leaves the others", () => {
    const { state, patch } = stateOf({ state: ["failed", "cancelled"] });
    const chips = buildFilterChips(state, fields);
    chips[0]?.remove();
    expect(patch).toHaveBeenCalledWith({ state: ["cancelled"] });
  });

  it("removing the last member drops the parameter, never leaving ?state=", () => {
    const { state, patch } = stateOf({ state: ["failed"] });
    buildFilterChips(state, fields)[0]?.remove();
    // `?state=` is a 422 on this API; absent and empty are different requests.
    expect(patch).toHaveBeenCalledWith({ state: undefined });
  });

  it("removes a scalar by setting it undefined", () => {
    const { state, patch } = stateOf({ telegramUserId: 770_000_123 });
    buildFilterChips(state, fields)[0]?.remove();
    expect(patch).toHaveBeenCalledWith({ telegramUserId: undefined });
  });

  it("goes through patch, which drops the cursor — a cursor outlives no filter change", () => {
    const { state, patch } = stateOf({ state: ["failed"], cursor: "abc" });
    buildFilterChips(state, fields)[0]?.remove();
    // patch() is called with no `keepCursor`, so useSearchParamsState discards it.
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch.mock.calls[0]?.[1]).toBeUndefined();
  });

  it("skips absent, null and empty-string parameters", () => {
    const { state } = stateOf({ state: undefined, isPaid: undefined, telegramUserId: undefined });
    expect(buildFilterChips(state, fields)).toHaveLength(0);
  });

  it("keeps a false boolean — false is a filter, absent is not", () => {
    const { state } = stateOf({ isPaid: false });
    const chips = buildFilterChips(state, fields);
    expect(chips).toHaveLength(1);
    expect(chips[0]?.value).toBe("no");
  });

  it("honours a caller's formatter", () => {
    const { state } = stateOf({ telegramUserId: 770_000_123 });
    const chips = buildFilterChips(state, [
      { key: "telegramUserId", label: "user", format: (value) => `#${String(value)}` },
    ]);
    expect(chips[0]?.value).toBe("#770000123");
  });
});

describe("defaultChipFormat", () => {
  it("humanises our own snake_case vocabularies", () => {
    expect(defaultChipFormat("brief_ready")).toBe("brief ready");
  });

  it("renders booleans as yes/no", () => {
    expect(defaultChipFormat(true)).toBe("yes");
    expect(defaultChipFormat(false)).toBe("no");
  });

  it("leaves an id ungrouped — a comma'd 770,000,123 is not a telegram id", () => {
    expect(defaultChipFormat(770_000_123)).toBe("770000123");
  });
});
