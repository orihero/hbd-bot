import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DurationBadge } from "./DurationBadge";

describe("DurationBadge", () => {
  it("renders green (< 1s) for fast latency", () => {
    render(<DurationBadge ms={450} />);
    const badge = screen.getByTestId("duration-badge");
    expect(badge).toHaveAttribute("data-band", "fast");
    expect(badge).toHaveTextContent("450ms");
    expect(badge).toHaveClass("bg-success-tint", "text-success");
  });

  it("renders neutral (1s - 5s) for standard duration", () => {
    render(<DurationBadge ms={2500} />);
    const badge = screen.getByTestId("duration-badge");
    expect(badge).toHaveAttribute("data-band", "neutral");
    expect(badge).toHaveTextContent("2.5s");
    expect(badge).toHaveClass("bg-surface-control", "text-ink-muted");
  });

  it("renders amber (5s - 15s) for slow operations", () => {
    render(<DurationBadge ms={9200} />);
    const badge = screen.getByTestId("duration-badge");
    expect(badge).toHaveAttribute("data-band", "slow");
    expect(badge).toHaveTextContent("9.2s");
    expect(badge).toHaveClass("bg-caution-tint", "text-caution");
  });

  it("renders red (> 15s) for critical latency", () => {
    render(<DurationBadge ms={18000} />);
    const badge = screen.getByTestId("duration-badge");
    expect(badge).toHaveAttribute("data-band", "critical");
    expect(badge).toHaveTextContent("18s");
    expect(badge).toHaveClass("bg-error-tint", "text-error");
  });

  it("renders 'not instrumented' when isInstrumented is false", () => {
    render(<DurationBadge ms={null} isInstrumented={false} />);
    expect(screen.getByTestId("duration-badge-uninstrumented")).toHaveTextContent("not instrumented");
  });

  it("renders em dash for null or undefined ms when instrumented", () => {
    render(<DurationBadge ms={null} isInstrumented={true} />);
    expect(screen.getByText("—")).toHaveAttribute("data-empty", "true");
  });
});
