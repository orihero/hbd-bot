/**
 * What the server half publishes, and the only channel between the two languages.
 *
 * `tests/e2e/serve_admin_e2e.py` writes `.manifest.json` before it opens the socket, so by
 * the time Playwright's `webServer` has seen `/healthz` the file is there. Everything the
 * browser side would otherwise hard-code lives in it: the origin, the credentials, the
 * seeded ids, the counts the seed implies — and `cspTemplate`, which is
 * `bayram.admin.middleware.security_headers.CSP_TEMPLATE` itself.
 *
 * That last one is the point. A gate that spelled the policy out in TypeScript would keep
 * passing after somebody widened `style-src` in Python; carrying the constant across means
 * the assertion is written against the middleware's own string, formatted with the nonce
 * this response actually carried.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export interface ManifestNames {
  /** `Gʻulom` — U+0047 U+02BB U+0075 U+006C U+006F U+006D. */
  readonly gulom: string;
  /** `Oʻktam` — U+004F U+02BB U+006B U+0074 U+0061 U+006D. */
  readonly oktam: string;
  /** `Дилноза` — Cyrillic, and the third string §14's font-coverage bullet names. */
  readonly dilnoza: string;
  /** `sanʼat` — U+02BC MODIFIER LETTER APOSTROPHE, a different codepoint from U+02BB. */
  readonly sanat: string;
  /** What §12.3 lets out of a read endpoint: first grapheme cluster + `•••`. */
  readonly maskedGulom: string;
  readonly maskedOktam: string;
}

export interface ManifestExpectations {
  readonly inFlight: number;
  readonly orders24h: number;
  readonly delivered24h: number;
  readonly failed24h: number;
  readonly paid24h: number;
  readonly terminal24h: number;
  readonly successRatePercent: number;
  readonly ordersTotal: number;
  readonly attentionRows: number;
  /** The `error_code` on the seeded failed generation attempt — rendered verbatim. */
  readonly failureCode: string;
  readonly failureRows: number;
}

export interface ManifestSeed {
  readonly deliveredOrderId: string;
  readonly failedOrderId: string;
  readonly purgedOrderId: string;
  /** `YYYY-MM-DD`, UTC — what `<PurgedValue>` must print after the lock. */
  readonly purgedDate: string;
  readonly telegramUserId: number;
  readonly telegramUserIdMasked: string;
}

export interface Manifest {
  readonly baseUrl: string;
  /** `security_headers.CSP_TEMPLATE`, verbatim, with its `{nonce}` placeholder intact. */
  readonly cspTemplate: string;
  readonly username: string;
  readonly bootstrapPassword: string;
  readonly rotatedPassword: string;
  readonly names: ManifestNames;
  readonly expected: ManifestExpectations;
  readonly seeded: ManifestSeed;
}

const MANIFEST_URL = new URL("./.manifest.json", import.meta.url);

export function readManifest(): Manifest {
  let raw: string;
  try {
    raw = readFileSync(fileURLToPath(MANIFEST_URL), "utf-8");
  } catch (error: unknown) {
    throw new Error(
      `No e2e manifest at ${fileURLToPath(MANIFEST_URL)}. It is written by ` +
        "`.venv/bin/python -m tests.e2e.serve_admin_e2e`, which Playwright starts as its " +
        `webServer — so this usually means the server failed to boot. Cause: ${String(error)}`,
    );
  }
  const parsed = JSON.parse(raw) as Manifest;
  if (typeof parsed.cspTemplate !== "string" || !parsed.cspTemplate.includes("{nonce}")) {
    throw new Error("the manifest carries no CSP template with a {nonce} placeholder");
  }
  return parsed;
}
