import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MusicProviderConfig } from "@/api/config";
import { MusicProviderSwitch } from "./MusicProviderSwitch";
import { useAuthStore } from "@/state/auth";

const { getMusicProviderConfig, setMusicProviderConfig } = vi.hoisted(() => ({
  getMusicProviderConfig: vi.fn(),
  setMusicProviderConfig: vi.fn(),
}));

vi.mock("@/api/config", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getMusicProviderConfig, setMusicProviderConfig };
});

const DEFAULT_CONFIG: MusicProviderConfig = {
  activeProvider: "elevenlabs_music",
  defaultProvider: "elevenlabs_music",
  availableProviders: ["elevenlabs_music", "gemini_music"],
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
      <MusicProviderSwitch />
    </QueryClientProvider>,
  );
}

describe("MusicProviderSwitch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMusicProviderConfig.mockResolvedValue({
      ok: true,
      data: DEFAULT_CONFIG,
    });
  });

  afterEach(() => {
    useAuthStore.setState({ account: null });
  });

  it("renders active provider badge without change button for non-owner roles", async () => {
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
      expect(screen.getByText("ElevenLabs")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /change/i })).not.toBeInTheDocument();
  });

  it("renders change button for owner role and allows switching provider", async () => {
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

    setMusicProviderConfig.mockResolvedValue({
      ok: true,
      data: {
        activeProvider: "gemini_music",
        defaultProvider: "elevenlabs_music",
        availableProviders: ["elevenlabs_music", "gemini_music"],
      },
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("ElevenLabs")).toBeInTheDocument();
    });

    const changeButton = screen.getByRole("button", { name: /change/i });
    expect(changeButton).toBeInTheDocument();
    await user.click(changeButton);

    // Dialog opens
    expect(screen.getByText("Change Music Provider")).toBeInTheDocument();
    expect(screen.getByText("Select provider")).toBeInTheDocument();

    // Select reason code
    const reasonSelect = screen.getByTestId("reason-code");
    await user.selectOptions(reasonSelect, "routine_ops");

    // Click confirm button
    const confirmButton = screen.getByRole("button", { name: /switch to gemini/i });
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);

    expect(setMusicProviderConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: "gemini_music",
        reasonCode: "routine_ops",
      }),
    );

    // Dialog closes and provider badge is updated to Gemini
    await waitFor(() => {
      expect(screen.queryByText("Change Music Provider")).not.toBeInTheDocument();
      expect(screen.getByText("Gemini")).toBeInTheDocument();
    });
  });
});
