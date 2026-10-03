/**
 * Runtime configuration endpoints:
 *   - GET /api/config/music-provider
 *   - POST /api/config/music-provider
 *   - GET /api/config/teachers-day
 *   - POST /api/config/teachers-day
 *   - GET /api/config/checkout-rails
 *   - POST /api/config/checkout-rails
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import {
  CONFIG_CHECKOUT_RAILS_PATH,
  CONFIG_MUSIC_PROVIDER_PATH,
  CONFIG_TEACHERS_DAY_PATH,
} from "./constants";
import { reasonedRequestSchema } from "./reveal";

export const musicProviderConfigSchema = z.object({
  activeProvider: z.string(),
  defaultProvider: z.string(),
  availableProviders: z.array(z.string()),
});
export type MusicProviderConfig = z.infer<typeof musicProviderConfigSchema>;

export const setMusicProviderRequestSchema = reasonedRequestSchema.extend({
  provider: z.string().min(1),
});
export type SetMusicProviderRequest = z.infer<typeof setMusicProviderRequestSchema>;

export const teachersDayConfigSchema = z.object({
  enabled: z.boolean(),
  discountPercent: z.number(),
});
export type TeachersDayConfig = z.infer<typeof teachersDayConfigSchema>;

export const setTeachersDayRequestSchema = reasonedRequestSchema.extend({
  enabled: z.boolean(),
});
export type SetTeachersDayRequest = z.infer<typeof setTeachersDayRequestSchema>;

/**
 * The rails the owner's switch can address, in the order the bot offers them. Mirrors
 * `bayram.checkout_rails.SWITCHABLE_RAILS`; the wire carries the name as a plain string so a
 * rail added server-side before this list learns it still renders (under its raw name) rather
 * than failing the whole read as schema drift.
 */
export const SWITCHABLE_RAILS = ["rhmt", "payme", "checkoutuz"] as const;
export type SwitchableRail = (typeof SWITCHABLE_RAILS)[number];

/**
 * One rail as the server sees it (DECISIONS.md D28).
 *
 * - `enabled` is the owner's Redis switch. A missing key reads as `true` — the switch fails
 *   OPEN, exactly like the global pause — so "on" here means "not switched off", not "selling".
 * - `wired` is whether the bot's environment actually composed this rail at its last boot, as
 *   the bot published it. `null` means the admin process could not tell (the bot has not
 *   published since this deploy, or Redis did not answer); it is NOT the same as `false`.
 *
 * A rail sells only when it is wired AND enabled AND checkouts are not globally paused.
 */
export const checkoutRailViewSchema = z.object({
  name: z.string(),
  enabled: z.boolean(),
  wired: z.boolean().nullable(),
});
export type CheckoutRailView = z.infer<typeof checkoutRailViewSchema>;

export const checkoutRailsConfigSchema = z.object({
  rails: z.array(checkoutRailViewSchema),
  /** `false` when the bot's wired-rails record was unreadable; every `wired` is then `null`. */
  wiredKnown: z.boolean(),
});
export type CheckoutRailsConfig = z.infer<typeof checkoutRailsConfigSchema>;

export const setCheckoutRailRequestSchema = reasonedRequestSchema.extend({
  rail: z.enum(SWITCHABLE_RAILS),
  enabled: z.boolean(),
});
export type SetCheckoutRailRequest = z.infer<typeof setCheckoutRailRequestSchema>;

export const CONFIG_ENDPOINT = {
  getMusicProvider: "GET /api/config/music-provider",
  setMusicProvider: "POST /api/config/music-provider",
  getTeachersDay: "GET /api/config/teachers-day",
  setTeachersDay: "POST /api/config/teachers-day",
  getCheckoutRails: "GET /api/config/checkout-rails",
  setCheckoutRail: "POST /api/config/checkout-rails",
} as const;

/** Read the active music provider, default fallback, and allowed providers. */
export function getMusicProviderConfig(
  signal?: AbortSignal,
): Promise<ApiResult<MusicProviderConfig>> {
  return request({
    endpoint: CONFIG_ENDPOINT.getMusicProvider,
    path: CONFIG_MUSIC_PROVIDER_PATH,
    schema: musicProviderConfigSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** Set the active music provider. Restricted to Owner role. */
export function setMusicProviderConfig(
  payload: SetMusicProviderRequest,
  signal?: AbortSignal,
): Promise<ApiResult<MusicProviderConfig>> {
  return request({
    endpoint: CONFIG_ENDPOINT.setMusicProvider,
    path: CONFIG_MUSIC_PROVIDER_PATH,
    method: "POST",
    body: payload,
    schema: musicProviderConfigSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** Read the Teachers' Day feature switch state and discount percentage. */
export function getTeachersDayConfig(
  signal?: AbortSignal,
): Promise<ApiResult<TeachersDayConfig>> {
  return request({
    endpoint: CONFIG_ENDPOINT.getTeachersDay,
    path: CONFIG_TEACHERS_DAY_PATH,
    schema: teachersDayConfigSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** Set the Teachers' Day switch state. Restricted to Owner role. */
export function setTeachersDayConfig(
  payload: SetTeachersDayRequest,
  signal?: AbortSignal,
): Promise<ApiResult<TeachersDayConfig>> {
  return request({
    endpoint: CONFIG_ENDPOINT.setTeachersDay,
    path: CONFIG_TEACHERS_DAY_PATH,
    method: "POST",
    body: payload,
    schema: teachersDayConfigSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** Read every switchable checkout rail: the owner's switch and whether the env wired it. */
export function getCheckoutRails(
  signal?: AbortSignal,
): Promise<ApiResult<CheckoutRailsConfig>> {
  return request({
    endpoint: CONFIG_ENDPOINT.getCheckoutRails,
    path: CONFIG_CHECKOUT_RAILS_PATH,
    schema: checkoutRailsConfigSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Turn one rail's sales on or off. Owner only, reasoned, audited, no step-up. The response is
 * the whole view RE-READ after the write, so the caller renders what is stored, not what was
 * asked for.
 */
export function setCheckoutRail(
  payload: SetCheckoutRailRequest,
  signal?: AbortSignal,
): Promise<ApiResult<CheckoutRailsConfig>> {
  return request({
    endpoint: CONFIG_ENDPOINT.setCheckoutRail,
    path: CONFIG_CHECKOUT_RAILS_PATH,
    method: "POST",
    body: payload,
    schema: checkoutRailsConfigSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
