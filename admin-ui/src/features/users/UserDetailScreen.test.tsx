/**
 * §11.2's dominant signal for `/users/:telegramUserId`: "Full-width banner: status of their
 * most recent order."
 *
 * The banner reads its own `limit=1` query, so the test also pins the reason: paging the
 * list below must not change what the banner says.
 */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import type {
  ApiResult,
  OrderView,
  OrdersPage,
  PageQuery,
  UserDetailView,
  UserView,
  WizardStateView,
} from "@/api";
import type * as ApiModule from "@/api";
import {
  configFixture,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";

const { getUserMock, getUserOrdersMock, getWizardStateMock } = vi.hoisted(() => ({
  getUserMock: vi.fn(),
  getUserOrdersMock: vi.fn(),
  getWizardStateMock: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getUser: getUserMock,
  getUserOrders: getUserOrdersMock,
  getWizardState: getWizardStateMock,
}));

const { UserDetailScreen } = await import("./UserDetailScreen");

const TELEGRAM_ID = 770000123;

function makeUser(overrides: Partial<UserView> = {}): UserView {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    uiLanguage: "uz_latn",
    isBlocked: false,
    accountCreatedAt: "2026-08-20T10:00:00Z",
    firstOrderAt: "2026-08-20T10:00:00Z",
    lastOrderAt: "2026-09-01T09:00:00Z",
    orderCount: 2,
    paidOrderCount: 1,
    ...overrides,
  };
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
    ...overrides,
  };
}

function ordersPage(items: readonly OrderView[]): OrdersPage {
  return { items: [...items], meta: { nextCursor: null, total: items.length, isTotalExact: true } };
}

function detail(user: UserView): UserDetailView {
  return {
    user,
    ordersByState: [
      { state: "delivered", count: 1 },
      { state: "generating", count: 1 },
    ],
    deliveredOrderCount: 1,
    failedOrderCount: 0,
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
  getUserMock.mockReset();
  getUserOrdersMock.mockReset();
  getWizardStateMock.mockReset();
  getUserMock.mockResolvedValue(ok(detail(makeUser())));
  getWizardStateMock.mockResolvedValue(ok(wizard()));
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
    expect(screen.queryByTestId("reveal-button")).not.toBeInTheDocument();
  });
});
