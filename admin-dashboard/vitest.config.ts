/**
 * Vitest — the COMPONENT test runner, and nothing else.
 *
 * Kept out of `vite.config.ts` on purpose: `test.environment: "jsdom"` in the shared config
 * would pull jsdom into every `vite build` resolution graph, and the bundle that ships to
 * `src/hbd/admin/static` must not carry a test environment.
 *
 * It is also kept out of `npm test`. That script is the bespoke localization E2E suite
 * (`tests/run-all.ts`, tsx, its own harness and reporter) and it is not a Vitest suite — it
 * is not compatible with one and it is not being migrated. Component tests are
 * `npm run test:unit`. The `include` below is why the two can never collide: this runner
 * looks only inside `src/`, and the localization suite lives only inside `tests/`.
 */

import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    /*
     * An https origin, not jsdom's default `http://localhost`. The panel's session cookies
     * are `__Host-` prefixed and therefore `Secure`; jsdom's cookie jar enforces the prefix
     * rules, so over plain http a `document.cookie = "__Host-hbd_csrf=…"` is silently
     * DISCARDED — and a CSRF assertion written against that would pass vacuously, against a
     * header that was never sent.
     */
    environmentOptions: { jsdom: { url: "https://admin.test/" } },
    /*
     * No `globals: true`. `tsconfig.json` pins `types: ["vite/client"]`, so ambient
     * `describe`/`it`/`expect` would have to be added there for `npm run typecheck` to pass;
     * importing them from "vitest" costs one line per file and keeps the type surface honest.
     */
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
