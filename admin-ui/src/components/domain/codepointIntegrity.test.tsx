/**
 * The reskin's codepoint gate: `Oʻktam`, `Gʻulom`, `Дилноза` and `sanʼat` still come back
 * out of the DOM one codepoint at a time, from every RESKINNED surface that draws a name.
 *
 * `NameText.test.tsx` proves the component. This file proves the RESKIN, and it exists
 * because a restyle is the single most likely moment for these four strings to break:
 * nobody rewrites `<NameText>`'s render, but a reskin touches class strings on every
 * ancestor of it, and `text-transform: uppercase` on a wrapper mangles `Gʻulom` on screen
 * while leaving `textContent` — and therefore most tests — perfectly intact.
 *
 * ## What is actually dangerous here, corrected
 *
 * The comments this codebase used to carry said `NFKD` folds U+02BB to a plain apostrophe.
 * **It does not.** NFC, NFD, NFKC and NFKD are all the identity for U+02BB MODIFIER LETTER
 * TURNED COMMA and for U+02BC MODIFIER LETTER APOSTROPHE — neither codepoint carries a
 * decomposition mapping of any kind. The three things that really destroy these names are
 * case folding (`"Gʻulom".toLowerCase()` is a different name), locale-aware collation
 * (`localeCompare` at `sensitivity: "base"` reports `Gʻulom` and `gʻulom` as equal, merging
 * two distinct names — it does NOT treat the mark as ignorable, and an earlier version of
 * this comment wrongly said `Gʻulom` and `Gulom` compare equal), and `text-transform`,
 * which changes the picture with no trace in the data at all.
 *
 * That correction is asserted NOWHERE IN THIS FILE, and deliberately so: demonstrating it
 * means calling `normalize` and `toLowerCase`, and both are banned inside
 * `components/domain/` by the fence in `eslint.config.js`. The fence is the point; routing
 * around it with `String.prototype.normalize.call(…)` — which the selector would not catch
 * — would be exactly the kind of clever that this directory exists to prevent. The rule's
 * own message says where such a proof belongs: `src/lib/`, outside the fence — and it now
 * lives there, as `src/lib/uzbekMarks.test.ts`, which measures all four normalisation forms
 * against both codepoints and pins what case folding and collation really do. Everything
 * below asserts what CAN be asserted in here, which is what actually reaches the DOM.
 *
 * ## Why the assertions are on `String.codePointAt`
 *
 * `Oʻktam` and `O'ktam` are the same picture at 14px and different names to the matcher.
 * An assertion written as `toHaveTextContent("Oʻktam")` passes on exactly the bug this
 * product exists to prevent, because the expected string in the test file would be folded
 * by the same bad paste that folded the source. Numbers cannot be folded.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AttentionList } from "./AttentionList";
import { CodepointTooltip } from "./CodepointTooltip";
import { makeOrder, NAME_DILNOZA, NAME_GULOM, NAME_OKTAM, WORD_SANAT } from "./fixtures";
import { NameText } from "./NameText";

/** U+02BB MODIFIER LETTER TURNED COMMA — the `oʻ`/`gʻ` mark. */
const TURNED_COMMA = 0x02bb;
/** U+02BC MODIFIER LETTER APOSTROPHE — `sanʼat`'s mark. A DIFFERENT character. */
const MODIFIER_APOSTROPHE = 0x02bc;

interface Specimen {
  readonly label: string;
  readonly value: string;
  readonly codepoints: readonly number[];
  /** What `<CodepointTooltip>` must print, spelled out by hand. */
  readonly spelled: readonly string[];
}

/*
 * The `spelled` column is written out by hand rather than derived with `toString(16)` and
 * `toUpperCase()`: the second of those is banned in this directory, and a table that
 * derives its own expectation from the value under test asserts only that two copies of the
 * same arithmetic agree. These are the strings a human should see in the panel.
 */
const SPECIMENS: readonly Specimen[] = [
  {
    label: "Oʻktam",
    value: NAME_OKTAM,
    codepoints: [0x004f, 0x02bb, 0x006b, 0x0074, 0x0061, 0x006d],
    spelled: ["U+004F", "U+02BB", "U+006B", "U+0074", "U+0061", "U+006D"],
  },
  {
    label: "Gʻulom",
    value: NAME_GULOM,
    codepoints: [0x0047, 0x02bb, 0x0075, 0x006c, 0x006f, 0x006d],
    spelled: ["U+0047", "U+02BB", "U+0075", "U+006C", "U+006F", "U+006D"],
  },
  {
    label: "Дилноза",
    value: NAME_DILNOZA,
    codepoints: [0x0414, 0x0438, 0x043b, 0x043d, 0x043e, 0x0437, 0x0430],
    spelled: ["U+0414", "U+0438", "U+043B", "U+043D", "U+043E", "U+0437", "U+0430"],
  },
  {
    label: "sanʼat",
    value: WORD_SANAT,
    codepoints: [0x0073, 0x0061, 0x006e, 0x02bc, 0x0061, 0x0074],
    spelled: ["U+0073", "U+0061", "U+006E", "U+02BC", "U+0061", "U+0074"],
  },
];

/** Every codepoint of a node's text, by index — never by string equality. */
function codepointsOf(node: Element | null): readonly number[] {
  return Array.from(node?.textContent ?? "", (char) => char.codePointAt(0) ?? -1);
}

/* ------------------------------------------------------------------------------------- *
 * Every reskinned surface that draws a name.
 * ------------------------------------------------------------------------------------- */

describe("the restyled <NameText> still emits the exact codepoints", () => {
  it.each(SPECIMENS.map((specimen) => [specimen.label, specimen] as const))(
    "%s round-trips through the plain render",
    (_label, specimen) => {
      render(<NameText value={specimen.value} />);
      expect(codepointsOf(screen.getByTestId("name-text"))).toEqual(specimen.codepoints);
    },
  );

  it("still emits <span lang=uz-Latn dir=ltr> after the restyle", () => {
    render(<NameText value={NAME_OKTAM} className="rounded-pill bg-brand-tint px-2" />);
    const span = screen.getByTestId("name-text");
    expect(span).toHaveAttribute("lang", "uz-Latn");
    expect(span).toHaveAttribute("dir", "ltr");
    // A caller's className lands on the WRAPPER, never on the language-tagged span, so no
    // restyle of a caller can reach inside and transform the name.
    expect(span.className).not.toMatch(/uppercase|lowercase|capitalize/u);
  });

  it("keeps the codepoint toggle spelling O <U+02BB> ktam after the restyle", () => {
    render(<NameText value={NAME_OKTAM} showCodepoints />);
    const span = screen.getByTestId("name-text");
    // The datum lives in an attribute, not only in the drawn text, so a font or a style
    // cannot be what makes it right.
    const sub = span.querySelector("sub[data-codepoint]");
    expect(sub?.getAttribute("data-codepoint")).toBe("U+02BB");
    // The legible characters are still themselves — the whole point of spelling out ONLY
    // the ambiguous ones is that the operator can still read the name.
    expect(span.textContent?.startsWith("O")).toBe(true);
    expect(span.textContent?.endsWith("ktam")).toBe(true);
  });

  it("keeps sanʼat's U+02BC distinct from Oʻktam's U+02BB in the same render", () => {
    render(
      <>
        <NameText value={NAME_OKTAM} className="a" />
        <NameText value={WORD_SANAT} className="b" />
      </>,
    );
    const [first, second] = screen.getAllByTestId("name-text");
    expect(codepointsOf(first ?? null)[1]).toBe(TURNED_COMMA);
    expect(codepointsOf(second ?? null)[3]).toBe(MODIFIER_APOSTROPHE);
  });
});

describe("the restyled <CodepointTooltip> panel", () => {
  it.each(SPECIMENS.map((specimen) => [specimen.label, specimen] as const))(
    "spells every codepoint of %s as U+XXXX",
    async (_label, specimen) => {
      const user = userEvent.setup();
      render(
        <CodepointTooltip value={specimen.value}>
          <NameText value={specimen.value} />
        </CodepointTooltip>,
      );
      await user.tab();
      const panel = screen.getByRole("tooltip");
      for (const label of specimen.spelled) {
        expect(panel.textContent).toContain(label);
      }
    },
  );
});

describe("the restyled <AttentionList> row", () => {
  it("draws a recipient name through <NameText> and nothing else", () => {
    render(
      <MemoryRouter>
        <AttentionList
          orders={[makeOrder({ id: "f", state: "failed", recipientName: NAME_GULOM })]}
          now={Date.parse("2026-05-01T12:00:00Z")}
        />
      </MemoryRouter>,
    );
    const name = screen.getByTestId("name-text");
    expect(codepointsOf(name)).toEqual(SPECIMENS[1]?.codepoints);
    expect(name).toHaveAttribute("lang", "uz-Latn");
  });

  it("puts no text-transform on any ancestor of the name, all the way to the card", () => {
    // This is the assertion the reskin needs and the component-level tests cannot make:
    // `text-transform` lives on an ANCESTOR's class, changes only the picture, and leaves
    // `textContent` — and therefore every codepoint assertion above — perfectly green.
    // `.type-caption` is the one class in `index.css` licensed to transform text, so it is
    // banned here too rather than allowed as an exception.
    const { container } = render(
      <MemoryRouter>
        <AttentionList
          orders={[makeOrder({ id: "f", state: "failed", recipientName: NAME_GULOM })]}
          now={Date.parse("2026-05-01T12:00:00Z")}
        />
      </MemoryRouter>,
    );
    let node: Element | null = screen.getByTestId("name-text");
    const seen: string[] = [];
    while (node !== null && node !== container) {
      seen.push(node.className);
      expect(node.className).not.toMatch(/\b(?:uppercase|lowercase|capitalize|type-caption)\b/u);
      expect(node.getAttribute("style") ?? "").not.toContain("text-transform");
      node = node.parentElement;
    }
    // The walk really did climb — an empty walk would pass vacuously.
    expect(seen.length).toBeGreaterThan(2);
  });
});
