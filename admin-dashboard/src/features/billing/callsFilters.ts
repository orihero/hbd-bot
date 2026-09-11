/**
 * The inbound journal's URL state.
 *
 * Same three rules as `intentsFilters.ts` — an absent filter writes no parameter, an
 * unrecognised value degrades rather than 422s the page, and `cursor` is paging and never
 * counts as a filter — with one deliberate exception.
 *
 * **`method` is free text and is NOT validated against a closed list.** It is the one filter
 * value on this whole API that may be anything, and the reason is on the server:
 * `payme_rpc_log.method` records an UNKNOWN method on purpose, because a closed enum column
 * would have raised on the way in and lost exactly the row an incident needs. A console that
 * offered only the methods it knew about would be unable to find the one nobody expected.
 *
 * `ref` and `transactionId` ARE shape-checked here, because both are 24-character identifiers
 * the server refuses with a 422 naming the parameter — and a hand-edited link should degrade to
 * an unfiltered journal rather than to a red banner about a filter nobody chose.
 */

import type { CallFilters } from "@/api/billing";
import { PAYME_TRANSACTION_ID_PATTERN, PUBLIC_REF_PATTERN } from "@/api/constants";

export const CALL_PARAM = {
  method: "method",
  faultsOnly: "faultsOnly",
  ref: "ref",
  transactionId: "transactionId",
  from: "from",
  to: "to",
  cursor: "cursor",
} as const;

export interface CallUrlState {
  readonly method: readonly string[];
  readonly faultsOnly: boolean;
  readonly ref: string | null;
  readonly transactionId: string | null;
  readonly from: string | null;
  readonly to: string | null;
  readonly cursor: string | null;
}

export const EMPTY_CALL_STATE: CallUrlState = {
  method: [],
  faultsOnly: false,
  ref: null,
  transactionId: null,
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

/** Free text, de-duplicated and trimmed. Nothing is checked against a vocabulary — see above. */
function readMethods(params: URLSearchParams): readonly string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of params.getAll(CALL_PARAM.method)) {
    const value = raw.trim();
    if (value === "" || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

/** An identifier that fails its shape is dropped: the server would 422 and blank the page. */
function readShaped(params: URLSearchParams, name: string, pattern: RegExp): string | null {
  const value = readString(params, name);
  if (value === null) return null;
  return pattern.test(value) ? value : null;
}

export function readCallUrlState(params: URLSearchParams): CallUrlState {
  return {
    method: readMethods(params),
    // Only the literal `true` turns it on. `?faultsOnly=no` reading as `true` would show an
    // operator a filtered journal they did not ask for, which is how an outage gets invented.
    faultsOnly: readString(params, CALL_PARAM.faultsOnly) === "true",
    ref: readShaped(params, CALL_PARAM.ref, PUBLIC_REF_PATTERN),
    transactionId: readShaped(params, CALL_PARAM.transactionId, PAYME_TRANSACTION_ID_PATTERN),
    from: readString(params, CALL_PARAM.from),
    to: readString(params, CALL_PARAM.to),
    cursor: readString(params, CALL_PARAM.cursor),
  };
}

export function writeCallUrlState(state: CallUrlState): URLSearchParams {
  const params = new URLSearchParams();
  for (const value of state.method) params.append(CALL_PARAM.method, value);
  // Written only when on: the server's default is `false`, so `faultsOnly=false` would be a
  // second spelling of one request and therefore a second cache entry.
  if (state.faultsOnly) params.set(CALL_PARAM.faultsOnly, "true");
  if (state.ref !== null) params.set(CALL_PARAM.ref, state.ref);
  if (state.transactionId !== null) params.set(CALL_PARAM.transactionId, state.transactionId);
  if (state.from !== null) params.set(CALL_PARAM.from, state.from);
  if (state.to !== null) params.set(CALL_PARAM.to, state.to);
  if (state.cursor !== null) params.set(CALL_PARAM.cursor, state.cursor);
  return params;
}

export function activeCallFilterCount(state: CallUrlState): number {
  return (
    (state.method.length === 0 ? 0 : 1) +
    (state.faultsOnly ? 1 : 0) +
    (state.ref === null ? 0 : 1) +
    (state.transactionId === null ? 0 : 1) +
    (state.from === null ? 0 : 1) +
    (state.to === null ? 0 : 1)
  );
}

export function toCallQuery(state: CallUrlState): CallFilters {
  return {
    method: state.method,
    faultsOnly: state.faultsOnly,
    ref: state.ref,
    transactionId: state.transactionId,
    from: state.from,
    to: state.to,
  };
}
