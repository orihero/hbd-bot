/**
 * The page's two controls, translated into the API's query parameters.
 *
 * The header carries one period picker (Today · Week · Month · Year) and each chart declares
 * the grains it can honestly draw. Everything the wire needs is derived here, in one place,
 * so a card and the chart under it cannot end up describing two different ranges.
 *
 * **Week, Month and Year are ROLLING windows, not calendar ones.** The mock says so on the
 * Active-users card ("rolling window, not calendar") and again on two chart captions ("last
 * 30d"), and the server counts a half-open `[from, to)` over whatever it is given — it has no
 * notion of a month boundary. A calendar month would also make the 1st of the month a card
 * reading "3 orders, -97%", which is a measurement of the calendar and not of the business.
 *
 * **Today is the exception, and it is the operator's calendar day, not a trailing 24h.**
 * "Today" is a word about a clock somebody is looking at. It is taken in LOCAL time, because
 * the mock's header prints a local offset (`08:04 · UTC+5`) and an operator asking for today
 * at 02:00 local means the two hours since midnight, not the tail of yesterday. The cost of
 * that choice is real and worth knowing: the server buckets series by UTC day, so a local
 * day that starts at 19:00 UTC lands across two of them, and an hourly series is the only
 * grain that renders "today" cleanly under a non-UTC offset. `granFor` already prefers
 * hourly for `today`.
 */

import { SERIES_BUCKET_VALUES, type SeriesBucket } from "@/api/dashboard";

/** The header's period picker. */
export type Period = "today" | "week" | "month" | "year";

/** The grains a chart may declare. Mapped onto the server's `SeriesBucket` by `bucketFor`. */
export type Gran = "hourly" | "daily" | "weekly" | "monthly";

/**
 * A resolved window, RFC 3339 with a `Z` suffix — the server refuses a naive instant with a
 * 422 naming the parameter, so these are always UTC-offset strings.
 *
 * Both ends are always sent even though the server accepts either alone: a lower bound is
 * what earns the `previous`/`change` arm on every `TrendView` and what allows the count
 * series to be zero-filled at all (`SeriesResponse.isZeroFilled`).
 */
export interface ApiWindow {
  readonly from: string;
  readonly to: string;
}

/** Trailing spans, in days. A year is 365 days and not a calendar one, for the reason above. */
const TRAILING_DAYS: Record<Exclude<Period, "today">, number> = {
  week: 7,
  month: 30,
  year: 365,
};

const MS_PER_DAY = 86_400_000;

/**
 * The `[from, to)` a period means, ending at `now`.
 *
 * `now` is a parameter rather than a `Date.now()` inside, so every section of one refresh is
 * asked for the same window — two clock reads a few milliseconds apart put a card and its
 * chart on opposite sides of a bucket boundary.
 */
export function windowFor(period: Period, now: Date): ApiWindow {
  const to = now.toISOString();
  if (period === "today") {
    // Local midnight: `Date`'s own y/m/d are the browser's, and the constructor reads them
    // back in the same zone, so this is the operator's calendar day with no zone arithmetic.
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return { from: midnight.toISOString(), to };
  }
  const from = new Date(now.getTime() - TRAILING_DAYS[period] * MS_PER_DAY);
  return { from: from.toISOString(), to };
}

/** A chart's declared grain, as the `?bucket=` member the server accepts. */
export function bucketFor(gran: Gran): SeriesBucket {
  return BUCKET[gran];
}

/**
 * Lowercase, verified against `bayram/admin/schemas/overview.py:199` and the exported OpenAPI —
 * `hour` | `day` | `week` | `month`. Spelled through `SERIES_BUCKET_VALUES` so a drift in the
 * enum is a type error here rather than a 422 in the browser.
 */
const BUCKET: Record<Gran, SeriesBucket> = {
  hourly: SERIES_BUCKET_VALUES[0],
  daily: SERIES_BUCKET_VALUES[1],
  weekly: SERIES_BUCKET_VALUES[2],
  monthly: SERIES_BUCKET_VALUES[3],
};

/** Trailing length of each period, in days. `today` is at most one. */
const PERIOD_DAYS: Record<Period, number> = { today: 1, week: 7, month: 30, year: 365 };

/**
 * Nominal length of one bucket, in days. A month is 28 for the same reason the server uses
 * 28: the count this feeds is a CEILING check, so it must over-estimate the bucket count
 * rather than under-estimate it.
 */
const BUCKET_DAYS: Record<Gran, number> = { hourly: 1 / 24, daily: 1, weekly: 7, monthly: 28 };

/**
 * The server's own two refusals, mirrored — `BAYRAM_ADMIN_DASHBOARD_MAX_HOURLY_WINDOW_DAYS` and
 * `BAYRAM_ADMIN_DASHBOARD_MAX_SERIES_BUCKETS`, both at their defaults. A grain outside them is
 * a 422 naming `bucket`, and 422 is terminal: the retry button re-runs the same refusal.
 */
const MAX_HOURLY_WINDOW_DAYS = 8;
const MAX_SERIES_BUCKETS = 750;

/** Below this a "chart" is one or two columns, which is a number with an axis drawn round it. */
const MIN_BUCKETS = 2;

/**
 * Whether the pair `(gran, period)` is one the server will serve AND one worth drawing.
 *
 * The ceiling half is the server's; the floor half is this page's, and it is the rule the
 * `want` table below obeys — never a bucket whose span reaches the window's own, because a
 * rolling seven days bucketed by week is one or two PARTIAL columns whose shape is an
 * artefact of where the window happens to fall.
 */
export function isGranLegal(gran: Gran, period: Period): boolean {
  const days = PERIOD_DAYS[period];
  if (gran === "hourly" && days > MAX_HOURLY_WINDOW_DAYS) return false;
  const buckets = days / BUCKET_DAYS[gran];
  return buckets >= MIN_BUCKETS && buckets <= MAX_SERIES_BUCKETS;
}

/**
 * Finest bucket a chart can honestly draw for the chosen window, preferred finest-first
 * within what the period can legally serve.
 *
 * The two kinds of chart want different things from the same window and the `fine` flag (a
 * chart offering an hourly grain) is what tells them apart: the line charts draw every point
 * they are given, so they want the finest legal grain; the six-column rung charts draw the
 * LAST SIX buckets, so a grain that is too fine shows six days of a year. Hence month →
 * daily for the lines and weekly for the rungs, and year → weekly and monthly.
 *
 * Every candidate is filtered through `isGranLegal`, which is also what keeps `?bucket=hour`
 * inside the server's eight-day ceiling.
 */
export function granFor(grans: readonly Gran[], period: Period): Gran | null {
  if (grans.length === 0) return null;
  const fine = grans.includes("hourly");
  const want: Record<Period, readonly Gran[]> = {
    today: ["hourly", "daily"],
    week: fine ? ["daily", "hourly"] : ["daily", "weekly"],
    month: fine ? ["daily", "weekly"] : ["weekly", "daily"],
    year: fine ? ["weekly", "monthly"] : ["monthly", "weekly"],
  };
  for (const g of want[period]) {
    if (grans.includes(g) && isGranLegal(g, period)) return g;
  }
  // Nothing legal was offered: take the finest the chart declares rather than none at all —
  // a window this short has one bucket whichever grain names it.
  for (const g of ["hourly", "daily", "weekly", "monthly"] as const) {
    if (grans.includes(g)) return g;
  }
  return grans[0] ?? null;
}
