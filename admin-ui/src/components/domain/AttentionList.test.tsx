/**
 * The list is an opinion about consequence, and the tests pin the opinion.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AttentionList } from "./AttentionList";
import { makeOrder, NAME_GULOM } from "./fixtures";

const NOW = Date.parse("2026-05-01T12:00:00Z");

function renderList(orders: ReturnType<typeof makeOrder>[]): void {
  render(
    <MemoryRouter>
      <AttentionList orders={orders} now={NOW} />
    </MemoryRouter>,
  );
}

describe("what gets on the list", () => {
  it("drops delivered and cancelled orders — they need no attention", () => {
    renderList([
      makeOrder({ id: "d", state: "delivered" }),
      makeOrder({ id: "c", state: "cancelled" }),
    ]);
    expect(screen.getByTestId("attention-list-empty")).toBeInTheDocument();
  });

  it("puts failures first, then in-flight orders oldest first", () => {
    renderList([
      makeOrder({ id: "young", state: "generating", updatedAt: "2026-05-01T11:59:00Z" }),
      makeOrder({ id: "old", state: "generating", updatedAt: "2026-05-01T09:00:00Z" }),
      makeOrder({
        id: "dead",
        state: "failed",
        updatedAt: "2026-05-01T11:00:00Z",
        failedReason: "MUSIC_PROVIDER_TIMEOUT",
        isFailedReasonRetryable: true,
      }),
    ]);
    const states = screen
      .getAllByTestId("attention-row")
      .map((node) => node.getAttribute("data-state"));
    expect(states).toEqual(["failed", "generating", "generating"]);
    const ids = screen
      .getAllByTestId("order-ref-chip")
      .map((node) => node.getAttribute("data-order-id"));
    expect(ids).toEqual(["dead", "old", "young"]);
  });

  it("carries the failure's code and retryability, not just the state", () => {
    renderList([
      makeOrder({
        state: "failed",
        failedReason: "LYRICS_REJECTED",
        isFailedReasonRetryable: false,
      }),
    ]);
    const badge = screen.getByTestId("error-code-badge");
    expect(badge).toHaveTextContent("LYRICS_REJECTED");
    expect(badge).toHaveTextContent("terminal");
  });
});

describe("what it draws for each row", () => {
  it("renders the recipient name through NameText, unmangled", () => {
    renderList([makeOrder({ state: "generating", recipientName: NAME_GULOM })]);
    const name = screen.getByTestId("name-text");
    expect(name.textContent).toBe(NAME_GULOM);
    expect(name.textContent?.codePointAt(1)).toBe(0x02bb);
  });

  it("renders a purged identity as a purge stamp rather than a blank", () => {
    renderList([
      makeOrder({
        state: "failed",
        recipientName: null,
        isIdentityPurged: true,
        identityPurgedAt: "2026-05-14T02:00:00Z",
      }),
    ]);
    expect(screen.getByTestId("purged-value").textContent).toBe("🔒 purged 2026-05-14identity clock");
  });

  it("masks the telegram id and links on the integer", () => {
    renderList([makeOrder({ state: "generating" })]);
    expect(screen.getByTestId("telegram-user-chip").textContent).toBe("•••••789");
    expect(document.body.textContent).not.toContain("123456789");
  });

  it("honours the limit rather than growing past the fold", () => {
    const orders = Array.from({ length: 12 }, (_, index) =>
      makeOrder({ id: `order-${String(index)}`, state: "generating" }),
    );
    render(
      <MemoryRouter>
        <AttentionList orders={orders} now={NOW} limit={3} />
      </MemoryRouter>,
    );
    expect(screen.getAllByTestId("attention-row")).toHaveLength(3);
  });
});
