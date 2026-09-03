/**
 * The audio stream probe — the one request in this client whose body is not JSON.
 *
 * ## Why a probe exists at all
 *
 * `GET /api/assets/{id}/stream` is an `A+S` cell: `REVEAL_MEDIA_READ` at the router, a
 * step-up scoped to this asset id in the handler, one unit of the reveal budget, and an
 * audit row — all decided before a byte moves. Six different refusals can come back and
 * every one of them is a different sentence for the operator: 403 `STEP_UP_REQUIRED`
 * (confirm your password), 403 `FORBIDDEN` (your role has no cell), 404 (the row or the
 * object is gone), 415 (this asset is not an audio format this route serves), 416 (there is
 * no byte at that offset — the stored object is empty), 429 `REVEAL_BUDGET_EXHAUSTED`
 * (wait), 503 (the counter store is down).
 *
 * **An `<audio>` element can tell you none of that.** Its `error` event carries a
 * `MediaError` with four codes, and every HTTP failure collapses into
 * `MEDIA_ERR_SRC_NOT_SUPPORTED`. Handing the element a URL and rendering whatever it says
 * produces exactly the outcome §11.4 forbids everywhere else: a dead control with no
 * explanation. So the console asks the question in a form that can be answered — one
 * request, `Range: bytes=0-0` — reads the real status, and only then hands the URL to the
 * element.
 *
 * ## Why the probe is free
 *
 * §12.3's audio caveat: the route audits the FIRST request per `(actor, asset)` per
 * ten-minute window, not every range request, because an `<audio>` element issues many. The
 * probe is that first request. It opens the window, spends the one budget unit and writes
 * the one audit row; every range request the element then makes falls inside the same
 * window and costs nothing further. The UI must not try to compensate for that accounting
 * or to duplicate it — no second reveal call, no cache-buster on the element's URL (a fresh
 * query string is a fresh URL to the browser and the same `(actor, asset)` to the window,
 * so all it buys is a re-download).
 *
 * ## What the probe learns beyond the status
 *
 * A 206 means the server honoured a byte range, so the scrubber can seek and
 * `Content-Range` names the object's real length. A 200 means it did not, and a seek would
 * restart the download — the player says so and disables the scrubber rather than offering
 * a control that silently re-fetches a four-megabyte song on every drag.
 *
 * One byte is requested rather than the whole object, and the response body is cancelled
 * immediately: the point is the headers. Nothing here buffers audio, and nothing here
 * builds a blob — the element streams, which is what the route's range support is for.
 */

import { errorFailure, parseRetryAfter, transportFailure, type CallOptions } from "./client";
import { CORRELATION_HEADER, RETRY_AFTER_HEADER } from "./constants";
import { ENDPOINT, pathAssetStream } from "./endpoints";
import { ok, type ApiResult } from "./errors";

/** One byte. Enough to learn the status, the mime and whether ranges are honoured. */
const PROBE_RANGE = "bytes=0-0";

/** `Content-Range: bytes 0-0/123456` — the header a 206 and a 416 both carry. */
const CONTENT_RANGE_HEADER = "content-range";

export interface AssetStreamProbe {
  /** `206` when the range was honoured, `200` when the server sent the whole object. */
  readonly status: number;
  /**
   * Whether a seek is a real seek. `false` means the server answered the range probe with a
   * whole-object 200, so dragging the scrubber would re-download from zero.
   */
  readonly isSeekable: boolean;
  /**
   * The object's length in bytes, from `Content-Range`. `null` when the server did not say
   * — which it does not on a plain 200. Never taken from `assets.sizeBytes`, which is
   * `BigInteger NOT NULL DEFAULT 0` and has never been written by anything in this repo.
   */
  readonly totalBytes: number | null;
  /** The stored mime, verbatim. `audio/mpeg` or `audio/ogg`; anything else was a 415. */
  readonly contentType: string | null;
}

/**
 * Ask the stream route whether it will serve this asset, and learn why not when it will
 * not. Returns, never throws — the same contract as everything else in this directory.
 *
 * The failure arm is built by `client.ts`'s own `errorFailure`, so a refusal here carries
 * the identical `code` / `message` / `correlationId` / `retryAfterS` an ordinary JSON call
 * would produce. A second copy of that mapping living in a component is how two failure
 * taxonomies grow in one console.
 */
export async function probeAssetStream(
  assetId: string,
  options?: CallOptions,
): Promise<ApiResult<AssetStreamProbe>> {
  let response: Response;
  try {
    response = await fetch(pathAssetStream(assetId), {
      method: "GET",
      // `*/*`, not `application/json`: the happy path is audio bytes. The failure path is
      // still the JSON envelope, because `errors.py` renders it regardless of `Accept`.
      headers: { Accept: "*/*", Range: PROBE_RANGE },
      // The `__Host-` session cookie, same-origin, no token in the URL (§11.1).
      credentials: "include",
      redirect: "error",
      cache: "no-store",
      ...(options?.signal ? { signal: options.signal } : {}),
    });
  } catch (error: unknown) {
    return transportFailure(ENDPOINT.assetStream, error);
  }

  const totalBytes = totalFromContentRange(response.headers.get(CONTENT_RANGE_HEADER));

  if (!response.ok) {
    const refusal = await errorFailure(
      response,
      ENDPOINT.assetStream,
      response.headers.get(CORRELATION_HEADER),
      parseRetryAfter(response.headers.get(RETRY_AFTER_HEADER)),
    );
    // RFC 9110 §15.5.17: a 416 says how long the object actually is, and the route sends
    // `bytes */{total}`. Carrying it through is what lets the player say "the stored object
    // is empty" instead of "that range is past the end", which for a probe of byte zero is
    // the same fact told uselessly.
    return totalBytes === null
      ? refusal
      : { ...refusal, details: { ...(refusal.details ?? {}), totalBytes } };
  }

  // The headers were the point. Release the connection rather than letting a song trickle
  // into a body nobody reads.
  try {
    void response.body?.cancel();
  } catch {
    /* A body that is already closed, or a Response with none. Nothing to release. */
  }

  return ok({
    status: response.status,
    isSeekable: response.status === 206,
    totalBytes,
    contentType: response.headers.get("content-type"),
  });
}

/**
 * The total out of `bytes 0-0/123456` or `bytes *\/0`.
 *
 * `null` for an absent header, for the `*` form (a server that will not say), and for
 * anything that is not a non-negative integer. A length nobody can parse is not a length.
 */
export function totalFromContentRange(header: string | null): number | null {
  if (header === null) return null;
  const slash = header.lastIndexOf("/");
  if (slash < 0) return null;
  const tail = header.slice(slash + 1).trim();
  if (tail === "" || tail === "*") return null;
  const total = Number(tail);
  return Number.isInteger(total) && total >= 0 ? total : null;
}
