/**
 * §11.2's dominant signal for `/generations/names`: "Per-strategy bake-off bars + a
 * similarity histogram with the threshold marked, linking straight to `/config`."
 *
 * Most of these tests are about refusing to draw a number that is arithmetically defensible
 * and operationally wrong:
 *
 *  - an empty window must not render as a measured zero, and must say WHICH window it is
 *    empty of, because the remedy (widen the range) only exists for one of the two empties;
 *  - an unpublished threshold must not render as `0`, because a cliff count of zero reads
 *    as "moving the threshold is free" and it means "nobody told the panel where the
 *    threshold is";
 *  - and the histogram must not claim to describe a window it only sampled a page of. The
 *    screen used to draw it from one `MAX_PAGE_LIMIT` page of `/api/generations` and said so
 *    in small type; it now reads one windowed endpoint that counts in the database, and the
 *    caption that hedged is gone. That is what `does not sample a page of /api/generations`
 *    pins.
 */

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiResult, NameAnalyticsView, StrategyAnalysisView, WindowQuery } from "@/api";
import type * as ApiModule from "@/api";
import { renderWithProviders, resetPrefs } from "@/components/util/testRender";

const { getNameAnalyticsMock, getGenerationsMock } = vi.hoisted(() => ({
  getNameAnalyticsMock: vi.fn(),
  getGenerationsMock: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getNameAnalytics: getNameAnalyticsMock,
  getGenerations: getGenerationsMock,
}));

const { NameStrategiesScreen, THRESHOLD_CONFIG_LINK_LABEL, THRESHOLD_UNPUBLISHED_HINT } =
  await import("./NameStrategiesScreen");

const WINDOW_FROM = "2026-03-20T00:00:00Z";
const WINDOW_TO = "2026-03-21T00:00:00Z";
const WINDOWED_ROUTE = `/generations/names?from=${WINDOW_FROM}&to=${WINDOW_TO}`;

/** Twenty half-open buckets, all empty unless a caller puts something in one. */
function emptyBuckets(): NameAnalyticsView["buckets"] {
  return Array.from({ length: 20 }, (_unused, index) => ({
    from: index / 20,
    to: (index + 1) / 20,
    count: 0,
  }));
}

function bucketsWith(entries: readonly (readonly [number, number])[]): NameAnalyticsView["buckets"] {
  const buckets = emptyBuckets();
  for (const [index, count] of entries) {
    const bucket = buckets[index];
    if (bucket !== undefined) buckets[index] = { ...bucket, count };
  }
  return buckets;
}

function strategy(
  name: StrategyAnalysisView["strategy"],
  attempts: number,
  verified: number,
  extra: Partial<StrategyAnalysisView> = {},
): StrategyAnalysisView {
  return {
    strategy: name,
    attempts,
    verified,
    verificationRate: attempts === 0 ? 0 : verified / attempts,
    scored: attempts,
    nearThreshold: 0,
    buckets: emptyBuckets(),
    ...extra,
  };
}

function analytics(overrides: Partial<NameAnalyticsView> = {}): NameAnalyticsView {
  const strategies = overrides.strategies ?? [
    strategy("canonical", 100, 92, { nearThreshold: 7 }),
    strategy("ascii", 10, 9),
    strategy("phonetic", 4, 1),
  ];
  const attempts = strategies.reduce((sum, row) => sum + row.attempts, 0);
  const verified = strategies.reduce((sum, row) => sum + row.verified, 0);
  return {
    window: { from: WINDOW_FROM, to: WINDOW_TO },
    threshold: 0.85,
    thresholdBand: 0.05,
    bucketCount: 20,
    attempts,
    verified,
    verificationRate: attempts === 0 ? null : verified / attempts,
    scored: attempts,
    nearThreshold: 9,
    hasRecordedAttempts: attempts > 0,
    buckets: bucketsWith([
      [3, 4],
      [16, 30],
      [19, 12],
    ]),
    ...overrides,
    strategies,
  };
}

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data };
}

beforeEach(() => {
  resetPrefs();
  getNameAnalyticsMock.mockReset();
  getGenerationsMock.mockReset();
  getNameAnalyticsMock.mockResolvedValue(ok(analytics()));
});

describe("NameStrategiesScreen", () => {
  it("leads with the near-threshold count — the number that says whether a move is safe", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    const signal = await screen.findByTestId("near-threshold-signal");
    expect(within(signal).getByText("9")).toBeInTheDocument();
    expect(within(signal).getByText("within ±0.05 of 0.85")).toBeInTheDocument();
    expect(within(signal).getByText(/of 114 scored attempts/)).toBeInTheDocument();
  });

  it("says the threshold is unpublished rather than showing a cliff count of zero", async () => {
    getNameAnalyticsMock.mockResolvedValue(
      ok(analytics({ threshold: null, nearThreshold: null })),
    );
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    const signal = await screen.findByTestId("near-threshold-signal");
    expect(signal).toHaveTextContent(THRESHOLD_UNPUBLISHED_HINT);
    expect(within(signal).queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("similarity-threshold-marker")).not.toBeInTheDocument();
  });

  it("draws a bake-off bar per strategy, in declaration order", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    const rows = await screen.findAllByTestId("bakeoff-row");
    expect(rows.map((row) => row.dataset["strategy"])).toEqual([
      "canonical",
      "stripped",
      "ascii",
      "cyrillic",
      "hyphenated",
      "phonetic",
    ]);
  });

  it("marks the threshold and shades the band a move would cross", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    expect(await screen.findByTestId("similarity-threshold-marker")).toBeInTheDocument();
    const band = screen.getByTestId("similarity-threshold-band");
    // 0.85 ± 0.05 → left 80%, width 10%.
    expect(band.style.left).toBe("80%");
    expect(band.style.width).toBe("10%");
  });

  it("still links straight to /config, as §11.2 requires", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    const link = await screen.findByTestId("threshold-config-link");
    expect(link).toHaveAttribute("href", "/config");
    expect(link).toHaveTextContent(THRESHOLD_CONFIG_LINK_LABEL);
  });

  it("asks the endpoint for the window that is in the URL, both bounds", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    await screen.findByTestId("similarity-histogram");
    const query = getNameAnalyticsMock.mock.calls[0]?.[0] as WindowQuery | undefined;
    expect(query).toEqual({ from: WINDOW_FROM, to: WINDOW_TO });
  });

  it("does not sample a page of /api/generations any more", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    await screen.findByTestId("similarity-histogram");
    expect(getGenerationsMock).not.toHaveBeenCalled();
    expect(screen.queryByText(/the window holds more/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("similarity-sample-note")).toHaveTextContent(
      "114 scored attempts in this window",
    );
  });

  it("renders an empty window as empty-FILTERED, naming the window, with a Clear", async () => {
    getNameAnalyticsMock.mockResolvedValue(
      ok(
        analytics({
          strategies: [],
          nearThreshold: 0,
          scored: 0,
          buckets: emptyBuckets(),
          hasRecordedAttempts: true,
        }),
      ),
    );
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    expect(await screen.findAllByText("No verification ran in this window")).not.toHaveLength(0);
    // The window itself, in the operator's chosen zone — not just "no data".
    expect(screen.getAllByText(/2026-03-20 00:00Z → 2026-03-21 00:00Z/)).not.toHaveLength(0);
    expect(screen.getAllByRole("button", { name: /clear filters/i })).not.toHaveLength(0);
  });

  it("renders a deployment where verification never ran as empty-VIRGIN, with no Clear", async () => {
    getNameAnalyticsMock.mockResolvedValue(
      ok(
        analytics({
          window: null,
          strategies: [],
          nearThreshold: 0,
          scored: 0,
          buckets: emptyBuckets(),
          hasRecordedAttempts: false,
        }),
      ),
    );
    renderWithProviders(<NameStrategiesScreen />, { route: "/generations/names" });

    expect(await screen.findAllByText("No verification has ever run here")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();
  });

  it("suggests a candidate order as a pasteable environment line", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    // canonical 92/100 → 0.92, ascii 9/10 → 0.90, phonetic 1/4 → 0.25; the three that ran
    // nothing are ABSENT from the endpoint's array and keep their declared positions last.
    const value = await screen.findByTestId("candidate-order-value");
    expect(value).toHaveTextContent(
      "BAYRAM_NAME_CANDIDATE_ORDER=canonical,ascii,phonetic,stripped,cyrillic,hyphenated",
    );
  });

  it("suggests nothing when nothing has been verified", async () => {
    getNameAnalyticsMock.mockResolvedValue(
      ok(analytics({ strategies: [], scored: 0, buckets: emptyBuckets() })),
    );
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    expect(await screen.findByText(/the current order stands/i)).toBeInTheDocument();
    expect(screen.queryByTestId("candidate-order-value")).not.toBeInTheDocument();
  });

  it("prints the denominator the overall rate was taken over", async () => {
    renderWithProviders(<NameStrategiesScreen />, { route: WINDOWED_ROUTE });

    expect(await screen.findByTestId("bakeoff-denominator")).toHaveTextContent(
      "102/114 verified in 2026-03-20 00:00Z → 2026-03-21 00:00Z",
    );
  });
});
