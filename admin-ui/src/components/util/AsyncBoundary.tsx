/**
 * §11.4's six states, from one component.
 *
 * Every panel that reads the API wraps its body in this. The precedence lives in
 * `asyncState.ts`; what is here is the rendering, and three of the six are worth reading
 * before using it:
 *
 *  - **Skeleton** takes a `skeleton` node from the CALLER, because "matching final
 *    dimensions exactly" is a claim only the caller can honour. There is deliberately no
 *    default: a generic grey box would silently reintroduce the reflow.
 *  - **Stale** renders the last-known children at 70% opacity behind a `stale 42s` chip that
 *    counts up in real time. It is `aria-busy`, not `role="alert"` — the numbers are still
 *    true, they are just old.
 *  - **Purged** is `🔒 purged 2026-05-14` plus the clock that did it. §14's acceptance names
 *    that string for the orders list: "not an error and not a blank".
 *
 * The reskin restyled all six and changed none of them. Empty-virgin and empty-filtered are
 * still different states with different copy, stale still shows the age chip and still keeps
 * the last-known numbers at 70%, and purged still renders the lock, the date and the clock —
 * as a centred card now, with the padding the rest of the language uses, but with the same
 * words in the same order.
 */

import type { ReactNode } from "react";

import { failureOf } from "@/api";
import { staleSeconds } from "@/lib/queryClient";
import { formatDate } from "@/lib/format";
import { usePrefsStore } from "@/lib/stores";
import { cn } from "@/lib/utils";

import { EmptyState, FilteredEmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { resolveAsyncState, type AsyncStateKind } from "./asyncState";
import { useNow } from "./hooks";

export interface AsyncBoundaryProps {
  /** TanStack Query's `status`. */
  readonly status: "pending" | "error" | "success";
  /** `query.data !== undefined`. Defaults to "there is data iff the query succeeded". */
  readonly hasData?: boolean | undefined;
  /** Whether the data in hand is an empty list. */
  readonly isEmpty?: boolean | undefined;
  /** `SearchParamsState.activeCount`, so the filtered-empty copy can name it. */
  readonly activeFilterCount?: number | undefined;
  readonly onClearFilters?: (() => void) | undefined;

  /** `query.error`. Unwrapped to an `ApiFailure` by `ErrorState`. */
  readonly error?: unknown;
  readonly onRetry?: (() => void) | undefined;
  /** `query.dataUpdatedAt`, for the stale chip. */
  readonly dataUpdatedAt?: number | undefined;

  /**
   * The purge stamp, when this panel's subject has one. Non-null forces the purged state
   * over every other — see the precedence note in `asyncState.ts`.
   */
  readonly purgedAt?: string | null | undefined;
  /**
   * WHICH clock did it — "identity retention clock", "operator purge request". §11.4 asks
   * for it by name and §12.3 is why: a purge on schedule and a purge on request are
   * different facts about the same absent value.
   */
  readonly purgedBy?: string | null | undefined;

  /** REQUIRED. Must match the finished layout's dimensions. */
  readonly skeleton: ReactNode;

  /** What this panel holds, lower case, our own noun: "orders", "attempts", "the pulse". */
  readonly noun?: string;
  /** Empty-virgin copy. The default states the fact rather than apologising for it. */
  readonly emptyTitle?: string | undefined;
  readonly emptyBody?: ReactNode;
  /**
   * Empty-FILTERED copy, for a panel whose filter can be named. §11.4 requires the filtered
   * state to name the filter count and offer Clear; a screen scoped by a single time window
   * can do better and name the window itself, which is the difference between "no rows" and
   * "no rows in the range you chose". The Clear affordance is unchanged either way.
   */
  readonly emptyFilteredTitle?: string | undefined;
  readonly emptyFilteredBody?: ReactNode;

  readonly className?: string;
  readonly children: ReactNode;
}

/** Which of the six this render is. The precedence itself lives in `asyncState.ts`. */
function asyncStateOf(props: AsyncBoundaryProps, now?: number): AsyncStateKind {
  return resolveAsyncState({
    status: props.status,
    hasData: props.hasData ?? props.status === "success",
    isEmpty: props.isEmpty ?? false,
    activeFilterCount: props.activeFilterCount ?? 0,
    purgedAt: props.purgedAt ?? null,
    dataUpdatedAt: props.dataUpdatedAt ?? 0,
    now,
  });
}

export function AsyncBoundary(props: AsyncBoundaryProps) {
  const {
    error,
    onRetry,
    onClearFilters,
    activeFilterCount = 0,
    dataUpdatedAt = 0,
    purgedAt = null,
    purgedBy = null,
    skeleton,
    noun = "rows",
    emptyTitle,
    emptyBody,
    emptyFilteredTitle,
    emptyFilteredBody,
    className,
    children,
  } = props;

  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);
  const kind = asyncStateOf(props);
  // The clock only ticks while something on screen is ageing. A healthy panel installs no
  // interval at all.
  const now = useNow(1_000, kind === "stale");

  if (kind === "purged") {
    return (
      <div
        role="status"
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-card bg-surface-card",
          "px-6 py-10 text-center shadow-card",
          className,
        )}
      >
        {/*
         * The lock stays ON the line with the words. It is tempting to promote it to a big
         * centred glyph above them, the way the empty and error cards do, but §14's
         * acceptance quotes the whole string `🔒 purged <date>` and a purge is the one
         * absence this console is graded on rendering exactly.
         */}
        <p className="type-body font-semibold text-ink">
          <span aria-hidden="true">🔒</span> purged{" "}
          <span className="num">{formatDate(purgedAt, timeZoneMode)}</span>
        </p>
        <p className="type-body-sm max-w-prose text-ink-muted">
          {purgedBy === null
            ? "This data was removed by a retention clock."
            : `Removed by the ${purgedBy}.`}
        </p>
      </div>
    );
  }

  if (kind === "skeleton") {
    return (
      <div aria-busy="true" className={className}>
        <span className="sr-only" role="status">
          Loading {noun}
        </span>
        {skeleton}
      </div>
    );
  }

  if (kind === "error") {
    return (
      <ErrorState
        error={error}
        what={noun}
        {...(onRetry === undefined ? {} : { onRetry })}
        {...(className === undefined ? {} : { className })}
      />
    );
  }

  if (kind === "empty-filtered") {
    return (
      <FilteredEmptyState
        activeFilterCount={activeFilterCount}
        onClear={onClearFilters}
        noun={noun}
        {...(emptyFilteredTitle === undefined ? {} : { title: emptyFilteredTitle })}
        {...(emptyFilteredBody === undefined ? {} : { body: emptyFilteredBody })}
        {...(className === undefined ? {} : { className })}
      />
    );
  }

  if (kind === "empty-virgin") {
    return (
      <EmptyState
        title={emptyTitle ?? `No ${noun} yet`}
        {...(emptyBody === undefined ? {} : { body: emptyBody })}
        {...(className === undefined ? {} : { className })}
      />
    );
  }

  if (kind === "stale") {
    const seconds = dataUpdatedAt === 0 ? null : staleSeconds(dataUpdatedAt, now);
    // When the poll is not merely late but FAILING, the code goes on the chip. Without it a
    // panel stuck at "stale 300s" gives the operator nothing to search a log for; with it,
    // the numbers still survive at 70% and the reason is one glance away.
    const staleFailure = failureOf(error);
    return (
      <div className={cn("relative", className)} aria-busy="true">
        <div className="pointer-events-none absolute right-2 top-2 z-10 flex items-center gap-2">
          {staleFailure === null ? null : (
            <code className="type-mono rounded-2xs bg-surface-control px-2 py-0.5 text-ink">
              {staleFailure.code}
            </code>
          )}
          <span
            role="status"
            className={cn(
              "type-caption num inline-flex items-center gap-1.5 rounded-pill",
              // Two things this class list is careful about:
              //   1. No `/40` opacity modifiers. The Tailwind colours are `var(--token)`
              //      strings; an alpha modifier on one produces an invalid colour that
              //      fails silently. `--caution-tint` IS the family's translucent member.
              //   2. The word is `--ink` and the hue is the dot. `--ink` is measured over
              //      every tint in both palettes (6.61:1 at worst); the dot is a graphical
              //      object at 1.4.11's 3:1, which `--caution-fill` clears.
              "bg-caution-tint px-2.5 py-1 text-ink shadow-2xs",
            )}
          >
            <span aria-hidden="true" className="leading-none text-caution-fill">
              ●
            </span>
            {seconds === null ? "stale" : `stale ${String(seconds)}s`}
          </span>
        </div>
        {/*
         * 70% opacity, per §11.4. The numbers underneath are the last true ones — dimming
         * says "old", blanking would say "gone", and only one of those is accurate.
         */}
        <div className="opacity-70 transition-opacity duration-base ease-standard">{children}</div>
      </div>
    );
  }

  return <div className={className}>{children}</div>;
}
