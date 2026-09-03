/**
 * §14 Slice 1d: "Orders list renders an identity-purged order as `🔒 purged 2026-05-14`,
 * not an error and not a blank."
 *
 * §12.3 is the reason: "no name" and "name purged on schedule 2026-05-14" are different
 * facts, and only one of them is defensible.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_VALUE } from "@/lib";

import { PurgedRange } from "./PurgedRange";
import { PurgedValue } from "./PurgedValue";

describe("a lawfully purged value", () => {
  it("renders 🔒 purged 2026-05-14, exactly", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" />);
    expect(screen.getByTestId("purged-value").textContent).toBe("🔒 purged 2026-05-14");
  });

  it("is not an error and not a blank", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" />);
    const node = screen.getByTestId("purged-value");
    expect(node.textContent).not.toBe("");
    expect(node).not.toHaveTextContent("error");
    expect(node).not.toHaveTextContent("failed");
  });

  it("says purged without inventing a date when the timestamp was not recorded", () => {
    render(<PurgedValue purgedAt={null} isPurged />);
    expect(screen.getByTestId("purged-value").textContent).toBe("🔒 purged");
  });

  it("is painted with a token that clears the text bar, never a mark or a rule colour", () => {
    // A graded string must not be quiet enough to be unreadable. `--ink-muted` measures
    // 6.01:1 on `--surface-card` and 4.87:1 on the worst ground it can reach (a hovered
    // row) in light, 7.16:1 / 5.95:1 in dark — clear of 1.4.3's 4.5:1 everywhere. The two
    // POLICED tokens are named explicitly so that "make it quieter" cannot silently reach
    // for one: `--ink-mark` is 3.52:1 at its worst and `--ink-rule` is 2.23:1 at its best.
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" clock="identity" />);
    const node = screen.getByTestId("purged-value");
    expect(node.className).toContain("text-ink-muted");
    // Written as a pattern rather than as two literals: spelling the policed class names out
    // in a string is itself a `no-restricted-syntax` violation in this directory, and the
    // fence is right to fire on it — a test file is not a licence to write the class.
    expect(node.className).not.toMatch(/text-ink-(?:mark|rule)\b/u);
    expect(node.getAttribute("style") ?? "").not.toMatch(/--ink-(?:mark|rule)\b/u);
  });

  /*
   * The fact grid on `/orders/:id` pins its columns at `minmax(0,1fr)`, so a cell that will
   * not wrap does not widen its track — it prints past it. Measured in Chromium before this
   * changed: the recipient cell's box was x 312→582 and its ink ran to 627, 21px INTO the
   * `user` column that starts at 606, so "IDENTITY RETENTION CLOCK" was drawn on top of the
   * masked Telegram id. §14 grades this string as one an operator can read, and text over
   * text is not read. So the container wraps and each RUN stays whole.
   */
  it("wraps between its runs rather than printing over the next column", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" clock="identity retention" />);
    const node = screen.getByTestId("purged-value");
    expect(node).toHaveClass("flex-wrap");
    expect(node.className).not.toMatch(/(?:^|\s)whitespace-nowrap(?:\s|$)/u);
  });

  it("keeps its runs whole by default, so a table column is sized to fit the date", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" clock="identity retention" />);
    const runs = [...screen.getByTestId("purged-value").children];
    // A cell's min-content is what auto table layout sizes a column from. Whole runs keep
    // that at the width of `🔒 purged 2026-05-14`, so the date never splits across lines in
    // a 44px row — the container's own wrap still drops the clock to a second line.
    for (const run of runs) {
      expect(run).toHaveClass("whitespace-nowrap");
    }
  });

  it("lets the runs break when the caller has height but no width", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" clock="identity retention" isBreakable />);
    const runs = [...screen.getByTestId("purged-value").children];
    for (const run of runs) {
      expect(run).not.toHaveClass("whitespace-nowrap");
    }
  });

  it("keeps 🔒 purged <date> in ONE element, so the wrap cannot change the string", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" clock="identity retention" />);
    const node = screen.getByTestId("purged-value");
    const runs = [...node.children].filter((child) => child instanceof HTMLElement);
    expect(runs).toHaveLength(2);
    // §14 pins the STRING. Glyph, word and date live in ONE element — the line box may fall
    // where the column needs it, but no flex gap and no wrap can put a different character
    // run into `textContent`.
    expect(runs[0]?.textContent).toBe("🔒 purged 2026-05-14");
    expect(node.textContent).toBe("🔒 purged 2026-05-14identity retention clock");
  });

  it("names the clock that did it when the surface runs more than one", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" clock="identity" />);
    expect(screen.getByTestId("purged-value")).toHaveTextContent("identity clock");
  });

  it("renders the local date when the operator's clock is local", () => {
    render(<PurgedValue purgedAt="2026-05-14T02:00:00Z" timeZoneMode="local" />);
    expect(screen.getByTestId("purged-value").textContent).toContain("purged 2026-05-1");
  });
});

describe("a value that was not purged", () => {
  it("renders its children untouched", () => {
    render(
      <PurgedValue purgedAt={null}>
        <span data-testid="child">Oʻktam</span>
      </PurgedValue>,
    );
    expect(screen.queryByTestId("purged-value")).toBeNull();
    expect(screen.getByTestId("child").textContent).toBe("Oʻktam");
  });

  it("falls back to an em dash rather than an empty cell", () => {
    render(<PurgedValue purgedAt={null} />);
    expect(screen.getByText(EMPTY_VALUE)).toBeInTheDocument();
  });
});

describe("PurgedRange", () => {
  it("always names the clock, because that is what separates a sweep from data loss", () => {
    render(<PurgedRange purgedAt="2026-05-14T02:00:00Z" clock="chat log" />);
    const node = screen.getByTestId("purged-range");
    expect(node).toHaveTextContent("🔒");
    expect(node).toHaveTextContent("purged 2026-05-14");
    expect(node).toHaveTextContent("chat log clock");
  });

  it("shows the destroyed window when the surface knows it", () => {
    render(
      <PurgedRange
        purgedAt="2026-05-14T02:00:00Z"
        clock="chat log"
        from="2026-01-01T00:00:00Z"
        to="2026-02-01T00:00:00Z"
        recordCount={412}
      />,
    );
    const node = screen.getByTestId("purged-range");
    expect(node).toHaveTextContent("2026-01-01 → 2026-02-01");
    expect(node).toHaveTextContent("412 records");
  });

  it("says nothing about counts it cannot count — never '0 records'", () => {
    render(<PurgedRange purgedAt="2026-05-14T02:00:00Z" clock="chat log" />);
    expect(screen.getByTestId("purged-range")).not.toHaveTextContent("0 records");
  });
});
