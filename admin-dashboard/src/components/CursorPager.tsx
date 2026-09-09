import { ChevronLeft, ChevronRight } from "lucide-react";
import type { JSX } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * Cursor pagination. There is no page number, no offset, and no "last page".
 *
 * The API mints an opaque `meta.nextCursor` and takes it back verbatim; it does not accept a
 * page index and it does not always know a total (`meta.total` is capped and can be `null`,
 * with `isTotalExact` saying which). A "Page 3 of 12" control here would be an invention, and
 * the first thing an operator would do with it is jump to a page that cannot be addressed.
 *
 * So: two directions and a range label the SCREEN composes from what it actually knows —
 * "51-100" when there is no total, "51-100 of 4,312" when there is, "51-100 of 10,000+" when
 * the count hit its cap. Going back is the caller's business too, because the API mints no
 * previous cursor: a screen that supports Previous keeps the cursors it has already used on a
 * stack, and one that does not simply passes `hasPrev={false}`.
 *
 * Both buttons are real `disabled` buttons rather than dimmed links, so a keyboard lands on
 * them only when they can do something and a screen reader says so.
 */

interface CursorPagerProps {
  readonly onPrev?: (() => void) | undefined;
  readonly onNext?: (() => void) | undefined;
  readonly hasPrev: boolean;
  readonly hasNext: boolean;
  /** A page is in flight. Both directions rest until it lands, so one press is one page. */
  readonly isFetching: boolean;
  /** "51-100 of 4,312". Composed by the screen — this control cannot know the total. */
  readonly rangeLabel: string;
  readonly className?: string | undefined;
}

const BUTTON_CLASS = cn(
  "flex h-9 cursor-pointer items-center gap-1 rounded-button border border-stroke bg-card px-3",
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800",
  "transition-[color,background-color] hover:bg-bg",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
  "disabled:cursor-not-allowed disabled:border-stroke disabled:bg-card disabled:text-ink-300 disabled:hover:bg-card",
);

export function CursorPager({
  onPrev,
  onNext,
  hasPrev,
  hasNext,
  isFetching,
  rangeLabel,
  className,
}: CursorPagerProps): JSX.Element {
  const { t } = useI18n();

  return (
    <nav
      aria-label={t("common.pagination")}
      className={cn("flex flex-wrap items-center justify-between gap-3", className)}
    >
      {/* Polite, not assertive: the range changes on every page and must not interrupt. */}
      <p aria-live="polite" className="m-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500">
        {rangeLabel}
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={!hasPrev || isFetching || onPrev === undefined}
          className={BUTTON_CLASS}
        >
          <ChevronLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
          {t("common.previous")}
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!hasNext || isFetching || onNext === undefined}
          className={BUTTON_CLASS}
        >
          {t("common.next")}
          <ChevronRight className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>
      </div>
    </nav>
  );
}
