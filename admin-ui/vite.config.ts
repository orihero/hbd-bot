/**
 * Vite config — plan §11.1.
 *
 * Two decisions here are load-bearing and must not be "tidied".
 *
 * 1. `build.outDir = ../src/bayram/admin/static`. The wheel force-includes that directory via
 *    `[tool.hatch.build.targets.wheel] artifacts`; it is gitignored, because a committed
 *    bundle drifts from `admin-ui/` with nothing to notice. `emptyOutDir` is on so a
 *    renamed chunk from a previous build cannot be served alongside the current one.
 *
 * 2. `changeOrigin: false` on the dev proxy. This is a SECURITY decision, not a default.
 *    The admin API rejects any non-GET whose `Origin` header is not exactly
 *    `BAYRAM_ADMIN_PUBLIC_ORIGIN` (`ORIGIN_REJECTED`, 403). With `changeOrigin: true` the proxy
 *    would rewrite `Origin` to the target and every request would sail through the check —
 *    which means the one control standing between a cross-site page and a state change
 *    would be exercised by nobody until production. Forwarding the browser's real origin
 *    keeps the check live in dev.
 *
 *    Consequence, and it is deliberate: developing against a local API requires
 *    `BAYRAM_ADMIN_PUBLIC_ORIGIN=http://localhost:5173` in `.env.admin`. If sign-in returns
 *    403 `ORIGIN_REJECTED` in dev, that variable is the answer — do not flip this flag.
 *
 *    The session cookies are `__Host-` prefixed and therefore `Secure`. `http://localhost`
 *    is a "potentially trustworthy origin" in every current browser, so they are accepted
 *    over plain http there; on any other dev hostname they are not, and the panel will
 *    appear to log in and then 401.
 */

import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react-swc";
import { defineConfig, type Plugin } from "vite";

const srcDir = fileURLToPath(new URL("./src", import.meta.url));

/**
 * The body face, as `src/styles/fonts.css` names it before Vite hashes it.
 *
 * A build that renames or drops the file must fail here rather than ship a `<link>` to a
 * URL that 404s, so this is matched against the real bundle and the miss is fatal.
 */
const BODY_FONT = /(^|\/)mulish-latin-cyrillic-var[.-][A-Za-z0-9_-]+\.woff2$/;

/**
 * Preload the body face — the one thing `font-display: swap` cannot do for you.
 *
 * Without it the browser learns Mulish exists only after it has fetched the HTML, fetched
 * the stylesheet and parsed it: three serial round trips before the first byte of the font
 * is asked for, and until then every name on the page is drawn in the fallback and then
 * reflowed. The `<link>` cannot be written by hand into `index.html` because the filename
 * carries a content hash, and it cannot be dodged by serving the font from `public/`
 * either: the API mounts `StaticFiles` under `/assets/` ALONE and hands every other path
 * the SPA shell, so a font outside that prefix would be answered with HTML.
 *
 * `crossorigin` is mandatory even though the font is same-origin. Fonts are always fetched
 * in CORS mode; a preload without it is a *different* request from the one the stylesheet
 * makes, so the browser downloads the file twice and warns that the preload went unused.
 *
 * Build only. `vite dev` serves the font off the source path with no hashing, and there is
 * no bundle to look the name up in.
 */
function preloadBodyFont(): Plugin {
  return {
    name: "bayram-preload-body-font",
    apply: "build",
    enforce: "post",
    transformIndexHtml(_html, context) {
      const emitted = Object.keys(context.bundle ?? {}).find((name) => BODY_FONT.test(name));
      if (emitted === undefined) {
        throw new Error(
          "no emitted asset matched the body face. src/styles/fonts.css must @font-face " +
            "mulish-latin-cyrillic-var.woff2, or this preload — and the comment in " +
            "index.html that promises it — is a lie. See admin-ui/tools/build-fonts.py.",
        );
      }
      return [
        {
          tag: "link",
          attrs: {
            rel: "preload",
            as: "font",
            type: "font/woff2",
            href: `/${emitted}`,
            crossorigin: "anonymous",
          },
          injectTo: "head-prepend",
        },
      ];
    },
  };
}

/** Where the FastAPI process listens (`make admin`). */
export const DEV_API_TARGET = "http://127.0.0.1:8080";

/** Everything the API owns. Only these prefixes are proxied; the rest is the SPA. */
export const PROXIED_PREFIXES = ["/api", "/healthz", "/readyz"] as const;

export default defineConfig({
  plugins: [react(), preloadBodyFont()],
  resolve: {
    alias: { "@": srcDir },
  },
  build: {
    // Read by pyproject.toml's hatch `artifacts` entry. Changing one means changing both.
    outDir: "../src/bayram/admin/static",
    emptyOutDir: true,
    assetsDir: "assets",
    /*
     * THIS IS A CSP DECISION, NOT A PERFORMANCE ONE.
     *
     * Vite inlines any asset under 4 kB as a `data:` URI. `bayram-status-symbols.woff2` is
     * 2.2 kB, so by default it is base64'd straight into the stylesheet — and the policy is
     * `default-src 'self'` with no `font-src` of its own, which means `data:` is NOT an
     * allowed font source. (`img-src` names `data:` explicitly; nothing else does.) The
     * browser refuses the face, the §11.3 status glyphs fall through to whatever the host
     * has, and on a bare container they are tofu — with one console line to say so.
     *
     * Returning false keeps every font as a real file under `/assets/`, which the policy
     * allows, which the immutable cache prefix covers, and which `preloadBodyFont()` can
     * point a `<link>` at. Widening the CSP to `font-src 'self' data:` instead is the wrong
     * trade and §12.1 T7 forbids it.
     */
    assetsInlineLimit: (filePath) => (filePath.endsWith(".woff2") ? false : undefined),
    sourcemap: true,
    target: "es2022",
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      PROXIED_PREFIXES.map((prefix) => [
        prefix,
        { target: DEV_API_TARGET, changeOrigin: false, secure: false },
      ]),
    ),
  },
});
