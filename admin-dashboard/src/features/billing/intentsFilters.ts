/**
 * The payments list's URL state: read it, write it, count it, and turn it into a request.
 *
 * **The URL is the store.** A filtered payments page is a thing an operator pastes into a
 * ticket, and a filter held in component state would make that link a lie. So every narrowing
 * lives in the query string and nothing else does — which also means the Back button walks the
 * questions asked rather than the pages visited.
 *
 * Three rules govern the codec and each has a failure it prevents.
 *
 * **An absent filter writes NO parameter.** `?state=` is not "no state filter": it is an empty
 * string, which FastAPI reads as a value and refuses. The absent/present distinction is what
 * selects the handler's default, and `api/pagination.ts` enforces the same rule on the way out.
 *
 * **An unknown enum member is DROPPED, not passed through.** `state`, `product`, `settledBy`
 * and `attention` are typed enums server-side, so one hand-edited character in a pasted link
 * would 422 the whole request and blank the table. Dropping degrades to a wider view, which is
 * legible; a 422 is a red banner about a filter nobody chose.
 *
 * **`cursor` is not a filter and never counts as one.** Counting it would make page two of an
 * unfiltered list report "1 filter", and the empty state would then offer to clear a filter
 * that does not exist.
 *
 * `staleAfterHours` is carried but is only meaningful — and is only SENT — alongside
 * `attention=awaiting_stale`, because that is the one population whose predicate takes it. The
 * board's chip puts it in the link so a count and the list behind it are computed against one
 * cutoff; the codec's job is to not lose it in between.
 */

import {
  ATTENTION_POPULATION_VALUES,
  INTENT_PRODUCT_VALUES,
  INTENT_STATE_VALUES,
  SETTLE_SOURCE_VALUES,
  type AttentionPopulation,
  type IntentFilters,
  type IntentProduct,
  type IntentState,
  type SettleSource,
} from "@/api/billing";
import {
  DEFAULT_STALE_AFTER_HOURS,
  MAX_STALE_AFTER_HOURS,
  MIN_STALE_AFTER_HOURS,
} from "@/api/constants";

/** The query-string names. One place, so a chip's id and the parameter cannot drift apart. */
export const INTENT_PARAM = {
  state: "state",
  product: "product",
  settledBy: "settledBy",
  attention: "attention",
  sandbox: "sandbox",
  staleAfterHours: "staleAfterHours",
  from: "from",
  to: "to",
  cursor: "cursor",
} as const;

export interface IntentUrlState {
  readonly state: readonly IntentState[];
  readonly product: readonly IntentProduct[];
  readonly settledBy: SettleSource | null;
  readonly attention: AttentionPopulation | null;
  /** Tri-state. `false` is a real filter — production rows only — and is not "unset". */
  readonly sandbox: boolean | null;
  readonly staleAfterHours: number | null;
  readonly from: string | null;
  readonly to: string | null;
  /** Paging, not a filter. */
  readonly cursor: string | null;
}

export const EMPTY_INTENT_STATE: IntentUrlState = {
  state: [],
  product: [],
  settledBy: null,
  attention: null,
  sandbox: null,
  staleAfterHours: null,
  from: null,
  to: null,
  cursor: null,
};

function readString(params: URLSearchParams, name: string): string | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/** Members we recognise, de-duplicated, in the order they appear. Unknown values are dropped. */
function readEnums<T extends string>(
  params: URLSearchParams,
  name: string,
  values: readonly T[],
): readonly T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of params.getAll(name)) {
    const member = values.find((value) => value === raw);
    if (member === undefined || seen.has(member)) continue;
    seen.add(member);
    out.push(member);
  }
  return out;
}

/**
 * A tri-state boolean. `"true"`/`"false"` are filters; anything else is no filter at all.
 *
 * Deliberately not `Boolean(raw)`: that reads `?sandbox=no` as `true`, which would show a
 * certification week to somebody who asked to see production.
 */
function readTriBool(params: URLSearchParams, name: string): boolean | null {
  const raw = readString(params, name);
  if (raw === "true") return true;
  if (raw === "false") return false;
  return null;
}

/**
 * The staleness cutoff, refused rather than clamped when out of range.
 *
 * The server refuses it too, with a 422 naming the parameter — and the duplication is the
 * point: a clamped value answers a DIFFERENT question with no way for anybody to notice, so an
 * unreadable or out-of-range value here falls back to `null`, which means "do not send it" and
 * lets the server apply its own documented default.
 */
function readStaleHours(params: URLSearchParams): number | null {
  const raw = readString(params, INTENT_PARAM.staleAfterHours);
  if (raw === null) return null;
  const hours = Number(raw);
  if (!Number.isInteger(hours)) return null;
  if (hours < MIN_STALE_AFTER_HOURS || hours > MAX_STALE_AFTER_HOURS) return null;
  return hours;
}

export function readIntentUrlState(params: URLSearchParams): IntentUrlState {
  return {
    state: readEnums(params, INTENT_PARAM.state, INTENT_STATE_VALUES),
    product: readEnums(params, INTENT_PARAM.product, INTENT_PRODUCT_VALUES),
    settledBy: readEnums(params, INTENT_PARAM.settledBy, SETTLE_SOURCE_VALUES)[0] ?? null,
    attention:
      readEnums(params, INTENT_PARAM.attention, ATTENTION_POPULATION_VALUES)[0] ?? null,
    sandbox: readTriBool(params, INTENT_PARAM.sandbox),
    staleAfterHours: readStaleHours(params),
    from: readString(params, INTENT_PARAM.from),
    to: readString(params, INTENT_PARAM.to),
    cursor: readString(params, INTENT_PARAM.cursor),
  };
}

/** An absent filter writes no parameter — see the module header. */
export function writeIntentUrlState(state: IntentUrlState): URLSearchParams {
  const params = new URLSearchParams();
  for (const value of state.state) params.append(INTENT_PARAM.state, value);
  for (const value of state.product) params.append(INTENT_PARAM.product, value);
  if (state.settledBy !== null) params.set(INTENT_PARAM.settledBy, state.settledBy);
  if (state.attention !== null) params.set(INTENT_PARAM.attention, state.attention);
  if (state.sandbox !== null) params.set(INTENT_PARAM.sandbox, String(state.sandbox));
  // Only alongside the population it qualifies: a parameter the server ignores is one a
  // reader will eventually believe changed something.
  if (state.attention === "awaiting_stale" && state.staleAfterHours !== null) {
    params.set(INTENT_PARAM.staleAfterHours, String(state.staleAfterHours));
  }
  if (state.from !== null) params.set(INTENT_PARAM.from, state.from);
  if (state.to !== null) params.set(INTENT_PARAM.to, state.to);
  if (state.cursor !== null) params.set(INTENT_PARAM.cursor, state.cursor);
  return params;
}

/** Paging is excluded: counting it misreports an unfiltered page two as filtered. */
export function activeIntentFilterCount(state: IntentUrlState): number {
  return (
    (state.state.length === 0 ? 0 : 1) +
    (state.product.length === 0 ? 0 : 1) +
    (state.settledBy === null ? 0 : 1) +
    (state.attention === null ? 0 : 1) +
    (state.sandbox === null ? 0 : 1) +
    (state.from === null ? 0 : 1) +
    (state.to === null ? 0 : 1)
  );
}

/**
 * The URL state as a request.
 *
 * `staleAfterHours` is defaulted HERE rather than left null when the population needs it, so
 * the value in the key is the value the server will use — otherwise a chip carrying the
 * default explicitly and a bare `?attention=awaiting_stale` would be two cache entries for one
 * question, and the second would silently ask about a different cutoff if the server's default
 * ever moved.
 */
export function toIntentQuery(state: IntentUrlState): IntentFilters {
  return {
    state: state.state,
    product: state.product,
    settledBy: state.settledBy,
    attention: state.attention,
    sandbox: state.sandbox,
    staleAfterHours:
      state.attention === "awaiting_stale"
        ? (state.staleAfterHours ?? DEFAULT_STALE_AFTER_HOURS)
        : null,
    from: state.from,
    to: state.to,
  };
}
