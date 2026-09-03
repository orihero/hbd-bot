/**
 * The client's four contracts, asserted rather than described.
 *
 * These are the behaviours every screen agent is about to rely on: it never throws, a bad
 * body is SCHEMA_DRIFT with a field path, an error envelope survives intact, and a non-GET
 * carries the CSRF token.
 */

import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from "./constants";
import { buildQueryString, postNoContent, request } from "./client";

const schema = z.object({ value: z.number().int() });

function jsonResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json", ...init.headers },
  });
}

describe("buildQueryString", () => {
  it("repeats a parameter for an array, which is how this API spells OR", () => {
    expect(buildQueryString({ state: ["failed", "cancelled"] })).toBe(
      "?state=failed&state=cancelled",
    );
  });

  it("omits null and undefined, because absent and empty are different to the API", () => {
    expect(buildQueryString({ cursor: undefined, limit: null, withTotal: false })).toBe(
      "?withTotal=false",
    );
  });
});

describe("request", () => {
  it("returns a failure instead of throwing when the network is gone", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    const result = await request({ endpoint: "GET /api/orders", path: "/api/orders", schema });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("NETWORK_ERROR");
    expect(result.status).toBe(0);
  });

  it("reports a wrongly-shaped 200 as SCHEMA_DRIFT naming the failing field path", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ value: "not-a-number" }))),
    );

    const result = await request({ endpoint: "GET /api/orders", path: "/api/orders", schema });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("SCHEMA_DRIFT");
    expect(result.issues?.[0]?.path).toBe("value");
    expect(result.message).toContain("GET /api/orders");
  });

  it("carries the server's own code, message and correlation id off an error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "FORBIDDEN",
                message: "your role has no cell for that",
                correlationId: "a".repeat(32),
                details: { permission: "admin.manage" },
              },
            },
            { status: 403, headers: { "X-Correlation-ID": "a".repeat(32) } },
          ),
        ),
      ),
    );

    const result = await request({ endpoint: "GET /api/admins", path: "/api/admins", schema });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("FORBIDDEN");
    expect(result.status).toBe(403);
    expect(result.correlationId).toBe("a".repeat(32));
    expect(result.details).toEqual({ permission: "admin.manage" });
  });

  it("echoes the CSRF cookie in the header on a non-GET, and never on a GET", async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=a-stored-token; path=/; Secure`;
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);

    await postNoContent("POST /api/auth/logout", "/api/auth/logout", {});
    await request({ endpoint: "GET /api/orders", path: "/api/orders", schema: undefined });

    const [, postInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [, getInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect((postInit.headers as Record<string, string>)[CSRF_HEADER_NAME]).toBe("a-stored-token");
    expect((getInit.headers as Record<string, string>)[CSRF_HEADER_NAME]).toBeUndefined();
    // Same origin, always: the `__Host-` cookies only travel with credentials included.
    expect(postInit.credentials).toBe("include");
  });
});
