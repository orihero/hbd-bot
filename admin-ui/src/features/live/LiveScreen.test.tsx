import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NOT_INSTRUMENTED_LABEL, SOURCE_UNAVAILABLE_LABEL, type PulseView } from "@/api";
import { makeOrder } from "@/components/domain/fixtures";
import {
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys, useFeedStore } from "@/lib";

import { LiveScreen } from "./LiveScreen";
import { rollingWindow } from "./liveMetrics";
import { LIVE_ORDERS_QUERY } from "./useLiveOps";

const NOW = Date.parse("2026-09-02T12:00:30Z");

/** A `StatTile` is an `<article>` with its label as the heading; the element carries no
 *  accessible name of its own, so the heading is the handle. */
function tileNamed(label: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: label });
  const tile = heading.closest("article");
  if (tile === null) throw new Error(`no tile for ${label}`);
  return tile;
}

function pulseFixture(overrides: Partial<PulseView> = {}): PulseView {
  return {
    delivery: {
      total: 400,
      delivered: 360,
      failed: 30,
      cancelled: 5,
      inFlight: 5,
      terminalCount: 395,
      successRate: 360 / 395,
    },
    latency: { sampleCount: 42, p50Seconds: 96, p95Seconds: 240 },
    failures: [
      { errorCode: "MUSIC_PROVIDER_TIMEOUT", count: 18, share: 0.6, isRetryable: true },
      { errorCode: null, count: 12, share: 0.4, isRetryable: null },
    ],
    capabilities: {
      isCostTelemetry: false,
      isLatencyTelemetry: false,
      isAssetStorageKeyRecorded: false,
      isChatCapture: false,
      isPaymentLedger: false,
      isStateTransitionLog: false,
    },
    ...overrides,
  };
}

function renderLive(days: readonly { day: string; total: number; delivered: number; failed: number; paid: number }[]) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.ops.pulse(), pulseFixture());
  client.setQueryData(queryKeys.metrics.ordersByDay(rollingWindow(NOW)), days);
  client.setQueryData(queryKeys.orders.list(LIVE_ORDERS_QUERY), {
    items: [
      makeOrder({ id: "11111111-1111-4111-8111-111111111111", state: "generating" }),
      makeOrder({
        id: "22222222-2222-4222-8222-222222222222",
        state: "failed",
        failedReason: "MUSIC_PROVIDER_TIMEOUT",
        isFailedReasonRetryable: true,
      }),
    ],
    meta: { nextCursor: null, total: null, isTotalExact: null },
  });
  return renderWithProviders(<LiveScreen />, { client });
}

describe("LiveScreen", () => {
  beforeEach(() => {
    resetPrefs();
    useFeedStore.getState().clear();
    vi.spyOn(Date, "now").mockReturnValue(NOW);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the 24 h delivery rate as the one hero-sized figure", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);

    const hero = tileNamed("24 h delivery success");
    expect(hero).toHaveAttribute("data-size", "hero");
    expect(hero).toHaveTextContent("94.7%");
    // Exactly one 44px figure on the screen — §11.2's dominant signal is singular.
    expect(
      document.querySelectorAll('[data-size="hero"]'),
    ).toHaveLength(1);
  });

  it("applies §11.2's colour rule and prints the band's word beside it", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);
    // 18/19 = 94.7% → amber.
    const hero = tileNamed("24 h delivery success");
    expect(hero).toHaveAttribute("data-band", "warn");
    expect(hero).toHaveTextContent("at risk");
  });

  it("goes red under 85% and green at or over 95%", () => {
    const bad = renderLive([{ day: "2026-09-02", total: 20, delivered: 8, failed: 2, paid: 10 }]);
    expect(tileNamed("24 h delivery success")).toHaveAttribute(
      "data-band",
      "bad",
    );
    bad.unmount();

    renderLive([{ day: "2026-09-02", total: 20, delivered: 19, failed: 1, paid: 20 }]);
    expect(tileNamed("24 h delivery success")).toHaveAttribute(
      "data-band",
      "good",
    );
  });

  it("shows `no data` rather than a red 0% on a quiet window", () => {
    renderLive([{ day: "2026-09-02", total: 3, delivered: 0, failed: 0, paid: 0 }]);
    const hero = tileNamed("24 h delivery success");
    expect(hero).toHaveAttribute("data-band", "unknown");
    expect(hero).toHaveTextContent("no data");
    expect(hero).not.toHaveTextContent("0.0%");
  });

  it("puts in-flight beside it with a pulsing ring", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);
    const inFlight = tileNamed("in flight");
    expect(inFlight).toHaveTextContent("5");
    expect(inFlight.querySelector(".animate-pulse-ring")).not.toBeNull();
  });

  it("feeds the live feed from the orders poll, since /ops/feed does not exist", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);
    expect(screen.getAllByTestId("live-feed-row").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("live-feed-empty")).toBeNull();
  });

  it("lists the orders that need attention, failures first", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);
    const rows = screen.getAllByTestId("attention-row");
    expect(rows[0]).toHaveAttribute("data-state", "failed");
  });

  it("says which questions this deployment cannot answer, rather than showing a zero", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);
    const chat = screen.getByText("chat capture").closest("[data-capability]");
    expect(chat).toHaveAttribute("data-enabled", "false");
    expect(chat).toHaveTextContent(SOURCE_UNAVAILABLE_LABEL);

    const cost = screen.getByText("cost telemetry").closest("[data-capability]");
    expect(cost).toHaveTextContent(NOT_INSTRUMENTED_LABEL);
  });

  it("renders the failure mix with tri-state retryability", () => {
    renderLive([{ day: "2026-09-02", total: 20, delivered: 18, failed: 1, paid: 19 }]);
    const badges = screen.getAllByTestId("error-code-badge");
    // The `errorCode: null` group is still a badge, never a blank.
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });
});
