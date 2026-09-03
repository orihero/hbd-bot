/**
 * §14's Slice 1d acceptance, as a test: *"The `/users` list's date column is headed **"last
 * order"**, not "last seen" — the real writer arrives in Phase 3."*
 *
 * The other assertions here guard the two ways this screen could quietly lie: rendering the
 * unmasked telegram id (§12.3 masks it at every role — the integer is on the wire to build a
 * link and for nothing else), and drawing a sparkline out of a truncated page.
 */

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiResult, UserView, UsersPage, UsersQuery } from "@/api";
import type * as ApiModule from "@/api";
import { renderWithProviders, resetPrefs } from "@/components/util/testRender";

const { getUsersMock } = vi.hoisted(() => ({ getUsersMock: vi.fn() }));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getUsers: getUsersMock,
}));

const { UsersScreen } = await import("./UsersScreen");

function makeUser(overrides: Partial<UserView> = {}): UserView {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    telegramUserId: 770000123,
    telegramUserIdMasked: "•••••123",
    uiLanguage: "uz_latn",
    isBlocked: false,
    accountCreatedAt: "2026-08-20T10:00:00Z",
    firstOrderAt: "2026-08-20T10:00:00Z",
    lastOrderAt: "2026-09-01T09:00:00Z",
    orderCount: 3,
    paidOrderCount: 2,
    ...overrides,
  };
}

function page(items: readonly UserView[], nextCursor: string | null, total: number): UsersPage {
  return { items: [...items], meta: { nextCursor, total, isTotalExact: true } };
}

function ok(data: UsersPage): ApiResult<UsersPage> {
  return { ok: true, data };
}

/** The screen fires three `getUsers` calls; branch on the shape rather than on call order. */
function respond(handler: (query: UsersQuery) => UsersPage): void {
  getUsersMock.mockImplementation((query: UsersQuery = {}) => Promise.resolve(ok(handler(query))));
}

beforeEach(() => {
  resetPrefs();
  getUsersMock.mockReset();
});

describe("UsersScreen", () => {
  it("heads the date column “last order”, never “last seen”", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByRole("columnheader", { name: /last order/i })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/last seen/i);
  });

  it("renders the masked telegram id and never the integer", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("•••••123")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("770000123");
  });

  it("shows the total-users signal from the unfiltered probe", async () => {
    respond((query) =>
      query.limit === 1 ? page([makeUser()], null, 4_231) : page([makeUser()], null, 1),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("4,231")).toBeInTheDocument();
  });

  it("draws the 30-day sparkline only when the window page was complete", async () => {
    respond((query) =>
      query.from === undefined
        ? page([makeUser()], null, 1)
        : page([makeUser()], "more-pages", 900),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    await waitFor(() => {
      expect(screen.getByText(/daily series needs an accounts-per-day metric/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("img", { name: /new accounts per day/i })).not.toBeInTheDocument();
  });

  it("draws the sparkline when the whole window fitted in one page", async () => {
    respond((query) =>
      query.from === undefined
        ? page([makeUser()], null, 1)
        : page([makeUser({ accountCreatedAt: new Date().toISOString() })], null, 1),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(
      await screen.findByRole("img", { name: /new accounts per day, last 30 days/i }),
    ).toBeInTheDocument();
  });

  it("reads the filter state out of the URL rather than component state", async () => {
    respond(() => page([makeUser({ isBlocked: true })], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users?isBlocked=true&uiLanguage=ru" });

    await screen.findByRole("columnheader", { name: /last order/i });
    const listCall = getUsersMock.mock.calls
      .map((call) => call[0] as UsersQuery)
      .find((query) => query.isBlocked !== undefined);
    expect(listCall?.isBlocked).toBe(true);
    expect(listCall?.uiLanguage).toEqual(["ru"]);
  });

  it("shows the empty-filtered copy, naming the filter count, over the virgin one", async () => {
    respond(() => page([], null, 0));
    renderWithProviders(<UsersScreen />, { route: "/users?isBlocked=true" });

    expect(await screen.findByText(/no users match these filters/i)).toBeInTheDocument();
    expect(screen.getByText(/filter is narrowing this list/i)).toBeInTheDocument();
  });
});
