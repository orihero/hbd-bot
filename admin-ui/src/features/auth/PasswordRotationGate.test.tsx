/**
 * The gate, and the one distinction it must not blur: `UNAUTHENTICATED` ends a session,
 * `FORBIDDEN` does not. Redirecting on a 403 would sign an operator out of the console for
 * opening a page their role does not hold — and then, because the cookie is still valid,
 * sign them straight back in, which is a loop rather than a message.
 */

import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResponse } from "@/api";
import {
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { PasswordRotationGate } from "./PasswordRotationGate";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function renderGate(me: MeResponse | null, meFailureStatus = 401) {
  const client = makeTestQueryClient();
  if (me !== null) client.setQueryData(queryKeys.auth.me(), me);
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        jsonResponse(meFailureStatus, {
          error: {
            code: meFailureStatus === 401 ? "UNAUTHENTICATED" : "FORBIDDEN",
            message: "no",
            correlationId: "c",
          },
        }),
      ),
    ),
  );
  return renderWithProviders(
    <PasswordRotationGate>
      <p>the console</p>
    </PasswordRotationGate>,
    { client, me: null, route: "/orders" },
  );
}

beforeEach(() => {
  resetPrefs();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PasswordRotationGate", () => {
  it("lets a healthy session through", () => {
    renderGate(meFixture("owner"));
    expect(screen.getByText("the console")).toBeInTheDocument();
  });

  it("replaces the whole tree with the rotation form while the flag is set", () => {
    renderGate({ ...meFixture("owner"), mustChangePassword: true });
    expect(screen.queryByText("the console")).not.toBeInTheDocument();
    expect(screen.getByTestId("password-rotation-form")).toHaveAttribute("data-forced", "true");
  });

  it("leaves the console mounted on a FORBIDDEN — a 403 is not a lost session", async () => {
    renderGate(null, 403);
    await waitFor(() => {
      expect(screen.getByText("the console")).toBeInTheDocument();
    });
  });

  it("stops rendering the console once the session is gone", async () => {
    renderGate(null, 401);
    await waitFor(() => {
      expect(screen.queryByText("the console")).not.toBeInTheDocument();
    });
  });
});
