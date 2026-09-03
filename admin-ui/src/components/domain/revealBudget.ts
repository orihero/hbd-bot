/**
 * The reveal budget as the client can honestly know it (§12.3).
 *
 * ## There is no endpoint that answers "what is left"
 *
 * §12.3 promises `/metrics/reveals` charting records-per-actor over seven days and no phase
 * mounts it; `Permission.REVEAL_VOLUME_READ` still guards no route. The only place a
 * REMAINING figure exists on this surface is the `budget` object on a `POST /api/reveal`
 * response — and, on a 429, in the refusal's `details`. `/api/config` publishes the two
 * CEILINGS (`adminRevealRecordsPerHour`, `adminRevealConversationsPerDay`) and nothing about
 * what has been spent.
 *
 * So the meter shows the LAST ANSWER THE SERVER GAVE, stamped with when it gave it, and says
 * "not measured yet" when there is none. It never extrapolates: the counter is a Redis key
 * shared by every tab and every session this account has open, so a locally-decremented guess
 * would be wrong in exactly the situation the budget exists to detect — the same credential
 * revealing from two places at once.
 *
 * ## Two counters, two windows, and `null` is not zero
 *
 * `recordsRemaining` and `conversationsRemaining` are `null` when that counter was NOT
 * TOUCHED: a single-record reveal never reads the daily conversation budget. A meter that
 * rendered "0 left" for "not asked" would stop an operator doing legitimate work, so an
 * untouched counter keeps whatever reading it already had — and only while that reading is
 * still inside its own window.
 *
 * ## The windows are fixed and epoch-aligned, which is why a reset is computable here
 *
 * `budget.py` bakes the window index into the Redis key, so the "hour" resets on the clock
 * hour and the "day" is a UTC day. `windowResetAt` is that arithmetic, and it agrees with the
 * `Retry-After` the server sends on a 429 — which is seconds-to-reset, not the whole window,
 * precisely so a daily budget does not report 86400 when the reset is a minute away.
 */

import {
  REVEAL_CONVERSATIONS_WINDOW_S,
  REVEAL_RECORDS_WINDOW_S,
  type ApiFailure,
  type RevealBudgetScope,
  type RevealBudgetView,
} from "@/api";

import type { RevealCost } from "./revealFields";

/** Which budget, in the words a 429 has to use. */
export const REVEAL_BUDGET_LABELS: Readonly<Record<RevealBudgetScope, string>> = {
  records: "records an hour",
  conversations: "conversations a day",
};

/** The unit each budget counts, singular. */
export const REVEAL_BUDGET_UNITS: Readonly<Record<RevealBudgetScope, string>> = {
  records: "record",
  conversations: "conversation",
};

/** The window each budget buckets on, in seconds. Fixed and epoch-aligned, not sliding. */
export const REVEAL_BUDGET_WINDOW_S: Readonly<Record<RevealBudgetScope, number>> = {
  records: REVEAL_RECORDS_WINDOW_S,
  conversations: REVEAL_CONVERSATIONS_WINDOW_S,
};

/** How the window reads in a sentence: "this hour", "today". */
export const REVEAL_BUDGET_WINDOW_LABELS: Readonly<Record<RevealBudgetScope, string>> = {
  records: "this hour",
  conversations: "today",
};

/** One counter's last known state. `remaining === null` means nobody has measured it. */
export interface CounterReading {
  readonly remaining: number | null;
  /** Epoch millis of the response that reported it. `null` when there was none. */
  readonly measuredAt: number | null;
}

export const UNMEASURED: CounterReading = { remaining: null, measuredAt: null };

/** Both counters, as last reported to THIS tab. */
export interface RevealBudgetSnapshot {
  readonly records: CounterReading;
  readonly conversations: CounterReading;
}

export const UNMEASURED_REVEAL_BUDGET: RevealBudgetSnapshot = {
  records: UNMEASURED,
  conversations: UNMEASURED,
};

/* -------------------------------------------------------------------------- */
/* Windows                                                                     */
/* -------------------------------------------------------------------------- */

/** The fixed-window index containing `nowMs`, exactly as `budget._window_index` computes it. */
export function windowIndex(nowMs: number, windowS: number): number {
  return Math.floor(Math.floor(nowMs / 1_000) / windowS);
}

/** Epoch millis at which the window containing `nowMs` rolls over. */
export function windowResetAt(nowMs: number, windowS: number): number {
  return (windowIndex(nowMs, windowS) + 1) * windowS * 1_000;
}

/** Seconds until that rollover — always `1 … windowS`, matching `budget._seconds_left`. */
export function secondsToReset(nowMs: number, windowS: number): number {
  return Math.ceil((windowResetAt(nowMs, windowS) - nowMs) / 1_000);
}

/**
 * Whether a reading taken at `measuredAt` still describes the window containing `nowMs`.
 *
 * A reading from the previous bucket is not a stale number to be shown with a caveat — it is
 * a number about a counter that has since been reset to zero, so it is discarded rather than
 * displayed. Showing "3 records left" from 10:59 at 11:01 would talk an operator out of work
 * they are entitled to do.
 */
export function isSameWindow(measuredAt: number, nowMs: number, windowS: number): boolean {
  return windowIndex(measuredAt, windowS) === windowIndex(nowMs, windowS);
}

/** A reading, dropped to `UNMEASURED` once its window has rolled. */
export function currentReading(
  reading: CounterReading,
  scope: RevealBudgetScope,
  nowMs: number,
): CounterReading {
  if (reading.measuredAt === null) return UNMEASURED;
  return isSameWindow(reading.measuredAt, nowMs, REVEAL_BUDGET_WINDOW_S[scope])
    ? reading
    : UNMEASURED;
}

/** Both counters, aged into the window containing `nowMs`. */
export function currentSnapshot(
  snapshot: RevealBudgetSnapshot,
  nowMs: number,
): RevealBudgetSnapshot {
  return {
    records: currentReading(snapshot.records, "records", nowMs),
    conversations: currentReading(snapshot.conversations, "conversations", nowMs),
  };
}

/* -------------------------------------------------------------------------- */
/* Learning from a response, and from a refusal                                */
/* -------------------------------------------------------------------------- */

/**
 * Fold a reveal's `budget` into what was already known.
 *
 * A counter the response did not touch (`null`) keeps its previous reading — aged, so a
 * reading from a rolled window is dropped rather than carried forward. This is what lets a
 * name reveal leave the day's conversation figure standing instead of blanking it.
 */
export function applyRevealBudget(
  previous: RevealBudgetSnapshot,
  budget: RevealBudgetView,
  nowMs: number,
): RevealBudgetSnapshot {
  const aged = currentSnapshot(previous, nowMs);
  return {
    records:
      budget.recordsRemaining === null
        ? aged.records
        : { remaining: budget.recordsRemaining, measuredAt: nowMs },
    conversations:
      budget.conversationsRemaining === null
        ? aged.conversations
        : { remaining: budget.conversationsRemaining, measuredAt: nowMs },
  };
}

/** `details.budget` on a 429 — which of the two ceilings refused. `null` when it is not one. */
export function budgetScopeOf(failure: ApiFailure): RevealBudgetScope | null {
  const scope = failure.details?.["budget"];
  if (scope === "records" || scope === "conversations") return scope;
  return null;
}

function detailInteger(failure: ApiFailure, key: string): number | null {
  const value = failure.details?.[key];
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

/**
 * What a `REVEAL_BUDGET_EXHAUSTED` refusal teaches about the two counters.
 *
 * `deps.enforce_reveal_budget` puts `recordsRemaining` and `conversationsRemaining` on the
 * 429 as well, computed with this request's own (released) charge added back, so a refusal is
 * as good a measurement as a success — and it is the only measurement an operator who is at
 * their ceiling will get.
 */
export function applyBudgetRefusal(
  previous: RevealBudgetSnapshot,
  failure: ApiFailure,
  nowMs: number,
): RevealBudgetSnapshot {
  return applyRevealBudget(
    previous,
    {
      recordsCharged: 0,
      recordsRemaining: detailInteger(failure, "recordsRemaining"),
      conversationsCharged: 0,
      conversationsRemaining: detailInteger(failure, "conversationsRemaining"),
    },
    nowMs,
  );
}

/** Everything a 429 has to be able to say: which budget, what is left, when it resets. */
export interface BudgetRefusal {
  readonly scope: RevealBudgetScope | null;
  readonly scopeLabel: string;
  readonly remaining: number | null;
  readonly requested: number | null;
  /** Seconds until the refusing window resets — the server's `Retry-After` when it sent one. */
  readonly resetsInS: number;
  /** Epoch millis of that reset, for a `<Timestamp>`. */
  readonly resetsAt: number;
}

/**
 * Read a 429 into something an operator can act on.
 *
 * `Retry-After` is authoritative and is preferred over the local arithmetic: the two agree
 * (both are seconds-to-reset of a fixed epoch-aligned window) but only one of them is the
 * server's clock. The fallback matters for the records budget on a response whose header was
 * stripped by a proxy — "your hourly budget is spent" with no reset time is the support
 * ticket §12.3 warns about.
 */
export function readBudgetRefusal(failure: ApiFailure, nowMs: number): BudgetRefusal {
  const scope = budgetScopeOf(failure);
  const windowS = scope === null ? REVEAL_RECORDS_WINDOW_S : REVEAL_BUDGET_WINDOW_S[scope];
  const resetsInS = failure.retryAfterS ?? secondsToReset(nowMs, windowS);
  return {
    scope,
    scopeLabel: scope === null ? "reveal budget" : REVEAL_BUDGET_LABELS[scope],
    remaining:
      scope === null
        ? null
        : detailInteger(failure, scope === "records" ? "recordsRemaining" : "conversationsRemaining"),
    requested: detailInteger(failure, "recordsRequested"),
    resetsInS,
    resetsAt: nowMs + resetsInS * 1_000,
  };
}

/* -------------------------------------------------------------------------- */
/* Bands — §11.3: colour is never the only channel                             */
/* -------------------------------------------------------------------------- */

/**
 * How a counter stands against what the pending reveal would cost.
 *
 * Five states rather than three, because two of them have different remedies:
 * `insufficient` means this particular reveal is too big for what is left (take a smaller
 * page, or wait), while `spent` means nothing at all fits until the window rolls. And
 * `unmeasured` is neither good nor bad — it is the honest answer before this tab has seen a
 * single budget figure, and it must not be painted like a healthy one.
 */
export type BudgetBand = "unmeasured" | "ample" | "tight" | "insufficient" | "spent";

/** Below this fraction of the ceiling, a counter is drawn as tight. */
export const TIGHT_FRACTION = 0.2;

export function budgetBand(
  reading: CounterReading,
  input: { readonly cost: number; readonly ceiling: number | null },
): BudgetBand {
  const { remaining } = reading;
  if (remaining === null) return "unmeasured";
  if (remaining <= 0) return "spent";
  if (input.cost > 0 && remaining < input.cost) return "insufficient";
  if (input.ceiling !== null && input.ceiling > 0 && remaining <= input.ceiling * TIGHT_FRACTION) {
    return "tight";
  }
  return "ample";
}

/**
 * §11.3: "status pills are never colour alone". Every band carries a glyph AND a word, so the
 * meter survives greyscale, a bad projector and the eight percent of operators who cannot
 * tell the amber from the green.
 */
export const BUDGET_BAND_GLYPH: Readonly<Record<BudgetBand, string>> = {
  unmeasured: "?",
  ample: "✓",
  tight: "▲",
  insufficient: "⊘",
  spent: "⊘",
};

export const BUDGET_BAND_LABEL: Readonly<Record<BudgetBand, string>> = {
  unmeasured: "not measured yet",
  ample: "within budget",
  tight: "running low",
  insufficient: "not enough left for this reveal",
  spent: "spent until the window resets",
};

export function budgetBandColorVar(band: BudgetBand): string {
  switch (band) {
    case "ample":
      return "var(--success)";
    case "tight":
      return "var(--caution)";
    case "insufficient":
    case "spent":
      return "var(--error)";
    case "unmeasured":
      return "var(--ink-muted)";
  }
}

/**
 * What is left after this reveal, if it is allowed. `null` whenever the answer would be a
 * guess — an unmeasured counter, or one this reveal does not touch.
 */
export function remainingAfter(reading: CounterReading, cost: number): number | null {
  if (reading.remaining === null || cost === 0) return null;
  return Math.max(0, reading.remaining - cost);
}

/** Whether a pending reveal is certain to be refused by what this tab last measured. */
export function willExceedBudget(
  snapshot: RevealBudgetSnapshot,
  cost: RevealCost,
  nowMs: number,
): boolean {
  const current = currentSnapshot(snapshot, nowMs);
  const overRecords =
    current.records.remaining !== null && cost.records > current.records.remaining;
  const overConversations =
    current.conversations.remaining !== null &&
    cost.conversations > current.conversations.remaining;
  return overRecords || overConversations;
}

/**
 * Our own words about our own clock: `in 43s`, `in 12 min`, `in 3 h 05 min`.
 *
 * Deliberately not `formatDurationS` from `@/lib` — that renders `2m 05s`, which is a
 * measured latency rather than a wait, and reads wrong under "resets".
 */
export function formatResetIn(seconds: number): string {
  if (seconds < 60) return `in ${String(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `in ${String(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `in ${String(hours)} h ${rest < 10 ? "0" : ""}${String(rest)} min`;
}
