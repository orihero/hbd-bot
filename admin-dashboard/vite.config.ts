import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

const srcDir = fileURLToPath(new URL("./src", import.meta.url));

/** Where the FastAPI admin process listens (`make admin`). */
export const DEV_API_TARGET = "http://127.0.0.1:8080";

/** Everything the API owns. Only these prefixes are proxied; the rest is the SPA. */
export const PROXIED_PREFIXES = ["/api", "/healthz", "/readyz"] as const;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": srcDir },
  },
  build: {
    outDir: "../src/bayram/admin/static",
    emptyOutDir: true,
    assetsDir: "assets",
    assetsInlineLimit: (filePath) => (filePath.endsWith(".woff2") ? false : undefined),
    target: "es2022",
    sourcemap: true,
  },
  server: {
    // 5174 so this can run beside admin-ui's 5173 without either stealing the other's port.
    port: 5174,
    strictPort: true,
    proxy: Object.fromEntries(
      PROXIED_PREFIXES.map((prefix) => [
        prefix,
        /*
         * `changeOrigin: false` is a SECURITY decision, not a default — the same one
         * admin-ui/vite.config.ts spells out at length. The admin API rejects any non-GET
         * whose `Origin` is not exactly `BAYRAM_ADMIN_PUBLIC_ORIGIN` (403 `ORIGIN_REJECTED`).
         * Rewriting `Origin` to the target would make every request sail through that
         * check, so the one control between a cross-site page and a state change would go
         * unexercised until production.
         *
         * Consequence: developing here needs `BAYRAM_ADMIN_PUBLIC_ORIGIN=http://localhost:5174`
         * in `.env.admin`. A 403 `ORIGIN_REJECTED` on sign-in is that variable, not this flag.
         */
        { target: DEV_API_TARGET, changeOrigin: false, secure: false },
      ]),
    ),
  },
});
