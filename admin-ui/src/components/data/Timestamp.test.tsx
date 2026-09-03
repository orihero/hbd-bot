import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { usePrefsStore } from "@/lib";

import { TimeZoneCaption, Timestamp } from "./Timestamp";

afterEach(() => {
  usePrefsStore.setState({ timeZoneMode: "utc" });
});

describe("Timestamp", () => {
  it("always carries a zone marker — §11.2's 'an ambiguous 14:32 is a support incident'", () => {
    render(<Timestamp at="2026-09-02T14:32:07Z" />);
    const rendered = screen.getByText(/2026-09-02/);
    expect(rendered).toHaveTextContent("2026-09-02 14:32Z");
  });

  it("follows the prefs store's UTC/local toggle", () => {
    usePrefsStore.setState({ timeZoneMode: "local" });
    render(<Timestamp at="2026-09-02T14:32:07Z" />);
    // Whatever the CI box's zone is, the rendered text must carry an explicit offset.
    expect(screen.getByRole("time")).toHaveAttribute("data-timezone-mode", "local");
    expect(screen.getByRole("time").textContent).toMatch(/[+−]\d{2}:\d{2}$/);
  });

  it("lets a caller pin the zone against the toggle", () => {
    usePrefsStore.setState({ timeZoneMode: "local" });
    render(<Timestamp at="2026-09-02T14:32:07Z" mode="utc" />);
    expect(screen.getByRole("time")).toHaveTextContent("2026-09-02 14:32Z");
  });

  it("adds seconds only when asked", () => {
    const { rerender } = render(<Timestamp at="2026-09-02T14:32:07Z" />);
    expect(screen.getByRole("time")).toHaveTextContent("14:32Z");
    rerender(<Timestamp at="2026-09-02T14:32:07Z" seconds />);
    expect(screen.getByRole("time")).toHaveTextContent("14:32:07Z");
  });

  it("keeps the absolute instant in the tooltip when rendering relative time", () => {
    render(<Timestamp at="2026-09-02T14:32:07Z" relative />);
    // Relative time is a SECOND label, never the only one (§11.4).
    expect(screen.getByRole("time")).toHaveAttribute("title", expect.stringContaining("Z"));
  });

  it("renders an em dash for null, never an empty cell", () => {
    render(<Timestamp at={null} />);
    expect(screen.getByText("—")).toHaveAttribute("data-empty", "true");
  });

  it("renders an em dash for an unparseable instant rather than Invalid Date", () => {
    render(<Timestamp at="not-a-timestamp" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid/)).toBeNull();
  });

  it("carries the tabular-numerals class so a poll cannot shift the column", () => {
    render(<Timestamp at="2026-09-02T14:32:07Z" />);
    expect(screen.getByRole("time")).toHaveClass("num");
  });
});

describe("TimeZoneCaption", () => {
  it("names the clock the column is in", () => {
    render(<TimeZoneCaption />);
    expect(screen.getByText("UTC")).toBeInTheDocument();
  });
});
