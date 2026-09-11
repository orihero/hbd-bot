/**
 * The React Router 6.28 data router — §11.2's route table.
 *
 * Every screen is `lazy()`, so the initial bundle is the shell and nothing else: an operator
 * opening the console during an incident downloads Live Ops, not the audit log's charts.
 * `lazy()` resolves a module's `Component` export, which is why every screen file ends with
 * `export const Component = XScreen;` — keep that line when you replace a placeholder.
 *
 * `createBrowserRouter`, not the hash router: the server serves `index.html` for every
 * non-`/api` GET (see `_mount_spa` in `src/bayram/admin/app.py`), so a deep link pasted into
 * Slack resolves on a cold load. A hash router would work without that server support and
 * would break every URL an operator has already shared, so the server support is the thing
 * that must not regress.
 *
 * ## Route parameter names
 *
 * The SPA uses camelCase params (`:orderId`, `:telegramUserId`). The SERVER's route
 * templates are snake_case (`{order_id}`, `{telegram_user_id}`) and must stay that way —
 * §12.1 T8's enumeration test compares them — but that is a server-side spelling and does
 * not reach the browser's URL (contract D3). `useParams()` here returns the camelCase names.
 *
 * `:telegramUserId` is the INTEGER Telegram id, never `users.id`. `UserView` carries both
 * and only the integer is a route key.
 *
 * ## What is NOT here
 *
 * §11.2's table also lists `/chat`, `/chat/:tgId`, `/payments` and `/moderation`. No router
 * on the shipped surface backs any of them — there is no chat, payments or moderation
 * endpoint at all — so routing to them would produce four screens that can only 404. They
 * arrive with their Phase 3 endpoints, and the nav should hide rather than disable them
 * until then (§11.4: role-based HIDING).
 *
 * `/admins` IS here: §11.2 has a row for it and `GET /api/admins` exists. It is OWNER-only
 * (403 with an audit row for everyone else), so its nav entry belongs behind a
 * `PermissionGate` — an operator must not discover their role by clicking.
 */

import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { RootLayout } from "@/app/RootLayout";

/** Every path the console serves, in one place, so a link is never spelled by hand. */
export const ROUTES = {
  live: "/",
  orders: "/orders",
  orderDetail: "/orders/:orderId",
  users: "/users",
  userDetail: "/users/:telegramUserId",
  generations: "/generations",
  nameStrategies: "/generations/names",
  vendors: "/vendors",
  assets: "/assets",
  audit: "/audit",
  retention: "/retention",
  config: "/config",
  admins: "/admins",
  login: "/login",
} as const;

export type RouteName = keyof typeof ROUTES;

/** Build a concrete href. The only sanctioned way to link to a parameterised route. */
export const href = {
  live: (): string => ROUTES.live,
  orders: (): string => ROUTES.orders,
  order: (orderId: string): string => `/orders/${encodeURIComponent(orderId)}`,
  users: (): string => ROUTES.users,
  /** Takes the INTEGER telegram id — `OrderView.telegramUserId`, not the masked string. */
  user: (telegramUserId: number): string => `/users/${encodeURIComponent(String(telegramUserId))}`,
  generations: (): string => ROUTES.generations,
  nameStrategies: (): string => ROUTES.nameStrategies,
  vendors: (): string => ROUTES.vendors,
  assets: (): string => ROUTES.assets,
  audit: (): string => ROUTES.audit,
  retention: (): string => ROUTES.retention,
  config: (): string => ROUTES.config,
  admins: (): string => ROUTES.admins,
  login: (): string => ROUTES.login,
} as const;

export const routeObjects: RouteObject[] = [
  {
    path: ROUTES.login,
    lazy: () => import("@/features/auth/LoginScreen"),
  },
  {
    path: "/",
    Component: RootLayout,
    children: [
      { index: true, lazy: () => import("@/features/live/LiveScreen") },
      { path: "orders", lazy: () => import("@/features/orders/OrdersScreen") },
      { path: "orders/:orderId", lazy: () => import("@/features/orders/OrderDetailScreen") },
      { path: "users", lazy: () => import("@/features/users/UsersScreen") },
      { path: "users/:telegramUserId", lazy: () => import("@/features/users/UserDetailScreen") },
      // `names` is declared before nothing in particular today, but keep literal segments
      // ahead of any future `:attemptId` sibling — React Router ranks literals higher, and
      // relying on that silently is how `/generations/names` becomes an attempt id.
      {
        path: "generations/names",
        lazy: () => import("@/features/generations/NameStrategiesScreen"),
      },
      { path: "generations", lazy: () => import("@/features/generations/GenerationsScreen") },
      // Literal, and declared ahead of any future `:vendorId` sibling for the same reason
      // `generations/names` is: React Router ranks literals higher, but relying on that
      // silently is how `/vendors` starts resolving as a vendor id.
      { path: "vendors", lazy: () => import("@/features/vendors/VendorsScreen") },
      { path: "assets", lazy: () => import("@/features/assets/AssetsScreen") },
      { path: "audit", lazy: () => import("@/features/audit/AuditScreen") },
      { path: "retention", lazy: () => import("@/features/retention/RetentionScreen") },
      { path: "config", lazy: () => import("@/features/config/ConfigScreen") },
      { path: "admins", lazy: () => import("@/features/admins/AdminsScreen") },
      { path: "*", lazy: () => import("@/features/NotFoundScreen") },
    ],
  },
];

export function createRouter() {
  return createBrowserRouter(routeObjects);
}
