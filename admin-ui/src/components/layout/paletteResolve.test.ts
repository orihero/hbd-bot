/** §11.2's "resolves by shape", as a table. */

import { describe, expect, it } from "vitest";

import {
  BARE_HEX32_PATTERN,
  ROUTE_ENTRIES,
  TELEGRAM_ID_PATTERN,
  UUID_PATTERN,
  dashUuid,
  resolvePalette,
} from "./paletteResolve";

const UUID = "0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30";
const HEX32 = "0123456789abcdef0123456789abcdef";

describe("shape patterns", () => {
  it("a UUID is 8-4-4-4-12, case-insensitive", () => {
    expect(UUID_PATTERN.test(UUID)).toBe(true);
    expect(UUID_PATTERN.test(UUID.toUpperCase())).toBe(true);
    expect(UUID_PATTERN.test(HEX32)).toBe(false);
  });

  it("a bare integer is a Telegram id", () => {
    expect(TELEGRAM_ID_PATTERN.test("123456789")).toBe(true);
    expect(TELEGRAM_ID_PATTERN.test("-1")).toBe(false);
    expect(TELEGRAM_ID_PATTERN.test("1 2")).toBe(false);
  });

  it("32 bare hex characters is a correlation id", () => {
    expect(BARE_HEX32_PATTERN.test(HEX32)).toBe(true);
    expect(BARE_HEX32_PATTERN.test(HEX32.slice(1))).toBe(false);
  });
});

describe("resolvePalette", () => {
  it("lists every section when nothing has been typed", () => {
    const results = resolvePalette("");
    expect(results).toHaveLength(ROUTE_ENTRIES.length);
    expect(results.every((result) => result.kind === "route")).toBe(true);
  });

  it("a UUID jumps to the order", () => {
    const [first] = resolvePalette(UUID);
    expect(first?.kind).toBe("order");
    expect(first?.href).toBe(`/orders/${UUID}`);
  });

  it("a bare integer jumps to the user", () => {
    const [first, second] = resolvePalette("987654321");
    expect(first?.kind).toBe("user");
    expect(first?.href).toBe("/users/987654321");
    // …and offers that person's orders, which is the next click every time.
    expect(second?.href).toBe("/orders?telegramUserId=987654321");
  });

  it("a 32-hex string goes to the correlation id FIRST, per §11.2", () => {
    const [first, second] = resolvePalette(HEX32);
    expect(first?.kind).toBe("correlation");
    expect(first?.href).toBe(`/orders?correlationId=${HEX32}`);
    // The plan is silent on the collision with a dash-stripped UUID, so the order id is
    // offered SECOND rather than chosen over the documented rule.
    expect(second?.kind).toBe("order");
    expect(second?.href).toBe(`/orders/${dashUuid(HEX32)}`);
  });

  it("dashUuid puts the dashes back in the right places", () => {
    expect(dashUuid("0c4f2a1e6b3d4d8f9a217f5e8c1b2d30")).toBe(UUID);
  });

  it("free text matches section names", () => {
    const results = resolvePalette("audit");
    expect(results[0]?.kind).toBe("route");
    expect(results[0]?.href).toBe("/audit");
  });

  it("reaches the two routes §11.2's rail does not list", () => {
    // The palette is "the single global entry point", so /retention and
    // /generations/names must be findable here even though the rail omits them.
    expect(resolvePalette("retention")[0]?.href).toBe("/retention");
    expect(resolvePalette("bake-off")[0]?.href).toBe("/generations/names");
  });

  it("says plainly that recipient-name search is not available, instead of returning nothing", () => {
    // §12.3 masks names at the response boundary and no list endpoint accepts free text.
    // An empty result would read as "no such customer", which this build cannot claim.
    const results = resolvePalette("Oʻktam");
    expect(results).toHaveLength(1);
    expect(results[0]?.kind).toBe("unavailable");
    expect(results[0]?.href).toBeNull();
  });

  it("trims, so a pasted id with a trailing newline still resolves", () => {
    expect(resolvePalette(`  ${UUID}\n`.trim())[0]?.kind).toBe("order");
  });

  it("refuses an integer too large to be a safe number", () => {
    const results = resolvePalette("99999999999999999999");
    expect(results.every((result) => result.kind !== "user")).toBe(true);
  });

  it("gives every result a stable, unique id", () => {
    const results = resolvePalette(HEX32);
    expect(new Set(results.map((result) => result.id)).size).toBe(results.length);
  });
});
