/**
 * The BUILT shell, checked against the policy the server will serve it under.
 *
 * WHY THIS IS NOT A PYTEST. `tests/test_admin/test_csp_shape.py` asserts every directive of
 * the Content-Security-Policy token by token and audits the shell for code that policy would
 * refuse — but it can only reach `admin-dashboard/index.html`, the SOURCE. The document that
 * actually ships is `src/bayram/admin/static/index.html`, which `.gitignore:63` excludes and
 * which nothing in the Python job ever produces. Everything Vite does to the head between
 * those two files — injecting the hashed module script and stylesheet, and whatever a plugin
 * added since — is invisible to that suite. This script is the only place it is visible, and
 * it can only run after `npm run build`.
 *
 * WHAT IT CANNOT SEE. No browser. This proves the emitted document asks for nothing the
 * policy forbids; it does not prove an engine parsed and ENFORCED the policy, and it cannot
 * see the opposite regression — a policy too strict, silently refusing something the app
 * needs at runtime. Only a browser collecting `securitypolicyviolation` events sees that.
 *
 * The policy it judges against is not read from a header — there is no server here. It is
 * `SOURCES` below, and the Python suite asserts every one of those source lists token by
 * token against a real response, so the two halves cannot drift apart without that suite
 * failing. The two halves also have to agree on WHICH elements the policy governs: the
 * refusals here and the refusals in `_refused_by` over there are written from one list, and
 * `selfTest()` at the bottom is what keeps this half honest about it.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

/**
 * The one thing this file needs out of `jsdom`, spelled out.
 *
 * `jsdom` ships no type declarations and `@types/jsdom` is not a dependency of this package,
 * so a bare `import { JSDOM } from "jsdom"` makes `JSDOM` an implicit `any` — which `tsc` and
 * `eslint` both accepted in silence for as long as this file was in neither's scope, and both
 * refuse now that it is in tsconfig.node.json and eslint.config.js. `createRequire` keeps the
 * runtime load exactly as it was while giving the binding a type written here rather than
 * inferred from nothing.
 */
interface JsdomConstructor {
  new (html: string): { readonly window: { readonly document: Document } };
}

const { JSDOM } = createRequire(import.meta.url)("jsdom") as { JSDOM: JsdomConstructor };

/** `build.outDir` from vite.config.ts, resolved from this file rather than from the cwd. */
const BUILT_SHELL = fileURLToPath(
  new URL("../../src/bayram/admin/static/index.html", import.meta.url),
);

/** `CSP_NONCE_PLACEHOLDER` in src/bayram/admin/shell.py. Spelled here for the third time. */
const NONCE_PLACEHOLDER = "__BAYRAM_CSP_NONCE__";

/** `CSP_NONCE_META_NAME` in src/bayram/admin/shell.py. */
const NONCE_META_NAME = "csp-nonce";

/** A URL naming a scheme, or protocol-relative. `'self'` refuses every one of them. */
const OFF_ORIGIN = /^(?:[A-Za-z][A-Za-z0-9+.-]*:|\/\/)/;

/** Named separately so `effectiveSources` can hand it back without an undefined branch. */
const DEFAULT_SRC: readonly string[] = ["'self'"];

/**
 * `CSP_TEMPLATE` in src/bayram/admin/middleware/security_headers.py, minus the directives no
 * element in a document can trip (`object-src`, `frame-ancestors`, `form-action`,
 * `worker-src`). `style-src`'s second source is the per-response nonce, which authorises an
 * inline element and never a host — so for the purpose of judging a URL it is `'self'` alone.
 */
const SOURCES: Readonly<Record<string, readonly string[]>> = {
  "default-src": DEFAULT_SRC,
  "script-src": ["'self'"],
  "style-src": ["'self'"],
  "img-src": ["'self'", "data:"],
  "media-src": ["'self'"],
  "connect-src": ["'self'"],
  "base-uri": ["'none'"],
};

/**
 * A fetch directive that is absent falls back to `default-src`: this policy names no
 * `frame-src` and no `font-src`, so `'self'` governs an `<iframe>` and a preloaded font all
 * the same. `base-uri` is NOT a fetch directive and has no fallback — which is exactly why
 * the policy spells it `'none'` instead of leaving it out.
 */
const FALLS_BACK_TO_DEFAULT = new Set([
  "script-src",
  "style-src",
  "img-src",
  "media-src",
  "font-src",
  "connect-src",
  "frame-src",
]);

/** `rel="preload"` names the directive that governs its fetch in the `as` attribute. */
const PRELOAD_AS_DIRECTIVE: Readonly<Record<string, string>> = {
  script: "script-src",
  style: "style-src",
  image: "img-src",
  font: "font-src",
  audio: "media-src",
  video: "media-src",
  track: "media-src",
  fetch: "connect-src",
};

/**
 * The `type` values that make a `<script>` executable, and therefore something `script-src`
 * has an opinion about. Every OTHER value makes the element a *data block*: the browser parses
 * it, hands the text to whatever reads it, and never runs it. `<script type="application/json">`
 * is markup, not code — a Vite plugin emitting a config block was failing this gate with no
 * way to be permitted and no security reason for the failure. `importmap` and
 * `speculationrules` are in the set on purpose: not JavaScript, but the browser acts on them
 * and `script-src` does police them.
 *
 * Kept identical to `_EXECUTABLE_SCRIPT_TYPES` in tests/test_admin/test_csp_shape.py.
 */
const EXECUTABLE_SCRIPT_TYPES = new Set([
  "",
  "module",
  "importmap",
  "speculationrules",
  // The JavaScript MIME types, from the HTML Standard's "JavaScript MIME type essence match".
  // Spelled out rather than pattern-matched: `text/json-script` contains "script" and is a
  // data block, and `application/javascript+xml` is not on the list.
  "application/ecmascript",
  "application/javascript",
  "application/x-ecmascript",
  "application/x-javascript",
  "text/ecmascript",
  "text/javascript",
  "text/javascript1.0",
  "text/javascript1.1",
  "text/javascript1.2",
  "text/javascript1.3",
  "text/javascript1.4",
  "text/javascript1.5",
  "text/jscript",
  "text/livescript",
  "text/x-ecmascript",
  "text/x-javascript",
]);

/** Does `script-src` police this `<script>`, or is it a data block the browser never runs? */
function scriptIsExecutable(script: Element): boolean {
  // A MIME type may carry parameters: `text/javascript; charset=utf-8` is still JavaScript.
  const declared = (script.getAttribute("type") ?? "").trim().toLowerCase();
  const essence = (declared.split(";")[0] ?? "").trim();
  return EXECUTABLE_SCRIPT_TYPES.has(essence);
}

/** `[directive actually applied, its sources]`, or null where the policy is silent. */
function effectiveSources(name: string): [string, readonly string[]] | null {
  const own = SOURCES[name];
  if (own !== undefined) return [name, own];
  // The name comes back with the sources because the two differ for the case that matters:
  // there is no `frame-src`, so a message naming one would send its reader looking for a
  // directive the header does not carry.
  if (FALLS_BACK_TO_DEFAULT.has(name)) return ["default-src", DEFAULT_SRC];
  return null;
}

/**
 * Would `sources` allow a subresource at `url`?
 *
 * Only the two answers a document can settle on its own: a RELATIVE URL is same-origin and
 * `'self'` covers it, and an ABSOLUTE one is allowed only where the policy lists its scheme as
 * a bare scheme source — `img-src`'s `data:` being the single instance. Host sources, ports
 * and paths are out of scope because this policy carries none of them, and the Python suite's
 * directive-equality assertions are what keep it that way.
 */
function permits(sources: readonly string[], url: string): boolean {
  if (sources.includes("'none'")) return false;
  // Not a fetch at all: an about:blank frame inherits the embedder's own policy.
  if (url.trim().toLowerCase() === "about:blank") return true;
  if (!OFF_ORIGIN.test(url)) return sources.includes("'self'");
  // Protocol-relative: a different host, reached over this document's scheme.
  if (url.startsWith("//")) return false;
  return sources.includes(`${(url.split(":", 1)[0] ?? "").toLowerCase()}:`);
}

/** The one refusal with no console script error behind it. */
const ALSO: Readonly<Record<string, string>> = {
  "base-uri":
    " — and this refusal is SILENT in the browser: the element is dropped, every relative " +
    "URL in the shell then resolves against the document's own path, and the panel loads " +
    "blank with nothing in the console to explain it",
};

function refusalsIn(document: Document): string[] {
  const refused: string[] = [];

  /** Judge one URL an element handed the browser. */
  const judge = (description: string, directive: string, url: string): void => {
    const applicable = effectiveSources(directive);
    if (applicable === null) return;
    const [applied, sources] = applicable;
    if (permits(sources, url)) return;
    const through = applied === directive ? "" : `, which ${directive} falls back to`;
    refused.push(
      `${description} is refused by ${applied} (${sources.join(" ")}${through})${ALSO[directive] ?? ""}`,
    );
  };

  for (const element of document.querySelectorAll("*")) {
    for (const attribute of element.attributes) {
      // `script-src` carries no `'unsafe-inline'`, so an event handler attribute is markup
      // the browser parses and then declines to run.
      if (attribute.name.toLowerCase().startsWith("on")) {
        refused.push(`<${element.tagName.toLowerCase()}> carries ${attribute.name}=`);
      }
      if (attribute.value.trim().toLowerCase().startsWith("javascript:")) {
        refused.push(
          `<${element.tagName.toLowerCase()}> has ${attribute.name}="javascript:…"`,
        );
      }
    }
  }

  for (const script of document.querySelectorAll("script")) {
    // A `<script>` the browser will not execute is a data block, whatever it contains —
    // including its `src`, which a data block does not even fetch.
    if (!scriptIsExecutable(script)) continue;
    const src = script.getAttribute("src");
    if (src === null) {
      // The one Vite is most likely to add. `script-src` is `'self'` with NO nonce, so this
      // is not a weakened policy — it is a script that runs nowhere, and the only symptom is
      // a console violation in production.
      refused.push(`an inline <script> (${script.textContent?.trim().slice(0, 60) ?? ""}…)`);
    } else if (OFF_ORIGIN.test(src)) {
      refused.push(`<script src="${src}"> is off-origin and script-src is 'self'`);
    }
  }

  for (const style of document.querySelectorAll("style")) {
    // An inline stylesheet the build emitted can only ever be nonce'd with the placeholder,
    // because the real nonce does not exist until the response is generated.
    if (style.getAttribute("nonce") !== NONCE_PLACEHOLDER) {
      refused.push(
        `an inline <style> with nonce="${style.getAttribute("nonce") ?? ""}" — style-src ` +
          `permits only 'self' and the per-response nonce`,
      );
    }
  }

  for (const sheet of document.querySelectorAll('link[rel~="stylesheet"]')) {
    const href = sheet.getAttribute("href") ?? "";
    if (OFF_ORIGIN.test(href)) {
      refused.push(`<link rel=stylesheet href="${href}"> is off-origin and style-src is 'self'`);
    }
  }

  // An ES module fetched ahead of use. `script-src` governs a modulepreload exactly as it
  // governs the `<script type="module">` that will import it — which is how an off-origin
  // chunk gets in past a check that only reads `<script>` elements.
  for (const link of document.querySelectorAll('link[rel~="modulepreload"]')) {
    judge(`<link rel=modulepreload href="${link.getAttribute("href") ?? ""}">`, "script-src",
      link.getAttribute("href") ?? "");
  }
  for (const link of document.querySelectorAll('link[rel~="preload"]')) {
    if (link.matches('[rel~="stylesheet"], [rel~="modulepreload"]')) continue;
    const directive = PRELOAD_AS_DIRECTIVE[(link.getAttribute("as") ?? "").trim().toLowerCase()];
    if (directive === undefined) continue;
    const href = link.getAttribute("href") ?? "";
    judge(`<link rel=preload as="${link.getAttribute("as") ?? ""}" href="${href}">`, directive, href);
  }

  // `img-src` is the one directive here carrying a bare scheme, so "has a scheme" is not the
  // whole answer: `data:` is permitted and every other absolute URL is not.
  for (const img of document.querySelectorAll("img")) {
    const src = img.getAttribute("src");
    if (src !== null) judge(`<img src="${src}">`, "img-src", src);
  }

  // No `frame-src` in this policy, so `default-src 'self'` decides. A checker that read only
  // the directives the policy NAMES would find nothing to consult here.
  for (const frame of document.querySelectorAll("iframe, frame")) {
    const src = frame.getAttribute("src");
    if (src !== null) {
      judge(`<${frame.tagName.toLowerCase()} src="${src}">`, "frame-src", src);
    }
  }

  // `base-uri 'none'` refuses EVERY `<base href>`, same-origin included — there is no
  // off-origin test to apply, which is why this one cannot ride on OFF_ORIGIN.
  for (const base of document.querySelectorAll("base[href]")) {
    const href = base.getAttribute("href") ?? "";
    judge(`<base href="${href}">`, "base-uri", href);
  }

  return refused;
}

/**
 * The gate, run against markup whose verdict is already known.
 *
 * A checker that returns `[]` for every input passes the real check against any document at
 * all. This repository has shipped exactly that once — an i18n check that matched the
 * substring `t(` and so passed on any file containing `useEffect` — and the risk is sharpest
 * right where this file learned to permit something: teaching it that
 * `<script type="application/json">` is data is one typo away from teaching it that every
 * inline script is. The Python half has these as parametrized tests; this half has no test
 * runner, so it proves itself on every run before it judges the build.
 */
function selfTest(): void {
  const mustRefuse = [
    "<script>alert(1)</script>",
    '<script type="text/javascript">alert(1)</script>',
    '<script type="TEXT/JavaScript; charset=utf-8">alert(1)</script>',
    '<script type="module">import "./x.js"</script>',
    '<script type="">alert(1)</script>',
    '<script type="importmap">{"imports":{}}</script>',
    '<script src="https://cdn.evil.example/x.js"></script>',
    '<script src="//cdn.evil.example/x.js"></script>',
    "<style>body{margin:0}</style>",
    '<body onload="boot()"></body>',
    '<a href="javascript:boot()">go</a>',
    '<link rel="stylesheet" href="https://fonts.googleapis.com/x.css">',
    '<img src="https://cdn.evil.example/pixel.png">',
    '<img src="//cdn.evil.example/pixel.png">',
    '<iframe src="https://evil.example/embed"></iframe>',
    '<base href="https://evil.example/">',
    '<base href="/panel/">',
    '<link rel="modulepreload" href="https://cdn.evil.example/chunk.js">',
    '<link rel="preload" as="script" href="https://cdn.evil.example/chunk.js">',
    '<link rel="preload" as="font" href="https://fonts.gstatic.com/x.woff2">',
  ];
  const mustPermit = [
    '<script type="application/json">{"api":"/api"}</script>',
    '<script type="application/ld+json">{"@context":"https://schema.org"}</script>',
    '<script type="text/template"><div></div></script>',
    '<script src="/assets/index-CjYrft9g.js"></script>',
    '<link rel="stylesheet" href="/assets/index-CjYrft9g.css">',
    `<style nonce="${NONCE_PLACEHOLDER}">body{margin:0}</style>`,
    '<img src="data:image/svg+xml;base64,PHN2Zy8+">',
    '<img src="/assets/logo-BQ2f9x.png">',
    "<iframe></iframe>",
    '<iframe src="about:blank"></iframe>',
    '<base target="_blank">',
    '<link rel="modulepreload" crossorigin href="/assets/vendor-D1x8sq.js">',
    '<link rel="preload" as="font" crossorigin href="/assets/inter-a91.woff2">',
  ];

  const broken: string[] = [];
  for (const markup of mustRefuse) {
    if (refusalsIn(new JSDOM(markup).window.document).length === 0) {
      broken.push(`should have been REFUSED and was not: ${markup}`);
    }
  }
  for (const markup of mustPermit) {
    const found = refusalsIn(new JSDOM(markup).window.document);
    if (found.length > 0) {
      broken.push(`should have been PERMITTED and was not: ${markup} -> ${found.join("; ")}`);
    }
  }
  if (broken.length > 0) {
    console.error("\n\x1b[31m✖ This gate does not agree with itself — it proved nothing:\x1b[0m");
    for (const line of broken) console.error(`    - ${line}`);
    process.exit(1);
  }
}

function main(): void {
  selfTest();

  let html: string;
  try {
    html = readFileSync(BUILT_SHELL, "utf8");
  } catch {
    // Never a skip. A missing build output means this gate proved nothing, and a gate that
    // reports green on silence is the failure mode this repository has already shipped once.
    console.error(`\x1b[31m✖ ${BUILT_SHELL} is missing — run \`npm run build\` first.\x1b[0m`);
    process.exit(1);
  }

  const { window } = new JSDOM(html);
  const { document } = window;
  const failures: string[] = [];

  // The placeholder has to survive the build, or the server substitutes nothing, logs one
  // WARNING and serves a shell whose nonce is dead. The Python suite asserts it is in the
  // SOURCE; only this can assert Vite did not rewrite the head out from under it.
  const meta = document.querySelector(`meta[name="${NONCE_META_NAME}"]`);
  if (meta?.getAttribute("content") !== NONCE_PLACEHOLDER) {
    failures.push(
      `the built shell's <meta name="${NONCE_META_NAME}"> carries ` +
        `"${meta?.getAttribute("content") ?? "<no such element>"}", not ${NONCE_PLACEHOLDER}`,
    );
  }

  failures.push(...refusalsIn(document));

  if (failures.length > 0) {
    console.error("\n\x1b[31m✖ The built SPA shell does not satisfy the panel's CSP:\x1b[0m");
    for (const failure of failures) console.error(`    - ${failure}`);
    console.error(
      "\n  script-src is 'self' with no nonce (src/bayram/admin/shell.py explains why it " +
        "stays\n  that way). Adding one to the policy to make the above work weakens the " +
        "panel's\n  strongest directive; the fix is to stop emitting it.\n",
    );
    process.exit(1);
  }

  console.log(
    `\x1b[32m✔ The built SPA shell carries no inline script, no inline style, no <base>, and\n` +
      `  no off-origin script, stylesheet, preload, image or frame; the style-nonce\n` +
      `  placeholder survived the build.\x1b[0m`,
  );
  process.exit(0);
}

main();
