/**
 * The render harness these components' tests share.
 *
 * Everything in `components/layout` and `components/util` needs at least one of: a
 * `QueryClientProvider` (the session, the pulse), a router (`NavLink`, `useNavigate`), and a
 * clean `usePrefsStore`. Rebuilding that in ten files is how three of them end up with a
 * retrying query client and flake.
 *
 * The client is built with `retry: false` and no polling: a test that waits out a 1s backoff
 * is a test nobody runs. Session and pulse data are SEEDED into the cache rather than
 * fetched, so no test depends on `fetch` at all.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import type { AdminRole, ConfigView, MeResponse } from "@/api";
import { queryKeys } from "@/lib/queryKeys";
import { usePrefsStore } from "@/lib/stores";

export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: Infinity, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

export function meFixture(role: AdminRole = "owner"): MeResponse {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    username: "operator",
    role,
    lastLoginAt: "2026-09-01T09:15:00Z",
    mustChangePassword: false,
  };
}

/** Only the fields the top bar reads; the rest is filled with defensible defaults. */
export function configFixture(environment: ConfigView["environment"] = "prod"): ConfigView {
  return {
    environment,
    logLevel: "INFO",
    isDebug: false,
    isProduction: environment === "prod",
    adminEnabled: true,
    adminConfigEnabled: true,
    adminHost: "127.0.0.1",
    adminPort: 8080,
    adminPublicOrigin: "https://admin.test",
    isCookieSecure: true,
    adminSessionTtlS: 43_200,
    adminSessionIdleTtlS: 3_600,
    adminStepUpGraceSeconds: 300,
    adminArgon2TimeCost: 3,
    adminArgon2MemoryKib: 65_536,
    adminArgon2Parallelism: 4,
    adminTrustedProxyHops: 0,
    adminTrustedProxyCidrs: [],
    adminRevealRecordsPerHour: 200,
    adminRevealConversationsPerDay: 20,
    databaseHost: "db.internal",
    databasePort: 5432,
    redisHost: "redis.internal",
    redisPort: 6379,
    isAuditDsnConfigured: true,
    isProbeTokenConfigured: true,
  };
}

export interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  readonly client?: QueryClient;
  /** Seeds `queryKeys.auth.me()`. Pass `null` for "no session yet". */
  readonly me?: MeResponse | null;
  /** Seeds `queryKeys.config.detail()`, which is where the env badge reads from. */
  readonly config?: ConfigView | null;
  readonly route?: string;
}

export interface RenderWithProvidersResult extends RenderResult {
  readonly client: QueryClient;
}

export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderWithProvidersResult {
  const { client = makeTestQueryClient(), me = meFixture(), config = null, route = "/" } = options;

  if (me !== null) client.setQueryData(queryKeys.auth.me(), me);
  if (config !== null) client.setQueryData(queryKeys.config.detail(), config);

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );

  const result = render(ui, { ...options, wrapper });
  return Object.assign(result, { client });
}

/**
 * Install a `matchMedia` stub if this environment lacks one.
 *
 * `src/test/setup.ts` installs one in a `beforeAll`, and now guards on the type rather than
 * on `"matchMedia" in window` — a property that is present and `undefined` passes the `in`
 * check, and then `applyTheme("system")` throws. This stays as belt-and-braces for a test
 * that needs the stub before that hook has run, or that replaces it.
 */
export function ensureMatchMedia(): void {
  if (typeof window.matchMedia === "function") return;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

/** Put `usePrefsStore` back to its declared defaults. Call in a `beforeEach`. */
export function resetPrefs(): void {
  ensureMatchMedia();
  usePrefsStore.setState({
    // The store's own declared default, which is LIGHT since the reskin — `:root` carries
    // the light palette and `[data-theme="dark"]` overrides it. A harness that reset to a
    // different default from the store's would make every theme assertion a statement about
    // this file rather than about the console.
    theme: "light",
    timeZoneMode: "utc",
    isNavCollapsed: false,
    density: "comfortable",
    isCommandPaletteOpen: false,
  });
}
