/**
 * Formatting. Numbers, instants, durations and our own closed-vocabulary labels.
 *
 * **Nothing in this file touches user content.** A recipient name, a note, a lyric, a
 * Telegram username: those reach the DOM through `<NameText>` unmodified, and the case- and
 * normalisation-folding calls that would destroy them are banned by lint inside
 * `components/domain/`. The functions here take numbers, ISO strings and enum members —
 * strings WE wrote — and are free to do what they like to those.
 *
 * ## Why every timestamp carries its zone
 *
 * §11.2: every column is `timestamptz` and three parties may be in three places — the
 * customer in Tashkent, the operator wherever they are, the server in UTC. **An ambiguous
 * "14:32" is a support incident.** So there is no bare-time formatter here. Every rendered
 * instant carries either a `Z` or an explicit offset, and the UTC/local toggle in the top bar
 * chooses which. `TimeZoneMode` is threaded from `usePrefsStore`.
 *
 * The UTC path is built from the ISO string arithmetically rather than through
 * `Intl.DateTimeFormat`, so it cannot pick up a host locale's calendar, numbering system or
 * digit shaping: an operator's machine set to `ar-EG` must not render an audit timestamp in
 * Eastern Arabic numerals that nobody can diff against a log line.
 */

/** Which clock the operator is reading. Persisted in `usePrefsStore`. */
export type TimeZoneMode = "utc" | "local";

/** Parse a wire instant. `null` for anything unparseable — never `Invalid Date` on screen. */
export function parseInstant(iso: string | null | undefined): Date | null {
  if (iso === null || iso === undefined || iso === "") return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : new Date(ms);
}

/** What a missing value renders as. An em dash, never an empty cell — an empty cell reads as
 *  a rendering bug, and half these fields are legitimately null. */
export const EMPTY_VALUE = "—";

const pad = (value: number, width = 2): string => String(value).padStart(width, "0");

/** `2026-09-02` in the chosen zone. */
export function formatDate(iso: string | null | undefined, mode: TimeZoneMode = "utc"): string {
  const at = parseInstant(iso);
  if (at === null) return EMPTY_VALUE;
  return mode === "utc"
    ? `${String(at.getUTCFullYear())}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`
    : `${String(at.getFullYear())}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

/**
 * `2026-09-02 14:32Z` or `2026-09-02 19:32 +05:00`.
 *
 * The zone marker is not decoration and must not be dropped to save width. If a column is
 * too narrow for it, narrow the date, not the offset.
 */
export function formatTimestamp(
  iso: string | null | undefined,
  mode: TimeZoneMode = "utc",
  options: { seconds?: boolean } = {},
): string {
  const at = parseInstant(iso);
  if (at === null) return EMPTY_VALUE;
  const withSeconds = options.seconds ?? false;
  if (mode === "utc") {
    const time = `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}${
      withSeconds ? `:${pad(at.getUTCSeconds())}` : ""
    }`;
    return `${formatDate(iso, "utc")} ${time}Z`;
  }
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}${
    withSeconds ? `:${pad(at.getSeconds())}` : ""
  }`;
  return `${formatDate(iso, "local")} ${time} ${localOffsetLabel(at)}`;
}

/** `+05:00`. `getTimezoneOffset` is minutes WEST of UTC, so the sign is inverted. */
export function localOffsetLabel(at: Date = new Date()): string {
  const minutesWestOfUtc = at.getTimezoneOffset();
  const sign = minutesWestOfUtc <= 0 ? "+" : "−";
  const total = Math.abs(minutesWestOfUtc);
  return `${sign}${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

/** What the UTC/local toggle shows as its current setting. */
export function timeZoneLabel(mode: TimeZoneMode): string {
  return mode === "utc" ? "UTC" : localOffsetLabel();
}

/**
 * `2m ago`, `3h ago`, `in 4d`.
 *
 * Relative time is a SECOND label, never the only one: "2h ago" is unusable for correlating
 * with a log line. Pair it with `formatTimestamp` (a tooltip, or a second line).
 */
export function formatRelative(
  iso: string | null | undefined,
  now: number = Date.now(),
): string {
  const at = parseInstant(iso);
  if (at === null) return EMPTY_VALUE;
  const deltaS = Math.round((at.getTime() - now) / 1_000);
  const magnitude = Math.abs(deltaS);
  const suffix = deltaS < 0 ? " ago" : "";
  const prefix = deltaS < 0 ? "" : "in ";
  if (magnitude < 45) return deltaS < 0 ? "just now" : "in a moment";
  if (magnitude < 3_600) return `${prefix}${String(Math.round(magnitude / 60))}m${suffix}`;
  if (magnitude < 86_400) return `${prefix}${String(Math.round(magnitude / 3_600))}h${suffix}`;
  if (magnitude < 2_592_000) return `${prefix}${String(Math.round(magnitude / 86_400))}d${suffix}`;
  return `${prefix}${String(Math.round(magnitude / 2_592_000))}mo${suffix}`;
}

/** Days until an instant, negative when it is past. Drives §11.2's "expiring within 7 days"
 *  and the retention clocks. */
export function daysUntil(iso: string | null | undefined, now: number = Date.now()): number | null {
  const at = parseInstant(iso);
  if (at === null) return null;
  return Math.ceil((at.getTime() - now) / 86_400_000);
}

/** `1.4s`, `320ms`, `2m 05s`. For `durationMs` and latency figures. */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return EMPTY_VALUE;
  if (ms < 1_000) return `${String(Math.round(ms))}ms`;
  const seconds = ms / 1_000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes)}m ${pad(Math.round(seconds - minutes * 60))}s`;
}

/** The same, for the seconds-valued fields (`p50Seconds`, `durationS`). */
export function formatDurationS(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return EMPTY_VALUE;
  return formatDurationMs(seconds * 1_000);
}

/* -------------------------------------------------------------------------- */
/* Numbers                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * `1,204`. Every element that renders one of these also carries the `.num` class
 * (`font-variant-numeric: tabular-nums slashed-zero`, §11.3), so a digit does not change
 * width as a poll ticks.
 *
 * `en-US` is pinned rather than left to the host locale: a grouping separator that changes
 * with the operator's machine makes two screenshots of the same number look like different
 * numbers.
 */
export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

/**
 * `10,000+` when the count hit `TOTAL_COUNT_CAP`.
 *
 * `bounded_total` stops counting at 10,000, so `{total: 10000, isTotalExact: false}` means
 * "at least ten thousand". Rendering a flat 10,000 there is a wrong number, not a rounded
 * one.
 */
export function formatTotal(total: number | null, isTotalExact: boolean | null): string {
  if (total === null) return EMPTY_VALUE;
  return isTotalExact === false ? `${formatInteger(total)}+` : formatInteger(total);
}

/**
 * `94.2%` from a 0–1 rate.
 *
 * `null` is a THIRD state, not zero: `successRate` is `null` when `terminalCount === 0`, and
 * a 0% success rate on a quiet morning is the most alarming wrong number the dashboard could
 * show. It renders as `—`.
 */
export function formatRate(rate: number | null | undefined, digits = 1): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return EMPTY_VALUE;
  return `${(rate * 100).toFixed(digits)}%`;
}

/** §11.2's Live-Ops colour rule: green ≥95%, amber 85–95%, red <85%. `null` is neither. */
export type RateBand = "good" | "warn" | "bad" | "unknown";

export function rateBand(rate: number | null | undefined): RateBand {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return "unknown";
  if (rate >= 0.95) return "good";
  if (rate >= 0.85) return "warn";
  return "bad";
}

/**
 * `$0.0142`, or "not instrumented".
 *
 * `costUsd` is `null` — never `0` — when `isInstrumented` is false, which is every row in
 * production today. Rendering `$0.00` would tell an operator the call was free.
 */
export function formatCostUsd(
  costUsd: number | null | undefined,
  isInstrumented: boolean,
): string {
  if (!isInstrumented) return "not instrumented";
  if (costUsd === null || costUsd === undefined || !Number.isFinite(costUsd)) return EMPTY_VALUE;
  return `$${costUsd.toFixed(4)}`;
}

/**
 * What an unpriced figure says. Not `$0.00`, and not "not instrumented" either — the call
 * WAS recorded; nothing in this deployment knows what it costs.
 *
 * **Two functions here bottom out in this one string** — `formatSpendUsd` with `isPriced`
 * false, and `costSourceLabel` with a `null` source — and both are true of the same row at
 * the same time, because the database will not let a cost exist without a source. A caller
 * that renders the money and its provenance side by side must therefore print ONE of them
 * for an unpriced row: `/vendors` shipped with both, and every speech group read "not priced
 * not priced". See `VendorsScreen`'s cost column for the shape that fixes it — the value
 * carries the absence, the provenance chip is omitted when there is no provenance to report.
 */
export const NOT_PRICED_LABEL = "not priced";

/**
 * `$12.34`, or "not priced", or `—`.
 *
 * The aggregate twin of `formatCostUsd`, and the two differ on purpose in both arguments:
 *
 *  - **Two decimals, not four.** A sum over a window is money an operator compares against
 *    an invoice, and `$12.3400` reads as a precision the estimate legs do not have.
 *    `formatCostUsd`'s four decimals stay exactly as they are for a SINGLE call, where the
 *    third and fourth digits are the whole figure.
 *  - **`isPriced`, not `isInstrumented`.** They are different absences and they arrive from
 *    different probes. A vendor call can be fully recorded — latency, tokens, status — and
 *    still carry no cost, because no rate is configured for that leg. "not instrumented"
 *    would be a false claim about the row.
 *
 * `null` with `isPriced` true is the third case and renders `EMPTY_VALUE`: this deployment
 * prices *something*, and it does not price THIS. Never `$0.00` — a zero here would say the
 * vendor did the work for free.
 */
export function formatSpendUsd(costUsd: number | null | undefined, isPriced: boolean): string {
  if (!isPriced) return NOT_PRICED_LABEL;
  if (costUsd === null || costUsd === undefined || !Number.isFinite(costUsd)) return EMPTY_VALUE;
  return `$${costUsd.toFixed(2)}`;
}

/**
 * How a cost figure was arrived at, in an operator's words rather than the wire's.
 *
 * The word is rendered BESIDE the money and never instead of it, because the four sources
 * are four different strengths of claim about the same `$`: a vendor-reported figure is what
 * we will be billed, a derived one is our arithmetic over the vendor's own counts, and an
 * estimate is our arithmetic over a quantity we chose ourselves — a requested duration, a
 * character count we guessed. `"mixed"` says a group's legs were priced more than one way,
 * which is a fact about the total and not a defect in it.
 *
 * Takes a bare `string` rather than `CostSource` so it can label a value that has already
 * been widened by a rollup or a fixture; an unrecognised member falls through to the same
 * answer as `null`, which is the honest one — we do not know what this cost.
 *
 * `null` in returns `NOT_PRICED_LABEL`, which is also what `formatSpendUsd` returns for the
 * same row — so do not render both. That constant's note says which one to keep.
 */
export function costSourceLabel(source: string | null): string {
  if (source === "vendor_reported") return "vendor-reported";
  if (source === "derived") return "derived";
  if (source === "estimated") return "estimated";
  if (source === "mixed") return "mixed";
  return NOT_PRICED_LABEL;
}

/** The same rule for `latencyMs`. */
export function formatLatencyMs(
  latencyMs: number | null | undefined,
  isInstrumented: boolean,
): string {
  if (!isInstrumented) return "not instrumented";
  return formatDurationMs(latencyMs);
}

/** The latency classification band (< 1s fast, 1-5s neutral, 5-15s slow, > 15s critical). */
export type LatencyBand = "fast" | "neutral" | "slow" | "critical" | "unknown";

export function latencyBand(ms: number | null | undefined): LatencyBand {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "unknown";
  if (ms < 1_000) return "fast";
  if (ms <= 5_000) return "neutral";
  if (ms <= 15_000) return "slow";
  return "critical";
}


/**
 * `1.4 MB`.
 *
 * Present because `AssetWireView.sizeBytes` exists — but §11.2 is explicit that storage size
 * is NOT shown on `/assets`, because `size_bytes` is always 0 today. Use this only where a
 * real byte count exists.
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return EMPTY_VALUE;
  if (bytes < 1024) return `${String(bytes)} B`;
  const units = ["KB", "MB", "GB", "TB"] as const;
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex] ?? "TB"}`;
}

/* -------------------------------------------------------------------------- */
/* Labels for our own closed vocabularies                                      */
/* -------------------------------------------------------------------------- */

/**
 * Turn a snake_case enum MEMBER into a human label: `brief_ready` → `brief ready`.
 *
 * Safe because the input is always one of OUR enum values — never a customer's string. Do
 * not reach for this to render a name, a note, or anything that came from a person; that is
 * what `<NameText>` is for, and this function's `replace` would be the start of exactly the
 * mangling §11.4 bans.
 */
export function humaniseEnum(value: string): string {
  return value.replace(/_/g, " ");
}

/**
 * The tri-state retryability label. Three states, never two.
 *
 * `null` means no class in `bayram.errors` claims the code — the system has no opinion, so the
 * UI must not invent one. "unknown" is not "not retryable": one is an absent decision, the
 * other is a decision, and only the second justifies hiding a retry button as settled.
 */
export function retryabilityLabel(isRetryable: boolean | null): string {
  if (isRetryable === null) return "unknown";
  return isRetryable ? "retryable" : "terminal";
}

/** The glyph half of §11.3's "status pills are never colour alone": `↻` retryable (amber),
 *  `■` terminal (red), `?` unknown. */
export function retryabilityGlyph(isRetryable: boolean | null): string {
  if (isRetryable === null) return "?";
  return isRetryable ? "↻" : "■";
}

/**
 * §11.3's status glyphs, exactly. Glyph + text + colour, so a pill survives greyscale and a
 * bad projector.
 *
 * `◉ generating` is the only animated one. `held` has no `OrderState` member on this build —
 * it is here because §11.3 lists the glyph and a later phase adds the state.
 */
export const STATUS_GLYPH = {
  draft: "○",
  brief_ready: "◔",
  lyrics_ready: "◑",
  authorized: "◆",
  generating: "◉",
  delivered: "✓",
  failed: "✗",
  cancelled: "⊘",
  held: "⚑",
} as const satisfies Record<string, string>;

export type StatusGlyphKey = keyof typeof STATUS_GLYPH;

/** The glyph for an order state, or `null` if this build has no glyph for it. */
export function statusGlyph(state: string): string | null {
  return state in STATUS_GLYPH ? STATUS_GLYPH[state as StatusGlyphKey] : null;
}

/** The CSS custom property carrying an order state's colour, for an inline `style`. */
export function orderStateColorVar(state: string): string {
  return `var(--st-${state.replace(/_/g, "-")})`;
}

/** The same for a pipeline status. */
export function pipelineStatusColorVar(status: string): string {
  return `var(--pg-${status.replace(/_/g, "-")})`;
}
