/**
 * `/vendors`' URL codecs, pinned without a DOM.
 *
 * Both assertions here are about DEGRADING rather than failing. A pasted link is an
 * operator's artefact, not a contract: a naive timestamp and a vendor member this bundle has
 * never heard of are both things a URL can carry, and neither may produce a red banner or a
 * 422. What they must produce is the same screen with the bad half of the filter dropped —
 * which the filter chips then make visible, because the chip for the dropped bound is simply
 * not there.
 */

import { describe, expect, it } from "vitest";

import { parseSearchParams } from "@/lib";

import {
  VENDORS_FILTER_FALLBACK,
  toVendorUsageQuery,
  vendorsFilterSchema,
  type VendorFilters,
} from "./vendorsFilters";

function parse(search: string): VendorFilters {
  return parseSearchParams(
    vendorsFilterSchema,
    new URLSearchParams(search),
    VENDORS_FILTER_FALLBACK,
  );
}

describe("the window codec", () => {
  it("rejects a naive timestamp rather than sending a 422 the operator cannot act on", () => {
    // Arrange: an offset-less instant, which every windowed route in this API refuses.
    const search = "?from=2026-09-01T00:00:00&to=2026-09-07T00:00:00";

    // Act.
    const filters = parse(search);

    // Assert: the bound is dropped, not forwarded. An unfiltered screen beats a red banner.
    expect(filters.from).toBeUndefined();
    expect(filters.to).toBeUndefined();
  });

  it("keeps an instant that carries its offset, in either spelling", () => {
    // Arrange / Act: `Z` and an explicit offset are both RFC 3339.
    const filters = parse("?from=2026-09-01T00:00:00Z&to=2026-09-07T05:00:00%2B05:00");

    // Assert.
    expect(filters.from).toBe("2026-09-01T00:00:00Z");
    expect(filters.to).toBe("2026-09-07T05:00:00+05:00");
  });
});

describe("the vendor codec", () => {
  it("drops a member this bundle has never heard of rather than throwing", () => {
    // Arrange: a stale bookmark naming a vendor that has since been renamed.
    const search = "?vendor=elevenlabs&vendor=suno&vendor=openrouter";

    // Act.
    const filters = parse(search);

    // Assert: the two survivors filter; the unknown one is gone without an error page.
    expect(filters.vendor).toEqual(["elevenlabs", "openrouter"]);
  });

  it("treats an all-unknown list as NO filter, never as 'match none'", () => {
    // Arrange / Act: nothing in the list is a member of this build's vocabulary.
    const filters = parse("?vendor=suno&vendor=udio");

    // Assert: absent, so the parameter is never written — `?vendor=` is a 422, and a filter
    // that matches nothing would render an empty screen for a deployment full of rows.
    expect(filters.vendor).toBeUndefined();
    expect(toVendorUsageQuery(filters).vendor).toBeUndefined();
  });

  it("normalises a single occurrence to a one-element list", () => {
    expect(parse("?vendor=gemini").vendor).toEqual(["gemini"]);
  });
});

describe("the query builder", () => {
  it("omits `vendor` entirely when nothing is selected, so the key matches an untouched filter", () => {
    // Arrange / Act.
    const untouched = toVendorUsageQuery(VENDORS_FILTER_FALLBACK);
    const emptied = toVendorUsageQuery({ vendor: [] });

    // Assert: selecting a chip and deselecting it lands back on the same cache entry.
    expect("vendor" in untouched).toBe(false);
    expect("vendor" in emptied).toBe(false);
  });

  it("passes the window and the selected vendors through unchanged", () => {
    // Arrange.
    const filters: VendorFilters = {
      from: "2026-09-01T00:00:00Z",
      to: "2026-09-07T00:00:00Z",
      vendor: ["openrouter"],
    };

    // Act / Assert.
    expect(toVendorUsageQuery(filters)).toEqual({
      from: "2026-09-01T00:00:00Z",
      to: "2026-09-07T00:00:00Z",
      vendor: ["openrouter"],
    });
  });
});
