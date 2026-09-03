/**
 * `/login` — the three server behaviours the screen is not allowed to soften.
 *
 * These tests drive the real client through a stubbed `fetch` rather than seeding the query
 * cache, because what is under test *is* the request path: the 401 body, the `Retry-After`
 * header, and what the panel does with `mustChangePassword` on the login response.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResponse } from "@/api";
import {
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";

import { LoginScreen } from "./LoginScreen";

/** A `Response` with only the four members the client touches. */
function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  const lower = new Map(
    Object.entries(headers).map(([name, value]) => [name.toLowerCase(), value] as const),
  );
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => lower.get(name.toLowerCase()) ?? null },
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function envelope(code: string, message: string, correlationId = "c0ffee"): unknown {
  return { error: { code, message, correlationId } };
}

interface Wiring {
  /** What `GET /auth/me` answers. `null` means 401 — nobody is signed in. */
  me: MeResponse | null;
  /** What `POST /auth/login` answers. */
  login: () => Response;
}

function stubFetch(wiring: Wiring): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: unknown) => {
      const url = String(input);
      if (url.includes("/api/auth/me")) {
        return Promise.resolve(
          wiring.me === null
            ? jsonResponse(401, envelope("UNAUTHENTICATED", "sign in to continue"))
            : jsonResponse(200, wiring.me),
        );
      }
      if (url.includes("/api/auth/login")) return Promise.resolve(wiring.login());
      return Promise.reject(new Error(`unexpected request: ${url}`));
    }),
  );
}

async function signIn(): Promise<void> {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Username"), "operator");
  await user.type(screen.getByLabelText("Password"), "hunter2hunter2");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

function renderScreen() {
  return renderWithProviders(<LoginScreen />, {
    client: makeTestQueryClient(),
    me: null,
    route: "/login",
  });
}

beforeEach(() => {
  resetPrefs();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LoginScreen", () => {
  it("renders the server's 401 verbatim and explains that it is the same either way", async () => {
    const message = "that username and password do not match an active account";
    stubFetch({
      me: null,
      login: () => jsonResponse(401, envelope("UNAUTHENTICATED", message)),
    });
    renderScreen();
    await signIn();

    const failure = await screen.findByTestId("auth-failure");
    expect(failure).toHaveTextContent(message);
    expect(failure).toHaveTextContent(/The same answer is given/);
    // Nothing on screen may hint at which half was wrong.
    expect(failure).not.toHaveTextContent(/unknown user|no such account|user not found/i);
  });

  it("counts down a 429 and refuses to spend the next attempt", async () => {
    stubFetch({
      me: null,
      login: () =>
        jsonResponse(429, envelope("LOGIN_RATE_LIMITED", "too many sign-in attempts"), {
          "Retry-After": "45",
        }),
    });
    renderScreen();
    await signIn();

    const failure = await screen.findByTestId("auth-failure");
    expect(failure).toHaveAttribute("data-code", "LOGIN_RATE_LIMITED");
    expect(screen.getByTestId("auth-retry-countdown")).toHaveTextContent("Try again in 45s.");
    expect(screen.getByRole("button", { name: "Wait 45s" })).toBeDisabled();
    // The panel does not say WHICH counter tripped — the per-username one is a DoS vector.
    expect(failure).not.toHaveTextContent(/per address counter|username counter/i);
  });

  it("goes straight to the rotation form when the account must change its password", async () => {
    let me: MeResponse | null = null;
    stubFetch({
      get me() {
        return me;
      },
      login: () => {
        me = { ...meFixture("owner"), mustChangePassword: true };
        return jsonResponse(200, { mustChangePassword: true });
      },
    });
    renderScreen();
    await signIn();

    const form = await screen.findByTestId("password-rotation-form");
    expect(form).toHaveAttribute("data-forced", "true");
    // Forced means forced: no sign-out, no way back into the console.
    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/including signing out/)).toBeInTheDocument();
  });

  it("never shows a sign-in form to an operator who already has a session", async () => {
    stubFetch({ me: meFixture("owner"), login: () => jsonResponse(200, { mustChangePassword: false }) });
    renderScreen();
    await waitFor(() => {
      expect(screen.queryByTestId("login-form")).not.toBeInTheDocument();
    });
  });

  it("explains an ORIGIN_REJECTED rather than leaving it as a bare 403", async () => {
    stubFetch({
      me: null,
      login: () =>
        jsonResponse(403, envelope("ORIGIN_REJECTED", "this request did not come from the panel")),
    });
    renderScreen();
    await signIn();

    expect(await screen.findByTestId("auth-failure")).toHaveTextContent(
      /HBD_ADMIN_PUBLIC_ORIGIN/,
    );
  });
});
