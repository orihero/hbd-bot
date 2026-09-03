/**
 * The feed and the config field.
 *
 * The feed's non-obvious requirement is that an empty one must not read as "nothing
 * happened": §11.5 says a REPLAYED order emits zero progress events, so silence in this
 * component is silence in the record, not silence in the world.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useFeedStore, type FeedEvent } from "@/lib";

import { ConfigField, SECRET_ABSENT_VALUE } from "./ConfigField";
import { LiveFeed } from "./LiveFeed";

const EVENTS: readonly FeedEvent[] = [
  {
    id: "e1",
    at: "2026-05-01T09:00:00Z",
    label: "order failed",
    severity: "error",
    orderId: "6f1b6c2e-1f3a-4a2b-8c9d-0e1f2a3b4c5d",
    correlationId: "0123456789abcdef0123456789abcdef",
  },
  {
    id: "e2",
    at: "2026-05-01T08:59:00Z",
    label: "order delivered",
    severity: "info",
    orderId: null,
    correlationId: null,
  },
];

function renderFeed(events?: readonly FeedEvent[]): void {
  render(
    <MemoryRouter>
      {events === undefined ? <LiveFeed /> : <LiveFeed events={events} />}
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useFeedStore.setState({ events: [], buffered: [], isPaused: false, severityFilter: null });
});

describe("LiveFeed", () => {
  it("says 'nothing recorded yet' — not 'nothing happened'", () => {
    renderFeed([]);
    expect(screen.getByTestId("live-feed-empty")).toHaveTextContent("nothing recorded yet");
  });

  it("renders each event with its glyph, its zoned timestamp and its references", () => {
    renderFeed(EVENTS);
    const rows = screen.getAllByTestId("live-feed-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("✗");
    expect(rows[0]).toHaveTextContent("2026-05-01 09:00Z");
    expect(rows[0]).toHaveTextContent("order failed");
    expect(screen.getAllByTestId("order-ref-chip")).toHaveLength(1);
    expect(screen.getAllByTestId("correlation-chip")).toHaveLength(1);
  });

  it("reads the store when no events are passed", () => {
    useFeedStore.getState().ingest(EVENTS);
    renderFeed();
    expect(screen.getAllByTestId("live-feed-row")).toHaveLength(2);
  });

  it("pauses, and keeps saying how many arrivals are being held", async () => {
    const user = userEvent.setup();
    useFeedStore.getState().ingest([EVENTS[0]!]);
    renderFeed();
    await user.click(screen.getByTestId("live-feed-pause"));
    // Outside `act`, a store write lands but React has not flushed the re-render yet.
    act(() => {
      useFeedStore.getState().ingest([EVENTS[1]!]);
    });
    // The visible list has not moved...
    expect(screen.getAllByTestId("live-feed-row")).toHaveLength(1);
    // ...and the held count is on screen, so the feed cannot be mistaken for a quiet one.
    expect(screen.getByTestId("live-feed-buffered")).toHaveTextContent("1 event held while paused");
    await user.click(screen.getByTestId("live-feed-buffered"));
    expect(screen.getAllByTestId("live-feed-row")).toHaveLength(2);
  });
});

describe("ConfigField", () => {
  it("renders a secret as absent, never as an empty value", () => {
    render(<ConfigField name="adminAuditHmacKey" tier="secret-absent" />);
    const value = screen.getByTestId("config-value");
    expect(value.textContent).toBe(SECRET_ABSENT_VALUE);
    expect(value.textContent).not.toBe("");
  });

  it("distinguishes the four tiers by glyph and word, not by colour alone", () => {
    const tiers = [
      ["live", "live editable"],
      ["after-fix", "after a named fix"],
      ["read-only", "restart only"],
      ["secret-absent", "not shown"],
    ] as const;
    for (const [tier, label] of tiers) {
      const { unmount } = render(<ConfigField name="x" tier={tier} value="v" />);
      expect(screen.getByTestId("config-tier")).toHaveTextContent(label);
      unmount();
    }
  });

  it("says when a change takes hold and what a Tier 2 field is waiting on", () => {
    render(
      <ConfigField
        name="kitPriceAmountMinor"
        tier="after-fix"
        value="49000"
        effect="next order"
        note="waiting on BotDeps holding the settings holder"
      />,
    );
    const field = screen.getByTestId("config-field");
    expect(field).toHaveTextContent("takes hold: next order");
    expect(field).toHaveTextContent("waiting on BotDeps");
  });
});
