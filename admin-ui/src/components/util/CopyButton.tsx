/**
 * Copy one value to the clipboard.
 *
 * It exists for a specific sentence in §11.4: the error state "shows the code and a
 * **copyable** correlation id". A 32-hex id is the join key between this console, the
 * server log and the audit row; retyping it by eye is how an incident gets attached to the
 * wrong request.
 *
 * Two details are not decoration:
 *
 *  - The confirmation is announced, not just drawn. An operator who copies with the
 *    keyboard gets `aria-live` text, because a tick that only appears is invisible to them.
 *  - A failure is shown, never swallowed. `navigator.clipboard` is undefined outside a
 *    secure context and can be refused by permissions policy; a button that silently does
 *    nothing is worse than one that says it could not copy, since the operator would paste
 *    whatever was in the clipboard before.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** How long the tick stays up. Long enough to read, short enough not to look stuck. */
const CONFIRM_MS = 1_400;

export interface CopyButtonProps {
  /** The exact text to place on the clipboard. Never transformed. */
  readonly value: string;
  /** What is being copied, for the accessible name: "Copy correlation id". */
  readonly label?: string;
  /** Show the value beside the glyph. Off by default — most callers render it themselves. */
  readonly withValue?: boolean;
  readonly className?: string;
}

type CopyPhase = "idle" | "copied" | "failed";

export function CopyButton({ value, label = "value", withValue = false, className }: CopyButtonProps) {
  const [phase, setPhase] = useState<CopyPhase>("idle");
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    const settle = (next: CopyPhase): void => {
      setPhase(next);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        setPhase("idle");
      }, CONFIRM_MS);
    };

    // `lib.dom` types `navigator.clipboard` as always present. It is genuinely absent
    // outside a secure context and can be removed by a permissions policy — which is the
    // case this component exists to REPORT rather than swallow — so the read goes through a
    // shape that admits the truth.
    const { clipboard } = navigator as Omit<Navigator, "clipboard"> & {
      clipboard?: Clipboard;
    };
    if (clipboard === undefined) {
      settle("failed");
      return;
    }
    void clipboard.writeText(value).then(
      () => {
        settle("copied");
      },
      () => {
        settle("failed");
      },
    );
  }, [value]);

  const glyph = phase === "copied" ? "✓" : phase === "failed" ? "✗" : "⧉";
  const tone =
    phase === "copied"
      ? "text-success"
      : phase === "failed"
        ? "text-error"
        : "text-ink-muted hover:text-ink";

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <button
        type="button"
        onClick={onCopy}
        aria-label={`Copy ${label}`}
        className={cn(
          "inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1",
          "transition-colors duration-fast ease-standard",
          "hover:bg-surface-control focus-visible:bg-surface-control",
          tone,
        )}
      >
        <span aria-hidden="true">{glyph}</span>
      </button>
      {withValue ? <span className="type-mono text-ink">{value}</span> : null}
      <span className="sr-only" role="status" aria-live="polite">
        {phase === "copied" ? `${label} copied` : phase === "failed" ? `could not copy ${label}` : ""}
      </span>
    </span>
  );
}
