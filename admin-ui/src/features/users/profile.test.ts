import { describe, expect, it } from "vitest";

import { toCodepoints } from "@/components/domain";

import {
  PROFILE_STANDING_HINT,
  PROFILE_STANDING_LABEL,
  displayNameOf,
  profileStandingOf,
  type ProfileStanding,
} from "./profile";

/** Every standing, so a loop cannot silently skip one a future member adds. */
const ALL_STANDINGS: readonly ProfileStanding[] = ["absent", "language_only", "onboarded"];

describe("profileStandingOf", () => {
  it("reports 'absent' when there is no row, whatever the phone says", () => {
    /*
     * `isProfilePresent` is tested first on purpose. An absent row carries a null
     * `phoneMasked` too, so a phone-first implementation would call every erased account
     * "onboarding unfinished" — an invented fact about somebody who may have onboarded and
     * then asked to be forgotten. The second case pins the ordering rather than the value:
     * the server cannot ship a masked phone without a row, and if it ever did, absence still
     * wins.
     */
    expect(profileStandingOf({ isProfilePresent: false, phoneMasked: null })).toBe("absent");
    expect(profileStandingOf({ isProfilePresent: false, phoneMasked: "•••••42" })).toBe("absent");
  });

  it("reports 'language_only' for a row with no number", () => {
    // The server's own `is_onboarded` predicate seen through the mask: no phone, no orders.
    expect(profileStandingOf({ isProfilePresent: true, phoneMasked: null })).toBe("language_only");
  });

  it("reports 'onboarded' once a masked number is present", () => {
    expect(profileStandingOf({ isProfilePresent: true, phoneMasked: "•••••42" })).toBe("onboarded");
  });
});

describe("the standing copy", () => {
  it("words every standing in both maps", () => {
    /*
     * The compiler already forces both records to be total, but only over the members that
     * exist when it runs. This walks the list so that adding a fourth standing and forgetting
     * a hint fails here rather than reaching an operator as an empty `title`.
     */
    for (const standing of ALL_STANDINGS) {
      expect(PROFILE_STANDING_LABEL[standing].length).toBeGreaterThan(0);
      expect(PROFILE_STANDING_HINT[standing].length).toBeGreaterThan(0);
    }
  });

  it("says out loud that absence and erasure are indistinguishable", () => {
    /*
     * This is the one sentence the module exists for. A label reading "no profile" with no
     * hint behind it teaches an operator that the account never onboarded, which is a
     * conclusion the data does not support: `/forget` DELETEs the row, so the two cases are
     * one absence. If somebody shortens this copy, they have to delete this assertion first.
     */
    expect(PROFILE_STANDING_HINT.absent).toContain("/forget");
    expect(PROFILE_STANDING_HINT.absent).toContain("cannot tell those apart");
  });
});

describe("displayNameOf", () => {
  it("joins both masked names with a single space", () => {
    expect(displayNameOf({ firstNameMasked: "G•••", lastNameMasked: "D•••" })).toBe("G••• D•••");
  });

  it("returns the one name that was shared", () => {
    // Telegram requires a first name and not a last one, but the wire allows either to be
    // null, so both single-sided cases are real.
    expect(displayNameOf({ firstNameMasked: "G•••", lastNameMasked: null })).toBe("G•••");
    expect(displayNameOf({ firstNameMasked: null, lastNameMasked: "D•••" })).toBe("D•••");
  });

  it("returns null, not an empty string, when neither name was shared", () => {
    /*
     * `null` is what lets the caller decide between drawing nothing and drawing an em dash.
     * An empty string renders as a collapsed element the caller cannot branch on.
     */
    expect(displayNameOf({ firstNameMasked: null, lastNameMasked: null })).toBeNull();
  });

  it("round-trips a Uzbek Latin mark codepoint-identical", () => {
    /*
     * `Gʻ` is U+0047 U+02BB MODIFIER LETTER TURNED COMMA — not an ASCII apostrophe and not
     * U+2019. The masked value keeps its first grapheme, which is what makes it a legitimate
     * monogram source, and this function must hand it on untouched: one fold, one trim or one
     * `slice` here and the panel shows a different name from the one the customer typed. The
     * assertion is on the code points, not on the rendered string, because at 14px the four
     * candidate marks are the same picture.
     */
    const masked = "Gʻ•••";
    const joined = displayNameOf({ firstNameMasked: masked, lastNameMasked: null });
    expect(joined).toBe(masked);
    expect(toCodepoints(joined ?? "").map((point) => point.code)).toEqual(
      toCodepoints(masked).map((point) => point.code),
    );
    expect(toCodepoints(joined ?? "")[1]?.code).toBe(0x02bb);
    expect(joined).not.toContain("’");
    expect(joined).not.toContain("'");
  });

  it("preserves a leading space rather than trimming a server-sent value", () => {
    /*
     * No `.trim()`: trimming would make a whitespace-only value indistinguishable from an
     * absent one, and it would move the mark's neighbours in a name whose first character is
     * combining. What the server sent is what the screen shows.
     */
    expect(displayNameOf({ firstNameMasked: " G•••", lastNameMasked: null })).toBe(" G•••");
  });
});
