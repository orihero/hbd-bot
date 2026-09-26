/**
 * The render ledger's vocabulary, and the two numbers on it that must not be believed.
 *
 * A leaf module, imported by the screen, its filter controls and its detail panel alike. It
 * exists because those three files each need the same words for the same wire members, and a
 * `kind` humanised two ways is a screen whose chip and whose column disagree about what the
 * operator filtered on.
 *
 * ## `costUsd` and `latencyMs` are claims, not measurements
 *
 * Both columns are NOT NULL with defaults of `0.0`/`0` and nothing in `src/bayram` writes
 * either, so every row in production today is uninstrumented. The wire says so twice — the
 * value arrives `null`, and `isInstrumented` is `false` — and this module refuses to render
 * either as a number. "$0.00 / 0 ms" on the one screen an operator uses to decide what to
 * spend is a confident lie, and once Phase 5 starts writing real numbers a genuinely free,
 * instantaneous vendor call would be indistinguishable from a row nobody ever measured.
 *
 * The copy is the dashboard's own — `adapt.ts` prints `not_instrumented` as "not tracked",
 * and one console should not have two words for one absence. `formatCount`/`formatUsd` come
 * from there for the same reason: the digit grouping is a decision, made once.
 *
 * ## The enum labels are prose, and two of them are traps
 *
 * `uz_latn` and `uz_cyrl` are two SCRIPTS of one language. Collapsing them into "Uzbek" would
 * make a filter chip claim a filter the operator did not set and hide the one they did.
 * `openai-compat` is hyphenated where its neighbours are not; that is the literal in
 * `providers/llm/openai_compat.py`, not a typo to tidy on the way past.
 */

import type { GenerationKind, NameStrategy } from "@/api/generations";
import type { TranslationPath } from "@/i18n/types";
import { formatCount, formatDuration, formatUsd } from "@/features/dashboard/adapt";

/* -------------------------------------------------------------------------- */
/* Absence, in its several kinds                                               */
/* -------------------------------------------------------------------------- */

/** Telemetry that was never written. The dashboard's word for the same fact. */
export const NOT_TRACKED = "not tracked";

/** `isNameVerified === null`: the verifier never ran. Not a pass, and not a failure. */
export const VERIFICATION_NOT_RUN = "did not run";

/**
 * `provider === null` on a `name_verification` row.
 *
 * The model says it outright: "None for a NAME_VERIFICATION verdict, which is our own
 * judgement, not a vendor's." An em dash there would read as missing data about a vendor call
 * that never happened.
 */
/* `generations.noVendorCall` carries this now. */

/**
 * `isOrphaned` / `orderId === null`, in one sentence, because a bare flag is unreadable.
 *
 * The predicate is `order_id IS NULL` and it has TWO causes that the row cannot tell apart: a
 * name preview rendered before any order existed, and an attempt whose order was deleted —
 * the FK sets null rather than cascading precisely so the tuning signal outlives the orders
 * it was collected from. Nothing here guesses which.
 */
/* The sentence is `generations.orphanedExplanation`, and the badge over it
 * `generations.orphanedLabel`. */

/* -------------------------------------------------------------------------- */
/* Closed vocabularies, in operator words                                      */
/* -------------------------------------------------------------------------- */

export const GENERATION_KIND_KEY: Readonly<Record<GenerationKind, TranslationPath>> = {
  song: "generations.kinds.song",
  song_inpaint: "generations.kinds.song_inpaint",
  greeting: "generations.kinds.greeting",
  lyrics: "generations.kinds.lyrics",
  name_preview: "generations.kinds.name_preview",
  name_verification: "generations.kinds.name_verification",
  cover: "generations.kinds.cover",
};

export const NAME_STRATEGY_KEY: Readonly<Record<NameStrategy, TranslationPath>> = {
  canonical: "generations.strategies.canonical",
  stripped: "generations.strategies.stripped",
  ascii: "generations.strategies.ascii",
  cyrillic: "generations.strategies.cyrillic",
  hyphenated: "generations.strategies.hyphenated",
  phonetic: "generations.strategies.phonetic",
};

/* Two scripts, two entries, never one "Uzbek" — and one table for the whole console, in
 * `@/lib/languageLabel`. */

/* -------------------------------------------------------------------------- */
/* Telemetry                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * `$3.47`, or "not tracked".
 *
 * Two independent ways of saying the same thing, and either one is enough: `isInstrumented`
 * false means the row's telemetry was never written, and a `null` value means this particular
 * number was not. Neither is a zero.
 */
export function formatCostUsd(costUsd: number | null, isInstrumented: boolean): string {
  if (!isInstrumented || costUsd === null) return NOT_TRACKED;
  return formatUsd(costUsd);
}

/** `840 ms`, `4m 12s`, or "not tracked". Same rule as the cost. */
export function formatLatencyMs(latencyMs: number | null, isInstrumented: boolean): string {
  if (!isInstrumented || latencyMs === null) return NOT_TRACKED;
  if (latencyMs < 1000) return `${formatCount(latencyMs)} ms`;
  return formatDuration(latencyMs / 1000);
}

/**
 * A similarity ratio as a percentage. `best_similarity` returns 0..1, and the threshold an
 * operator compares it against (`name_match_min_similarity`) is quoted the same way.
 *
 * One decimal, because two candidates in a bake-off are routinely a fraction of a point
 * apart and rounding them to the same integer hides the whole result.
 */
export function formatConfidence(matchConfidence: number | null): string | null {
  if (matchConfidence === null) return null;
  return `${(matchConfidence * 100).toFixed(1)}%`;
}

/** `1 240 chars` — a LENGTH, which is all of the transcript that is on this wire. */
export function formatCharCount(chars: number | null): string | null {
  if (chars === null) return null;
  return `${formatCount(chars)} chars`;
}

/* -------------------------------------------------------------------------- */
/* Time                                                                        */
/* -------------------------------------------------------------------------- */

function pad2(value: number): string {
  return value < 10 ? `0${String(value)}` : String(value);
}

export interface SplitTimestamp {
  /** `2026-09-08`. */
  readonly date: string;
  /** `14:32:05`. Seconds included: two attempts of one stage land in the same minute. */
  readonly time: string;
  /** The whole thing, for a `title` and for the panel's single-line rendering. */
  readonly full: string;
  /** True when the string could not be parsed — the raw value is in `full`. */
  readonly isUnparsed: boolean;
}

/**
 * An RFC 3339 instant in the READER'S timezone, split for the kit's two-line cell.
 *
 * Local rather than UTC because the operator is correlating this against a support
 * conversation and a wall clock. The screen captions the column so the choice is stated
 * rather than assumed. An unparseable value is returned verbatim: inventing an epoch for a
 * string the server sent would put a wrong date on screen with no way to tell.
 */
export function splitTimestamp(iso: string): SplitTimestamp {
  const at = new Date(iso);
  const ms = at.getTime();
  if (Number.isNaN(ms)) return { date: iso, time: "", full: iso, isUnparsed: true };

  const date = `${String(at.getFullYear())}-${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}`;
  const time = `${pad2(at.getHours())}:${pad2(at.getMinutes())}:${pad2(at.getSeconds())}`;
  return { date, time, full: `${date} ${time}`, isUnparsed: false };
}

/** The reader's zone, named, so a timestamp column is not a guess. `UTC+5`, `UTC-3:30`. */
export function localZoneLabel(): string {
  // `getTimezoneOffset` is minutes WEST of UTC, so its sign is inverted from the label's.
  const minutesWest = new Date().getTimezoneOffset();
  const sign = minutesWest <= 0 ? "+" : "-";
  const total = Math.abs(minutesWest);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return minutes === 0
    ? `UTC${sign}${String(hours)}`
    : `UTC${sign}${String(hours)}:${pad2(minutes)}`;
}

/**
 * `<input type="datetime-local">` wants `YYYY-MM-DDTHH:mm` in LOCAL time; the API wants
 * RFC 3339. These two are the only conversion between them, so a filter round-trips through
 * the URL without drifting an hour each way.
 */
export function isoToLocalInput(iso: string | null): string {
  if (iso === null) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return (
    `${String(at.getFullYear())}-${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}` +
    `T${pad2(at.getHours())}:${pad2(at.getMinutes())}`
  );
}

/** The inverse. `""` (the input cleared) is `null`, which OMITS the parameter — `?from=` is a 422. */
export function localInputToIso(value: string): string | null {
  if (value === "") return null;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString();
}
