import { X } from "lucide-react";
import type { JSX } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * The filters that are currently narrowing a list, each one removable.
 *
 * A filter an operator cannot see is a filter they will read a wrong conclusion through: an
 * empty Generations page under a forgotten `provider=gemini` looks exactly like an outage. So
 * every chip states its FIELD AND ITS VALUE in words — "Provider: gemini", not "gemini" — and
 * the caller passes prose, never an enum member the wire happens to use. Two of these
 * vocabularies are traps if echoed raw: `uz_latn` and `uz_cyrl` are two scripts of one
 * language and must never be collapsed into "Uzbek", and a boolean filter is TRI-STATE, so
 * `hasBalance=false` reads "Has credit account: no" and its absence reads nothing at all.
 *
 * Drawn as the kit's badge: #75FC96B2 at radius 4, 6/8 padding, a 12/-0.36 label.
 */

export interface FilterChip {
  /** Stable across renders — usually the filter's field name. */
  readonly id: string;
  /** The field, in words. "Language", "Blocked", "Kind". */
  readonly field: string;
  /** The value, in words. Never a raw enum member. */
  readonly value: string;
  readonly onRemove: () => void;
}

interface FilterChipsProps {
  readonly chips: readonly FilterChip[];
  /** Omitted when there is nothing a single press should clear (a filter the screen pins). */
  readonly onClearAll?: (() => void) | undefined;
  /** Names the group for assistive tech. */
  readonly label?: string;
  readonly className?: string | undefined;
}

export function FilterChips({
  chips,
  onClearAll,
  label,
  className,
}: FilterChipsProps): JSX.Element | null {
  const { t } = useI18n();
  if (chips.length === 0) return null;

  return (
    <div role="group" aria-label={label ?? t("common.activeFilters")} className={cn("flex flex-wrap items-center gap-2", className)}>
      {chips.map((chip) => (
        <span
          key={chip.id}
          className="inline-flex max-w-full items-center gap-2 rounded bg-accent-70 py-[6px] pl-2 pr-1 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-800"
        >
          <span className="truncate">
            <span className="font-semibold">{chip.field}:</span> {chip.value}
          </span>
          <button
            type="button"
            onClick={chip.onRemove}
            aria-label={t("common.removeFilter", { field: chip.field, value: chip.value })}
            className={cn(
              "flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-full border-0 bg-transparent p-0 text-ink-800",
              /* No `/60` opacity modifier: these colours are bare `var(--token)`, which Tailwind
                 cannot split into channels, so an alpha suffix silently emits nothing. */
              "transition-[background-color] hover:bg-card",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
            )}
          >
            <X className="h-3 w-3" strokeWidth={2} aria-hidden />
          </button>
        </span>
      ))}

      {onClearAll === undefined ? null : (
        <button
          type="button"
          onClick={onClearAll}
          className={cn(
            "cursor-pointer rounded border-0 bg-transparent px-1 py-[6px] text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-500 underline underline-offset-2",
            "transition-colors hover:text-ink-900",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
          )}
        >
          {t("common.clearAll")}
        </button>
      )}
    </div>
  );
}
