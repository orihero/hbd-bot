/**
 * What the dashboard's components share once the fixtures are gone: the chart viewBox they
 * are all drawn in, the period picker's vocabulary, and the header's copy.
 *
 * Every fixture array that used to live here (SIGNUPS, DELIVERED, REVCOST, CPS, COSTSPLIT,
 * FUNNEL, ROWS and the tick tables) has been DELETED, not commented out. They were the
 * mockup's numbers, and a demo number that survives into production is one an operator
 * believes. The numbers now come from `adapt.ts`, the card metadata from `cardSpecs.ts`, and
 * both of those are keyed off a real response or they render a hatched pill instead.
 *
 * The header's "1 USD = 12 800 soʻm" was the last hardcoded measurement on the page — a stale
 * FX rate stated as fact. It is now `headerMeta`, a function of the finance response's own `fx`
 * block alone, and it prints nothing at all when that block carries no rate.
 */

import type { FxRateView, WindowView } from "@/api/dashboard";
import { formatCount } from "@/features/dashboard/adapt";
import type { TranslationPath } from "@/i18n/types";

/** What every function here needs to say anything: the caller's bound `t`. */
export type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

/** The picker, the grains and the window maths live in `window.ts`. Re-exported, never copied. */
export type { Period, Gran, ApiWindow } from "@/features/dashboard/window";
export { granFor, isGranLegal, bucketFor, windowFor } from "@/features/dashboard/window";

import type { Period } from "@/features/dashboard/window";

/* `PeriodValue`, `StatSpec` and `StatRow` lived here too. They described a card assembled
   from a fixture — a pre-formatted `value`, a `pv` table of one canned figure per period.
   The live page never builds one: `cardSpecs.ts` owns a card's metadata and `adapt.ts`
   derives its number from a response, so the two halves meet as `CardSpec` + `CardValue`. */

/** Chart viewBox. Every figure is drawn in this fixed coordinate space and scaled by CSS. */
export const CW = 651;
export const CH = 176;

export const PERIODS: readonly Period[] = ["today", "week", "month", "year"];

/**
 * The picker's vocabulary, as KEYS.
 *
 * These were the words themselves until the console became multilingual. A module-level
 * string is resolved once, at import — which is before an operator has chosen a language and
 * long before they can change it — so the label has to stay a key until a component renders
 * it.
 */
export const PERIOD_LABEL_KEY: Record<Period, TranslationPath> = {
  today: "dashboard.periods.today",
  week: "dashboard.periods.week",
  month: "dashboard.periods.month",
  year: "dashboard.periods.year",
};

export const MINI_KEY: Record<Period, TranslationPath> = {
  today: "dashboard.periodsMini.today",
  week: "dashboard.periodsMini.week",
  month: "dashboard.periodsMini.month",
  year: "dashboard.periodsMini.year",
};

/*
 * The header's title used to live here as `HEADER.title`. It is `dashboard.title` now, read
 * during render like every other word on the page.
 *
 * The mock's second piece, `live: "LIVE · 5s"`, is gone: it named a poll interval that is not
 * the one this page runs, and it printed the same "5s" whether a read had just landed or had
 * been failing for an hour. `LiveChip` reports the age `useLiveness` actually observed.
 */

const MONTHS_EN: readonly string[] = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * `07 Sep`, in the operator's own zone — the same zone the header's clock is printed in — and
 * in the operator's own language.
 *
 * `Intl` rather than twelve more catalogue keys: a month abbreviation is one of the few
 * strings a browser already knows in every locale this console offers, and three hand-written
 * tables would be three chances to misspell one. The English table survives as the fallback
 * for an environment with no `Intl` data for the locale, which is the only case where the
 * catalogue would have been the better answer.
 */
function dayMonth(at: Date, locale: string): string {
  const day = `${at.getDate() < 10 ? "0" : ""}${String(at.getDate())}`;
  try {
    const month = new Intl.DateTimeFormat(locale, { month: "short" }).format(at);
    return `${day} ${month}`;
  } catch {
    return `${day} ${MONTHS_EN[at.getMonth()] ?? ""}`;
  }
}

/** The finance read failed, so the rate is unknown rather than absent. */
export const UNAVAILABLE = "unavailable";

/**
 * What the header knows about the rate: the published one, `null` for "this deployment
 * publishes none", or `UNAVAILABLE` for "the read that would have said never answered".
 */
export type FxState = FxRateView | null | typeof UNAVAILABLE;

/**
 * `1 USD = 12 800 soʻm (05 Sep)`, or nothing at all.
 *
 * The line used to open `08:04 · UTC+5 ·`. Neither segment was a measurement this dashboard
 * took: the operating system already prints the wall clock and the zone, one of them in the
 * same screen corner, and a console whose first two segments restate the reader's own desk has
 * spent the line before reaching anything it knows.
 *
 * **The two ABSENCE clauses went with them, and that is the one real loss here.** `FX rate
 * unavailable` and `no FX rate published` drew a distinction that is genuine — a read that
 * failed never heard either way, which is not the same as a deployment that publishes no rate —
 * and the header is no longer where it is drawn. The distinction still exists in `FxState` and
 * still governs every conversion downstream; what is gone is a sentence in the one place on the
 * page sized for a title and a figure. A header with no rate in it is already the honest report
 * that there is no rate to show.
 *
 * `asOf` STAYS. The rate is hand-published with no feed behind it, so the date is the only
 * staleness signal it has, and it is a property OF the figure rather than a sentence about it.
 */
export function headerMeta(fx: FxState, t: Translate, locale: string): string {
  if (fx === UNAVAILABLE || fx === null || fx.uzsPerUsd === null) return "";
  const taken = fx.asOf === null ? "" : ` (${dayMonth(calendarDate(fx.asOf), locale)})`;
  return `${t("dashboard.fx.rate", { rate: formatCount(fx.uzsPerUsd) })}${taken}`;
}

/**
 * `to 07 Sep`, or `all time` when the response counted from the first row ever recorded.
 *
 * A null `window` is the whole record; a null `from` inside one is the same statement about
 * the lower bound. Neither is a date, and printing one would be inventing a start.
 */
export function headerAsOf(window: WindowView | null, t: Translate, locale: string): string {
  if (window === null) return t("dashboard.header.allTime");
  const to = new Date(window.to);
  if (Number.isNaN(to.getTime())) return t("dashboard.header.allTime");
  const date = dayMonth(to, locale);
  return window.from === null
    ? t("dashboard.header.allTimeTo", { date })
    : t("dashboard.header.to", { date });
}

/**
 * `FxRateView.asOf` is a calendar DATE (`YYYY-MM-DD`), not an instant. Parsed by hand
 * because `new Date("2026-09-05")` is midnight UTC and prints as the 4th west of Greenwich.
 */
function calendarDate(iso: string): Date {
  const [y = "0", m = "1", d = "1"] = iso.split("-");
  return new Date(Number(y), Number(m) - 1, Number(d));
}
