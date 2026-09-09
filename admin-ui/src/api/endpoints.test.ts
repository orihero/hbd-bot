/**
 * What the new endpoint functions actually put on the wire.
 *
 * The schema tests next door prove the responses parse; these prove the REQUESTS are the ones
 * the routers answer — the right method, the right path, and the right query aliases. Those
 * are the details a screen cannot check for itself: a `?search=` where the server declared
 * `Query(alias="q")` is not an error anywhere, it is a filter that silently does nothing.
 */

import { describe, expect, it, vi } from "vitest";

import {
  ENDPOINT,
  getOrderStateCounts,
  getOrders,
  getUserCredits,
  getUsers,
  getVendorUsage,
  pathUserBlock,
  pathUserCredits,
  pathUserCreditsGrant,
  pathUserUnblock,
  postCreditGrant,
  postUserBlock,
} from "./endpoints";

const TELEGRAM_ID = 770000123;
const REQUEST_ID = "7a1b2c3d-4e5f-4061-8273-9a0b1c2d3e4f";

/** Stubs `fetch` with a 200 carrying `body`, and hands back the mock to read the URL off. */
function stubFetch(body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function urlOf(fetchMock: ReturnType<typeof vi.fn>, call = 0): string {
  const [url] = fetchMock.mock.calls[call] as unknown as [string, RequestInit];
  return url;
}

function initOf(fetchMock: ReturnType<typeof vi.fn>, call = 0): RequestInit {
  const [, init] = fetchMock.mock.calls[call] as unknown as [string, RequestInit];
  return init;
}

/**
 * The request body as a string. `RequestInit["body"]` is a `BodyInit` union — a Blob, a
 * stream, a form — none of which stringify to anything readable, so a bare `String(body)`
 * would quietly assert against `"[object Object]"`. Every body this client sends is a JSON
 * string; anything else is the failure worth seeing.
 */
function bodyOf(fetchMock: ReturnType<typeof vi.fn>, call = 0): string {
  const { body } = initOf(fetchMock, call);
  if (typeof body !== "string") {
    throw new Error(`expected a JSON string body, got ${typeof body}`);
  }
  return body;
}

const EMPTY_LEDGER = { account: null, items: [], meta: { nextCursor: null, total: null, isTotalExact: null } };
const EMPTY_PAGE = { items: [], meta: { nextCursor: null, total: null, isTotalExact: null } };

describe("path builders", () => {
  it("nests the credits routes under the user, and the grant under the credits", () => {
    expect(pathUserCredits(TELEGRAM_ID)).toBe("/api/users/770000123/credits");
    expect(pathUserCreditsGrant(TELEGRAM_ID)).toBe("/api/users/770000123/credits/grant");
    expect(pathUserBlock(TELEGRAM_ID)).toBe("/api/users/770000123/block");
    expect(pathUserUnblock(TELEGRAM_ID)).toBe("/api/users/770000123/unblock");
  });

  it("names the four new routes with the server's snake_case templates", () => {
    expect(ENDPOINT.userCredits).toBe("GET /api/users/{telegram_user_id}/credits");
    expect(ENDPOINT.userCreditsGrant).toBe("POST /api/users/{telegram_user_id}/credits/grant");
    expect(ENDPOINT.userBlock).toBe("POST /api/users/{telegram_user_id}/block");
    expect(ENDPOINT.orderStateCounts).toBe("GET /api/orders/state-counts");
  });
});

describe("getUsers", () => {
  /**
   * The alias is the bare `q`. `routers/users.py` declares `Query(alias="q")`, and an unknown
   * parameter is IGNORED rather than refused — so a client sending `?search=` gets an
   * unfiltered page and nothing on the screen says the search did not happen.
   */
  it("forwards the free-text search as `q` and the balance filter as `hasBalance`", async () => {
    const fetchMock = stubFetch(EMPTY_PAGE);

    await getUsers({ q: "77000", hasBalance: true, isBlocked: false });

    const url = urlOf(fetchMock);
    expect(url).toContain("q=77000");
    expect(url).toContain("hasBalance=true");
    expect(url).toContain("isBlocked=false");
  });

  it("omits both when they are absent, because absent and empty differ to this API", async () => {
    const fetchMock = stubFetch(EMPTY_PAGE);

    await getUsers({ telegramUserId: TELEGRAM_ID });

    expect(urlOf(fetchMock)).toBe("/api/users?telegramUserId=770000123");
  });
});

describe("getOrderStateCounts", () => {
  it("sends the list's filters to the aggregate route", async () => {
    const fetchMock = stubFetch({ counts: [], total: 0 });

    const result = await getOrderStateCounts({
      state: ["failed", "cancelled"],
      isPaid: true,
      from: "2026-09-01T00:00:00Z",
      to: "2026-09-05T00:00:00Z",
    });

    const url = urlOf(fetchMock);
    expect(url.startsWith("/api/orders/state-counts?")).toBe(true);
    // Repeats are how this API spells OR, and the aggregate takes the identical dependency:
    // filtering to `failed` makes every other segment 0, which is correct rather than useless.
    expect(url).toContain("state=failed&state=cancelled");
    expect(url).toContain("isPaid=true");
    expect(url).toContain("from=2026-09-01T00%3A00%3A00Z");
    expect(result.ok).toBe(true);
  });

  it("sends no paging parameters — the route takes none and its total is already exact", async () => {
    const fetchMock = stubFetch({ counts: [], total: 0 });

    await getOrderStateCounts({});

    expect(urlOf(fetchMock)).toBe("/api/orders/state-counts");
  });
});

/**
 * `windowParams` is shared by every windowed route, so the rule it enforces is pinned here
 * rather than on any one screen.
 *
 * The helper used to drop a lone bound, which was correct while `resolve_window` refused
 * one and became a lie on screen once it stopped: `/vendors` renders a "from" filter chip
 * from the URL, and a request that carried no window at all put the whole record under a
 * filtered heading. Every windowed router — orders, users, generations, assets, dashboard,
 * vendors — reaches `hbd/admin/window.py::resolve_window` through the same adapter, so
 * there is no endpoint for which sending half a window is the wrong move.
 */
describe("a one-sided window", () => {
  const EMPTY_USAGE = {
    window: null,
    isInstrumented: false,
    isCostPriced: false,
    hasRowsInWindow: false,
    totals: {
      calls: 0,
      successes: 0,
      failures: 0,
      successRate: null,
      costUsd: null,
      costedCalls: 0,
      totalTokens: null,
      billedCharacters: null,
      audioMs: null,
      avgLatencyMs: null,
    },
    rows: [],
  };

  it("sends `from` alone, because 'since X, and still going' is a question this API answers", async () => {
    // Arrange.
    const fetchMock = stubFetch(EMPTY_USAGE);

    // Act: the shape an operator's pasted link has when they trimmed the closing bound.
    await getVendorUsage({ from: "2026-09-01T00:00:00Z" });

    // Assert: the bound is on the wire, so the chip and the result describe one window.
    expect(urlOf(fetchMock)).toBe("/api/metrics/vendor-usage?from=2026-09-01T00%3A00%3A00Z");
  });

  it("sends `to` alone, whose missing start is absent rather than an epoch sentinel", async () => {
    const fetchMock = stubFetch(EMPTY_PAGE);

    await getOrders({ to: "2026-09-05T00:00:00Z" });

    expect(urlOf(fetchMock)).toBe("/api/orders?to=2026-09-05T00%3A00%3A00Z");
  });

  it("still spells 'no window' as no parameters at all", async () => {
    // Arrange / Act: an untouched filter on a shared list route.
    const fetchMock = stubFetch(EMPTY_PAGE);

    await getOrders({});

    // Assert: `buildQueryString` drops an `undefined`, so neither name appears.
    expect(urlOf(fetchMock)).toBe("/api/orders");
  });
});

describe("getUserCredits", () => {
  it("reads the ledger page under the user, forwarding only paging", async () => {
    const fetchMock = stubFetch(EMPTY_LEDGER);

    const result = await getUserCredits(TELEGRAM_ID, { limit: 20, withTotal: true });

    expect(urlOf(fetchMock)).toBe("/api/users/770000123/credits?limit=20&withTotal=true");
    expect(result.ok).toBe(true);
    expect(result.ok && result.data.account).toBeNull();
  });
});

describe("postCreditGrant", () => {
  it("POSTs the reason and the caller's requestId to the grant route", async () => {
    const fetchMock = stubFetch({
      telegramUserId: TELEGRAM_ID,
      telegramUserIdMasked: "•••••123",
      grantedCredits: 3,
      isReplay: false,
      idempotencyKey: `grant:admin:770000123:${REQUEST_ID}`,
      account: {
        telegramUserId: TELEGRAM_ID,
        telegramUserIdMasked: "•••••123",
        balance: 3,
        lifetimeGranted: 3,
        allowancePeriod: null,
      },
    });

    const result = await postCreditGrant(TELEGRAM_ID, {
      credits: 3,
      requestId: REQUEST_ID,
      reasonCode: "customer_request",
      reasonRef: "HD-4412",
    });

    expect(urlOf(fetchMock)).toBe("/api/users/770000123/credits/grant");
    expect(initOf(fetchMock).method).toBe("POST");
    // The Telegram id is the PATH parameter and never a body field: a second copy would be a
    // second answer to "who is being credited", which is how one account gets granted under
    // another account's re-authentication.
    expect(JSON.parse(bodyOf(fetchMock))).toEqual({
      credits: 3,
      requestId: REQUEST_ID,
      reasonCode: "customer_request",
      reasonRef: "HD-4412",
    });
    expect(result.ok && result.data.isReplay).toBe(false);
  });
});

describe("postUserBlock", () => {
  function blockResult(isBlocked: boolean): Record<string, unknown> {
    return {
      telegramUserId: TELEGRAM_ID,
      telegramUserIdMasked: "•••••123",
      isBlocked,
      changedAt: "2026-09-05T08:30:00Z",
    };
  }

  /**
   * `isBlocked` chooses the ROUTE. The body carries a reason and nothing else, because the
   * audit row is the only durable record of which action happened and a single `/block` with
   * `{"isBlocked": false}` would be an unblock that audits as a block.
   */
  it("posts to /block when blocking and to /unblock when lifting, with the same body", async () => {
    const fetchMock = stubFetch(blockResult(true));

    await postUserBlock(TELEGRAM_ID, true, { reasonCode: "abuse_report" });
    stubFetch(blockResult(false));
    await postUserBlock(TELEGRAM_ID, false, { reasonCode: "customer_request" });

    expect(urlOf(fetchMock)).toBe("/api/users/770000123/block");
    expect(JSON.parse(bodyOf(fetchMock))).toEqual({ reasonCode: "abuse_report" });
  });

  it("reads back the resulting state, because the pair is idempotent by design", async () => {
    stubFetch(blockResult(true));

    const result = await postUserBlock(TELEGRAM_ID, true, { reasonCode: "abuse_report" });

    // Pressing Block on an already-blocked account is a no-op that still writes an audit row;
    // the echo is how the operator sees the state is what they wanted without re-reading.
    expect(result.ok && result.data.isBlocked).toBe(true);
    expect(result.ok && result.data.changedAt).toBe("2026-09-05T08:30:00Z");
  });
});
