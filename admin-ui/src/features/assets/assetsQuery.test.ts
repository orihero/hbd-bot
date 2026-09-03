/**
 * The `/assets` URL codec.
 *
 * A hand-edited URL is an operator's typo, not an incident: an unknown `kind` drops out of
 * the filter and the rest of the view survives, which is the behaviour `zEnumList` promises
 * and the reason the screen never renders a red banner for a bad query string.
 */

import { describe, expect, it } from "vitest";

import { DEFAULT_PAGE_LIMIT, MAX_EXPIRING_WITHIN_DAYS } from "@/api";
import { parseSearchParams } from "@/lib";

import { ASSETS_FILTERS_EMPTY, assetsFilterSchema, toAssetsQuery } from "./assetsQuery";

const parse = (search: string) =>
  parseSearchParams(assetsFilterSchema, new URLSearchParams(search), ASSETS_FILTERS_EMPTY);

describe("the assets filter codec", () => {
  it("reads a repeated parameter as the OR the API spells that way", () => {
    expect(parse("kind=song&kind=greeting").kind).toEqual(["song", "greeting"]);
  });

  it("drops an unknown enum member instead of failing the whole parse", () => {
    expect(parse("kind=song&kind=hologram").kind).toEqual(["song"]);
  });

  it("refuses an expiry window outside 1…365", () => {
    expect(parse(`expiringWithinDays=${String(MAX_EXPIRING_WITHIN_DAYS + 1)}`).expiringWithinDays)
      .toBeUndefined();
    expect(parse("expiringWithinDays=7").expiringWithinDays).toBe(7);
  });

  it("refuses a naive instant, because the endpoint 422s on one", () => {
    expect(parse("from=2026-09-01T00:00:00").from).toBeUndefined();
    expect(parse("from=2026-09-01T00:00:00Z").from).toBe("2026-09-01T00:00:00Z");
  });
});

describe("toAssetsQuery", () => {
  it("defaults the page size and sends nothing else", () => {
    expect(toAssetsQuery({})).toEqual({ limit: DEFAULT_PAGE_LIMIT });
  });

  it("passes the expiry window through untouched", () => {
    expect(toAssetsQuery({ expiringWithinDays: 7, kind: ["song"] })).toEqual({
      expiringWithinDays: 7,
      kind: ["song"],
      limit: DEFAULT_PAGE_LIMIT,
    });
  });
});
