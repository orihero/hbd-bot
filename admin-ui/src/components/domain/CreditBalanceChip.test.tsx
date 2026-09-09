/**
 * The one assertion this component exists for: `null` does not render as `0`.
 *
 * `credit_accounts.balance` is `NOT NULL`, so a null on the wire can only mean "no account
 * row" — a customer who was never metered, or one whose `/forget` deleted the row. Rendering
 * that as `0 credits` tells the operator the opposite: that everything granted was spent.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CreditBalanceChip } from "./CreditBalanceChip";
import { creditBalanceState, NEVER_METERED_LABEL } from "./credits";

describe("creditBalanceState", () => {
  it("puts null, zero and a positive balance in three different states", () => {
    expect(creditBalanceState(null)).toBe("never-metered");
    expect(creditBalanceState(undefined)).toBe("never-metered");
    expect(creditBalanceState(0)).toBe("spent");
    expect(creditBalanceState(3)).toBe("held");
  });
});

describe("CreditBalanceChip", () => {
  it("renders a null account differently from a balance of 0, in words and in state", () => {
    const { unmount } = render(<CreditBalanceChip balance={null} />);
    const never = screen.getByTestId("credit-balance-chip");
    const neverText = never.textContent;
    const neverState = never.getAttribute("data-state");
    unmount();

    render(<CreditBalanceChip balance={0} />);
    const spent = screen.getByTestId("credit-balance-chip");

    expect(neverText).toContain(NEVER_METERED_LABEL);
    expect(spent).toHaveTextContent("0 credits");
    expect(spent.textContent).not.toBe(neverText);
    expect(spent.getAttribute("data-state")).not.toBe(neverState);
    expect(neverState).toBe("never-metered");
    expect(spent).toHaveAttribute("data-state", "spent");
  });

  it("says how many when there are some, and gets the singular right", () => {
    const { unmount } = render(<CreditBalanceChip balance={1} />);
    expect(screen.getByTestId("credit-balance-chip")).toHaveTextContent("1 credit");
    expect(screen.getByTestId("credit-balance-chip")).toHaveAttribute("data-state", "held");
    unmount();

    render(<CreditBalanceChip balance={12} />);
    expect(screen.getByTestId("credit-balance-chip")).toHaveTextContent("12 credits");
  });

  it("carries a non-colour channel: a distinct glyph per state (§11.3)", () => {
    const glyphs = new Set<string>();
    for (const balance of [null, 0, 4] as const) {
      const { unmount } = render(<CreditBalanceChip balance={balance} />);
      const glyph = screen.getByTestId("credit-balance-chip").querySelector("[aria-hidden]");
      glyphs.add(glyph?.textContent ?? "");
      unmount();
    }

    // Three states, three glyphs — the chip survives greyscale.
    expect(glyphs.size).toBe(3);
  });

  it("explains the distinction on hover rather than only in a design document", () => {
    render(<CreditBalanceChip balance={null} />);

    expect(screen.getByTestId("credit-balance-chip").getAttribute("title")).toContain(
      "not a balance of 0",
    );
  });
});
