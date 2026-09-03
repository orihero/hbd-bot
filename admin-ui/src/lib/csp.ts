/**
 * The per-response CSP style nonce, read once at boot and handed to the one library that
 * needs it.
 *
 * ## What is actually broken without this
 *
 * The panel is served under `style-src 'self' 'nonce-<per-response>'` (§12.1 T7). Two very
 * different things get called "inline styles" and only one of them is policed:
 *
 * - **Style _attributes_** — React's `style={{}}`, and Radix/floating-ui writing
 *   `node.style.setProperty(...)` to position a popover — go through the CSSOM. CSP does
 *   not police the CSSOM. Every one of the SPA's `style={{}}` call sites is fine, and a
 *   dialog renders correctly positioned under the production policy. Do not "fix" them.
 * - **Style _elements_** — a real `<style>` node appended to `<head>` — are policed, and
 *   are blocked unless they carry the response's nonce.
 *
 * Exactly one library here injects a `<style>` element: `react-remove-scroll`, which every
 * Radix modal mounts (`Dialog`, `AlertDialog`, and `DropdownMenu`/`Popover`/`Select` in
 * their modal default). Its stylesheet is what implements the modal scroll lock —
 * `overflow: hidden` on `<body>` plus the scrollbar-gutter compensation that keeps the page
 * from jumping. Blocked, the dialog still opens and still looks right, and the page behind
 * it still scrolls: a silent failure whose only trace is a console violation.
 *
 * ## Why a module-level install and not a `nonce` prop
 *
 * Radix's `Content`/`Overlay` do accept a `nonce` prop, but only because they spread
 * `React.ComponentPropsWithoutRef<'div'>` — it lands as an attribute on a `<div>` and
 * reaches nothing. Radix renders `<RemoveScroll as={Slot} allowPinchZoom shards={...}>`
 * with no nonce forwarded, and `react-remove-scroll`'s props (`IRemoveScrollSelfProps`)
 * have no `nonce` member at all. Threading a prop through every call site would look like
 * the fix and change nothing.
 *
 * The seam the libraries actually read is `get-nonce`'s module-level `setNonce`, which
 * `react-style-singleton` consults in `makeStyleTag()` before appending. Installing it once
 * at boot covers every Radix primitive in the SPA — including ones nobody has added yet,
 * which a per-call-site prop could never do.
 *
 * ## The one exception, for whoever hits it next
 *
 * `@radix-ui/react-scroll-area` is the single primitive in the tree that renders a `<style>`
 * element from React rather than through `react-style-singleton`
 * (`ScrollAreaViewportStyle`), and it takes a real `nonce` prop that means something. It is
 * installed but imported nowhere today. If you mount one, pass it:
 *
 * ```tsx
 * import { getNonce } from "get-nonce";
 * <ScrollArea.Viewport nonce={getNonce()}>
 * ```
 *
 * `getNonce()` returns whatever `installCspNonce` published, so there is no second source of
 * truth. Every other Radix `nonce` prop is just `<div nonce>` spread from
 * `ComponentPropsWithoutRef<'div'>` and reaches nothing — do not add those.
 */

import { setNonce } from "get-nonce";

/** `hbd.admin.shell.CSP_NONCE_META_NAME`. */
export const CSP_NONCE_META_NAME = "csp-nonce";

/**
 * `hbd.admin.shell.CSP_NONCE_PLACEHOLDER`. Present verbatim under `vite dev`, where no
 * server substitutes it — and where there is no CSP either, so "no nonce" is correct.
 */
export const CSP_NONCE_PLACEHOLDER = "__HBD_CSP_NONCE__";

/**
 * This response's style nonce, or `null` when the document carries none.
 *
 * `null` covers three real cases and they are not distinguished on purpose, because the
 * answer is the same in all three: `vite dev` (placeholder unsubstituted), jsdom under
 * Vitest (no shell at all), and a bundle served by something that is not this API.
 */
export function readCspNonce(doc: Document = document): string | null {
  const meta = doc.querySelector(`meta[name="${CSP_NONCE_META_NAME}"]`);
  const value = meta?.getAttribute("content") ?? "";
  if (value === "" || value === CSP_NONCE_PLACEHOLDER) return null;
  return value;
}

/**
 * Publish the nonce to `get-nonce` so every runtime-injected `<style>` carries it.
 *
 * Called from `main.tsx` before `createRoot`. Ordering is not delicate — the injection
 * happens in an effect when the first modal mounts, long after boot — but "before React"
 * is the one place it cannot be forgotten by a future entry point.
 *
 * Returns what it installed, so the caller (and the tests) can assert on it.
 */
export function installCspNonce(doc: Document = document): string | null {
  const nonce = readCspNonce(doc);
  if (nonce !== null) {
    setNonce(nonce);
    return nonce;
  }
  if (import.meta.env.PROD) {
    // A production bundle with no nonce means the shell was served by something that did
    // not substitute the placeholder — a stale `src/hbd/admin/static/`, or a proxy serving
    // index.html itself. Every Radix modal's scroll lock is dead in that deployment, so it
    // is worth one loud line rather than a violation nobody correlates.
    console.error(
      `No <meta name="${CSP_NONCE_META_NAME}"> nonce in this document. The CSP will block ` +
        "every <style> element the console injects, and modal scroll locking will not " +
        "work. Rebuild and redeploy the bundle (`make ui-build`).",
    );
  }
  return null;
}
