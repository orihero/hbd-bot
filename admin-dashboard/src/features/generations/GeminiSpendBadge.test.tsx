import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GeminiSpendResponse } from "@/api/dashboard";

import { GeminiSpendBadge } from "./GeminiSpendBadge";

const { geminiSpend } = vi.hoisted(() => ({ geminiSpend: vi.fn() }));

vi.mock("@/api/dashboard", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, geminiSpend };
});

const SPEND: GeminiSpendResponse = {
  today: { spentUsd: 0.24, pricedCalls: 3 },
  monthToDate: { spentUsd: 4.8, pricedCalls: 60 },
  isDepleted: false,
  depletedAt: null,
};

function renderBadge(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <GeminiSpendBadge />
    </QueryClientProvider>,
  );
}

describe("GeminiSpendBadge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("prints month-to-date spend as an estimate, with today and the song count on hover", async () => {
    geminiSpend.mockResolvedValue({ ok: true, data: SPEND });
    renderBadge();

    const label = await screen.findByText("Gemini this month ≈ $4.80 (est.)");
    const badge = label.parentElement;
    expect(badge?.getAttribute("title")).toBe(
      "today $0.24 · 60 songs this month · estimated at our per-request price",
    );
    expect(badge?.className ?? "").not.toMatch(/required/);
  });

  it("goes red and says what to do when Google is refusing for credit", async () => {
    geminiSpend.mockResolvedValue({
      ok: true,
      data: { ...SPEND, isDepleted: true, depletedAt: "2026-09-30T09:12:00Z" },
    });
    renderBadge();

    const label = await screen.findByText(
      "Gemini out of credit — renders fail over to ElevenLabs. Top up in AI Studio.",
    );
    expect(label.parentElement?.className ?? "").toMatch(/required/);
  });

  it("offers no control to change anything", async () => {
    geminiSpend.mockResolvedValue({ ok: true, data: SPEND });
    renderBadge();

    await screen.findByText("Gemini this month ≈ $4.80 (est.)");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
