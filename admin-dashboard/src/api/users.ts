/**
 * The `/api/users/**` contract, transcribed from
 * `.openpencil-export/users-generations-openapi.json` (produced by `bayram/admin/routers/
 * {users,credits}.py` and `bayram/admin/schemas/{users,credits,orders}.py`).
 *
 * Eight routes: one keyset list, four reads about one person, and three privileged writes.
 *
 * ## Three rules this module encodes, all of them the backend's
 *
 * **`q` searches the Telegram id and NOTHING else.** `UserFilters` (`db/admin/users.py`)
 * refuses a name filter and a phone filter for two different reasons, and refuses a
 * substring search over either for a third: every free-text column this list can reach lives
 * on `user_profiles`, is masked at all four roles, and a `LIKE '%…%'` over it would let an
 * operator with no reveal cell confirm a customer's name three characters at a time — no
 * step-up, no budget unit, no audit row. Matching a substring of the Telegram id discloses
 * nothing, because every row already prints that id in full. **The placeholder, the label
 * and the empty state must say what it searches and must never say "name".**
 *
 * **Everything personal is masked here and nowhere else is it not.** `telegramUsernameMasked`,
 * `firstNameMasked`, `lastNameMasked`, `phoneMasked` are what this wire carries; the
 * plaintext twins exist only as the result of `POST /api/reveal`. They are different fields,
 * so both are modelled and neither substitutes for the other.
 *
 * **`null` is a third value on the credit fields.** `creditBalance`, `lifetimeCreditsGranted`
 * and `allowancePeriod` are `null` when the account has no `credit_accounts` row — a
 * customer nobody has ever charged or granted, who is still owed a full rolling allowance,
 * or one whose `/forget` deleted it. "0 credits" says the opposite of both: that this account
 * has spent everything it had.
 *
 * ## Two numbers about money, and they settle different arguments
 *
 * `user.creditBalance` is the stored column — what the ledger can prove. `creditsProjected`
 * on the detail is what the BOT would tell the customer right now (the balance plus a
 * rolling allowance that is due and not yet minted). An operator handed one of them cannot
 * answer "they say they have three songs and your panel says zero", which is the support
 * ticket the pair exists for. Show both, labelled.
 */

import { z } from "zod";

/*
 * The segment is a DOCUMENT the registry owns, and `src/lib/segmentCodec.ts` owns its type and
 * its codec. Restating either here would be a second, drifting copy of a shape the wizard and
 * this list have to agree on byte for byte — `api/broadcasts.ts` imports the same two for the
 * same reason. Only the direction vocabulary is needed: the token itself travels as a string.
 */
import type { SortDirection } from "@/lib/segmentCodec";

import { request, type ApiResult } from "./client";
import { MAX_GRANT_CREDITS, MIN_GRANT_CREDITS, USERS_PREFIX } from "./constants";
import { orderStateSchema } from "./dashboard";
import {
  appendCountedPage,
  appendEach,
  appendPage,
  appendParam,
  pageMetaSchema,
  queryOf,
  type CountedPageRequest,
  type PageRequest,
} from "./pagination";
import { reasonedRequestSchema } from "./reveal";

export { ORDER_STATE_VALUES, orderStateSchema, type OrderState } from "./dashboard";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from the spec; a new member must be added here first        */
/* -------------------------------------------------------------------------- */

/**
 * `Language`. The customer's UI language on `UserView`, the song's on an order or an
 * attempt. Four members, and `uz_latn`/`uz_cyrl` are two scripts of one language — never
 * collapse them in a filter chip, because the answer set differs.
 */
export const LANGUAGE_VALUES = ["uz_latn", "uz_cyrl", "ru", "en"] as const;
export const languageSchema = z.enum(LANGUAGE_VALUES);
export type Language = z.infer<typeof languageSchema>;

/** `Occasion` — what the song is for. `custom` is the customer's own words, not a preset. */
export const OCCASION_VALUES = [
  "birthday",
  "love",
  "support",
  "prank",
  "holiday",
  "wedding",
  "anniversary",
  "kids",
  "no_occasion",
  "custom",
] as const;
export const occasionSchema = z.enum(OCCASION_VALUES);
export type Occasion = z.infer<typeof occasionSchema>;

/** `Genre`. */
export const GENRE_VALUES = [
  "pop",
  "retro_estrada",
  "hip_hop",
  "rock",
  "acoustic_ballad",
  "dance_electronic",
  "uzbek_pop",
  "uzbek_folk",
  "shashmaqom",
  "jazz_lounge",
] as const;
export const genreSchema = z.enum(GENRE_VALUES);
export type Genre = z.infer<typeof genreSchema>;

/**
 * `OrderLedgerStatus` — where this order stands with the credit ledger. `unmetered` is an
 * order from before the paywall or under an unenforced rail: it is not "free", it is
 * "nothing was ever charged", and the two read differently in a refund conversation.
 */
export const ORDER_LEDGER_STATUS_VALUES = ["unmetered", "pending", "settled", "refunded"] as const;
export const orderLedgerStatusSchema = z.enum(ORDER_LEDGER_STATUS_VALUES);
export type OrderLedgerStatus = z.infer<typeof orderLedgerStatusSchema>;

/** `OrderPaymentRail` — which rail authorised this order. */
export const ORDER_PAYMENT_RAIL_VALUES = ["none", "credits", "unenforced"] as const;
export const orderPaymentRailSchema = z.enum(ORDER_PAYMENT_RAIL_VALUES);
export type OrderPaymentRail = z.infer<typeof orderPaymentRailSchema>;

/** `CreditEntryKind` — what a ledger row DID. `consume` settles a debit and moves nothing. */
export const CREDIT_ENTRY_KIND_VALUES = ["grant", "debit", "refund", "consume"] as const;
export const creditEntryKindSchema = z.enum(CREDIT_ENTRY_KIND_VALUES);
export type CreditEntryKind = z.infer<typeof creditEntryKindSchema>;

/**
 * `CreditReason` — WHY it moved. Finer than `kind`, and the pair is what makes a ledger
 * readable: `admin_grant` is an operator's comp, `signup_allowance` and `period_allowance`
 * are the bot's own, and `stale_settlement` / `unenforced_render` are the two ways a render
 * escaped the gate.
 */
export const CREDIT_REASON_VALUES = [
  "signup_allowance",
  "period_allowance",
  "admin_grant",
  "order_render",
  "order_failed",
  "order_delivered",
  "order_not_delivered",
  "stale_settlement",
  "unenforced_render",
  "topup_purchase",
  "plan_song",
] as const;
export const creditReasonSchema = z.enum(CREDIT_REASON_VALUES);
export type CreditReason = z.infer<typeof creditReasonSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/users                                                              */
/* -------------------------------------------------------------------------- */

/**
 * One row of `/users`. There is deliberately no `lastSeenAt`.
 *
 * `id` is the `users` row UUID and it is the subject a `POST /api/reveal` of a
 * `user_profiles.*` field is taken against — NOT `telegramUserId`, which is what the block,
 * unblock and grant routes key on. Two id spaces, one row; sending the wrong one is a scope
 * mismatch or a reveal of somebody else.
 */
export const userViewSchema = z.object({
  id: z.string().uuid(),
  /** Unmasked, and it must be: every `/users/**` route keys on it. */
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  uiLanguage: languageSchema,
  isBlocked: z.boolean(),
  /** FIRST CONTACT, not the first order — reading it as one understates account age. */
  accountCreatedAt: timestampSchema,
  firstOrderAt: timestampSchema.nullable(),
  lastOrderAt: timestampSchema.nullable(),
  orderCount: z.number().int(),
  paidOrderCount: z.number().int(),
  /**
   * Whether a `user_profiles` row exists. False is "never onboarded" AND "erased by
   * /forget" at once, deliberately: PD-3 deletes the row, so absence IS the erasure record
   * and there is no purge stamp to show beside it.
   */
  isProfilePresent: z.boolean(),
  /** `@G•••`. The handle itself comes only from a reveal of `user_profiles.telegram_username`. */
  telegramUsernameMasked: z.string().nullable(),
  firstNameMasked: z.string().nullable(),
  lastNameMasked: z.string().nullable(),
  /** `•••••42` — no country prefix, by design. */
  phoneMasked: z.string().nullable(),
  phoneSharedAt: timestampSchema.nullable(),
  /** When WE last fetched a picture, never when the customer changed one. */
  avatarFetchedAt: timestampSchema.nullable(),
  hasAvatar: z.boolean(),
  /**
   * `/api/users/{telegramUserId}/avatar`, or `null` when there is nothing to fetch.
   *
   * Built by the ROUTER and handed over, so this SPA never composes an avatar path — which
   * is why there is no `getUserAvatar` fetcher in this module: it is an `<img src>` serving
   * bytes, not JSON, and the `<img onError>` monogram is still required because nothing
   * stat-ed a file to answer `hasAvatar`.
   */
  avatarUrl: z.string().nullable(),
  /** `null` = no `credit_accounts` row. A third value; never render it as `0`. */
  creditBalance: z.number().int().nullable(),
  /** Monotone: every credit ever added, allowances included. Answers "already comped?". */
  lifetimeCreditsGranted: z.number().int().nullable(),
  /** The last rolling-allowance window minted. `null` for no row OR no allowance yet. */
  allowancePeriod: z.number().int().nullable(),
});
export type UserView = z.infer<typeof userViewSchema>;

export const usersPageSchema = z.object({
  items: z.array(userViewSchema),
  meta: pageMetaSchema,
});
export type UsersPage = z.infer<typeof usersPageSchema>;

/** One state with at least one order. States with none are ABSENT, never zero-filled. */
export const orderStateCountSchema = z.object({
  state: orderStateSchema,
  count: z.number().int(),
});
export type OrderStateCount = z.infer<typeof orderStateCountSchema>;

/** `GET /api/users/{telegramUserId}` — the row, plus what it takes to read it in context. */
export const userDetailViewSchema = z.object({
  user: userViewSchema,
  ordersByState: z.array(orderStateCountSchema),
  deliveredOrderCount: z.number().int(),
  failedOrderCount: z.number().int(),
  /**
   * What the bot would tell this customer they have right now: the stored balance plus a
   * rolling allowance that is due and not yet minted. An `int`, never null — "no row" is
   * exactly what a brand-new customer with their whole allowance ahead of them looks like.
   *
   * Only as true as the panel's mirrored `admin_free_allowance_credits` and
   * `admin_settlement_grace_s` are current; when one drifted, this field said 4 to an
   * operator while the customer read 1.
   */
  creditsProjected: z.number().int(),
  /**
   * Debits not yet settled, inside the settlement grace. A render whose worker died holds a
   * credit that neither the balance nor the ledger totals show as spent — this is the only
   * number on the screen that explains why the customer is being refused.
   */
  inFlightRenderCount: z.number().int(),
});
export type UserDetailView = z.infer<typeof userDetailViewSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/users/{telegramUserId}/orders                                      */
/* -------------------------------------------------------------------------- */

/**
 * One of this person's orders.
 *
 * `recipientName` is MASKED (first grapheme cluster), and `isIdentityPurged` /
 * `identityPurgedAt` are why it may be absent: a purged name is not a missing name, and it
 * is not a reveal that could succeed. Render "purged {date}" and offer no unmask.
 */
export const orderViewSchema = z.object({
  id: z.string().uuid(),
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  state: orderStateSchema,
  isPaid: z.boolean(),
  /** The id an operator pastes into `/orders?q=` from a support ticket. */
  correlationId: z.string(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
  deliveredAt: timestampSchema.nullable(),
  /** Our own operator prose plus a code; never a customer's words. */
  failedReason: z.string().nullable(),
  /** `null` = the code is unknown to the taxonomy, NOT "not retryable". */
  isFailedReasonRetryable: z.boolean().nullable(),
  isBriefPresent: z.boolean(),
  /** Masked. Plaintext only via a reveal of `briefs.recipient_name_display`/`_raw`. */
  recipientName: z.string().nullable(),
  isIdentityPurged: z.boolean(),
  identityPurgedAt: timestampSchema.nullable(),
  notePurgedAt: timestampSchema.nullable(),
  occasion: occasionSchema.nullable(),
  genre: genreSchema.nullable(),
  outputLanguage: languageSchema.nullable(),
  assetCount: z.number().int(),
  hasAssets: z.boolean(),
  creditCost: z.number().int(),
  ledgerStatus: orderLedgerStatusSchema,
  paymentRail: orderPaymentRailSchema,
  retryCount: z.number().int(),
});
export type OrderView = z.infer<typeof orderViewSchema>;

export const ordersPageSchema = z.object({
  items: z.array(orderViewSchema),
  meta: pageMetaSchema,
});
export type OrdersPage = z.infer<typeof ordersPageSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/users/{telegramUserId}/credits                                     */
/* -------------------------------------------------------------------------- */

/** One `credit_accounts` row: what the ledger can prove this account holds. */
export const creditAccountViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  /** The STORED column, not the number the customer sees — that is `creditsProjected`. */
  balance: z.number().int(),
  lifetimeGranted: z.number().int(),
  /** `null` until the first allowance lands: "opened but never granted" is its own state. */
  allowancePeriod: z.number().int().nullable(),
});
export type CreditAccountView = z.infer<typeof creditAccountViewSchema>;

/** One movement. Append-only: no row on this wire was ever updated after it was written. */
export const creditLedgerEntryViewSchema = z.object({
  id: z.string().uuid(),
  kind: creditEntryKindSchema,
  reason: creditReasonSchema,
  /** Signed, and the database constrains it to agree with `kind`: `consume` is exactly 0. */
  delta: z.number().int(),
  orderId: z.string().uuid().nullable(),
  /** Which charge attempt for that order — what makes a refunded order chargeable again. */
  generation: z.number().int(),
  idempotencyKey: z.string(),
  /** `admin:{username}` for an operator's grant; `bot`/`pipeline`/`sweep` otherwise. */
  actor: z.string().nullable(),
  createdAt: timestampSchema,
});
export type CreditLedgerEntryView = z.infer<typeof creditLedgerEntryViewSchema>;

/**
 * The balance and one page of its movements.
 *
 * `account` is `null` for a user who has a `users` row and no `credit_accounts` one — never
 * a zeroed object. That is a different fact from a balance of 0 and the two must not render
 * alike.
 */
export const creditLedgerPageSchema = z.object({
  account: creditAccountViewSchema.nullable(),
  items: z.array(creditLedgerEntryViewSchema),
  meta: pageMetaSchema,
});
export type CreditLedgerPage = z.infer<typeof creditLedgerPageSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/users/{telegramUserId}/wizard-state                                */
/* -------------------------------------------------------------------------- */

/**
 * One allowlisted draft key: whether it is there, and how much of it there is.
 *
 * `charCount` is `null` for an absent key and `0` for one present and empty — the
 * distinction that answers "did they type a note and delete it?".
 */
export const draftFieldViewSchema = z.object({
  key: z.string(),
  isPresent: z.boolean(),
  charCount: z.number().int().nullable().default(null),
});
export type DraftFieldView = z.infer<typeof draftFieldViewSchema>;

/**
 * The live FSM session, projected out of Redis. No plaintext at any role, and **no 404**:
 * every account answers, and `isStatePresent: false` is the normal state of everyone not
 * mid-flow right now.
 *
 * An absent state is not proof of nothing: the draft expires on the abandoned-draft clock,
 * so it may simply mean the sweep already happened. `textFields` carries lengths, never
 * text.
 */
export const wizardStateViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  isStatePresent: z.boolean(),
  state: z.string().nullable().default(null),
  sessionId: z.string().nullable().default(null),
  /** Closed-vocabulary choices (occasion, genre, …), key → value. Never free text. */
  choices: z.record(z.string(), z.string()).default({}),
  textFields: z.array(draftFieldViewSchema).default([]),
  /** How many times they rewrote their own lyrics. `null` = not recorded. */
  lyricWrites: z.number().int().nullable().default(null),
});
export type WizardStateView = z.infer<typeof wizardStateViewSchema>;

/* -------------------------------------------------------------------------- */
/* The three writes                                                            */
/* -------------------------------------------------------------------------- */

/**
 * `POST /users/{id}/block` and `/unblock` — a reason and nothing else.
 *
 * Which of the two states is being set is carried by the PATH, because the audit log is
 * queried by equality on `action` and "show me every block this week" must not mean "read
 * every row and look at a field".
 */
export const userBlockRequestSchema = reasonedRequestSchema;
export type UserBlockRequest = z.infer<typeof userBlockRequestSchema>;

/**
 * The result. `changedAt` is the instant the write, the audit row and this response all
 * share — the handler reads its clock once.
 */
export const userBlockResultViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  isBlocked: z.boolean(),
  changedAt: timestampSchema,
});
export type UserBlockResultView = z.infer<typeof userBlockResultViewSchema>;

/**
 * `POST /users/{id}/credits/grant`.
 *
 * The Telegram id is deliberately NOT in the body: it is the path parameter the step-up
 * scope was built from, and a second copy would be a second answer to "who is being
 * credited" — the shape that credits one account under another account's re-authentication.
 *
 * `requestId` is the idempotency key and **must be minted at the call site** — see
 * `newRequestId`.
 */
export const creditGrantRequestSchema = reasonedRequestSchema.extend({
  credits: z.number().int().min(MIN_GRANT_CREDITS).max(MAX_GRANT_CREDITS),
  requestId: z.string().uuid().nullish(),
});
export type CreditGrantRequest = z.infer<typeof creditGrantRequestSchema>;

/**
 * The result, read back FROM the database rather than from arithmetic — so `account.balance`
 * is one the ledger agrees with.
 *
 * `isReplay: true` with `grantedCredits: N` means **nothing moved**: this `requestId` had
 * already been used for this account. Say so; do not print `N` as if it had just been
 * issued. A replay still writes an audit row, because somebody still asked.
 */
export const creditGrantResultViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  /** What the request asked for — NOT what moved, when `isReplay` is true. */
  grantedCredits: z.number().int(),
  isReplay: z.boolean(),
  /** `grant:admin:{telegramUserId}:{requestId}` — scoped to the subject, on purpose. */
  idempotencyKey: z.string(),
  account: creditAccountViewSchema,
});
export type CreditGrantResultView = z.infer<typeof creditGrantResultViewSchema>;

/**
 * A fresh idempotency key for ONE press of the Grant button.
 *
 * **Call it where the operator acts, not inside `grantCredits`.** The whole value of the key
 * is that a RETRY of the same action reuses it: mint it when the confirm dialog opens, keep
 * it in the component's state, and send the same one through the step-up round trip, the
 * network failure and the retry. A key minted inside the fetcher would be new on every call,
 * which turns a retried timeout into a second grant — and two presses of the button are two
 * grants, which is the honest reading of two presses.
 *
 * Conversely, never key it off something coarser than one press (a ticket id, a resubmitted
 * form): the server scopes the key to this account, so a reused `requestId` on a DIFFERENT
 * account is a real grant, but on the SAME account it is a silent no-op reported as
 * `isReplay`.
 *
 * `crypto.randomUUID` needs a secure context, and so do the `__Host-` cookies this panel's
 * session rides on — if it is missing, there is no session to grant credits with.
 */
export function newRequestId(): string {
  return crypto.randomUUID();
}

/* -------------------------------------------------------------------------- */
/* Filters                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * §6.6's filter set. Every field is optional and an omitted one is not sent — absent, `true`
 * and `false` are three different questions on each tri-state.
 */
export interface UsersFilters {
  /**
   * Ask for the bounded count as well. Off by default because it is a second query, and no
   * screen needs it to render the first page. It arrives as the `total`/`isTotalExact` pair.
   */
  readonly withTotal?: boolean;
  /** EXACT `telegram_user_id`, for an id pasted whole. */
  readonly telegramUserId?: number | null;
  /**
   * A SUBSTRING of the Telegram id — and of nothing else. Not a name search and not a phone
   * search; see this module's header for why neither exists. Cap the INPUT at
   * `MAX_SEARCH_CHARS`: an over-long value is a 422 naming the parameter, and truncating it
   * here would hide that behind a page the operator did not ask for.
   */
  readonly q?: string | null;
  /** Tri-state: absent = do not filter. */
  readonly isBlocked?: boolean | null;
  /**
   * Tri-state. `true` is a strictly positive STORED balance; `false` deliberately includes
   * the customer with no `credit_accounts` row at all. Neither reads `creditsProjected`.
   */
  readonly hasBalance?: boolean | null;
  /** REPEATED on the wire: OR within the field, AND across fields. Empty = do not filter. */
  readonly uiLanguage?: readonly Language[];
  /** Account creation, half-open `[from, to)`, RFC 3339. Either end may stand alone. */
  readonly from?: string | null;
  readonly to?: string | null;
  /**
   * The advanced segment, as the base64url document the URL carries — `encodeSegment()`'s
   * output and nothing else.
   *
   * A TOKEN rather than the `Segment` object, because this is what travels on the wire and
   * what a react-query key can hold: two documents that encode the same bytes are one
   * question, and the same string is what `?segment=` puts in the address bar and what
   * `GET /api/segments/preview` counts. It is ANDed with the six chip filters above rather
   * than replacing them — keeping both is what stops this being a breaking change.
   */
  readonly segment?: string | null;
  /**
   * A `SORT_KEYS` member — a NAME the server resolves to an expression, never an expression.
   *
   * Only the registry's `sortable: true` fields are members: `last_activity_at` is filterable
   * and deliberately not sortable, because a sort publishes a total order over identified
   * accounts. Sending an unsortable key is a 422 naming the parameter.
   *
   * It **replaces** the ordering inside `segment`, rather than sitting beside it — one
   * ordering, one source (`build_query`, routers/users.py).
   */
  readonly sort?: string | null;
  /**
   * The direction to read `sort` in. Sent only beside a `sort`: alone it names a direction
   * for an ordering nobody chose, which is a second spelling of the default request.
   */
  readonly sortDir?: SortDirection | null;
}

function usersQuery(filters: UsersFilters, page: PageRequest): string {
  const params = new URLSearchParams();
  // `withTotal` is sent only when asked: the server's default is false, and `withTotal=false`
  // would be a second spelling of the same request — two react-query keys, two log lines.
  if (filters.withTotal === true) params.append("withTotal", "true");
  appendParam(params, "telegramUserId", filters.telegramUserId);
  appendParam(params, "q", filters.q);
  appendParam(params, "isBlocked", filters.isBlocked);
  appendParam(params, "hasBalance", filters.hasBalance);
  appendEach(params, "uiLanguage", filters.uiLanguage);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendParam(params, "segment", filters.segment);
  // `sortDir` rides on `sort` and is never sent without it: the server defaults the direction,
  // so a lone `?sortDir=asc` is the default request under a second spelling — one more cache
  // key and one more line in the request log for a question nobody asked.
  if (filters.sort !== undefined && filters.sort !== null && filters.sort.trim() !== "") {
    appendParam(params, "sort", filters.sort);
    appendParam(params, "sortDir", filters.sortDir);
  }
  appendPage(params, page);
  return queryOf(params);
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const USERS_ENDPOINT = {
  list: "GET /api/users",
  detail: "GET /api/users/{telegramUserId}",
  orders: "GET /api/users/{telegramUserId}/orders",
  credits: "GET /api/users/{telegramUserId}/credits",
  wizardState: "GET /api/users/{telegramUserId}/wizard-state",
  block: "POST /api/users/{telegramUserId}/block",
  unblock: "POST /api/users/{telegramUserId}/unblock",
  grant: "POST /api/users/{telegramUserId}/credits/grant",
} as const;

/** A Telegram id is a positive integer well inside `Number.MAX_SAFE_INTEGER`. */
function userPath(telegramUserId: number): string {
  return `${USERS_PREFIX}/${String(telegramUserId)}`;
}

/** One keyset page of users, newest account first. */
export function listUsers(
  filters: UsersFilters,
  page: PageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<UsersPage>> {
  return request({
    endpoint: USERS_ENDPOINT.list,
    path: `${USERS_PREFIX}${usersQuery(filters, page)}`,
    schema: usersPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** One person's record plus their per-state order breakdown. 404 for an id we hold nothing on. */
export function getUser(
  telegramUserId: number,
  signal?: AbortSignal,
): Promise<ApiResult<UserDetailView>> {
  return request({
    endpoint: USERS_ENDPOINT.detail,
    path: userPath(telegramUserId),
    schema: userDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * This person's orders, newest first.
 *
 * A 404 here means we hold nothing about this id at all — the handler probes for existence
 * precisely so that an unknown id cannot read as "this customer has never ordered".
 */
export function getUserOrders(
  telegramUserId: number,
  page: CountedPageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<OrdersPage>> {
  const params = new URLSearchParams();
  appendCountedPage(params, page);
  return request({
    endpoint: USERS_ENDPOINT.orders,
    path: `${userPath(telegramUserId)}/orders${queryOf(params)}`,
    schema: ordersPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * This account's balance and one page of its movements, newest first.
 *
 * 404 only when neither `credit_accounts` nor `users` has heard of the id. An account row
 * with no `users` row is a real population — `grant` opens one — and answers normally.
 */
export function getUserCredits(
  telegramUserId: number,
  page: CountedPageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<CreditLedgerPage>> {
  const params = new URLSearchParams();
  appendCountedPage(params, page);
  return request({
    endpoint: USERS_ENDPOINT.credits,
    path: `${userPath(telegramUserId)}/credits${queryOf(params)}`,
    schema: creditLedgerPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** The live wizard session, projected. Never 404s; read `isStatePresent`. */
export function getWizardState(
  telegramUserId: number,
  signal?: AbortSignal,
): Promise<ApiResult<WizardStateView>> {
  return request({
    endpoint: USERS_ENDPOINT.wizardState,
    path: `${userPath(telegramUserId)}/wizard-state`,
    schema: wizardStateViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Bar this Telegram account from the bot.
 *
 * Needs a live step-up scoped to `user.block:{telegramUserId}` — the id as bare decimal
 * digits — so expect `STEP_UP_REQUIRED` on the first attempt and drive
 * `POST /api/auth/step-up` from the refusal's details. **There is no 404 and that is the
 * design**: the writer upserts, because the account an operator reaches for this button is
 * often one with no `users` row, and refusing an unknown id would both refuse the common
 * case and make the route an existence oracle for guessable Telegram ids.
 */
export function blockUser(
  telegramUserId: number,
  body: UserBlockRequest,
  signal?: AbortSignal,
): Promise<ApiResult<UserBlockResultView>> {
  return request({
    endpoint: USERS_ENDPOINT.block,
    path: `${userPath(telegramUserId)}/block`,
    method: "POST",
    body,
    schema: userBlockResultViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Lift the bar. A separate route and a separate audit action, for the reason `blockUser`
 * gives. Blocking an already-blocked account is not a conflict — the write is idempotent and
 * answers 200 with the state it set.
 */
export function unblockUser(
  telegramUserId: number,
  body: UserBlockRequest,
  signal?: AbortSignal,
): Promise<ApiResult<UserBlockResultView>> {
  return request({
    endpoint: USERS_ENDPOINT.unblock,
    path: `${userPath(telegramUserId)}/unblock`,
    method: "POST",
    body,
    schema: userBlockResultViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Add credits to one account on an operator's say-so.
 *
 * Needs a live step-up scoped to `credit.grant:{telegramUserId}`. There is no 404: the
 * writer opens an account that has never been metered, which is precisely the customer a
 * goodwill comp is usually for.
 *
 * Pass `body.requestId` from {@link newRequestId}, minted once per press of the button — a
 * retry of the same press must send the same one, and the answer will say `isReplay: true`
 * with nothing moved.
 */
export function grantCredits(
  telegramUserId: number,
  body: CreditGrantRequest,
  signal?: AbortSignal,
): Promise<ApiResult<CreditGrantResultView>> {
  return request({
    endpoint: USERS_ENDPOINT.grant,
    path: `${userPath(telegramUserId)}/credits/grant`,
    method: "POST",
    body,
    schema: creditGrantResultViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
