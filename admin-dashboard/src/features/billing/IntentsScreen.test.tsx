/**
 * The payments list.
 *
 * Three properties make this a list of PAYMENTS rather than a list of rows, and each is a
 * thing an operator would misread if it broke:
 *
 * 1. **An erased buyer and a masked one are two different facts.** `/forget` nulls
 *    `payment_intents.telegram_user_id` and the money columns survive by design, so a row whose
 *    buyer is gone must read "buyer erased" with its amount intact — never blank (which reads
 *    as a rendering fault), never an error, and never collapsed with the masked form.
 * 2. **The attention filter and the server compute one population.** `?attention=` reaches the
 *    server as the population's NAME and one predicate answers both the count and the rows, so
 *    the filter has to round-trip through the URL codec unchanged — including the staleness
 *    cutoff, which is the one input to that predicate a caller can move.
 * 3. **Amounts are minor units in the currency the payment recorded.** Payme quotes tiyin, and
 *    the console formats them through the dashboard's own `money()` rather than a second
 *    exponent table, because two tables eventually disagree about a currency and quote a
 *    receipt at a hundredth of what the customer paid.
 * 4. **The strip above the table is four counts and no rate.** A tile prints a dash rather than
 *    a zero for anything this rail has never done, and the notify invalidates the attention
 *    counters — the one number in this console a re-sent confirmation actually moves.
 *
 * Only the FETCHER is replaced; every schema, hook and formatter is the real one.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { JSX } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BillingWindowQuery, IntentFilters } from "@/api/billing";
import { en } from "@/i18n/locales/en";
import { useAuthStore } from "@/state/auth";

import { IntentsScreen } from "./IntentsScreen";
import {
  makeAttention,
  makeIntent,
  makeIntentPage,
  makeRailFunnel,
  makeRailStatus,
} from "./fixtures";
import { useNotifyPayment } from "./useRail";

const { getAttention, getRailFunnel, getRailStatus, listIntents, postIntentNotify } = vi.hoisted(
  () => ({
    getAttention: vi.fn(),
    getRailFunnel: vi.fn(),
    getRailStatus: vi.fn(),
    listIntents: vi.fn(),
    postIntentNotify: vi.fn(),
  }),
);

vi.mock("@/api/billing", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getAttention, getRailFunnel, getRailStatus, listIntents, postIntentNotify };
});

/** The em dash `PageStats` prints in place of a figure nobody measured. Never a zero. */
const NO_VALUE = "—";

/**
 * One tile of the strip, as a single element, so a test can read its value AND its caption.
 *
 * Addressed by `PageStat.key` — which is what that field is for — and not by its label text:
 * "Settled" is also a column heading in the table below, so a text query would be ambiguous on
 * exactly the screen this strip sits on.
 */
function tile(key: string): HTMLElement {
  const box = document.getElementById(`page-stat-${key}-label`)?.closest("li") ?? null;
  if (box === null) throw new Error(`no tile for "${key}"`);
  return box;
}

/** What a tile is currently saying. Used inside `waitFor`: the strip loads after the labels. */
function tileText(key: string): string {
  return tile(key).textContent ?? "";
}

/** `/billing` IS this screen — the section has no board in front of it. */
function renderList(url = "/billing"): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/billing" element={<IntentsScreen />} />
          <Route path="/billing/calls" element={<p>journal</p>} />
          <Route path="/billing/intents/:intentId" element={<p>dossier</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function lastFilters(): Promise<IntentFilters> {
  await waitFor(() => {
    expect(listIntents).toHaveBeenCalled();
  });
  const calls = listIntents.mock.calls;
  return calls[calls.length - 1]?.[0] as IntentFilters;
}

beforeEach(() => {
  listIntents.mockResolvedValue({ ok: true, data: makeIntentPage() });
  getRailStatus.mockResolvedValue({ ok: true, data: makeRailStatus() });
  /* The deployment as it stands: nothing opened, nothing settled, nothing heard. Every strip
     test that wants numbers says so; the rest inherit a rail that has never run, which is the
     state these tiles have to render honestly. */
  getRailFunnel.mockResolvedValue({ ok: true, data: makeRailFunnel() });
  getAttention.mockResolvedValue({ ok: true, data: makeAttention() });
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

describe("IntentsScreen — the buyer column", () => {
  it("renders an erased buyer as a state, with the amount intact and visibly distinct", async () => {
    listIntents.mockResolvedValue({
      ok: true,
      data: makeIntentPage([
        makeIntent({
          intentId: "aaaaaaaa-1111-4111-8111-111111111111",
          publicRef: "aaaaaaaaaaaaaaaaaaaaaaaa",
          telegramUserIdMasked: null,
          isBuyerErased: true,
          state: "paid",
          settledAt: "2026-09-10T08:02:00Z",
          settleSource: "rail",
          settleNote: "payme",
        }),
        makeIntent({
          intentId: "bbbbbbbb-1111-4111-8111-111111111111",
          publicRef: "bbbbbbbbbbbbbbbbbbbbbbbb",
          telegramUserIdMasked: "•••4321",
          isBuyerErased: false,
        }),
      ]),
    });
    renderList();

    // The erased row says so in words, and the masked row shows the server's mask. Two
    // different cells, because they are two different facts.
    const erased = await screen.findByTestId("buyer-erased");
    expect(erased).toHaveTextContent(en.billing.intents.buyerErased);
    expect(screen.getByTestId("buyer-masked")).toHaveTextContent("•••4321");

    // Money survives erasure by design, so the amount is still on the erased row itself.
    const erasedRow = erased.closest("tr");
    expect(erasedRow).not.toBeNull();
    expect(erasedRow?.textContent ?? "").toContain("7 000");
  });

  it("draws no reveal affordance anywhere in the table", async () => {
    listIntents.mockResolvedValue({
      ok: true,
      data: makeIntentPage([makeIntent()]),
    });
    renderList();
    const table = await screen.findByRole("table");
    // A payer identity is a `POST /api/reveal` question. A button here could only ever fail,
    // and a button that always fails is worse than no button.
    expect(within(table).queryByTestId("masked-value-reveal")).not.toBeInTheDocument();
  });
});

describe("IntentsScreen — money", () => {
  it("renders a UZS tiyin amount as whole soʻm", async () => {
    listIntents.mockResolvedValue({
      ok: true,
      // 700 000 tiyin is 7 000 soʻm — the single-song price. A second exponent table would
      // have rendered this as 700 000 or as 70.
      data: makeIntentPage([makeIntent({ amountMinor: 700_000, currency: "UZS" })]),
    });
    renderList();

    // The whole cell, because the unit is its own span: `7 000` and `soʻm` are one figure
    // rendered in two nodes so the unit can be de-emphasised without splitting the number.
    const amount = await screen.findByText("soʻm");
    expect(amount.closest("td")?.textContent ?? "").toContain("7 000");
  });
});

describe("IntentsScreen — filters round-trip through the URL", () => {
  it("carries ?attention= to the request unchanged", async () => {
    renderList("/billing?attention=paid_unnotified");
    const filters = await lastFilters();
    expect(filters.attention).toBe("paid_unnotified");
    // The cutoff is only meaningful for the stale population, so it is not sent here.
    expect(filters.staleAfterHours).toBeNull();
  });

  it("carries the staleness cutoff with the population it qualifies", async () => {
    renderList("/billing?attention=awaiting_stale&staleAfterHours=24");
    const filters = await lastFilters();
    expect(filters.attention).toBe("awaiting_stale");
    // Without this, the chip on the board and the list behind it would count against two
    // different cutoffs and could honestly disagree.
    expect(filters.staleAfterHours).toBe(24);
  });

  it("defaults the cutoff rather than leaving it null for the stale population", async () => {
    renderList("/billing?attention=awaiting_stale");
    const filters = await lastFilters();
    // Defaulted here so the key holds the value the server will use; otherwise a bare
    // `?attention=awaiting_stale` and a chip carrying `12` would be two cache entries.
    expect(filters.staleAfterHours).toBe(12);
  });

  it("drops an unknown enum member instead of 422-ing the whole page", async () => {
    renderList("/billing?state=paid&state=nonsense");
    const filters = await lastFilters();
    // A hand-edited link degrades to a wider view, which is legible. A 422 would blank the
    // table with a red banner about a filter nobody chose.
    expect(filters.state).toEqual(["paid"]);
  });

  it("reads sandbox=false as a real filter, not as unset", async () => {
    renderList("/billing?sandbox=false");
    const filters = await lastFilters();
    expect(filters.sandbox).toBe(false);
  });
});

describe("IntentsScreen — the three empties", () => {
  it("says no payment has ever been opened when the probe says so", async () => {
    listIntents.mockResolvedValue({
      ok: true,
      data: makeIntentPage([], {
        capabilities: {
          hasOpenedAnyIntent: false,
          hasRecordedTransaction: false,
          hasSettledAnyIntent: false,
        },
      }),
    });
    renderList();
    expect(await screen.findByText(en.billing.intents.emptyVirgin)).toBeInTheDocument();
  });

  it("says nothing matches when payments exist but none is in range", async () => {
    listIntents.mockResolvedValue({
      ok: true,
      data: makeIntentPage([], {
        capabilities: {
          hasOpenedAnyIntent: true,
          hasRecordedTransaction: true,
          hasSettledAnyIntent: true,
        },
      }),
    });
    renderList();
    // The probe, not the row count: `0` alone cannot tell these two apart, and they have
    // different remedies.
    expect(await screen.findByText(en.billing.intents.emptyFiltered)).toBeInTheDocument();
  });
});

describe("IntentsScreen — the filter panel is the screen's only narrowing", () => {
  it("opens itself when the URL already carries a question", async () => {
    renderList("/billing?state=paid");
    // A pasted link has to SHOW what it is asking, or the rows look like the whole ledger.
    const toggle = await screen.findByRole("button", { name: /Filters/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("stays shut on an unfiltered page and opens on request", async () => {
    const user = userEvent.setup();
    renderList();
    const toggle = await screen.findByRole("button", { name: en.common.filters });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group", { name: en.billing.intents.chips.state })).toBeInTheDocument();
  });

  it("sends a toggled state to the server and drops the cursor with it", async () => {
    const user = userEvent.setup();
    renderList("/billing?cursor=abc");
    await user.click(await screen.findByRole("button", { name: /Filters/ }));
    await user.click(screen.getByRole("button", { name: "paid", pressed: false }));

    await waitFor(async () => {
      expect((await lastFilters()).state).toEqual(["paid"]);
    });
    // Page two of the OLD question would be rows nobody asked for under the new chip.
    const page = listIntents.mock.calls[listIntents.mock.calls.length - 1]?.[1] as {
      cursor: string | null;
    };
    expect(page.cursor).toBeNull();
  });

  it("offers the enum members in the words the table prints", async () => {
    const user = userEvent.setup();
    renderList();
    await user.click(await screen.findByRole("button", { name: en.common.filters }));
    // The State column renders `row.state` raw, so a toggle that said "Paid" would be a word
    // the operator has to translate before they can trust the filter.
    for (const member of ["pending", "awaiting", "paid", "cancelled", "expired"]) {
      expect(screen.getByRole("button", { name: member })).toBeInTheDocument();
    }
  });
});

describe("IntentsScreen — the pause switch rides in the toolbar", () => {
  it("offers Pause to a role that holds the cell, and Resume once the rail is paused", async () => {
    renderList();
    expect(
      await screen.findByRole("button", { name: en.billing.pause.pauseAction }),
    ).toBeInTheDocument();

    getRailStatus.mockResolvedValue({ ok: true, data: makeRailStatus({ isPaused: true }) });
    renderList();
    expect(
      await screen.findByRole("button", { name: en.billing.pause.resumeAction }),
    ).toBeInTheDocument();
  });

  it("draws no switch at all for a role without the cell", async () => {
    // Hidden rather than disabled: a press would be a 403 and a `permission.denied` audit row
    // against somebody who did nothing wrong.
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000002",
        username: "support",
        role: "support",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    renderList();
    await screen.findByRole("table");
    expect(
      screen.queryByRole("button", { name: en.billing.pause.pauseAction }),
    ).not.toBeInTheDocument();
  });
});

describe("IntentsScreen — the strip above the filters", () => {
  it("prints the window's MONEY, and settles on `performed` alone", async () => {
    getRailFunnel.mockResolvedValue({
      ok: true,
      data: makeRailFunnel({
        // Sparse, as the wire sends it: an intent is in exactly one state, so the total is
        // every payment opened in the window. 12 payments at 15 000 soʻm = 180 000 soʻm, in
        // tiyin — the amounts and the counts are deliberately NOT in proportion to each other
        // across the two lists, so a tile that read the wrong field cannot coincidentally pass.
        intents: [
          { state: "paid", count: 9, amountMinor: 135_000_00, currency: "UZS" },
          { state: "expired", count: 3, amountMinor: 45_000_00, currency: "UZS" },
        ],
        // Seven charges arrived; two cards declined. A tile labelled "Settled" that summed the
        // list would say 9 and would be counting declines as money. Transactions carry no
        // currency — Payme denominates in soʻm and the column does not exist.
        transactions: [
          { state: "performed", count: 7, amountMinor: 105_000_00, currency: null },
          { state: "cancelled", count: 2, amountMinor: 30_000_00, currency: null },
        ],
        rpcCalls: 41,
        rpcFaults: 4,
        hasOpenedAnyIntent: true,
        hasRecordedTransaction: true,
        hasRecordedInboundCall: true,
      }),
    });
    getAttention.mockResolvedValue({
      ok: true,
      data: makeAttention({
        awaitingHeldPastTimeout: 1,
        paidNeverAnnounced: 2,
        paidWithNoReceipt: 3,
      }),
    });
    renderList();

    // The labels are on screen while the figures are still in flight — that is the skeleton
    // arm doing its job — so the wait is for the number, not for the tile.
    await waitFor(() => {
      expect(tileText("intents")).toContain("12");
    });
    expect(tileText("intents")).toContain(en.billing.stats.intents);
    expect(tileText("settled")).toContain("7");
    expect(tileText("faults")).toContain("4");
    // One queue as far as this strip is concerned: 1 + 2 + 3 payments somebody must look at.
    expect(tileText("attention")).toContain("6");
  });

  it("dashes a count this rail has never recorded, rather than printing a zero", async () => {
    getRailFunnel.mockResolvedValue({
      ok: true,
      // The probes are the whole point: no inbound call has ever arrived, so `rpcFaults: 0` is
      // silence, not a clean bill of health, and `0` beside "Faults" would read as health.
      data: makeRailFunnel({ hasOpenedAnyIntent: false, hasRecordedInboundCall: false }),
    });
    renderList();

    await waitFor(() => {
      expect(tileText("faults")).toContain(NO_VALUE);
    });
    // The dash is not allowed to stand there in silence: a blank reads as a broken panel, and
    // "this has never run here" is a fact about the deployment with its own remedy.
    expect(tileText("faults")).toContain(en.common.stats.unavailable.notInstrumented);
    expect(tileText("intents")).toContain(NO_VALUE);
    // And a zero that IS a measurement still prints: the attention route carries no probe
    // because it needs none — nothing is stuck, whatever this rail has or has not done.
    expect(tileText("attention")).toContain("0");
  });

  it("renders the payments table even when both aggregates fail", async () => {
    /* A 409 rather than a 503, and only because 5xx is RETRYABLE here: `LIST_READ` carries
       `shouldRetryRead`, which overrides the client's `retry: false`, so a 503 would leave this
       test sitting out two backoffs before the dash it is asserting on ever appeared. The
       status does not matter to what is being checked, which is what the screen renders once
       the aggregate has failed. */
    const failure = {
      ok: false,
      code: "CONFLICT",
      message: "the aggregate could not be read",
      status: 409,
      endpoint: "GET /api/metrics/rail/funnel",
      correlationId: "corr-9",
      issues: null,
      details: null,
      retryAfterS: null,
    };
    getRailFunnel.mockResolvedValue(failure);
    getAttention.mockResolvedValue({ ...failure, endpoint: "GET /api/metrics/rail/attention" });
    listIntents.mockResolvedValue({ ok: true, data: makeIntentPage([makeIntent()]) });
    renderList();

    // The ledger is the work; the aggregates are context. A failed strip is four dashes here,
    // and the table below it is a separate read that must still arrive.
    expect(await screen.findByRole("table")).toBeInTheDocument();
    await waitFor(() => {
      expect(tileText("settled")).toContain(NO_VALUE);
    });
    expect(tileText("attention")).toContain(NO_VALUE);
  });

  it("asks the funnel for the window the table is filtered to, and for nothing else", async () => {
    renderList("/billing?from=2026-09-01T00:00:00Z&to=2026-09-08T00:00:00Z&state=paid");

    await waitFor(() => {
      expect(getRailFunnel).toHaveBeenCalled();
    });
    const calls = getRailFunnel.mock.calls;
    const window = calls[calls.length - 1]?.[0] as BillingWindowQuery;
    expect(window.from).toBe("2026-09-01T00:00:00Z");
    expect(window.to).toBe("2026-09-08T00:00:00Z");
    // `state` is not on this route. A strip that pretended to carry the chips would answer a
    // wider question than it appeared to.
    expect(Object.keys(window)).toEqual(["from", "to"]);
  });

  it("never asks for the settlement identity, and prints no rate", async () => {
    renderList();
    await screen.findByRole("table");
    // `/metrics/rail/settlement` 422s without an explicit `from`, and the ratio it would feed
    // has a denominator dominated by stub-rail traffic: a percentage about the sandbox wearing
    // the name of the business. Four tiles, and the fourth is a queue depth, not a rate.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem").length).toBe(4);
  });
});

/**
 * A stand-in for the dossier's Re-send button, mounted beside the list inside ONE query client.
 *
 * The notify does not live on this screen — it lives on the dossier — but its invalidation is a
 * fact about this one, because `paidNeverAnnounced` is the counter it moves and this strip is
 * where an operator reads that counter. Two screens, one cache: the bug being guarded against
 * is a freshly-updated table sitting under a stale number.
 */
function NotifyProbe(): JSX.Element {
  const notify = useNotifyPayment();
  return (
    <button
      type="button"
      onClick={() => {
        notify.mutate({
          intentId: "aaaaaaaa-1111-4111-8111-111111111111",
          body: { reasonCode: "customer_request" },
        });
      }}
    >
      re-send
    </button>
  );
}

describe("IntentsScreen — a re-sent confirmation must not leave the strip stale", () => {
  it("invalidates the attention counters, so the strip re-reads with the table", async () => {
    const user = userEvent.setup();
    getAttention.mockResolvedValue({
      ok: true,
      data: makeAttention({ paidNeverAnnounced: 3 }),
    });
    postIntentNotify.mockResolvedValue({
      ok: true,
      data: {
        intentId: "aaaaaaaa-1111-4111-8111-111111111111",
        publicRef: "aaaaaaaaaaaaaaaaaaaaaaaa",
        jobId: "payme-notify:aaaaaaaaaaaaaaaaaaaaaaaa",
        isReplay: false,
        enqueuedAt: "2026-09-10T09:05:00Z",
      },
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/billing"]}>
          <Routes>
            <Route
              path="/billing"
              element={
                <>
                  <IntentsScreen />
                  <NotifyProbe />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(tileText("attention")).toContain("3");
    });

    // The worker stamps `notified_at` seconds later, so the SERVER is what has moved on. The
    // console learns it by asking again.
    getAttention.mockResolvedValue({
      ok: true,
      data: makeAttention({ paidNeverAnnounced: 2 }),
    });
    await user.click(screen.getByRole("button", { name: "re-send" }));

    await waitFor(() => {
      expect(getAttention).toHaveBeenCalledTimes(2);
    });
    // Without the attention key on that mutation's `onSuccess` the strip would still read 3
    // above a table that had just dropped to 2 — and the strip is the one an operator reads
    // without scrolling.
    await waitFor(() => {
      expect(tileText("attention")).toContain("2");
    });
  });
});
