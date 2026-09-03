/**
 * The rotation form, in the mode that matters: forced.
 *
 * §14 Slice 1a makes every route but this one and `/auth/me` a 403 while
 * `must_change_password` is set — logout included. So the assertions are mostly about what
 * is NOT on screen: any control that would 403 on click is worse than no control, because
 * the operator cannot tell a refused action from a broken panel.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MIN_PASSWORD_CHARS } from "@/api";
import {
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";

import { ChangePasswordScreen } from "./ChangePasswordScreen";

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

function stubPasswordFetch(response: () => Response): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: unknown) => {
      const url = String(input);
      if (url.includes("/api/auth/password")) return Promise.resolve(response());
      if (url.includes("/api/auth/me")) {
        return Promise.resolve(
          jsonResponse(401, {
            error: { code: "UNAUTHENTICATED", message: "sign in", correlationId: "c" },
          }),
        );
      }
      return Promise.reject(new Error(`unexpected request: ${url}`));
    }),
  );
}

function renderScreen(isForced = true) {
  return renderWithProviders(<ChangePasswordScreen isForced={isForced} />, {
    client: makeTestQueryClient(),
    me: null,
    route: "/login",
  });
}

async function fillForm(current: string, next: string, confirmation = next): Promise<void> {
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText("Current password"));
  await user.type(screen.getByLabelText("Current password"), current);
  await user.type(screen.getByLabelText("New password"), next);
  await user.type(screen.getByLabelText("New password again"), confirmation);
}

beforeEach(() => {
  resetPrefs();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChangePasswordScreen", () => {
  it("offers no way out when the rotation is forced", () => {
    renderScreen();
    expect(screen.getByTestId("password-rotation-form")).toHaveAttribute("data-forced", "true");
    expect(screen.getByText(/including signing out/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("still asks for the current password on the forced path", () => {
    renderScreen();
    expect(screen.getByLabelText("Current password")).toBeInTheDocument();
  });

  it("blocks a new password under the floor before spending a round trip", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    renderScreen();
    await fillForm("temporary-one", "short");

    expect(
      screen.getByText(`Too short — ${String(MIN_PASSWORD_CHARS)} characters minimum.`),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("blocks a mismatched confirmation", async () => {
    renderScreen();
    await fillForm("temporary-one", "a-long-enough-password", "a-different-password");
    expect(screen.getByText("The two entries do not match.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
  });

  it("renders the server's wrong-current-password message verbatim", async () => {
    const message = "that is not your current password";
    stubPasswordFetch(() =>
      jsonResponse(403, { error: { code: "FORBIDDEN", message, correlationId: "c0ffee" } }),
    );
    renderScreen();
    await fillForm("wrong-password", "a-long-enough-password");
    await userEvent.setup().click(screen.getByRole("button", { name: "Change password" }));

    expect(await screen.findByTestId("auth-failure")).toHaveTextContent(message);
  });

  it("treats REAUTH_RATE_LIMITED as its own thing, with its own remedy", async () => {
    stubPasswordFetch(() =>
      jsonResponse(
        429,
        {
          error: {
            code: "REAUTH_RATE_LIMITED",
            message: "too many password attempts on this session",
            correlationId: "c0ffee",
          },
        },
        { "Retry-After": "30" },
      ),
    );
    renderScreen();
    await fillForm("temporary-one", "a-long-enough-password");
    await userEvent.setup().click(screen.getByRole("button", { name: "Change password" }));

    const failure = await screen.findByTestId("auth-failure");
    expect(failure).toHaveAttribute("data-code", "REAUTH_RATE_LIMITED");
    expect(failure).toHaveTextContent(/Signing in again starts a fresh window/);
    expect(screen.getByTestId("auth-retry-countdown")).toHaveTextContent("Try again in 30s.");
  });
});
