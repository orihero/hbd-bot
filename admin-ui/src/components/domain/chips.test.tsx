/**
 * The three reference chips.
 *
 * The one that matters is `<TelegramUserChip>`: §12.3 masks `telegram_user_id` at every
 * role, and contract D10 ships the unmasked integer alongside it ONLY so a link can be
 * built. This test is the thing standing between that integer and a screenshot.
 */

import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { EMPTY_VALUE } from "@/lib";

import { CorrelationChip } from "./CorrelationChip";
import { OrderRefChip } from "./OrderRefChip";
import { TelegramUserChip } from "./TelegramUserChip";

function renderRouted(node: ReactElement): void {
  render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("TelegramUserChip", () => {
  it("draws the masked id and never the integer", () => {
    renderRouted(<TelegramUserChip telegramUserId={123456789} telegramUserIdMasked="•••••789" />);
    const chip = screen.getByTestId("telegram-user-chip");
    expect(chip.textContent).toBe("•••••789");
    expect(document.body.textContent).not.toContain("123456789");
  });

  it("uses the integer for the href, which is what it is on the wire for", () => {
    renderRouted(<TelegramUserChip telegramUserId={123456789} telegramUserIdMasked="•••••789" />);
    expect(screen.getByTestId("telegram-user-chip")).toHaveAttribute(
      "href",
      "/users/123456789",
    );
  });

  it("flags a blocked user with a glyph and a word, not a colour alone", () => {
    renderRouted(
      <TelegramUserChip telegramUserId={1} telegramUserIdMasked="•••••1" isBlocked />,
    );
    const flag = screen.getByTestId("telegram-user-blocked");
    expect(flag).toHaveTextContent("⊘");
    expect(flag).toHaveTextContent("blocked");
  });
});

describe("OrderRefChip", () => {
  it("links through the href builder and carries the whole id in the title", () => {
    const orderId = "6f1b6c2e-1f3a-4a2b-8c9d-0e1f2a3b4c5d";
    renderRouted(<OrderRefChip orderId={orderId} />);
    const chip = screen.getByTestId("order-ref-chip");
    expect(chip).toHaveAttribute("href", `/orders/${orderId}`);
    expect(chip).toHaveAttribute("title", orderId);
    expect(chip.textContent).toBe("6f1b6c2e");
  });

  it("shows a glyph-only status pill when the surface knows the state", () => {
    renderRouted(<OrderRefChip orderId="abc" state="failed" />);
    expect(screen.getByTestId("status-pill")).toHaveAttribute("aria-label", "failed");
  });
});

describe("CorrelationChip", () => {
  const correlationId = "0123456789abcdef0123456789abcdef";

  it("shows a prefix and copies all thirty-two characters", async () => {
    // `userEvent.setup()` installs its own clipboard stub, so the spy goes in AFTER it.
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<CorrelationChip correlationId={correlationId} />);
    expect(screen.getByTestId("correlation-chip")).toHaveTextContent("01234567");
    await user.click(screen.getByTestId("correlation-chip"));
    expect(writeText).toHaveBeenCalledWith(correlationId);
  });

  it("flags an id that is not 32 hex rather than hiding it", () => {
    render(<CorrelationChip correlationId="not-a-correlation-id" />);
    const chip = screen.getByTestId("correlation-chip");
    expect(chip).toHaveTextContent("⚠");
    expect(chip.getAttribute("title")).toContain("not a 32-hex correlation id");
  });

  it("renders an em dash for a missing id, never an empty button", () => {
    render(<CorrelationChip correlationId={null} />);
    expect(screen.queryByTestId("correlation-chip")).toBeNull();
    expect(screen.getByText(EMPTY_VALUE)).toBeInTheDocument();
  });
});
