/**
 * The browser gate — §14 Slice 1d's last acceptance bullet.
 *
 * "Playwright smoke passes **with the production CSP applied**, including a correctly-
 * positioned Radix dialog." jsdom implements no Content-Security-Policy at all, so the
 * Vitest suite cannot stand in for that one: it renders the same components with the same
 * props and every `<style>` element the browser would refuse is silently accepted.
 *
 * The slice's font bullet — *"font-coverage snapshot renders `Oʻktam`, `Gʻulom`, `Дилноза`,
 * `sanʼat`"* — is the second line that needs a browser and for the same kind of reason:
 * jsdom has no rasteriser, so it cannot tell a glyph from a `.notdef` box. It lives in
 * `e2e/font-coverage.spec.ts`.
 *
 * Three decisions here are load-bearing.
 *
 * **The server is the real admin API.** `webServer` runs `tests/e2e/serve_admin_e2e.py`,
 * which builds `hbd.admin.app.create_app` over the same in-memory SQLite and dictionary
 * Redis the Python unit suite uses. So the CSP the browser enforces is the one
 * `SecurityHeadersMiddleware` wrote — nothing about the policy is restated on this side —
 * and the run needs no Postgres, no Redis, no network, no vendor key and no ffmpeg.
 *
 * **`retries: 0` and `workers: 1`.** A gate that passes on the second attempt is not a
 * gate; a CSP violation or a mispositioned dialog is deterministic, and a retry would turn
 * a real regression into a flake nobody looks at. One worker because the flow is one
 * operator's session against one seeded database.
 *
 * **The viewport is 1512×900.** That is the width the finding's baseline was measured at
 * (`x=452 w=608`, centred), and `top-[12vh]` and `w-[min(38rem,94vw)]` — the palette's own
 * classes — are both relative to it. The dialog test derives its expected geometry from
 * those two rules rather than pinning the pixels.
 *
 * `timezoneId: "UTC"` because `formatDate` renders UTC by default and the purge date the
 * smoke asserts is a fixed instant: a browser on Asia/Tashkent would read the same row as
 * the next day and fail for a reason that has nothing to do with the console.
 */

import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

/** Kept in step with `HOST`/`PORT` in `tests/e2e/serve_admin_e2e.py`. */
const PORT = Number(process.env.HBD_E2E_PORT ?? "8099");
const BASE_URL = `http://127.0.0.1:${PORT}`;

/** The repository root — `admin-ui/`'s parent. The harness is a `tests.e2e` module there. */
const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));

export const VIEWPORT = { width: 1512, height: 900 } as const;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    viewport: VIEWPORT,
    timezoneId: "UTC",
    locale: "en-US",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: VIEWPORT },
    },
  ],
  webServer: {
    command: `${process.env.HBD_PYTHON ?? ".venv/bin/python"} -m tests.e2e.serve_admin_e2e`,
    cwd: REPO_ROOT,
    url: `${BASE_URL}/healthz`,
    // Never reuse: a server left running from an earlier attempt holds an earlier seed,
    // and the counts this smoke asserts are the seed's.
    reuseExistingServer: false,
    timeout: 90_000,
    stdout: "pipe",
    stderr: "pipe",
    env: { HBD_E2E_PORT: String(PORT) },
  },
});
