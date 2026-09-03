/**
 * URL search params as the single source of truth for filter state — §11.1.
 *
 * "URL search params (zod-parsed) for all filter state so an operator can paste 'the failed
 * orders I'm looking at' into Slack." That sentence is the whole design: filter state lives
 * in the URL, not in a component's `useState`, so a link carries a screen and a refresh
 * loses nothing.
 *
 * Every read goes through `safeParse` with a fallback. A hand-edited or truncated URL must
 * degrade to the default view, never to a crash and never to a request the API will 422 —
 * an operator who mistypes a query string is not an incident.
 *
 * Repeated parameters are the OR spelling the API uses (`?state=failed&state=cancelled`), so
 * `zStringList` reads them with `getAll` and normalises a single occurrence to a one-element
 * array.
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";

/** What one parameter looks like after `URLSearchParams` has been flattened. */
export type SearchParamValue = string | string[];
export type SearchParamRecord = Record<string, SearchParamValue>;

/**
 * Flatten a `URLSearchParams` into something zod can parse.
 *
 * A key that appears once becomes a string; a key that appears more than once becomes an
 * array. Use `zStringList` (which accepts both) for anything that may repeat, so a
 * single-selection filter does not parse differently from a multi-selection one.
 */
export function searchParamsToRecord(params: URLSearchParams): SearchParamRecord {
  const record: SearchParamRecord = {};
  for (const key of new Set(params.keys())) {
    const all = params.getAll(key);
    const first = all[0];
    if (first === undefined) continue;
    record[key] = all.length === 1 ? first : all;
  }
  return record;
}

/**
 * The inverse. `undefined`, `null` and empty arrays are OMITTED — an empty parameter is not
 * the same as an absent one to this API, and `?state=` is a 422.
 */
export function recordToSearchParams(values: Readonly<Record<string, unknown>>): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) {
      for (const item of value as readonly unknown[]) {
        const rendered = renderParam(item);
        if (rendered !== null) params.append(key, rendered);
      }
      continue;
    }
    const rendered = renderParam(value);
    if (rendered !== null) params.set(key, rendered);
  }
  // Sorted so two links to the same view are the same string — which is what makes a pasted
  // URL comparable and a query key stable.
  params.sort();
  return params;
}

/**
 * A parameter value as text, or `null` for "do not write this one".
 *
 * Only primitives are rendered. An object or an array reaching here means a filter shape
 * changed without its codec changing, and `String({})` would silently write
 * `?filter=[object Object]` into the operator's URL — a link that looks fine, pastes fine,
 * and filters nothing.
 */
function renderParam(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "boolean") return String(value);
  return null;
}

/* -------------------------------------------------------------------------- */
/* Codecs                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * `?withTotal=true`. Accepts the spellings a human might type into the bar as well as the
 * one we emit; anything else is `undefined`, not `false`, because "absent" and "false" drive
 * different server defaults.
 */
export const zBoolParam = z
  .union([z.string(), z.boolean()])
  .optional()
  .transform((value): boolean | undefined => {
    if (value === undefined) return undefined;
    if (typeof value === "boolean") return value;
    if (value === "true" || value === "1" || value === "yes") return true;
    if (value === "false" || value === "0" || value === "no") return false;
    return undefined;
  });

/** An integer parameter — `?limit=50`, `?telegramUserId=770000123`. */
export function zIntParam(bounds?: { min?: number; max?: number }) {
  return z
    .union([z.string(), z.number()])
    .optional()
    .transform((value): number | undefined => {
      if (value === undefined) return undefined;
      const parsed = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) return undefined;
      if (bounds?.min !== undefined && parsed < bounds.min) return undefined;
      if (bounds?.max !== undefined && parsed > bounds.max) return undefined;
      return parsed;
    });
}

/**
 * A repeatable enum parameter. Unknown members are DROPPED rather than failing the parse: a
 * stale bookmark naming a state that no longer exists should show the rest of the filter,
 * not an error page.
 */
export function zEnumList<T extends readonly [string, ...string[]]>(values: T) {
  const member = z.enum(values);
  return z
    .union([z.string(), z.array(z.string())])
    .optional()
    .transform((value): T[number][] | undefined => {
      if (value === undefined) return undefined;
      const list = Array.isArray(value) ? value : [value];
      const kept = list.filter((item): item is T[number] => member.safeParse(item).success);
      return kept.length === 0 ? undefined : kept;
    });
}

/** A repeatable free-text parameter, normalised to an array. */
export const zStringList = z
  .union([z.string(), z.array(z.string())])
  .optional()
  .transform((value): string[] | undefined => {
    if (value === undefined) return undefined;
    const list = (Array.isArray(value) ? value : [value]).filter((item) => item !== "");
    return list.length === 0 ? undefined : list;
  });

/** A single free-text parameter; empty becomes absent. */
export const zStringParam = z
  .union([z.string(), z.array(z.string())])
  .optional()
  .transform((value): string | undefined => {
    const first = Array.isArray(value) ? value[0] : value;
    return first === undefined || first === "" ? undefined : first;
  });

/**
 * An RFC 3339 instant. Only accepted with an OFFSET — a naive timestamp is a 422 on every
 * endpoint that takes a window, and refusing it here means the operator sees an empty filter
 * chip rather than a red banner they cannot act on.
 */
export const zInstantParam = z
  .union([z.string(), z.array(z.string())])
  .optional()
  .transform((value): string | undefined => {
    const first = Array.isArray(value) ? value[0] : value;
    if (first === undefined || first === "") return undefined;
    if (!/(?:Z|[+-]\d{2}:?\d{2})$/.test(first)) return undefined;
    return Number.isNaN(Date.parse(first)) ? undefined : first;
  });

/* -------------------------------------------------------------------------- */
/* Parsing                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * A schema that turns raw search params into filter state.
 *
 * The third parameter is what matters. `z.ZodType<T>` defaults its INPUT to `T`, and every
 * codec above is a `.transform()` whose input is `string | string[] | undefined` — so
 * inference against `z.ZodType<T>` unified on the input side and handed each screen
 * `limit: string | number`. Five feature modules independently papered over that with
 * `as unknown as z.ZodType<Filters>`, which silenced the symptom and also switched off the
 * check that the codec's OUTPUT still matches the hand-written filter type.
 *
 * Declaring the input as `unknown` says the true thing: the parser accepts whatever came out
 * of the URL, and `T` is the parsed result. Every one of those casts is gone.
 */
export type SearchParamsSchema<T> = z.ZodType<T, z.ZodTypeDef, unknown>;

/**
 * Parse a `URLSearchParams` against a schema, falling back on failure.
 *
 * Deliberately `safeParse` with a fallback rather than a throw: this runs on every render of
 * every filtered screen, and a bad URL is an operator's typo, not a data-integrity bug. The
 * loud path is reserved for `SCHEMA_DRIFT` on a RESPONSE, where the server and the bundle
 * genuinely disagree.
 */
export function parseSearchParams<T>(
  schema: SearchParamsSchema<T>,
  params: URLSearchParams,
  fallback: T,
): T {
  const parsed = schema.safeParse(searchParamsToRecord(params));
  return parsed.success ? parsed.data : fallback;
}

/** The number of filters currently applied, for §11.4's "Empty-filtered" copy and the
 *  FilterBar's Clear affordance. `exclude` skips the keys that are paging, not filtering. */
export function activeFilterCount(
  values: Readonly<Record<string, unknown>>,
  exclude: readonly string[] = ["limit", "cursor", "withTotal"],
): number {
  return Object.entries(values).filter(([key, value]) => {
    if (exclude.includes(key)) return false;
    if (value === undefined || value === null || value === "") return false;
    return !(Array.isArray(value) && value.length === 0);
  }).length;
}

/* -------------------------------------------------------------------------- */
/* The hook                                                                    */
/* -------------------------------------------------------------------------- */

export interface SearchParamsState<T> {
  /** The parsed, validated filter state. Never `undefined`; falls back on a bad URL. */
  readonly value: T;
  /** Replace the whole filter state. Drops the cursor by default — see `setValue`. */
  readonly setValue: (next: T, options?: { keepCursor?: boolean }) => void;
  /** Patch one or more fields, keeping the rest. */
  readonly patch: (partial: Partial<T>, options?: { keepCursor?: boolean }) => void;
  /** Back to the fallback. §11.4's "Clear" on an Empty-filtered state. */
  readonly clear: () => void;
  /** How many filters are set, for the Empty-filtered copy. */
  readonly activeCount: number;
}

/**
 * Filter state, read from and written to the URL.
 *
 * `setValue` and `patch` DROP `cursor` unless told otherwise, and that is the important
 * behaviour: a keyset cursor encodes `(created_at, id)` from a previous page of a previous
 * filter. Carrying it across a filter change asks the API to continue a list that no longer
 * exists — at best the wrong page, at worst a 422. Changing a filter starts at page one.
 *
 * Writes use `replace` so a filter change does not fill the back button with every keystroke
 * of a search box.
 */
export function useSearchParamsState<T extends Record<string, unknown>>(
  schema: SearchParamsSchema<T>,
  fallback: T,
): SearchParamsState<T> {
  const [params, setParams] = useSearchParams();

  const value = useMemo(() => parseSearchParams(schema, params, fallback), [schema, params, fallback]);

  const setValue = useCallback(
    (next: T, options?: { keepCursor?: boolean }) => {
      const write: Record<string, unknown> = { ...next };
      if (options?.keepCursor !== true) delete write["cursor"];
      setParams(recordToSearchParams(write), { replace: true });
    },
    [setParams],
  );

  const patch = useCallback(
    (partial: Partial<T>, options?: { keepCursor?: boolean }) => {
      setValue({ ...value, ...partial }, options);
    },
    [setValue, value],
  );

  const clear = useCallback(() => {
    setParams(new URLSearchParams(), { replace: true });
  }, [setParams]);

  return {
    value,
    setValue,
    patch,
    clear,
    activeCount: activeFilterCount(value),
  };
}
