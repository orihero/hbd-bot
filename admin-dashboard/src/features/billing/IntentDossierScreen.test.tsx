/**
 * One payment's dossier.
 *
 * Four things are pinned here and each is a promise this section makes that would be easy to
 * break by accident:
 *
 * 1. **The settle-by-hand card renders a command and nothing else.** No form, no submit, no
 *    mutation — the only control in it copies text. That transition is the one move in the
 *    state machine that names no holder and therefore drops the mutex, and the evidence that
 *    authorises it is a charge in a cabinet this process is structurally forbidden to see.
 * 2. **The notify button is disabled with its reason showing**, for each of the three refusals,
 *    rather than discovering the refusal as a red banner after a round trip.
 * 3. **The idempotency key never reaches the DOM.** It is shaped `topup:{tg}:{scope}:{seq}` and
 *    embeds the customer's Telegram id, which is why `public_ref` exists. It is absent from
 *    every view model; this test is the backstop that would catch it being put back.
 * 4. **The chain-stop panel is always rendered**, including the single-song case where the
 *    honest answer is that the question is unanswerable by construction. A hidden panel reads
 *    as a screen that failed to load.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NOTIFY_REFUSAL_VALUES, type NotifyRefusal } from "@/api/billing";
import { en } from "@/i18n/locales/en";
import { useAuthStore } from "@/state/auth";

import { IntentDossierScreen } from "./IntentDossierScreen";
import { FIXTURE_INTENT_ID, FIXTURE_PUBLIC_REF, makeDossier, makeIntent, makeLifeline, makeReceipt } from "./fixtures";

const { getIntentDossier } = vi.hoisted(() => ({ getIntentDossier: vi.fn() }));

vi.mock("@/api/billing", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getIntentDossier };
});

function renderDossier(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/billing/intents/${FIXTURE_INTENT_ID}`]}>
        <Routes>
          <Route path="/billing/intents/:intentId" element={<IntentDossierScreen />} />
          <Route path="/billing/intents" element={<p>payments</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const REFUSAL_COPY: Readonly<Record<NotifyRefusal, string>> = {
  not_paid: en.billing.notify.refusalNotPaid,
  buyer_erased: en.billing.notify.refusalBuyerErased,
  already_notified: en.billing.notify.refusalAlreadyNotified,
};

beforeEach(() => {
  getIntentDossier.mockResolvedValue({ ok: true, data: makeDossier() });
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

describe("IntentDossierScreen — settle by hand is text, not a button", () => {
  it("renders the command with a copy control and no submit path", async () => {
    renderDossier();

    const card = await screen.findByTestId("settle-by-hand");
    expect(within(card).getByTestId("settle-command")).toHaveTextContent(
      `python -m bayram.payme.cli settle --ref ${FIXTURE_PUBLIC_REF}`,
    );
    // Exactly one control in the whole card, and it is the copy button.
    const buttons = within(card).getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveAttribute("data-testid", "settle-copy");
    // No form to submit, either.
    expect(card.querySelector("form")).toBeNull();
  });

  it("puts the cabinet reference beside it, which is what the check depends on", async () => {
    getIntentDossier.mockResolvedValue({
      ok: true,
      data: makeDossier({ receipt: makeReceipt({ reference: "66a1f0c2e4b7d3a19f5c8b20" }) }),
    });
    renderDossier();

    const card = await screen.findByTestId("settle-by-hand");
    expect(card).toHaveTextContent("66a1f0c2e4b7d3a19f5c8b20");
    expect(card).toHaveTextContent(en.billing.dossier.settleByHandCaveat);
  });
});

describe("IntentDossierScreen — the notify action", () => {
  for (const refusal of NOTIFY_REFUSAL_VALUES) {
    it(`is disabled with its reason showing for ${refusal}`, async () => {
      getIntentDossier.mockResolvedValue({
        ok: true,
        data: makeDossier({
          notify: { canNotify: false, refusalCode: refusal, notifiedAt: null },
        }),
      });
      renderDossier();

      const button = await screen.findByRole("button", { name: en.billing.notify.action });
      expect(button).toBeDisabled();
      // The reason is on screen before any round trip: all three are evaluable from the
      // payment row alone, which is why they ride on the READ.
      expect(screen.getByTestId("notify-refusal")).toHaveTextContent(REFUSAL_COPY[refusal]);
    });
  }

  it("is enabled with no refusal when the payment is settled and unannounced", async () => {
    getIntentDossier.mockResolvedValue({
      ok: true,
      data: makeDossier({
        intent: makeIntent({ state: "paid", settledAt: "2026-09-10T08:02:00Z" }),
        notify: { canNotify: true, refusalCode: null, notifiedAt: null },
      }),
    });
    renderDossier();

    const button = await screen.findByRole("button", { name: en.billing.notify.action });
    expect(button).toBeEnabled();
    expect(screen.queryByTestId("notify-refusal")).not.toBeInTheDocument();
  });

  it("is hidden entirely from a role without payment.notify", async () => {
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000003",
        username: "readonly",
        role: "viewer",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    renderDossier();
    await screen.findByTestId("settle-by-hand");
    // Hidden, not disabled: a press would be a 403 and a `permission.denied` row against
    // somebody who did nothing wrong.
    expect(
      screen.queryByRole("button", { name: en.billing.notify.action }),
    ).not.toBeInTheDocument();
  });
});

describe("IntentDossierScreen — privacy", () => {
  it("renders no idempotency key anywhere on the page", async () => {
    renderDossier();
    await screen.findByTestId("settle-by-hand");
    const rendered = document.body.textContent ?? "";
    // `topup:{tg}:{scope}:{seq}` / `plan:starter:{tg}:{scope}:{seq}` embed the customer's
    // Telegram id. They are absent from every view model, and a tooltip would not have stopped
    // one reaching a DOM node, a screenshot and a support ticket.
    expect(rendered).not.toContain("topup:");
    expect(rendered).not.toContain("plan:starter:");
  });

  it("renders an erased buyer as a state with the amount intact", async () => {
    getIntentDossier.mockResolvedValue({
      ok: true,
      data: makeDossier({
        intent: makeIntent({
          state: "paid",
          settledAt: "2026-09-10T08:02:00Z",
          telegramUserIdMasked: null,
          isBuyerErased: true,
        }),
        lifeline: makeLifeline([
          { key: "receipt", status: "not_applicable", at: null, noteCode: "buyer_erased" },
        ]),
      }),
    });
    renderDossier();

    expect(await screen.findByTestId("dossier-buyer-erased")).toHaveTextContent(
      en.billing.intents.buyerErased,
    );
    // Money columns survive `/forget` by design.
    expect(screen.getByTestId("dossier-intent")).toHaveTextContent("7 000");
  });
});

describe("IntentDossierScreen — where the chain stops", () => {
  it("states the single-song answer rather than hiding the panel", async () => {
    renderDossier();
    const panel = await screen.findByTestId("dossier-chain-stop");
    expect(panel).toHaveTextContent(en.billing.dossier.chainStopSingle);
  });

  it("counts songs against a plan receipt", async () => {
    getIntentDossier.mockResolvedValue({
      ok: true,
      data: makeDossier({
        intent: makeIntent({ product: "starter", planSongs: 5, planDays: 30 }),
        chainStop: {
          kind: "plan",
          songsUsed: 2,
          songsIncluded: 5,
          planEndsAt: "2026-10-10T08:00:00Z",
        },
      }),
    });
    renderDossier();

    const panel = await screen.findByTestId("dossier-chain-stop");
    expect(panel).toHaveTextContent("2 of 5 songs used");
  });
});

describe("IntentDossierScreen — Payme's calls", () => {
  it("says Payme never called when the payment is younger than the journal's retention", async () => {
    renderDossier();
    await waitFor(() => {
      expect(screen.getByTestId("dossier-calls")).toHaveTextContent(
        en.billing.dossier.callsNever,
      );
    });
  });

  it("says PURGED when the payment outlived the 90-day journal", async () => {
    getIntentDossier.mockResolvedValue({
      ok: true,
      data: makeDossier({
        // Older than PAYME_RPC_LOG_RETENTION_DAYS. A paid payment is never purged while the
        // journal beneath it is swept, and there are no foreign keys between the two — so an
        // empty call list here is ORDINARY and must not read as "settled by hand".
        intent: makeIntent({ createdAt: "2020-01-01T00:00:00Z" }),
      }),
    });
    renderDossier();

    await waitFor(() => {
      expect(screen.getByTestId("dossier-calls")).toHaveTextContent(
        en.billing.dossier.callsPurged,
      );
    });
  });
});
