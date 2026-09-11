/**
 * `<ErrorCodeBadge>` — an error code plus the one thing the operator actually decides on.
 *
 * §11.3/§11.4: error badges add `↻` retryable (the caution hue) vs `■` terminal (the error
 * hue), driven by `BayramError.is_retryable`, because **"is retrying worth anything" is the
 * real question and it is one glyph away**. Under the reskin the hue moved from a 2px left
 * rule to a tinted capsule ground and to the glyph; the glyph and the word are unchanged,
 * so the badge still reads in greyscale.
 *
 * `isRetryable` is TRI-STATE and the third state is not a falsy second one. `null` means no
 * class in `bayram.errors` claims this code — the system has no opinion, so the badge says
 * `unknown` (`UNKNOWN_RETRYABILITY_LABEL`) and offers no retry. "unknown" is an ABSENT
 * decision; "terminal" is a decision. Only the second justifies hiding a retry control as
 * settled, and rendering the first as the second is how an operator gives up on an order
 * that would have gone through.
 *
 * The code itself is rendered VERBATIM in mono and is never humanised: it is the string an
 * operator greps the worker log for, and `SUNO_TIMEOUT` → `SUNO TIMEOUT` breaks that.
 */

import type { ReactElement } from "react";

import { UNKNOWN_RETRYABILITY_LABEL } from "@/api";
import { cn, EMPTY_VALUE, retryabilityGlyph, retryabilityLabel } from "@/lib";

import { retryabilityColorVar, tintVar } from "./colors";

export interface ErrorCodeBadgeProps {
  /** `null` groups failures whose writer recorded no code — still a badge, never a blank. */
  code: string | null;
  /** Tri-state. `null` renders "unknown", never "terminal". */
  isRetryable: boolean | null;
  /**
   * OUR operator prose (`AttemptWireView.errorMessage`, `OrderView.failedReason`), never a
   * customer's words. Shown as a second line when present.
   */
  message?: string | null | undefined;
  size?: "sm" | "md" | undefined;
  className?: string | undefined;
}

export function ErrorCodeBadge({
  code,
  isRetryable,
  message,
  size = "sm",
  className,
}: ErrorCodeBadgeProps): ReactElement {
  const color = retryabilityColorVar(isRetryable);
  // `var(--retryable)` → `var(--retryable-tint)`, from the same lookup, so the ground and
  // the glyph can never name different decisions.
  const tint = tintVar(color);
  const label = isRetryable === null ? UNKNOWN_RETRYABILITY_LABEL : retryabilityLabel(isRetryable);

  return (
    <span
      data-testid="error-code-badge"
      data-retryability={label}
      className={cn(
        // No left rule and no border: the hue is a tinted ground now (this design draws no
        // 1px edges), and the decision still arrives through THREE channels — the glyph,
        // the word, and the tint.
        "inline-flex max-w-full flex-col gap-0.5 rounded-2xs px-2.5 py-1",
        className,
      )}
      style={{ backgroundColor: tint }}
    >
      <span className="inline-flex flex-wrap items-baseline gap-2">
        {/* The code is `--ink`, not the hue: it is the string an operator greps for and it
            is the longest run of characters in the badge, so it gets the readable token.
            Measured on the three grounds this badge can wear — `--retryable-tint`,
            `--terminal-tint`, `--slate-tint` — `--ink` is 6.96:1 at its worst in light and
            7.97:1 in dark. The hue beside it (`--retryable` and co. on their own tints) is
            4.71:1 at its worst in light, 4.60:1 in dark.

            Those figures now hold on EVERY surface, which is new and is what makes the word
            below legal. The tints used to be translucent, so this badge's ratios were a
            property of whatever it was dropped onto: inside a `DataTable` row the operator
            was hovering, the retryability WORD — 11px `type-caption`, so the 4.5:1 bar
            applies to it — fell to 3.90:1. The tints are opaque now (see the long note in
            tokens.css), so a badge reads the same on a hovered row, in a sunken well and on
            a card, and there is one number per palette rather than one per ground. */}
        <span
          className={cn("type-mono text-ink", size === "sm" ? "text-[12px]" : "")}
          data-testid="error-code"
        >
          {code ?? EMPTY_VALUE}
        </span>
        <span
          data-testid="error-code-retryability"
          className="type-caption inline-flex items-baseline gap-1"
          style={{ color }}
        >
          <span aria-hidden="true">{retryabilityGlyph(isRetryable)}</span>
          <span>{label}</span>
        </span>
      </span>
      {message === null || message === undefined || message === "" ? null : (
        <span className="type-body-sm text-ink-muted">{message}</span>
      )}
    </span>
  );
}
