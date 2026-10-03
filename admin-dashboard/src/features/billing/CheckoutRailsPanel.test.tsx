/**
 * The owner's per-rail sale switch (DECISIONS.md D28).
 *
 * Four properties, each one this panel would be wrong without:
 *
 * 1. **Only the owner gets a button.** `CONFIG_MANAGE` is owner-only; an admin who pressed
 *    would earn a 403 and a `permission.denied` audit row for nothing.
 * 2. **The confirm sends exactly `{rail, enabled, reasonCode}`** — and is withheld until a
 *    reason code is chosen, because a body the server refuses writes no audit row at all.
 * 3. **"Not live in env" means `wired === false`, never `null`.** Unknown is not dead.
 * 4. **A 403 renders as a plain `denied` note**, never a password box.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CheckoutRailsConfig } from "@/api/config";
import { en } from "@/i18n/locales/en";
import type { AdminRole } from "@/lib/rbac";
import { useAuthStore } from "@/state/auth";

import { CheckoutRailsPanel } from "./CheckoutRailsPanel";

const { getCheckoutRails, setCheckoutRail } = vi.hoisted(() => ({
  getCheckoutRails: vi.fn(),
  setCheckoutRail: vi.fn(),
}));

vi.mock("@/api/config", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getCheckoutRails, setCheckoutRail };
});

const ALL_ON: CheckoutRailsConfig = {
  rails: [
    { name: "rhmt", enabled: true, wired: true },
    { name: "payme", enabled: true, wired: false },
    { name: "checkoutuz", enabled: true, wired: true },
  ],
  wiredKnown: true,
};

function signIn(role: AdminRole): void {
  useAuthStore.setState({
    account: {
      id: "1",
      username: `${role}_user`,
      role,
      mustChangePassword: false,
      lastLoginAt: null,
    },
  });
}

function renderPanel(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <CheckoutRailsPanel />
    </QueryClientProvider>,
  );
}

async function rowOf(rail: string): Promise<HTMLElement> {
  return await screen.findByTestId(`checkout-rail-${rail}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  getCheckoutRails.mockResolvedValue({ ok: true, data: ALL_ON });
});

afterEach(() => {
  useAuthStore.setState({ account: null });
});

describe("CheckoutRailsPanel", () => {
  it("shows an admin the badges and no toggle", async () => {
    signIn("admin");
    renderPanel();

    const row = await rowOf("checkoutuz");
    expect(within(row).getByText("checkout.uz")).toBeInTheDocument();
    expect(within(row).getByText(en.billing.rails.on)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the owner one toggle per rail", async () => {
    signIn("owner");
    renderPanel();

    await rowOf("rhmt");
    expect(screen.getAllByRole("button", { name: /^Turn off / })).toHaveLength(3);
  });

  it("marks only a rail the env did not wire, and treats unknown as not-dead", async () => {
    signIn("admin");
    getCheckoutRails.mockResolvedValue({
      ok: true,
      data: {
        rails: [
          { name: "rhmt", enabled: true, wired: null },
          { name: "payme", enabled: false, wired: false },
        ],
        wiredKnown: false,
      },
    });
    renderPanel();

    const rhmt = await rowOf("rhmt");
    const payme = await rowOf("payme");
    expect(within(rhmt).queryByText(en.billing.rails.notWired)).not.toBeInTheDocument();
    expect(within(payme).getByText(en.billing.rails.notWired)).toBeInTheDocument();
    expect(within(payme).getByText(en.billing.rails.off)).toBeInTheDocument();
  });

  it("sends {rail, enabled, reasonCode} on confirm and redraws from the response", async () => {
    const user = userEvent.setup();
    signIn("owner");
    setCheckoutRail.mockResolvedValue({
      ok: true,
      data: {
        ...ALL_ON,
        rails: ALL_ON.rails.map((r) =>
          r.name === "checkoutuz" ? { ...r, enabled: false } : r,
        ),
      },
    });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Turn off checkout.uz" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Stop selling through checkout.uz?")).toBeInTheDocument();

    const confirm = within(dialog).getByRole("button", { name: "Turn off checkout.uz" });
    // Withheld until a reason code is chosen: a refused body writes no audit row.
    expect(confirm).toBeDisabled();
    await user.selectOptions(within(dialog).getByTestId("reason-code"), "routine_ops");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(setCheckoutRail).toHaveBeenCalledTimes(1);
    expect(setCheckoutRail).toHaveBeenCalledWith(
      expect.objectContaining({ rail: "checkoutuz", enabled: false, reasonCode: "routine_ops" }),
    );

    await waitFor(() => {
      expect(screen.queryByText("Stop selling through checkout.uz?")).not.toBeInTheDocument();
    });
    const row = await rowOf("checkoutuz");
    expect(within(row).getByText(en.billing.rails.off)).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Turn on checkout.uz" })).toBeInTheDocument();
  });

  it("renders a 403 as a denied note, not a credential prompt", async () => {
    const user = userEvent.setup();
    signIn("owner");
    setCheckoutRail.mockResolvedValue({
      ok: false,
      status: 403,
      code: "FORBIDDEN",
      message: "your role does not allow this",
      endpoint: "POST /api/config/checkout-rails",
      correlationId: "corr-1",
      issues: null,
      details: null,
      retryAfterS: null,
    });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Turn off Payme" }));
    const dialog = screen.getByRole("dialog");
    await user.selectOptions(within(dialog).getByTestId("reason-code"), "routine_ops");
    await user.click(within(dialog).getByRole("button", { name: "Turn off Payme" }));

    expect(await screen.findByText("your role does not allow this")).toBeInTheDocument();
    expect(await screen.findByText(en.billing.rails.failedTitle)).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(document.querySelector("input[type='password']")).toBeNull();
    // Nothing moved, so nothing repaints: the row still reads On.
    expect(within(await rowOf("payme")).getByText(en.billing.rails.on)).toBeInTheDocument();
  });
});
