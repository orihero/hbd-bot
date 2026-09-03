/**
 * `/admins` — the two obligations §11.2 puts on this screen, plus the two RBAC puts on it.
 *
 * **Every test here goes through `fetch`.** An earlier version seeded the roster into the
 * query cache and rendered it as an OWNER, which was green while asserting nothing about the
 * request the screen actually makes. The bodies below are the ones the server really sends,
 * parsed by the real client through the real schema.
 *
 * Two outcomes, and they must stay apart — the server's own router test says the same thing
 * from the other side:
 *
 *  - **OWNER** holds `admin.read` (§6.8 line 949: `| GET | /admins | List | W |`, no `+S`).
 *    The request goes out and the roster renders. No step-up is asked for on the way, so the
 *    screen must not draw an affordance for one, and nothing may reach `/auth/step-up`.
 *  - **VIEWER / SUPPORT / ADMIN** hold no cell at all. They must not cause a request: a 403
 *    `FORBIDDEN` writes a `permission.denied` audit row, and opening a pasted URL should not
 *    put one in the log. Asserted on `fetch` never being called — the rendering is a
 *    consequence, the silence is the requirement.
 *
 * `admin.manage` is the *other* row, `W+S`, and it guards the four account writes that are
 * not in this build. Nothing on this screen asks for it.
 */

import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminAccountView, AdminRole } from "@/api";
import {
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";

import { AdminsScreen } from "./AdminsScreen";

const CORRELATION_ID = "5c1ce1dfa1b2496fa1f0a90dcbb0f0aa";

function account(overrides: Partial<AdminAccountView> = {}): AdminAccountView {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    username: "operator",
    role: "admin",
    isActive: true,
    mustChangePassword: false,
    lastLoginAt: "2026-09-01T09:15:00Z",
    passwordChangedAt: "2026-01-05T09:15:00Z",
    createdAt: "2026-01-01T09:15:00Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "X-Correlation-ID": CORRELATION_ID },
  });
}

/** Install a `fetch` that answers `/api/admins` with `response` and nothing else. */
function stubFetch(response: () => Response): ReturnType<typeof vi.fn> {
  const spy = vi.fn((input: unknown) => {
    const url = String(input);
    if (url.includes("/api/admins")) return Promise.resolve(response());
    throw new Error(`unexpected request in this test: ${url}`);
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function renderScreen(role: AdminRole = "owner") {
  return renderWithProviders(<AdminsScreen />, {
    client: makeTestQueryClient(),
    me: { ...meFixture(role), role },
    route: "/admins",
  });
}

/** Render as an OWNER against the roster the server sends. */
async function renderRoster(items: readonly AdminAccountView[]) {
  stubFetch(() => jsonResponse({ items }));
  renderScreen("owner");
  await screen.findByRole("table", { name: "Operator accounts" });
}

beforeEach(() => {
  resetPrefs();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AdminsScreen — what an OWNER gets", () => {
  it("loads the roster: `admin.read` carries no step-up, so the request just succeeds", async () => {
    const fetchSpy = stubFetch(() => jsonResponse({ items: [account({ username: "operator" })] }));

    renderScreen("owner");

    expect(await screen.findByRole("table", { name: "Operator accounts" })).toBeInTheDocument();
    expect(screen.getByText("operator")).toBeInTheDocument();
    expect(fetchSpy.mock.calls.map((call) => String(call[0]))).toContainEqual(
      expect.stringContaining("/api/admins"),
    );
  });

  it("asks for no step-up on the way, so no confirmation affordance is drawn", async () => {
    const fetchSpy = stubFetch(() => jsonResponse({ items: [account()] }));

    renderScreen("owner");
    await screen.findByRole("table", { name: "Operator accounts" });

    // Absent, not disabled: this read never carries a `+S`, and an affordance for one would
    // spend a re-auth budget slot and write a `STEP_UP_SUCCESS` audit row to buy nothing.
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm|step.?up|re-?authenticate/i })).toBeNull();
    for (const call of fetchSpy.mock.calls) {
      expect(String(call[0])).not.toContain("/auth/step-up");
    }
  });

  it("reports a refusal through the ordinary error arm rather than a screen of its own", async () => {
    // A 403 here would mean the server had moved the roster back onto `ADMIN_MANAGE`'s
    // `W+S` cell. The screen does not explain that away in prose; it reports it like any
    // other failure, correlation id and all.
    stubFetch(() =>
      jsonResponse(
        {
          error: {
            code: "STEP_UP_REQUIRED",
            message: "your role does not allow this",
            correlationId: CORRELATION_ID,
            details: { permission: "admin.manage" },
          },
        },
        403,
      ),
    );

    renderScreen("owner");

    expect(await screen.findByText(CORRELATION_ID)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Operator accounts" })).not.toBeInTheDocument();
  });
});

describe("AdminsScreen — a role with no admin.read cell", () => {
  it.each<AdminRole>(["viewer", "support", "admin"])(
    "refuses a %s WITHOUT making the request that would log a refusal",
    async (role) => {
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);

      renderScreen(role);

      expect(screen.getByTestId("admins-forbidden")).toBeInTheDocument();
      expect(screen.queryByText("operator")).not.toBeInTheDocument();
      // Given a moment for an effect to fire a request it should never fire.
      await waitFor(() => {
        expect(fetchSpy).not.toHaveBeenCalled();
      });
    },
  );

  it("explains the denial rather than showing a generic error or a greyed-out roster", () => {
    vi.stubGlobal("fetch", vi.fn());

    renderScreen("support");

    const panel = screen.getByTestId("admins-forbidden");
    expect(within(panel).getByText(/owner capability/i)).toBeInTheDocument();
    expect(within(panel).getByText("admin.read")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("AdminsScreen — the roster it renders", () => {
  it("answers §11.2's signal: active count and last-login recency", async () => {
    await renderRoster([
      account({ id: "aaaaaaaa-0000-4000-8000-000000000001", username: "one" }),
      account({ id: "aaaaaaaa-0000-4000-8000-000000000002", username: "two", isActive: false }),
    ]);

    const signal = screen.getByTestId("admins-signal");
    expect(within(signal).getByText("active accounts")).toBeInTheDocument();
    expect(within(signal).getByText("1")).toBeInTheDocument();
    expect(within(signal).getByText("most recent sign-in")).toBeInTheDocument();
    expect(within(signal).getByText(/1 deactivated/)).toBeInTheDocument();
  });

  it("lists a deactivated account instead of omitting it", async () => {
    await renderRoster([
      account({ id: "aaaaaaaa-0000-4000-8000-000000000002", username: "departed", isActive: false }),
    ]);

    expect(screen.getByText("departed")).toBeInTheDocument();
    expect(screen.getByText("deactivated")).toBeInTheDocument();
  });

  it("names a bootstrapped account that never rotated its temporary password", async () => {
    await renderRoster([
      account({
        id: "aaaaaaaa-0000-4000-8000-000000000002",
        username: "bootstrap",
        lastLoginAt: null,
        mustChangePassword: true,
      }),
    ]);

    const stale = screen.getByTestId("admins-stale");
    expect(within(stale).getByText("bootstrap")).toBeInTheDocument();
    expect(within(stale).getByText(/never signed in/)).toBeInTheDocument();
    expect(within(stale).getByText(/temporary password/)).toBeInTheDocument();
  });

  it("says 'never', not a blank, for an account that has not signed in", async () => {
    await renderRoster([account({ lastLoginAt: null })]);

    expect(screen.getAllByText("never").length).toBeGreaterThan(0);
  });

  it("says the roster is empty rather than blaming the reader's role", async () => {
    // An empty list is a 200: the account doing the reading should have been in it. That is
    // a deployment fact, and it must not be dressed up as a permission problem now that a
    // 403 is not what an OWNER gets here.
    await renderRoster([]);

    expect(screen.getByText("No operator accounts")).toBeInTheDocument();
    expect(screen.queryByTestId("admins-forbidden")).not.toBeInTheDocument();
  });
});
