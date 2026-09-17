/**
 * Wire-shaped fixtures for the rail section's tests.
 *
 * Every one is a full, valid response — never a partial cast — because the shapes here are
 * transcribed from the server and a fixture that omitted a key would be a test passing against
 * a body the API never sends. The overrides argument is how a test says what it is actually
 * about; everything it does not name stays at the deployment's real default, which is empty.
 *
 * The defaults are deliberately **this deployment, today**: nothing opened, nothing settled,
 * Payme never heard from, checkouts open, no cashbox recorded. A test that wants a working rail
 * has to say so, which keeps the empty case — the one that ships first and stays longest — the
 * one every screen test starts from.
 */

import type {
  Attention,
  CheckoutSeen,
  FaultClusterList,
  InboundCall,
  IntentDossier,
  IntentListItem,
  IntentPage,
  Lifeline,
  RailFunnel,
  RailStatus,
  Receipt,
  Settlement,
} from "@/api/billing";

/** A UUID that is obviously a fixture and is still a legal `payment_intents.id`. */
export const FIXTURE_INTENT_ID = "11111111-1111-4111-8111-111111111111";

/** 24 lowercase hex, exactly as `secrets.token_hex(12)` mints it. */
export const FIXTURE_PUBLIC_REF = "a1b2c3d4e5f60718293a4b5c";

export function makeRailStatus(overrides: Partial<RailStatus> = {}): RailStatus {
  return {
    checkoutSeen: null,
    isPaused: false,
    // The real key, spelled once. Two spellings would be two answers to "is the rail paused".
    pauseKey: "bayram:payme:paused",
    lastInboundCall: null,
    hasOpenedAnyIntent: false,
    hasRecordedTransaction: false,
    hasRecordedInboundCall: false,
    hasSettledAnyIntent: false,
    asOf: "2026-09-10T09:00:00Z",
    ...overrides,
  };
}

export function makeCheckoutSeen(overrides: Partial<CheckoutSeen> = {}): CheckoutSeen {
  return {
    provider: "payme",
    // What the gateway actually boots with until merchant credentials arrive.
    merchantId: "placeholder",
    isSandbox: true,
    seenAt: "2026-09-10T08:00:00Z",
    ...overrides,
  };
}

export function makeInboundCall(overrides: Partial<InboundCall> = {}): InboundCall {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    at: "2026-09-10T08:59:00Z",
    method: "CheckPerformTransaction",
    publicRef: FIXTURE_PUBLIC_REF,
    paymeTransactionId: null,
    replyCode: 0,
    peerIp: "185.8.212.10",
    durationMs: 42,
    ...overrides,
  };
}

/**
 * All zeros with `hasRecordedSettlement: false` — which the server calls `never_settled` and
 * NOT `balanced`. That distinction is the single most important thing this card renders.
 */
export function makeSettlement(overrides: Partial<Settlement> = {}): Settlement {
  return {
    window: { since: "2026-08-11T09:00:00Z", until: "2026-09-10T09:00:00Z" },
    transactionsPerformed: 0,
    operatorSettlements: 0,
    receiptsWritten: 0,
    grantsWritten: 0,
    hasRecordedSettlement: false,
    verdict: "never_settled",
    ...overrides,
  };
}

export function makeAttention(overrides: Partial<Attention> = {}): Attention {
  return {
    asOf: "2026-09-10T09:00:00Z",
    staleAfterHours: 12,
    awaitingHeldPastTimeout: 0,
    paidNeverAnnounced: 0,
    paidWithNoReceipt: 0,
    ...overrides,
  };
}

/** Nothing opened, nothing on the rail, nothing heard — the deployment as it stands. */
export function makeRailFunnel(overrides: Partial<RailFunnel> = {}): RailFunnel {
  return {
    window: { since: "2026-08-11T09:00:00Z", until: "2026-09-10T09:00:00Z" },
    // Sparse by construction: a state with no rows is ABSENT, never a zero entry.
    intents: [],
    intentsExpiredAfterTransaction: 0,
    intentsExpiredWithNoTransaction: 0,
    transactions: [],
    rpcCalls: 0,
    rpcFaults: 0,
    hasOpenedAnyIntent: false,
    hasRecordedTransaction: false,
    hasRecordedInboundCall: false,
    ...overrides,
  };
}

export function makeFaultClusters(overrides: Partial<FaultClusterList> = {}): FaultClusterList {
  return {
    window: { since: "2026-08-11T09:00:00Z", until: "2026-09-10T09:00:00Z" },
    clusters: [],
    hasRecordedInboundCall: false,
    ...overrides,
  };
}

export function makeIntent(overrides: Partial<IntentListItem> = {}): IntentListItem {
  return {
    intentId: FIXTURE_INTENT_ID,
    publicRef: FIXTURE_PUBLIC_REF,
    createdAt: "2026-09-10T08:00:00Z",
    validUntil: "2026-09-10T09:00:00Z",
    state: "pending",
    product: "single",
    planSongs: null,
    planDays: null,
    // 7 000 soʻm in tiyin — `single_song_price_minor`, so the money formatter is exercised
    // against a real price rather than a round number that would hide an exponent bug.
    amountMinor: 700_000,
    currency: "UZS",
    provider: "payme",
    merchantId: "placeholder",
    isSandbox: false,
    telegramUserIdMasked: "•••4321",
    isBuyerErased: false,
    transactionCount: 0,
    latestTransactionState: null,
    latestPerformTime: null,
    hasReceipt: false,
    hasGrant: false,
    settledAt: null,
    settleSource: null,
    settleNote: null,
    notifiedAt: null,
    ...overrides,
  };
}

export function makeIntentPage(
  items: readonly IntentListItem[] = [],
  overrides: Partial<IntentPage> = {},
): IntentPage {
  return {
    items: [...items],
    meta: { nextCursor: null, total: null, isTotalExact: null },
    capabilities: {
      hasOpenedAnyIntent: items.length > 0,
      hasRecordedTransaction: false,
      hasSettledAnyIntent: false,
    },
    ...overrides,
  };
}

export function makeReceipt(overrides: Partial<Receipt> = {}): Receipt {
  return {
    source: "topup_purchases",
    amountMinor: 700_000,
    currency: "UZS",
    provider: "payme",
    reference: "66a1f0c2e4b7d3a19f5c8b20",
    creditsGranted: 1,
    songsIncluded: null,
    songsUsed: null,
    planEndsAt: null,
    createdAt: "2026-09-10T08:05:00Z",
    ...overrides,
  };
}

/** The six steps in the server's order. Callers replace individual steps by key. */
export function makeLifeline(steps: Partial<Lifeline["steps"][number]>[] = []): Lifeline {
  const base: Lifeline["steps"] = [
    { key: "opened", status: "done", at: "2026-09-10T08:00:00Z", noteCode: null },
    { key: "rail_transaction", status: "pending", at: null, noteCode: "never_opened" },
    { key: "performed", status: "pending", at: null, noteCode: null },
    { key: "receipt", status: "pending", at: null, noteCode: null },
    { key: "credit_granted", status: "pending", at: null, noteCode: null },
    { key: "customer_told", status: "pending", at: null, noteCode: null },
  ];
  return {
    steps: base.map((step) => {
      const patch = steps.find((candidate) => candidate.key === step.key);
      return patch === undefined ? step : { ...step, ...patch };
    }),
  };
}

export function makeDossier(overrides: Partial<IntentDossier> = {}): IntentDossier {
  return {
    intent: makeIntent(),
    transactions: [],
    receipt: null,
    ledger: [],
    calls: [],
    lifeline: makeLifeline(),
    chainStop: { kind: "single_song", songsUsed: null, songsIncluded: null, planEndsAt: null },
    notify: { canNotify: false, refusalCode: "not_paid", notifiedAt: null },
    // Built by the server so the flag spelling lives in one place; the reference appears twice
    // and nothing else does, which is what makes the string safe to paste into a ticket.
    settleCommand: `python -m bayram.payme.cli settle --ref ${FIXTURE_PUBLIC_REF} --note '${FIXTURE_PUBLIC_REF}'`,
    ...overrides,
  };
}
