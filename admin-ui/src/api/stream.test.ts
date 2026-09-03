/**
 * The stream probe's contract.
 *
 * The point of these is that the probe distinguishes what an `<audio>` element cannot. A
 * media element reports 403, 404, 415 and 416 identically — one `error` event carrying
 * `MEDIA_ERR_SRC_NOT_SUPPORTED` — and a player built on that can only say "cannot play".
 * Every case below is one refusal the console can now name.
 */

import { describe, expect, it, vi } from "vitest";

import { probeAssetStream, totalFromContentRange } from "./stream";

const ASSET_ID = "a1b2c3d4-1111-2222-3333-444455556666";

function envelope(
  status: number,
  code: string,
  message: string,
  headers: Record<string, string> = {},
): Response {
  return new Response(
    JSON.stringify({ error: { code, message, correlationId: "corr-1" } }),
    { status, headers: { "content-type": "application/json", ...headers } },
  );
}

describe("probeAssetStream", () => {
  it("asks for ONE byte, same-origin, with no token in the URL", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response("x", {
          status: 206,
          headers: { "content-range": "bytes 0-0/4194304", "content-type": "audio/mpeg" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await probeAssetStream(ASSET_ID);

    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [url, init] = call;
    // §11.1: the `__Host-` cookie travels as a subresource. A signed URL or a `?token=`
    // here would undo the decision that lets the CSP be `default-src 'self'`.
    expect(url).toBe(`/api/assets/${ASSET_ID}/stream`);
    expect(url).not.toContain("?");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["Range"]).toBe("bytes=0-0");
  });

  it("reads a 206 as seekable and takes the object's length from Content-Range", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response("x", {
            status: 206,
            headers: { "content-range": "bytes 0-0/4194304", "content-type": "audio/mpeg" },
          }),
        ),
      ),
    );

    const result = await probeAssetStream(ASSET_ID);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.status).toBe(206);
    expect(result.data.isSeekable).toBe(true);
    // Never `assets.sizeBytes`, which is `DEFAULT 0` and has never been written.
    expect(result.data.totalBytes).toBe(4_194_304);
    expect(result.data.contentType).toBe("audio/mpeg");
  });

  it("reads a whole-object 200 as NOT seekable, which is a real difference", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(new Response("x", { status: 200, headers: { "content-type": "audio/ogg" } })),
      ),
    );

    const result = await probeAssetStream(ASSET_ID);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // A scrubber over this re-downloads the whole song on every drag. The player says so.
    expect(result.data.isSeekable).toBe(false);
    expect(result.data.totalBytes).toBeNull();
  });

  it("carries STEP_UP_REQUIRED through as itself, not as a generic 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(envelope(403, "STEP_UP_REQUIRED", "this action needs a fresh step-up")),
      ),
    );

    const result = await probeAssetStream(ASSET_ID);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    // The whole reason the probe exists: this one is a prompt and the other 403 is a wall.
    expect(result.code).toBe("STEP_UP_REQUIRED");
    expect(result.correlationId).toBe("corr-1");
  });

  it("keeps the 416's object length, which is what makes 'the object is empty' sayable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          envelope(416, "RANGE_NOT_SATISFIABLE", "that byte range is past the end of this object", {
            "content-range": "bytes */0",
          }),
        ),
      ),
    );

    const result = await probeAssetStream(ASSET_ID);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("RANGE_NOT_SATISFIABLE");
    expect(result.details?.["totalBytes"]).toBe(0);
  });

  it("keeps a 429's Retry-After, because 'wait' is only useful with a number", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          envelope(429, "REVEAL_BUDGET_EXHAUSTED", "the reveal budget is spent", {
            "retry-after": "312",
          }),
        ),
      ),
    );

    const result = await probeAssetStream(ASSET_ID);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("REVEAL_BUDGET_EXHAUSTED");
    expect(result.retryAfterS).toBe(312);
  });

  it("returns a failure rather than throwing when there is no network at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    const result = await probeAssetStream(ASSET_ID);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("NETWORK_ERROR");
    expect(result.status).toBe(0);
  });

  it("reports an abort as an abort, so the UI can say nothing about it", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new DOMException("aborted", "AbortError"))),
    );

    const result = await probeAssetStream(ASSET_ID, { signal: controller.signal });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("REQUEST_ABORTED");
  });
});

describe("totalFromContentRange", () => {
  it("reads the total off both forms the route sends", () => {
    expect(totalFromContentRange("bytes 0-0/4194304")).toBe(4_194_304);
    expect(totalFromContentRange("bytes */0")).toBe(0);
  });

  it("refuses to invent a length it cannot parse", () => {
    // A `*` total is a server declining to say. Reading it as anything else would put a
    // number under the scrubber that nobody measured.
    expect(totalFromContentRange("bytes 0-0/*")).toBeNull();
    expect(totalFromContentRange(null)).toBeNull();
    expect(totalFromContentRange("bytes 0-0")).toBeNull();
    expect(totalFromContentRange("bytes 0-0/nonsense")).toBeNull();
    expect(totalFromContentRange("bytes 0-0/-4")).toBeNull();
  });
});
