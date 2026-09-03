import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("describes itself, because a trend line is unreadable without a label", () => {
    render(<Sparkline values={[1, 4, 9]} label="30-day new users" />);
    expect(
      screen.getByRole("img", { name: "30-day new users: 1 to 9 over 3 points" }),
    ).toBeInTheDocument();
  });

  it("draws a 2px round-capped line", () => {
    const { container } = render(<Sparkline values={[1, 4, 9]} label="x" />);
    const path = container.querySelector("path");
    expect(path).toHaveAttribute("stroke-width", "2");
    expect(path).toHaveAttribute("stroke-linecap", "round");
  });

  it("ends in a ≥8px marker ringed in the card colour", () => {
    const { container } = render(<Sparkline values={[1, 4, 9]} label="x" />);
    const dot = container.querySelector("circle");
    expect(dot).toHaveAttribute("r", "4");
    // The ring is whatever the sparkline is sitting ON. Every surface that hosts one is a
    // card, so `--surface-card` is what makes the marker read where it crosses its own line.
    expect(dot).toHaveAttribute("stroke", "var(--surface-card)");
    expect(dot).toHaveAttribute("stroke-width", "2");
  });

  it("stretches to its container in full-bleed mode without stretching the stroke", () => {
    const { container } = render(<Sparkline values={[1, 4, 9]} label="x" isFullBleed isArea />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("data-full-bleed", "true");
    expect(svg).toHaveAttribute("preserveAspectRatio", "none");
    // A 2px stroke under a non-uniform scale is a wedge without this.
    const line = container.querySelector("path[fill='none']");
    expect(line).toHaveAttribute("vector-effect", "non-scaling-stroke");
    // The end dot is the one mark `preserveAspectRatio="none"` would draw as an ellipse, and
    // it would be half-clipped on the container's edge anyway.
    expect(container.querySelector("circle")).toBeNull();
    // The accessible name still carries the last value, so nothing is lost with the marker.
    expect(svg).toHaveAttribute("aria-label", expect.stringContaining("to 9"));
  });

  it("paints from a token, never a hex", () => {
    const { container } = render(<Sparkline values={[1, 4, 9]} label="x" colorVar="var(--c-2)" />);
    expect(container.querySelector("path")).toHaveAttribute("stroke", "var(--c-2)");
  });

  it("draws a flat series down the middle rather than dividing by zero", () => {
    const { container } = render(<Sparkline values={[5, 5, 5]} label="x" height={28} />);
    const d = container.querySelector("path")?.getAttribute("d") ?? "";
    expect(d).not.toContain("NaN");
    // All three points share one y.
    const ys = [...d.matchAll(/[ML]([\d.]+),([\d.]+)/g)].map((match) => match[2]);
    expect(new Set(ys).size).toBe(1);
  });

  it("falls back to an em dash below two points — a one-point trend is not a trend", () => {
    render(<Sparkline values={[7]} label="x" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("ignores non-finite values rather than rendering a broken path", () => {
    const { container } = render(<Sparkline values={[1, Number.NaN, 4, 9]} label="x" />);
    expect(container.querySelector("path")?.getAttribute("d")).not.toContain("NaN");
    expect(container.querySelector("svg")).toHaveAttribute("data-point-count", "3");
  });

  it("adds the area wash only when asked", () => {
    const { container: plain } = render(<Sparkline values={[1, 4, 9]} label="x" />);
    expect(plain.querySelector("linearGradient")).toBeNull();
    const { container: washed } = render(<Sparkline values={[1, 4, 9]} label="y" isArea />);
    expect(washed.querySelector("linearGradient")).not.toBeNull();
  });
});
