/**
 * §11.4 lists TWO empty states and the distinction is the whole point.
 *
 *  - **Empty-virgin** — nothing exists yet. "No orders have been placed" is a fact about the
 *    product.
 *  - **Empty-filtered** — things exist, this filter excludes them all. It must name the
 *    filter count and offer **Clear**, because the operator's next thought is "did I break
 *    the query or is it really zero?" and a shared "No results" answers neither.
 *
 * Getting this wrong is a support incident during an incident: an operator filters to
 * `state=failed`, sees "No orders", and concludes the console is broken rather than that
 * nothing has failed.
 *
 * The reskin gave it the shape the rest of the language uses for an absence: a centred card
 * with generous padding, a glyph, a short bold line, a muted line and ONE pill button. The
 * dashed border is gone — this design draws no borders, and a dashed one was the old
 * language's way of saying "there would be something here", which the padding now says.
 */

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./Button";

export interface EmptyStateProps {
  /** A glyph from our own vocabulary. Never an image, never a mascot. */
  readonly glyph?: string;
  readonly title: string;
  readonly body?: ReactNode;
  /** A button or link. The filtered variant puts **Clear** here. */
  readonly action?: ReactNode;
  readonly className?: string;
}

export function EmptyState({ glyph = "○", title, body, action, className }: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-card bg-surface-card",
        "px-6 py-12 text-center shadow-card",
        className,
      )}
    >
      {/*
       * A decorative mark, `aria-hidden`, carrying no information the title does not.
       * `--ink-muted`, NOT the policed `--ink-mark`: this glyph is the largest thing on an
       * otherwise empty card and the first thing the eye lands on, so it should clear the
       * text bar even though, formally, 1.4.11's 3:1 would do. It needs no waiver, which is
       * the other half of the point.
       */}
      <span aria-hidden="true" className="text-[28px] leading-none text-ink-muted">
        {glyph}
      </span>
      <p className="type-h2 text-ink">{title}</p>
      {body === undefined ? null : (
        <div className="type-body-sm max-w-prose text-ink-muted">{body}</div>
      )}
      {action === undefined ? null : <div className="mt-2">{action}</div>}
    </div>
  );
}

export interface FilteredEmptyStateProps {
  /** How many filters are narrowing the list. `SearchParamsState.activeCount` gives it. */
  readonly activeFilterCount: number;
  /** Clears every filter. Omitted only when the caller genuinely has no way to. */
  readonly onClear?: (() => void) | undefined;
  /** What is being filtered — "orders", "attempts". Lower case, our own noun. */
  readonly noun?: string;
  /**
   * Override the generic headline when the caller can NAME the filter that excluded
   * everything — "No attempts between 20 Mar and 21 Mar". A screen filtered by one window
   * can say which window; a screen filtered by six chips cannot, and gets the default.
   */
  readonly title?: string | undefined;
  /** Override the body. The caller that overrides it owes the reader the filter count. */
  readonly body?: ReactNode;
  readonly className?: string;
}

/**
 * The filtered variant, with §11.4's required copy: the filter count, and a Clear.
 *
 * The count is stated rather than implied ("3 filters are active") so the operator can tell
 * at a glance whether the URL they pasted carried more constraints than they remembered.
 */
export function FilteredEmptyState({
  activeFilterCount,
  onClear,
  noun = "rows",
  title,
  body,
  className,
}: FilteredEmptyStateProps) {
  const plural = activeFilterCount === 1 ? "filter is" : "filters are";
  return (
    <EmptyState
      glyph="⊘"
      title={title ?? `No ${noun} match these filters`}
      body={
        body ?? (
        <>
          <span className="num">{activeFilterCount}</span> {plural} narrowing this list. There may
          be {noun} outside them.
        </>
        )
      }
      action={
        onClear === undefined ? undefined : (
          /* The design's primary button, from the one definition: solid brand, white label
             at 4.95:1, in the pill shape an empty state's single call to action wears. */
          <Button variant="primary" shape="pill" onClick={onClear}>
            Clear filters
          </Button>
        )
      }
      {...(className === undefined ? {} : { className })}
    />
  );
}
