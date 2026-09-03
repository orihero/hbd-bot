/**
 * `DataTable<T>` — §11.4: keyset paging, sticky header, `j`/`k` nav, density.
 *
 * Built on TanStack Table v8 **headless**: the library owns the row model and nothing else.
 * There is no sorting row model and that is deliberate — every list on this panel is
 * keyset-paged server-side, so a client-side sort would reorder fifty rows out of ten
 * thousand and present the result as "sorted", which is worse than no sort at all. Sorting,
 * when a screen needs it, is a query parameter.
 *
 * ## The column contract
 *
 * Callers describe columns with `DataColumn<T>` rather than a raw `ColumnDef`. That is a
 * deliberate narrowing: it makes `isNumeric` a required decision rather than a forgotten
 * one, and `isNumeric` is what applies `.num` (`tabular-nums slashed-zero`, §11.3) so a
 * digit does not change width as a 15s poll ticks under the operator's cursor.
 *
 * ## Keyboard
 *
 * `j`/`k` move the active row, `↓`/`↑` do the same for anyone who does not think in vi,
 * `Enter`/`o` activate it, `Home`/`End` jump. The handler ignores every event that started
 * in a text field or carries a modifier, so `⌘K` still reaches the palette and typing in a
 * filter box does not scroll the table.
 *
 * ## Density
 *
 * Read from `usePrefsStore`, not from a prop, because it is one operator-level preference
 * for the whole console — a table that is compact on one screen and comfortable on the next
 * is a bug the operator cannot fix from either screen.
 *
 * ## The surface
 *
 * A table IS a card here: `--surface-card` at `--r-card`, `--shadow-card`, and no border at
 * all — the toolbar, the grid and the pager share one 28px panel rather than being three
 * bordered boxes stacked on each other.
 *
 * Rows carry no `border-b`. They are separated by height (`--row-h` = 44px) and read by a
 * soft `--surface-control-hover` pill that follows the pointer and the `j`/`k` cursor; the
 * pill is painted on the CELLS rather than the row so its ends can be rounded, which is the
 * detail that makes a dense grid look like this design rather than like a spreadsheet. The
 * one rule that survives is the `--hairline` under the header, which is decoration in the
 * WCAG sense and is what stops the sticky head from floating over the first row unattached.
 *
 * The sticky head is `--surface-card`, not a filled bar: it has to be opaque to occlude the
 * rows scrolling beneath it, and the card colour is the one opacity that is invisible.
 */

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";

import { Button } from "@/components/util";
import { cn, usePrefsStore } from "@/lib";

export interface DataColumn<T> {
  /** Stable identity. Used as the React key and as the `data-column` attribute. */
  readonly id: string;
  /** Header content. Our own copy — never user content. */
  readonly header: ReactNode;
  /** One cell, from one row. */
  readonly cell: (row: T) => ReactNode;
  /**
   * Numbers, durations, counts, rates, ids that are compared by eye. Right-aligns and
   * applies `.num` (§11.3). Say `false` explicitly for a text column; do not leave it off
   * because a column "looks numeric enough".
   */
  readonly isNumeric?: boolean;
  /** A CSS width for the `<col>`; keeps a poll from reflowing the grid. */
  readonly width?: string;
  /** Long header text abbreviated in the cell; goes on `title`. */
  readonly headerTitle?: string;
}

export interface DataTableProps<T> {
  readonly data: readonly T[];
  readonly columns: readonly DataColumn<T>[];
  /** Stable row identity. Falls back to the array index, which breaks `j`/`k` across a
   *  poll — pass a real id for anything that refetches. */
  readonly getRowId?: (row: T, index: number) => string;
  /** `Enter` on the active row, and a click. */
  readonly onRowActivate?: (row: T) => void;
  /** Marks a row as the current one (the open detail, the selected order). */
  readonly isRowHighlighted?: (row: T) => boolean;
  /** Names the grid for assistive tech. */
  readonly label: string;
  /** What to show when `data` is empty. §11.4's Empty-virgin / Empty-filtered live here. */
  readonly emptyState?: ReactNode;
  /** The `CursorPager`, usually. Rendered outside the scroll container. */
  readonly footer?: ReactNode;
  /** A toolbar above the header row; the density toggle joins whatever is passed. */
  readonly toolbar?: ReactNode;
  /** Hide the density toggle on a table that is never long. */
  readonly isDensityToggle?: boolean;
  /** Holds the previous render at 70% while the next page loads — never a skeleton flash. */
  readonly isRefetching?: boolean;
  /** Caps the scroll area. Omit to let the page scroll instead. */
  readonly maxHeight?: string;
  readonly className?: string;
}

export function DataTable<T>({
  data,
  columns,
  getRowId,
  onRowActivate,
  isRowHighlighted,
  label,
  emptyState,
  footer,
  toolbar,
  isDensityToggle = true,
  isRefetching = false,
  maxHeight,
  className,
}: DataTableProps<T>): ReactElement {
  const density = usePrefsStore((state) => state.density);
  const setDensity = usePrefsStore((state) => state.setDensity);

  const rows = useMemo(() => [...data], [data]);

  const tableColumns = useMemo<ColumnDef<T>[]>(
    () =>
      columns.map((column) => ({
        id: column.id,
        header: () => column.header,
        cell: (context) => column.cell(context.row.original),
      })),
    [columns],
  );

  const table = useReactTable<T>({
    data: rows,
    columns: tableColumns,
    getCoreRowModel: getCoreRowModel(),
    ...(getRowId === undefined ? {} : { getRowId: (row: T, index: number) => getRowId(row, index) }),
  });

  const modelRows = table.getRowModel().rows;
  const [activeIndex, setActiveIndex] = useState(-1);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  /*
   * Which edges have content past them. Both false is the honest default: a grid that fits
   * shows no cue at all, and a browser that reports no geometry (jsdom, a display:none
   * ancestor) reports "fits" rather than inventing one.
   */
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollEdges, setScrollEdges] = useState({ start: false, end: false });

  const syncScrollEdges = useCallback(() => {
    const element = scrollRef.current;
    if (element === null) return;
    const hidden = element.scrollWidth - element.clientWidth;
    // Sub-pixel layout leaves a fraction of a pixel behind at both ends; a cue for half a
    // pixel of "more" is a lie the operator can see.
    const next = {
      start: element.scrollLeft > 1,
      end: hidden - element.scrollLeft > 1,
    };
    setScrollEdges((current) =>
      current.start === next.start && current.end === next.end ? current : next,
    );
  }, []);

  /*
   * Measured from the DOM rather than from the props, because the cause is layout: the same
   * fifty rows overflow at 1280px and do not at 1728px, and a column only widens once its
   * content has arrived. A `ResizeObserver` on the scroll port catches the viewport half and
   * one on the `<table>` catches the content half; `onScroll` catches the operator.
   */
  useEffect(() => {
    syncScrollEdges();
    const element = scrollRef.current;
    const observer =
      element !== null && typeof ResizeObserver === "function"
        ? new ResizeObserver(syncScrollEdges)
        : null;
    if (observer !== null && element !== null) {
      observer.observe(element);
      const grid = element.querySelector("table");
      if (grid !== null) observer.observe(grid);
    }
    return () => {
      observer?.disconnect();
    };
  }, [syncScrollEdges]);

  const hasOverflowX = scrollEdges.start || scrollEdges.end;

  // A shrinking page must not leave the cursor pointing past the end.
  useEffect(() => {
    setActiveIndex((current) => (current >= modelRows.length ? modelRows.length - 1 : current));
  }, [modelRows.length]);

  useEffect(() => {
    if (activeIndex < 0) return;
    const element = rowRefs.current[activeIndex];
    if (element === null || element === undefined) return;
    element.focus({ preventScroll: true });
    // `scrollIntoView` is unimplemented in jsdom and is a nicety anywhere: keyboard
    // navigation must not depend on it, so it is called only where it exists.
    if (typeof element.scrollIntoView === "function") {
      element.scrollIntoView({ block: "nearest" });
    }
  }, [activeIndex]);

  const move = useCallback(
    (delta: number) => {
      setActiveIndex((current) => {
        const next = current < 0 ? (delta > 0 ? 0 : modelRows.length - 1) : current + delta;
        if (next < 0) return 0;
        if (next > modelRows.length - 1) return modelRows.length - 1;
        return next;
      });
    },
    [modelRows.length],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (modelRows.length === 0) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      switch (event.key) {
        case "j":
        case "ArrowDown":
          event.preventDefault();
          move(1);
          return;
        case "k":
        case "ArrowUp":
          event.preventDefault();
          move(-1);
          return;
        case "Home":
          event.preventDefault();
          setActiveIndex(0);
          return;
        case "End":
          event.preventDefault();
          setActiveIndex(modelRows.length - 1);
          return;
        case "Enter":
        case "o": {
          if (onRowActivate === undefined) return;
          const row = modelRows[activeIndex];
          if (row === undefined) return;
          event.preventDefault();
          onRowActivate(row.original);
          return;
        }
        default:
          return;
      }
    },
    [activeIndex, modelRows, move, onRowActivate],
  );

  const rowHeightClass = density === "compact" ? "h-row-compact" : "h-row";

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-card bg-surface-card shadow-card",
        className,
      )}
    >
      {(toolbar !== undefined || isDensityToggle) && (
        <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-4">
          <div className="flex min-w-0 flex-wrap items-center gap-2">{toolbar}</div>
          {isDensityToggle && (
            /* A toolbar affordance, so `secondary` at the small rung rather than a filled
               grey chip. It is a two-way switch, not a segment: both states are equally
               "on", so `segmentVariant` would be the wrong helper and `aria-pressed` carries
               which way it is set. */
            <Button
              variant="secondary"
              size="sm"
              shape="pill"
              className="px-3"
              aria-pressed={density === "compact"}
              onClick={() => {
                setDensity(density === "compact" ? "comfortable" : "compact");
              }}
            >
              <span aria-hidden="true">≡</span> {density}
            </Button>
          )}
        </div>
      )}

      <div
        /* A positioning context for the edge cues, and nothing else: it keeps the scroll
           port's own flex context (`flex min-h-0 flex-col`) so the card's height behaviour
           is exactly what it was before the cues existed. */
        className="relative flex min-h-0 flex-col"
        data-overflow-x={hasOverflowX ? "true" : "false"}
      >
        <div
          ref={scrollRef}
          className={cn(
            "min-h-0 overflow-auto",
            isRefetching && "opacity-70 transition-opacity duration-base ease-standard",
          )}
          style={maxHeight === undefined ? undefined : { maxHeight }}
          onKeyDown={onKeyDown}
          onScroll={syncScrollEdges}
        >
          <table
            className="w-full border-collapse text-left"
            aria-label={label}
            aria-rowcount={modelRows.length}
            data-density={density}
          >
            <colgroup>
              {columns.map((column) => (
                <col
                  key={column.id}
                  style={column.width === undefined ? undefined : { width: column.width }}
                />
              ))}
            </colgroup>

            {/* Sticky on the CARD colour — the head is a label row, not a filled bar, so the
                one thing it must do is occlude the rows sliding under it. */}
            <thead className="sticky top-0 z-10 bg-surface-card">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header, index) => {
                    const column = columns[index];
                    return (
                      <th
                        key={header.id}
                        scope="col"
                        data-column={column?.id ?? header.id}
                        title={column?.headerTitle}
                        className={cn(
                          "type-caption border-b border-hairline px-4 pb-2 pt-1 text-ink-muted",
                          column?.isNumeric === true && "text-right",
                        )}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>

            <tbody>
              {modelRows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-14 text-center text-ink-muted">
                    {emptyState}
                  </td>
                </tr>
              ) : (
                modelRows.map((row, rowIndex) => {
                  const isActive = rowIndex === activeIndex;
                  const isHighlighted = isRowHighlighted?.(row.original) ?? false;
                  return (
                    <tr
                      key={row.id}
                      ref={(element) => {
                        rowRefs.current[rowIndex] = element;
                      }}
                      tabIndex={isActive || (activeIndex < 0 && rowIndex === 0) ? 0 : -1}
                      aria-rowindex={rowIndex + 1}
                      aria-current={isHighlighted ? "true" : undefined}
                      data-active={isActive ? "true" : undefined}
                      className={cn(
                        rowHeightClass,
                        /* No `border-b`: rows are separated by height and by the hover pill
                           the cells paint. `group` is what lets the cells see the row's
                           hover and focus states. */
                        "group focus:outline-none",
                        onRowActivate !== undefined && "cursor-pointer",
                      )}
                      onFocus={() => {
                        setActiveIndex(rowIndex);
                      }}
                      onClick={() => {
                        setActiveIndex(rowIndex);
                        onRowActivate?.(row.original);
                      }}
                    >
                      {row.getVisibleCells().map((cell, cellIndex) => {
                        const column = columns[cellIndex];
                        const isFirst = cellIndex === 0;
                        const isLast = cellIndex === row.getVisibleCells().length - 1;
                        return (
                          <td
                            key={cell.id}
                            data-column={column?.id ?? cell.column.id}
                            className={cn(
                              "type-body-sm px-4 text-ink",
                              "transition-colors duration-fast ease-standard",
                              density === "compact" ? "py-1" : "py-2",
                              /* The soft pill: rounded ends on the outer cells so the tint
                                 reads as one rounded band rather than a full-bleed stripe. */
                              isFirst && "rounded-l-control",
                              isLast && "rounded-r-control",
                              "group-hover:bg-surface-control-hover",
                              "group-focus-visible:bg-surface-control-hover",
                              isActive && "bg-surface-control",
                              /* The open record, marked by a brand rail on the leading edge —
                                 `aria-current` on the row carries the same fact for AT. */
                              isHighlighted &&
                                isFirst &&
                                "shadow-[inset_3px_0_0_0_var(--brand-fill)]",
                              column?.isNumeric === true && "num text-right",
                            )}
                          >
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/*
          The overflow affordance. In the bordered design the card's own 1px edge implied
          "this is cut"; a borderless card implies nothing, and Chromium draws OVERLAY
          scrollbars, so `/orders` sat with 31px of hidden "updated" column and no signal at
          all that anything continued.

          Two soft edges, each mounted only while there is genuinely something past it —
          `scrollLeft > 0` for the leading one, `scrollWidth - clientWidth - scrollLeft > 0`
          for the trailing. A fade rather than a rule because this language has no hard
          borders left to reintroduce, and it is deliberately narrow (24px) and keyed to the
          card colour so it dissolves into the surface rather than sitting on it.

          It cannot hide a last column an operator is trying to read: the trailing fade only
          exists while that column is ALREADY clipped by the scroll port, and it unmounts the
          moment the scroll reaches the end, which is exactly when the column becomes whole.
          `pointer-events-none` keeps the scroll port hit-testable underneath, and `z-20`
          puts it over the sticky `<thead>` (`z-10`) so the header is faded with its rows
          rather than floating above the cue.
        */}
        {scrollEdges.start && (
          <div
            aria-hidden="true"
            data-testid="table-scroll-fade-start"
            className="pointer-events-none absolute inset-y-0 left-0 z-20 w-6 bg-gradient-to-r from-surface-card to-transparent"
          />
        )}
        {scrollEdges.end && (
          <div
            aria-hidden="true"
            data-testid="table-scroll-fade-end"
            className="pointer-events-none absolute inset-y-0 right-0 z-20 w-6 bg-gradient-to-l from-surface-card to-transparent"
          />
        )}
      </div>

      {footer}
    </div>
  );
}

/** `j` must type a `j` when the operator is in a filter box, not scroll the grid. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
