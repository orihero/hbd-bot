/**
 * §11.5's four states. The pill is a rendering of `liveStatus()` and nothing else — there is
 * no connection to be connected to, so freshness IS the connection.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/components/util/testRender";
import { LAGGING_THRESHOLD_MS, LIVE_THRESHOLD_MS, liveStatus } from "@/lib/queryClient";

import { LivePill } from "./LivePill";

const NOW = 1_800_000_000_000;

describe("LivePill", () => {
  it("is green and pulsing under 10s", () => {
    const status = liveStatus({ dataUpdatedAt: NOW - 4_000, errorCount: 0, isPaused: false, now: NOW });
    renderWithProviders(<LivePill status={status} />);
    const pill = screen.getByRole("status");
    expect(pill).toHaveTextContent("LIVE");
    expect(pill).toHaveAttribute("data-live-state", "live");
    // The hue lives on the dot, not the word — see the contrast note in LivePill.tsx. The
    // dot is a graphical object at 1.4.11's 3:1, which is what the `-fill` member clears.
    expect(pill.querySelector(".text-success-fill.animate-pulse-ring")).not.toBeNull();
  });

  it("is amber between 10 and 30 seconds", () => {
    const status = liveStatus({
      dataUpdatedAt: NOW - LIVE_THRESHOLD_MS - 4_000,
      errorCount: 0,
      isPaused: false,
      now: NOW,
    });
    const pill = renderWithProviders(<LivePill status={status} />).getByRole("status");
    expect(pill).toHaveTextContent("LAGGING");
    expect(pill).toHaveAttribute("data-live-state", "lagging");
    expect(pill.querySelector(".text-caution-fill")).not.toBeNull();
  });

  it("is amber while retrying, even when the data is fresh", () => {
    const status = liveStatus({ dataUpdatedAt: NOW - 1_000, errorCount: 1, isPaused: false, now: NOW });
    expect(status.state).toBe("lagging");
  });

  it("is red past 30 seconds and shows a countdown to the next attempt", () => {
    const status = liveStatus({
      dataUpdatedAt: NOW - LAGGING_THRESHOLD_MS - 12_000,
      errorCount: 2,
      isPaused: false,
      now: NOW,
    });
    const pill = renderWithProviders(
      <LivePill status={status} onRefresh={() => undefined} />,
    ).getByRole("button");
    expect(pill).toHaveTextContent("STALLED");
    expect(pill).toHaveTextContent(/retry \d+s/u);
    expect(pill).toHaveAttribute("data-live-state", "stalled");
    expect(pill.querySelector(".text-error-fill")).not.toBeNull();
  });

  it("offers a retry when stalled, because 'try now' is the obvious wish", async () => {
    const onRefresh = vi.fn();
    const status = liveStatus({
      dataUpdatedAt: NOW - 90_000,
      errorCount: 1,
      isPaused: false,
      now: NOW,
    });
    renderWithProviders(<LivePill status={status} onRefresh={onRefresh} />);
    await userEvent.click(screen.getByRole("button", { name: /Retry now/u }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("is slate and says PAUSED when the tab is in the background", () => {
    // Not an error: every poll is gated on visibility, so a backgrounded tab genuinely
    // stops fetching and must not greet the operator with an incident that never happened.
    const status = liveStatus({ dataUpdatedAt: NOW - 600_000, errorCount: 0, isPaused: true, now: NOW });
    const pill = renderWithProviders(<LivePill status={status} />).getByRole("status");
    expect(pill).toHaveTextContent("PAUSED");
    expect(pill).toHaveAttribute("data-live-state", "paused");
    // Slate, not neutral: the palette's cool grey is the "somebody stopped this" hue, and a
    // backgrounded tab is exactly that.
    expect(pill.querySelector(".text-slate-fill")).not.toBeNull();
    expect(pill).not.toHaveTextContent(/\d+s/u);
  });

  it("does not go red on a cold start", () => {
    const status = liveStatus({ dataUpdatedAt: 0, errorCount: 0, isPaused: false, now: NOW });
    const pill = renderWithProviders(<LivePill status={status} />).getByRole("status");
    expect(pill).toHaveTextContent("LIVE");
  });

  it("carries its state in the accessible name, not only in the hue", () => {
    const status = liveStatus({ dataUpdatedAt: NOW - 15_000, errorCount: 0, isPaused: false, now: NOW });
    renderWithProviders(<LivePill status={status} />);
    expect(screen.getByRole("status")).toHaveAccessibleName(/LAGGING/u);
  });
});
