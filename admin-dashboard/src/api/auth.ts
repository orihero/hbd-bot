/**
 * The auth surface, mirroring the real contract in admin-ui/src/api/{endpoints,schemas}.ts.
 *
 * Three routes, and one thing worth knowing before you build a form against them:
 *
 *   POST /api/auth/login   {username, password}  ->  {mustChangePassword}
 *   GET  /api/auth/me      -> {id, username, role, lastLoginAt, mustChangePassword}
 *   POST /api/auth/logout  -> 204, empty body
 *
 * The identifier is `username`, NOT an email address, and the login body has NO
 * remember/duration field — session lifetime is the server's (`adminSessionTtlS` /
 * `adminSessionIdleTtlS`), not the browser's. A "remember me" checkbox is therefore a
 * local-only convenience (see `state/auth.ts`), and must not be sent.
 *
 * Login's response carries `mustChangePassword` and nothing else — no account payload — so
 * a successful sign-in is followed by `me()` to learn who signed in.
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import {
  AUTH_PREFIX,
  MAX_PASSWORD_CHARS,
  MAX_USERNAME_CHARS,
  MIN_PASSWORD_CHARS,
} from "./constants";

/** `bayram.admin.errors.AdminRole` — four members, value == lowercase name. */
export const ADMIN_ROLE_VALUES = ["owner", "admin", "support", "viewer"] as const;
export const adminRoleSchema = z.enum(ADMIN_ROLE_VALUES);

/**
 * RFC 3339 with a `Z` suffix. Not validated beyond "a string": a stricter regex would turn
 * a timezone-spelling change into a drift banner, and `Date.parse` handles both forms.
 */
const timestampSchema = z.string();

export const loginRequestSchema = z.object({
  username: z.string().min(1).max(MAX_USERNAME_CHARS),
  /** No minimum by design — the bound is on a NEW password, not on the one being checked. */
  password: z.string().min(1).max(MAX_PASSWORD_CHARS),
});
export type LoginRequest = z.infer<typeof loginRequestSchema>;

export const loginResponseSchema = z.object({
  mustChangePassword: z.boolean(),
});
export type LoginResponse = z.infer<typeof loginResponseSchema>;

/** There is deliberately no `displayName`: `admin_users` has no column for one. */
export const meResponseSchema = z.object({
  id: z.string().uuid(),
  username: z.string(),
  role: adminRoleSchema,
  lastLoginAt: timestampSchema.nullable(),
  mustChangePassword: z.boolean(),
});
export type MeResponse = z.infer<typeof meResponseSchema>;

export const passwordChangeRequestSchema = z.object({
  currentPassword: z.string().min(1).max(MAX_PASSWORD_CHARS),
  newPassword: z.string().min(MIN_PASSWORD_CHARS).max(MAX_PASSWORD_CHARS),
});
export type PasswordChangeRequest = z.infer<typeof passwordChangeRequestSchema>;

/** The route templates, as a failure names them. */
export const AUTH_ENDPOINT = {
  login: "POST /api/auth/login",
  me: "GET /api/auth/me",
  logout: "POST /api/auth/logout",
  password: "POST /api/auth/password",
} as const;

/**
 * The only unauthenticated body this API accepts. Needs a matching `Origin` — a 403
 * `ORIGIN_REJECTED` in dev means `BAYRAM_ADMIN_PUBLIC_ORIGIN`, not this call.
 *
 * `LOGIN_RATE_LIMITED` carries a `Retry-After`, which the failure exposes as `retryAfterS`.
 */
export function login(
  body: LoginRequest,
  signal?: AbortSignal,
): Promise<ApiResult<LoginResponse>> {
  return request({
    endpoint: AUTH_ENDPOINT.login,
    path: `${AUTH_PREFIX}/login`,
    method: "POST",
    body,
    schema: loginResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** Who is signed in. A 401 `UNAUTHENTICATED` here is the normal answer for a cold visitor. */
export function me(signal?: AbortSignal): Promise<ApiResult<MeResponse>> {
  return request({
    endpoint: AUTH_ENDPOINT.me,
    path: `${AUTH_PREFIX}/me`,
    schema: meResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * 204 with an empty body. The server clears the cookies; it does not redirect, so the
 * caller drops its own state and navigates to `/login` itself.
 */
export function logout(signal?: AbortSignal): Promise<ApiResult<void>> {
  return request<void>({
    endpoint: AUTH_ENDPOINT.logout,
    path: `${AUTH_PREFIX}/logout`,
    method: "POST",
    body: {},
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Rotate the current password. On success, the server revokes all sessions and issues
 * a fresh session with `must_change_password=False`.
 */
export function changePassword(
  body: PasswordChangeRequest,
  signal?: AbortSignal,
): Promise<ApiResult<LoginResponse>> {
  return request({
    endpoint: AUTH_ENDPOINT.password,
    path: `${AUTH_PREFIX}/password`,
    method: "POST",
    body,
    schema: loginResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
