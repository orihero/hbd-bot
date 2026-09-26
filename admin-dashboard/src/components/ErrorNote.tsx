import { CircleAlert, RefreshCw, ShieldOff, WifiOff, type LucideIcon } from "lucide-react";
import type { JSX } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * Why a section of a page has nothing to show, stated in the section's own place.
 *
 * A dashboard fails in pieces — one of six routes 500s, one is forbidden to this role, the
 * network drops for a second — and a whole-page error screen throws away the five sections
 * that answered. This is the per-section alternative: it occupies exactly the band the missing
 * cards would have, says which read failed and what the server said about it, and offers the
 * only useful action, which is asking again.
 *
 * The four tones are four different facts, not four severities:
 *   `error`   the server answered, and the answer was a failure.
 *   `denied`  403 — the request was understood and refused. Nothing to retry, so no button.
 *   `offline` the request never reached the server at all (`status: 0`).
 *   `stale`   the section HAS numbers on screen; it is the refresh that is failing. Quietest,
 *             because the cards below it are still true — they are just not moving.
 */
export type NoteTone = "error" | "denied" | "offline" | "stale";

const ICON: Record<NoteTone, LucideIcon> = {
  error: CircleAlert,
  denied: ShieldOff,
  offline: WifiOff,
  stale: RefreshCw,
};

/** `required` is the only alarm colour the token set has; the quiet tones stay in the ink ramp. */
const ICON_CLASS: Record<NoteTone, string> = {
  error: "text-required",
  denied: "text-ink-400",
  offline: "text-ink-400",
  stale: "text-ink-300",
};

const GROUND: Record<NoteTone, string> = {
  error: "bg-card ring-1 ring-inset ring-required-24",
  denied: "bg-card ring-1 ring-inset ring-stroke",
  offline: "bg-card ring-1 ring-inset ring-stroke",
  stale: "bg-card ring-1 ring-inset ring-stroke",
};

interface ErrorNoteProps {
  readonly tone: NoteTone;
  /** One line naming what is missing — "Finances failed to load". */
  readonly title: string;
  /** The API's own message, verbatim. Never a rewritten one: the operator greps for it. */
  readonly message: string;
  /** Endpoint and correlation id — what gets pasted into a bug report. */
  readonly hint?: string | undefined;
  /** Omitted when asking again cannot change the answer (403, a contract mismatch). */
  readonly onRetry?: (() => void) | undefined;
  readonly isRetrying?: boolean | undefined;
  /**
   * `false` withholds the Retry even though `onRetry` was passed.
   *
   * The two are separate because the caller usually holds ONE retry callback for a query and
   * decides per failure whether pressing it could change anything. It cannot for a 403
   * (`FORBIDDEN`, `CSRF_REJECTED`, `ORIGIN_REJECTED`, and the router-level `STEP_UP_REQUIRED`
   * that carries no `details`) or for a 422 `INVALID_INPUT`: the request was understood and
   * refused, so the same request refused again is the only outcome, plus a second
   * `permission.denied` audit row against an operator who did nothing wrong. A button that
   * always fails is worse than no button.
   *
   * `REVEAL_BUDGET_EXHAUSTED` and `REAUTH_RATE_LIMITED` are also `false` here, but for a
   * different reason: they DO become retryable, after `retryAfterS`. Say when, in `message`.
   */
  readonly retryable?: boolean | undefined;
}

export function ErrorNote({
  tone,
  title,
  message,
  hint,
  onRetry,
  isRetrying = false,
  retryable = true,
}: ErrorNoteProps): JSX.Element {
  const { t } = useI18n();
  const Icon = ICON[tone];

  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-card px-4 py-3 text-ink-900",
        GROUND[tone],
      )}
    >
      <Icon
        className={cn("mt-[1px] h-4 w-4 shrink-0", ICON_CLASS[tone])}
        strokeWidth={1.75}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[12px] font-semibold leading-[1.3] tracking-[-.1px] text-ink-900">
          {title}
        </p>
        <p className="mb-0 mt-[2px] text-[11px] font-normal leading-[1.35] text-ink-400">
          {message}
        </p>
        {hint === undefined ? null : (
          /* The endpoint and the correlation id — read character by character and pasted into
             a ticket, so it gets the kit's 12px cell and --ink-500 (7.0:1) rather than 10px
             --ink-300 (3.3:1, under AA). Monospace for the same reason `l` and `1` have to be
             told apart. `whitespace-nowrap` because the ellipsis only fires on one line. */
          <p className="mb-0 mt-[3px] overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[12px] font-normal leading-[16.392px] text-ink-500">
            {hint}
          </p>
        )}
      </div>
      {onRetry === undefined || !retryable ? null : (
        <button
          type="button"
          onClick={onRetry}
          disabled={isRetrying}
          className={cn(
            "flex h-7 shrink-0 items-center gap-[6px] rounded-chip bg-bg px-3 text-[11px] font-semibold tracking-[-.1px] text-ink-900",
            "transition-[color,background-color,filter] hover:brightness-95 active:brightness-90",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
            "disabled:cursor-progress disabled:text-ink-300",
          )}
        >
          <RefreshCw
            className={cn("h-3 w-3", isRetrying && "animate-spin motion-reduce:animate-none")}
            strokeWidth={2}
            aria-hidden
          />
          {isRetrying ? t("common.retrying") : t("common.retry")}
        </button>
      )}
    </div>
  );
}
