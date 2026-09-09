/**
 * `/orders/:orderId`'s view state, in the URL.
 *
 * There is ONE `cursor` and ONE `limit`, and since the tabset was retired they belong to one
 * table: the attempt ledger. Same rule as the filters on `/orders` (§11.1) — the address bar
 * is the store, because "look at the attempts on this order" is a thing one operator sends
 * another and it has to survive being pasted.
 *
 * ## The tabs are gone, and `?tab=` is deliberately still harmless
 *
 * The screen used to hide three sections behind `timeline` / `attempts` / `assets`, with
 * `timeline` the default — so an operator opening an order saw no attempts, and none were
 * even fetched. The attempt ledger now renders on load beside the stepper and the
 * deliverables card, and the assets tab is retired outright: it duplicated the deliverables
 * card that was already hoisted above it.
 *
 * `tab` is therefore no longer a parameter. It is not rejected either — an old link carrying
 * `?tab=attempts` or `?tab=assets` parses to exactly the same state as one carrying nothing,
 * opens the order, and shows the very section it was pointing at, because every section is
 * now on the page. The stale key is dropped from the URL the first time anything patches it.
 */

import { z } from "zod";

import { MAX_PAGE_LIMIT, MIN_PAGE_LIMIT } from "@/api";
import { zIntParam, zStringParam, type SearchParamsSchema } from "@/lib";

/**
 * The vocabulary the `tab` parameter used to carry, kept as a written record of what old
 * links may still say. None of these values selects anything now; each one names a section
 * that renders unconditionally.
 */
export const RETIRED_TABS = ["timeline", "attempts", "assets"] as const;
export type RetiredTab = (typeof RETIRED_TABS)[number];

export const orderDetailParamsSchema = z.object({
  cursor: zStringParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
});

export type OrderDetailParams = z.infer<typeof orderDetailParamsSchema>;

export const ORDER_DETAIL_FALLBACK: OrderDetailParams = {
  cursor: undefined,
  limit: undefined,
};

/** See the note on `ordersFilterParser`. Annotated, not asserted. */
export const orderDetailParser: SearchParamsSchema<OrderDetailParams> = orderDetailParamsSchema;
