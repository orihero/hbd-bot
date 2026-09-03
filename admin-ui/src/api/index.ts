/**
 * The API barrel. Screens and components import from `@/api` and never reach past it.
 *
 * `fetch` is called in exactly one file (`client.ts`) and an ESLint rule bans naming it
 * anywhere else. Everything here returns `ApiResult<T>` and never throws.
 */

export * from "./constants";
export * from "./enums";
export * from "./errors";
export * from "./schemas";
export {
  buildQueryString,
  readCsrfToken,
  request,
  get,
  post,
  postNoContent,
  apiPath,
  type CallOptions,
  type QueryParams,
  type QueryValue,
  type RequestOptions,
} from "./client";
export * from "./endpoints";
export * from "./stream";
