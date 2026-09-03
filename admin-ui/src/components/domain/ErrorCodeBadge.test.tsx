/**
 * Retryability is three states. The third one is an ABSENT decision, and rendering it as
 * "terminal" is how an operator abandons an order that would have gone through.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UNKNOWN_RETRYABILITY_LABEL } from "@/api";
import { EMPTY_VALUE } from "@/lib";

import { ErrorCodeBadge } from "./ErrorCodeBadge";

describe("the one glyph the operator decides on", () => {
  it("renders ↻ retryable in the caution hue", () => {
    render(<ErrorCodeBadge code="MUSIC_PROVIDER_TIMEOUT" isRetryable />);
    const badge = screen.getByTestId("error-code-badge");
    expect(badge).toHaveTextContent("↻");
    expect(badge).toHaveTextContent("retryable");
    // The reskin split the hue in two: the capsule ground is the tint, the glyph and the
    // word beside it are the text-safe member. Both are asserted, because either drifting
    // alone would leave the badge naming one decision and colouring another.
    expect(badge.getAttribute("style")).toContain("var(--retryable-tint)");
    expect(screen.getByTestId("error-code-retryability").getAttribute("style")).toContain(
      "var(--retryable)",
    );
  });

  it("renders ■ terminal in the error hue", () => {
    render(<ErrorCodeBadge code="LYRICS_REJECTED" isRetryable={false} />);
    const badge = screen.getByTestId("error-code-badge");
    expect(badge).toHaveTextContent("■");
    expect(badge).toHaveTextContent("terminal");
    expect(badge.getAttribute("style")).toContain("var(--terminal-tint)");
    expect(screen.getByTestId("error-code-retryability").getAttribute("style")).toContain(
      "var(--terminal)",
    );
  });

  it("renders unknown for null — not terminal, and not the caution hue either", () => {
    render(<ErrorCodeBadge code="SOMETHING_NEW" isRetryable={null} />);
    const badge = screen.getByTestId("error-code-badge");
    expect(badge).toHaveTextContent(UNKNOWN_RETRYABILITY_LABEL);
    expect(badge).not.toHaveTextContent("terminal");
    expect(badge.getAttribute("style")).toContain("var(--slate-tint)");
    expect(screen.getByTestId("error-code-retryability").getAttribute("style")).toContain(
      "var(--slate)",
    );
    expect(badge).toHaveAttribute("data-retryability", "unknown");
  });

  it("keeps the code itself in --ink rather than in the decision hue", () => {
    render(<ErrorCodeBadge code="MUSIC_PROVIDER_TIMEOUT" isRetryable />);
    // The code is the longest run of characters in the badge, so it gets the token that
    // clears 4.5:1 on every tint rather than the one that only has to clear it on a card.
    expect(screen.getByTestId("error-code").className).toContain("text-ink");
    expect(screen.getByTestId("error-code").getAttribute("style")).toBeNull();
  });
});

describe("the code itself", () => {
  it("is rendered verbatim, so it still matches a grep of the worker log", () => {
    render(<ErrorCodeBadge code="MUSIC_PROVIDER_TIMEOUT" isRetryable />);
    expect(screen.getByTestId("error-code")).toHaveTextContent("MUSIC_PROVIDER_TIMEOUT");
  });

  it("still renders a badge when the writer recorded no code", () => {
    render(<ErrorCodeBadge code={null} isRetryable={null} />);
    expect(screen.getByTestId("error-code")).toHaveTextContent(EMPTY_VALUE);
    expect(screen.getByTestId("error-code-badge")).toHaveTextContent(UNKNOWN_RETRYABILITY_LABEL);
  });

  it("shows our operator prose when there is some, and nothing when there is not", () => {
    const { rerender } = render(
      <ErrorCodeBadge code="X" isRetryable={false} message="provider returned 502 three times" />,
    );
    expect(screen.getByTestId("error-code-badge")).toHaveTextContent("provider returned 502");
    rerender(<ErrorCodeBadge code="X" isRetryable={false} message={null} />);
    expect(screen.getByTestId("error-code-badge").textContent).toContain("terminal");
  });
});
