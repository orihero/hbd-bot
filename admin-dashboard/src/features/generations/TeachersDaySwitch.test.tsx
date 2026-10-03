import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TeachersDayConfig } from "@/api/config";
import { TeachersDaySwitch } from "./TeachersDaySwitch";
import { useAuthStore } from "@/state/auth";

const { getTeachersDayConfig, setTeachersDayConfig } = vi.hoisted(() => ({
  getTeachersDayConfig: vi.fn(),
  setTeachersDayConfig: vi.fn(),
}));

vi.mock("@/api/config", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getTeachersDayConfig, setTeachersDayConfig };
});

const DEFAULT_CONFIG: TeachersDayConfig = {
  enabled: false,
  discountPercent: 30,
};

function renderComponent(): void {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TeachersDaySwitch />
    </QueryClientProvider>,
  );
}

describe("TeachersDaySwitch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTeachersDayConfig.mockResolvedValue({
      ok: true,
      data: DEFAULT_CONFIG,
    });
  });

  afterEach(() => {
    useAuthStore.setState({ account: null });
  });

  it("renders Teachers Day status badge without button for non-owner roles", async () => {
    useAuthStore.setState({
      account: {
        id: "1",
        username: "admin_user",
        role: "admin",
        mustChangePassword: false,
        lastLoginAt: null,
      },
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Off")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /teachers' day promo/i })).not.toBeInTheDocument();
  });

  it("renders turn on button for owner role and allows enabling promo", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({
      account: {
        id: "1",
        username: "owner_user",
        role: "owner",
        mustChangePassword: false,
        lastLoginAt: null,
      },
    });

    setTeachersDayConfig.mockResolvedValue({
      ok: true,
      data: {
        enabled: true,
        discountPercent: 30,
      },
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Off")).toBeInTheDocument();
    });

    const turnOnButton = screen.getByRole("button", { name: /teachers' day promo/i });
    expect(turnOnButton).toBeInTheDocument();
    await user.click(turnOnButton);

    // Dialog opens
    expect(screen.getByText("Enable Teachers' Day Promo (-30%)")).toBeInTheDocument();

    // Select reason code
    const reasonSelect = screen.getByTestId("reason-code");
    await user.selectOptions(reasonSelect, "routine_ops");

    // Click confirm button
    const confirmButton = screen.getByRole("button", { name: /turn on promo/i });
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);

    expect(setTeachersDayConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: true,
        reasonCode: "routine_ops",
      }),
    );

    // Dialog closes and status badge is updated
    await waitFor(() => {
      expect(screen.queryByText("Enable Teachers' Day Promo (-30%)")).not.toBeInTheDocument();
      expect(screen.getByText("Active (-30%)")).toBeInTheDocument();
    });
  });
});
