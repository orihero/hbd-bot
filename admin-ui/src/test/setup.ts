/**
 * Test setup: jest-dom matchers, a clean DOM between tests, and the browser APIs jsdom does
 * not implement that this app depends on.
 *
 * `matchMedia` is stubbed because `initTheme()` reads `prefers-color-scheme`, and
 * `ResizeObserver` because Radix and Recharts both measure.
 *
 * `localStorage` is the third, and it is not obvious. jsdom would normally provide it, but
 * on Node 24+ the runtime defines its OWN `localStorage` global which is `undefined` unless
 * the process was started with `--localstorage-file`, and that shadows jsdom's. The symptom
 * is remote from the cause: `usePrefsStore` is wrapped in zustand's `persist`, so ANY write
 * to it — a density toggle, a theme change, `usePrefsStore.setState` in a test's cleanup —
 * throws `Cannot read properties of undefined (reading 'setItem')` from inside the
 * middleware, and because that throw usually lands in an `afterEach`, it takes
 * `cleanup()` down with it and every later test in the file fails on a DOM full of
 * leftovers. An in-memory implementation is enough: nothing here asserts on persistence
 * across a reload, and per-file isolation is what a test wants anyway.
 */

import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, vi } from "vitest";

/*
 * Installed at MODULE scope, not inside `beforeAll`. Setup files run before the test
 * modules are imported, but hooks run after — and zustand's `persist` resolves its
 * storage once, when the store module is first evaluated. A stub installed in a hook
 * arrives too late and the store keeps the `undefined` it captured at import.
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

beforeAll(() => {
  // Guarded on the TYPE, not on `"matchMedia" in window`: the property can be present and
  // `undefined`, in which case the `in` check passes, the stub is never installed, and
  // `applyTheme("system")` throws `window.matchMedia is not a function` from inside a store.
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

  if (!("ResizeObserver" in globalThis)) {
    Object.defineProperty(globalThis, "ResizeObserver", {
      writable: true,
      value: class {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    });
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // The client reads `document.cookie` for the CSRF token; a leftover from one test would
  // silently change another's request headers.
  for (const chunk of document.cookie.split("; ")) {
    const name = chunk.split("=")[0];
    if (name) document.cookie = `${name}=; Max-Age=0; path=/; Secure`;
  }
});
