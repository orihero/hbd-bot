import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserStatsView, UsersFilters, UsersPage, UserView } from "@/api/users";
import { SEGMENT_FIELDS_FIXTURE } from "@/components/SegmentBuilder/fixtures";
import { UsersScreen } from "@/features/users/UsersScreen";
import { encodeSegment, type Segment } from "@/lib/segmentCodec";
import { useAuthStore } from "@/state/auth";

/**
 * The directory, with the audience builder on it.
 *
 * Three things have to hold for the builder to be the SAME filter the wizard uses rather than
 * a second one that looks like it, and each gets a test here:
 *
 * 1. **The URL is the state.** A `?segment=` token decodes into the builder, and an edit
 *    encodes back into the URL — byte for byte, so a link an operator pastes into a ticket
 *    reopens the audience they were looking at and the request the server sees is the one the
 *    address bar shows.
 * 2. **The chips say what the token hides.** A segment lives in the URL as one opaque string;
 *    without a chip per LEAF RULE the whole audience is invisible and "Filters · 1" stands
 *    over a nine-clause document.
 * 3. **The hand-off carries the document, not a description of it.** "Message these users"
 *    passes the same token to the wizard, so nobody retypes an audience — and it refuses while
 *    a quick filter is on, because those six parameters are not part of a segment.
 *
 * The registry is the REAL `GET /api/segments/fields` (`SEGMENT_FIELDS_FIXTURE`), so a field
 * that stopped being sortable, or an operator the server withdrew, fails here rather than in a
 * 422 an operator has to read.
 */

const { listUsers, getUsersStats, getSegmentFields, previewSegment } = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUsersStats: vi.fn(),
  getSegmentFields: vi.fn(),
  previewSegment: vi.fn(),
}));

/*
 * Only the FETCHERS are replaced. `importOriginal` keeps every schema, enum and helper the
 * screen reads out of these modules — `segmentFieldIndex` among them — so the test is driven
 * by the real contract and only the network is standing still.
 */
vi.mock("@/api/users", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listUsers, getUsersStats };
});

vi.mock("@/api/segments", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getSegmentFields, previewSegment };
});

const EMPTY_PAGE: UsersPage = {
  items: [],
  meta: { nextCursor: null, total: 0, isTotalExact: true },
};

/**
 * One row, for the tests that have to prove the TABLE is still standing. Everything personal on
 * it is the masked twin, which is all `/api/users` ever sends.
 */
const ONE_ACCOUNT: UserView = {
  id: "00000000-0000-4000-8000-0000000000aa",
  telegramUserId: 7_001,
  telegramUserIdMasked: "7•••01",
  uiLanguage: "uz_latn",
  isBlocked: false,
  accountCreatedAt: "2026-09-01T09:00:00Z",
  firstOrderAt: null,
  lastOrderAt: null,
  orderCount: 0,
  paidOrderCount: 0,
  isProfilePresent: true,
  telegramUsernameMasked: "@G•••",
  firstNameMasked: "M•••",
  lastNameMasked: null,
  phoneMasked: null,
  phoneSharedAt: null,
  avatarFetchedAt: null,
  hasAvatar: false,
  avatarUrl: null,
  creditBalance: null,
  lifetimeCreditsGranted: null,
  allowancePeriod: null,
};

const ONE_ROW_PAGE: UsersPage = {
  items: [ONE_ACCOUNT],
  meta: { nextCursor: null, total: null, isTotalExact: null },
};

/**
 * The four counts of `GET /api/users/stats`. They OVERLAP: 9 accounts we have barred and 31 who
 * have blocked the bot are not 40 unreachable people, and `matched` is not their sum plus
 * `reachable`. Nothing in these tests may add any two of them together, and neither may the
 * screen.
 */
const USER_STATS: UserStatsView = {
  matched: 1_204,
  reachable: 1_190,
  blocked: 9,
  botBlocked: 31,
};

/** The screen prints counts through `Intl.NumberFormat`, so the expectation is built the same. */
function formatted(count: number): string {
  return new Intl.NumberFormat().format(count);
}

/**
 * One tile of the strip, read the way `PageStats` wires it together: the value carries
 * `aria-labelledby` pointing at its label, which is what makes a screen reader say "Reachable,
 * 1,190" as one thing instead of two loose strings.
 *
 * Queried by the tile's stable `key` rather than by its label text on purpose — the labels are
 * `users.stats.*` and belong to the translation catalogues, and a test that hard-codes English
 * copy fails the day somebody improves a word rather than the day something breaks.
 */
function statTile(key: string): { readonly label: string; readonly value: string } {
  const label = document.getElementById(`page-stat-${key}-label`);
  const value = document.querySelector(`[aria-labelledby="page-stat-${key}-label"]`);
  if (label === null || value === null) throw new Error(`No stat tile "${key}" on screen.`);
  return { label: label.textContent ?? "", value: value.textContent ?? "" };
}

/** "Songs delivered is at least 3" — one leaf rule, and the audience the four-name list opens on. */
const DELIVERED_AT_LEAST_3: Segment = {
  v: 1,
  match: "all",
  rules: [{ field: "delivered_order_count", op: "gte", value: 3 }],
};

/** Where the wizard would be. It never renders one; it reports the URL it was handed. */
function WizardProbe(): JSX.Element {
  const location = useLocation();
  return <p data-testid="wizard-url">{`${location.pathname}${location.search}`}</p>;
}

/*
 * `MemoryRouter`, deliberately NOT `createMemoryRouter`. A data router builds a `Request` for
 * every navigation, and jsdom's `AbortSignal` is not the one undici's `Request` will accept —
 * so under this environment `setSearchParams` rejects and the URL silently never moves, which
 * is exactly the behaviour these tests exist to check.
 */
function renderScreen(url: string): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/users" element={<UsersScreen />} />
          <Route path="/broadcasts/new" element={<WizardProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The filters of the most recent `GET /api/users`, once one has been made. */
async function lastRequest(): Promise<UsersFilters> {
  await waitFor(() => {
    expect(listUsers).toHaveBeenCalled();
  });
  const calls = listUsers.mock.calls;
  return calls[calls.length - 1]?.[0] as UsersFilters;
}

beforeEach(() => {
  listUsers.mockResolvedValue({ ok: true, data: EMPTY_PAGE });
  getUsersStats.mockResolvedValue({ ok: true, data: USER_STATS });
  getSegmentFields.mockResolvedValue({ ok: true, data: SEGMENT_FIELDS_FIXTURE });
  previewSegment.mockResolvedValue({
    ok: true,
    data: {
      matched: 42,
      reachable: 40,
      skippedBlocked: 1,
      skippedBotBlocked: 2,
      byLanguage: [],
    },
  });
  useAuthStore.setState({
    account: {
      id: "00000000-0000-4000-8000-000000000001",
      username: "operator",
      role: "admin",
      lastLoginAt: null,
      mustChangePassword: false,
    },
  });
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("UsersScreen — a segment in the URL", () => {
  it("decodes the token, sends it back verbatim, and draws one chip per leaf rule", async () => {
    const token = encodeSegment(DELIVERED_AT_LEAST_3);
    renderScreen(`/users?segment=${encodeURIComponent(token)}`);

    // Verbatim: the bytes in the address bar are the bytes on the wire, which is what makes
    // this list and `/segments/preview` provably one population and one cache key.
    const filters = await lastRequest();
    expect(filters.segment).toBe(token);

    // The chip states the FIELD and the OPERATOR-folded VALUE in words — the token itself is
    // unreadable, and an invisible filter is one an operator reads a wrong conclusion through.
    expect(
      await screen.findByRole("button", {
        name: "Remove filter Songs delivered: is at least 3",
      }),
    ).toBeInTheDocument();

    // Counted as a LEAF RULE, never as the one `?segment=` key.
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters · 1");
  });

  it("counts every leaf rule, at every depth, in the Filters badge", async () => {
    const nested: Segment = {
      v: 1,
      match: "all",
      rules: [
        { field: "delivered_order_count", op: "gte", value: 3 },
        {
          match: "any",
          rules: [
            { field: "plan_status", op: "in", value: ["lapsed"] },
            { field: "is_blocked", op: "is_false" },
          ],
        },
      ],
    };
    renderScreen(`/users?segment=${encodeURIComponent(encodeSegment(nested))}`);

    await lastRequest();
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters · 3");

    // A nested chip carries its own group's connective, or it reads as one more thing EVERY
    // account must match — which inverts the audience.
    expect(
      await screen.findByRole("button", {
        name: "Remove filter Any · Plan status: is any of Plan expired, not bought again",
      }),
    ).toBeInTheDocument();
  });

  it("degrades a token it cannot read to the unfiltered list rather than an empty screen", async () => {
    renderScreen("/users?segment=not-a-real-token");

    const filters = await lastRequest();
    expect(filters.segment).toBeNull();
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters");
  });
});

describe("UsersScreen — editing the builder writes the URL", () => {
  it("round-trips an edit back into ?segment= as the same document", async () => {
    const user = userEvent.setup();
    const token = encodeSegment(DELIVERED_AT_LEAST_3);
    renderScreen(`/users?segment=${encodeURIComponent(token)}`);
    await lastRequest();

    // Removing the only chip empties the document, and an empty document narrows nothing — so
    // the parameter goes away entirely rather than lingering as a second spelling of the
    // plain list.
    await user.click(
      await screen.findByRole("button", { name: "Remove filter Songs delivered: is at least 3" }),
    );

    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.segment).toBeNull();
    });
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters");
  });

  it("puts a rule composed in the panel into the URL, and hands the wizard the same bytes", async () => {
    const user = userEvent.setup();
    renderScreen("/users");
    await lastRequest();

    await user.click(screen.getByRole("button", { name: /^Filters/u }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    const rule = screen.getByRole("group", { name: "Rule 1" });
    await user.selectOptions(within(rule).getByLabelText("Field"), "plan_status");
    await user.click(screen.getByRole("button", { name: "Plan expired, not bought again" }));

    const expected: Segment = {
      v: 1,
      match: "all",
      rules: [{ field: "plan_status", op: "in", value: ["lapsed"] }],
    };
    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.segment).toBe(encodeSegment(expected));
    });

    // The hand-off carries the DOCUMENT the operator just composed — the same bytes, so the
    // audience they approved is the audience the wizard freezes.
    await user.click(screen.getByRole("button", { name: /^Message these users/u }));
    expect(screen.getByTestId("wizard-url")).toHaveTextContent(
      `/broadcasts/new?segment=${encodeURIComponent(encodeSegment(expected))}`,
    );
  });
});

describe("UsersScreen — the hand-off to the campaign wizard", () => {
  it("carries the current segment into the wizard path", async () => {
    const user = userEvent.setup();
    const token = encodeSegment(DELIVERED_AT_LEAST_3);
    renderScreen(`/users?segment=${encodeURIComponent(token)}`);
    await lastRequest();

    await user.click(screen.getByRole("button", { name: /^Message these users/u }));

    expect(screen.getByTestId("wizard-url")).toHaveTextContent(
      `/broadcasts/new?segment=${encodeURIComponent(token)}`,
    );
  });

  it("refuses while a quick filter is on, because a chip parameter is not a segment", async () => {
    renderScreen("/users?isBlocked=true");
    await lastRequest();

    const action = screen.getByRole("button", { name: /^Message these users/u });
    expect(action).toBeDisabled();
  });

  it("is absent for a role that cannot write campaigns", async () => {
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000002",
        username: "viewer",
        role: "viewer",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    renderScreen("/users");
    await lastRequest();

    // Hidden, not disabled: a press would be a 403 and a `permission.denied` audit row against
    // somebody who did nothing wrong.
    expect(screen.queryByRole("button", { name: /^Message these users/u })).toBeNull();
  });
});

describe("UsersScreen — sorting is the server's, and only where the server allows it", () => {
  it("sends the registry's sort key, and asks the list for no count at either end", async () => {
    const user = userEvent.setup();
    renderScreen("/users");

    const first = await lastRequest();
    // `withTotal` is not asked for AT ALL any more: the bounded count it returns and the strip's
    // exact `matched` are two answers to one question, and the exact one won. Never asking also
    // retires the 422 that `withTotal` and a sort on a computed column used to be together.
    expect(first.withTotal).toBeUndefined();
    expect(first.sort).toBeNull();

    await user.click(await screen.findByRole("button", { name: /^Sort by Orders/u }));

    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.sort).toBe("order_count");
      expect(filters.sortDir).toBe("desc");
      expect(filters.withTotal).toBeUndefined();
    });

    const header = screen.getByRole("columnheader", { name: /Orders/u });
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("offers no control on a column the server refuses to sort", async () => {
    renderScreen("/users");
    await lastRequest();

    // `is_blocked` and `ui_language` are filterable and deliberately not sortable; a header
    // that offered a control and then rendered a 422 would teach an operator that the panel is
    // unreliable about a refusal that is deliberate.
    await waitFor(() => {
      expect(getSegmentFields).toHaveBeenCalled();
    });
    const standing = screen.getByRole("columnheader", { name: "Standing" });
    expect(within(standing).queryByRole("button")).toBeNull();
    expect(standing).not.toHaveAttribute("aria-sort");
  });

  it("keeps a document's own ordering when the URL names no sort", async () => {
    const sorted: Segment = {
      ...DELIVERED_AT_LEAST_3,
      sort: { key: "delivered_order_count", dir: "desc" },
    };
    renderScreen(`/users?segment=${encodeURIComponent(encodeSegment(sorted))}`);

    const filters = await lastRequest();
    // Lifted out into the two parameters that own it: `?sort=` is where the server reads an
    // ordering, and the token left in the URL is the audience alone.
    expect(filters.sort).toBe("delivered_order_count");
    expect(filters.sortDir).toBe("desc");
    expect(filters.segment).toBe(encodeSegment(DELIVERED_AT_LEAST_3));
  });

  it("lets an explicit ?sort= override the document's own, as the server does", async () => {
    const sorted: Segment = {
      ...DELIVERED_AT_LEAST_3,
      sort: { key: "delivered_order_count", dir: "desc" },
    };
    renderScreen(
      `/users?segment=${encodeURIComponent(encodeSegment(sorted))}&sort=order_count&sortDir=asc`,
    );

    const filters = await lastRequest();
    expect(filters.sort).toBe("order_count");
    expect(filters.sortDir).toBe("asc");
  });
});

describe("UsersScreen — the audience count", () => {
  it("states reachable and the two overlapping skips without ever adding them up", async () => {
    const user = userEvent.setup();
    renderScreen(`/users?segment=${encodeURIComponent(encodeSegment(DELIVERED_AT_LEAST_3))}`);
    await lastRequest();

    await user.click(screen.getByRole("button", { name: /^Filters/u }));

    expect(await screen.findByText("42 accounts match this segment")).toBeInTheDocument();
    expect(
      screen.getByText(
        "40 of them can be messaged. 1 are barred by us and 2 have blocked the bot — the two overlap, so never add them together.",
      ),
    ).toBeInTheDocument();
  });

  it("is not asked for at all on an unfiltered list nobody has opened the panel on", async () => {
    renderScreen("/users");
    await lastRequest();

    expect(previewSegment).not.toHaveBeenCalled();
  });
});

describe("UsersScreen — the stat strip over the table", () => {
  /*
   * The strip answers "what is this filtered population made of?" and the table answers "who is
   * in it?". These four tests are the seams where those two could quietly stop being the same
   * population: one request or two, one ordering-insensitive answer or a refetch per column
   * press, and one failure taking the other's surface down with it.
   */

  it("states the four counts, and is handed the list's own filter set to state them about", async () => {
    renderScreen("/users");
    await lastRequest();

    await waitFor(() => {
      expect(statTile("accounts").value).toBe(formatted(USER_STATS.matched));
    });
    expect(statTile("reachable").value).toBe(formatted(USER_STATS.reachable));
    expect(statTile("blocked").value).toBe(formatted(USER_STATS.blocked));
    expect(statTile("botBlocked").value).toBe(formatted(USER_STATS.botBlocked));

    // Every tile carries a label, and the value is bound to it — a bare 1,190 announces itself
    // as a number with no noun attached.
    expect(statTile("reachable").label).not.toBe("");

    // THE SAME filter set object the table was asked for, not a second one assembled beside it.
    // `getUsersStats` is what drops the parameters a count cannot honour, and it is the only
    // place that decides; a screen that pre-narrowed here would be a third opinion about what
    // narrows a population, and the first to go stale when a seventh filter is added.
    expect(getUsersStats.mock.calls[0]?.[0]).toBe(listUsers.mock.calls[0]?.[0]);
  });

  it("is not asked again when only the ordering changes", async () => {
    const user = userEvent.setup();
    renderScreen("/users");
    await lastRequest();
    await waitFor(() => {
      expect(getUsersStats).toHaveBeenCalledTimes(1);
    });

    await user.click(await screen.findByRole("button", { name: /^Sort by Orders/u }));

    // The list refetches — its rows are ordered and its cursor is minted under one `ORDER BY`.
    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.sort).toBe("order_count");
    });
    // The counts do not. How many accounts match is one answer however the rows are arranged,
    // and re-asking would flicker a figure an operator may be mid-sentence about, for nothing.
    expect(getUsersStats).toHaveBeenCalledTimes(1);
    expect(statTile("accounts").value).toBe(formatted(USER_STATS.matched));
  });

  it("is asked again when the narrowing itself changes", async () => {
    const user = userEvent.setup();
    renderScreen("/users?isBlocked=true");
    await lastRequest();
    await waitFor(() => {
      expect(getUsersStats).toHaveBeenCalledTimes(1);
    });
    expect((getUsersStats.mock.calls[0]?.[0] as UsersFilters).isBlocked).toBe(true);

    // A chip IS the narrowing, written out — so dropping one is the press that must re-ask, or
    // the numbers sitting under the chip row go on describing a population the rows below them
    // no longer belong to, with the chip that explained them already gone.
    await user.click(screen.getByRole("button", { name: /^Remove filter/u }));

    await waitFor(() => {
      expect(getUsersStats).toHaveBeenCalledTimes(2);
    });
    expect((getUsersStats.mock.calls[1]?.[0] as UsersFilters).isBlocked).toBeNull();
  });

  it("draws dashes and its own note when the counts cannot be taken, and keeps the table", async () => {
    listUsers.mockResolvedValue({ ok: true, data: ONE_ROW_PAGE });
    getUsersStats.mockResolvedValue({
      ok: false,
      code: "NOT_FOUND",
      // A 404 is the honest shape of this failure: an API build that predates /users/stats. It
      // is also not retried, unlike a 5xx, so the assertion is about the screen and not a clock.
      message: "GET /api/users/stats is not available on this API build.",
      status: 404,
      endpoint: "GET /api/users/stats",
      correlationId: "c-404",
      issues: null,
      details: null,
      retryAfterS: null,
    });
    renderScreen("/users");
    await lastRequest();

    // The strip says it in its own space, with the endpoint and the correlation id an operator
    // would quote — not as a caption, and not by borrowing the table's note.
    expect(
      await screen.findByText("GET /api/users/stats is not available on this API build."),
    ).toBeInTheDocument();
    expect(screen.getByText(/GET \/api\/users\/stats · c-404/u)).toBeInTheDocument();

    // An em dash, never a 0. "0 accounts match" is a sentence an operator would act on, and it
    // would be a fabrication: nothing was counted.
    expect(statTile("accounts").value).toBe("—");
    expect(statTile("reachable").value).toBe("—");

    // And the records are still on screen. A caption that could not be computed says nothing
    // about whether the rows beneath it are true, and they are what the operator came for.
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);
  });
});
