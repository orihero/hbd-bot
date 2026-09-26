import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminAccountView, AdminRoster } from "@/api/admins";
import type { ApiFailure } from "@/api/client";
import { AdminsScreen } from "@/features/admins/AdminsScreen";
import { useAuthStore } from "@/state/auth";

/**
 * The roster screen's one write: adding an operator.
 *
 * Four things have to hold for the button to be honest about what it can do, and each gets a
 * test here:
 *
 * 1. **It is OWNER's alone.** `ADMIN_MANAGE_WRITE` has one cell, so a button drawn for anybody
 *    else is a `FORBIDDEN` and an audit row for an operator who did nothing wrong.
 * 2. **The username reaches the wire exactly as it was re-authenticated for.** It is the
 *    step-up subject — there is no id yet — so the field lowercases as it is typed and the body
 *    carries that same string.
 * 3. **A `STEP_UP_REQUIRED` is recovered, not reported.** The refusal opens the password prompt
 *    and, once the grant lands, the IDENTICAL body goes again: the server has no memory of the
 *    request it refused.
 * 4. **The success says what the panel cannot do.** The password still has to be handed over
 *    out of band and replaced at first sign-in, and that line is the only place it is said.
 */

const { listAdmins, createAdmin, stepUp } = vi.hoisted(() => ({
  listAdmins: vi.fn(),
  createAdmin: vi.fn(),
  stepUp: vi.fn(),
}));

/* Only the fetchers are replaced. `importOriginal` keeps every schema and helper the screen
   reads — `ADMIN_USERNAME_PATTERN` among them — so the form is held to the real contract. */
vi.mock("@/api/admins", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listAdmins, createAdmin };
});

vi.mock("@/api/reveal", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, stepUp };
});

const OWNER_ROW: AdminAccountView = {
  id: "00000000-0000-4000-8000-000000000001",
  username: "owner",
  role: "owner",
  isActive: true,
  mustChangePassword: false,
  lastLoginAt: "2026-09-01T09:00:00Z",
  passwordChangedAt: "2026-08-01T09:00:00Z",
  createdAt: "2026-08-01T09:00:00Z",
};

const ROSTER: AdminRoster = { items: [OWNER_ROW] };

/** What the server answers for the account the form asks for. */
const CREATED: AdminAccountView = {
  id: "00000000-0000-4000-8000-000000000002",
  username: "dilnoza",
  role: "support",
  isActive: true,
  mustChangePassword: true,
  lastLoginAt: null,
  passwordChangedAt: "2026-09-10T09:00:00Z",
  createdAt: "2026-09-10T09:00:00Z",
};

/**
 * The refusal the handler raises before anything is written — carrying the remedy in
 * `details`, which is the only place the scope to ask for exists.
 */
const STEP_UP_REFUSAL: ApiFailure = {
  ok: false,
  code: "STEP_UP_REQUIRED",
  message: "re-authenticate for this action and this subject",
  status: 403,
  endpoint: "POST /api/admins",
  correlationId: "c0ffee",
  issues: null,
  details: { stepUpAction: "admin.manage", subjectId: "dilnoza" },
  retryAfterS: null,
};

function renderScreen(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/admins"]}>
        <AdminsScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function signedInAs(role: "owner" | "admin"): void {
  useAuthStore.setState({
    account: {
      id: "00000000-0000-4000-8000-00000000000f",
      username: role,
      role,
      lastLoginAt: null,
      mustChangePassword: false,
    },
  });
}

/** Fill the form the way an operator does, and press the button that sends it. */
async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, name: string): Promise<void> {
  await user.type(screen.getByTestId("create-admin-username"), name);
  await user.type(screen.getByTestId("create-admin-password"), "a-password-nobody-chose");
  await user.selectOptions(screen.getByTestId("create-admin-role"), "support");
  await user.selectOptions(screen.getByTestId("reason-code"), "routine_ops");
  await user.click(screen.getByRole("button", { name: /^Create dilnoza$/ }));
}

beforeEach(() => {
  listAdmins.mockResolvedValue({ ok: true, data: ROSTER });
  createAdmin.mockResolvedValue({ ok: true, data: CREATED });
  stepUp.mockResolvedValue({
    ok: true,
    data: {
      scope: "admin.manage:dilnoza",
      grantedAt: "2026-09-10T09:00:00Z",
      expiresAt: "2026-09-10T09:05:00Z",
    },
  });
  signedInAs("owner");
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("AdminsScreen — who may add an operator", () => {
  it("offers the button to an OWNER", async () => {
    renderScreen();

    expect(await screen.findByRole("button", { name: /New operator/ })).toBeTruthy();
  });

  it("does not draw it for a role whose only answer would be a 403", async () => {
    // `ADMIN_MANAGE_WRITE` is OWNER's alone. A button here would spend an audit row to tell an
    // ADMIN something this bundle already knows.
    signedInAs("admin");
    renderScreen();

    await waitFor(() => {
      expect(listAdmins).toHaveBeenCalled();
    });
    expect(screen.queryByRole("button", { name: /New operator/ })).toBeNull();
  });
});

describe("AdminsScreen — creating an operator", () => {
  it("sends the username exactly as it was typed, lowercased, with the reason", async () => {
    const user = userEvent.setup();
    renderScreen();
    await user.click(await screen.findByRole("button", { name: /New operator/ }));

    // Typed with a capital: the field holds the spelling the step-up will be taken for, and a
    // scope is compared byte for byte.
    await fillAndSubmit(user, "Dilnoza");

    await waitFor(() => {
      expect(createAdmin).toHaveBeenCalled();
    });
    expect(createAdmin.mock.calls[0]?.[0]).toEqual({
      username: "dilnoza",
      password: "a-password-nobody-chose",
      role: "support",
      reasonCode: "routine_ops",
    });
  });

  it("answers a step-up refusal with the prompt, then replays the identical body", async () => {
    const user = userEvent.setup();
    createAdmin
      .mockResolvedValueOnce(STEP_UP_REFUSAL)
      .mockResolvedValueOnce({ ok: true, data: CREATED });
    renderScreen();
    await user.click(await screen.findByRole("button", { name: /New operator/ }));
    await fillAndSubmit(user, "dilnoza");

    // The password prompt, not a red banner: the refusal is a thing the operator can fix.
    const password = await screen.findByLabelText(/password/i);
    await user.type(password, "the-owners-own-password");
    await user.click(screen.getByRole("button", { name: /Re-authenticate|Confirm|Continue/i }));

    await waitFor(() => {
      expect(createAdmin).toHaveBeenCalledTimes(2);
    });
    // Byte-identical. A body rebuilt between the two attempts is a different subject and a
    // second refusal.
    expect(createAdmin.mock.calls[1]?.[0]).toEqual(createAdmin.mock.calls[0]?.[0]);
    // The grant was asked for with the subject the REFUSAL named, never a re-spelling.
    expect(stepUp.mock.calls[0]?.[0]).toMatchObject({
      scope: "admin.manage",
      subjectId: "dilnoza",
    });
  });

  it("says the password still has to be handed over and replaced", async () => {
    const user = userEvent.setup();
    renderScreen();
    await user.click(await screen.findByRole("button", { name: /New operator/ }));
    await fillAndSubmit(user, "dilnoza");

    // The one part of this flow the panel cannot do, said where the answer lands.
    expect(await screen.findByText(/dilnoza was created/i)).toBeTruthy();
    expect(screen.getByText(/replace it at first sign-in/i)).toBeTruthy();
  });
});
