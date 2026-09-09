import { type JSX, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { cn } from "@/lib/cn";

import { Skeleton } from "./Skeleton";

/**
 * The kit's Task List, made generic.
 *
 * Metrics are measured from `.openpencil-export/task-list.jsx`, not chosen: white card at
 * radius 15 with the overflow clipped, a 16/400/-0.64 header in --ink-300, and a 12/600/-0.36
 * cell in --ink-800 with an optional 12/400 second line in --cell-2. Screens that need that
 * second line take `CELL_SECONDARY_CLASS` from here rather than re-deriving three numbers.
 *
 * Three behaviours are load-bearing rather than decorative:
 *
 * 1. **A clickable row is reachable by keyboard.** The kit's rows are pictures; ours navigate.
 *    So a row with `onRowClick` is focusable, activates on Enter and Space, and shows a focus
 *    ring drawn INSIDE the card (the card clips its overflow, and an outset ring on the first
 *    or last row would be sliced in half). Row semantics are kept — no `role="button"` on a
 *    `<tr>`, which would strip the table from the accessibility tree; the row is an extra
 *    affordance over cells that already read correctly.
 * 2. **Controls inside a row do not also trigger the row.** Enforced here, by ignoring any
 *    activation whose target sits inside a button, link or field, rather than asking every
 *    caller to remember `stopPropagation` on every per-row control. A reveal button that also
 *    navigates away is a reveal an operator did not get to read.
 * 3. **Loading does not resize the table.** Skeleton rows are the real row height and the real
 *    column count, so the header does not jump when the page lands. `aria-busy` on the table
 *    is the fact a screen reader can act on; the shimmer itself is `aria-hidden`.
 * 4. **A sortable header is a real button inside a real `<th>`.** `Column.sort` turns the
 *    heading into a keyboard-operable control while the cell keeps `scope="col"` and gains
 *    `aria-sort`, so the ordering is announced once, in the place the property is defined for.
 *    Only columns the SERVER will order by get one — this component offers no client-side
 *    sort, because a table that reorders fifty rows of a fifty-thousand-row walk is lying
 *    about what it sorted.
 *
 * Horizontal overflow scrolls INSIDE the card, so a wide table never makes the page scroll
 * sideways and never breaks the radius.
 */

/**
 * A column the SERVER can order by, and the state that ordering is currently in.
 *
 * Only what the server will actually sort on gets one. The Users list's keys come from the
 * segment registry's `sortable` flag, where `last_activity_at` is filterable and deliberately
 * NOT sortable and no free-text column is either — offering a header and then rendering a 422
 * teaches an operator that the table is unreliable about a refusal that is deliberate.
 *
 * The strings belong to the CALLER, not to this file: a header is the one control here whose
 * accessible name has to say what pressing it will do ("Sort by Orders, largest first"), and
 * this component holds no catalogue. `direction` is the ordering the table is in RIGHT NOW,
 * so `null` means "sortable, but something else is the sort" — which is what `aria-sort`
 * distinguishes and what a screen reader announces per column.
 */
export interface ColumnSort {
  readonly direction: "asc" | "desc" | null;
  /** The button's accessible name — what one press will do, in the operator's language. */
  readonly label: string;
  readonly onSort: () => void;
}

export interface Column<T> {
  /** React key and nothing else — never sent anywhere, so it need not match a wire field. */
  readonly key: string;
  readonly header: string;
  /** Any CSS width, applied through a `<colgroup>` so it cannot fight the cell padding. */
  readonly width?: string | undefined;
  readonly align?: "left" | "right" | undefined;
  readonly render: (row: T) => ReactNode;
  /**
   * For a column whose heading is obvious from its cells (an avatar, a row-end action). The
   * text still ships to assistive tech — a `<th>` with no accessible name leaves every cell
   * under it unlabelled.
   */
  readonly srOnlyHeader?: boolean | undefined;
  /** Present only on a column the server will order by. Absent renders a plain heading. */
  readonly sort?: ColumnSort | undefined;
}

export interface DataTableProps<T> {
  readonly columns: readonly Column<T>[];
  readonly rows: readonly T[];
  readonly getRowKey: (row: T) => string;
  readonly onRowClick?: ((row: T) => void) | undefined;
  readonly isLoading?: boolean | undefined;
  /** What stands in the table's body when there are no rows. Say what was searched, not "no data". */
  readonly emptyMessage: ReactNode;
  /**
   * How many rows the skeleton reserves. Pass the PAGE LIMIT: a table that reserves eight
   * rows and then renders fifty moves everything under it — the pager included — by about
   * two thousand pixels in the frame the data lands.
   */
  readonly skeletonRows?: number | undefined;
  /**
   * Which row is the one currently open elsewhere on the screen. It gets `aria-current` and a
   * ground, so a list beside a detail panel says which row the panel is showing.
   */
  readonly isRowActive?: ((row: T) => boolean) | undefined;
  /** The table's accessible name. Rendered as a visually hidden `<caption>`. */
  readonly caption?: string | undefined;
  readonly className?: string | undefined;
}

/** 12/600/-0.36 #000000 — the kit's primary cell line. */
export const CELL_PRIMARY_CLASS =
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800";

/** 12/400/-0.36 #00000066 — the kit's second line, under the primary one. */
export const CELL_SECONDARY_CLASS =
  "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-cell-2";

/** 16/400/-0.64 #8D8D8D — the kit's column header. */
const HEADER_CLASS = "text-[16px] font-normal leading-[21.856px] tracking-[-0.64px] text-ink-300";

/** Anything that handles its own activation. A click inside one of these is not a row click. */
const INTERACTIVE_SELECTOR = 'a, button, input, select, textarea, label, [role="button"], [tabindex]';

function isInsideOwnControl(target: EventTarget | null, row: Element): boolean {
  if (!(target instanceof Element)) return false;
  const owner = target.closest(INTERACTIVE_SELECTOR);
  // The row itself matches `[tabindex]`; only a control BELOW it counts.
  return owner !== null && owner !== row;
}

/** `aria-sort`'s vocabulary, which is not the wire's. */
const ARIA_SORT: Readonly<Record<"asc" | "desc" | "none", "ascending" | "descending" | "none">> = {
  asc: "ascending",
  desc: "descending",
  none: "none",
};

/**
 * The arrow, drawn from text so it inherits the header's colour and never loads.
 *
 * A column that COULD be the sort still draws one, dimmed: an affordance nobody can see is an
 * affordance nobody presses, and the alternative — reserving invisible space — makes a
 * sortable header indistinguishable from a fixed one until the pointer happens to land on it.
 */
const SORT_GLYPH: Readonly<Record<"asc" | "desc" | "none", string>> = {
  asc: "↑",
  desc: "↓",
  none: "↕",
};

/**
 * One column heading: a word, or the button that reorders the list.
 *
 * The button is inside the `<th>` rather than being it, so the cell keeps its `scope="col"`
 * and its `aria-sort` and the header still reads as a header to a screen reader. The arrow is
 * `aria-hidden` — the direction is already in `aria-sort` and in the button's own label, and
 * announcing "down arrow" a third time is noise.
 */
function ColumnHeader<T>({ column }: { readonly column: Column<T> }): JSX.Element {
  const text =
    column.srOnlyHeader === true ? <span className="sr-only">{column.header}</span> : column.header;

  if (column.sort === undefined) return <>{text}</>;

  const { direction, label, onSort } = column.sort;
  return (
    <button
      type="button"
      onClick={onSort}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex max-w-full cursor-pointer items-center gap-1 rounded border-0 bg-transparent p-0 font-sans",
        HEADER_CLASS,
        "transition-colors hover:text-ink-800",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
        // The active column is the one fact the header row states about the ordering.
        direction !== null && "text-ink-800",
      )}
    >
      <span className="truncate">{text}</span>
      <span aria-hidden className={cn("shrink-0", direction === null && "opacity-40")}>
        {SORT_GLYPH[direction ?? "none"]}
      </span>
    </button>
  );
}

export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  onRowClick,
  isLoading = false,
  emptyMessage,
  skeletonRows = 8,
  isRowActive,
  caption,
  className,
}: DataTableProps<T>): JSX.Element {
  const isClickable = onRowClick !== undefined;

  function handleClick(event: MouseEvent<HTMLTableRowElement>, row: T): void {
    if (onRowClick === undefined) return;
    if (isInsideOwnControl(event.target, event.currentTarget)) return;
    onRowClick(row);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: T): void {
    if (onRowClick === undefined) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    if (isInsideOwnControl(event.target, event.currentTarget)) return;
    // Space scrolls the page otherwise, and the row the operator meant to open leaves the screen.
    event.preventDefault();
    onRowClick(row);
  }

  return (
    <div className={cn("overflow-hidden rounded-card bg-card", className)}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left" aria-busy={isLoading}>
          {caption === undefined ? null : <caption className="sr-only">{caption}</caption>}
          <colgroup>
            {columns.map((column) => (
              <col
                key={column.key}
                style={column.width === undefined ? undefined : { width: column.width }}
              />
            ))}
          </colgroup>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  /* The CELL carries `aria-sort`, not the button inside it: the property is
                     defined on the header cell, and one column at a time may be anything but
                     "none" — which is why an inactive sortable column still says "none"
                     rather than omitting it. */
                  {...(column.sort === undefined ? {} : { "aria-sort": ARIA_SORT[column.sort.direction ?? "none"] })}
                  className={cn(
                    "whitespace-nowrap px-4 pb-2 pt-4 align-middle font-normal",
                    HEADER_CLASS,
                    column.align === "right" && "text-right",
                  )}
                >
                  <ColumnHeader column={column} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: skeletonRows }, (_unused, index) => (
                  /* The real row's box, exactly: the same 1px top edge, and two stacked bars
                     because these tables' tallest cells are two lines or a 32px avatar. One
                     short bar reserves 48px against a ~57px row, and the difference lands on
                     the pager as a jump of a page-length. */
                  <tr key={`skeleton-${String(index)}`} className="border-t border-stroke">
                    {columns.map((column) => (
                      <td key={column.key} className="h-12 px-4 py-3 align-middle">
                        <div className="flex flex-col gap-[3px]">
                          <Skeleton className="h-4 w-full max-w-[140px]" />
                          <Skeleton className="h-3 w-full max-w-[90px]" />
                        </div>
                      </td>
                    ))}
                  </tr>
                ))
              : null}

            {!isLoading && rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-12 align-middle">
                  {emptyMessage}
                </td>
              </tr>
            ) : null}

            {!isLoading
              ? rows.map((row) => {
                  const isActive = isRowActive?.(row) ?? false;
                  return (
                  <tr
                    key={getRowKey(row)}
                    /* Addressable from outside, so a screen that opened a panel from this row
                       can put focus back on it when the panel closes. */
                    data-row-key={getRowKey(row)}
                    {...(isActive ? { "aria-current": true as const } : {})}
                    tabIndex={isClickable ? 0 : undefined}
                    onClick={isClickable ? (event) => handleClick(event, row) : undefined}
                    onKeyDown={isClickable ? (event) => handleKeyDown(event, row) : undefined}
                    className={cn(
                      "border-t border-stroke transition-colors",
                      isClickable &&
                        "cursor-pointer hover:bg-row-hover focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent-deep",
                      isActive && "bg-row-hover",
                    )}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "h-12 px-4 py-3 align-middle",
                          CELL_PRIMARY_CLASS,
                          column.align === "right" && "text-right",
                        )}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                  );
                })
              : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
