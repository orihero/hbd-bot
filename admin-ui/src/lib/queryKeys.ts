/**
 * The query-key factory.
 *
 * One place, because keys are how invalidation works and two screens spelling the same read
 * differently is an invalidation that silently misses. Every key starts with a resource name
 * so `queryClient.invalidateQueries({queryKey: queryKeys.orders.all})` catches every orders
 * query whatever its filters.
 *
 * Filter objects go in the key as-is. TanStack Query hashes them stably (its `hashKey` sorts
 * object keys), so `{state: ["failed"], limit: 50}` and `{limit: 50, state: ["failed"]}` are
 * the same key — no need to normalise before calling.
 */

import type {
  AssetsQuery,
  AuditQuery,
  GenerationsQuery,
  OrderAttemptsQuery,
  OrderStateCountsQuery,
  OrdersQuery,
  PageQuery,
  RetentionQuery,
  UserCreditsQuery,
  UsersQuery,
  VendorUsageQuery,
  WindowQuery,
} from "@/api";

export const queryKeys = {
  health: {
    readyz: () => ["readyz"] as const,
  },

  auth: {
    me: () => ["auth", "me"] as const,
  },

  ops: {
    all: ["ops"] as const,
    pulse: () => ["ops", "pulse"] as const,
    capabilities: () => ["ops", "capabilities"] as const,
  },

  metrics: {
    all: ["metrics"] as const,
    ordersByDay: (window: WindowQuery) => ["metrics", "orders-by-day", window] as const,
    failures: (window: WindowQuery) => ["metrics", "failures", window] as const,
    latency: (window: WindowQuery) => ["metrics", "latency", window] as const,
    nameStrategies: (window: WindowQuery) => ["metrics", "name-strategies", window] as const,
    /** The windowed bake-off + distribution + cliff count that `/generations/names` reads. */
    nameAnalytics: (window: WindowQuery) => ["metrics", "name-analytics", window] as const,
  },

  /**
   * `/vendors`' three reads.
   *
   * Its own namespace rather than three more entries under `metrics`, because the screen's
   * three queries share ONE filter object and are invalidated together: a namespace prefix
   * is what lets `invalidateQueries({queryKey: queryKeys.vendors.all})` refresh the rollup,
   * the daily series and the failure mix as a set. Splitting them across `metrics` would
   * mean invalidating the orders-by-day chart to refresh a spend table.
   *
   * The query object goes in as-is, `vendor` array and all — TanStack hashes it stably.
   */
  vendors: {
    all: ["vendors"] as const,
    usage: (query: VendorUsageQuery) => ["vendors", "usage", query] as const,
    byDay: (query: VendorUsageQuery) => ["vendors", "by-day", query] as const,
    errors: (query: VendorUsageQuery) => ["vendors", "errors", query] as const,
  },

  orders: {
    all: ["orders"] as const,
    list: (query: OrdersQuery) => ["orders", "list", query] as const,
    /**
     * The filtered aggregate behind the distribution bar. Keyed on the list's filters MINUS
     * paging (`OrderStateCountsQuery` is `OrdersQuery` without `PageQuery`), so turning a page
     * does not refetch an aggregate that does not depend on the page — and so the bar keeps
     * describing the whole filtered set rather than the fifty rows on screen.
     */
    stateCounts: (query: OrderStateCountsQuery) => ["orders", "state-counts", query] as const,
    detail: (orderId: string) => ["orders", "detail", orderId] as const,
    attempts: (orderId: string, query: OrderAttemptsQuery) =>
      ["orders", "detail", orderId, "attempts", query] as const,
    assets: (orderId: string, query: PageQuery) =>
      ["orders", "detail", orderId, "assets", query] as const,
    timeline: (orderId: string) => ["orders", "detail", orderId, "timeline"] as const,
  },

  users: {
    all: ["users"] as const,
    list: (query: UsersQuery) => ["users", "list", query] as const,
    detail: (telegramUserId: number) => ["users", "detail", telegramUserId] as const,
    orders: (telegramUserId: number, query: PageQuery) =>
      ["users", "detail", telegramUserId, "orders", query] as const,
    /**
     * The balance and the ledger — ONE key, because they are one response.
     *
     * Under `users.detail` so that a grant can invalidate `queryKeys.users.detail(id)` and
     * catch this too: `creditsProjected` on the detail and `account.balance` here both move on
     * a grant, and a screen that refreshed one without the other would show the pair the whole
     * feature exists to compare disagreeing with itself.
     */
    credits: (telegramUserId: number, query: UserCreditsQuery) =>
      ["users", "detail", telegramUserId, "credits", query] as const,
    /** Redis-backed and never 404s, so it is cached separately from the user detail — a
     *  stuck customer has wizard state and no user row at all. */
    wizardState: (telegramUserId: number) =>
      ["users", "detail", telegramUserId, "wizard-state"] as const,
  },

  generations: {
    all: ["generations"] as const,
    list: (query: GenerationsQuery) => ["generations", "list", query] as const,
    detail: (attemptId: string) => ["generations", "detail", attemptId] as const,
  },

  assets: {
    all: ["assets"] as const,
    list: (query: AssetsQuery) => ["assets", "list", query] as const,
    detail: (assetId: string) => ["assets", "detail", assetId] as const,
    /*
     * There is deliberately NO key for `GET /api/assets/{id}/text`. Reading a lyric sheet
     * is a REVEAL — charged against the budget and committed to the audit log on every
     * call — and a cache entry is a thing that can be refetched by an invalidation the
     * operator did not ask for. `/assets` drives it as a MUTATION instead, so a second
     * disclosure can only happen after a second click.
     */
  },

  audit: {
    all: ["audit"] as const,
    list: (query: AuditQuery) => ["audit", "list", query] as const,
    verify: () => ["audit", "verify"] as const,
  },

  retention: {
    all: ["retention"] as const,
    list: (query: RetentionQuery) => ["retention", "list", query] as const,
  },

  admins: {
    all: ["admins"] as const,
    list: () => ["admins", "list"] as const,
  },

  config: {
    all: ["config"] as const,
    detail: () => ["config", "detail"] as const,
  },

  /**
   * The reveal budget, and it is the one key here that names NO endpoint.
   *
   * There is no `GET /api/reveal/budget` and no `/metrics/reveals` on this build (§12.3 asks
   * for the second and no phase mounts it). The only place a REMAINING figure exists is the
   * `budget` object on a `POST /api/reveal` response — and, on a 429, in the refusal's
   * `details`. So the cache holds the last answer the server gave this tab and every meter on
   * screen reads it from here, which is what makes one reveal's cost visible on the next
   * dialog. `/api/config` supplies the two CEILINGS; it does not supply what is left.
   *
   * It is written with `setQueryData` and never fetched. Do not give it a `queryFn` that
   * calls the API: a budget the SPA could refresh on demand would be a counter an operator
   * could poll, and the number would still be a guess about a Redis key this process shares
   * with every other tab and session the same account has open.
   */
  reveal: {
    all: ["reveal"] as const,
    budget: () => ["reveal", "budget"] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
