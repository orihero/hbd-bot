/**
 * `/orders/:orderId`'s view state, in the URL.
 *
 * Which tab is open is not a private component detail: "look at the attempts on this order"
 * is a thing one operator sends another, and it has to survive being pasted. Same rule as
 * the filters on `/orders` (§11.1) — the address bar is the store.
 *
 * There is ONE `cursor` and ONE `limit`, owned by whichever tab is open. Two independent
 * pagers would need two more parameters to express a state nobody can see, since only one
 * tab renders at a time; switching tabs drops the cursor, which is right — a cursor cut
 * against the attempts list means nothing to the assets list.
 */

import { z } from "zod";

import { MAX_PAGE_LIMIT, MIN_PAGE_LIMIT } from "@/api";
import { zIntParam, zStringParam, type SearchParamsSchema } from "@/lib";

export const DETAIL_TABS = ["timeline", "attempts", "assets"] as const;
export type DetailTab = (typeof DETAIL_TABS)[number];

function isDetailTab(value: string): value is DetailTab {
  return (DETAIL_TABS as readonly string[]).includes(value);
}

/** An unknown tab falls back to the default rather than failing the parse: a stale link
 *  naming a tab that no longer exists should open the order, not an error page. */
const zTabParam = z
  .union([z.string(), z.array(z.string())])
  .optional()
  .transform((value): DetailTab | undefined => {
    const first = Array.isArray(value) ? value[0] : value;
    if (first === undefined || first === "") return undefined;
    return isDetailTab(first) ? first : undefined;
  });

export const orderDetailParamsSchema = z.object({
  tab: zTabParam,
  cursor: zStringParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
});

export type OrderDetailParams = z.infer<typeof orderDetailParamsSchema>;

export const ORDER_DETAIL_FALLBACK: OrderDetailParams = {
  tab: undefined,
  cursor: undefined,
  limit: undefined,
};

/** See the note on `ordersFilterParser`. Annotated, not asserted. */
export const orderDetailParser: SearchParamsSchema<OrderDetailParams> = orderDetailParamsSchema;

/** The timeline is the default: "where is it" is answered by the merged event list, and the
 *  attempts and assets tabs are the follow-up questions. */
export const DEFAULT_TAB: DetailTab = "timeline";

export function activeTab(params: OrderDetailParams): DetailTab {
  return params.tab ?? DEFAULT_TAB;
}
