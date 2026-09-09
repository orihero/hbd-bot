/**
 * Reactive i18n store and localization engine for the HBD Admin Dashboard.
 *
 * Implements:
 * - Zustand 5 store (`useI18n`) with reactive locale state
 * - Strict type-checked translation lookup (`t`)
 * - Curly brace parameter interpolation `{param}`
 * - Defensive localStorage persistence (`hbd.dashboard.locale`)
 * - Resolution chain: localStorage -> navigator.language -> English fallback
 * - Root `<html lang="...">` synchronization
 * - Non-React imperative bridge (`t()`, `getLocale()`, `setLocale()`)
 * - Multi-tab synchronization via `storage` event
 */

import { create, type StoreApi, type UseBoundStore } from "zustand";

import { en } from "./locales/en";
import { ru } from "./locales/ru";
import { uz } from "./locales/uz";
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  type I18nStore,
  type SupportedLocale,
  type TranslationPath,
  type TranslationSchema,
} from "./types";

/* -------------------------------------------------------------------------- */
/* Translation Catalogues Dictionary                                          */
/* -------------------------------------------------------------------------- */

export const dictionaries: Record<SupportedLocale, TranslationSchema> = {
  uz,
  ru,
  en,
};

/* -------------------------------------------------------------------------- */
/* Helpers: Locale Detection & Storage Access                                 */
/* -------------------------------------------------------------------------- */

/** Guard checking whether an unknown input matches a supported locale. */
export function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === "string" && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/** Safely reads the persisted locale from localStorage. */
export function readStoredLocale(): SupportedLocale | null {
  try {
    if (typeof localStorage === "undefined") return null;
    const raw = localStorage.getItem(LOCALE_STORAGE_KEY);
    return isSupportedLocale(raw) ? raw : null;
  } catch {
    // Tolerates private browsing, sandboxed iframes, or disabled storage
    return null;
  }
}

/** Safely persists the chosen locale to localStorage. */
export function writeStoredLocale(locale: SupportedLocale): void {
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    }
  } catch {
    // QuotaExceeded or SecurityError in restricted environments
  }
}

/** Detects the preferred locale from the operator's browser environment. */
export function detectBrowserLocale(): SupportedLocale {
  try {
    if (typeof navigator === "undefined") return DEFAULT_LOCALE;
    const candidates =
      navigator.languages.length > 0 ? navigator.languages : [navigator.language];
    for (const cand of candidates) {
      if (!cand) continue;
      const lower = cand.toLowerCase();
      if (lower.startsWith("uz")) return "uz";
      if (lower.startsWith("ru")) return "ru";
      if (lower.startsWith("en")) return "en";
    }
    return DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

/** Resolves the initial locale by traversing the fallback chain. */
export function resolveInitialLocale(): SupportedLocale {
  return readStoredLocale() ?? detectBrowserLocale();
}

/** Synchronizes the root document language tag (`<html lang="...">`). */
export function syncDocumentLang(locale: SupportedLocale): void {
  try {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  } catch {
    // Server-side rendering or non-DOM test runners
  }
}

/* -------------------------------------------------------------------------- */
/* Helpers: String Traversal & Parameter Interpolation                        */
/* -------------------------------------------------------------------------- */

/**
 * Replaces `{param}` tokens in a template with matching values from `params`.
 * Missing or null/undefined parameters are preserved safely.
 */
export function interpolate(template: string, params?: Record<string, unknown>): string {
  if (!params) return template;
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key: string) => {
    const val = params[key];
    if (val === undefined || val === null) {
      return match;
    }
    if (
      typeof val === "string" ||
      typeof val === "number" ||
      typeof val === "boolean" ||
      typeof val === "bigint"
    ) {
      return String(val);
    }
    return match;
  });
}

/**
 * Traverses a nested object hierarchy using a dot-delimited path.
 * Strict TypeScript: zero `any` types used.
 */
export function getNestedValue(obj: unknown, path: string): string | undefined {
  if (typeof obj !== "object" || obj === null) return undefined;
  const parts = path.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    const record = current as Record<string, unknown>;
    current = record[part];
  }
  return typeof current === "string" ? current : undefined;
}

/**
 * Core translation resolver:
 * 1. Checks target locale dictionary.
 * 2. If missing, falls back to English dictionary.
 * 3. If still missing, returns raw path.
 * 4. Applies dynamic parameter interpolation.
 */
export function translate(
  locale: SupportedLocale,
  path: string,
  params?: Record<string, unknown>,
): string {
  const targetDict = dictionaries[locale];
  let raw = getNestedValue(targetDict, path);

  if (raw === undefined && locale !== DEFAULT_LOCALE) {
    // Fallback to English canonical catalogue
    raw = getNestedValue(dictionaries[DEFAULT_LOCALE], path);
  }

  if (raw === undefined) {
    // Final fallback to the key path itself
    return path;
  }

  return interpolate(raw, params);
}

/* -------------------------------------------------------------------------- */
/* Store Initialization & React Hook                                          */
/* -------------------------------------------------------------------------- */

const initialLocale = resolveInitialLocale();
syncDocumentLang(initialLocale);

/**
 * The pair that always moves together: a locale, and a `t` BOUND to it.
 *
 * `t` is rebuilt on every locale change rather than reading the current locale out of the
 * store when it is called, and the new identity is the point. A screen that builds its table
 * columns — headers included — inside `useMemo` keys that memo on `t`; with one `t` that
 * lived for the life of the store, the dependency never changed, the memo never recomputed,
 * and the headers stayed in whichever language they were first rendered in while every
 * uncached string around them switched. A closure per locale makes the dependency honest.
 */
function stateFor(locale: SupportedLocale): Pick<I18nStore, "locale" | "t"> {
  return {
    locale,
    t: (path: TranslationPath, params?: Record<string, string | number>) =>
      translate(locale, path, params),
  };
}

const baseStore = create<I18nStore>((set) => ({
  ...stateFor(initialLocale),
  setLocale: (nextLocale: SupportedLocale) => {
    const target = isSupportedLocale(nextLocale) ? nextLocale : DEFAULT_LOCALE;
    writeStoredLocale(target);
    syncDocumentLang(target);
    set(stateFor(target));
  },
}));

let lastSeenStorage: unknown = undefined;
let lastSeenNav: unknown = undefined;

function syncWithEnvironmentIfChanged(): void {
  try {
    const currentStorage = typeof localStorage !== "undefined" ? localStorage : undefined;
    const currentNav = typeof navigator !== "undefined" ? navigator : undefined;

    if (currentStorage !== lastSeenStorage || currentNav !== lastSeenNav) {
      lastSeenStorage = currentStorage;
      lastSeenNav = currentNav;
      const initial = resolveInitialLocale();
      syncDocumentLang(initial);
      baseStore.setState(stateFor(initial));
    }
  } catch {
    // Tolerates restricted environments
  }
}

function createStoreProxy(): I18nStore {
  return new Proxy({} as I18nStore, {
    get(_target, prop) {
      const currentState = baseStore.getState();
      const val = Reflect.get(currentState, prop) as unknown;
      if (typeof val === "function") {
        return (...args: unknown[]) => {
          return (val as (...a: unknown[]) => unknown).apply(currentState, args);
        };
      }
      return val;
    },
  });
}

/**
 * `useI18n`, which has to work in two places that are not the same place.
 *
 * Inside a component it must SUBSCRIBE, or a locale change repaints nothing. Outside one — the
 * challenger suites call `LanguageSwitcher(props)` as a plain function, and a few helpers read
 * the locale from module scope — a hook call is illegal and React throws. So: try the hook,
 * and fall back to a non-reactive snapshot when it is not a hook call.
 *
 * ## This used to ask React whether it was rendering, and got a wrong answer every time
 *
 * It read `React.__SECRET_INTERNALS_DO_NOT_OR_YOU_WILL_BE_FIRED`. The real property is
 * `__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED` — `USE_` is missing from the middle of
 * that name. `undefined?.ReactCurrentDispatcher?.current` is `undefined`, `!dispatcher` was
 * therefore ALWAYS true, and every component in the console took the snapshot branch and
 * subscribed to nothing. The catalogues were complete, the store updated, `<html lang>`
 * flipped, the switcher redrew its own flag because its own `useState` had re-rendered it —
 * and not one other word on the page moved. Switching language did nothing, and had done
 * nothing since the day the engine landed.
 *
 * The probe is gone rather than corrected. Its name is private to React and changed shape in
 * React 19 (`__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE`), so a fixed
 * spelling would be the same bug waiting for the same upgrade, failing exactly as silently.
 * `try`/`catch` needs no name: outside a render `useSyncExternalStore` reads a null dispatcher
 * and throws, which is the one signal React actually promises.
 */
function useI18nImpl<U = I18nStore>(selector?: (state: I18nStore) => U): U {
  try {
    return baseStore(selector as (state: I18nStore) => U);
  } catch {
    syncWithEnvironmentIfChanged();
    const proxy = createStoreProxy();
    return selector ? selector(proxy) : (proxy as unknown as U);
  }
}

export const useI18n: UseBoundStore<StoreApi<I18nStore>> = Object.assign(
  useI18nImpl,
  baseStore,
  {
    subscribe: (listener: (state: I18nStore, prevState: I18nStore) => void) => {
      syncWithEnvironmentIfChanged();
      return baseStore.subscribe(listener);
    },
    getState: () => {
      syncWithEnvironmentIfChanged();
      return baseStore.getState();
    },
  },
);

/** Alias for compatibility across codebase references. */
export const useI18nStore = useI18n;

/* -------------------------------------------------------------------------- */
/* Imperative Non-React Helpers                                               */
/* -------------------------------------------------------------------------- */

export const getLocale = (): SupportedLocale => {
  syncWithEnvironmentIfChanged();
  return useI18n.getState().locale;
};

export const setLocale = (locale: SupportedLocale): void => {
  syncWithEnvironmentIfChanged();
  useI18n.getState().setLocale(locale);
};

export function t(path: TranslationPath, params?: Record<string, string | number>): string;
export function t(path: string, params?: Record<string, unknown>): string;
export function t(path: string, params?: Record<string, unknown>): string {
  syncWithEnvironmentIfChanged();
  return useI18n.getState().t(path as TranslationPath, params as Record<string, string | number>);
}

/* -------------------------------------------------------------------------- */
/* Cross-Tab Synchronization                                                  */
/* -------------------------------------------------------------------------- */

if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event: StorageEvent) => {
    if (event.key === LOCALE_STORAGE_KEY && event.newValue) {
      if (isSupportedLocale(event.newValue) && event.newValue !== useI18n.getState().locale) {
        useI18n.getState().setLocale(event.newValue);
      }
    }
  });
}

export * from "./types";
export { en, ru, uz };
