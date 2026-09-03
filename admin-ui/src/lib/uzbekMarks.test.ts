/**
 * The premise behind the `components/domain/` fence, as something CI can check.
 *
 * For three rounds this codebase justified its most important lint rule with a claim that
 * was false. Every comment said "`NFKD` folds U+02BB to a plain ASCII apostrophe". It does
 * not. The rule was still right, but its stated reason was wrong — and a rule defended by a
 * wrong reason is a rule that gets argued away the first time somebody checks the reason.
 *
 * The correction was applied in five places (eslint.config.js, NameText.tsx, RevealDialog.tsx
 * and two test titles) and every one of them was PROSE. Prose is exactly the footing the
 * false version stood on. This file replaces that footing with assertions.
 *
 * WHY IT LIVES IN `src/lib/` AND NOT BESIDE THE COMPONENTS IT DEFENDS. Demonstrating any of
 * this requires calling `normalize`, `toLowerCase` and `localeCompare` — the three methods
 * the fence bans inside `components/domain/`. That ban is correct and must not be routed
 * around: `String.prototype.normalize.call(x, "NFKD")` would evade the selector, and reaching
 * for that trick inside the fenced directory is precisely the cleverness the directory exists
 * to prevent. The rule's own message names the right home for this — "if you need to compare
 * or fold OUR OWN strings, do it in src/lib/" — so here it is.
 *
 * Nothing here is a component test. It is a test about Unicode, pinning the two facts the
 * fence's rationale now asserts.
 */

import { describe, expect, it } from "vitest";

/** U+02BB MODIFIER LETTER TURNED COMMA — the `ʻ` in `oʻ` and `gʻ`. */
const TURNED_COMMA = "ʻ";
/** U+02BC MODIFIER LETTER APOSTROPHE — the `ʼ` in `sanʼat`. */
const MODIFIER_APOSTROPHE = "ʼ";

/** The three specimens the whole product is measured against. */
const OKTAM = `O${TURNED_COMMA}ktam`;
const GULOM = `G${TURNED_COMMA}ulom`;
const SANAT = `san${MODIFIER_APOSTROPHE}at`;

const FORMS = ["NFC", "NFD", "NFKC", "NFKD"] as const;

describe("what normalisation does to the two Uzbek modifier letters: nothing", () => {
  it.each(FORMS)("%s is the identity for U+02BB and U+02BC in isolation", (form) => {
    // The claim the old comments made was specifically about NFKD. It is false for NFKD and
    // for the other three: neither codepoint carries a decomposition mapping of any kind.
    expect(TURNED_COMMA.normalize(form)).toBe(TURNED_COMMA);
    expect(MODIFIER_APOSTROPHE.normalize(form)).toBe(MODIFIER_APOSTROPHE);
  });

  it.each(FORMS)("%s leaves the three specimen names byte-for-byte unchanged", (form) => {
    expect(OKTAM.normalize(form)).toBe(OKTAM);
    expect(GULOM.normalize(form)).toBe(GULOM);
    expect(SANAT.normalize(form)).toBe(SANAT);
  });

  it("never turns either mark into an ASCII apostrophe, which is what was claimed", () => {
    for (const form of FORMS) {
      expect(TURNED_COMMA.normalize(form)).not.toBe("'");
      expect(MODIFIER_APOSTROPHE.normalize(form)).not.toBe("'");
      expect(OKTAM.normalize(form)).not.toContain("'");
    }
  });

  it("keeps U+02BB and U+02BC distinct from each other under every form", () => {
    // If any form collapsed these two, `Oʻktam` and a `sanʼat`-style name would stop being
    // distinguishable, and the codepoint toggle would be showing the operator a fiction.
    for (const form of FORMS) {
      expect(TURNED_COMMA.normalize(form)).not.toBe(MODIFIER_APOSTROPHE.normalize(form));
    }
  });
});

describe("what actually destroys these names — the real reasons the fence exists", () => {
  it("case folding changes the datum: Gʻulom is not gʻulom", () => {
    expect(GULOM.toLowerCase()).not.toBe(GULOM);
    expect(GULOM.toUpperCase()).not.toBe(GULOM);
  });

  it("case folding is lossy even though the mark itself survives it", () => {
    // The mark has no case, so it comes through — which is exactly why this is insidious:
    // the character the old comment blamed is the one part that is fine. The LETTER moved.
    expect(GULOM.toLowerCase()).toContain(TURNED_COMMA);
    expect(GULOM.toLowerCase().startsWith("g")).toBe(true);
    expect(GULOM.startsWith("G")).toBe(true);
  });

  /*
   * A SECOND FALSE RATIONALE, caught by writing this file.
   *
   * The correction that replaced the NFKD claim introduced a new one: several comments now
   * say `localeCompare` "treats the mark as ignorable, so `Gʻulom` and `Gulom` compare
   * equal". Measured, that is also false — under every locale and every option this runtime
   * offers, including `ignorePunctuation: true`, those two names compare NON-equal. Writing
   * a plausible-sounding reason instead of measuring one is the exact defect the NFKD
   * correction existed to fix, so these two tests pin what collation really does.
   */
  it("does NOT treat U+02BB as ignorable: Gʻulom and Gulom never compare equal", () => {
    expect(GULOM).not.toBe("Gulom");
    for (const options of [
      {},
      { sensitivity: "base" },
      { sensitivity: "accent" },
      { sensitivity: "variant" },
      { ignorePunctuation: true },
      { sensitivity: "base", ignorePunctuation: true },
    ] as const) {
      expect(
        GULOM.localeCompare("Gulom", "en", options),
        `collation equated Gʻulom with Gulom under ${JSON.stringify(options)}`,
      ).not.toBe(0);
    }
  });

  it("DOES silently erase the case distinction at base strength: Gʻulom == gʻulom", () => {
    // This is the real hazard, and it is the one worth banning for: `sensitivity: "base"`
    // is what a dedupe or an "is this the same name" check reaches for, and it reports two
    // distinct names as one string. The mark survives; the identity does not.
    const folded = `g${TURNED_COMMA}ulom`;
    expect(GULOM).not.toBe(folded);
    expect(GULOM.localeCompare(folded, "en", { sensitivity: "base" })).toBe(0);
    expect(GULOM.localeCompare(folded, "en", { sensitivity: "accent" })).toBe(0);
    // At full strength collation does keep them apart — so whether the datum survives
    // depends entirely on an options bag at the call site. That is the argument for banning
    // the method in the render path rather than reviewing each use of it.
    expect(GULOM.localeCompare(folded, "en", { sensitivity: "variant" })).not.toBe(0);
  });

  it("a Turkish locale mangles the surrounding Latin as well", () => {
    // `I` lowercases to a dotless `ı` under tr — the locale-aware folding the rule warns
    // about, on a name that has nothing to do with the modifier letters.
    expect("Iroda".toLocaleLowerCase("tr")).not.toBe("iroda");
  });
});
