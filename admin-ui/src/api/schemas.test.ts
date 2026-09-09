/**
 * The wire contract for the credits vertical and the order financials, asserted against
 * fixtures shaped like the real routers' responses rather than described.
 *
 * These exist because `schemas.ts:19` deliberately does NOT use `.strict()`: a field the
 * server sends and this bundle does not declare is dropped SILENTLY, with no drift banner and
 * no type error, which is exactly how the backend shipped `creditBalance`, `creditCost` and
 * their neighbours months before any screen could read them. A round-trip test is the only
 * thing that notices, so every field added here gets one.
 *
 * The mirror image is asserted too: every nullable field is `.nullable()` and NOT `.nullish()`,
 * so a MISSING key is drift and must fail. That is what keeps "the server has not deployed
 * this yet" from rendering as "this customer has no credits".
 */

import { describe, expect, it } from "vitest";

import {
  auditEntryViewSchema,
  creditGrantResultViewSchema,
  creditLedgerPageSchema,
  orderStateCountsSchema,
  orderViewSchema,
  userDetailViewSchema,
  userViewSchema,
} from "./schemas";

const UUID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";
const OTHER_UUID = "7a1b2c3d-4e5f-4061-8273-9a0b1c2d3e4f";

/** One `/api/users` row, exactly as `to_user_view` projects it. */
function userRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: UUID,
    telegramUserId: 770000123,
    telegramUserIdMasked: "•••••123",
    uiLanguage: "uz_latn",
    isBlocked: false,
    isProfilePresent: true,
    telegramUsernameMasked: "@G•••",
    firstNameMasked: "D•••",
    lastNameMasked: null,
    phoneMasked: "•••••42",
    phoneSharedAt: "2026-08-01T09:00:00Z",
    hasAvatar: true,
    avatarUrl: "/api/users/770000123/avatar",
    avatarFetchedAt: "2026-08-01T09:00:01Z",
    accountCreatedAt: "2026-07-30T12:00:00Z",
    firstOrderAt: "2026-08-01T10:00:00Z",
    lastOrderAt: "2026-09-01T10:00:00Z",
    orderCount: 4,
    paidOrderCount: 3,
    creditBalance: 2,
    lifetimeCreditsGranted: 9,
    allowancePeriod: 41,
    ...overrides,
  };
}

/** One `/api/orders` row, financials included. */
function orderRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: UUID,
    telegramUserId: 770000123,
    telegramUserIdMasked: "•••••123",
    state: "delivered",
    isPaid: true,
    correlationId: "b".repeat(32),
    createdAt: "2026-09-01T10:00:00Z",
    updatedAt: "2026-09-01T10:09:00Z",
    deliveredAt: "2026-09-01T10:09:00Z",
    failedReason: null,
    isFailedReasonRetryable: null,
    isBriefPresent: true,
    recipientName: "•••",
    isIdentityPurged: false,
    identityPurgedAt: null,
    notePurgedAt: null,
    occasion: "birthday",
    genre: "uzbek_pop",
    outputLanguage: "uz_latn",
    assetCount: 3,
    hasAssets: true,
    creditCost: 1,
    ledgerStatus: "settled",
    paymentRail: "credits",
    retryCount: 0,
    ...overrides,
  };
}

describe("auditEntryViewSchema", () => {
  /**
   * The drift this closes. `AuditAction.CREDIT_GRANT` has existed server-side since the
   * entitlement ledger shipped; `AUDIT_ACTION_VALUES` did not carry it, and
   * `auditEntryViewSchema.action` is a `z.enum`, so the FIRST real grant row would have
   * turned the whole `/audit` screen into a SCHEMA_DRIFT banner rather than one odd row.
   */
  it("parses a credit.grant row rather than reporting the whole page as drift", () => {
    const parsed = auditEntryViewSchema.safeParse({
      seq: 812,
      id: UUID,
      at: "2026-09-05T08:30:00Z",
      actorId: OTHER_UUID,
      actorUsername: "dilnoza",
      actorRole: "admin",
      action: "credit.grant",
      subjectType: "user",
      subjectId: "770000123",
      fieldNames: null,
      recordCount: null,
      reasonCode: "customer_request",
      reasonRef: "HD-4412",
      hasReasonText: true,
      reasonText: null,
      outcome: "ok",
      errorCode: null,
      correlationId: "c".repeat(32),
      ip: "203.0.113.7",
      configVersion: null,
      chainHmac: "d".repeat(64),
    });

    expect(parsed.success).toBe(true);
    expect(parsed.success && parsed.data.action).toBe("credit.grant");
    // The subject is the TELEGRAM ID as a decimal string, not `users.id` — the same spelling
    // the step-up scope was composed from.
    expect(parsed.success && parsed.data.subjectId).toBe("770000123");
  });
});

describe("userViewSchema — the three credit fields", () => {
  it("keeps balance, lifetime granted and allowance period instead of dropping them", () => {
    const parsed = userViewSchema.parse(userRow());

    expect(parsed.creditBalance).toBe(2);
    expect(parsed.lifetimeCreditsGranted).toBe(9);
    expect(parsed.allowancePeriod).toBe(41);
  });

  /**
   * `null` is a THIRD state — no `credit_accounts` row — and the column is `NOT NULL` in the
   * schema, so it can mean nothing else. It must survive parsing as `null` and never arrive
   * as `0`, which says the opposite: that this account spent everything it had.
   */
  it("carries a null balance through as null, distinct from a balance of 0", () => {
    const never = userViewSchema.parse(
      userRow({ creditBalance: null, lifetimeCreditsGranted: null, allowancePeriod: null }),
    );
    const spent = userViewSchema.parse(
      userRow({ creditBalance: 0, lifetimeCreditsGranted: 4, allowancePeriod: 41 }),
    );

    expect(never.creditBalance).toBeNull();
    expect(spent.creditBalance).toBe(0);
    expect(never.creditBalance).not.toBe(spent.creditBalance);
  });

  it("reports a server that has not shipped the credit fields as drift, not as no credits", () => {
    const withoutBalance = userRow();
    delete withoutBalance.creditBalance;

    expect(userViewSchema.safeParse(withoutBalance).success).toBe(false);
  });
});

describe("userDetailViewSchema", () => {
  it("carries creditsProjected and inFlightRenderCount beside the stored balance", () => {
    const parsed = userDetailViewSchema.parse({
      user: userRow({ creditBalance: null }),
      ordersByState: [{ state: "delivered", count: 3 }],
      deliveredOrderCount: 3,
      failedOrderCount: 1,
      creditsProjected: 3,
      inFlightRenderCount: 1,
    });

    // The pair the whole feature exists to compare: the ledger can prove nothing (no account
    // row) while the bot would still tell this customer they have three renders due.
    expect(parsed.user.creditBalance).toBeNull();
    expect(parsed.creditsProjected).toBe(3);
    expect(parsed.inFlightRenderCount).toBe(1);
  });
});

describe("orderViewSchema — the four financial fields", () => {
  it("keeps creditCost, ledgerStatus, paymentRail and retryCount", () => {
    const parsed = orderViewSchema.parse(orderRow());

    expect(parsed.creditCost).toBe(1);
    expect(parsed.ledgerStatus).toBe("settled");
    expect(parsed.paymentRail).toBe("credits");
    expect(parsed.retryCount).toBe(0);
  });

  it("accepts every member of both ledger vocabularies, `unmetered` and `unenforced` included", () => {
    for (const ledgerStatus of ["unmetered", "pending", "settled", "refunded"]) {
      expect(orderViewSchema.safeParse(orderRow({ ledgerStatus })).success).toBe(true);
    }
    for (const paymentRail of ["none", "credits", "unenforced"]) {
      expect(orderViewSchema.safeParse(orderRow({ paymentRail })).success).toBe(true);
    }
  });

  /** §5.1's `telegram_stars` and `admin_grant` are not derivable and must never parse. */
  it("refuses a payment rail the server cannot prove", () => {
    expect(orderViewSchema.safeParse(orderRow({ paymentRail: "telegram_stars" })).success).toBe(
      false,
    );
    expect(orderViewSchema.safeParse(orderRow({ paymentRail: "admin_grant" })).success).toBe(false);
  });
});

describe("orderStateCountsSchema", () => {
  it("round-trips the aggregate, zero segments and all", () => {
    const parsed = orderStateCountsSchema.parse({
      counts: [
        { state: "draft", count: 0 },
        { state: "brief_ready", count: 0 },
        { state: "lyrics_ready", count: 2 },
        { state: "authorized", count: 0 },
        { state: "generating", count: 1 },
        { state: "delivered", count: 41 },
        { state: "failed", count: 3 },
        { state: "cancelled", count: 0 },
      ],
      total: 47,
    });

    expect(parsed.counts).toHaveLength(8);
    // The exact sum, not the list's `TOTAL_COUNT_CAP`-bounded `meta.total`.
    expect(parsed.total).toBe(47);
    expect(parsed.counts.reduce((sum, segment) => sum + segment.count, 0)).toBe(parsed.total);
  });
});

describe("creditLedgerPageSchema", () => {
  it("round-trips a metered account and its four movement kinds", () => {
    const parsed = creditLedgerPageSchema.parse({
      account: {
        telegramUserId: 770000123,
        telegramUserIdMasked: "•••••123",
        balance: 2,
        lifetimeGranted: 9,
        allowancePeriod: 41,
      },
      items: [
        {
          id: UUID,
          kind: "grant",
          reason: "admin_grant",
          delta: 3,
          orderId: null,
          generation: 0,
          idempotencyKey: `grant:admin:770000123:${OTHER_UUID}`,
          actor: "admin:dilnoza",
          createdAt: "2026-09-05T08:30:00Z",
        },
        {
          id: OTHER_UUID,
          kind: "debit",
          reason: "order_render",
          delta: -1,
          orderId: UUID,
          generation: 1,
          idempotencyKey: "render:3f2b1c4d:1",
          actor: null,
          createdAt: "2026-09-05T08:31:00Z",
        },
        {
          id: UUID,
          kind: "consume",
          reason: "order_delivered",
          delta: 0,
          orderId: UUID,
          generation: 1,
          idempotencyKey: "settle:3f2b1c4d:1",
          actor: null,
          createdAt: "2026-09-05T08:39:00Z",
        },
        {
          id: OTHER_UUID,
          kind: "refund",
          reason: "order_failed",
          delta: 1,
          orderId: UUID,
          generation: 2,
          idempotencyKey: "refund:3f2b1c4d:2",
          actor: null,
          createdAt: "2026-09-05T09:00:00Z",
        },
      ],
      meta: { nextCursor: null, total: null, isTotalExact: null },
    });

    expect(parsed.account?.balance).toBe(2);
    // `actor` is published verbatim, `admin:{username}` included: masking it would make the
    // column unable to answer the only question it is on the screen for.
    expect(parsed.items[0]?.actor).toBe("admin:dilnoza");
    // A consume moves nothing and is still a row. Signed-delta colouring needs three cases.
    expect(parsed.items.map((entry) => entry.delta)).toEqual([3, -1, 0, 1]);
  });

  /**
   * The 404-vs-empty distinction the router's docstring makes load-bearing: a `users` row with
   * no `credit_accounts` row answers 200 with `account: null`, which means "never metered" and
   * not "spent everything".
   */
  it("round-trips the null-account case rather than requiring a zeroed object", () => {
    const parsed = creditLedgerPageSchema.parse({
      account: null,
      items: [],
      meta: { nextCursor: null, total: 0, isTotalExact: true },
    });

    expect(parsed.account).toBeNull();
    expect(parsed.items).toEqual([]);
  });

  /** `/forget` keeps the ledger rows and nulls their Telegram id, so they belong to nobody. */
  it("allows movements beside a null account, which is what an erased customer looks like", () => {
    const parsed = creditLedgerPageSchema.parse({
      account: null,
      items: [
        {
          id: UUID,
          kind: "grant",
          reason: "signup_allowance",
          delta: 3,
          orderId: null,
          generation: 0,
          idempotencyKey: "signup:770000123",
          actor: null,
          createdAt: "2026-07-30T12:00:00Z",
        },
      ],
      meta: { nextCursor: null, total: null, isTotalExact: null },
    });

    expect(parsed.account).toBeNull();
    expect(parsed.items).toHaveLength(1);
  });

  it("rejects a movement kind or reason this build does not know", () => {
    const withBadKind = {
      account: null,
      items: [
        {
          id: UUID,
          kind: "topup",
          reason: "admin_grant",
          delta: 1,
          orderId: null,
          generation: 0,
          idempotencyKey: "x",
          actor: null,
          createdAt: "2026-09-05T08:30:00Z",
        },
      ],
      meta: { nextCursor: null, total: null, isTotalExact: null },
    };

    expect(creditLedgerPageSchema.safeParse(withBadKind).success).toBe(false);
  });
});

describe("creditGrantResultViewSchema", () => {
  it("round-trips a fresh grant, with the account read back after the write", () => {
    const parsed = creditGrantResultViewSchema.parse({
      telegramUserId: 770000123,
      telegramUserIdMasked: "•••••123",
      grantedCredits: 3,
      isReplay: false,
      idempotencyKey: `grant:admin:770000123:${OTHER_UUID}`,
      account: {
        telegramUserId: 770000123,
        telegramUserIdMasked: "•••••123",
        balance: 5,
        lifetimeGranted: 12,
        allowancePeriod: 41,
      },
    });

    expect(parsed.isReplay).toBe(false);
    expect(parsed.account.balance).toBe(5);
    // The key carries the Telegram id: a bare `grant:admin:{requestId}` made one reused
    // request id credit the first account and silently issue nothing to the second.
    expect(parsed.idempotencyKey).toContain("770000123");
  });

  it("round-trips a replay, where nothing moved and the balance is unchanged", () => {
    const parsed = creditGrantResultViewSchema.parse({
      telegramUserId: 770000123,
      telegramUserIdMasked: "•••••123",
      grantedCredits: 3,
      isReplay: true,
      idempotencyKey: `grant:admin:770000123:${OTHER_UUID}`,
      account: {
        telegramUserId: 770000123,
        telegramUserIdMasked: "•••••123",
        balance: 5,
        lifetimeGranted: 12,
        allowancePeriod: null,
      },
    });

    // The field that lets a retried, timed-out request say "it worked the first time" rather
    // than guessing from the balance.
    expect(parsed.isReplay).toBe(true);
    expect(parsed.account.allowancePeriod).toBeNull();
  });
});
