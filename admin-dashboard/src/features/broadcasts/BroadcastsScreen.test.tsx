import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BroadcastsFilters, BroadcastsPage } from "@/api/broadcasts";
import { BroadcastsScreen } from "@/features/broadcasts/BroadcastsScreen";
import { SENDING_PROGRESS, makeBroadcast } from "@/features/broadcasts/fixtures";
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
 *
 * Only the FETCHER is replaced; every schema, enum and hook the screen reads is the real one.
 */

const { listBroadcasts } = vi.hoisted(() => ({ listBroadcasts: vi.fn() }));

vi.mock("@/api/broadcasts", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listBroadcasts };
});

const EMPTY_PAGE: BroadcastsPage = {
  items: [],
  meta: { nextCursor: null, total: 0, isTotalExact: true },
};

function pageOf(items: BroadcastsPage["items"]): BroadcastsPage {
  return { items, meta: { nextCursor: null, total: items.length, isTotalExact: true } };
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
