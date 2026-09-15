import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BROADCAST_STATE_VALUES,
  type BroadcastState,
  type BroadcastStatsView,
  type BroadcastsFilters,
  type BroadcastsPage,
} from "@/api/broadcasts";
import type { ApiFailure } from "@/api/client";
import { BroadcastsScreen } from "@/features/broadcasts/BroadcastsScreen";
import { SENDING_PROGRESS, makeBroadcast } from "@/features/broadcasts/fixtures";
import { BROADCAST_POLL_MS } from "@/features/broadcasts/useBroadcasts";
import { useAuthStore } from "@/state/auth";

/**
 * The campaign list.
 *
 * Three properties are what make this screen a campaign list rather than a message log, and each
 * one is a thing an operator would misread if it broke:
 *
 * 1. **One row per CAMPAIGN.** Two campaigns of forty thousand recipients are two rows. A screen
 *    that paged recipients here would put a customer under filters that are about campaigns.
 * 2. **The delivery column counts settled rows against rows WRITTEN**, never against the frozen
 *    audience — the two differ during an expansion, and a bar drawn against the audience sits at
 *    a third while a send is in fact complete.
 * 3. **A filter is a repeated parameter and the row goes back to it verbatim.** `?state=sending`
 *    reaches `GET /api/broadcasts` as `state`, and the chip says which vocabulary member it is
 *    in words rather than in the wire's spelling.
 * 4. **The strip states the count, the toolbar no longer does, and it asks for nothing while the
 *    deployment is asleep.** Those are the two failures the strip could introduce: one set of
 *    campaigns given two different sizes on one screen, and a timer nobody turned off.
 *
 * Only the FETCHERS are replaced; every schema, enum and hook the screen reads is the real one.
 */

const { listBroadcasts, getBroadcastStats } = vi.hoisted(() => ({
  listBroadcasts: vi.fn(),
  getBroadcastStats: vi.fn(),
}));

vi.mock("@/api/broadcasts", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listBroadcasts, getBroadcastStats };
});

const EMPTY_PAGE: BroadcastsPage = {
  items: [],
  meta: { nextCursor: null, total: 0, isTotalExact: true },
};

function pageOf(items: BroadcastsPage["items"]): BroadcastsPage {
  return { items, meta: { nextCursor: null, total: items.length, isTotalExact: true } };
}

/**
 * Every member of the closed vocabulary, because the server publishes every one of them.
 *
 * A state the caller does not name is a campaign count of zero and says so; a state MISSING from
 * the array would be a different fact — a figure this build was not given — and the screen is
 * required to render that as an absence rather than as nought.
 */
function countsOf(counts: Partial<Record<BroadcastState, number>>): BroadcastStatsView["counts"] {
  return BROADCAST_STATE_VALUES.map((state) => ({ state, count: counts[state] ?? 0 }));
}

/** A deployment that has composed nothing and sent nothing. `lastSendAt` is null, not an epoch. */
function statsOf(overrides: Partial<BroadcastStatsView> = {}): BroadcastStatsView {
  return {
    counts: countsOf({}),
    total: 0,
    reachedRecipients: 0,
    audienceTotal: 0,
    lastSendAt: null,
    ...overrides,
  };
}

/**
 * A refused read of the STRIP alone, and drift is the realistic shape of one.
 *
 * `/broadcasts/stats` is the newest route in this namespace, so the deployment where one query
 * fails and the other does not is exactly a server whose strip this bundle cannot parse while it
 * reads the list perfectly. It is also terminal — `shouldRetryRead` does not re-ask for bytes it
 * already failed to understand — so the tile reaches its refusal without three seconds of backoff.
 */
const STATS_REFUSED: ApiFailure = {
  ok: false,
  code: "SCHEMA_DRIFT",
  message: "The strip does not match this build's contract.",
  status: 200,
  endpoint: "GET /api/broadcasts/stats",
  correlationId: "c-strip-1",
  issues: [{ path: "lastSendAt", message: "Expected string, received number" }],
  details: null,
  retryAfterS: null,
};

/**
 * A tile by its stable `key`, never by its label.
 *
 * `PageStats` publishes the key as `aria-labelledby` precisely so a test can find a tile without
 * knowing what language the operator reads: the labels come out of the catalogue and asserting on
 * their English would make these tests a second, silent copy of the translations.
 */
function tile(key: string): HTMLElement {
  const element = document.querySelector<HTMLElement>(`[aria-labelledby="page-stat-${key}-label"]`);
  if (element === null) throw new Error(`no strip tile under the key "${key}"`);
  return element;
}

/** Where the detail screen would be. It never renders one; it reports the URL it was handed. */
function DetailProbe(): JSX.Element {
  const location = useLocation();
  return <p data-testid="detail-url">{location.pathname}</p>;
}

/*
 * `MemoryRouter`, deliberately NOT `createMemoryRouter`: a data router builds a `Request` for
 * every navigation and jsdom's `AbortSignal` is not the instance undici's `Request` accepts, so
 * `setSearchParams` rejects and the URL silently never moves.
 */
function renderScreen(url = "/broadcasts"): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/broadcasts" element={<BroadcastsScreen />} />
          <Route path="/broadcasts/:broadcastId" element={<DetailProbe />} />
          <Route path="/broadcasts/new" element={<DetailProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function lastRequest(): Promise<BroadcastsFilters> {
  await waitFor(() => {
    expect(listBroadcasts).toHaveBeenCalled();
  });
  const calls = listBroadcasts.mock.calls;
  return calls[calls.length - 1]?.[0] as BroadcastsFilters;
}

beforeEach(() => {
  listBroadcasts.mockResolvedValue({ ok: true, data: EMPTY_PAGE });
  getBroadcastStats.mockResolvedValue({ ok: true, data: statsOf() });
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
  /* The two polling tests install fake timers; a test that leaks them would freeze every
     `waitFor` after it. A no-op for the rest. */
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("BroadcastsScreen — campaigns, not recipients", () => {
  it("renders one row per campaign whatever the size of its audience", async () => {
    listBroadcasts.mockResolvedValue({
      ok: true,
      data: pageOf([
        makeBroadcast({ id: "a1111111-1111-4111-8111-111111111111", title: "August outage notice" }),
        makeBroadcast({
          id: "b1111111-1111-4111-8111-111111111111",
          title: "September price change",
          state: "sending",
          isTerminal: false,
          progress: SENDING_PROGRESS,
        }),
      ]),
    });
    renderScreen();

    const table = await screen.findByRole("table");
    // Two campaigns of forty thousand recipients each: two rows, plus the header row.
    await waitFor(() => {
      expect(within(table).getAllByRole("row")).toHaveLength(3);
    });
    expect(within(table).getByText("August outage notice")).toBeInTheDocument();
    expect(within(table).getByText("September price change")).toBeInTheDocument();
  });

  it("counts settled rows against rows written, never against the frozen audience", async () => {
    listBroadcasts.mockResolvedValue({
      ok: true,
      data: pageOf([
        makeBroadcast({ state: "sending", isTerminal: false, progress: SENDING_PROGRESS }),
      ]),
    });
    renderScreen();

    // 12,010 settled of the 40,000 ROWS WRITTEN — the same denominator the server settles against.
    expect(await screen.findByText(/12,010/)).toBeInTheDocument();
  });

  it("says which state the badge is in, in words rather than in the wire's spelling", async () => {
    listBroadcasts.mockResolvedValue({
      ok: true,
      data: pageOf([makeBroadcast({ state: "paused", isTerminal: false })]),
    });
    renderScreen();

    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.queryByText("paused")).not.toBeInTheDocument();
  });

  it("reads a state filter out of the URL and sends it back as a repeated parameter", async () => {
    renderScreen("/broadcasts?state=sending&state=paused");

    const filters = await lastRequest();
    expect(filters.state).toEqual(["sending", "paused"]);
    // The chip states the members in words, so an empty page is legible.
    expect(screen.getByText(/Sending or Paused/)).toBeInTheDocument();
  });

  it("drops a state member this build does not know rather than sending a 422", async () => {
    renderScreen("/broadcasts?state=sending&state=teleported");

    const filters = await lastRequest();
    expect(filters.state).toEqual(["sending"]);
  });

  it("opens the campaign, not a recipient, when a row is pressed", async () => {
    const user = userEvent.setup();
    listBroadcasts.mockResolvedValue({
      ok: true,
      data: pageOf([makeBroadcast({ id: "c1111111-1111-4111-8111-111111111111" })]),
    });
    renderScreen();

    await user.click(await screen.findByText("August outage notice"));
    expect(screen.getByTestId("detail-url")).toHaveTextContent(
      "/broadcasts/c1111111-1111-4111-8111-111111111111",
    );
  });

  it("withholds the primary action from a role that cannot compose", async () => {
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000002",
        username: "watcher",
        role: "support",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    renderScreen();

    await waitFor(() => {
      expect(listBroadcasts).toHaveBeenCalled();
    });
    // Absent, not disabled: a press would be a 403 and a `permission.denied` audit row.
    expect(screen.queryByRole("button", { name: /New campaign/ })).not.toBeInTheDocument();
  });
});

describe("BroadcastsScreen — the strip above the table", () => {
  it("states the campaign count once, in the tile, and drops the toolbar's copy of it", async () => {
    listBroadcasts.mockResolvedValue({ ok: true, data: pageOf([makeBroadcast()]) });
    getBroadcastStats.mockResolvedValue({ ok: true, data: statsOf({ total: 412 }) });
    renderScreen();

    await screen.findByText("August outage notice");
    await waitFor(() => {
      expect(tile("campaigns")).toHaveTextContent("412");
    });
    /*
     * The subtitle is the `p` beside the toolbar's h1, and once the rows are here there must not
     * be one. `meta.total` saturates at the server's count cap while the strip's total is the
     * exact sum of its segments, so two counts on one screen are two different numbers for one
     * set of campaigns the moment a deployment passes the cap.
     */
    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading.parentElement?.querySelector("p")).toBeNull();
  });

  it("does not ask for the bounded count the toolbar used to spend it on", async () => {
    renderScreen();

    const filters = await lastRequest();
    expect(filters.withTotal).toBeUndefined();
  });

  it("counts sending and paused as in flight — the campaigns a person must look at", async () => {
    getBroadcastStats.mockResolvedValue({
      ok: true,
      data: statsOf({
        // `expanding` moves on its own and needs nobody; it is why the screen polls, not something
        // to act on, and it must not be added into this tile.
        counts: countsOf({ sending: 2, paused: 1, expanding: 7, completed: 40 }),
        total: 50,
      }),
    });
    renderScreen();

    await waitFor(() => {
      expect(tile("inFlight")).toHaveTextContent("3");
    });
  });

  it("renders the reach as the two integers it was counted from, and divides nothing", async () => {
    getBroadcastStats.mockResolvedValue({
      ok: true,
      data: statsOf({ total: 3, reachedRecipients: 1_240, audienceTotal: 1_500 }),
    });
    renderScreen();

    await waitFor(() => {
      expect(tile("recipients")).toHaveTextContent("1,240");
    });
    // Both numbers, so a reader can check the quotient against the rows. Never "83%".
    expect(tile("recipients")).toHaveTextContent("1,500");
    expect(tile("recipients")).not.toHaveTextContent("%");
  });

  it("draws a dash for a reach with no denominator rather than a reach of zero", async () => {
    getBroadcastStats.mockResolvedValue({
      ok: true,
      // Nothing has been frozen into an audience, so there is nothing to have reached a share OF.
      data: statsOf({ total: 2, reachedRecipients: 0, audienceTotal: 0 }),
    });
    renderScreen();

    await waitFor(() => {
      expect(tile("recipients")).toHaveTextContent("—");
    });
    expect(tile("recipients")).not.toHaveTextContent("0");
  });

  it("draws a dash for a deployment that has never sent, never an instant it invented", async () => {
    getBroadcastStats.mockResolvedValue({ ok: true, data: statsOf({ total: 4, lastSendAt: null }) });
    renderScreen();

    await waitFor(() => {
      expect(tile("lastSend")).toHaveTextContent("—");
    });
    /* A null `lastSendAt` is a column that has stayed NULL because no run has started. The epoch
       would render as a send made in 1970 and a creation date as one nobody made. */
    expect(tile("lastSend")).not.toHaveTextContent("1970");
  });

  it("keeps a refused strip inside the strip: the rows that arrived stay on the screen", async () => {
    listBroadcasts.mockResolvedValue({
      ok: true,
      data: pageOf([makeBroadcast({ title: "August outage notice" })]),
    });
    getBroadcastStats.mockResolvedValue(STATS_REFUSED);
    renderScreen();

    await waitFor(() => {
      expect(tile("campaigns")).toHaveTextContent("—");
    });
    // The table is a different query and its rows are still good.
    expect(screen.getByText("August outage notice")).toBeInTheDocument();
    // All four figures are missing for one reason, and each tile says so under its own dash.
    for (const key of ["campaigns", "inFlight", "recipients", "lastSend"]) {
      expect(tile(key)).toHaveTextContent("—");
    }
  });

  it("makes no request of the strip on a clock while nothing is in flight", async () => {
    /* `shouldAdvanceTime` keeps `waitFor`'s own polling alive while the fake clock is installed;
       without it the assertion below never gets a chance to run. */
    vi.useFakeTimers({ shouldAdvanceTime: true });
    listBroadcasts.mockResolvedValue({
      ok: true,
      // Every campaign terminal: nothing on this page can move without somebody pressing something.
      data: pageOf([makeBroadcast({ state: "completed", isTerminal: true })]),
    });
    renderScreen();

    await waitFor(() => {
      expect(getBroadcastStats).toHaveBeenCalledTimes(1);
    });
    await vi.advanceTimersByTimeAsync(BROADCAST_POLL_MS * 5);
    /* An idle deployment makes no requests AT ALL. A strip that polled unconditionally would be a
       request every five seconds, for ever, for four numbers that cannot change until somebody
       composes a campaign — and composing one invalidates the key anyway. */
    expect(getBroadcastStats).toHaveBeenCalledTimes(1);
  });

  it("refreshes the strip on the list's clock while a campaign is sending", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    listBroadcasts.mockResolvedValue({
      ok: true,
      data: pageOf([
        makeBroadcast({ state: "sending", isTerminal: false, progress: SENDING_PROGRESS }),
      ]),
    });
    renderScreen();

    await waitFor(() => {
      expect(getBroadcastStats).toHaveBeenCalledTimes(1);
    });
    await vi.advanceTimersByTimeAsync(BROADCAST_POLL_MS * 3);
    /* The gate is the list's verdict, not the strip's: this response is four totals and cannot
       tell a worker delivering forty thousand messages from a deployment asleep since Tuesday. */
    await waitFor(() => {
      expect(getBroadcastStats.mock.calls.length).toBeGreaterThan(1);
    });
  });
});
