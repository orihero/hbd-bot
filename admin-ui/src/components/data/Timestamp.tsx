/**
 * `Timestamp` — §11.4's data primitive for every instant on screen.
 *
 * §11.2: "every column is `timestamptz` and three parties may be in three places; an
 * ambiguous '14:32' is a support incident." So this component has exactly one rule it may
 * not break: **the rendered text always carries `Z` or an explicit offset.** There is no
 * prop that turns the zone marker off, and there is no bare-time mode.
 *
 * The zone comes from `usePrefsStore.timeZoneMode` — the top bar's UTC/local toggle — so
 * flipping that toggle repaints every timestamp in the app in one commit. A `mode` prop
 * overrides it only for the rare surface that must pin a zone (a diff against a log line).
 *
 * `relative` swaps the VISIBLE text for `2h ago` and keeps the absolute instant in the
 * `title` and in `dateTime`. §11.4's rule stands: relative time is a second label, never
 * the only one — "2h ago" cannot be correlated with a log line.
 */

import { type ReactElement } from "react";

import {
  cn,
  EMPTY_VALUE,
  formatRelative,
  formatTimestamp,
  parseInstant,
  timeZoneLabel,
  usePrefsStore,
  type TimeZoneMode,
} from "@/lib";

export interface TimestampProps {
  /** The wire instant. `null`/`undefined`/unparseable all render `—`. */
  readonly at: string | null | undefined;
  /** Pin the zone, ignoring the top bar toggle. Almost never what you want. */
  readonly mode?: TimeZoneMode;
  /** Render `:ss`. On by default nowhere — ask for it on audit and timeline rows. */
  readonly seconds?: boolean;
  /** Show `2h ago` as the visible text; the absolute instant stays in the tooltip. */
  readonly relative?: boolean;
  readonly className?: string;
}

export function Timestamp({
  at,
  mode,
  seconds = false,
  relative = false,
  className,
}: TimestampProps): ReactElement {
  const storeMode = usePrefsStore((state) => state.timeZoneMode);
  const effectiveMode = mode ?? storeMode;
  const parsed = parseInstant(at);

  if (parsed === null) {
    return (
      <span className={cn("num text-ink-muted", className)} data-empty="true">
        {EMPTY_VALUE}
      </span>
    );
  }

  const absolute = formatTimestamp(at, effectiveMode, { seconds });
  const relativeText = formatRelative(at);

  return (
    <time
      dateTime={parsed.toISOString()}
      title={relative ? absolute : `${absolute} · ${relativeText}`}
      data-timezone-mode={effectiveMode}
      className={cn("num whitespace-nowrap", className)}
    >
      {relative ? relativeText : absolute}
    </time>
  );
}

/**
 * The label for a column header or an axis caption that renders `Timestamp`s: `UTC` or
 * `+05:00`. A grid of instants says which clock it is in once, at the top, rather than
 * repeating the offset in forty rows.
 */
export function TimeZoneCaption({ className }: { readonly className?: string }): ReactElement {
  const mode = usePrefsStore((state) => state.timeZoneMode);
  return (
    <span className={cn("type-caption text-ink-muted", className)} data-timezone-mode={mode}>
      {timeZoneLabel(mode)}
    </span>
  );
}
