/**
 * Component-test setup: jest-dom matchers, a clean DOM between tests, and the browser APIs
 * jsdom either does not implement or implements in a way this app trips over.
 *
 * Two of the four below are REPAIRS rather than stubs — jsdom is wrong, not absent — and both
 * were paid for once already in `admin-ui/src/test/setup.ts`. They are copied here with their
 * reasoning intact, because the symptom of losing either one is remote from its cause and the
 * next person to hit it would spend the same day on it.
 */

import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/*
 * REPAIR 1 — the top-layer pseudo-classes, answered directly instead of through the selector
 * engine.
 *
 * nwsapi (jsdom's selector engine) compiles `:modal` to its own `isModal`, which calls
 * `matchesNative(node, ":modal")`, which — because jsdom never installs nwsapi over
 * `Element.prototype.matches` — resolves to jsdom's `matches`, which is nwsapi again.
 * `isModal` also calls `isFullscreen`, which recurses the same way, so each level branches
 * twice and the whole thing only terminates when the call stack overflows into
 * `matchesNative`'s `try/catch`. It returns the right answer (`false`) and it does not hang,
 * which is exactly why it is hard to find: ONE `element.matches(":modal")` costs ~200ms and
 * millions of nested selector matches. A component that asks it per element per frame — any
 * floating-layer positioner, and `@testing-library/user-event`'s pointer-events walk over a
 * dialog subtree — turns that into a five-second timeout with no error to read.
 *
 * `false` is the honest answer, not a shortcut: jsdom implements no top layer, no fullscreen
 * and no picture-in-picture, so no element in a test can be in any of those states. The
 * delegation is deliberately narrow — an EXACT match against these three selectors and nothing
 * else — so compound selectors, other pseudo-classes, and every real query in the suite still
 * go to the selector engine unchanged.
 */
const TOP_LAYER_PSEUDOS: ReadonlySet<string> = new Set([
  ":modal",
  ":fullscreen",
  ":picture-in-picture",
]);

// Taken off the prototype through its DESCRIPTOR rather than as `Element.prototype.matches`,
// which `@typescript-eslint/unbound-method` rejects and is right to: a method read off a
// prototype and stored has lost its receiver. This one gets it back explicitly on every call
// below, and the descriptor spelling says that is deliberate instead of disabling the rule.
const engineMatches = Object.getOwnPropertyDescriptor(Element.prototype, "matches")?.value as (
  this: Element,
  selectors: string,
) => boolean;

Element.prototype.matches = function matches(this: Element, selectors: string): boolean {
  if (TOP_LAYER_PSEUDOS.has(selectors)) return false;
  return engineMatches.call(this, selectors);
};

/*
 * REPAIR 2 — web storage, installed at MODULE scope rather than in `beforeAll`.
 *
 * jsdom would normally provide `localStorage`, but on Node 24+ the runtime defines its OWN
 * `localStorage` global which is `undefined` unless the process was started with
 * `--localstorage-file`, and that can shadow jsdom's. This app reads it UNGUARDED in three
 * places — `src/state/theme.ts`, `src/state/auth.ts` and `src/app/NavRail.tsx` — so the
 * failure is a `Cannot read properties of undefined (reading 'getItem')` thrown from inside a
 * store during a render that has nothing to do with storage.
 *
 * Setup files run before the test modules are imported, but hooks run after — and a module
 * that resolves storage once at import time keeps whatever it captured. A stub installed in a
 * hook arrives too late. An in-memory implementation is enough: nothing here asserts on
 * persistence across a reload, and per-file isolation is what a test wants anyway.
 */
const storageHost = globalThis as Partial<typeof globalThis>;
if (storageHost.localStorage === undefined || storageHost.sessionStorage === undefined) {
  const memoryStorage = (): Storage => {
    const entries = new Map<string, string>();
    return {
      get length() {
        return entries.size;
      },
      key: (index: number) => [...entries.keys()][index] ?? null,
      getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => {
        entries.set(key, value);
      },
      removeItem: (key: string) => {
        entries.delete(key);
      },
      clear: () => {
        entries.clear();
      },
    };
  };
  for (const name of ["localStorage", "sessionStorage"] as const) {
    Object.defineProperty(globalThis, name, {
      writable: true,
      configurable: true,
      value: memoryStorage(),
    });
  }
}

/*
 * `matchMedia` is genuinely missing from jsdom, and `src/state/theme.ts` calls it on the
 * first render of the shell (`prefers-color-scheme`), as does `src/app/NavRail.tsx` for its
 * compact breakpoint. Guarded on the TYPE, not on `"matchMedia" in window`: the property can
 * be present and `undefined`, in which case an `in` check passes, the stub is never
 * installed, and the app throws `window.matchMedia is not a function` from inside a store.
 *
 * At MODULE scope for REPAIR 2's reason, and it was a `beforeAll` until a test file imported a
 * screen whose graph reaches `state/theme.ts`. That store calls `systemPrefersDark()` while
 * zustand's `create` is still evaluating — module initialisation, which happens when Vitest
 * COLLECTS the test file, and collection is finished long before any `beforeAll` registered
 * here gets to run. The symptom is a suite that fails with `window.matchMedia is not a
 * function` and zero tests collected, pointing at a store nobody in the test called.
 */
if (typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // `src/api/client.ts` reads `document.cookie` for the CSRF token; a leftover from one test
  // would silently change another's request headers.
  for (const chunk of document.cookie.split("; ")) {
    const name = chunk.split("=")[0];
    if (name) document.cookie = `${name}=; Max-Age=0; path=/; Secure`;
  }
});
