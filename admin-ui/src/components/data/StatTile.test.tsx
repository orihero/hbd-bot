import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatRate, rateBand } from "@/lib";

import { BAND_PRESENTATION, StatTile } from "./StatTile";

describe("StatTile", () => {
  it("renders the label and the pre-formatted value", () => {
    render(<StatTile label="24h delivery" value={formatRate(0.968)} band={rateBand(0.968)} />);
    expect(screen.getByText("24h delivery")).toBeInTheDocument();
    expect(screen.getByText("96.8%")).toBeInTheDocument();
  });

  it("puts §11.2's colour rule on the value", () => {
    // The hues moved with the palette; the RULE did not. green ≥95% / amber 85–95% / red
    // <85% is now --success / --caution / --error, and every one of them is a text-safe
    // token rather than a graphic fill, because the figure is text however large it is.
    const { rerender } = render(<StatTile label="rate" value="96.8%" band="good" />);
    expect(screen.getByText("96.8%")).toHaveStyle({ color: "var(--success)" });
    rerender(<StatTile label="rate" value="90.0%" band="warn" />);
    expect(screen.getByText("90.0%")).toHaveStyle({ color: "var(--caution)" });
    rerender(<StatTile label="rate" value="70.0%" band="bad" />);
    expect(screen.getByText("70.0%")).toHaveStyle({ color: "var(--error)" });
  });

  it("never paints a band from a policed token or a hex", () => {
    // The old `unknown` band was `--fg-2` behind a contrast waiver. Every band is a token
    // that clears 4.5:1 on every ground in both palettes now, so the tile needs no waiver
    // and cannot acquire one by accident.
    const painted = Object.values(BAND_PRESENTATION).map((entry) => entry.colorVar);
    expect(painted).toEqual([
      "var(--success)",
      "var(--caution)",
      "var(--error)",
      "var(--neutral)",
    ]);
    for (const colorVar of painted) {
      expect(colorVar).not.toMatch(/--ink-mark|--ink-rule/u);
      expect(colorVar).not.toMatch(/#[0-9a-f]{3,8}/iu);
    }
  });

  it("prints the band's word too, so the tile survives greyscale", () => {
    render(<StatTile label="rate" value="70.0%" band="bad" />);
    expect(screen.getByText("bad")).toBeInTheDocument();
  });

  it("treats an unknown rate as neither zero nor bad", () => {
    render(<StatTile label="rate" value={formatRate(null)} band={rateBand(null)} />);
    // `successRate` is null when nothing terminated; a red 0% would be the most alarming
    // wrong number this console could show.
    expect(screen.getByText("—")).toHaveStyle({ color: "var(--neutral)" });
    expect(screen.getByText("no data")).toBeInTheDocument();
  });

  it("renders the hero size at 44px for the one dominant signal per view", () => {
    render(<StatTile label="24h delivery" value="96.8%" size="hero" />);
    expect(screen.getByText("96.8%")).toHaveClass("type-hero");
  });

  it("defaults to the 28px metric size", () => {
    render(<StatTile label="in flight" value="12" />);
    expect(screen.getByText("12")).toHaveClass("type-metric");
  });

  it("adds the pulsing ring for in-flight work", () => {
    const { container } = render(<StatTile label="in flight" value="12" band="warn" isPulsing />);
    expect(container.querySelector(".animate-pulse-ring")).not.toBeNull();
  });

  it("runs the trend across the bottom of the tile in the brand hue", () => {
    const { container } = render(
      <StatTile
        label="new users"
        value="1,204"
        band="bad"
        trend={[1, 4, 2, 9, 12]}
        trendLabel="30-day new users"
      />,
    );
    expect(screen.getByRole("img", { name: /30-day new users/ })).toBeInTheDocument();
    // The sparkline is the tile's own trend, not a semantic series: it stays --brand-fill
    // even on a `bad` tile, where painting it the band's colour said "red" twice and added
    // nothing. Semantic hue is reserved for the figure, which pairs it with the band's word.
    expect(container.querySelector("path[fill='none']")).toHaveAttribute(
      "stroke",
      "var(--brand-fill)",
    );
    expect(container.querySelector("svg[data-full-bleed='true']")).not.toBeNull();
  });

  it("omits the band word entirely when no band is given", () => {
    render(<StatTile label="in flight" value="12" />);
    expect(screen.queryByText("no data")).toBeNull();
    expect(screen.getByText("12")).toHaveStyle({ color: "var(--ink)" });
  });

  it("carries a delta chip whose direction is a glyph, not only a tint", () => {
    render(
      <StatTile
        label="24h delivery"
        value="96.8%"
        delta={{ value: "+2.1pp", direction: "up", tone: "good", comparedTo: "vs. previous 24h" }}
      />,
    );
    const chip = screen.getByText("+2.1pp").parentElement;
    expect(chip).toHaveAttribute("data-delta-direction", "up");
    expect(chip).toHaveAttribute("data-delta-tone", "good");
    // ▲ is the second channel: the chip's meaning survives greyscale and a red-green reader.
    expect(chip).toHaveTextContent("▲");
    // …and what it is measured against is a fact, so it is in the accessible name too.
    expect(chip).toHaveTextContent("vs. previous 24h");
  });

  it("keeps direction and goodness separate — a falling failure rate is down AND good", () => {
    render(
      <StatTile
        label="failure rate"
        value="0.4%"
        delta={{ value: "−1.2pp", direction: "down", tone: "good" }}
      />,
    );
    const chip = screen.getByText("−1.2pp").parentElement;
    expect(chip).toHaveAttribute("data-delta-direction", "down");
    expect(chip).toHaveAttribute("data-delta-tone", "good");
    expect(chip).toHaveTextContent("▼");
  });

  it("tints a delta neutral when the caller has no opinion about the movement", () => {
    render(<StatTile label="orders" value="1,204" delta={{ value: "+18", direction: "up" }} />);
    expect(screen.getByText("+18").parentElement).toHaveAttribute("data-delta-tone", "neutral");
  });
  /*
   * The glyph is a mark ON the figure, not a word beside it. Left on the row's
   * `items-baseline`, a 14px ⚑ sat its 10px of ink in the bottom third of a 40px numeral's
   * 28px cap band (measured in Chromium: glyph ink 169.9→180 against figure ink 152→180) and
   * read as a stray artefact that had slipped off the number. `self-center` puts it on the
   * figure's own line box instead, which is where the numeral's optical centre is.
   */
  describe("a glyph beside a figure", () => {
    it("is centred on the numeral rather than sat on its baseline", () => {
      render(<StatTile label="destructive actions · 24h" size="hero" value="7" glyph="⚑" />);
      const mark = screen.getByText("⚑");
      expect(mark).toHaveClass("self-center");
      // `/none` is the line-height: the mark's box is its own ink, so what gets centred on
      // the numeral is the glyph and not a font's leading.
      expect(mark.className).toMatch(/\/none/u);
      expect(mark).toHaveAttribute("aria-hidden", "true");
    });

    it("scales with the figure, so hero and metric tiles read as one family", () => {
      const hero = render(
        <StatTile label="destructive actions · 24h" size="hero" value="7" glyph="⚑" />,
      );
      const heroMark = hero.getByText("⚑").className;
      hero.unmount();
      render(<StatTile label="in flight" value="3" glyph="◐" />);
      const metricMark = screen.getByText("◐").className;
      // Not the same size — a 40px figure and a 28px one do not take the same mark — but
      // both sized off the figure rather than left at the inherited 14px body size.
      expect(heroMark).not.toBe(metricMark);
      expect(heroMark).toMatch(/text-\[1\.375rem\]\/none/u);
      expect(metricMark).toMatch(/text-\[1rem\]\/none/u);
    });

    it("still pulses with the figure when the tile is live", () => {
      render(<StatTile label="in flight" value="3" glyph="◐" isPulsing />);
      expect(screen.getByText("◐")).toHaveClass("animate-pulse-ring");
    });
  });
});
