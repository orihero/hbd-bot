/**
 * `CodeBlock` — §11.4. A verbatim block of text with a copy button.
 *
 * Deliberately un-highlighted. There is no syntax highlighter in this bundle and there
 * should not be one: the things this renders are a correlation id, a stack frame, an error
 * body, a lyric line the operator is checking character by character. A tokeniser that
 * guesses wrong recolours half of that, and a highlighter that mangles a `ʻ` while
 * "prettifying" would be the same data loss `<NameText>` exists to prevent, arriving through
 * a different door.
 *
 * So: `white-space: pre`, the mono token, and nothing between the string and the DOM. The
 * only transform is splitting on newlines to draw the gutter, and the gutter is
 * `aria-hidden` so a screen reader and a copy both get the code without line numbers in it.
 */

import { type ReactElement } from "react";

import { cn } from "@/lib";

import { useCopy } from "./useCopy";

export interface CodeBlockProps {
  /** Rendered verbatim. Never normalised, never trimmed per line. */
  readonly code: string;
  /** A label for the corner: `json`, `traceback`, `sql`. Ours, not the content's. */
  readonly language?: string;
  /** Wrap long lines instead of scrolling horizontally. Off by default: a wrapped
   *  traceback is harder to read than a scrolled one. */
  readonly isWrapped?: boolean;
  readonly showLineNumbers?: boolean;
  /** Caps the height; the block scrolls inside. */
  readonly maxHeight?: string;
  readonly className?: string;
  /** Names the region for assistive tech. */
  readonly label?: string;
}

export function CodeBlock({
  code,
  language,
  isWrapped = false,
  showLineNumbers = false,
  maxHeight,
  className,
  label = "code",
}: CodeBlockProps): ReactElement {
  const { copy, isCopied, isFailed } = useCopy();
  const lines = code.split(/\r?\n/);

  return (
    <figure
      /*
       * `--surface-sunken` is the inset well, and it is now defined in BOTH themes — the old
       * `--bg-inset` had no light value at all, so every code block on a white page was a
       * dark-theme surface wearing light-theme text.
       */
      className={cn(
        "group relative overflow-hidden rounded-2xl bg-surface-sunken",
        className,
      )}
      aria-label={label}
    >
      <div className="absolute right-3 top-3 z-10 flex items-center gap-2">
        {/*
         * Both chips sit on the SUNKEN well, so both take an OPAQUE ground rather than a
         * tint. A `-tint` is 14% alpha and is measured composited over the card and over the
         * page only; composited over `--surface-sunken` it lands ~0.2 of a ratio point lower,
         * which is enough to drop `--success` on `--success-tint` under 4.5:1 in the light
         * palette. An opaque chip is measured exactly where it is painted.
         */}
        {language !== undefined && (
          <span className="type-caption rounded-pill bg-surface-control px-2 py-0.5 text-ink-muted">
            {language}
          </span>
        )}
        <button
          type="button"
          onClick={() => {
            copy(code);
          }}
          aria-label={isCopied ? "copied" : `copy ${label}`}
          className={cn(
            "type-caption rounded-pill px-2.5 py-1",
            "opacity-0 transition-opacity duration-fast ease-standard",
            "focus-visible:opacity-100 group-hover:opacity-100",
            /* A raised chip on the recessed well: `--surface-card` is opaque, so the hue on
               top of it is measured on one of the five surfaces rather than on a tint over a
               surface the tint was never composited against. */
            "bg-surface-card shadow-2xs",
            isCopied ? "text-success" : isFailed ? "text-caution" : "text-ink",
          )}
        >
          <span aria-hidden="true">{isCopied ? "✓" : isFailed ? "!" : "⧉"}</span>{" "}
          {isCopied ? "copied" : isFailed ? "no clipboard" : "copy"}
        </button>
      </div>

      <pre
        className={cn(
          "type-mono overflow-auto p-4 text-ink",
          isWrapped ? "whitespace-pre-wrap break-words" : "whitespace-pre",
        )}
        style={maxHeight === undefined ? undefined : { maxHeight }}
      >
        {showLineNumbers ? (
          <code className="grid grid-cols-[auto_1fr] gap-x-3">
            {lines.map((line, index) => (
              // Line numbers are positional by definition, so the index IS the identity.
              <span key={`${String(index)}:${line}`} className="contents">
                <span aria-hidden="true" className="num select-none text-right text-ink-muted">
                  {index + 1}
                </span>
                <span>{line}</span>
              </span>
            ))}
          </code>
        ) : (
          <code>{code}</code>
        )}
      </pre>
    </figure>
  );
}
