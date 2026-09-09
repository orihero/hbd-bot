/**
 * The grant, from the four angles that can turn it into money moving twice or not at all.
 *
 * **Who sees it.** `credit.grant.write` is the router's own permission; §11.4 is hiding, not
 * disabling, so SUPPORT sees no button at all.
 *
 * **The reason.** No `reasonCode`, no confirm. The server's 422 is not allowed to be how the
 * operator finds out that an unattributed grant is refused.
 *
 * **The `requestId`.** Fresh per PRESS, and the SAME one on a step-up retry. Those are two
 * different rules pulling in opposite directions and both are asserted here: a retry that
 * mints a new id is a second grant, and a second press that reuses the old id is a grant that
 * silently does nothing.
 *
 * **`isReplay`.** The two outcomes read differently on screen, because "we added three" and
 * "this had already been added and nothing moved" are different answers to the same press.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminRole } from "@/api";
import {
  configFixture,
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { FRESH_GRANT_NOTICE, GrantCreditsButton, REPLAY_NOTICE } from "./GrantCreditsDialog";

const TELEGRAM_ID = 770000123;

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function grantResult(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    telegramUserId: TELEGRAM_ID,
    telegramUserIdMasked: "•••••123",
    grantedCredits: 3,
    isReplay: false,
    idempotencyKey: "grant:admin:770000123:7a1b2c3d-4e5f-4061-8273-9a0b1c2d3e4f",
    account: {
      telegramUserId: TELEGRAM_ID,
      telegramUserIdMasked: "•••••123",
      balance: 5,
      lifetimeGranted: 9,
      allowancePeriod: 41,
    },
    ...overrides,
  };
}

interface Stub {
  readonly grant: () => Response;
  readonly stepUp?: () => Response;
}

/** Every request this dialog can make, and nothing else. An unexpected URL fails loudly. */
function stubFetch(stub: Stub): ReturnType<typeof vi.fn> {
  const calls = vi.fn((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/credits/grant")) return Promise.resolve(stub.grant());
    if (url.includes("/api/auth/step-up")) {
      const answer = stub.stepUp;
      if (answer === undefined) return Promise.reject(new Error("no step-up expected"));
      return Promise.resolve(answer());
    }
    return Promise.reject(new Error(`unexpected request: ${url} ${String(init?.method)}`));
  });
  vi.stubGlobal("fetch", calls);
  return calls;
}

function renderButton(role: AdminRole = "admin", onSuccess?: () => void) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.config.detail(), configFixture());
  return renderWithProviders(
    <GrantCreditsButton
      telegramUserId={TELEGRAM_ID}
      subjectLabel="•••••123"
      onSuccess={onSuccess}
    />,
    { client, me: meFixture(role) },
  );
}

function open(): void {
  fireEvent.click(screen.getByTestId("grant-credits-button"));
}

function setCredits(value: string): void {
  fireEvent.change(screen.getByTestId("grant-credits-amount"), { target: { value } });
}

function chooseReason(code = "customer_request"): void {
  fireEvent.change(screen.getByTestId("action-reason-code"), { target: { value: code } });
}

function confirm(): void {
  fireEvent.click(screen.getByTestId("action-confirm"));
}

function bodyOf(calls: ReturnType<typeof vi.fn>, index: number): Record<string, unknown> {
  const call = calls.mock.calls[index];
  if (call === undefined) throw new Error(`no call ${String(index)}`);
  const init = call[1] as RequestInit | undefined;
  const raw = init?.body;
  if (typeof raw !== "string") throw new Error(`call ${String(index)} carried no JSON body`);
  return JSON.parse(raw) as Record<string, unknown>;
}

const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

beforeEach(() => {
  resetPrefs();
});

describe("who sees the affordance at all", () => {
  it("is invisible below OPERATOR — the permission the router guards is credit.grant.write", () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton("support");

    expect(screen.queryByTestId("grant-credits-button")).not.toBeInTheDocument();
  });

  it("is there for an ADMIN — OPERATOR_UP in §12.2", () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton("admin");

    expect(screen.getByTestId("grant-credits-button")).toBeInTheDocument();
  });
});

describe("before the confirm", () => {
  it("withholds the grant until a reason is chosen, and says why", () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton();
    open();

    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    expect(screen.getByTestId("action-reason-required")).toBeInTheDocument();

    chooseReason();

    expect(screen.getByTestId("action-confirm")).toBeEnabled();
  });

  it("refuses a credits value outside 1..100 before the server has to", () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton();
    open();
    chooseReason();

    setCredits("0");
    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    setCredits("101");
    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    setCredits("2.5");
    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    setCredits("100");
    expect(screen.getByTestId("action-confirm")).toBeEnabled();
  });
});

describe("the grant", () => {
  it("posts the credits, the reason and a freshly minted requestId", async () => {
    const calls = stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    const onSuccess = vi.fn();
    renderButton("admin", onSuccess);
    open();
    setCredits("3");
    chooseReason("customer_request");
    confirm();

    await screen.findByTestId("grant-result");

    const body = bodyOf(calls, 0);
    expect(body["credits"]).toBe(3);
    expect(body["reasonCode"]).toBe("customer_request");
    // The Telegram id is the PATH parameter and never a body field.
    expect(body["telegramUserId"]).toBeUndefined();
    expect(String(body["requestId"])).toMatch(UUID_SHAPE);
    expect(String(calls.mock.calls[0]?.[0])).toBe("/api/users/770000123/credits/grant");
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("says the credits were added just now when the server did the work", async () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton();
    open();
    chooseReason();
    confirm();

    const result = await screen.findByTestId("grant-result");
    expect(result).toHaveAttribute("data-replay", "false");
    expect(result.textContent).toContain(FRESH_GRANT_NOTICE);
    expect(result.textContent).toContain("balance now 5");
  });

  it("says NOTHING MOVED on a replay, rather than reporting a second grant", async () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult({ isReplay: true })) });
    renderButton();
    open();
    chooseReason();
    confirm();

    const result = await screen.findByTestId("grant-result");
    expect(result).toHaveAttribute("data-replay", "true");
    expect(result.textContent).toContain(REPLAY_NOTICE);
    expect(result.textContent).not.toContain(FRESH_GRANT_NOTICE);
  });

  it("mints a DIFFERENT requestId for the next press — two presses are two grants", async () => {
    const calls = stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton();

    open();
    chooseReason();
    confirm();
    await screen.findByTestId("grant-result");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    open();
    chooseReason();
    confirm();
    await waitFor(() => {
      expect(calls.mock.calls).toHaveLength(2);
    });

    expect(bodyOf(calls, 1)["requestId"]).not.toBe(bodyOf(calls, 0)["requestId"]);
  });

  it("re-sends the SAME requestId when the operator retries the attempt that failed", async () => {
    // The write commits, the gateway times out, the client sees a failure: the second press
    // is a RETRY. A fresh id here writes a second grant, which is the exact double-comp the
    // server's idempotency key exists to refuse.
    let attempts = 0;
    const calls = stubFetch({
      grant: () => {
        attempts += 1;
        return attempts === 1
          ? jsonResponse(504, {
              error: {
                code: "NETWORK_ERROR",
                message: "the gateway timed out",
                correlationId: "c0ffee",
              },
            })
          : jsonResponse(200, grantResult({ isReplay: true }));
      },
    });
    renderButton();
    open();
    setCredits("3");
    chooseReason("customer_request");
    confirm();
    await screen.findByTestId("grant-failure");

    confirm();
    const result = await screen.findByTestId("grant-result");

    expect(bodyOf(calls, 1)["requestId"]).toBe(bodyOf(calls, 0)["requestId"]);
    // And the server can therefore tell the operator what actually happened: nothing moved,
    // because the timed-out request had already landed.
    expect(result).toHaveAttribute("data-replay", "true");
  });

  it("mints a fresh requestId when the form changed after a failure — that is a different grant", async () => {
    let attempts = 0;
    const calls = stubFetch({
      grant: () => {
        attempts += 1;
        return attempts === 1
          ? jsonResponse(500, {
              error: { code: "INTERNAL", message: "boom", correlationId: "c0ffee" },
            })
          : jsonResponse(200, grantResult());
      },
    });
    renderButton();
    open();
    setCredits("3");
    chooseReason("customer_request");
    confirm();
    await screen.findByTestId("grant-failure");

    setCredits("9");
    confirm();
    await screen.findByTestId("grant-result");

    // Reusing the id here would fold "grant 9" into the earlier "grant 3" and hand back a
    // replay: the operator would be told it worked, and nothing would have moved.
    expect(bodyOf(calls, 1)["credits"]).toBe(9);
    expect(bodyOf(calls, 1)["requestId"]).not.toBe(bodyOf(calls, 0)["requestId"]);
  });

  it("reports a refusal that re-authentication cannot fix as the refusal it is", async () => {
    stubFetch({
      grant: () =>
        jsonResponse(409, {
          error: {
            code: "CONFLICT",
            message: "the ledger moved under this request",
            correlationId: "c0ffee",
          },
        }),
    });
    renderButton();
    open();
    chooseReason();
    confirm();

    const failure = await screen.findByTestId("grant-failure");
    expect(failure).toHaveAttribute("data-code", "CONFLICT");
    expect(screen.queryByTestId("step-up-prompt")).not.toBeInTheDocument();
  });
});

/**
 * The outcome has nowhere else to go.
 *
 * There is no toast host in this console, so the `role="status"` panel inside the dialog is
 * the only place `isReplay` is ever said. A dialog that can be dismissed mid-flight therefore
 * loses it: the POST lands, real credits are written, the operator is told nothing, and their
 * next press mints a new key and comps the account twice.
 */
describe("dismissal while an answer is outstanding", () => {
  /** A grant the test settles by hand, so the dialog can be poked while it is unsettled. */
  function deferredGrant(): {
    readonly calls: ReturnType<typeof vi.fn>;
    readonly settle: () => void;
  } {
    let resolve: ((value: Response) => void) | undefined;
    const pending = new Promise<Response>((resolveGrant) => {
      resolve = resolveGrant;
    });
    const calls = vi.fn((input: unknown) => {
      if (String(input).includes("/credits/grant")) return pending;
      return Promise.reject(new Error(`unexpected request: ${String(input)}`));
    });
    vi.stubGlobal("fetch", calls);
    return {
      calls,
      settle: () => {
        resolve?.(jsonResponse(200, grantResult({ isReplay: true })));
      },
    };
  }

  it("refuses Escape, the X and Cancel while the grant is in flight", async () => {
    const { calls, settle } = deferredGrant();
    renderButton();
    open();
    chooseReason();
    confirm();
    await waitFor(() => {
      expect(calls).toHaveBeenCalledTimes(1);
    });

    fireEvent.keyDown(screen.getByTestId("grant-credits-dialog"), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByTestId("grant-credits-dialog")).toBeInTheDocument();

    settle();
    // And so the answer the operator pressed for is the answer they get, replay and all.
    const result = await screen.findByTestId("grant-result");
    expect(result).toHaveAttribute("data-replay", "true");
    expect(result.textContent).toContain(REPLAY_NOTICE);
  });

  it("holds the result on screen until Done — Escape does not throw the answer away", async () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton();
    open();
    chooseReason();
    confirm();
    await screen.findByTestId("grant-result");

    fireEvent.keyDown(screen.getByTestId("grant-credits-dialog"), { key: "Escape" });
    expect(screen.getByTestId("grant-result")).toBeInTheDocument();

    // Done is the acknowledgement, and the only way out while an outcome is unread.
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.queryByTestId("grant-credits-dialog")).not.toBeInTheDocument();
    });
  });

  it("still closes on Escape before anything has been sent", () => {
    stubFetch({ grant: () => jsonResponse(200, grantResult()) });
    renderButton();
    open();
    chooseReason();

    fireEvent.keyDown(screen.getByTestId("grant-credits-dialog"), { key: "Escape" });

    // The lock is about an outstanding answer, not about trapping the operator in a form.
    expect(screen.queryByTestId("grant-credits-dialog")).not.toBeInTheDocument();
  });
});

describe("a 403 STEP_UP_REQUIRED", () => {
  const refusal = () =>
    jsonResponse(403, {
      error: {
        code: "STEP_UP_REQUIRED",
        message: "re-authenticate for this action and this subject",
        correlationId: "c0ffee",
        // The subject is the Telegram integer as a bare decimal string, NOT a uuid.
        details: { stepUpAction: "credit.grant", subjectId: String(TELEGRAM_ID) },
      },
    });

  it("routes into the password box carrying the server's own subject spelling", async () => {
    stubFetch({ grant: refusal });
    renderButton();
    open();
    chooseReason();
    confirm();

    const prompt = await screen.findByTestId("step-up-prompt");
    expect(prompt.dataset["stepUpAction"]).toBe("credit.grant");
    // Byte-identical: a re-formatted subject id is a scope mismatch nobody can debug.
    expect(prompt.dataset["stepUpSubject"]).toBe("770000123");
    expect(screen.queryByTestId("grant-failure")).not.toBeInTheDocument();
  });

  it("re-sends the SAME body — same requestId, same reason — once the grant lands", async () => {
    let attempts = 0;
    const calls = stubFetch({
      grant: () => {
        attempts += 1;
        return attempts === 1 ? refusal() : jsonResponse(200, grantResult());
      },
      stepUp: () =>
        jsonResponse(200, {
          scope: `credit.grant:${String(TELEGRAM_ID)}`,
          grantedAt: "2026-09-02T10:30:00Z",
          expiresAt: "2026-09-02T10:35:00Z",
        }),
    });

    renderButton();
    open();
    setCredits("7");
    chooseReason("incident");
    confirm();
    await screen.findByTestId("step-up-prompt");

    fireEvent.change(screen.getByLabelText("Your password"), {
      target: { value: "hunter2hunter2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Re-authenticate" }));

    await screen.findByTestId("grant-result");

    const first = bodyOf(calls, 0);
    const retry = bodyOf(calls, 2);
    // A fresh id here would make the retry a SECOND grant; the operator's typed reason and
    // amount must survive the detour as well.
    expect(retry).toEqual(first);
    expect(retry["credits"]).toBe(7);
    expect(retry["reasonCode"]).toBe("incident");
  });
});
