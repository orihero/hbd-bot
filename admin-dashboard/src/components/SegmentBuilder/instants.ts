/**
 * The date controls' arithmetic: a day an operator picked, in their own zone, into the aware
 * RFC 3339 instant the compiler demands — and back.
 *
 * Three properties, all of them the server's rules restated rather than invented:
 *
 * **Local, not UTC.** An operator filtering "from the 7th" means their 7th. `<input
 * type="date">` yields `YYYY-MM-DD` with no zone at all, so the conversion has to choose one,
 * and the only choice that matches what was typed is the browser's. `toISOString()` then
 * writes it back as a `Z` instant, which carries the offset the compiler insists on
 * (`_as_instant`: a naive instant is a refusal, never a guess about which zone it meant).
 *
 * **Half-open, `[from, to)`.** `between` is `expr >= low AND expr < high`, the same convention
 * `apply_window` uses, so a June segment and a June dashboard tile count the same rows and the
 * account that landed exactly on 1 July belongs to July in both. "To the 7th" is therefore the
 * instant the 8th begins, and {@link dateInputValue} steps an exclusive end back before
 * showing it so the day the operator picked is the day the box redisplays.
 *
 * **A half-typed field yields `null`, never a string the server will refuse.** A 422 empties
 * the audience and blames a parameter nobody typed; an incomplete rule is the builder's own
 * problem to name (`segmentValidation.betweenIncomplete`), on screen, before submit.
 *
 * `monthRangeIso` exists because "people who joined in June" is one of the four audiences this
 * feature was asked for by name, and spelling it as two separate day pickers is four controls
 * and an off-by-one waiting to happen. A native `<input type="month">` makes it one gesture
 * that lands on the half-open pair by construction.
 */

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/u;
const MONTH_PATTERN = /^\d{4}-\d{2}$/u;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function isoOfLocalDay(year: number, month: number, day: number): string | null {
  const at = new Date(year, month - 1, day);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString();
}

/** `YYYY-MM-DD` → the RFC 3339 instant that day BEGINS, in the operator's own zone. */
export function startOfLocalDayIso(day: string): string | null {
  if (!DAY_PATTERN.test(day)) return null;
  const parts = day.split("-");
  return isoOfLocalDay(Number(parts[0]), Number(parts[1]), Number(parts[2]));
}

/** The same day's EXCLUSIVE end: the instant the next day begins. */
export function endOfLocalDayExclusiveIso(day: string): string | null {
  if (!DAY_PATTERN.test(day)) return null;
  const parts = day.split("-");
  return isoOfLocalDay(Number(parts[0]), Number(parts[1]), Number(parts[2]) + 1);
}

/**
 * An instant from the document, back into what a `<input type="date">` shows.
 *
 * `""` for anything that is not an instant — including a value a hand-edited URL put there.
 * The document keeps its exact value until the field is changed, so nothing is silently
 * rounded behind an operator's back.
 */
export function dateInputValue(value: unknown, bound: "start" | "endExclusive"): string {
  if (typeof value !== "string" || value === "") return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  const shown = bound === "endExclusive" ? new Date(at.getTime() - 1) : at;
  return `${String(shown.getFullYear())}-${pad(shown.getMonth() + 1)}-${pad(shown.getDate())}`;
}

/** `YYYY-MM` → the half-open `[first of that month, first of the next)`, in the operator's zone. */
export function monthRangeIso(month: string): readonly [string, string] | null {
  if (!MONTH_PATTERN.test(month)) return null;
  const parts = month.split("-");
  const year = Number(parts[0]);
  const index = Number(parts[1]);
  const from = isoOfLocalDay(year, index, 1);
  const to = isoOfLocalDay(year, index + 1, 1);
  if (from === null || to === null) return null;
  return [from, to];
}

/**
 * The `YYYY-MM` a `between` pair spells, when it spells one exactly.
 *
 * `""` when the pair is any other range — the month box then shows nothing rather than
 * claiming a month the two day bounds do not actually describe.
 */
export function monthInputValue(from: unknown, to: unknown): string {
  if (typeof from !== "string" || typeof to !== "string") return "";
  const start = new Date(from);
  const end = new Date(to);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "";
  const candidate = `${String(start.getFullYear())}-${pad(start.getMonth() + 1)}`;
  const range = monthRangeIso(candidate);
  if (range === null) return "";
  return range[0] === from && range[1] === to ? candidate : "";
}

/**
 * One instant, as a chip reads it: a day, in the operator's locale and zone.
 *
 * The time of day is deliberately dropped. Every instant this builder mints is a local
 * midnight, so printing `00:00` would be noise; an instant a hand-edited URL put there prints
 * as the day it falls in, and the document keeps the exact value it carried.
 */
export function formatInstantDay(value: unknown, locale: string): string {
  if (typeof value !== "string" || value === "") return String(value);
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(at);
}
