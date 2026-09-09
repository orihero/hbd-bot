/**
 * §11.2's dominant signal for `/users/:telegramUserId`: "Full-width banner: status of their
 * most recent order."
 *
 * The banner reads its own `limit=1` query, so the test also pins the reason: paging the
 * list below must not change what the banner says.
 *
 * ## The screen now carries TWO reveals, and they are different subjects
 *
 * The order-brief reveal lives on the banner; the contact reveal lives in the page header.
 * `RevealButton` stamps `data-testid="reveal-button"` on every instance, so every assertion
 * about either of them is scoped with `within(...)` or matched by its accessible name. An
 * unscoped `getByTestId("reveal-button")` would now throw on a screen where it used to pass,
 * and — worse — a `queryByTestId(...)` used to prove ABSENCE would keep working while
 * silently testing only whichever button happened to be first in the DOM.
 *
 * The contact reveal is keyed on `users.id`, the UUID, and NEVER on the Telegram integer:
 * `revealRequestSchema.subjectId` is a uuid and the server compares the composed
 * `reveal:<subjectId>` step-up scope WHOLE, so an integer there is a permanent, silent 403
 * that only a test against the real route would ever catch. That is asserted on the request
 * body rather than on anything rendered, because nothing rendered would show it.
 *
 * ## The profile panel says what it cannot know
 *
 * `/forget` DELETEs the `user_profiles` row rather than nulling it, and the table carries no
 * retention clock at all, so an erased profile and a profile that never existed are ONE
 * absence with no stamp between them. The panel therefore names a standing and admits the
 * ambiguity in its `title`; it draws no `🔒 purged` lock, which would invent a date.
 */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import type {
  AdminRole,
  ApiResult,
  CreditGrantRequest,
  CreditGrantResultView,
  CreditLedgerPage,
  OrderView,
  OrdersPage,
  PageQuery,
  RevealRequest,
  RevealResponse,
  UserBlockResultView,
  UserDetailView,
  UserView,
  WizardStateView,
} from "@/api";
import type * as ApiModule from "@/api";
import { pathUserAvatar } from "@/api";
import {
  configFixture,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";

const {
  getUserCreditsMock,
  getUserMock,
  getUserOrdersMock,
  getWizardStateMock,
  postCreditGrantMock,
  postRevealMock,
  postUserBlockMock,
} = vi.hoisted(() => ({
  getUserCreditsMock: vi.fn(),
  getUserMock: vi.fn(),
  getUserOrdersMock: vi.fn(),
  getWizardStateMock: vi.fn(),
  postCreditGrantMock: vi.fn(),
  postRevealMock: vi.fn(),
  postUserBlockMock: vi.fn(),
}));

/*
 * The BARREL is mocked, never `fetch`. `useReveal` imports `postReveal` from `@/api` too, so
 * one mock covers the dialog's mutation as well as this screen's three queries — and the
 * request body this file asserts on is the one the dialog actually composed, not a JSON
 * string re-parsed out of a stubbed `Response`. The same holds for `<GrantCreditsDialog>`'s
 * `postCreditGrant`, which is why the grant tests can assert on the body it minted rather
 * than on what they handed it.
 */
vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getUser: getUserMock,
  getUserCredits: getUserCreditsMock,
  getUserOrders: getUserOrdersMock,
  getWizardState: getWizardStateMock,
  postCreditGrant: postCreditGrantMock,
  postReveal: postRevealMock,
  postUserBlock: postUserBlockMock,
}));

const { UserDetailScreen } = await import("./UserDetailScreen");

const TELEGRAM_ID = 770000123;

/** `users.id` — the PK the reveal is keyed on. Never `TELEGRAM_ID`, at any point. */
const USER_ID = "11111111-1111-4111-8111-111111111111";

/**
 * The E.164 number `"•••••42"` is the mask of.
 *
 * It is here ONLY as the string no assertion may find. It is never put in a fixture, because
 * no field on this wire could carry it: the plaintext exists at no role, OWNER included, and
 * `POST /api/reveal` is its one path.
 */
const PLAINTEXT_PHONE = "+998901234542";

/**
 * The shape a leaking country prefix would have: `+` followed by a long run of digits.
 *
 * It was `/\+\d/u` until the credit ledger landed on this screen. The ledger draws its signed
 * deltas with the sign in the TEXT as well as in the colour — `+3`, `−1`, `±0` — which is the
 * §11.3 rule that keeps direction readable in greyscale, so a bare `+`-then-digit no longer
 * distinguishes a phone number from arithmetic. The run length is what does: E.164 numbers are
 * seven to fifteen digits and a grant is capped at 100, so five digits is above everything
 * this screen can legitimately print after a `+` and far below anything a real number could
 * shrink to. The guard still fails on `+998901234542`, which is the only thing it is for.
 */
const CLEAR_DIALLING_CODE = /\+\d{5,}/u;

/**
 * An onboarded customer with a photo, because that is the row with the most to get wrong.
 *
 * `avatarUrl` comes from `pathUserAvatar` rather than from a literal: the server sends its own
 * spelling of that path and the client has a builder for it, so a hard-coded fixture could
 * keep passing while the two spellings drifted apart. Building it from the builder makes this
 * fixture the drift check.
 */
function makeUser(overrides: Partial<UserView> = {}): UserView {
  return {
    id: USER_ID,
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    uiLanguage: "uz_latn",
    isBlocked: false,
    accountCreatedAt: "2026-08-20T10:00:00Z",
    firstOrderAt: "2026-08-20T10:00:00Z",
    lastOrderAt: "2026-09-01T09:00:00Z",
    orderCount: 2,
    paidOrderCount: 1,
    isProfilePresent: true,
    telegramUsernameMasked: "@G•••",
    firstNameMasked: "G•••",
    lastNameMasked: "D•••",
    phoneMasked: "•••••42",
    phoneSharedAt: "2026-08-20T10:05:00Z",
    hasAvatar: true,
    avatarUrl: pathUserAvatar(TELEGRAM_ID),
    avatarFetchedAt: "2026-08-20T10:05:02Z",
    /*
     * The three credit fields, all `.nullable()` and therefore all REQUIRED properties.
     * `creditBalance: null` is not a balance of 0 — it says there is no `credit_accounts`
     * row — so the default fixture gives this customer a real metered account and the
     * never-metered population gets its own fixture below.
     */
    creditBalance: 2,
    lifetimeCreditsGranted: 5,
    allowancePeriod: 7,
    ...overrides,
  };
}

/** The other credit population: a `users` row with no `credit_accounts` row behind it. */
function makeNeverMeteredUser(overrides: Partial<UserView> = {}): UserView {
  return makeUser({
    creditBalance: null,
    lifetimeCreditsGranted: null,
    allowancePeriod: null,
    ...overrides,
  });
}

/** The other half of the population: an account with no `user_profiles` row at all. */
function makeProfilelessUser(overrides: Partial<UserView> = {}): UserView {
  return makeUser({
    isProfilePresent: false,
    telegramUsernameMasked: null,
    firstNameMasked: null,
    lastNameMasked: null,
    phoneMasked: null,
    phoneSharedAt: null,
    hasAvatar: false,
    avatarUrl: null,
    avatarFetchedAt: null,
    ...overrides,
  });
}

function makeOrder(overrides: Partial<OrderView> = {}): OrderView {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    state: "generating",
    isPaid: true,
    correlationId: "0123456789abcdef0123456789abcdef",
    createdAt: "2026-09-01T09:00:00Z",
    updatedAt: "2026-09-01T09:05:00Z",
    deliveredAt: null,
    failedReason: null,
    isFailedReasonRetryable: null,
    isBriefPresent: true,
    recipientName: "G•••",
    isIdentityPurged: false,
    identityPurgedAt: null,
    notePurgedAt: null,
    occasion: "birthday",
    genre: "pop",
    outputLanguage: "uz_latn",
    assetCount: 0,
    hasAssets: false,
    creditCost: 1,
    ledgerStatus: "pending",
    paymentRail: "credits",
    /* ATTEMPTS recorded, not "retries beyond the first" — see `orderViewSchema`. */
    retryCount: 1,
    ...overrides,
  };
}

function ordersPage(items: readonly OrderView[]): OrdersPage {
  return { items: [...items], meta: { nextCursor: null, total: items.length, isTotalExact: true } };
}

function detail(user: UserView, overrides: Partial<UserDetailView> = {}): UserDetailView {
  return {
    user,
    ordersByState: [
      { state: "delivered", count: 1 },
      { state: "generating", count: 1 },
    ],
    deliveredOrderCount: 1,
    failedOrderCount: 0,
    /*
     * An `int` and never `null`: it is computed for every account, row or no row. The
     * default agrees with `makeUser`'s stored balance so that a disagreement in a test is
     * one the test asked for.
     */
    creditsProjected: 2,
    inFlightRenderCount: 0,
    ...overrides,
  };
}

/**
 * A metered account and one movement on its ledger.
 *
 * `account` is an OBJECT here. The null-account page is built by `neverMeteredLedger()`
 * below, and the two are kept apart deliberately: `account: null` is "no `credit_accounts`
 * row", not "balance 0", and a fixture that let one stand in for the other would make the
 * screen's whole reason for existing untestable.
 */
function ledgerPage(overrides: Partial<CreditLedgerPage> = {}): CreditLedgerPage {
  return {
    account: {
      telegramUserId: TELEGRAM_ID,
      telegramUserIdMasked: "•••••123",
      balance: 2,
      lifetimeGranted: 5,
      allowancePeriod: 7,
    },
    items: [
      {
        id: "55555555-5555-4555-8555-555555555555",
        kind: "grant",
        reason: "admin_grant",
        delta: 3,
        orderId: null,
        generation: 1,
        idempotencyKey: "grant:admin:770000123:abc",
        actor: "admin:operator",
        createdAt: "2026-09-01T08:00:00Z",
      },
    ],
    meta: { nextCursor: null, total: 1, isTotalExact: true },
    ...overrides,
  };
}

/** No `credit_accounts` row at all — and, as after a `/forget`, movements that outlived it. */
function neverMeteredLedger(items: CreditLedgerPage["items"] = []): CreditLedgerPage {
  return {
    account: null,
    items: [...items],
    meta: { nextCursor: null, total: items.length, isTotalExact: true },
  };
}

function grantResult(overrides: Partial<CreditGrantResultView> = {}): CreditGrantResultView {
  return {
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    grantedCredits: 3,
    isReplay: false,
    idempotencyKey: "grant:admin:770000123:abc",
    account: {
      telegramUserId: TELEGRAM_ID,
      telegramUserIdMasked: "•••••123",
      balance: 5,
      lifetimeGranted: 8,
      allowancePeriod: 7,
    },
    ...overrides,
  };
}

function blockResult(isBlocked: boolean): UserBlockResultView {
  return {
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    isBlocked,
    changedAt: "2026-09-02T11:00:00Z",
  };
}

function wizard(overrides: Partial<WizardStateView> = {}): WizardStateView {
  return {
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    isStatePresent: false,
    state: null,
    sessionId: null,
    choices: {},
    textFields: [
      { key: "note", isPresent: false, charCount: null },
      { key: "recipient", isPresent: false, charCount: null },
      { key: "lyrics", isPresent: false, charCount: null },
    ],
    lyricWrites: null,
    ...overrides,
  };
}

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data };
}

/**
 * A 200 from `POST /api/reveal`, carrying nothing this screen's assertions read.
 *
 * The plaintext columns come back EMPTY on purpose. Every test in this file is about what
 * happens BEFORE the plaintext exists — who may ask, what the request says, and what is still
 * masked while the dialog is open. `RevealDialog.test.tsx` owns the codepoint assertions on
 * the revealed values, and a second fixture carrying a real `+998…` here would put an E.164
 * string in the one file whose whole-body assertions exist to prove one never appears.
 */
function revealResponse(): RevealResponse {
  return {
    subjectType: "user",
    subjectId: USER_ID,
    revealedAt: "2026-09-02T10:30:00Z",
    reasonCode: "support_investigation",
    recordCount: 1,
    revealedFields: ["user_profiles.phone_e164"],
    records: [
      {
        recordId: "44444444-4444-4444-8444-444444444444",
        createdAt: "2026-08-20T10:05:00Z",
        fields: { "user_profiles.phone_e164": null },
        identityPurgedAt: null,
        textPurgedAt: null,
      },
    ],
    nextCursor: null,
    budget: {
      recordsCharged: 1,
      recordsRemaining: 143,
      conversationsCharged: 0,
      conversationsRemaining: null,
    },
  };
}

/** The body the dialog composed, read off the mock rather than out of a stubbed `Response`. */
function revealBodyOf(index: number): RevealRequest {
  const call = postRevealMock.mock.calls[index];
  if (call === undefined) throw new Error(`no reveal call ${String(index)}`);
  return call[0] as RevealRequest;
}

/** Render as SUPPORT with a seeded config, which is what the reveal dialog needs to price. */
function renderAsSupport(user: UserView = makeUser()) {
  getUserMock.mockResolvedValue(ok(detail(user)));
  return renderAsRole("support", user);
}

/**
 * Render at one role with a seeded config.
 *
 * The role is the whole subject of the RBAC tests below: `credit.grant.write` and
 * `user.block.write` are both `OPERATOR_UP` (admin, owner), so SUPPORT — who may reveal — is
 * exactly the role that proves the two write buttons are hidden rather than merely disabled.
 */
function renderAsRole(
  role: AdminRole,
  user: UserView = makeUser(),
  detailOverrides: Partial<UserDetailView> = {},
) {
  getUserMock.mockResolvedValue(ok(detail(user, detailOverrides)));
  return renderWithProviders(
    <Routes>
      <Route path="/users/:telegramUserId" element={<UserDetailScreen />} />
    </Routes>,
    { route: `/users/${String(TELEGRAM_ID)}`, me: meFixture(role), config: configFixture() },
  );
}

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/users/:telegramUserId" element={<UserDetailScreen />} />
    </Routes>,
    { route },
  );
}

beforeEach(() => {
  resetPrefs();
  getUserCreditsMock.mockReset();
  getUserMock.mockReset();
  getUserOrdersMock.mockReset();
  getWizardStateMock.mockReset();
  postCreditGrantMock.mockReset();
  postRevealMock.mockReset();
  postUserBlockMock.mockReset();
  getUserMock.mockResolvedValue(ok(detail(makeUser())));
  getUserCreditsMock.mockResolvedValue(ok(ledgerPage()));
  getWizardStateMock.mockResolvedValue(ok(wizard()));
  postCreditGrantMock.mockResolvedValue(ok(grantResult()));
  postRevealMock.mockResolvedValue(ok(revealResponse()));
  postUserBlockMock.mockResolvedValue(ok(blockResult(true)));
});

describe("UserDetailScreen", () => {
  it("banners the most recent order's status", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAt(`/users/${String(TELEGRAM_ID)}`);

    const banner = await screen.findByTestId("latest-order-banner");
    expect(banner).toHaveAttribute("data-state", "generating");
  });

  /*
   * The reskin re-laid the banner out as a hero card — a header row and a fact grid where
   * there used to be one wrapping line. That is a presentation change and it must not have
   * been a content change: the four facts support reads aloud on the phone are still on it,
   * still labelled, and still on the banner rather than only in the table below.
   */
  it("keeps every fact on the banner — the reskin moved them, it did not drop them", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder({ deliveredAt: null })])));
    renderAt(`/users/${String(TELEGRAM_ID)}`);

    const banner = await screen.findByTestId("latest-order-banner");
    for (const label of ["recipient", "created", "delivered", "paid"]) {
      expect(within(banner).getByText(label)).toBeInTheDocument();
    }
  });

  it("takes the banner from its own limit=1 query, not from the paged list", async () => {
    getUserOrdersMock.mockImplementation((_id: number, query: PageQuery = {}) =>
      Promise.resolve(
        ok(
          ordersPage(
            query.limit === 1
              ? [makeOrder({ state: "failed", failedReason: "SUNO_TIMEOUT" })]
              : [makeOrder({ id: "33333333-3333-4333-8333-333333333333", state: "delivered" })],
          ),
        ),
      ),
    );
    renderAt(`/users/${String(TELEGRAM_ID)}?cursor=page-two`);

    const banner = await screen.findByTestId("latest-order-banner");
    expect(banner).toHaveAttribute("data-state", "failed");
    expect(banner.textContent).toContain("SUNO_TIMEOUT");
  });

  it("renders the masked telegram id and never the integer", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAt(`/users/${String(TELEGRAM_ID)}`);

    await screen.findByTestId("latest-order-banner");
    expect(screen.getAllByText("•••••123").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain(String(TELEGRAM_ID));
  });

  it("shows a purged identity as a purge stamp, not a blank and not an error", async () => {
    getUserOrdersMock.mockResolvedValue(
      ok(
        ordersPage([
          makeOrder({
            recipientName: null,
            isIdentityPurged: true,
            identityPurgedAt: "2026-05-14T00:00:00Z",
          }),
        ]),
      ),
    );
    renderAt(`/users/${String(TELEGRAM_ID)}`);

    await screen.findByTestId("latest-order-banner");
    expect(screen.getAllByText(/🔒 purged 2026-05-14/)[0]).toBeInTheDocument();
  });

  it("renders the wizard panel without any draft content", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    getWizardStateMock.mockResolvedValue(
      ok(
        wizard({
          isStatePresent: true,
          state: "Wizard:recipient",
          choices: { ui_language: "uz_latn" },
          textFields: [
            { key: "note", isPresent: true, charCount: 41 },
            { key: "recipient", isPresent: true, charCount: 6 },
            { key: "lyrics", isPresent: false, charCount: null },
          ],
          lyricWrites: 0,
        }),
      ),
    );
    renderAt(`/users/${String(TELEGRAM_ID)}`);

    await waitFor(() => {
      expect(screen.getByTestId("wizard-state")).toHaveAttribute("data-present", "true");
    });
    expect(screen.getByText("41 chars")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("uz_latn");
  });

  it("refuses a route parameter that is not a telegram id instead of requesting NaN", async () => {
    renderAt("/users/not-an-id");

    expect(await screen.findByText(/is not a Telegram user id/i)).toBeInTheDocument();
    expect(getUserOrdersMock).not.toHaveBeenCalled();
    expect(getUserMock).not.toHaveBeenCalled();
  });
});

/**
 * The reveal, on the banner rather than on the table.
 *
 * `POST /api/reveal`'s subject is an ORDER, and the banner is the one order the operator is
 * certainly talking about — §11.2 put it there because it is what support reads aloud. A
 * reveal control per table row would offer the same charge from eight places at once and make
 * it easy to unmask the wrong order's recipient while reading the right one's reference.
 */
describe("UserDetailScreen — the reveal", () => {
  it("offers the latest order's brief, keyed on that order's id", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderWithProviders(
      <Routes>
        <Route path="/users/:telegramUserId" element={<UserDetailScreen />} />
      </Routes>,
      { route: `/users/${String(TELEGRAM_ID)}`, me: meFixture("support"), config: configFixture() },
    );

    const banner = await screen.findByTestId("latest-order-banner");
    const trigger = within(banner).getByRole("button", { name: /Reveal this order's brief/u });
    expect(trigger).toBeInTheDocument();

    fireEvent.click(trigger);
    const dialog = screen.getByTestId("reveal-dialog");
    expect(dialog.textContent).toContain("22222222");
    // The masked name is still masked: opening the dialog is not the reveal.
    expect(dialog.textContent).not.toContain("G•••");
  });

  it("shows a VIEWER nothing at all", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderWithProviders(
      <Routes>
        <Route path="/users/:telegramUserId" element={<UserDetailScreen />} />
      </Routes>,
      { route: `/users/${String(TELEGRAM_ID)}`, me: meFixture("viewer") },
    );

    await screen.findByTestId("latest-order-banner");
    /*
     * `queryAllBy…().toHaveLength(0)` and not `queryBy…()`. There are two reveal buttons on
     * this screen for anyone who may see them, and `queryBy` throws on multiple matches —
     * so the singular form would have turned "a viewer sees both" into a crash whose message
     * is about ambiguous queries rather than about a permission leak. Counting says the
     * thing the test is named after: NEITHER of them is drawn.
     */
    expect(screen.queryAllByTestId("reveal-button")).toHaveLength(0);
  });
});

/**
 * The contact reveal — a second reveal, a different subject, a different place on the page.
 *
 * The order-brief reveal above is keyed on an ORDER and sits on the banner, because the banner
 * is the one order support is certainly talking about. This one is keyed on the PERSON, who is
 * the subject of the whole screen, so it sits in the page header. Two subjects, two regions;
 * every assertion below scopes accordingly.
 */
describe("UserDetailScreen — the contact reveal", () => {
  it("offers the contact details in the header and not on the order banner", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport();

    const banner = await screen.findByTestId("latest-order-banner");
    // The banner's reveal is the ORDER's brief and nothing else. A contact reveal inside a
    // card about one order would charge a person-shaped budget from an order-shaped context.
    expect(
      within(banner).queryByRole("button", { name: /contact details/u }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Reveal this person's contact details/u }),
    ).toBeInTheDocument();
  });

  it("keys the request on users.id, never on the Telegram integer", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport();

    await screen.findByTestId("latest-order-banner");
    fireEvent.click(screen.getByRole("button", { name: /Reveal this person's contact details/u }));
    fireEvent.change(screen.getByTestId("reveal-reason-code"), {
      target: { value: "support_investigation" },
    });
    fireEvent.click(screen.getByTestId("reveal-confirm"));

    await screen.findByTestId("reveal-result");
    const body = revealBodyOf(0);
    expect(body.subjectType).toBe("user");
    expect(body.subjectId).toBe(USER_ID);
    /*
     * Stated as its own assertion because the failure it guards is silent. The server
     * composes the step-up scope as `reveal:<subjectId>` and compares it WHOLE, so a
     * Telegram integer here never matches a grant minted against the UUID: the operator
     * re-authenticates, the same 403 comes back, and nothing on either side says why.
     */
    expect(body.subjectId).not.toBe(String(TELEGRAM_ID));
    // All four `user_profiles` columns, because they are one `SINGLE`-shaped record: the four
    // together cost exactly what one costs, so offering only the number would charge the same
    // budget for less answer.
    expect(body.fields).toEqual([
      "user_profiles.phone_e164",
      "user_profiles.first_name",
      "user_profiles.last_name",
      "user_profiles.telegram_username",
    ]);
  });

  it("reveals nothing merely by being opened", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport();

    await screen.findByTestId("latest-order-banner");
    fireEvent.click(screen.getByRole("button", { name: /Reveal this person's contact details/u }));

    const dialog = screen.getByTestId("reveal-dialog");
    expect(within(dialog).queryByTestId("reveal-result")).not.toBeInTheDocument();
    expect(postRevealMock).not.toHaveBeenCalled();

    /*
     * The masked number is still the only number on the page. The dialog itself carries the
     * subject LABEL — our masked id — and never the value it exists to unmask, so the check
     * is on the whole body: opening the dialog moved nothing from the masked side to the
     * clear side, and no `+`-then-digit sequence exists anywhere for it to have moved.
     */
    const body = document.body.textContent ?? "";
    expect(body).toContain("•••••42");
    expect(body).not.toContain(PLAINTEXT_PHONE);
    expect(body).not.toMatch(CLEAR_DIALLING_CODE);
    expect(dialog.textContent).not.toContain(PLAINTEXT_PHONE);
  });
});

/**
 * The face and the five facts behind it.
 *
 * `hasAvatar` and `avatarUrl` have different jobs and the tests keep them apart: `avatarUrl`
 * drives the picture and is `null` exactly when there is nothing to fetch, while `hasAvatar`
 * plus `avatarFetchedAt` drive a FACT in the panel — which is what an operator needs on the
 * day the picture will not draw and the `<img>` can tell them nothing.
 */
describe("UserDetailScreen — the profile panel", () => {
  it("draws the photo from the server's own URL", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    const { container } = renderAsSupport();

    await screen.findByTestId("latest-order-banner");
    const images = [...container.querySelectorAll<HTMLImageElement>("img")];
    expect(images).toHaveLength(1);
    // `getAttribute`, not `.src`: jsdom resolves the property against the document base URL,
    // so `.src` would compare an absolute URL against the relative path the server sends.
    expect(images[0]?.getAttribute("src")).toBe(pathUserAvatar(TELEGRAM_ID));
    // Empty by construction, so "the alt must never carry the raw Telegram integer" holds
    // without review — and `document.body.textContent` could not have caught it if it did not.
    expect(images[0]?.getAttribute("alt")).toBe("");
    expect(screen.getByText("captured")).toBeInTheDocument();
  });

  it("draws a monogram and no element at all when there is no photo", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    const { container } = renderAsSupport(makeUser({ hasAvatar: false, avatarUrl: null }));

    await screen.findByTestId("latest-order-banner");
    // Not a broken image and not a hidden one: no element. An `<img>` with nothing to fetch
    // is a request the browser still makes and a 404 an operator has to explain.
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(within(screen.getByTestId("profile-panel")).getByText("none")).toBeInTheDocument();
  });

  it("names an absent profile and admits it cannot tell erasure from absence", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport(makeProfilelessUser());

    await screen.findByTestId("latest-order-banner");
    const panel = screen.getByTestId("profile-panel");
    const standing = within(panel).getByText("no profile");
    expect(standing).toBeInTheDocument();
    /*
     * The hint has to name `/forget` by name. It is the only place in the console where the
     * "deletion IS the erasure record" consequence is spelled out to the person reading the
     * screen; without it, a two-word label reads as "this account never onboarded" about
     * somebody who may have onboarded years ago and then asked to be forgotten.
     */
    expect(standing.getAttribute("title")).toContain("/forget");
    // No lock. `user_profiles` is on no retention clock, so `🔒 purged <date>` would be an
    // invented date attached to an erasure the panel cannot actually confirm happened.
    expect(within(panel).queryByText(/🔒/u)).not.toBeInTheDocument();
  });

  it("still says onboarding is unfinished when a row exists with no number", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport(makeUser({ phoneMasked: null, phoneSharedAt: null }));

    await screen.findByTestId("latest-order-banner");
    const panel = screen.getByTestId("profile-panel");
    // A person who chose a language and stopped cannot order at all, and calling them
    // "onboarded" sends support hunting for a delivery that was never possible.
    expect(within(panel).getByText("onboarding unfinished")).toBeInTheDocument();
  });
});

/**
 * The credits panel — the three numbers that must not be allowed to merge.
 *
 * `creditBalance` is the stored column and what the ledger can prove; `creditsProjected` is
 * what the bot would tell the customer right now (the stored balance plus a rolling allowance
 * that is due and unminted); `inFlightRenderCount` is unsettled debits inside the grace
 * window. The support ticket this panel exists for — "they say they have three songs and your
 * panel says zero" — is unanswerable from any one of them.
 *
 * The load-bearing assertion in here is that `null` renders DIFFERENTLY from `0`. A null
 * balance means there is no `credit_accounts` row at all, which is the opposite claim from
 * "they have spent everything", and the operator's next move differs in each case.
 */
describe("UserDetailScreen — the credits panel", () => {
  it("shows balance, projection, in-flight, lifetime and allowance as facts", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    const panel = await screen.findByTestId("credits-panel");
    // `findByText` and not `getByText`: the panel element is on the page from the first
    // paint, with a skeleton in it, so awaiting the panel is not awaiting the facts.
    expect(await within(panel).findByText("balance")).toBeInTheDocument();
    for (const label of ["projected", "renders in flight", "lifetime granted", "allowance period"]) {
      expect(within(panel).getByText(label)).toBeInTheDocument();
    }
    expect(within(panel).getByTestId("credit-balance-chip")).toHaveAttribute("data-state", "held");
  });

  it("names an absent account rather than drawing it as a number", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    getUserCreditsMock.mockResolvedValue(ok(neverMeteredLedger()));
    renderAsRole("admin", makeNeverMeteredUser(), { creditsProjected: 3 });

    const panel = await screen.findByTestId("credits-panel");
    const chip = await within(panel).findByTestId("credit-balance-chip");
    expect(chip).toHaveAttribute("data-state", "never-metered");
    /*
     * `lifetimeCreditsGranted: null` is the SAME absent row the chip names, so it says so in
     * words too. A `0` there would be a claim — "we have granted this account nothing" —
     * about a table that holds no row to have granted anything on.
     */
    expect(within(panel).getAllByText(/never metered/iu).length).toBeGreaterThanOrEqual(2);
  });

  it("draws a metered balance of zero as a different state from an absent one", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin", makeUser({ creditBalance: 0 }), { creditsProjected: 0 });

    const panel = await screen.findByTestId("credits-panel");
    const chip = await within(panel).findByTestId("credit-balance-chip");
    /*
     * The pair this test exists for: `spent` here, `never-metered` above. "They have spent
     * everything they were given" and "there is no account row at all" send an operator to
     * two different next moves, and a chip that drew both as `0` would answer the wrong one.
     */
    expect(chip).toHaveAttribute("data-state", "spent");
    expect(chip.textContent).toContain("0 credits");
    expect(chip.textContent).not.toMatch(/never metered/iu);
  });

  it("reconciles a projection that disagrees with the stored balance", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin", makeUser({ creditBalance: 0 }), { creditsProjected: 3 });

    const note = await screen.findByTestId("credits-projection-note");
    // Both numbers, in one sentence, in the operator's terms: this is the answer to the call.
    expect(note.textContent).toContain("3");
    expect(note.textContent).toContain("0");
    expect(note.textContent).toMatch(/rolling allowance/iu);
  });

  it("says nothing when the two numbers agree and nothing is in flight", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    await screen.findByTestId("credits-panel");
    expect(screen.queryByTestId("credits-projection-note")).not.toBeInTheDocument();
  });

  it("explains an unsettled debit, which is the only reason a stocked account is refused", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin", makeUser(), { inFlightRenderCount: 1 });

    const note = await screen.findByTestId("credits-in-flight-note");
    expect(note.textContent).toMatch(/not settled/iu);
  });
});

/**
 * The ledger, and the one thing it must never do: render an absent account as an empty table.
 *
 * `GET /users/{id}/credits` distinguishes three answers — a 404 for an id neither table has
 * heard of, `account: null` for a user with no `credit_accounts` row, and an account object
 * with an empty page. The middle one is the one a table flattens by accident, and the two
 * populations behind it (never metered, and erased by `/forget`) are exactly the ones whose
 * next operator action differs.
 */
describe("UserDetailScreen — the credit ledger", () => {
  it("lists movements with the actor verbatim, admin prefix included", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    const panel = await screen.findByTestId("credits-panel");
    // Not masked. "was this account comped, and by whom?" is the question the table is open
    // for, and `admin:•••` sends the operator to the audit log for every grant.
    expect(await within(panel).findByText("admin:operator")).toBeInTheDocument();
    expect(within(panel).getByTestId("credit-delta")).toHaveAttribute("data-sign", "positive");
  });

  it("says 'never metered' for a null account rather than drawing an empty ledger", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    getUserCreditsMock.mockResolvedValue(ok(neverMeteredLedger()));
    renderAsRole("admin", makeNeverMeteredUser());

    const panel = await screen.findByTestId("credits-panel");
    expect(await within(panel).findByText("Never metered")).toBeInTheDocument();
    // The generic "no rows" copy would say the opposite of what this page means.
    expect(within(panel).queryByText("No movements")).not.toBeInTheDocument();
  });

  it("keeps orphaned movements visible when the account row was erased", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    getUserCreditsMock.mockResolvedValue(ok(neverMeteredLedger(ledgerPage().items)));
    renderAsRole("admin", makeNeverMeteredUser());

    // `/forget` deletes `credit_accounts` and nulls the ledger's Telegram id, so a null
    // account above a populated table is what a forgotten customer looks like — not a bug.
    expect(await screen.findByTestId("credit-ledger-orphan-note")).toBeInTheDocument();
    expect(screen.getByText("admin:operator")).toBeInTheDocument();
  });

  it("asks for its own page and not the orders table's", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    await screen.findByTestId("credits-panel");
    await waitFor(() => {
      expect(getUserCreditsMock).toHaveBeenCalled();
    });
    const call = getUserCreditsMock.mock.calls[0];
    expect(call?.[0]).toBe(TELEGRAM_ID);
    // The ledger is the explanation beside a balance, so it pages ten at a time rather than
    // fifty — and its cursor is component state, never the URL's, which belongs to orders.
    expect((call?.[1] as PageQuery | undefined)?.limit).toBe(10);
    expect((call?.[1] as PageQuery | undefined)?.cursor).toBeUndefined();
  });
});

/**
 * Grant Credits, at its call site.
 *
 * `credit.grant.write` is `OPERATOR_UP`, so SUPPORT — a role that may reveal a phone number
 * on this very screen — is the sharpest proof that §11.4's rule is hiding rather than
 * disabling: the button is absent, not greyed.
 */
describe("UserDetailScreen — granting credits", () => {
  it("shows no button at all to a role without credit.grant.write", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport();

    // Support still has its reveal, so this is a permission check and not a render failure —
    // and awaiting THAT button is what proves the header's actions have actually rendered.
    expect(
      await screen.findByRole("button", { name: /Reveal this person's contact details/u }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("grant-credits-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("grant-credits-dialog")).not.toBeInTheDocument();
  });

  it("grants with a mandatory reason and a freshly minted requestId", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    fireEvent.click(await screen.findByTestId("grant-credits-button"));
    fireEvent.change(screen.getByTestId("grant-credits-amount"), { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("action-reason-code"), {
      target: { value: "support_investigation" },
    });
    fireEvent.click(screen.getByTestId("action-confirm"));

    const result = await screen.findByTestId("grant-result");
    expect(result).toHaveAttribute("data-replay", "false");
    // The account read back INSIDE the write's transaction, not the request's arithmetic.
    expect(result.textContent).toContain("5");

    const [telegramUserId, body] = postCreditGrantMock.mock.calls[0] as [
      number,
      CreditGrantRequest,
    ];
    // The path parameter, never a body field: a second copy would be a second answer to
    // "who is being credited".
    expect(telegramUserId).toBe(TELEGRAM_ID);
    expect(body.credits).toBe(3);
    expect(body.reasonCode).toBe("support_investigation");
    /*
     * Minted per PRESS. The server keys `grant:admin:{id}:{requestId}`, so an id derived
     * from anything coarser silently grants nothing the second time an operator legitimately
     * grants again — a failure with no error and no ledger row to notice it by.
     */
    expect(body.requestId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u,
    );
  });

  it("says plainly when nothing moved, so a retry is not read as a second grant", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    postCreditGrantMock.mockResolvedValue(ok(grantResult({ isReplay: true })));
    renderAsRole("admin");

    fireEvent.click(await screen.findByTestId("grant-credits-button"));
    fireEvent.change(screen.getByTestId("action-reason-code"), {
      target: { value: "routine_ops" },
    });
    fireEvent.click(screen.getByTestId("action-confirm"));

    const result = await screen.findByTestId("grant-result");
    expect(result).toHaveAttribute("data-replay", "true");
    // The two outcomes differ, so the two sentences do. "Granted 3 credits" for both is how
    // an operator grants twice, or believes they did.
    expect(result.textContent).toMatch(/NOTHING moved/u);
  });

  it("refuses to send without a reason code", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    fireEvent.click(await screen.findByTestId("grant-credits-button"));
    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    fireEvent.click(screen.getByTestId("action-confirm"));
    expect(postCreditGrantMock).not.toHaveBeenCalled();
  });
});

/**
 * Block / unblock, at its call site.
 *
 * `isBlocked` picks the ROUTE and is never a body field: the two routes write different audit
 * actions, so a single endpoint taking a boolean would be an unblock that audits as a block.
 * What the call site passes is therefore the state being MOVED TO — the negation of the state
 * on screen — and that negation is the assertion worth pinning.
 */
describe("UserDetailScreen — blocking", () => {
  it("shows no button at all to a role without user.block.write", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsSupport();

    // Awaiting a control support DOES hold, so the absence below is a permission decision
    // rather than a header that had not rendered yet.
    await screen.findByRole("button", { name: /Reveal this person's contact details/u });
    expect(screen.queryByTestId("block-user-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("block-user-dialog")).not.toBeInTheDocument();
  });

  it("blocks an unblocked account with a reason", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    renderAsRole("admin");

    const button = await screen.findByTestId("block-user-button");
    expect(button).toHaveTextContent("Block");

    fireEvent.click(button);
    fireEvent.change(screen.getByTestId("action-reason-code"), {
      target: { value: "abuse_report" },
    });
    fireEvent.click(screen.getByTestId("action-confirm"));

    await waitFor(() => {
      expect(postUserBlockMock).toHaveBeenCalled();
    });
    const [telegramUserId, isBlocked, reason] = postUserBlockMock.mock.calls[0] as [
      number,
      boolean,
      { reasonCode: string },
    ];
    expect(telegramUserId).toBe(TELEGRAM_ID);
    expect(isBlocked).toBe(true);
    expect(reason.reasonCode).toBe("abuse_report");
  });

  it("offers the opposite action for an account that is already blocked", async () => {
    getUserOrdersMock.mockResolvedValue(ok(ordersPage([makeOrder()])));
    postUserBlockMock.mockResolvedValue(ok(blockResult(false)));
    renderAsRole("admin", makeUser({ isBlocked: true }));

    const button = await screen.findByTestId("block-user-button");
    expect(button).toHaveTextContent("Unblock");

    fireEvent.click(button);
    fireEvent.change(screen.getByTestId("action-reason-code"), {
      target: { value: "customer_request" },
    });
    fireEvent.click(screen.getByTestId("action-confirm"));

    await waitFor(() => {
      expect(postUserBlockMock).toHaveBeenCalled();
    });
    // The state being MOVED TO, which is the negation of the one on screen — not a re-send
    // of what the row already said.
    expect((postUserBlockMock.mock.calls[0] as [number, boolean])[1]).toBe(false);
  });
});
