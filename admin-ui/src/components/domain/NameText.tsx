/**
 * `<NameText>` — the ONLY way a name reaches the DOM (§11.4).
 *
 * This is the most important component in the codebase, and it is important for a boring
 * reason: it does nothing to its input.
 *
 * The bot exists to spell and pronounce an Uzbek recipient's name correctly. Uzbek Latin
 * writes `oʻ` and `gʻ` with U+02BB MODIFIER LETTER TURNED COMMA, and `sanʼat` with U+02BC
 * MODIFIER LETTER APOSTROPHE.
 *
 * ## What actually destroys these two characters — corrected 2026-09-03
 *
 * This comment used to say that `String.prototype.normalize` under NFKD folds U+02BB to a
 * plain ASCII apostrophe. **That is false and was verified false**: all four normalisation
 * forms — NFC, NFD, NFKC and NFKD — are the IDENTITY for U+02BB and U+02BC. Neither
 * character has a compatibility decomposition. The fence below is still right; the reason
 * given for it was not, and a wrong reason is worse than none because it teaches the next
 * reader to trust the wrong test.
 *
 * The three things that really do destroy them:
 *
 * 1. **Case folding.** `"Gʻulom".toLowerCase()` is `"gʻulom"` — the mark survives, the NAME
 *    does not. That is data loss in every locale, not only Turkish or Azeri, and it is the
 *    common case: a "case-insensitive" search or dedupe key applied to display text.
 * 2. **`localeCompare` and locale-aware collation**, which erase the case distinction at
 *    the strength most callers ask for: `sensitivity: "base"` (and `"accent"`) report
 *    `Gʻulom` and `gʻulom` as EQUAL, so a dedupe key or an "is this the same name" check
 *    silently merges two distinct strings. Whether the datum survives depends on an
 *    options bag at the call site, which is why the method is banned here rather than
 *    reviewed case by case. (It does NOT treat the mark as ignorable — `Gʻulom` and
 *    `Gulom` compare non-equal under every option, `ignorePunctuation` included. An
 *    earlier version of this comment said otherwise; `src/lib/uzbekMarks.test.ts`
 *    measures both facts.)
 * 3. **`text-transform: uppercase`**, which alters the name visually with no trace in the
 *    data at all — the DOM still holds the right string and the screen shows the wrong one.
 *
 * **One accidental call anywhere in the render path and the panel shows the operator a
 * different name from the one the customer typed — while claiming, on the very same screen,
 * that name verification passed.**
 *
 * So: the value is rendered as a single text node, unmodified, inside
 * `<span lang="uz-Latn" dir="ltr">`, and the ESLint `no-restricted-syntax` fence over
 * `components/domain/` makes the folding calls unavailable in this directory. Do not add a
 * `className` that uppercases, do not trim, do not truncate with `slice` (that cuts UTF-16
 * units and can split a surrogate pair) — clip with CSS if a column is narrow.
 *
 * ## The codepoint toggle
 *
 * §11.4 pins the rendering: `O<sub>U+02BB</sub>ktam`. When a verification fails the first
 * question is *which* apostrophe the customer typed, and at 14px U+02BB, U+02BC, U+2019 and
 * U+0027 are the same picture. In codepoint mode the ambiguous characters are replaced by
 * their spelled-out `U+XXXX`; everything legible stays as itself, so the name is still
 * readable while the invisible datum becomes visible.
 *
 * ## `null` is not `MASK`
 *
 * `recipientName === null` means the identity was PURGED (check `identityPurgedAt` and
 * render `<PurgedValue>`); `recipientName === "•••"` means the stored name was empty. This
 * component renders `fallback` for `null` and the mask string as itself — it does not
 * collapse the two, and neither should a caller's `??`.
 */

import { useState, type ReactElement, type ReactNode } from "react";

import { Button } from "@/components/util";
import { cn, EMPTY_VALUE } from "@/lib";

import { toCodepoints } from "./codepoints";

/** §11.4 pins this exactly. Uzbek Latin, left to right, on every name the panel draws. */
export const NAME_LANG = "uz-Latn";
export const NAME_DIR = "ltr";

export interface NameTextProps {
  /**
   * The name exactly as the server sent it — masked (`G•••`), whole, or `null` when the
   * identity was purged. Never pre-processed by the caller.
   */
  value: string | null;
  /** Force codepoint spelling on or off. Omit to let the toggle drive it. */
  showCodepoints?: boolean | undefined;
  /** Render the `U+` toggle button beside the name. */
  isToggleable?: boolean | undefined;
  /** What `null` renders as. An em dash by default; pass `<PurgedValue>` where it applies. */
  fallback?: ReactNode;
  className?: string | undefined;
}

export function NameText({
  value,
  showCodepoints,
  isToggleable = false,
  fallback = EMPTY_VALUE,
  className,
}: NameTextProps): ReactElement {
  const [isExpanded, setIsExpanded] = useState(false);
  const isSpelled = showCodepoints ?? isExpanded;

  if (value === null) {
    // The fallback is OUR content, not the customer's, so it does not go inside the
    // language-tagged span.
    return <span className={cn("text-ink-muted", className)}>{fallback}</span>;
  }

  return (
    <span className={cn("inline-flex items-baseline gap-1", className)}>
      <span
        lang={NAME_LANG}
        dir={NAME_DIR}
        data-testid="name-text"
        className="whitespace-pre-wrap break-words"
      >
        {isSpelled ? <SpelledOut value={value} /> : value}
      </span>
      {isToggleable ? (
        <Button
          /*
           * A segment, in the accent hue rather than the brand: pressed, it is the console's
           * secondary idiom painted from `--accent-tint` / `--accent` (4.71:1 light, 4.59:1
           * dark, both measured by `tokenContrast.test.ts` as a family-on-own-tint pair);
           * unpressed, it is `quiet` — no ground at all, rather than the filled grey capsule
           * with a grey label it used to be.
           *
           * `size="none"` because this control's box is 10px monospace and set right here,
           * and because the `chip` rung is `.type-caption`, which uppercases: nothing in the
           * subtree a name lives in may carry that class.
           */
          variant={isSpelled ? "tinted" : "quiet"}
          size="none"
          shape="pill"
          onClick={() => {
            setIsExpanded((current) => !current);
          }}
          aria-pressed={isSpelled}
          title={
            isSpelled ? "hide codepoints" : "spell out the ambiguous characters as codepoints"
          }
          className="type-mono px-1.5 py-0.5 text-[10px] leading-none"
          style={
            isSpelled
              ? { color: "var(--accent)", backgroundColor: "var(--accent-tint)" }
              : {}
          }
        >
          U+
        </Button>
      ) : null}
    </span>
  );
}

/**
 * `O` `<sub>U+02BB</sub>` `ktam`.
 *
 * Only the ambiguous codepoints are spelled out. Spelling out every character would turn
 * `Дилноза` into six subscripts and make the component useless for the case it exists for —
 * the operator needs to READ the name and SEE the tick at the same time.
 */
function SpelledOut({ value }: { value: string }): ReactElement {
  return (
    <>
      {toCodepoints(value).map((point, index) =>
        point.isAmbiguous ? (
          <sub
            key={`${String(index)}:${point.label}`}
            data-codepoint={point.label}
            title={point.label}
            className="type-mono mx-[1px] align-baseline text-[9px] text-accent"
          >
            {point.label}
          </sub>
        ) : (
          <span key={`${String(index)}:${point.label}`}>{point.char}</span>
        ),
      )}
    </>
  );
}
