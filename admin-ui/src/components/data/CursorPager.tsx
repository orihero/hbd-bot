/**
 * `CursorPager` — §11.4's pager for a keyset-paged list.
 *
 * The API pages on an opaque cursor encoding `(created_at, id)`, not on an offset. Three
 * consequences shape this component and none of them are negotiable:
 *
 *  1. **There is no page number and there cannot be one.** A keyset cursor has no ordinal;
 *     rendering "page 3 of 40" would require an offset count the API deliberately does not
 *     compute. What is honest is the range of rows currently on screen.
 *  2. **Backwards is a client-side stack, not a `prevCursor`.** The API returns only
 *     `nextCursor`, so "previous" means "re-request the cursor we came from". This component
 *     keeps that history and drops it the moment the caller resets to page one — which is
 *     exactly what `useSearchParamsState`'s `patch`/`setValue` do on every filter change,
 *     because a cursor from a previous filter continues a list that no longer exists.
 *  3. **`total` is optional and capped.** `withTotal` is opt-in and `bounded_total` stops
 *     counting at `TOTAL_COUNT_CAP`, so `{total: 10000, isTotalExact: false}` renders
 *     `10,000+` via `formatTotal`. A flat `10,000` there is a wrong number, not a rounded
 *     one — and an absent total is not zero, it is "not counted".
 */

import { useCallback, useEffect, useRef, type ReactElement } from "react";

import { MAX_PAGE_LIMIT, MIN_PAGE_LIMIT, type PageMeta } from "@/api";
import { Button } from "@/components/util";
import { cn, formatInteger, formatTotal } from "@/lib";

/** The limits offered in the page-size control. All within `[MIN_PAGE_LIMIT, MAX_PAGE_LIMIT]`. */
export const PAGE_LIMIT_CHOICES = [25, 50, 100, 200] as const satisfies readonly number[];

export interface CursorPagerProps {
  /** The page envelope's `meta`. `null` while the first page is still loading. */
  readonly meta: PageMeta | null | undefined;
  /** How many rows are on screen right now. */
  readonly itemCount: number;
  /** The cursor that produced the current page; `null` on page one. */
  readonly cursor: string | null;
  /** Ask for a different page. `null` means "back to page one". */
  readonly onCursorChange: (cursor: string | null) => void;
  /** The page size in force. */
  readonly limit: number;
  /** Omit to hide the page-size control. */
  readonly onLimitChange?: (limit: number) => void;
  /** Disables both buttons while a page is in flight, so a double click cannot skip one. */
  readonly isFetching?: boolean;
  readonly className?: string;
  /** Names the widget for assistive tech: `orders`, `audit entries`, … */
  readonly label?: string;
}

export function CursorPager({
  meta,
  itemCount,
  cursor,
  onCursorChange,
  limit,
  onLimitChange,
  isFetching = false,
  className,
  label = "results",
}: CursorPagerProps): ReactElement {
  /**
   * The cursors of the pages behind us, oldest first. `[]` means we are on page one.
   *
   * A ref rather than state: it is never rendered directly, and re-rendering the pager when
   * it changes would be a render caused by nothing the operator can see.
   */
  const history = useRef<string[]>([]);

  // The caller reset to page one — a filter changed, or Clear was pressed. Anything we had
  // walked through belongs to a list that no longer exists.
  useEffect(() => {
    if (cursor === null) history.current = [];
  }, [cursor]);

  const nextCursor = meta?.nextCursor ?? null;
  const hasNext = nextCursor !== null && !isFetching;
  const hasPrevious = cursor !== null && !isFetching;

  const goNext = useCallback(() => {
    if (nextCursor === null) return;
    history.current = cursor === null ? [] : [...history.current, cursor];
    onCursorChange(nextCursor);
  }, [cursor, nextCursor, onCursorChange]);

  const goPrevious = useCallback(() => {
    const previous = history.current[history.current.length - 1] ?? null;
    history.current = history.current.slice(0, -1);
    onCursorChange(previous);
  }, [onCursorChange]);

  const pageIndex = history.current.length + (cursor === null ? 0 : 1);
  const firstRow = itemCount === 0 ? 0 : pageIndex * limit + 1;
  const lastRow = pageIndex * limit + itemCount;

  return (
    <nav
      aria-label={`${label} pagination`}
      className={cn(
        /* No `border-t`. The pager sits inside the table's own card, and this design
           separates a footer from a grid with space rather than with a rule. */
        "flex flex-wrap items-center justify-between gap-3 px-5 pb-4 pt-3",
        className,
      )}
    >
      <p className="type-body-sm text-ink-muted" aria-live="polite">
        {itemCount === 0 ? (
          <span>no {label}</span>
        ) : (
          <>
            <span className="num text-ink">
              {formatInteger(firstRow)}–{formatInteger(lastRow)}
            </span>{" "}
            {meta?.total === null || meta?.total === undefined ? (
              <span>{label}</span>
            ) : (
              <>
                of{" "}
                <span className="num text-ink">
                  {formatTotal(meta.total, meta.isTotalExact)}
                </span>{" "}
                {label}
              </>
            )}
          </>
        )}
      </p>

      <div className="flex items-center gap-2">
        {onLimitChange !== undefined && (
          <label className="type-body-sm flex items-center gap-2 text-ink-muted">
            <span>rows</span>
            <select
              className="num rounded-control bg-surface-control px-3 py-1.5 text-ink"
              value={limit}
              onChange={(event) => {
                const next = Number(event.target.value);
                if (!Number.isInteger(next)) return;
                if (next < MIN_PAGE_LIMIT || next > MAX_PAGE_LIMIT) return;
                // A page size change restarts the list: the cursor was cut for the old size.
                history.current = [];
                onLimitChange(next);
              }}
            >
              {PAGE_LIMIT_CHOICES.map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          </label>
        )}

        <Button variant="secondary" size="sm" shape="pill" onClick={goPrevious} disabled={!hasPrevious}>
          <span aria-hidden="true">←</span> Previous
        </Button>
        <Button variant="secondary" size="sm" shape="pill" onClick={goNext} disabled={!hasNext}>
          Next <span aria-hidden="true">→</span>
        </Button>
      </div>
    </nav>
  );
}

/*
 * The pager buttons, and the two decisions that used to live in a local class constant here.
 *
 * **They are SECONDARY now, not a grey control ground.** A live pager button used to be
 * `--surface-control` under `--ink`: a filled grey chip, which is the shape the brand
 * language rules out. It is the console's one secondary idiom instead — a tint of the hue
 * with the hue as the label — and it comes from `buttonVariants`, so it cannot drift away
 * from the rest of the console again.
 *
 * **The disabled state survived the move, because it was the right one.** The old rule dimmed
 * a dead button's LABEL to `--fg-3` (2.05:1 at its worst) and leaned on WCAG 1.4.3's
 * inactive-control exemption to justify it. That exemption is real, but it is a licence to be
 * unreadable, not a reason to be. `disabled:` in `buttonVariants` strips the GROUND and steps
 * the label back to `--ink-muted`: losing the button shape is a far louder signal than losing
 * 2:1 of contrast, the label stays at 4.87:1 worst case so it is readable rather than merely
 * present, and `disabled` on the element is what assistive tech reads either way. Two visible
 * channels, no exemption claimed, and no `--ink-rule` in this file — which is why
 * `RULE_WAIVERS` still needs no entry for `CursorPager`.
 */
