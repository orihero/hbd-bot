/**
 * Vitest. Separate from vite.config.ts on purpose: the app build must not carry a test
 * environment, and `test.environment: "jsdom"` in the shared config would pull jsdom into
 * every `vite build` resolution graph.
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
    // An https origin, because the panel's cookies are `__Host-` prefixed and therefore
    // `Secure`: jsdom's cookie jar enforces the prefix rules, so over the default
    // http://localhost a `document.cookie = "__Host-bayram_csrf=…"` is silently DISCARDED and
    // every CSRF assertion passes vacuously against an absent header.
    environmentOptions: { jsdom: { url: "https://admin.test/" } },
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reportsDirectory: "./coverage",
      // The API layer and lib/ are the shared contract every other agent builds on; they
      // carry the gate. Screens and components are covered by their own agents' tests.
      include: ["src/api/**", "src/lib/**"],
      reporter: ["text", "html"],
    },
  },
});
