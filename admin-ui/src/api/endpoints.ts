/**
 * One typed function per endpoint. Thirty-one routes, all of them.
 *
 * Screen and component code imports from here (via `src/api`) and calls `fetch` nowhere.
 * Every function returns `Promise<ApiResult<T>>` and never throws; at a TanStack Query
 * boundary wrap it in `unwrapAsync` from errors.ts.
 *
 * Conventions worth knowing before you use these:
 *
 * - **`ENDPOINT.*` are route TEMPLATES with snake_case parameter names** (`{order_id}`,
 *   `{telegram_user_id}`). That is the shipped server spelling and §12.1 T8's enumeration
 *   test compares against it; the plan's §6.1 writes `{telegramUserId}` and is stale
 *   (contract D3). It does not change the URL a client builds.
 *
 * - **There is NO `sort` parameter on any endpoint.** §6.1's `?sort=-created_at` is not
 *   implemented anywhere. Every list is `ORDER BY created_at DESC, id DESC`, newest first,
 *   fixed. Do not build a sort control (contract D2).
 *
 * - **`from`/`to` are ONE WINDOW everywhere except `/api/audit`.** Sending one without the
 *   other is a 422 on orders, users, generations, assets and all four metrics routes. The
 *   audit log alone accepts a half-open window, because its query builder passes the bounds
 *   through independently (contract D6). A shared date-range widget must still send both
 *   bounds to everything else. A naive (offset-less) timestamp is a 422 everywhere.
 *
 * - **404 behaviour is deliberately uneven and must not be normalised.**
 *   `/orders/{id}` and `/orders/{id}/timeline` 404; `/orders/{id}/attempts` and
 *   `/orders/{id}/assets` do NOT — an empty page is the right answer to a filter.
 *   `/users/{id}` and `/users/{id}/orders` 404; `/users/{id}/wizard-state` NEVER does,
 *   because the person it exists for has no `users` row by construction.
 */

import { get, post, postNoContent, request, type CallOptions, type QueryParams } from "./client";
import { AUTH_PREFIX, HEALTHZ_PATH, READYZ_PATH } from "./constants";
import type { ApiResult } from "./errors";
import type {
  AssetKind,
  AuditAction,
  AuditOutcome,
  GenerationKind,
  Language,
  NameStrategy,
  OrderState,
  RetentionClass,
} from "./enums";
import {
  adminRosterResponseSchema,
  assetTextViewSchema,
  assetWireViewSchema,
  assetsPageSchema,
  attemptWireViewSchema,
  attemptsPageSchema,
  auditPageSchema,
  capabilitiesViewSchema,
  chainVerifyResponseSchema,
  configViewSchema,
  failureSeriesSchema,
  latencyViewSchema,
  loginResponseSchema,
  meResponseSchema,
  nameAnalyticsViewSchema,
  orderDetailViewSchema,
  ordersPageSchema,
  ordersPerDaySeriesSchema,
  pulseViewSchema,
  readyzResponseSchema,
  retentionResponseSchema,
  revealResponseSchema,
  stepUpResponseSchema,
  strategyOutcomeSeriesSchema,
  timelineViewSchema,
  userDetailViewSchema,
  usersPageSchema,
  wizardStateViewSchema,
  type AdminRosterResponse,
  type AssetTextView,
  type AssetWireView,
  type AssetsPage,
  type AttemptWireView,
  type AttemptsPage,
  type AuditPage,
  type CapabilitiesView,
  type ChainVerifyResponse,
  type ConfigView,
  type FailureView,
  type LatencyView,
  type LoginRequest,
  type LoginResponse,
  type MeResponse,
  type NameAnalyticsView,
  type OrderDetailView,
  type OrdersPage,
  type OrdersPerDayView,
  type PasswordChangeRequest,
  type PulseView,
  type ReadyzResponse,
  type RetentionResponse,
  type RevealRequest,
  type RevealResponse,
  type StepUpRequest,
  type StepUpResponse,
  type StrategyOutcomeView,
  type TimelineView,
  type UserDetailView,
  type UsersPage,
  type WizardStateView,
} from "./schemas";

/* -------------------------------------------------------------------------- */
/* Route templates                                                             */
/* -------------------------------------------------------------------------- */

/**
 * The exact server-side route templates, for failure messages and query keys. Never
 * interpolate these by hand — use the `path*` builders below, which encode their arguments.
 */
export const ENDPOINT = {
  healthz: "GET /healthz",
  readyz: "GET /readyz",

  login: "POST /api/auth/login",
  me: "GET /api/auth/me",
  logout: "POST /api/auth/logout",
  passwordChange: "POST /api/auth/password",
  stepUp: "POST /api/auth/step-up",

  pulse: "GET /api/ops/pulse",
  capabilities: "GET /api/ops/capabilities",
  ordersByDay: "GET /api/metrics/orders-by-day",
  failures: "GET /api/metrics/failures",
  latency: "GET /api/metrics/latency",
  nameStrategies: "GET /api/metrics/name-strategies",
  nameAnalytics: "GET /api/metrics/name-analytics",

  orders: "GET /api/orders",
  order: "GET /api/orders/{order_id}",
  orderAttempts: "GET /api/orders/{order_id}/attempts",
  orderAssets: "GET /api/orders/{order_id}/assets",
  orderTimeline: "GET /api/orders/{order_id}/timeline",

  users: "GET /api/users",
  user: "GET /api/users/{telegram_user_id}",
  userOrders: "GET /api/users/{telegram_user_id}/orders",
  wizardState: "GET /api/users/{telegram_user_id}/wizard-state",

  generations: "GET /api/generations",
  attempt: "GET /api/generations/{attempt_id}",

  assets: "GET /api/assets",
  asset: "GET /api/assets/{asset_id}",
  assetStream: "GET /api/assets/{asset_id}/stream",
  assetText: "GET /api/assets/{asset_id}/text",

  admins: "GET /api/admins",
  config: "GET /api/config",
  audit: "GET /api/audit",
  auditVerify: "GET /api/audit/verify",
  retention: "GET /api/retention",

  /* The ONE path by which masked data becomes plaintext (§12.2, §12.3). One reveal path,
     one audit shape, one budget — a second reveal endpoint is how one of them ends up
     unaudited, so a new subject or column is a `RevealField` member and never a route. */
  reveal: "POST /api/reveal",
} as const;

export type EndpointName = keyof typeof ENDPOINT;

/* -------------------------------------------------------------------------- */
/* Query parameter shapes                                                      */
/* -------------------------------------------------------------------------- */

/**
 * The three parameters every `Page<T>` endpoint takes.
 *
 * `cursor` is OPAQUE. It comes from a previous response's `meta.nextCursor` and from nowhere
 * else; a value this API did not issue is a 422. The audit log's cursor is a different
 * encoding (unpadded base64url over `{"seq": n}`) and crossing the two is a 422 as well.
 *
 * `withTotal` costs a second query, so it is off by default. When it is on, `total` and
 * `isTotalExact` arrive as a pair, and `{10000, false}` means "10,000+".
 */
export interface PageQuery {
  readonly limit?: number | undefined;
  readonly cursor?: string | undefined;
  readonly withTotal?: boolean | undefined;
}

/** `from`/`to` are a PAIR: both, or neither. Both are RFC 3339 with an offset. */
export interface WindowQuery {
  readonly from?: string | undefined;
  readonly to?: string | undefined;
}

export interface OrdersQuery extends PageQuery, WindowQuery {
  /** Repeats: `?state=failed&state=cancelled` means failed OR cancelled. */
  readonly state?: readonly OrderState[] | undefined;
  readonly isPaid?: boolean | undefined;
  readonly telegramUserId?: number | undefined;
  readonly correlationId?: string | undefined;
  readonly hasAssets?: boolean | undefined;
}

export interface UsersQuery extends PageQuery, WindowQuery {
  readonly telegramUserId?: number | undefined;
  readonly isBlocked?: boolean | undefined;
  /** Repeats. */
  readonly uiLanguage?: readonly Language[] | undefined;
}

export interface GenerationsQuery extends PageQuery, WindowQuery {
  /** Repeats. */
  readonly kind?: readonly GenerationKind[] | undefined;
  readonly provider?: string | undefined;
  readonly isSuccess?: boolean | undefined;
  readonly errorCode?: string | undefined;
  /** The one enum filter here that does NOT repeat — a single value. */
  readonly strategy?: NameStrategy | undefined;
  /** `order_id IS NULL`. It cannot say which KIND of orphan. */
  readonly isOrphaned?: boolean | undefined;
}

export interface AssetsQuery extends PageQuery, WindowQuery {
  /** Repeats. */
  readonly kind?: readonly AssetKind[] | undefined;
  /** Repeats. */
  readonly retentionClass?: readonly RetentionClass[] | undefined;
  /**
   * `1 … 365`. There is NO lower bound on the window: a row already past `expires_at` is
   * included, because it is the most urgent line on the retention page.
   */
  readonly expiringWithinDays?: number | undefined;
}

/** `/api/orders/{order_id}/attempts` — no `from`/`to` here. */
export interface OrderAttemptsQuery extends PageQuery {
  /** Repeats. */
  readonly kind?: readonly GenerationKind[] | undefined;
  readonly isSuccess?: boolean | undefined;
}

/**
 * The audit log's own parameters. Note three departures from every other list:
 * `from`/`to` are INDEPENDENT here; there is no `withTotal`; and `actor` is matched as a
 * UUID when it parses as one and as a case-folded username otherwise.
 */
export interface AuditQuery {
  readonly cursor?: string | undefined;
  readonly limit?: number | undefined;
  readonly actor?: string | undefined;
  /** Repeats. */
  readonly action?: readonly AuditAction[] | undefined;
  readonly subjectType?: string | undefined;
  readonly subjectId?: string | undefined;
  /** Repeats. */
  readonly outcome?: readonly AuditOutcome[] | undefined;
  /** The wire name is `from`, not `since`. */
  readonly from?: string | undefined;
  readonly to?: string | undefined;
}

/** `/api/retention` — `limit` only, defaulting to 24 (not 50). No cursor, no `withTotal`. */
export interface RetentionQuery {
  readonly limit?: number | undefined;
}

/* -------------------------------------------------------------------------- */
/* Path builders                                                               */
/* -------------------------------------------------------------------------- */

const encode = (value: string | number): string => encodeURIComponent(String(value));

export const pathOrder = (orderId: string): string => `/api/orders/${encode(orderId)}`;
export const pathOrderAttempts = (orderId: string): string => `${pathOrder(orderId)}/attempts`;
export const pathOrderAssets = (orderId: string): string => `${pathOrder(orderId)}/assets`;
export const pathOrderTimeline = (orderId: string): string => `${pathOrder(orderId)}/timeline`;
export const pathUser = (telegramUserId: number): string => `/api/users/${encode(telegramUserId)}`;
export const pathUserOrders = (telegramUserId: number): string =>
  `${pathUser(telegramUserId)}/orders`;
export const pathWizardState = (telegramUserId: number): string =>
  `${pathUser(telegramUserId)}/wizard-state`;
export const pathAttempt = (attemptId: string): string => `/api/generations/${encode(attemptId)}`;
export const pathAsset = (assetId: string): string => `/api/assets/${encode(assetId)}`;

/**
 * The URL an `<audio src>` points at — `GET /api/assets/{id}/stream`, live since Phase 2.
 *
 * It is a SAME-ORIGIN subresource, so the `__Host-` session cookie travels with it
 * automatically and no token ever appears in a URL (§11.1). Do not build a signed-URL
 * scheme for it, and do not add a query string: the element cannot carry a body, the route
 * takes no parameters, and a `?reasonCode=` here would be the only place in the console
 * where a reveal reason rides in a URL an operator can paste.
 *
 * The bytes move only for `audio/mpeg` and `audio/ogg` (415 otherwise), only with a step-up
 * scoped to this asset id (403 otherwise), and only while the reveal budget holds (429).
 * Nothing here downloads a song — an `<audio>` element streams, and pulling a whole song
 * into memory to hand it a blob would defeat the range support the route was built for. The
 * one `fetch` that touches this URL is `probeAssetStream` in `stream.ts`, which asks for a
 * single byte, reads the status and the `Content-Range`, and cancels the body: an `<audio>`
 * element collapses every one of the six refusals above into one opaque `error` event, so
 * the console asks the question in a form that can be answered before it hands the element
 * the URL. That probe IS the request §12.3's ten-minute window is keyed on, so the element's
 * own range requests cost no further audit row and no further budget unit.
 */
export const pathAssetStream = (assetId: string): string => `${pathAsset(assetId)}/stream`;

/** `GET /api/assets/{id}/text` — the lyric sheet as JSON, never as `text/plain` (T7). */
export const pathAssetText = (assetId: string): string => `${pathAsset(assetId)}/text`;

/* -------------------------------------------------------------------------- */
/* Health                                                                      */
/* -------------------------------------------------------------------------- */

/** 200 with an EMPTY body — not JSON. Touches nothing. */
export function getHealthz(options?: CallOptions): Promise<ApiResult<void>> {
  return request<void>({
    endpoint: ENDPOINT.healthz,
    path: HEALTHZ_PATH,
    ...(options?.signal ? { signal: options.signal } : {}),
  });
}

/**
 * The shape depends on AUTHORISATION, not on role: an unauthorised caller gets the constant
 * `{status: "ok"}` whatever the deployment is doing; a live session or a matching
 * `X-Probe-Token` gets the detail.
 */
export function getReadyz(options?: CallOptions): Promise<ApiResult<ReadyzResponse>> {
  return get(ENDPOINT.readyz, READYZ_PATH, readyzResponseSchema, undefined, options);
}

/* -------------------------------------------------------------------------- */
/* Auth                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * The only unauthenticated body this API accepts. Needs a matching `Origin` (the browser
 * sends it) and NO CSRF token, because there is no session yet.
 *
 * Sets both cookies. `401` is deliberately indistinguishable between an unknown username and
 * a wrong password — there is no user enumeration here, so do not try to tell an operator
 * which half was wrong.
 */
export function postLogin(
  body: LoginRequest,
  options?: CallOptions,
): Promise<ApiResult<LoginResponse>> {
  return post(ENDPOINT.login, `${AUTH_PREFIX}/login`, loginResponseSchema, body, options);
}

/** Exempt from the forced-rotation gate — one of only two routes that are. */
export function getMe(options?: CallOptions): Promise<ApiResult<MeResponse>> {
  return get(ENDPOINT.me, `${AUTH_PREFIX}/me`, meResponseSchema, undefined, options);
}

/**
 * 204, empty body, both cookies deleted.
 *
 * NOT exempt from the forced-rotation gate: while `mustChangePassword` is true this is a
 * 403. An operator on the rotation screen cannot sign out — dropping the cookie needs no
 * route, so clear local state and go to `/login` yourself.
 */
export function postLogout(options?: CallOptions): Promise<ApiResult<void>> {
  return postNoContent(ENDPOINT.logout, `${AUTH_PREFIX}/logout`, {}, options);
}

/**
 * Exempt from the forced-rotation gate. Revokes every session for the account and sets a
 * FRESH pair of cookies, so the caller stays signed in.
 *
 * A wrong `currentPassword` is a **403**, not a 401 — mistyping your own password must not
 * sign you out.
 */
export function postPasswordChange(
  body: PasswordChangeRequest,
  options?: CallOptions,
): Promise<ApiResult<LoginResponse>> {
  return post(
    ENDPOINT.passwordChange,
    `${AUTH_PREFIX}/password`,
    loginResponseSchema,
    body,
    options,
  );
}

/**
 * Request `scope` is a bare `StepUpAction`; response `scope` is the composed
 * `"<action>:<subjectId>"`. The window is zero for `user.purge` and `config.write`.
 *
 * **Nothing consumes a grant yet.** `require_step_up` / `check_step_up` have no handler
 * callers anywhere in `src/hbd/admin/routers/`, and the one router guard that reports
 * `STEP_UP_REQUIRED` (`RequirePermission` → `check_role`) decides from the §12.2 cell alone
 * and never reads the session's grant. So a 200 from here changes the outcome of no request
 * on this build. Phase 2's A+S cells are what this is for; until one of them lands, calling
 * it spends the operator's re-auth budget and writes a `STEP_UP_SUCCESS` audit row for
 * nothing, so no Phase 1 screen calls it.
 */
export function postStepUp(
  body: StepUpRequest,
  options?: CallOptions,
): Promise<ApiResult<StepUpResponse>> {
  return post(ENDPOINT.stepUp, `${AUTH_PREFIX}/step-up`, stepUpResponseSchema, body, options);
}

/* -------------------------------------------------------------------------- */
/* Ops and metrics                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Every dashboard counter in ONE request, so the 5s tick is one round trip (§11.5). Takes no
 * parameters at all — the pulse has no window.
 */
export function getPulse(options?: CallOptions): Promise<ApiResult<PulseView>> {
  return get(ENDPOINT.pulse, "/api/ops/pulse", pulseViewSchema, undefined, options);
}

export function getCapabilities(options?: CallOptions): Promise<ApiResult<CapabilitiesView>> {
  return get(
    ENDPOINT.capabilities,
    "/api/ops/capabilities",
    capabilitiesViewSchema,
    undefined,
    options,
  );
}

/** Bare array, OLDEST first. A day with no orders is absent, not zero-filled. */
export function getOrdersByDay(
  query: WindowQuery = {},
  options?: CallOptions,
): Promise<ApiResult<OrdersPerDayView[]>> {
  return get(
    ENDPOINT.ordersByDay,
    "/api/metrics/orders-by-day",
    ordersPerDaySeriesSchema,
    windowParams(query),
    options,
  );
}

/** Bare array, LARGEST first. */
export function getFailures(
  query: WindowQuery = {},
  options?: CallOptions,
): Promise<ApiResult<FailureView[]>> {
  return get(
    ENDPOINT.failures,
    "/api/metrics/failures",
    failureSeriesSchema,
    windowParams(query),
    options,
  );
}

/** A single object, not an array. */
export function getLatency(
  query: WindowQuery = {},
  options?: CallOptions,
): Promise<ApiResult<LatencyView>> {
  return get(
    ENDPOINT.latency,
    "/api/metrics/latency",
    latencyViewSchema,
    windowParams(query),
    options,
  );
}

/** Bare array. Feeds the `/generations/names` bake-off and the `HBD_NAME_CANDIDATE_ORDER`
 *  recommendation that links to `/config`. */
export function getNameStrategies(
  query: WindowQuery = {},
  options?: CallOptions,
): Promise<ApiResult<StrategyOutcomeView[]>> {
  return get(
    ENDPOINT.nameStrategies,
    "/api/metrics/name-strategies",
    strategyOutcomeSeriesSchema,
    windowParams(query),
    options,
  );
}

/**
 * The whole of `/generations/names` in one read: bake-off rows, the summed distribution,
 * the threshold and the count sitting within a band of it.
 *
 * It does NOT supersede `getNameStrategies` — `/generations` and the config screen consume
 * that bare array and its shape is frozen. This is the windowed, counted-in-the-database
 * answer the names screen needs, over one population, so its two halves cannot disagree.
 */
export function getNameAnalytics(
  query: WindowQuery = {},
  options?: CallOptions,
): Promise<ApiResult<NameAnalyticsView>> {
  return get(
    ENDPOINT.nameAnalytics,
    "/api/metrics/name-analytics",
    nameAnalyticsViewSchema,
    windowParams(query),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Orders                                                                      */
/* -------------------------------------------------------------------------- */

export function getOrders(
  query: OrdersQuery = {},
  options?: CallOptions,
): Promise<ApiResult<OrdersPage>> {
  return get(
    ENDPOINT.orders,
    "/api/orders",
    ordersPageSchema,
    {
      state: query.state,
      isPaid: query.isPaid,
      telegramUserId: query.telegramUserId,
      correlationId: query.correlationId,
      hasAssets: query.hasAssets,
      ...windowParams(query),
      ...pageParams(query),
    },
    options,
  );
}

/** 404s on an unknown id, and the id is NOT echoed back. `assets` and `attempts` inside the
 *  detail are ALL of them, unpaged. */
export function getOrder(
  orderId: string,
  options?: CallOptions,
): Promise<ApiResult<OrderDetailView>> {
  return get(ENDPOINT.order, pathOrder(orderId), orderDetailViewSchema, undefined, options);
}

/** Does NOT 404 on an unknown order id — an empty page is the answer to a filter that
 *  matched nothing. */
export function getOrderAttempts(
  orderId: string,
  query: OrderAttemptsQuery = {},
  options?: CallOptions,
): Promise<ApiResult<AttemptsPage>> {
  return get(
    ENDPOINT.orderAttempts,
    pathOrderAttempts(orderId),
    attemptsPageSchema,
    { kind: query.kind, isSuccess: query.isSuccess, ...pageParams(query) },
    options,
  );
}

/** Only `withTotal`/`limit`/`cursor`; no kind or retention filters here. Does NOT 404. */
export function getOrderAssets(
  orderId: string,
  query: PageQuery = {},
  options?: CallOptions,
): Promise<ApiResult<AssetsPage>> {
  return get(
    ENDPOINT.orderAssets,
    pathOrderAssets(orderId),
    assetsPageSchema,
    pageParams(query),
    options,
  );
}

/** DOES 404 — it claims to return *an order's* timeline. */
export function getOrderTimeline(
  orderId: string,
  options?: CallOptions,
): Promise<ApiResult<TimelineView>> {
  return get(
    ENDPOINT.orderTimeline,
    pathOrderTimeline(orderId),
    timelineViewSchema,
    undefined,
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Users                                                                       */
/* -------------------------------------------------------------------------- */

export function getUsers(
  query: UsersQuery = {},
  options?: CallOptions,
): Promise<ApiResult<UsersPage>> {
  return get(
    ENDPOINT.users,
    "/api/users",
    usersPageSchema,
    {
      telegramUserId: query.telegramUserId,
      isBlocked: query.isBlocked,
      uiLanguage: query.uiLanguage,
      ...windowParams(query),
      ...pageParams(query),
    },
    options,
  );
}

/**
 * The path parameter is the INTEGER TELEGRAM ID, never `users.id` (which is also on
 * `UserView`, as `id`, and is not the route key).
 *
 * 404s on an unknown id, and the message deliberately does not echo it.
 */
export function getUser(
  telegramUserId: number,
  options?: CallOptions,
): Promise<ApiResult<UserDetailView>> {
  return get(ENDPOINT.user, pathUser(telegramUserId), userDetailViewSchema, undefined, options);
}

/** 404s on an unknown id: an empty page would read as "never ordered" rather than as
 *  "we hold nothing about this id". */
export function getUserOrders(
  telegramUserId: number,
  query: PageQuery = {},
  options?: CallOptions,
): Promise<ApiResult<OrdersPage>> {
  return get(
    ENDPOINT.userOrders,
    pathUserOrders(telegramUserId),
    ordersPageSchema,
    pageParams(query),
    options,
  );
}

/**
 * Its OWN permission (`wizard_state.read`) on its own router — not `records.read`.
 *
 * Reads Redis, not the database, and NEVER 404s: the person it exists for is stuck
 * mid-wizard and has no `users` row at all.
 */
export function getWizardState(
  telegramUserId: number,
  options?: CallOptions,
): Promise<ApiResult<WizardStateView>> {
  return get(
    ENDPOINT.wizardState,
    pathWizardState(telegramUserId),
    wizardStateViewSchema,
    undefined,
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Generations                                                                 */
/* -------------------------------------------------------------------------- */

export function getGenerations(
  query: GenerationsQuery = {},
  options?: CallOptions,
): Promise<ApiResult<AttemptsPage>> {
  return get(
    ENDPOINT.generations,
    "/api/generations",
    attemptsPageSchema,
    {
      kind: query.kind,
      provider: query.provider,
      isSuccess: query.isSuccess,
      errorCode: query.errorCode,
      strategy: query.strategy,
      isOrphaned: query.isOrphaned,
      ...windowParams(query),
      ...pageParams(query),
    },
    options,
  );
}

/** The only 404 on this surface that echoes its id: `details: {attemptId}`, because FastAPI
 *  had already parsed it as a UUID. */
export function getAttempt(
  attemptId: string,
  options?: CallOptions,
): Promise<ApiResult<AttemptWireView>> {
  return get(ENDPOINT.attempt, pathAttempt(attemptId), attemptWireViewSchema, undefined, options);
}

/* -------------------------------------------------------------------------- */
/* Assets                                                                      */
/* -------------------------------------------------------------------------- */

export function getAssets(
  query: AssetsQuery = {},
  options?: CallOptions,
): Promise<ApiResult<AssetsPage>> {
  return get(
    ENDPOINT.assets,
    "/api/assets",
    assetsPageSchema,
    {
      kind: query.kind,
      retentionClass: query.retentionClass,
      expiringWithinDays: query.expiringWithinDays,
      ...windowParams(query),
      ...pageParams(query),
    },
    options,
  );
}

/** 404s, and the message echoes the (already parsed) id. */
export function getAsset(
  assetId: string,
  options?: CallOptions,
): Promise<ApiResult<AssetWireView>> {
  return get(ENDPOINT.asset, pathAsset(assetId), assetWireViewSchema, undefined, options);
}

/**
 * The lyric sheet. **Calling this IS a reveal**: it re-checks the step-up scoped to this
 * asset, spends one record of the reveal budget and commits an audit row, on EVERY call —
 * there is no dedupe window, because one call returns the whole sheet.
 *
 * So it must be driven by a click and never by a mount. `enabled: false` until the operator
 * asks, `gcTime: 0`, `staleTime: 0`; a cached copy re-read on a re-render would be a second
 * disclosure that no audit row distinguishes from the first.
 *
 * Refusals worth branching on: `STEP_UP_REQUIRED` (403 — confirm the password),
 * `REVEAL_BUDGET_EXHAUSTED` (429), `UNSUPPORTED_MEDIA_TYPE` (415 — this asset is not a
 * lyric sheet), `NOT_FOUND` (404 — no row, or a payload that no longer parses).
 */
export function getAssetText(
  assetId: string,
  options?: CallOptions,
): Promise<ApiResult<AssetTextView>> {
  return get(ENDPOINT.assetText, pathAssetText(assetId), assetTextViewSchema, undefined, options);
}

/* -------------------------------------------------------------------------- */
/* Audit                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * `audit.read`: ADMIN gets a masked read, OWNER an unmasked one. This is the ONE endpoint
 * whose bytes vary by role — `reasonText` is populated at OWNER and `null` at ADMIN, while
 * `hasReasonText` stays true. Every other screen is masked at every role, including OWNER,
 * so no other screen needs a role branch.
 *
 * Pages on `seq` with its OWN envelope (`AuditPageMeta`, no `total`), and its cursor is a
 * different encoding from every other list's.
 */
export function getAudit(
  query: AuditQuery = {},
  options?: CallOptions,
): Promise<ApiResult<AuditPage>> {
  return get(
    ENDPOINT.audit,
    "/api/audit",
    auditPageSchema,
    {
      cursor: query.cursor,
      limit: query.limit,
      actor: query.actor,
      action: query.action,
      subjectType: query.subjectType,
      subjectId: query.subjectId,
      outcome: query.outcome,
      // Independent here, and ONLY here.
      from: query.from,
      to: query.to,
    },
    options,
  );
}

/** No parameters. `ok: true` with `isComplete: false` is not a clean answer over the whole
 *  table — the walk hit its row ceiling. */
export function getAuditVerify(options?: CallOptions): Promise<ApiResult<ChainVerifyResponse>> {
  return get(
    ENDPOINT.auditVerify,
    "/api/audit/verify",
    chainVerifyResponseSchema,
    undefined,
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Retention, admins, config                                                   */
/* -------------------------------------------------------------------------- */

/** `limit` defaults to **24**, not 50. `rowsPastExpiry` is counted live. */
export function getRetention(
  query: RetentionQuery = {},
  options?: CallOptions,
): Promise<ApiResult<RetentionResponse>> {
  return get(
    ENDPOINT.retention,
    "/api/retention",
    retentionResponseSchema,
    { limit: query.limit },
    options,
  );
}

/**
 * `admin.read` — **OWNER only**; every other role is a 403 `FORBIDDEN` with an audit row,
 * so gate the nav entry with `PermissionGate` rather than letting a support operator discover
 * it by clicking (§11.4: role-based HIDING, not disabling).
 *
 * **No step-up. An OWNER session reads this straight, with nothing to re-authenticate.**
 * The guard is `require_permission(ADMIN_READ)`, whose cell is §6.8 line 949's bare owner
 * `W`. Do not draw a step-up affordance for this call and do not treat a 403 here as one:
 * the only 403 this endpoint produces is `FORBIDDEN`, for a role that holds no cell.
 *
 * The split is the ruling on a plan contradiction: §6.8 line 949 gives this read to the
 * owner with **no** `+S` and marks each of the four account writes `W +S` separately, while
 * §12.2 folded all five into one `W+S` row. Following the collapsed row made the
 * roster unreachable by everybody — the router guard resolves to `check_role`, which reports
 * a cell's step-up requirement without ever consulting a grant
 * (`security/permissions.py:379-393`) — so `ADMIN_MANAGE` keeps the `W+S` cell for the
 * writes and this GET moved onto `ADMIN_READ`. Asserted server-side by
 * `tests/test_admin/test_admins_router.py::test_an_owner_reads_the_roster_with_no_step_up_at_all`.
 *
 * No pagination. Deactivated accounts ARE in the list — grey them, do not omit them.
 */
export function getAdmins(options?: CallOptions): Promise<ApiResult<AdminRosterResponse>> {
  return get(ENDPOINT.admins, "/api/admins", adminRosterResponseSchema, undefined, options);
}

/* -------------------------------------------------------------------------- */
/* The reveal                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * `POST /api/reveal` — plaintext for the named fields of one subject.
 *
 * The one path by which masked data becomes plaintext (§12.2), and the only endpoint on this
 * surface whose refusals a caller MUST branch on rather than render flat:
 *
 *  - **403 `STEP_UP_REQUIRED`** is not a dead end. `details.stepUpAction` (`"reveal"`) and
 *    `details.subjectId` name exactly what to re-authenticate for; `POST /auth/step-up` with
 *    that pair, then send this request again unchanged. Route the operator through it —
 *    `stepUpTargetOf` in `components/domain` reads those two keys — and never render it as
 *    an error the operator can only stare at. This is the FIRST route on the surface that
 *    consumes a step-up grant: everything in Phase 1 reported `STEP_UP_REQUIRED` from the
 *    router guard, which holds no subject and therefore never consults a grant.
 *  - **429 `REVEAL_BUDGET_EXHAUSTED`** carries `details.budget` (`"records"` |
 *    `"conversations"`), `details.recordsRequested`, `details.recordsRemaining` and
 *    `details.conversationsRemaining`, plus `Retry-After` counting down to that window's
 *    reset. Say WHICH budget and WHEN it resets; "you have run out" is a support ticket.
 *  - **503 `SERVICE_UNAVAILABLE`** is the budget store being down, which is deliberately NOT
 *    the 429: telling an operator their budget is spent for the hour Redis is down has them
 *    open an incident against the wrong system.
 *  - **422 `INVALID_INPUT`** covers a missing `reasonCode`, a duplicate or mixed-shape
 *    `fields`, `limit`/`cursor` on a single-record reveal, a cursor this API did not mint,
 *    and a `reasonRef` the audit boundary read as a credential. No plaintext crosses and no
 *    audit row is written for any of them.
 *
 * A 404 (unknown subject) still costs a step-up, a charge and an audit row: the row is
 * committed BEFORE the read, so a reveal that then errors is still attributable (§12.3).
 */
export function postReveal(
  body: RevealRequest,
  options?: CallOptions,
): Promise<ApiResult<RevealResponse>> {
  return post(ENDPOINT.reveal, "/api/reveal", revealResponseSchema, body, options);
}

/* -------------------------------------------------------------------------- */
/* Retention, admins, config (continued)                                       */
/* -------------------------------------------------------------------------- */

/** The admin PROCESS's own settings — not the bot's runtime config. Readable by all four
 *  roles; no DSN and no secret is on the wire in any form. */
export function getConfig(options?: CallOptions): Promise<ApiResult<ConfigView>> {
  return get(ENDPOINT.config, "/api/config", configViewSchema, undefined, options);
}

/* -------------------------------------------------------------------------- */
/* Parameter helpers                                                           */
/* -------------------------------------------------------------------------- */

function pageParams(query: PageQuery): QueryParams {
  return { limit: query.limit, cursor: query.cursor, withTotal: query.withTotal };
}

/**
 * `from`/`to` travel together or not at all.
 *
 * Sending exactly one is a 422 on every endpoint except `/api/audit`, and the three routers
 * word that 422 slightly differently from each other — orders says "give both bounds or
 * neither", users says it with a semicolon, generations and assets each have their own
 * phrasing. Nothing should parse those strings; refusing to send half a window here is what
 * keeps an operator from ever seeing one.
 */
function windowParams(query: WindowQuery): QueryParams {
  if (query.from === undefined || query.to === undefined) return {};
  return { from: query.from, to: query.to };
}
