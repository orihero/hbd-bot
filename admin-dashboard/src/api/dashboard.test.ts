import { afterEach, describe, expect, it, vi } from "vitest";

import { geminiSpend, type GeminiSpendResponse } from "@/api/dashboard";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("GET /api/metrics/gemini-spend", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads today and month-to-date, with no query string", async () => {
    const payload: GeminiSpendResponse = {
      today: { spentUsd: 0.24, pricedCalls: 3 },
      monthToDate: { spentUsd: 4.8, pricedCalls: 60 },
      isDepleted: false,
      depletedAt: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    const result = await geminiSpend();
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/metrics/gemini-spend",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("carries the depleted flag and its instant", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        today: { spentUsd: 0, pricedCalls: 0 },
        monthToDate: { spentUsd: 9.6, pricedCalls: 120 },
        isDepleted: true,
        depletedAt: "2026-09-30T09:12:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await geminiSpend();
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.isDepleted).toBe(true);
    expect(result.data.depletedAt).toBe("2026-09-30T09:12:00Z");
  });

  it("reports schema drift when a period is missing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ today: { spentUsd: 0, pricedCalls: 0 }, isDepleted: false, depletedAt: null }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await geminiSpend();
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("SCHEMA_DRIFT");
  });
});
