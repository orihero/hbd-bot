/**
 * §14's Slice 1d acceptance, as a test: *"The `/users` list's date column is headed **"last
 * order"**, not "last seen" — the real writer arrives in Phase 3."*
 *
 * The other assertions here guard the ways this screen could quietly lie.
 *
 * **The unmasked integer.** §12.3 masks the Telegram id at every role — the integer is on the
 * wire to build a link and for nothing else. Note the limit of that assertion, because it is
 * exactly why the avatar's `alt` is the empty string: `document.body.textContent` walks text
 * nodes and does NOT include attribute values, so an `alt="770000123"` would sail past it.
 * The colocated `UserAvatar.test.tsx` asserts the attribute itself; here the avatar case
 * re-states it per row, because a row is where the leak would actually be minted.
 *
 * **The sparkline.** Drawn only from a page that reached the end of its window, never from a
 * truncated one.
 *
 * **The mask.** `phoneMasked` is `"•••••42"` — the last two digits and nothing else. The
 * assertion is not just "the masked string is on screen" but that NO `+`-then-digit sequence
 * reaches the DOM at all. That is the client half of the country-prefix defect: a mask that
 * kept a clear `+998` head would hide the country code of a `+79161234567` while publishing
 * two of its subscriber digits, and this table is where an operator would first see such a
 * regression in `mask_phone`. A whole-body regex catches it wherever it surfaces, including
 * from a cell nobody thought to look at.
 *
 * **The absent profile.** `/forget` DELETEs the `user_profiles` row, so an erased profile and
 * a profile that never existed are the same absence with no stamp between them. The screen
 * must therefore render a NAMED STANDING and must not render a `🔒 purged` lock — that glyph
 * belongs to the retention clocks and this table is on none of them.
 *
 * **The empty state.** Its old sentence ("the first time somebody confirms an order") has been
 * false since `db/credits.py::touch` began upserting a `users` row on every inbound update.
 * The new copy is asserted so the correction cannot be silently reverted.
 *
 * **The credits column.** Three states and never two: `null` (no `credit_accounts` row at all)
 * must not render as `0` (metered, and spent).
 *
 * **The search box.** It says it searches by Telegram id, and nothing on the screen implies a
 * name search — the server refuses to be one, and for a privacy reason rather than an
 * unfinished one.
 *
 * **The peek.** Activating a row opens a drawer and leaves the table, its filters and its page
 * exactly where they were. The old behaviour navigated away from all three.
 */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ApiResult,
  CreditLedgerPage,
  OrderView,
  OrdersPage,
  UserView,
  UsersPage,
  UsersQuery,
} from "@/api";
import type * as ApiModule from "@/api";
import { MAX_SEARCH_CHARS, pathUserAvatar } from "@/api";
import { renderWithProviders, resetPrefs } from "@/components/util/testRender";

const { getUsersMock, getUserCreditsMock, getUserOrdersMock } = vi.hoisted(() => ({
  getUsersMock: vi.fn(),
  getUserCreditsMock: vi.fn(),
  getUserOrdersMock: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getUsers: getUsersMock,
  getUserCredits: getUserCreditsMock,
  getUserOrders: getUserOrdersMock,
}));

const { UsersScreen } = await import("./UsersScreen");

const TELEGRAM_ID = 770000123;

/**
 * The E.164 number `"•••••42"` is the mask of. It exists in this file ONLY as the string no
 * assertion may find; it is never fed to a fixture, because there is no field on this wire
 * that could carry it.
 */
const PLAINTEXT_PHONE = "+998901234542";

/** `+` immediately followed by a digit — the shape a leaking country prefix would have. */
const CLEAR_DIALLING_CODE = /\+\d/u;

/**
 * An onboarded customer with a photo, because that is the row with the most to get wrong.
 *
 * `avatarUrl` is built with `pathUserAvatar` rather than written as a literal: the server
 * sends its own spelling of that path and the client has a builder for it, so a fixture that
 * hard-coded the string could keep passing while the two spellings drifted apart. Building it
 * from the builder makes this fixture the drift check.
 */
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
    orderCount: 3,
    paidOrderCount: 2,
    isProfilePresent: true,
    telegramUsernameMasked: "@G•••",
    firstNameMasked: "G•••",
    lastNameMasked: "D•••",
    phoneMasked: "•••••42",
    phoneSharedAt: "2026-08-20T10:05:00Z",
    hasAvatar: true,
    avatarUrl: pathUserAvatar(TELEGRAM_ID),
    avatarFetchedAt: "2026-08-20T10:05:02Z",
    /* An account that HAS been metered and is holding two credits. `null` is the other fact
       entirely and is what `makeProfilelessUser` carries — see the credits-column tests. */
    creditBalance: 2,
    lifetimeCreditsGranted: 6,
    allowancePeriod: 41,
    ...overrides,
  };
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
    /* No `credit_accounts` row at all — never metered, or erased by `/forget`. NOT zero. */
    creditBalance: null,
    lifetimeCreditsGranted: null,
    allowancePeriod: null,
    ...overrides,
  });
}

function page(items: readonly UserView[], nextCursor: string | null, total: number): UsersPage {
  return { items: [...items], meta: { nextCursor, total, isTotalExact: true } };
}

function ok(data: UsersPage): ApiResult<UsersPage> {
  return { ok: true, data };
}

/** The screen fires three `getUsers` calls; branch on the shape rather than on call order. */
function respond(handler: (query: UsersQuery) => UsersPage): void {
  getUsersMock.mockImplementation((query: UsersQuery = {}) => Promise.resolve(ok(handler(query))));
}

/**
 * Every `<img>` inside the avatar COLUMN, found through `DataTable`'s own `data-column`.
 *
 * No `data-testid` is added to the column for this: `DataTable` already stamps `data-column`
 * on every `<th>` and `<td>` from the column's `id`, so a hook invented here would be a
 * second name for a thing that already has one — and the day the column is renamed, the
 * invented hook keeps passing while the column it claims to test is gone.
 */
function avatarImages(container: HTMLElement): readonly HTMLImageElement[] {
  return [...container.querySelectorAll<HTMLImageElement>('td[data-column="avatar"] img')];
}

/** One movement, so the peek's ledger has something to draw beside the balance. */
function ledgerPage(overrides: Partial<CreditLedgerPage> = {}): CreditLedgerPage {
  return {
    account: {
      telegramUserId: TELEGRAM_ID,
      telegramUserIdMasked: "•••••123",
      balance: 2,
      lifetimeGranted: 6,
      allowancePeriod: 41,
    },
    items: [
      {
        id: "33333333-3333-4333-8333-333333333333",
        kind: "grant",
        reason: "admin_grant",
        delta: 3,
        orderId: null,
        generation: 0,
        idempotencyKey: "grant:admin:770000123:7a1b2c3d-4e5f-4061-8273-9a0b1c2d3e4f",
        // Verbatim, `admin:` prefix included — the column exists to answer "by whom".
        actor: "admin:operator",
        createdAt: "2026-09-01T08:00:00Z",
      },
    ],
    meta: { nextCursor: null, total: 1, isTotalExact: true },
    ...overrides,
  };
}

/** The peek's order list. Mirrors `UserDetailScreen.test.tsx`'s shape, ten rows shorter. */
function makeOrder(overrides: Partial<OrderView> = {}): OrderView {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    state: "delivered",
    isPaid: true,
    correlationId: "0123456789abcdef0123456789abcdef",
    createdAt: "2026-09-01T09:00:00Z",
    updatedAt: "2026-09-01T09:05:00Z",
    deliveredAt: "2026-09-01T09:05:00Z",
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
    assetCount: 1,
    hasAssets: true,
    creditCost: 1,
    ledgerStatus: "settled",
    paymentRail: "credits",
    retryCount: 1,
    ...overrides,
  };
}

function ordersPage(items: readonly OrderView[]): OrdersPage {
  return { items: [...items], meta: { nextCursor: null, total: items.length, isTotalExact: true } };
}

/** The row the peek opens from — clicking any cell in it activates the row. */
function firstDataRow(): HTMLElement {
  const [, row] = screen.getAllByRole("row");
  if (row === undefined) throw new Error("the table rendered no data row");
  return row;
}

/** The most recent `getUsers` call that carried a filter, i.e. the LIST query. */
function lastListCall(): UsersQuery | undefined {
  return getUsersMock.mock.calls
    .map((call) => call[0] as UsersQuery)
    .filter((query) => query.limit !== 1 && query.from === undefined)
    .at(-1);
}

beforeEach(() => {
  resetPrefs();
  getUsersMock.mockReset();
  getUserCreditsMock.mockReset();
  getUserOrdersMock.mockReset();
  getUserCreditsMock.mockResolvedValue({ ok: true, data: ledgerPage() });
  getUserOrdersMock.mockResolvedValue({ ok: true, data: ordersPage([makeOrder()]) });
});

describe("UsersScreen", () => {
  it("heads the date column “last order”, never “last seen”", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByRole("columnheader", { name: /last order/i })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/last seen/i);
  });

  it("renders the masked telegram id and never the integer", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("•••••123")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(String(TELEGRAM_ID));
  });

  it("shows the total-users signal from the unfiltered probe", async () => {
    respond((query) =>
      query.limit === 1 ? page([makeUser()], null, 4_231) : page([makeUser()], null, 1),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("4,231")).toBeInTheDocument();
  });

  it("draws the 30-day sparkline only when the window page was complete", async () => {
    respond((query) =>
      query.from === undefined
        ? page([makeUser()], null, 1)
        : page([makeUser()], "more-pages", 900),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    await waitFor(() => {
      expect(screen.getByText(/daily series needs an accounts-per-day metric/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("img", { name: /new accounts per day/i })).not.toBeInTheDocument();
  });

  it("draws the sparkline when the whole window fitted in one page", async () => {
    respond((query) =>
      query.from === undefined
        ? page([makeUser()], null, 1)
        : page([makeUser({ accountCreatedAt: new Date().toISOString() })], null, 1),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(
      await screen.findByRole("img", { name: /new accounts per day, last 30 days/i }),
    ).toBeInTheDocument();
  });

  it("reads the filter state out of the URL rather than component state", async () => {
    respond(() => page([makeUser({ isBlocked: true })], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users?isBlocked=true&uiLanguage=ru" });

    await screen.findByRole("columnheader", { name: /last order/i });
    const listCall = getUsersMock.mock.calls
      .map((call) => call[0] as UsersQuery)
      .find((query) => query.isBlocked !== undefined);
    expect(listCall?.isBlocked).toBe(true);
    expect(listCall?.uiLanguage).toEqual(["ru"]);
  });

  it("shows the empty-filtered copy, naming the filter count, over the virgin one", async () => {
    respond(() => page([], null, 0));
    renderWithProviders(<UsersScreen />, { route: "/users?isBlocked=true" });

    expect(await screen.findByText(/no users match these filters/i)).toBeInTheDocument();
    expect(screen.getByText(/filter is narrowing this list/i)).toBeInTheDocument();
  });

  it("dates a row from first contact, not from a signup event that does not exist", async () => {
    respond(() => page([], null, 0));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(
      await screen.findByText(/a row appears the first time somebody speaks to the bot/i),
    ).toBeInTheDocument();
    // The sentence this replaced. `touch` has been upserting a row per inbound update for
    // some time, so "confirms an order" was false before this change and must not come back.
    expect(document.body.textContent).not.toMatch(/confirms an order/i);
  });
});

describe("UsersScreen — the avatar column", () => {
  it("draws exactly one lazy <img> per row that has a photo", async () => {
    respond(() => page([makeUser()], null, 1));
    const { container } = renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    const images = avatarImages(container);

    // ONE element, not two. Radix's `Avatar.Image` preloads through a detached
    // `new window.Image()` and then renders a second `<img>`; with `Cache-Control: no-store`
    // on every `/api/**` response that is a hundred requests for a fifty-row page. This
    // count is what keeps that regression out.
    expect(images).toHaveLength(1);
    const [image] = images;
    // `getAttribute`, not `.src`: jsdom resolves the property against the document base URL,
    // so `.src` would compare an absolute URL against the relative path the server sends.
    expect(image?.getAttribute("src")).toBe(pathUserAvatar(TELEGRAM_ID));
    expect(image?.getAttribute("loading")).toBe("lazy");
    // The `alt` a `textContent` assertion cannot see. Empty by construction, so "the alt must
    // never carry the raw Telegram integer" is true without anybody having to check.
    expect(image?.getAttribute("alt")).toBe("");
  });

  it("issues no request at all for a customer who shared no photo", async () => {
    respond(() => page([makeProfilelessUser()], null, 1));
    const { container } = renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });

    // Not a broken image and not a hidden one: no element. An `<img>` with a `null` src is a
    // request the browser still makes, and fifty of them is fifty 404s per page load.
    expect(avatarImages(container)).toHaveLength(0);
    expect(container.querySelectorAll('td[data-column="avatar"]')).toHaveLength(1);
  });
});

describe("UsersScreen — the contact profile", () => {
  it("shows the masked number and lets no dialling code reach the DOM", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("•••••42")).toBeInTheDocument();

    const body = document.body.textContent ?? "";
    expect(body).not.toContain(PLAINTEXT_PHONE);
    // The narrower half, and the one that would catch a NEW leak: no `+` followed by a digit
    // anywhere. A `+998•••••42` mask would satisfy the assertion above and fail this one.
    expect(body).not.toMatch(CLEAR_DIALLING_CODE);
  });

  it("names an absent profile instead of drawing a lock or a blank", async () => {
    respond(() => page([makeProfilelessUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("no profile")).toBeInTheDocument();
    // `🔒 purged <date>` is `<PurgedValue>`'s rendering of a retention clock. `user_profiles`
    // has no clock at all — `/forget` deletes the row — so a lock here would be an invented
    // date on a person who may simply never have onboarded.
    expect(document.body.textContent).not.toContain("🔒");
  });

  it("says “onboarded” only when a number has actually been shared", async () => {
    const unfinished = makeUser({
      id: "22222222-2222-4222-8222-222222222222",
      phoneMasked: null,
      phoneSharedAt: null,
    });
    respond(() => page([makeUser(), unfinished], null, 2));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    expect(await screen.findByText("onboarded")).toBeInTheDocument();
    // A row whose profile exists but holds no number cannot order, and saying "onboarded"
    // about it would send support looking for a delivery that was never possible.
    expect(screen.getByText("onboarding unfinished")).toBeInTheDocument();
  });
});

/**
 * §11.2's headline operator question — "does this customer have credits?" — answered on the
 * row. The assertion that matters is that `null` and `0` are not the same chip: `null` means
 * `credit_accounts` holds NO ROW (never metered, or erased by `/forget`) and `0` means the
 * account exists and has spent everything. Rendering the first as the second tells an
 * operator to explain a spend that never happened.
 */
describe("UsersScreen — the credits column", () => {
  it("draws three states, so “never metered” can never read as “0 credits”", async () => {
    respond(() =>
      page(
        [
          makeUser({ id: "aaaaaaaa-1111-4111-8111-111111111111", creditBalance: null }),
          makeUser({ id: "bbbbbbbb-1111-4111-8111-111111111111", creditBalance: 0 }),
          makeUser({ id: "cccccccc-1111-4111-8111-111111111111", creditBalance: 4 }),
        ],
        null,
        3,
      ),
    );
    renderWithProviders(<UsersScreen />, { route: "/users" });

    const chips = await screen.findAllByTestId("credit-balance-chip");
    expect(chips.map((chip) => chip.dataset["state"])).toEqual([
      "never-metered",
      "spent",
      "held",
    ]);
    // The words, not just the data attribute: the chip's whole job is that these read
    // differently to somebody who is not inspecting the DOM.
    expect(screen.getByText("never metered")).toBeInTheDocument();
    expect(screen.getByText("0 credits")).toBeInTheDocument();
    expect(screen.getByText("4 credits")).toBeInTheDocument();
  });
});

/**
 * The search box, and the sentence it is not allowed to say.
 *
 * `/api/users`'s `q` matches the TELEGRAM ID and nothing else, deliberately: every other text
 * column on this list is masked at all four roles, and a substring filter over one would be a
 * reveal an operator could perform three characters at a time with no step-up and no audit
 * row. So the placeholder has to say what is searchable, and no copy on this screen may
 * suggest a name search — an operator who believes names are searchable reads an empty result
 * as "this customer does not exist".
 */
describe("UsersScreen — the search and telegram-id controls", () => {
  it("says plainly that search is by telegram id, and never implies a name search", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    const box = await screen.findByLabelText("search");
    expect(box).toHaveAttribute("placeholder", expect.stringMatching(/telegram id/i));
    expect(document.body.textContent).not.toMatch(/search by name|name search|search users/i);
  });

  it("forwards `q` once the typing settles rather than on every keystroke", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    fireEvent.change(await screen.findByLabelText("search"), { target: { value: "77000" } });

    await waitFor(() => {
      expect(lastListCall()?.q).toBe("77000");
    });
    // One request for the settled value, not one per character: `77`, `770`, `7700`, `77000`
    // would be four list calls if the box wrote through on every keystroke.
    const searched = getUsersMock.mock.calls
      .map((call) => call[0] as UsersQuery)
      .filter((query) => query.q !== undefined);
    expect(searched).toHaveLength(1);
  });

  it("caps the search box at the server's own limit, so a long paste narrows rather than 422s", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    // The server declares `q` with `max_length=MAX_SEARCH_CHARS`, so an uncapped paste does
    // not return a narrower list — it returns INVALID_INPUT and empties the screen behind an
    // error that names a query parameter rather than the box it was pasted into.
    const box = await screen.findByLabelText("search");
    expect(box).toHaveAttribute("maxlength", String(MAX_SEARCH_CHARS));
  });

  it("gives telegramUserId a real control and forwards it as an integer", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    const box = await screen.findByLabelText("telegram id");
    // Digits only, stripped in the control: the box must never show a value the filter is
    // quietly ignoring.
    fireEvent.change(box, { target: { value: "77abc0" } });
    expect(box).toHaveValue("770");

    fireEvent.change(box, { target: { value: String(TELEGRAM_ID) } });
    await waitFor(() => {
      expect(lastListCall()?.telegramUserId).toBe(TELEGRAM_ID);
    });
  });

  it("empties the box when its chip is removed", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users?q=77000" });

    const box = await screen.findByLabelText("search");
    expect(box).toHaveValue("77000");

    fireEvent.click(screen.getByRole("button", { name: /remove filter search 77000/i }));

    // Without the URL→draft sync the removed filter would still be sitting in the input,
    // one keystroke away from reapplying itself.
    await waitFor(() => {
      expect(box).toHaveValue("");
    });
  });
});

/**
 * The presets. Each writes the SAME URL parameter its control in the bar writes — they are
 * shortcuts, not a second filter store — so a chip that is on is also a removal chip above.
 *
 * "In Wizard" is asserted ABSENT on purpose: wizard state is per-user Redis read one id at a
 * time, so that chip could only be built by scanning every row's key. It arrives when a
 * list-level source does, and until then a chip that half-works is worse than none.
 */
describe("UsersScreen — the quick-filter chips", () => {
  it("narrows to blocked accounts and says so through aria-pressed", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    const chip = await screen.findByRole("button", { name: "Blocked" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(chip);

    await waitFor(() => {
      expect(lastListCall()?.isBlocked).toBe(true);
    });
    expect(screen.getByRole("button", { name: "Blocked" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends hasBalance for the balance preset, and drops it rather than sending false", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    const chip = await screen.findByRole("button", { name: "Has balance > 0" });
    fireEvent.click(chip);
    await waitFor(() => {
      expect(lastListCall()?.hasBalance).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Has balance > 0" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Has balance > 0" })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });
    /*
     * Off is ABSENT, never `false`. `?hasBalance=false` is a filter in its own right — the
     * accounts with a zero balance AND the accounts with no `credit_accounts` row — and it is
     * not what turning a preset off means. Asserted over EVERY call, because turning it off
     * restores a query key the client already holds and therefore need not refetch at all.
     */
    for (const call of getUsersMock.mock.calls) {
      expect((call[0] as UsersQuery).hasBalance).not.toBe(false);
    }
  });

  it("offers no In Wizard chip, because there is no list-level source for it", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("button", { name: "Blocked" });
    expect(screen.queryByRole("button", { name: /wizard/i })).not.toBeInTheDocument();
  });
});

/**
 * The peek. Activating a row used to navigate to `/users/{id}`, which threw away the filters'
 * scroll position and the keyset page every time an operator checked one person in a list they
 * were working through. The drawer keeps all of it, and the full record is one link away.
 */
describe("UsersScreen — the peek drawer", () => {
  it("opens beside the table rather than navigating away from it", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users?isBlocked=true" });

    await screen.findByRole("columnheader", { name: /last order/i });
    const callsBefore = getUsersMock.mock.calls.length;
    fireEvent.click(firstDataRow());

    const drawer = await screen.findByTestId("user-peek-drawer");
    expect(drawer).toHaveAttribute("aria-modal", "true");
    /*
     * The table is still mounted behind it, still filtered, and was not refetched: the peek
     * costs the list nothing, which is the whole reason it is not a route.
     *
     * `hidden: true` because the drawer is MODAL — Radix marks the rest of the page
     * `aria-hidden` while it is open, which is correct and is exactly why the default query
     * cannot see the table. It is still there; a navigation would have unmounted it.
     */
    expect(
      screen.getByRole("columnheader", { name: /last order/i, hidden: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /remove filter blocked yes/i, hidden: true }),
    ).toBeInTheDocument();
    expect(getUsersMock.mock.calls).toHaveLength(callsBefore);
  });

  it("shows the balance, the ledger and the last ten orders", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    fireEvent.click(firstDataRow());

    const drawer = await screen.findByTestId("user-peek-drawer");
    expect(await within(drawer).findByText("admin:operator")).toBeInTheDocument();
    // A signed delta with its sign in the TEXT, not only in the colour.
    expect(within(drawer).getByTestId("credit-delta")).toHaveTextContent("+3");
    expect(within(drawer).getByTestId("credit-balance-chip")).toHaveAttribute(
      "data-state",
      "held",
    );
    await waitFor(() => {
      expect(within(drawer).getByTestId("order-ref-chip")).toBeInTheDocument();
    });
    expect(getUserCreditsMock).toHaveBeenCalledWith(
      TELEGRAM_ID,
      expect.objectContaining({ limit: 10 }),
      expect.anything(),
    );
  });

  it("links to the full record instead of duplicating it", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    fireEvent.click(firstDataRow());

    const link = await screen.findByTestId("open-full-record");
    expect(link).toHaveAttribute("href", `/users/${String(TELEGRAM_ID)}`);
    // The integer is in the href and nowhere in the text — the same rule the table is under.
    expect(document.body.textContent).not.toContain(String(TELEGRAM_ID));
  });

  /*
   * The row is a snapshot; the account is not.
   *
   * A grant made from this drawer's own footer invalidates the ledger below it, but nothing
   * re-derives the `UserView` the drawer was opened with — so a header chip reading off that
   * object would still say "never metered" under a ledger showing the grant, and the operator
   * who trusts the chip comps them a second time. The ledger response carries the account.
   */
  it("reads the balance and the lifetime total from the ledger's account, not the frozen row", async () => {
    respond(() => page([makeProfilelessUser()], null, 1));
    getUserCreditsMock.mockResolvedValue({
      ok: true,
      data: ledgerPage({
        account: {
          telegramUserId: TELEGRAM_ID,
          telegramUserIdMasked: "•••••123",
          balance: 3,
          lifetimeGranted: 3,
          allowancePeriod: null,
        },
      }),
    });
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    fireEvent.click(firstDataRow());
    const drawer = await screen.findByTestId("user-peek-drawer");

    await waitFor(() => {
      expect(within(drawer).getByTestId("credit-balance-chip")).toHaveAttribute(
        "data-state",
        "held",
      );
    });
    expect(within(drawer).getByTestId("credit-balance-chip")).toHaveTextContent("3 credits");
    expect(drawer.textContent).not.toContain("never metered");
    // And the fact beside it moves with the same answer, rather than staying on the row's dash.
    expect(within(drawer).getByText("lifetime granted").closest("div")).toHaveTextContent("3");
  });

  it("fetches nothing for a row nobody has peeked", async () => {
    respond(() => page([makeUser()], null, 1));
    renderWithProviders(<UsersScreen />, { route: "/users" });

    await screen.findByRole("columnheader", { name: /last order/i });
    // Fifty rows must not be fifty ledger requests: the drawer's queries are `enabled` only
    // while it is open.
    expect(getUserCreditsMock).not.toHaveBeenCalled();
    expect(getUserOrdersMock).not.toHaveBeenCalled();
  });
});
