/**
 * `/assets` filter state — zod-parsed URL search params (§11.1).
 *
 * Kept out of the screen file so the codec can be tested without a DOM, and so the screen
 * file exports components only.
 *
 * The one filter worth a note is `expiringWithinDays`. It has **no lower bound**: a row
 * already past `expires_at` is inside the window, because it is the most urgent line on the
 * page — the sweep has not reached it yet and the bytes are still there. So "expiring within
 * 7 days" means "7 days or less remaining, including negative", and the screen says so
 * rather than letting an operator read it as "the next 7 days only".
 */

import { z } from "zod";

import {
  ASSET_KIND_VALUES,
  DEFAULT_PAGE_LIMIT,
  MAX_EXPIRING_WITHIN_DAYS,
  MAX_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  RETENTION_CLASS_VALUES,
  type AssetsQuery,
} from "@/api";
import type { FilterFieldDescriptor, FilterScalar } from "@/components/data";
import {
  zBoolParam,
  zEnumList,
  zInstantParam,
  zIntParam,
  zStringParam,
  type SearchParamsSchema,
} from "@/lib";

const assetsFilterCodec = z.object({
  kind: zEnumList(ASSET_KIND_VALUES),
  retentionClass: zEnumList(RETENTION_CLASS_VALUES),
  expiringWithinDays: zIntParam({ min: 1, max: MAX_EXPIRING_WITHIN_DAYS }),
  from: zInstantParam,
  to: zInstantParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
  cursor: zStringParam,
  withTotal: zBoolParam,
});

export type AssetsFilters = z.output<typeof assetsFilterCodec>;

/**
 * The codec, named by its OUTPUT type.
 *
 * This used to be an `as unknown as z.ZodType<AssetsFilters>` assertion, because
 * `useSearchParamsState` declared `z.ZodType<T>` — input and output pinned to the same `T` —
 * while every URL codec in `lib/searchParams.ts` takes `string | string[]` and returns a
 * parsed value. The hook now declares `SearchParamsSchema<T>`, whose input is `unknown`, so
 * the annotation is a real check rather than an assertion that switched one off.
 */
export const assetsFilterSchema: SearchParamsSchema<AssetsFilters> = assetsFilterCodec;

/**
 * The unfiltered view. Deliberately empty rather than pre-seeded with `expiringWithinDays`:
 * `useSearchParamsState` only falls back to this when the URL FAILS to parse, so a default
 * written here would never be applied to an empty URL and would silently disagree with the
 * chips. The expiring-soon view is one click from the dominant signal instead.
 */
export const ASSETS_FILTERS_EMPTY: AssetsFilters = {};

/** The days-remaining windows offered in the toolbar. `undefined` is "any". */
export const EXPIRY_WINDOW_CHOICES = [7, 30, 90, 365] as const;

/** Project the parsed URL onto the wire query. */
export function toAssetsQuery(filters: AssetsFilters): AssetsQuery {
  return {
    ...(filters.kind === undefined ? {} : { kind: filters.kind }),
    ...(filters.retentionClass === undefined ? {} : { retentionClass: filters.retentionClass }),
    ...(filters.expiringWithinDays === undefined
      ? {}
      : { expiringWithinDays: filters.expiringWithinDays }),
    ...(filters.from === undefined ? {} : { from: filters.from }),
    ...(filters.to === undefined ? {} : { to: filters.to }),
    ...(filters.cursor === undefined ? {} : { cursor: filters.cursor }),
    ...(filters.withTotal === undefined ? {} : { withTotal: filters.withTotal }),
    limit: filters.limit ?? DEFAULT_PAGE_LIMIT,
  };
}

/** What the chips call each filter. `from`/`to` are formatted by the caller, which owns
 *  the operator's UTC/local preference. */
export function assetsFilterFields(
  formatInstant: (value: FilterScalar) => string,
): readonly FilterFieldDescriptor<AssetsFilters>[] {
  return [
    { key: "kind", label: "kind" },
    { key: "retentionClass", label: "retention class" },
    {
      key: "expiringWithinDays",
      label: "expiring within",
      format: (value) => `${String(value)}d`,
    },
    { key: "from", label: "created after", format: formatInstant },
    { key: "to", label: "created before", format: formatInstant },
  ];
}
