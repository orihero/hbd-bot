/**
 * `/vendors`' filter state: a window and a set of vendors, in the URL and nowhere else.
 *
 * §11.1's rule applies here as everywhere — filter state lives in the search params so a
 * spend question pastes into Slack as a link — but this screen has one property the list
 * screens do not, and it is what makes the URL load-bearing rather than convenient: THREE
 * queries read this object. The rollup, the daily series and the failure mix must all be
 * counted over the same window and the same vendors, or the table and the chart beside it
 * are two different claims wearing one heading. One parsed object, one query builder, three
 * calls.
 *
 * Both codecs degrade rather than fail, and both degradations are deliberate:
 *
 *  - `zInstantParam` refuses a NAIVE timestamp. `?from=2026-09-01T00:00:00` (no offset) is a
 *    422 on every windowed route in this API, and a 422 is a red banner an operator cannot
 *    act on. Dropping the bound instead shows the unfiltered screen, which is at least a
 *    screen — and the empty filter chip says the bound did not take.
 *  - `zEnumList` DROPS a vendor member this bundle has never heard of. A link from before a
 *    vendor was renamed should filter by the members it still recognises, not render an
 *    error page; and an empty result after the drop means no filter at all, never "match
 *    none", which is what `toVendorUsageQuery` then spells by omitting the parameter.
 *
 * DOM-free on purpose: everything here is a pure function over search params, so the rules
 * above are pinned by a unit test rather than by rendering a screen and reading its URL.
 */

import { z } from "zod";

import { VENDOR_VALUES, type Vendor, type VendorUsageQuery } from "@/api";
import { zEnumList, zInstantParam, type SearchParamsSchema } from "@/lib";

/**
 * The codecs' OUTPUT, hand-written rather than inferred.
 *
 * `useSearchParamsState` takes a `z.ZodType<T>` whose declared output is `T`, and every
 * codec above is a `.transform()` over `string | string[] | undefined`. Writing the parsed
 * shape out and checking it with `satisfies` is what keeps the schema and the type from
 * drifting apart — see the longer note in `features/users/UsersScreen.tsx`.
 */
export type VendorFilters = {
  from?: string | undefined;
  to?: string | undefined;
  vendor?: Vendor[] | undefined;
};

export const vendorsFilterSchema = z.object({
  from: zInstantParam,
  to: zInstantParam,
  vendor: zEnumList(VENDOR_VALUES),
}) satisfies SearchParamsSchema<VendorFilters>;

/** No window, no vendors: the whole record, every vendor. */
export const VENDORS_FILTER_FALLBACK: VendorFilters = {};

/**
 * The parsed filter as the three endpoints want it.
 *
 * Built in one place because it is also the QUERY KEY: three `useQuery` calls hash this
 * object, and a screen that spelled the query inline three times would key three caches on
 * three subtly different objects and refetch all of them on every render.
 *
 * An empty vendor list is passed through as `undefined` rather than `[]`. Both mean "no
 * filter" to `vendorParams`, but only one of them hashes the same as an untouched filter,
 * and an operator who selects a chip and deselects it should land back on the cache entry
 * they started from rather than on a second identical one.
 */
export function toVendorUsageQuery(filters: VendorFilters): VendorUsageQuery {
  const vendors = filters.vendor ?? [];
  return {
    from: filters.from,
    to: filters.to,
    ...(vendors.length === 0 ? {} : { vendor: vendors }),
  };
}
