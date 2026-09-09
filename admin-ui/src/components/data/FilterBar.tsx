/**
 * `FilterBar` — §11.4's URL-backed removable chips.
 *
 * One row, above everything it scopes. Controls on the left (a `TimeRangePicker`, a state
 * multi-select, a search box), the active filters restated as removable chips, and a Clear
 * that resets to the default view. Never inside a card, never per-chart: every table, tile
 * and chart below this row reads the same slice, so the numbers on the screen always agree
 * with each other.
 *
 * The chips are derived from the parsed search params by `buildFilterChips`; this component
 * renders them and owns no filter state of its own. That is what makes a pasted URL and the
 * screen it produces the same thing.
 *
 * `activeCount` comes from `SearchParamsState.activeCount`, which excludes `limit`, `cursor`
 * and `withTotal` — paging is not filtering, and §11.4's "Empty-filtered" copy names the
 * count of filters, so counting the page size in it would tell the operator to clear a
 * filter that does not exist.
 */

import { type ReactElement, type ReactNode } from "react";

import { cn } from "@/lib";

import type { FilterChipModel } from "./filterChips";

export interface FilterBarProps {
  /** From `buildFilterChips(state, fields)`. */
  readonly chips: readonly FilterChipModel[];
  /** `SearchParamsState.clear`. */
  readonly onClear: () => void;
  /** How many filters are set — `SearchParamsState.activeCount`. */
  readonly activeCount?: number;
  /** The controls. Rendered first, left-aligned, in the same row. */
  readonly children?: ReactNode;
  /** Names the region for assistive tech: `order filters`. */
  readonly label?: string;
  readonly className?: string;
}

export function FilterBar({
  chips,
  onClear,
  activeCount,
  children,
  label = "filters",
  className,
}: FilterBarProps): ReactElement {
  const count = activeCount ?? chips.length;

  return (
    <section
      aria-label={label}
      data-active-count={count}
      /* Its own card, on the page ground, above everything it scopes — this design draws no
         `border-b` under a bar, it floats the bar and lets the gutter do the separating. */
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-card bg-surface-card px-5 py-4 shadow-card",
        className,
      )}
    >
      {children}

      {chips.length > 0 && (
        <ul className="flex flex-wrap items-center gap-2" aria-label={`active ${label}`}>
          {chips.map((chip) => (
            <li key={chip.id}>
              <FilterChip chip={chip} />
            </li>
          ))}
        </ul>
      )}

      {count > 0 && (
        <button
          type="button"
          onClick={onClear}
          className={cn(
            "text-button ml-auto shrink-0 rounded-pill px-3 py-1.5 text-brand",
            "transition-colors duration-fast ease-standard hover:bg-brand-tint",
          )}
        >
          Clear {count === 1 ? "filter" : `all ${String(count)} filters`}
        </button>
      )}
    </section>
  );
}

/**
 * One chip. The whole token is the remove button — a separate 8px × target next to a label
 * is a miss waiting to happen, and there is nothing else a chip could do when clicked.
 *
 * A chip is ACTIVE by definition — it only exists while its filter is set — so it wears the
 * brand tint rather than a neutral control ground. The field name stays `--ink-muted` and the
 * value is `--ink`: `state failed` reads as one label with one emphasis, not two competing
 * ones, and the tint is already carrying the brand.
 *
 * The `×` used to be `--fg-2` behind a contrast waiver. It is `--ink-muted` now: it is a small
 * mark next to words that already say "remove filter …", so it never needed to be the dimmest
 * thing on screen, and at 4.73:1 worst case (across all four cells) it is legible without a
 * policed token or a waiver entry.
 *
 * Hover swaps the whole GROUND to `--error-tint` and takes the `×` to `--error`, rather than
 * reddening the `×` alone on the brand tint. Both readings pass, but only this one is
 * MEASURED: `tokenContrast.test.ts` composites each family's tint over the card and the page
 * and checks `--ink`, `--ink-muted` and that family's own text member against it — it has no
 * ground for "`--error` over `--brand-tint`". Keeping every pair inside the measured set is
 * what stops the next palette change from silently breaking one, and it reads better anyway:
 * the chip turns the colour of what the click is about to do.
 */
export function FilterChip({ chip }: { readonly chip: FilterChipModel }): ReactElement {
  return (
    <button
      type="button"
      onClick={chip.remove}
      data-chip={chip.id}
      aria-label={`remove filter ${chip.label} ${chip.value}`}
      className={cn(
        "type-body-sm group inline-flex items-center gap-1.5 rounded-pill",
        "bg-brand-tint py-1.5 pl-3 pr-2.5 text-ink",
        "transition-colors duration-fast ease-standard hover:bg-error-tint",
      )}
    >
      <span className="text-ink-muted">{chip.label}</span>
      <span className="num font-semibold">{chip.value}</span>
      <span aria-hidden="true" className="text-ink-muted group-hover:text-error">
        ×
      </span>
    </button>
  );
}
