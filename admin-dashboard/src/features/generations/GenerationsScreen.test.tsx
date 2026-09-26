import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { LedgerWindow, NameAnalyticsView } from "@/api/dashboard";
import type { AttemptWireView, AttemptsPage, GenerationsFilters } from "@/api/generations";
import { formatCount } from "@/features/dashboard/adapt";
import { GenerationsScreen } from "@/features/generations/GenerationsScreen";
import { useAuthStore } from "@/state/auth";

/**
 * The render ledger's stat strip.
 *
 * ADMIN_PANEL_PLAN §11.2 names this screen's question as "is name verification working", and
 * every test below is one way the strip can answer that question dishonestly:
 *
 * 1. **The rate is the SPA's, formed from two integers.** The response also carries a
 *    server-computed `verificationRate`; the fixtures deliberately set it to a figure that is
 *    NOT `verified / attempts`, so a screen that printed it fails here rather than in a support
 *    thread about a percentage nobody can reproduce.
 * 2. **Neither end of the rounding is allowed to lie.** 999 of 1 000 is not "every name
 *    verified", and 1 of 1 000 is not "none".
 * 3. **`0` is a measurement and an absent figure is not.** "Nothing was checked in this window"
 *    and "acoustic verification has never run here" are two facts with two different remedies,
 *    and the wire tells them apart with `hasRecordedAttempts` — so the strip must too.
 * 4. **A refusal stays inside the strip.** `/api/metrics/name-analytics` is `DASHBOARD_READ`
 *    and the rows under it are `RECORDS_READ`: an operator can hold one grant and not the
 *    other, and a 403 on the aggregate must not take the ledger down with it.
 * 5. **One number, printed once.** The Toolbar subtitle used to state the same count the
 *    Attempts tile does; two spellings of one figure is how the two eventually disagree.
 */

const { listGenerations, getGeneration, nameAnalytics } = vi.hoisted(() => ({
  listGenerations: vi.fn(),
  getGeneration: vi.fn(),
  nameAnalytics: vi.fn(),
}));

/*
 * Only the FETCHERS are replaced. `importOriginal` keeps every schema, enum and helper the
 * screen reads out of these modules, so the test runs against the real contract with nothing
 * but the network standing still — and `@/features/dashboard/adapt`, which imports the same
 * dashboard module for its types, keeps working untouched.
 */
vi.mock("@/api/generations", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listGenerations, getGeneration };
});

vi.mock("@/api/dashboard", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, nameAnalytics };
});

/** One row, so the "the ledger survives" assertions have something to survive. */
const ROW: AttemptWireView = {
  id: "11111111-1111-4111-8111-111111111111",
  orderId: "22222222-2222-4222-8222-222222222222",
  kind: "name_verification",
  sequence: 1,
  attempt: 1,
  provider: "elevenlabs_music",
  providerRemoteId: null,
  language: "uz_latn",
  isSuccess: true,
  isOrphaned: false,
  nameCandidateStrategy: "canonical",
  nameCandidateRank: 1,
  isNameVerified: true,
  matchConfidence: 0.91,
  nameCandidate: null,
  identityPurgedAt: null,
  sttTranscriptChars: null,
  textPurgedAt: null,
  errorCode: null,
  errorMessage: null,
  isRetryable: null,
  /* Both null with `isInstrumented: false`, exactly as production writes them — which is why
     there is no cost tile and no latency tile for these tests to look for. */
  costUsd: null,
  costSource: null,
  latencyMs: null,
  isInstrumented: false,
  createdAt: "2026-09-14T08:30:00Z",
};

function pageOf(total: number | null, isTotalExact = true): AttemptsPage {
  return { items: [ROW], meta: { nextCursor: null, total, isTotalExact } };
}

/** A verification read, with only the figures a test cares about spelled out. */
function analytics(over: Partial<NameAnalyticsView>): NameAnalyticsView {
  return {
    window: null,
    threshold: null,
    thresholdBand: 0.05,
    bucketCount: 10,
    attempts: 0,
    verified: 0,
    /* Deliberately NOT `verified / attempts` in the fixtures that override the pair: the SPA
       must form the quotient itself, and this is what proves it did. */
    verificationRate: null,
    scored: 0,
    nearThreshold: null,
    hasRecordedAttempts: true,
    strategies: [],
    buckets: [],
    ...over,
  };
}

/*
 * `MemoryRouter`, deliberately NOT `createMemoryRouter` — a data router builds a `Request` per
 * navigation and jsdom's `AbortSignal` is not the one undici's `Request` accepts, so under this
 * environment `setSearchParams` would silently never move the URL.
 */
function renderScreen(url = "/generations"): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/generations" element={<GenerationsScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The tile carrying one label, once it holds a figure rather than a skeleton.
 *
 * The labels render immediately and the values do not, so every assertion below waits on the
 * strip's `aria-busy` rather than on any one tile: the whole row fills in one go — one busy
 * state for both reads — and a helper that waited per tile would pass against a strip that
 * filled in two stages under the reader.
 */
async function tile(label: string): Promise<HTMLElement> {
  const item = (await screen.findByText(label)).closest("li");
  if (item === null) throw new Error(`"${label}" is not inside a stat tile`);
  await waitFor(() => {
    expect(item.parentElement).toHaveAttribute("aria-busy", "false");
  });
  return item;
}

beforeEach(() => {
  listGenerations.mockResolvedValue({ ok: true, data: pageOf(1234) });
  getGeneration.mockResolvedValue({ ok: true, data: ROW });
  nameAnalytics.mockResolvedValue({
    ok: true,
    data: analytics({ attempts: 100, verified: 97, verificationRate: 0.5, scored: 100 }),
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

describe("GenerationsScreen — the stat strip", () => {
  it("prints the ledger's own total, the rate the SPA formed, and the sample it was formed over", async () => {
    renderScreen();

    expect(within(await tile("Attempts")).getByText(formatCount(1234))).toBeInTheDocument();
    // 97 of 100 — NOT the 0.5 the fixture put in `verificationRate`.
    expect(within(await tile("Pass rate")).getByText("97%")).toBeInTheDocument();
    expect(screen.queryByText("50%")).toBeNull();
    // The denominator beside the rate: three attempts and a thousand are the same percentage
    // and are not the same evidence, and this tile is the difference.
    expect(within(await tile("Checked")).getByText(formatCount(100))).toBeInTheDocument();
  });

  it("ships exactly three tiles, and neither of the two figures nobody measures", async () => {
    renderScreen();
    await tile("Attempts");

    // `cost_usd` and `latency_ms` are never written on this deployment, so a cost or latency
    // tile would be a made-up number in a 22px weight. The table's own columns still carry
    // both, where "not tracked" fits beside them.
    const labels = screen
      .getAllByRole("listitem")
      .map((item) => item.firstElementChild?.textContent);
    expect(labels).toEqual(["Attempts", "Pass rate", "Checked"]);
  });

  it("states the count once — the Toolbar subtitle that printed it is gone", async () => {
    renderScreen();
    await tile("Attempts");

    expect(screen.queryByText(`${formatCount(1234)} attempts in the render ledger`)).toBeNull();
    expect(screen.queryByText(`${formatCount(1234)} attempts match these filters`)).toBeNull();
  });

  it("says the count was not requested rather than standing a zero in for it", async () => {
    listGenerations.mockResolvedValue({ ok: true, data: pageOf(null) });
    renderScreen();

    const attempts = await tile("Attempts");
    expect(within(attempts).getByText("—")).toBeInTheDocument();
    expect(within(attempts).getByText("count not requested")).toBeInTheDocument();
    expect(within(attempts).queryByText("0")).toBeNull();
  });
});

describe("GenerationsScreen — the rate rounds towards the truth", () => {
  it("holds a window with one failure in it short of 100%", async () => {
    nameAnalytics.mockResolvedValue({
      ok: true,
      data: analytics({ attempts: 1000, verified: 999, verificationRate: 0.999 }),
    });
    renderScreen();

    // 99.9% rounds to 100, and "every name verified" is exactly the sentence somebody is on
    // this screen to disprove.
    expect(within(await tile("Pass rate")).getByText("99%")).toBeInTheDocument();
  });

  it("holds a window with one success in it above 0%", async () => {
    nameAnalytics.mockResolvedValue({
      ok: true,
      data: analytics({ attempts: 1000, verified: 1, verificationRate: 0.001 }),
    });
    renderScreen();

    expect(within(await tile("Pass rate")).getByText("1%")).toBeInTheDocument();
  });

  it("prints 100% only for a window that really did verify everything", async () => {
    nameAnalytics.mockResolvedValue({
      ok: true,
      data: analytics({ attempts: 40, verified: 40, verificationRate: 1 }),
    });
    renderScreen();

    expect(within(await tile("Pass rate")).getByText("100%")).toBeInTheDocument();
  });
});

describe("GenerationsScreen — the two kinds of empty", () => {
  it("names an uninstrumented verifier instead of reporting nought checked", async () => {
    nameAnalytics.mockResolvedValue({
      ok: true,
      data: analytics({ attempts: 0, verified: 0, hasRecordedAttempts: false }),
    });
    renderScreen();

    // `hasRecordedAttempts` is measured with the window IGNORED, so this is the state where a
    // zero would send an operator to widen a range that holds nothing at any width.
    const checked = await tile("Checked");
    expect(within(checked).getByText("—")).toBeInTheDocument();
    expect(within(checked).getByText("Nothing records this yet")).toBeInTheDocument();
    expect(within(checked).queryByText("0")).toBeNull();
    expect(
      within(await tile("Pass rate")).getByText("Nothing records this yet"),
    ).toBeInTheDocument();
  });

  it("counts an empty window as nought checked, and refuses a rate over it", async () => {
    nameAnalytics.mockResolvedValue({
      ok: true,
      data: analytics({ attempts: 0, verified: 0, hasRecordedAttempts: true }),
    });
    renderScreen();

    // The ledger holds verdicts; this range excludes them. Somebody measured that, so it is a
    // zero and not a dash — and there is still nothing to divide by.
    expect(within(await tile("Checked")).getByText("0")).toBeInTheDocument();
    const rate = await tile("Pass rate");
    expect(within(rate).getByText("—")).toBeInTheDocument();
    expect(within(rate).getByText("Nothing to divide by")).toBeInTheDocument();
  });
});

describe("GenerationsScreen — the verification read is its own query", () => {
  it("keeps the ledger and the count when the aggregate over them is refused", async () => {
    nameAnalytics.mockResolvedValue({
      ok: false,
      code: "FORBIDDEN",
      message: "This role cannot read dashboard metrics.",
      status: 403,
      endpoint: "GET /api/metrics/name-analytics",
      correlationId: "c0ffee",
      issues: null,
      details: null,
    });
    renderScreen();

    // The rows are `RECORDS_READ` and they are still here; only the two `DASHBOARD_READ` tiles
    // went blank, and the note says which read was refused and carries the id to chase it by.
    expect(within(await tile("Attempts")).getByText(formatCount(1234))).toBeInTheDocument();
    expect(screen.getByText("elevenlabs_music")).toBeInTheDocument();
    expect(
      await screen.findByText("name verification is not visible to this role"),
    ).toBeInTheDocument();
    expect(screen.getByText(/c0ffee/u)).toBeInTheDocument();

    // No invented caption under the dash: the six absence reasons say what the DATA could not
    // answer, and this read never happened at all.
    const checked = await tile("Checked");
    expect(within(checked).getByText("—")).toBeInTheDocument();
    expect(within(checked).queryByText("Nothing records this yet")).toBeNull();
  });

  it("asks that route for the window, and for none of the filters it cannot honour", async () => {
    renderScreen(
      "/generations?from=2026-09-01T00:00:00Z&to=2026-09-08T00:00:00Z" +
        "&provider=elevenlabs_music&isSuccess=false&kind=name_verification",
    );

    await waitFor(() => {
      expect(nameAnalytics).toHaveBeenCalled();
    });
    const asked = nameAnalytics.mock.calls[nameAnalytics.mock.calls.length - 1]?.[0] as LedgerWindow;
    // Exactly two keys. `/api/metrics/name-analytics` has no parameter for provider, kind or
    // outcome, and a screen that handed it `state` wholesale would look like it was filtering
    // these figures without doing it.
    expect(asked).toEqual({ from: "2026-09-01T00:00:00Z", to: "2026-09-08T00:00:00Z" });

    // The ledger, over the same window, DOES take all of them — which is the scope difference
    // the `Checked` tile exists to make visible.
    const filters = listGenerations.mock.calls[0]?.[0] as GenerationsFilters;
    expect(filters.provider).toBe("elevenlabs_music");
    expect(filters.isSuccess).toBe(false);
  });
});
