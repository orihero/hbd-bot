/**
 * The tests that guard the datum this product exists to get right.
 *
 * They assert on `String.codePointAt`, never on visual equality: `Oʻktam` and `O'ktam` are
 * the same picture at 14px and different names to the matcher, so an assertion that
 * compares what a human sees would pass on exactly the bug this component exists to
 * prevent. Every case below survives a render round-trip codepoint for codepoint.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MASK } from "@/api";
import { EMPTY_VALUE } from "@/lib";

import { NAME_DILNOZA, NAME_GULOM, NAME_OKTAM, WORD_SANAT } from "./fixtures";
import { NameText } from "./NameText";

/** The rendered text of the language-tagged span, as codepoints. */
function renderedCodepoints(value: string | null): readonly number[] {
  render(<NameText value={value} />);
  const text = screen.getByTestId("name-text").textContent ?? "";
  return Array.from(text, (char) => char.codePointAt(0) ?? -1);
}

describe("a name survives the render round-trip codepoint for codepoint", () => {
  it.each([
    ["Oʻktam", NAME_OKTAM, [0x004f, 0x02bb, 0x006b, 0x0074, 0x0061, 0x006d]],
    ["Gʻulom", NAME_GULOM, [0x0047, 0x02bb, 0x0075, 0x006c, 0x006f, 0x006d]],
    ["Дилноза", NAME_DILNOZA, [0x0414, 0x0438, 0x043b, 0x043d, 0x043e, 0x0437, 0x0430]],
    ["sanʼat", WORD_SANAT, [0x0073, 0x0061, 0x006e, 0x02bc, 0x0061, 0x0074]],
  ])("renders %s unchanged", (_label, value, expected) => {
    expect(renderedCodepoints(value)).toEqual(expected);
  });

  it("keeps U+02BB distinct from the three characters an ASCII fold collapses it to", () => {
    // Not NFKD: all four normalisation forms are the identity for U+02BB. What collapses
    // these four is an autocorrect, a "smart quotes" pass, or a hand-rolled ASCII fold —
    // and if any of them ran in the render path, these four would be one character.
    const rendered = renderedCodepoints(NAME_OKTAM);
    expect(rendered[1]).toBe(0x02bb);
    expect(rendered[1]).not.toBe(0x0027); // APOSTROPHE
    expect(rendered[1]).not.toBe(0x2019); // RIGHT SINGLE QUOTATION MARK
    expect(rendered[1]).not.toBe(0x02bc); // MODIFIER LETTER APOSTROPHE — sanʼat's
  });

  it("keeps sanʼat's U+02BC distinct from Oʻktam's U+02BB", () => {
    expect(WORD_SANAT.codePointAt(3)).toBe(0x02bc);
    expect(NAME_OKTAM.codePointAt(1)).toBe(0x02bb);
    expect(renderedCodepoints(WORD_SANAT)[3]).toBe(0x02bc);
  });

  it("does not case-fold: the capital survives and no lowercase form appears", () => {
    const rendered = renderedCodepoints(NAME_GULOM);
    expect(rendered[0]).toBe(0x0047); // G, not g
  });
});

describe("the element it emits", () => {
  it("is the <span lang=uz-Latn dir=ltr> §11.4 pins", () => {
    render(<NameText value={NAME_OKTAM} />);
    const span = screen.getByTestId("name-text");
    expect(span.tagName).toBe("SPAN");
    expect(span).toHaveAttribute("lang", "uz-Latn");
    expect(span).toHaveAttribute("dir", "ltr");
  });
});

describe("null is not the mask, and the mask is not null", () => {
  it("renders the fallback for null — a purged identity, not an empty name", () => {
    render(<NameText value={null} />);
    expect(screen.queryByTestId("name-text")).toBeNull();
    expect(screen.getByText(EMPTY_VALUE)).toBeInTheDocument();
  });

  it("renders the mask string as itself — three U+2022, not three asterisks", () => {
    expect(renderedCodepoints(MASK)).toEqual([0x2022, 0x2022, 0x2022]);
  });

  it("renders a masked first grapheme plus the mask verbatim", () => {
    expect(renderedCodepoints(`G${MASK}`)).toEqual([0x0047, 0x2022, 0x2022, 0x2022]);
  });
});

describe("the codepoint toggle", () => {
  it("renders O<sub>U+02BB</sub>ktam — the exact rendering §11.4 specifies", () => {
    const { container } = render(<NameText value={NAME_OKTAM} showCodepoints />);
    const subs = container.querySelectorAll("sub");
    expect(subs).toHaveLength(1);
    expect(subs[0]?.textContent).toBe("U+02BB");
    expect(screen.getByTestId("name-text").textContent).toBe("OU+02BBktam");
  });

  it("spells U+02BC for sanʼat, so the two modifier letters are told apart on screen", () => {
    const { container } = render(<NameText value={WORD_SANAT} showCodepoints />);
    expect(container.querySelector("sub")?.textContent).toBe("U+02BC");
  });

  it("leaves a Cyrillic name legible — spelling every codepoint would be useless", () => {
    const { container } = render(<NameText value={NAME_DILNOZA} showCodepoints />);
    expect(container.querySelectorAll("sub")).toHaveLength(0);
    expect(screen.getByTestId("name-text").textContent).toBe(NAME_DILNOZA);
  });

  it("offers a toggle button that flips the spelling on", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<NameText value={NAME_OKTAM} isToggleable />);
    expect(screen.getByTestId("name-text").textContent).toBe(NAME_OKTAM);
    await user.click(screen.getByRole("button"));
    expect(screen.getByTestId("name-text").textContent).toBe("OU+02BBktam");
  });
});
