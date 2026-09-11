/**
 * The two traps `/audit/verify` sets, as tests.
 *
 * 1. A clean `ok: true` with `isComplete: false` is not a clean answer over the log. The
 *    verb has to change, or an operator reads "chain holds" about 10,000 rows out of a
 *    million as if it were about the million.
 * 2. `chainProtection` is rendered VERBATIM. `"hmac-only"` is what the server reports when
 *    `BAYRAM_ADMIN_AUDIT_DSN` is empty and the migration therefore skipped the `REVOKE` — a
 *    control that is not deployed is reported as not deployed, not humanised into a phrase
 *    that could be either.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ChainVerifyResponse } from "@/api";

import { ChainVerifyPanel } from "./ChainVerifyPanel";

function verify(overrides: Partial<ChainVerifyResponse> = {}): ChainVerifyResponse {
  return {
    ok: true,
    firstBreakSeq: null,
    chainProtection: "revoke+hmac",
    checkedRows: 4_210,
    lastSeq: 4_210,
    isComplete: true,
    truncationPoints: [],
    ...overrides,
  };
}

describe("ChainVerifyPanel", () => {
  it("says the chain holds when the walk was complete", () => {
    render(<ChainVerifyPanel verify={verify()} />);
    expect(screen.getByText("chain holds")).toBeInTheDocument();
  });

  it("qualifies the verdict when the walk hit its row ceiling", () => {
    render(<ChainVerifyPanel verify={verify({ isComplete: false, checkedRows: 10_000 })} />);
    expect(screen.getByText("chain holds over the rows checked")).toBeInTheDocument();
    expect(screen.queryByText("chain holds")).not.toBeInTheDocument();
    expect(screen.getByText(/stopped at the row ceiling/)).toBeInTheDocument();
  });

  it("names the first break when the chain does not hold", () => {
    render(<ChainVerifyPanel verify={verify({ ok: false, firstBreakSeq: 812 })} />);
    expect(screen.getByText("chain broken")).toBeInTheDocument();
    expect(screen.getByText("seq 812")).toBeInTheDocument();
  });

  it("renders chainProtection verbatim, hmac-only included", () => {
    render(<ChainVerifyPanel verify={verify({ chainProtection: "hmac-only" })} />);
    const protection = screen.getByTestId("chain-protection");
    expect(protection).toHaveTextContent("hmac-only");
    expect(protection).toHaveTextContent(/REVOKE is not deployed/);
  });

  it("says a truncation point is not a break", () => {
    render(<ChainVerifyPanel verify={verify({ truncationPoints: [17, 240] })} />);
    expect(screen.getByTestId("chain-truncation-points")).toHaveTextContent(
      /deleted on purpose by the retention sweep/,
    );
  });
});
