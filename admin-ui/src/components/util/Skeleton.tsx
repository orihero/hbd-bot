/**
 * §11.4's loading state: "Skeleton (matching final dimensions exactly, 1.2 s shimmer,
 * **never** a centred spinner)".
 *
 * The rule is not aesthetic. A centred spinner throws away the one piece of information the
 * console already has — the shape of what is coming — and every arrival reflows the page
 * under a cursor that was already moving toward a row. A skeleton whose dimensions match
 * the finished thing makes the load a fade rather than a jump.
 *
 * Which means the CALLER owns the shape. `AsyncBoundary` takes a `skeleton` node rather
 * than drawing a generic one, and these are the primitives to build it from: the same row
 * height (`h-row` / `h-row-compact`), the same column count, the same paddings.
 *
 * The shimmer is a `background-position` sweep at exactly 1.2 s (`animate-shimmer` in
 * `tailwind.config.ts`). It is switched off under `prefers-reduced-motion` — the tokens
 * zero out the CSS transition durations but a keyframe animation is not a transition and
 * has to be dropped by hand.
 */

import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

/**
 * The sweep: `--skeleton-base` → `--skeleton-sheen` → `--skeleton-base`, so it reads as a
 * highlight travelling across a surface rather than as a second colour.
 *
 * Both stops are named for the JOB, not for a surface. That is the whole reason the two
 * tokens exist: this gradient is a string handed to CSS at runtime, so a renamed surface
 * token would not fail the build or any test — it would resolve to nothing and paint a blank
 * shimmer, with a green suite either way.
 */
const SHIMMER_STYLE: CSSProperties = {
  backgroundImage:
    "linear-gradient(90deg, var(--skeleton-base) 0%, var(--skeleton-sheen) 45%, " +
    "var(--skeleton-sheen) 55%, var(--skeleton-base) 100%)",
  backgroundSize: "200% 100%",
};

export interface SkeletonProps {
  readonly className?: string;
  readonly style?: CSSProperties;
  /** Width as a CSS length or percentage, when a utility class is the wrong tool. */
  readonly width?: string | undefined;
  readonly height?: string | undefined;
}

/** One shimmering block. Give it the exact dimensions of the thing it stands in for. */
export function Skeleton({ className, style, width, height }: SkeletonProps) {
  return (
    <div
      data-testid="skeleton"
      aria-hidden="true"
      className={cn(
        "animate-shimmer rounded-control bg-skeleton motion-reduce:animate-none",
        className,
      )}
      style={{
        ...SHIMMER_STYLE,
        ...(width === undefined ? {} : { width }),
        ...(height === undefined ? {} : { height }),
        ...style,
      }}
    />
  );
}

export interface SkeletonTextProps {
  readonly lines?: number;
  /** Line height in px; defaults to the `body` line box so text does not jump on arrival. */
  readonly lineHeight?: number;
  readonly className?: string;
}

/** A paragraph's worth. The last line is short, because real ones are. */
export function SkeletonText({ lines = 3, lineHeight = 20, className }: SkeletonTextProps) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: Math.max(1, lines) }, (_unused, index) => (
        <Skeleton
          key={index}
          height={`${String(Math.max(8, lineHeight - 8))}px`}
          className={index === lines - 1 ? "w-1/2" : "w-full"}
        />
      ))}
    </div>
  );
}

export interface SkeletonTableProps {
  readonly rows?: number;
  readonly columns?: number;
  /** `DataTable`'s density. `compact` uses `--row-h-compact` (32px), not 40px. */
  readonly density?: "comfortable" | "compact";
  /** Draw a header row above the body rows. */
  readonly withHeader?: boolean;
  readonly className?: string;
}

/**
 * A table's worth, at the SAME row height the real table will use. Passing the wrong
 * density here is the one way to reintroduce the reflow this component exists to prevent.
 */
export function SkeletonTable({
  rows = 8,
  columns = 5,
  density = "comfortable",
  withHeader = true,
  className,
}: SkeletonTableProps) {
  const rowHeight = density === "compact" ? "h-row-compact" : "h-row";
  return (
    <div className={cn("w-full", className)} data-testid="skeleton-table">
      {withHeader ? (
        <div className={cn("flex items-center gap-4 border-b border-hairline px-3", rowHeight)}>
          {Array.from({ length: columns }, (_unused, index) => (
            <Skeleton key={index} className="h-3 flex-1" />
          ))}
        </div>
      ) : null}
      {Array.from({ length: Math.max(1, rows) }, (_unused, rowIndex) => (
        <div
          key={rowIndex}
          /* A dense data grid keeps a hairline between rows even in a language that
             separates everything else with whitespace: eight rows of identical shimmer with
             no rule at all is one grey block, and the skeleton's whole job is to have the
             shape of what is coming. */
          className={cn("flex items-center gap-4 border-b border-hairline px-3", rowHeight)}
        >
          {Array.from({ length: columns }, (_unused, columnIndex) => (
            <Skeleton key={columnIndex} className="h-3 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
