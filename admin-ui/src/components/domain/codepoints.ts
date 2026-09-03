/**
 * Codepoint spelling — the machinery behind `<NameText>`'s `U+` toggle (§11.4).
 *
 * When a name verification fails, the first question an operator asks is *which apostrophe
 * did the customer type*, and the answer is invisible at 14px: U+02BB MODIFIER LETTER
 * TURNED COMMA, U+02BC MODIFIER LETTER APOSTROPHE, U+2019 RIGHT SINGLE QUOTATION MARK and
 * plain U+0027 all draw as a small tick. `Oʻktam` and `O'ktam` are different names to the
 * matcher and the same picture to the eye.
 *
 * Two rules hold in this file, and both exist because of the ESLint fence over this
 * directory:
 *
 * 1. **Nothing here transforms the string.** `Array.from` iterates by code POINT — never by
 *    UTF-16 unit — so an astral character is one entry and a surrogate pair is never split
 *    in half. `codePointAt` reads; it does not fold.
 * 2. **The hex digits are built by hand rather than with `Number.toString(16).toUpperCase()`.**
 *    `toUpperCase` is banned inside `components/domain/` (it is the call that mangles Uzbek
 *    Latin when the host locale is Turkish), and a lint exemption "just for a number" is
 *    exactly how the ban stops meaning anything. Sixteen characters in a lookup string cost
 *    less than the exception would.
 */

const HEX_DIGITS = "0123456789ABCDEF";

/** `0x02bb` → `U+02BB`. Four digits minimum, more for astral planes. */
export function formatCodepoint(code: number): string {
  let digits = "";
  let remaining = Math.max(0, Math.floor(code));
  while (remaining > 0) {
    digits = (HEX_DIGITS[remaining % 16] ?? "0") + digits;
    remaining = Math.floor(remaining / 16);
  }
  if (digits === "") digits = "0";
  return `U+${digits.padStart(4, "0")}`;
}

/**
 * The codepoints that must be spelled out rather than drawn.
 *
 * The apostrophe family first — these are the ones the whole product turns on. Then the
 * invisible formatting characters, which a copy-paste out of a web page drags along and
 * which make a verification fail for a reason nobody can see.
 */
export const AMBIGUOUS_CODEPOINTS: ReadonlySet<number> = new Set<number>([
  0x0027, // APOSTROPHE
  0x0060, // GRAVE ACCENT
  0x00b4, // ACUTE ACCENT
  0x02b9, // MODIFIER LETTER PRIME
  0x02ba, // MODIFIER LETTER DOUBLE PRIME
  0x02bb, // MODIFIER LETTER TURNED COMMA — the one in oʻ and gʻ
  0x02bc, // MODIFIER LETTER APOSTROPHE — the one in sanʼat
  0x02bd, // MODIFIER LETTER REVERSED COMMA
  0x02c8, // MODIFIER LETTER VERTICAL LINE
  0x2018, // LEFT SINGLE QUOTATION MARK
  0x2019, // RIGHT SINGLE QUOTATION MARK
  0x201b, // SINGLE HIGH-REVERSED-9 QUOTATION MARK
  0x2032, // PRIME
  0x2035, // REVERSED PRIME
  0xff07, // FULLWIDTH APOSTROPHE
  0x00a0, // NO-BREAK SPACE
  0x200b, // ZERO WIDTH SPACE
  0x200c, // ZERO WIDTH NON-JOINER
  0x200d, // ZERO WIDTH JOINER
  0x200e, // LEFT-TO-RIGHT MARK
  0x200f, // RIGHT-TO-LEFT MARK
  0x2060, // WORD JOINER
  0xfeff, // ZERO WIDTH NO-BREAK SPACE
]);

/**
 * Whether a codepoint draws as something an operator cannot identify by looking at it.
 *
 * Combining marks are included as a range: `и` + U+0306 is a different datum from `й`, and
 * on screen they are the same picture.
 */
export function isAmbiguousCodepoint(code: number): boolean {
  if (AMBIGUOUS_CODEPOINTS.has(code)) return true;
  if (code >= 0x0300 && code <= 0x036f) return true; // combining diacritical marks
  if (code < 0x20 || code === 0x7f) return true; // C0 controls and DEL
  return false;
}

export interface Codepoint {
  /** The character exactly as it appears in the value. Never folded, never re-encoded. */
  readonly char: string;
  /** The Unicode scalar value. */
  readonly code: number;
  /** `U+02BB`. */
  readonly label: string;
  /** Whether this one must be spelled out instead of drawn. */
  readonly isAmbiguous: boolean;
}

/** Split a value into codepoints, preserving every one of them exactly. */
export function toCodepoints(value: string): readonly Codepoint[] {
  return Array.from(value, (char): Codepoint => {
    const code = char.codePointAt(0) ?? 0;
    return {
      char,
      code,
      label: formatCodepoint(code),
      isAmbiguous: isAmbiguousCodepoint(code),
    };
  });
}

/** `U+004F U+02BB U+006B` — the whole value, for a copy into a bug report. */
export function codepointSequence(value: string): string {
  return toCodepoints(value)
    .map((point) => point.label)
    .join(" ");
}
