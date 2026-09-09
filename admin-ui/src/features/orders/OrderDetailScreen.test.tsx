import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import {
  DEFAULT_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  SOURCE_UNAVAILABLE_LABEL,
  type AttemptsPage,
  type BriefWireView,
  type CreditAccountView,
  type CreditLedgerPage,
  type OrderDetailView,
  type TimelineView,
  type UserDetailView,
  type UserView,
} from "@/api";
import {
  makeAsset,
  makeFailedStagePlan,
  makeOrder,
  makeStagePlan,
} from "@/components/domain/fixtures";
import {
  configFixture,
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { OrderDetailScreen } from "./OrderDetailScreen";
import { RETIRED_TABS } from "./orderDetailParams";

const ORDER_ID = "6f1b6c2e-1f3a-4a2b-8c9d-0e1f2a3b4c5d";
/** `makeOrder`'s own Telegram id — the key both customer queries are cut against. */
const CUSTOMER_ID = 123456789;
const ATTEMPTS_QUERY = { limit: DEFAULT_PAGE_LIMIT, cursor: undefined };
/** The card asks for the ACCOUNT, so it asks for the smallest legal page. */
const CREDITS_QUERY = { limit: MIN_PAGE_LIMIT };
const LYRIC_ASSET_ID = "c0ffee00-1111-4222-8333-444455556666";

function accountFixture(overrides: Partial<CreditAccountView> = {}): CreditAccountView {
  return {
    telegramUserId: CUSTOMER_ID,
    telegramUserIdMasked: "\u2022\u2022\u2022\u2022\u2022789",
    balance: 4,
    lifetimeGranted: 9,
    allowancePeriod: 3,
    ...overrides,
  };
}

/** `account: null` is "no `credit_accounts` row", which is NOT a balance of 0. */
function creditsFixture(account: CreditAccountView | null = accountFixture()): CreditLedgerPage {
  return { account, items: [], meta: { nextCursor: null, total: null, isTotalExact: null } };
}

function customerFixture(overrides: Partial<UserView> = {}): UserDetailView {
  return {
    user: {
      id: "5f5f5f5f-6666-4777-8888-999999999999",
      telegramUserId: CUSTOMER_ID,
      telegramUserIdMasked: "\u2022\u2022\u2022\u2022\u2022789",
      uiLanguage: "uz_latn",
      isBlocked: false,
      isProfilePresent: true,
      telegramUsernameMasked: "@G\u2022\u2022\u2022",
      firstNameMasked: "O\u2022\u2022\u2022",
      lastNameMasked: null,
      phoneMasked: null,
      phoneSharedAt: null,
      hasAvatar: false,
      avatarUrl: null,
      avatarFetchedAt: null,
      accountCreatedAt: "2026-01-04T08:00:00Z",
      firstOrderAt: "2026-01-05T08:00:00Z",
      lastOrderAt: "2026-05-01T09:00:00Z",
      orderCount: 7,
      paidOrderCount: 5,
      creditBalance: 4,
      lifetimeCreditsGranted: 9,
      allowancePeriod: 3,
      ...overrides,
    },
    ordersByState: [],
    deliveredOrderCount: 4,
    failedOrderCount: 1,
    creditsProjected: 4,
    inFlightRenderCount: 0,
  };
}

function attemptsFixture(): AttemptsPage {
  return {
    items: [
      {
        id: "9a9a9a9a-1111-4111-8111-999999999999",
        orderId: ORDER_ID,
        kind: "song",
        sequence: 1,
        attempt: 2,
        provider: "suno",
        providerRemoteId: null,
        language: "uz_latn",
        isSuccess: false,
        isOrphaned: false,
        nameCandidateStrategy: null,
        nameCandidateRank: null,
        isNameVerified: null,
        matchConfidence: null,
        nameCandidate: null,
        identityPurgedAt: null,
        sttTranscriptChars: null,
        textPurgedAt: null,
        errorCode: "MUSIC_PROVIDER_TIMEOUT",
        errorMessage: "provider did not answer",
        isRetryable: true,
        costUsd: null,
        costSource: null,
        latencyMs: null,
        isInstrumented: false,
        createdAt: "2026-05-01T09:20:00Z",
      },
    ],
    meta: { nextCursor: null, total: null, isTotalExact: null },
  };
}

/** The lyric sheet the deliverables card now renders, in the ONE mime `/text` will serve. */
function lyricAssetFixture() {
  return makeAsset({
    id: LYRIC_ASSET_ID,
    orderId: ORDER_ID,
    kind: "lyric_sheet",
    mime: "text/plain; charset=utf-8",
    durationS: 0,
    loudnessLufs: null,
  });
}

function briefFixture(): BriefWireView {
  return {
    id: "7a2c3d4e-5555-4666-8777-888899990000",
    occasion: "birthday",
    genre: "pop",
    vocalGender: "female",
    uiLanguage: "uz_latn",
    outputLanguage: "uz_latn",
    eventDay: 14,
    eventMonth: 5,
    recipientName: "Oʻktam",
    recipientScript: "latin",
    recipientLanguage: "uz_latn",
    candidateCount: 3,
    identityExpiresAt: "2026-06-01T00:00:00Z",
    identityPurgedAt: null,
    isIdentityPurged: false,
    noteChars: 180,
    hasApprovedLyrics: true,
    noteExpiresAt: "2026-06-01T00:00:00Z",
    notePurgedAt: null,
    isNotePurged: false,
  };
}

function timelineFixture(): TimelineView {
  return {
    events: [
      {
        at: "2026-05-01T09:00:00Z",
        kind: "order_created",
        source: "order",
        isInferred: false,
        label: null,
        referenceId: null,
      },
      {
        at: "2026-05-01T09:20:00Z",
        kind: "attempt_failed",
        source: "attempts",
        isInferred: true,
        label: "composing_song",
        referenceId: null,
      },
    ],
    availableSources: ["order", "attempts", "assets", "audit"],
    unavailableSources: ["chat", "payments"],
  };
}

function detailFixture(overrides: Partial<OrderDetailView> = {}): OrderDetailView {
  return {
    order: makeOrder({
      id: ORDER_ID,
      state: "failed",
      failedReason: "MUSIC_PROVIDER_TIMEOUT",
      isFailedReasonRetryable: true,
      deliveredAt: null,
    }),
    brief: briefFixture(),
    assets: [],
    attempts: [],
    stagePlan: makeFailedStagePlan(),
    timeline: timelineFixture(),
    ...overrides,
  };
}

/**
 * Everything the screen fetches on arrival, seeded.
 *
 * The attempts page is in that list now: hoisting the ledger out of the tabset means it is
 * requested on load, and a test that left it unseeded would be asserting against an error
 * state. The two customer queries — the credit account and the `users` row behind the order
 * count — are seeded for the same reason.
 */
function renderDetail(
  detail: OrderDetailView = detailFixture(),
  extra: (client: ReturnType<typeof makeTestQueryClient>) => void = () => undefined,
  options: { role?: Parameters<typeof meFixture>[0]; route?: string } = {},
) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.orders.detail(ORDER_ID), detail);
  client.setQueryData(queryKeys.orders.timeline(ORDER_ID), timelineFixture());
  client.setQueryData(queryKeys.orders.attempts(ORDER_ID, ATTEMPTS_QUERY), attemptsFixture());
  client.setQueryData(queryKeys.users.credits(CUSTOMER_ID, CREDITS_QUERY), creditsFixture());
  client.setQueryData(queryKeys.users.detail(CUSTOMER_ID), customerFixture());
  extra(client);
  return renderWithProviders(
    <Routes>
      <Route path="/orders/:orderId" element={<OrderDetailScreen />} />
    </Routes>,
    {
      client,
      route: options.route ?? `/orders/${ORDER_ID}`,
      me: meFixture(options.role ?? "owner"),
      config: configFixture(),
    },
  );
}

describe("OrderDetailScreen", () => {
  beforeEach(() => {
    resetPrefs();
  });

  /* §14, Slice 1d acceptance. */
  it("shows a 9-stage plan, not 11, with the two greeting stages ghosted", () => {
    renderDetail();

    expect(screen.getByTestId("scheduled-stage-count")).toHaveTextContent("9");
    expect(screen.getAllByTestId("pipeline-stage")).toHaveLength(11);

    for (const stage of ["writing_scripts", "rendering_greetings"]) {
      const node = document.querySelector(`[data-stage="${stage}"]`);
      expect(node).toHaveAttribute("data-planned", "false");
    }
  });

  it("highlights the failed stage with its error code and retryability", () => {
    renderDetail();

    const failed = document.querySelector('[data-stage="composing_song"]');
    expect(failed).toHaveAttribute("data-outcome", "failed");
    expect(failed).toHaveTextContent("MUSIC_PROVIDER_TIMEOUT");
    // `↻` retryable vs `■` terminal — the operator's real decision, one glyph away.
    expect(failed).toHaveTextContent("↻");
  });

  it("renders unknown retryability as unknown, never as terminal", () => {
    const plan = makeStagePlan();
    renderDetail(
      detailFixture({
        stagePlan: {
          ...plan,
          stages: plan.stages.map((status) =>
            status.stage === "composing_song"
              ? {
                  ...status,
                  outcome: "failed" as const,
                  attemptCount: 1,
                  failedAttemptCount: 1,
                  errorCode: "SOMETHING_NEW",
                  isRetryable: null,
                }
              : status,
          ),
        },
      }),
    );
    const failed = document.querySelector('[data-stage="composing_song"]');
    expect(failed).toHaveTextContent("unknown");
    expect(failed).not.toHaveTextContent("terminal");
  });

  /* §14: chat and payments read "not enabled in this deployment"; stateTransitions is
     labelled "inferred". */
  it("renders the sources legend so an absent section is not read as silence", () => {
    renderDetail();

    for (const source of ["chat", "payments"]) {
      const row = document.querySelector(`[data-source="${source}"]`);
      expect(row).toHaveAttribute("data-standing", "unavailable");
      expect(row).toHaveTextContent(SOURCE_UNAVAILABLE_LABEL);
    }

    const transitions = document.querySelector('[data-source="state_transitions"]');
    expect(transitions).toHaveAttribute("data-standing", "inferred");
    expect(transitions).toHaveTextContent("inferred");
  });

  it("keeps the legend beside the pipeline, not behind a tab", () => {
    renderDetail();
    // Visible on arrival, with the timeline tab merely the default panel.
    expect(screen.getByTestId("timeline-source-legend")).toBeInTheDocument();
    expect(screen.getAllByTestId("timeline-event")).toHaveLength(2);
  });

  it("marks a derived timeline row as inferred", () => {
    renderDetail();
    const rows = screen.getAllByTestId("timeline-event");
    expect(rows[1]).toHaveTextContent("inferred");
  });

  it("renders a purged recipient as a lock, never as a blank", () => {
    renderDetail(
      detailFixture({
        order: makeOrder({
          id: ORDER_ID,
          recipientName: null,
          isIdentityPurged: true,
          identityPurgedAt: "2026-05-14T03:00:00Z",
        }),
      }),
    );
    expect(screen.getAllByTestId("purged-value")[0]).toHaveTextContent("🔒 purged 2026-05-14");
  });

  /* WS2 task 5: the ledger is a SIBLING of the stepper now, not the third of three tabs. */
  it("renders the attempt ledger on load, with no tab to open", () => {
    renderDetail();

    const table = screen.getByRole("table", { name: "generation attempts" });
    expect(table).toHaveTextContent("MUSIC_PROVIDER_TIMEOUT");
    // `null` cost and latency are "not instrumented", never $0.00 / 0 ms.
    expect(table).toHaveTextContent("not instrumented");
    expect(table).not.toHaveTextContent("$0.00");
    // The whole tabset is gone: nothing here is behind a click any more.
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("fetches the attempts without waiting for a tab that no longer exists", () => {
    const { client } = renderDetail(detailFixture(), (seeded) => {
      seeded.removeQueries({ queryKey: queryKeys.orders.attempts(ORDER_ID, ATTEMPTS_QUERY) });
    });

    // The query ran on mount rather than sitting `idle` behind `tab === "attempts"`.
    const state = client.getQueryState(queryKeys.orders.attempts(ORDER_ID, ATTEMPTS_QUERY));
    expect(state?.fetchStatus).not.toBe("idle");
  });

  /* WS2 task 5: a pasted link naming a retired tab opens the order and shows that section,
     because every section is on the page now. */
  it.each(RETIRED_TABS)("still opens on a link that names the retired %s tab", (name) => {
    renderDetail(detailFixture(), () => undefined, {
      route: `/orders/${ORDER_ID}?tab=${name}`,
    });

    expect(screen.getByRole("table", { name: "generation attempts" })).toBeInTheDocument();
    expect(screen.getAllByTestId("timeline-event")).toHaveLength(2);
    expect(screen.getByLabelText("deliverables")).toBeInTheDocument();
  });

  /* WS2 task 4: the lyric sheet, with its reveal step-up untouched. */
  it("renders the lyric sheet inside the deliverables card, unrevealed", () => {
    renderDetail(detailFixture({ assets: [lyricAssetFixture()] }));

    const deliverables = screen.getByLabelText("deliverables");
    expect(deliverables).toContainElement(screen.getByTestId("lyric-sheet-panel"));
    // Nothing is fetched until the operator asks: reading the sheet is a charged, audited
    // reveal, so the control is offered and the text is absent.
    expect(screen.getByTestId("lyric-sheet-reveal")).toBeInTheDocument();
    expect(screen.queryByTestId("lyric-sheet-text")).not.toBeInTheDocument();
    // The approval badge is still the header chip, and it is a different fact.
    expect(deliverables).toHaveTextContent("Approved Lyrics");
    expect(deliverables).toHaveTextContent("\u2713 Approved");
    expect(screen.queryByTestId("lyric-sheet-absent")).not.toBeInTheDocument();
  });

  it("says there is no sheet rather than rendering an empty panel", () => {
    renderDetail();

    expect(screen.queryByTestId("lyric-sheet-panel")).not.toBeInTheDocument();
    const absent = screen.getByTestId("lyric-sheet-absent");
    expect(absent).toHaveTextContent("\u2014");
    expect(absent).toHaveTextContent("No lyric sheet has been rendered");
    // The badge is a brief fact and survives the absence of the asset.
    expect(screen.getByLabelText("deliverables")).toHaveTextContent("\u2713 Approved");
  });

  it("keeps the sheet behind the media-reveal cell a VIEWER does not hold", () => {
    renderDetail(detailFixture({ assets: [lyricAssetFixture()] }), () => undefined, {
      role: "viewer",
    });

    expect(screen.getByTestId("lyric-sheet-no-cell")).toBeInTheDocument();
    expect(screen.queryByTestId("lyric-sheet-reveal")).not.toBeInTheDocument();
  });
});

/**
 * WS2 task 2, the render half: the four financial fields the server has always sent.
 *
 * `retryCount` is the one with a trap in it. It counts ATTEMPTS, and today only
 * name-verification attempts are written, so a delivered three-song order reports `0` —
 * which read as a bare number beside the word "retries" says "this one went through
 * cleanly", the opposite of what it can mean.
 */
describe("OrderDetailScreen \u2014 the financial row", () => {
  beforeEach(() => {
    resetPrefs();
  });

  it("renders credits charged, the ledger status and the payment rail", () => {
    renderDetail(
      detailFixture({
        order: makeOrder({
          id: ORDER_ID,
          creditCost: 2,
          ledgerStatus: "settled",
          paymentRail: "credits",
        }),
      }),
    );

    expect(screen.getByTestId("credit-cost")).toHaveTextContent("2");
    expect(screen.getByTestId("ledger-status")).toHaveAttribute("data-status", "settled");
    expect(screen.getByTestId("ledger-status")).toHaveTextContent("settled");
    expect(screen.getByTestId("payment-rail")).toHaveAttribute("data-rail", "credits");
    expect(screen.getByTestId("payment-rail")).toHaveTextContent("credits");
  });

  /* A refund leaves net 0, which is what makes the order chargeable again — it is not an
     ending and it is not "never charged". */
  it("shows a refunded order as refunded, not as unmetered", () => {
    renderDetail(
      detailFixture({
        order: makeOrder({
          id: ORDER_ID,
          creditCost: 0,
          ledgerStatus: "refunded",
          paymentRail: "credits",
        }),
      }),
    );

    expect(screen.getByTestId("ledger-status")).toHaveAttribute("data-status", "refunded");
    expect(screen.getByTestId("credit-cost")).toHaveTextContent("0");
  });

  it("never renders retryCount as a bare 0", () => {
    renderDetail(
      detailFixture({ order: makeOrder({ id: ORDER_ID, state: "delivered", retryCount: 0 }) }),
    );

    expect(screen.getByTestId("retry-count")).toHaveTextContent("0");
    const facts = screen.getByLabelText("order facts");
    expect(facts).toHaveTextContent("attempts recorded");
    expect(facts).toHaveTextContent("Attempts, not retries");
    expect(facts).toHaveTextContent("name-verification attempts");
    // The word that would license the wrong reading is not on the screen.
    expect(facts).not.toHaveTextContent("render retries");
  });
});

/**
 * WS2 task 3: the Customer 360 card, which `OrderDetailView` cannot fill on its own.
 */
describe("OrderDetailScreen \u2014 Customer 360", () => {
  beforeEach(() => {
    resetPrefs();
  });

  it("renders the credit balance and the customer's order count", () => {
    renderDetail();

    const chip = screen.getByTestId("credit-balance-chip");
    expect(chip).toHaveAttribute("data-state", "held");
    expect(chip).toHaveTextContent("4 credits");
    expect(screen.getByLabelText("order facts")).toHaveTextContent("orders placed");
    expect(screen.getByLabelText("order facts")).toHaveTextContent("7");
  });

  /* The router's own distinction: no `credit_accounts` row is not a balance of 0. */
  it("renders a never-metered account differently from a balance of 0", () => {
    const zeroed = renderDetail(detailFixture(), (client) => {
      client.setQueryData(
        queryKeys.users.credits(CUSTOMER_ID, CREDITS_QUERY),
        creditsFixture(accountFixture({ balance: 0 })),
      );
    });
    const spent = screen.getByTestId("credit-balance-chip");
    expect(spent).toHaveAttribute("data-state", "spent");
    expect(spent).toHaveTextContent("0 credits");
    zeroed.unmount();

    renderDetail(detailFixture(), (client) => {
      client.setQueryData(queryKeys.users.credits(CUSTOMER_ID, CREDITS_QUERY), creditsFixture(null));
    });
    const never = screen.getByTestId("credit-balance-chip");
    expect(never).toHaveAttribute("data-state", "never-metered");
    expect(never).toHaveTextContent("never metered");
    expect(never).not.toHaveTextContent("0");
  });

  /*
   * The other half of "null is not zero": UNKNOWN is not null either.
   *
   * A settled-but-failed credits query has `data === undefined`, and a `?? null` on the way
   * into the chip would launder that into "no credit_accounts row at all" — a positive claim
   * about the account, made from a 404, a 5xx or a dropped connection. An operator who reads
   * "never metered" off a blip comps a customer who already holds four credits.
   */
  it("says the balance could not be read when the credits request fails, and never 'never metered'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 503,
          headers: { get: () => null },
          json: () =>
            Promise.resolve({
              error: { code: "INTERNAL", message: "the database blinked", correlationId: "c0ffee" },
            }),
        } as unknown as Response),
      ),
    );
    renderDetail(detailFixture(), (client) => {
      client.removeQueries({ queryKey: queryKeys.users.credits(CUSTOMER_ID, CREDITS_QUERY) });
    });

    const unreadable = await screen.findByTestId("credit-balance-unreadable");
    expect(unreadable).toBeInTheDocument();
    expect(screen.queryByTestId("credit-balance-chip")).not.toBeInTheDocument();
    expect(screen.getByLabelText("order facts")).not.toHaveTextContent("never metered");
  });

  it("renders the order count as absent rather than zero when the users row 404s", () => {
    renderDetail(detailFixture(), (client) => {
      // `exact`, because the credits key nests UNDER the detail key by design.
      client.removeQueries({ queryKey: queryKeys.users.detail(CUSTOMER_ID), exact: true });
    });

    expect(screen.getByLabelText("order facts")).not.toHaveTextContent("orders placed7");
  });

  /* `credit.grant.write` is the permission the ROUTER names, and §11.4 hides rather than
     greying out. */
  it("offers Grant Credits to an operator and hides it from a support role", () => {
    const asOwner = renderDetail(detailFixture(), () => undefined, { role: "owner" });
    expect(screen.getByTestId("grant-credits-button")).toBeInTheDocument();
    asOwner.unmount();

    renderDetail(detailFixture(), () => undefined, { role: "support" });
    expect(screen.queryByTestId("grant-credits-button")).not.toBeInTheDocument();
  });

  it("opens the grant dialog on this order's customer", () => {
    renderDetail();

    fireEvent.click(screen.getByTestId("grant-credits-button"));

    const dialog = screen.getByTestId("grant-credits-dialog");
    expect(dialog).toBeInTheDocument();
    // OUR words for the subject — the masked id, never the recipient's name.
    expect(dialog.textContent).toContain("\u2022\u2022\u2022\u2022\u2022789");
    expect(dialog.textContent).not.toContain("O\u02bbktam");
  });
});

/**
 * The reveal affordance, Phase 2.
 *
 * §12.3 masks the recipient name and hides the note at every role, including OWNER, and
 * `POST /api/reveal` is the one path out of that. What is asserted here is the WIRING —
 * that both record shapes are offered as two separate controls, that they carry this order's
 * id as the subject, and that a VIEWER sees neither. The dialog's own behaviour is pinned in
 * `components/domain/RevealDialog.test.tsx`.
 */
describe("OrderDetailScreen — the reveal", () => {
  beforeEach(() => {
    resetPrefs();
  });

  function renderAs(role: Parameters<typeof meFixture>[0]) {
    const client = makeTestQueryClient();
    client.setQueryData(queryKeys.orders.detail(ORDER_ID), detailFixture());
    client.setQueryData(queryKeys.orders.timeline(ORDER_ID), timelineFixture());
    return renderWithProviders(
      <Routes>
        <Route path="/orders/:orderId" element={<OrderDetailScreen />} />
      </Routes>,
      // The ceilings come from `/api/config`, which the top bar has already cached in a live
      // session. Seeded here so opening the dialog is not a network call.
      { client, route: `/orders/${ORDER_ID}`, me: meFixture(role), config: configFixture() },
    );
  }

  it("offers the brief and the attempt free text SEPARATELY — the shapes cannot be mixed", () => {
    renderAs("support");
    expect(screen.getByRole("button", { name: /Reveal the brief/u })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Reveal attempt free text/u }),
    ).toBeInTheDocument();
  });

  it("opens on this order, and prices the brief at one record before anything is sent", () => {
    renderAs("support");
    fireEvent.click(screen.getByRole("button", { name: /Reveal the brief/u }));

    expect(screen.getByTestId("reveal-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-cost").textContent).toContain("charged 1 record");
    // The dialog's subject is the order, and its label is OUR reference — never the name it
    // exists to unmask.
    expect(screen.getByTestId("reveal-dialog").textContent).toContain(ORDER_ID.slice(0, 8));
    expect(screen.getByTestId("reveal-dialog").textContent).not.toContain("Oʻktam");
  });

  it("is invisible to a VIEWER — §11.4 hides, it does not grey out", () => {
    renderAs("viewer");
    expect(screen.queryByTestId("reveal-button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reveal/u })).not.toBeInTheDocument();
  });
});
