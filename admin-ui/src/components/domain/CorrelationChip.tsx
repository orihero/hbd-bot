/**
 * `<CorrelationChip>` — the 32-hex id that joins this screen to the worker's logs.
 *
 * A correlation id is only useful if it reaches a `grep`, so the chip is a copy button
 * first and a label second. It shows the first eight characters (enough to recognise, short
 * enough for a table cell) and copies ALL thirty-two — copying the truncation would be
 * worse than copying nothing, because it fails silently in the log search.
 *
 * An id that does not match `CORRELATION_ID_PATTERN` is still rendered, flagged rather than
 * hidden: a malformed correlation id is a real bug worth seeing, and hiding it makes the
 * bug invisible exactly when someone is trying to trace a request.
 *
 * `navigator.clipboard` is absent on an insecure origin and in jsdom, so the failure path
 * is a state, not an exception — and the promise is never left floating (the ESLint rule
 * that catches that is the frontend twin of the repo's never-throw client).
 */

import { useState, type ReactElement } from "react";

import { CORRELATION_ID_PATTERN } from "@/api";
import { Button } from "@/components/util";
import { cn, EMPTY_VALUE } from "@/lib";

export interface CorrelationChipProps {
  correlationId: string | null;
  /** How many leading characters to show. The whole id is always what gets copied. */
  visibleChars?: number | undefined;
  className?: string | undefined;
}

type CopyState = "idle" | "copied" | "failed";

export function CorrelationChip({
  correlationId,
  visibleChars = 8,
  className,
}: CorrelationChipProps): ReactElement {
  const [copyState, setCopyState] = useState<CopyState>("idle");

  if (correlationId === null || correlationId === "") {
    return <span className={cn("text-ink-muted", className)}>{EMPTY_VALUE}</span>;
  }

  const isWellFormed = CORRELATION_ID_PATTERN.test(correlationId);
  // `slice` on a hex id is safe: it is our own ASCII, not user content. It would NOT be
  // safe on a name — that is what `<NameText>` and CSS clipping are for.
  const shown = correlationId.slice(0, visibleChars);

  const copy = (): void => {
    // `lib.dom` types `navigator.clipboard` as always present; it is absent on an
    // insecure origin and in jsdom, so it is read through a shape that admits that.
    const { clipboard } = navigator as { clipboard?: Clipboard };
    if (clipboard === undefined) {
      setCopyState("failed");
      return;
    }
    clipboard.writeText(correlationId).then(
      () => {
        setCopyState("copied");
      },
      () => {
        setCopyState("failed");
      },
    );
  };

  return (
    <Button
      /*
       * `quiet`: no ground until hover. It used to be a filled `--surface-control` capsule
       * with an `--ink-muted` label — grey on grey, the shape this design rules out — and it
       * is not re-pointed at a hue, because a correlation id carries no state and a brand
       * chip beside an order ref would claim it did. `TelegramUserChip` already reads this
       * way; the two now agree.
       */
      variant="quiet"
      size="none"
      shape="pill"
      onClick={copy}
      data-testid="correlation-chip"
      data-correlation-id={correlationId}
      data-copy-state={copyState}
      title={`${correlationId}${isWellFormed ? "" : " — not a 32-hex correlation id"}`}
      aria-label={`copy correlation id ${correlationId}`}
      className={cn("type-mono items-baseline gap-1 px-2 py-0.5", className)}
    >
      {isWellFormed ? null : (
        <span aria-hidden="true" style={{ color: "var(--caution)" }}>
          ⚠
        </span>
      )}
      <span>{shown}</span>
      <span className="text-ink-muted" aria-hidden="true">
        {copyState === "copied" ? "✓" : copyState === "failed" ? "✗" : "⧉"}
      </span>
    </Button>
  );
}
