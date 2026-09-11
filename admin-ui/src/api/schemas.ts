/**
 * A zod schema for every response model on the read-only surface, plus the types inferred
 * from them.
 *
 * Read this before adding one:
 *
 * 1. **Wire names are camelCase, mechanically.** Every model inherits `ApiModel`, which sets
 *    `alias_generator=to_camel`; there is not one snake_case response field and not one
 *    per-field alias override anywhere in this API. Watch the numeric-suffixed names though
 *    — `adminSessionTtlS`, `adminArgon2MemoryKib`, `p50Seconds`, `durationS`, `sha256` — a
 *    hand-written guess gets several of these wrong.
 *
 * 2. **Nothing is omitted.** FastAPI serialises with `response_model_exclude_unset=False`,
 *    so a field with a default still appears carrying `null` / `{}` / `[]`. The single
 *    genuinely-optional key in the whole API is `error.details`, which lives in errors.ts.
 *    That is why every nullable field below is `.nullable()` and NOT `.nullish()`: a missing
 *    key is drift and must be reported as drift.
 *
 * 3. **`.strict()` is deliberately NOT used.** The server may add a field before this bundle
 *    is redeployed; an unknown key is not a data-integrity problem and must not raise a
 *    SCHEMA_DRIFT banner. A missing or wrongly-typed key is, and does.
 *
 * 4. **Three places snake_case survives inside the camelCase envelope**, and each will drift
 *    loudly if missed: `WizardStateView.choices` KEYS, `AuditEntryView.fieldNames` values,
 *    and `DraftFieldView.key`.
 *
 * 5. **Tri-state booleans are `boolean | null` and the null arm is a THIRD state**, never a
 *    falsy second one. `isRetryable`, `isFailedReasonRetryable`: `null` means no class in
 *    `bayram.errors` claims the code — render "unknown" and offer no retry. Likewise
 *    `successRate` is `null` (never `0.0`) when there is no denominator, and
 *    `costUsd`/`latencyMs` are `null` (never `0`) when `isInstrumented` is false.
 */

import { z } from "zod";

import {
  MAX_REASON_REF_CHARS,
  MAX_REASON_TEXT_CHARS,
  MAX_RECORDS_PER_REVEAL,
  MAX_REVEAL_CURSOR_CHARS,
  REASON_REF_PATTERN,
} from "./constants";
import {
  adminEnvironmentSchema,
  adminRoleSchema,
  assetKindSchema,
  auditActionSchema,
  auditOutcomeSchema,
  auditReasonCodeSchema,
  chainProtectionSchema,
  costSourceSchema,
  creditEntryKindSchema,
  creditReasonSchema,
  draftFieldKeySchema,
  generationKindSchema,
  genreSchema,
  greetingEvidenceSchema,
  languageSchema,
  logLevelSchema,
  nameStrategySchema,
  occasionSchema,
  orderLedgerStatusSchema,
  orderPaymentRailSchema,
  orderStateSchema,
  pipelineStageSchema,
  purgeTriggerSchema,
  REVEAL_FIELD_VALUES,
  retentionClassSchema,
  revealFieldSchema,
  revealSubjectTypeSchema,
  scriptSchema,
  stageOutcomeSchema,
  stepUpActionSchema,
  storageReconciliationSchema,
  timelineEventKindSchema,
  timelineSourceSchema,
  vendorOperationSchema,
  vendorSchema,
  voiceGenderSchema,
} from "./enums";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * A UUID, canonical lowercase hyphenated. Kept as `string` — the SPA never constructs one.
 * `z.string().uuid()` rather than a bare string so a route that puts an order id where an
 * attempt id belongs drifts here rather than 404ing three screens later.
 */
export const uuidSchema = z.string().uuid();

/**
 * RFC 3339 with a `Z` SUFFIX — `"2026-09-02T12:00:00Z"`, never a `+00:00` offset spelling.
 * Verified live. Not validated beyond "a string": a stricter regex here would turn a
 * timezone-format change into a drift banner on every screen at once, and `Date.parse`
 * handles both spellings anyway. `src/lib/format.ts` is where it becomes text.
 */
export const timestampSchema = z.string();

/** An ISO date, `"2026-09-02"` — a UTC day, not an instant. */
export const isoDateSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Pagination — TWO envelopes, and they are not interchangeable                */
/* -------------------------------------------------------------------------- */

/**
 * `bayram/admin/schemas/page.py`. Used by orders, users, attempts and assets.
 *
 * All three keys are ALWAYS present. Without `?withTotal=true`, `total` and `isTotalExact`
 * are both `null` and travel as a pair. `{total: 10000, isTotalExact: false}` means
 * "10,000+" — see `TOTAL_COUNT_CAP`.
 *
 * `nextCursor` is `null` at the end of a list and is NEVER `""`.
 */
export const pageMetaSchema = z.object({
  nextCursor: z.string().nullable(),
  total: z.number().int().nullable(),
  isTotalExact: z.boolean().nullable(),
});
export type PageMeta = z.infer<typeof pageMetaSchema>;

/** `{ items, meta }` for any `T`. */
export function pageSchema<T extends z.ZodTypeAny>(item: T) {
  return z.object({ items: z.array(item), meta: pageMetaSchema });
}

export interface Page<T> {
  readonly items: T[];
  readonly meta: PageMeta;
}

/**
 * `/api/audit` alone. It pages on `seq`, has NO `total`/`isTotalExact` and takes NO
 * `withTotal` parameter.
 *
 * The two cursor encodings also differ in base64 padding (page.py keeps `=`, audit strips
 * it), so round-tripping one into the other's endpoint is a 422, not a wrong page.
 */
export const auditPageMetaSchema = z.object({
  nextCursor: z.string().nullable(),
});
export type AuditPageMeta = z.infer<typeof auditPageMetaSchema>;

/* -------------------------------------------------------------------------- */
/* Orders                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * One row of `/api/orders`.
 *
 * `telegramUserId` ships UNMASKED alongside `telegramUserIdMasked` (contract D10). Render
 * the masked string; use the integer only to build a `/users/:telegramUserId` link.
 *
 * `recipientName === null` and `recipientName === MASK` are DIFFERENT FACTS: `null` means
 * the identity was purged (check `identityPurgedAt`), `"•••"` means the stored name was
 * empty.
 */
export const orderViewSchema = z.object({
  id: uuidSchema,
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  state: orderStateSchema,
  isPaid: z.boolean(),
  correlationId: z.string(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
  deliveredAt: timestampSchema.nullable(),
  /** Closed-vocabulary operator triage text, not a customer's words. */
  failedReason: z.string().nullable(),
  /** Tri-state: `null` = no `bayram.errors` class claims the code. */
  isFailedReasonRetryable: z.boolean().nullable(),
  isBriefPresent: z.boolean(),
  recipientName: z.string().nullable(),
  isIdentityPurged: z.boolean(),
  identityPurgedAt: timestampSchema.nullable(),
  notePurgedAt: timestampSchema.nullable(),
  occasion: occasionSchema.nullable(),
  genre: genreSchema.nullable(),
  outputLanguage: languageSchema.nullable(),
  assetCount: z.number().int(),
  hasAssets: z.boolean(),

  /* -- financials, derived from `credit_ledger` ---------------------------- */

  /**
   * Credits standing against this order **right now** — `-SUM(delta)` over its ledger rows,
   * the same net position the authorisation gate reads. A refunded order is `0`, not `1`,
   * and that is not history being rounded off: net 0 is precisely what makes it chargeable
   * again on its next attempt. Label it "credits charged", NEVER "credits spent".
   */
  creditCost: z.number().int(),
  ledgerStatus: orderLedgerStatusSchema,
  paymentRail: orderPaymentRailSchema,
  /**
   * Rows in `generation_attempts` for this order. **Two caveats a UI must render rather than
   * swallow.** It counts ATTEMPTS, so one clean render is `1` and not `0` — it is not
   * "retries beyond the first". And today every row it can count is a name-verification
   * verdict: no vendor-render attempt writer exists in `src/`, so a delivered order whose
   * three songs the vendor rendered reports `0` here unless verification also ran. Label it
   * "attempts recorded", never "render retries", and say what a `0` can mean.
   */
  retryCount: z.number().int(),
});
export type OrderView = z.infer<typeof orderViewSchema>;

export const ordersPageSchema = pageSchema(orderViewSchema);
export type OrdersPage = z.infer<typeof ordersPageSchema>;

/** One segment of the Orders hub's distribution bar. */
export const orderStateTotalViewSchema = z.object({
  state: orderStateSchema,
  count: z.number().int(),
});
export type OrderStateTotalView = z.infer<typeof orderStateTotalViewSchema>;

/**
 * `GET /api/orders/state-counts` — per-state totals for the caller's WHOLE filter set.
 *
 * Every `OrderState` is present, in enum declaration order, with a count that may be `0`.
 * That is the opposite of `UserDetailView.ordersByState`, which omits states nobody reached,
 * and they are two schemas on purpose: a stacked bar whose segments appear and disappear as
 * data arrives is a bar that cannot be read.
 *
 * `total` is the sum of the segments and is **exact** — not `TOTAL_COUNT_CAP`-bounded the way
 * the list's `meta.total` is. The two therefore disagree above ten thousand rows, and they
 * should: label the bar from `total` here, never from the list's capped meta.
 */
export const orderStateCountsSchema = z.object({
  counts: z.array(orderStateTotalViewSchema),
  total: z.number().int(),
});
export type OrderStateCountsView = z.infer<typeof orderStateCountsSchema>;

/** `occasion`, `genre`, `vocalGender` are NOT nullable here, unlike on `OrderView`. */
export const briefWireViewSchema = z.object({
  id: uuidSchema,
  occasion: occasionSchema,
  genre: genreSchema,
  vocalGender: voiceGenderSchema,
  uiLanguage: languageSchema,
  outputLanguage: languageSchema,
  eventDay: z.number().int().nullable(),
  eventMonth: z.number().int().nullable(),
  recipientName: z.string().nullable(),
  recipientScript: scriptSchema.nullable(),
  recipientLanguage: languageSchema.nullable(),
  candidateCount: z.number().int(),
  identityExpiresAt: timestampSchema,
  identityPurgedAt: timestampSchema.nullable(),
  isIdentityPurged: z.boolean(),
  /** The note's LENGTH only. The note itself needs `POST /reveal`, which is Phase 2. */
  noteChars: z.number().int().nullable(),
  hasApprovedLyrics: z.boolean(),
  noteExpiresAt: timestampSchema,
  notePurgedAt: timestampSchema.nullable(),
  isNotePurged: z.boolean(),
});
export type BriefWireView = z.infer<typeof briefWireViewSchema>;

/* -------------------------------------------------------------------------- */
/* Assets                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * There is deliberately no `isFilePresent` and no `payload` (the lyric sheet).
 *
 * `sizeBytes` is on the wire and is ALWAYS 0 today — §11.2 says storage size is not shown on
 * `/assets` for exactly that reason. `isStorageKeyRecorded: false` means the bytes will
 * outlive the row, which is the fact that page is actually for.
 */
export const assetWireViewSchema = z.object({
  id: uuidSchema,
  orderId: uuidSchema,
  kind: assetKindSchema,
  variantIndex: z.number().int(),
  mime: z.string(),
  sizeBytes: z.number().int(),
  durationS: z.number(),
  sha256: z.string(),
  loudnessLufs: z.number().nullable(),
  personaId: z.string().nullable(),
  isStorageKeyRecorded: z.boolean(),
  hasTelegramFileId: z.boolean(),
  nameCandidateStrategy: nameStrategySchema.nullable(),
  nameCandidateRank: z.number().int().nullable(),
  retentionClass: retentionClassSchema,
  expiresAt: timestampSchema,
  createdAt: timestampSchema,
});
export type AssetWireView = z.infer<typeof assetWireViewSchema>;

export const assetsPageSchema = pageSchema(assetWireViewSchema);
export type AssetsPage = z.infer<typeof assetsPageSchema>;

/**
 * `GET /api/assets/{id}/text` — the lyric sheet, as JSON.
 *
 * **Never `text/plain`.** §12.1 T7: a lyric sheet served as its own content type is a
 * sniffable document under the operator's own origin. The server renders it into a JSON
 * field instead, so it arrives as data and reaches the DOM as a text node.
 *
 * Reading it is a REVEAL, charged and audited on every request — there is no ten-minute
 * dedupe window here the way there is on `/stream`, because one request returns the whole
 * sheet and a second read is a second disclosure. Do not prefetch it, do not put it in a
 * hover card, and do not let a `staleTime` turn a re-render into a second charge.
 */
export const assetTextViewSchema = z.object({
  assetId: uuidSchema,
  text: z.string(),
});
export type AssetTextView = z.infer<typeof assetTextViewSchema>;

/* -------------------------------------------------------------------------- */
/* Generation attempts — the render ledger                                     */
/* -------------------------------------------------------------------------- */

/**
 * The ONLY projection of `generation_attempts` in the codebase: identical bytes at
 * `/api/generations`, `/api/generations/{id}`, `/api/orders/{id}/attempts` and inside
 * `OrderDetailView.attempts`.
 *
 * `costUsd` and `latencyMs` are `null` — never `0` — when `isInstrumented` is false, which
 * is every row in production today. Render "not instrumented", never `$0.00 / 0 ms`.
 *
 * `nameCandidate` is MASKED (`"G•••"`); `errorMessage` is OUR operator prose and never a
 * customer's words; `sttTranscriptChars` is a length, not a transcript.
 */
export const attemptWireViewSchema = z.object({
  id: uuidSchema,
  /** `null` = orphaned: a pre-order preview, or the order was deleted. */
  orderId: uuidSchema.nullable(),
  kind: generationKindSchema,
  sequence: z.number().int(),
  attempt: z.number().int(),
  provider: z.string().nullable(),
  providerRemoteId: z.string().nullable(),
  language: languageSchema.nullable(),
  isSuccess: z.boolean(),
  isOrphaned: z.boolean(),

  nameCandidateStrategy: nameStrategySchema.nullable(),
  nameCandidateRank: z.number().int().nullable(),
  isNameVerified: z.boolean().nullable(),
  matchConfidence: z.number().nullable(),

  nameCandidate: z.string().nullable(),
  identityPurgedAt: timestampSchema.nullable(),
  sttTranscriptChars: z.number().int().nullable(),
  textPurgedAt: timestampSchema.nullable(),

  errorCode: z.string().nullable(),
  errorMessage: z.string().nullable(),
  /** Tri-state. `null` = no class claims the code: render "unknown", offer no retry. */
  isRetryable: z.boolean().nullable(),

  costUsd: z.number().nullable(),
  costSource: z.string().nullable(),
  latencyMs: z.number().int().nullable(),
  isInstrumented: z.boolean(),
  createdAt: timestampSchema,
});
export type AttemptWireView = z.infer<typeof attemptWireViewSchema>;

export const attemptsPageSchema = pageSchema(attemptWireViewSchema);
export type AttemptsPage = z.infer<typeof attemptsPageSchema>;

/* -------------------------------------------------------------------------- */
/* Stage plan and timeline                                                     */
/* -------------------------------------------------------------------------- */

export const stageStatusViewSchema = z.object({
  stage: pipelineStageSchema,
  outcome: stageOutcomeSchema,
  attemptCount: z.number().int(),
  failedAttemptCount: z.number().int(),
  errorCode: z.string().nullable(),
  isRetryable: z.boolean().nullable(),
  isGreetingStage: z.boolean(),
});
export type StageStatusView = z.infer<typeof stageStatusViewSchema>;

/**
 * `stages` carries ONE ENTRY PER `PipelineStage`, in `STAGE_ORDER` — all eleven, always.
 * `scheduledStageCount` is how many this deployment actually plans (9 by default, because
 * `greetings_per_kit=0` is shipped); the unplanned remainder is GHOSTED, not dropped.
 *
 * `isInferred` is ALWAYS `true`. Render it as a caption on the timeline, not as a debug
 * flag — the plan is reconstructed from attempt rows, and seven stages write none.
 */
export const stagePlanViewSchema = z.object({
  stages: z.array(stageStatusViewSchema),
  greetingEvidence: greetingEvidenceSchema,
  isConclusive: z.boolean(),
  scheduledStageCount: z.number().int(),
  isInferred: z.boolean(),
});
export type StagePlanView = z.infer<typeof stagePlanViewSchema>;

export const timelineEventViewSchema = z.object({
  at: timestampSchema,
  kind: timelineEventKindSchema,
  source: timelineSourceSchema,
  isInferred: z.boolean(),
  /** Closed vocabulary, never free text. */
  label: z.string().nullable(),
  referenceId: uuidSchema.nullable(),
});
export type TimelineEventView = z.infer<typeof timelineEventViewSchema>;

/**
 * `unavailableSources` is why the merged timeline renders a `sources` legend: an absent
 * section must read as "not enabled in this deployment", never as "nothing happened".
 */
export const timelineViewSchema = z.object({
  events: z.array(timelineEventViewSchema),
  availableSources: z.array(timelineSourceSchema),
  unavailableSources: z.array(timelineSourceSchema),
});
export type TimelineView = z.infer<typeof timelineViewSchema>;

/** `assets` and `attempts` are ALL of them, unpaged. */
export const orderDetailViewSchema = z.object({
  order: orderViewSchema,
  brief: briefWireViewSchema.nullable(),
  assets: z.array(assetWireViewSchema),
  attempts: z.array(attemptWireViewSchema),
  stagePlan: stagePlanViewSchema,
  timeline: timelineViewSchema,
});
export type OrderDetailView = z.infer<typeof orderDetailViewSchema>;

/* -------------------------------------------------------------------------- */
/* Users                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * There is deliberately NO `lastSeenAt`, and the column heading reads **"last order"** for a
 * reason that will keep being true: this schema carries no `lastSeenAt` field at all. The
 * older reason — "until Phase 3 gives `lastSeenAt` a real writer" — is dead;
 * `db/credits.py::touch` writes `users.last_seen_at` on every inbound update already. What is
 * missing is the wire field, not the writer, so labelling the column "last seen" would name a
 * value this object cannot supply. Use `LAST_ORDER_COLUMN_LABEL`.
 *
 * `id` is the `users.id` PK and is NOT the route key. `/api/users/**` is keyed on
 * `telegramUserId`, the integer. `id` IS what a `subjectType: "user"` reveal is keyed on,
 * because `revealRequestSchema.subjectId` is a UUID.
 *
 * The nine profile fields below arrive together or not at all. Every one is `.nullable()` and
 * therefore a REQUIRED property: a server that has not shipped them yet raises `SCHEMA_DRIFT`
 * rather than quietly rendering a page with no phone, no name and no photo, which is why this
 * bundle deploys strictly after the API.
 */
export const userViewSchema = z.object({
  id: uuidSchema,
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  uiLanguage: languageSchema,
  isBlocked: z.boolean(),
  /**
   * Whether a `user_profiles` row exists at all.
   *
   * There is deliberately no purge stamp beside it. `/forget` DELETEs the row outright, so
   * absence IS the erasure record — and it is the same absence as an account that has never
   * answered the language question. The panel must not claim to tell those apart; see
   * `features/users/profile.ts`, which is the one place that distinction is worded.
   */
  isProfilePresent: z.boolean(),
  /** `"@G•••"` — masked at the response boundary, `@` re-prefixed. Never the raw handle. */
  telegramUsernameMasked: z.string().nullable(),
  firstNameMasked: z.string().nullable(),
  lastNameMasked: z.string().nullable(),
  /**
   * `"•••••42"` — the last two digits and nothing else.
   *
   * There is NO clear country prefix, on purpose: a fixed `+998` head would publish two
   * subscriber digits of `+79161234567` while hiding its country code, which is the mask
   * leaking what it claims to protect. A non-E.164 value is never echoed — it masks whole.
   * The plaintext is on this wire at NO role, OWNER included; `POST /api/reveal` with
   * `user_profiles.phone_e164` is the one path, and it costs a step-up and an audit row.
   */
  phoneMasked: z.string().nullable(),
  phoneSharedAt: timestampSchema.nullable(),
  /** `true` when a photo was captured. Drives a FACT, not the `<img>` — see `avatarUrl`. */
  hasAvatar: z.boolean(),
  /**
   * `"/api/users/770000123/avatar"`, or `null` when there is nothing to fetch.
   *
   * The URL and the presence decision are ONE value so they cannot disagree: a client-built
   * path plus a separate boolean can point an `<img>` at a 404. Same-origin, so the `__Host-`
   * session cookie travels with the subresource and no token appears in a URL — the same
   * property `pathAssetStream` documents for `<audio src>`. `img-src 'self'` permits it.
   */
  avatarUrl: z.string().nullable(),
  /** When the bytes were last fetched from Telegram. `null` with `hasAvatar: false`. */
  avatarFetchedAt: timestampSchema.nullable(),
  /**
   * When the `users` row was created.
   *
   * That is now FIRST CONTACT, not the first order: `users_sql.ensure_user` writes a row when
   * somebody answers the language question, and `db/credits.py::touch` upserts one on every
   * inbound update. Rows that predate onboarding were still born at their first order, so this
   * column means two things depending on the row's age — say so wherever it is labelled.
   */
  accountCreatedAt: timestampSchema,
  firstOrderAt: timestampSchema.nullable(),
  lastOrderAt: timestampSchema.nullable(),
  orderCount: z.number().int(),
  paidOrderCount: z.number().int(),

  /* -- credits, LEFT-JOINED from `credit_accounts` ------------------------- */

  /**
   * `credit_accounts.balance`, or `null` when this account has no row there.
   *
   * **`null` is a THIRD value and must never render as "0".** The column is `NOT NULL` in the
   * schema, so a null here has exactly one cause: no row. That happens for a customer nobody
   * has ever charged or granted — the row is opened by the first movement, so everybody who
   * has talked to the bot and not confirmed an order is in this state, and they are still
   * owed a full rolling allowance the moment they do — and for a customer whose `/forget`
   * deleted it. "0 credits" says the opposite of both: it says this account has spent
   * everything it had.
   *
   * There is deliberately no `isCreditAccountPresent` beside these three, and the asymmetry
   * with `isProfilePresent` is not an oversight: every profile column is independently
   * nullable so none of them can carry presence, whereas the balance can carry it alone.
   */
  creditBalance: z.number().int().nullable(),
  /**
   * Every credit ever added, allowances included — the number that answers "has this account
   * already been comped?" without reading the ledger. `null` for the one reason
   * `creditBalance` is.
   */
  lifetimeCreditsGranted: z.number().int().nullable(),
  /**
   * The last rolling-allowance window this account was minted for, as a period INDEX (not a
   * timestamp). `null` for TWO reasons — no account row, or an account that has never had an
   * allowance — and `creditBalance` is what tells them apart.
   */
  allowancePeriod: z.number().int().nullable(),
});
export type UserView = z.infer<typeof userViewSchema>;

export const usersPageSchema = pageSchema(userViewSchema);
export type UsersPage = z.infer<typeof usersPageSchema>;

export const orderStateCountSchema = z.object({
  state: orderStateSchema,
  count: z.number().int(),
});
export type OrderStateCount = z.infer<typeof orderStateCountSchema>;

/** States with ZERO orders are ABSENT from `ordersByState`, not zero-filled. */
export const userDetailViewSchema = z.object({
  user: userViewSchema,
  ordersByState: z.array(orderStateCountSchema),
  deliveredOrderCount: z.number().int(),
  failedOrderCount: z.number().int(),
  /**
   * What the BOT would tell this customer they have right now — the stored balance plus a
   * rolling allowance that is due and not yet minted, from the same read the bot's own gate
   * calls.
   *
   * It sits BESIDE `user.creditBalance` rather than instead of it, because the two settle
   * different arguments: the stored column is what the ledger can prove, and this is what the
   * customer was shown on the Confirm screen. Render the pair, or an operator cannot answer
   * "they say they have three songs and your panel says zero".
   *
   * An `int` and NOT `int | null`: it is computed for every account, row or no row, and "no
   * row" is exactly what a brand-new customer with their whole allowance ahead of them looks
   * like. So a `creditBalance` of `null` beside a `creditsProjected` of 3 is the normal
   * reading, not a contradiction.
   */
  creditsProjected: z.number().int(),
  /**
   * Debits this account has not settled yet, inside the settlement grace window. A render
   * whose worker died holds a credit that neither the balance nor the ledger's totals show as
   * spent, and this is the only number on the screen that explains why the customer is being
   * refused.
   */
  inFlightRenderCount: z.number().int(),
});
export type UserDetailView = z.infer<typeof userDetailViewSchema>;

/* -------------------------------------------------------------------------- */
/* User actions — block / unblock (`bayram.admin.schemas.actions`)                */
/* -------------------------------------------------------------------------- */

/**
 * `POST /api/users/{telegram_user_id}/block` and `/unblock` — ONE body, TWO routes.
 *
 * Which state is being set is carried by the PATH and never by a boolean in the body: a
 * single `POST /block {"isBlocked": false}` would be an unblock that audits as a block, and
 * the audit row is the only durable record of which one happened.
 *
 * `reasonCode` has no default and no optional arm — an action without a reason is a 422 — for
 * the same §12.4 reason `revealRequestSchema` states. `reasonText` is control-stripped and
 * capped server-side and lives on the audit log's 90-day reason clock; whitespace-only text is
 * no text.
 */
export const userBlockRequestSchema = z.object({
  reasonCode: auditReasonCodeSchema,
  reasonRef: z.string().regex(REASON_REF_PATTERN).max(MAX_REASON_REF_CHARS).optional(),
  reasonText: z.string().max(MAX_REASON_TEXT_CHARS).optional(),
});
export type UserBlockRequest = z.infer<typeof userBlockRequestSchema>;

/**
 * What the account looks like after the action, and when it was recorded.
 *
 * It echoes `isBlocked` rather than answering 204, because the two routes are idempotent by
 * design: an operator who pressed Block on an already-blocked account has to see that the
 * state is what they wanted, and pressing it twice is information — it still writes an audit
 * row.
 *
 * `changedAt` is the instant the ACTION was recorded, not "when this account was first
 * blocked". The `users` row carries no such column.
 */
export const userBlockResultViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  isBlocked: z.boolean(),
  changedAt: timestampSchema,
});
export type UserBlockResultView = z.infer<typeof userBlockResultViewSchema>;

/* -------------------------------------------------------------------------- */
/* Credits — the entitlement ledger (`bayram.admin.schemas.credits`)              */
/* -------------------------------------------------------------------------- */

/**
 * The most credits ONE call may add. A credit is one render and one render is real vendor
 * spend, so this is a blast radius rather than a validation nicety: the number it exists to
 * refuse is the `1000` that was meant to be `10`. `credits` is `ge=1` server-side too.
 */
export const MIN_GRANT_CREDITS = 1;
export const MAX_GRANT_CREDITS = 100;

/**
 * One `credit_accounts` row: what the ledger can prove this account holds.
 *
 * **Nothing on this wire is masked and nothing here is reveal-gated**, which is a property of
 * the table rather than a relaxation: `credit_accounts` and `credit_ledger` hold a Telegram
 * id, two closed enums, integers and machine-built keys — no free text — so there is nothing
 * for `POST /reveal` to gate. The Telegram id still travels beside its own mask, so a screen
 * that renders masked ids everywhere else does not have to special-case this one.
 *
 * `balance` is the stored column and NOT the number the customer sees; that is
 * `UserDetailView.creditsProjected`, and the pair is what settles a support argument.
 */
export const creditAccountViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  balance: z.number().int(),
  /** Monotone, never decremented — allowances included. */
  lifetimeGranted: z.number().int(),
  /** A period INDEX, `null` until the first allowance lands. */
  allowancePeriod: z.number().int().nullable(),
});
export type CreditAccountView = z.infer<typeof creditAccountViewSchema>;

/**
 * One movement. Append-only: no row on this wire was ever updated after it was written.
 *
 * `delta` is SIGNED and is constrained at the database to agree with `kind` — positive for a
 * grant or refund, negative for a debit, exactly `0` for a consume. A consume settles a debit
 * without moving anything, so a table that colours by sign must give it a third treatment
 * rather than drawing it as a zero-value grant.
 *
 * `actor` is published verbatim, `admin:{username}` included, and that is the column's whole
 * purpose: "was this account comped, and by whom?" is the question this screen is open for.
 * Do not mask it — an answer of `admin:•••` sends the operator to the audit log for every
 * grant. It is `null` for movements the pipeline wrote.
 */
export const creditLedgerEntryViewSchema = z.object({
  id: uuidSchema,
  kind: creditEntryKindSchema,
  reason: creditReasonSchema,
  delta: z.number().int(),
  orderId: uuidSchema.nullable(),
  /** Which charge attempt for that order, bumped by each refund — what makes a refunded
   *  order chargeable again rather than free. */
  generation: z.number().int(),
  idempotencyKey: z.string(),
  actor: z.string().nullable(),
  createdAt: timestampSchema,
});
export type CreditLedgerEntryView = z.infer<typeof creditLedgerEntryViewSchema>;

/**
 * `GET /api/users/{telegram_user_id}/credits`.
 *
 * **`account === null` is not an empty ledger and must not render as one.** It means
 * `credit_accounts` holds no row, which happens for two populations an operator must be able
 * to tell apart from "spent everything": a customer who has never been charged or granted
 * anything, and a customer whose `/forget` deleted the row. In the second case `items` may
 * still be non-empty — erasure keeps the rows and nulls their Telegram id — and in the first
 * it is empty. Render "never metered", never a zeroed account object.
 *
 * The route DOES 404, but only for an id neither `credit_accounts` nor `users` has heard of.
 */
export const creditLedgerPageSchema = z.object({
  account: creditAccountViewSchema.nullable(),
  items: z.array(creditLedgerEntryViewSchema),
  meta: pageMetaSchema,
});
export type CreditLedgerPage = z.infer<typeof creditLedgerPageSchema>;

/**
 * `POST /api/users/{telegram_user_id}/credits/grant` — how many, why, and optionally under
 * which key.
 *
 * The Telegram id is **not** in the body. It is the path parameter the step-up scope was
 * built from, and a second copy here would be a second answer to "who is being credited".
 *
 * `requestId` is the idempotency key's variable half, and it must be minted **per press of
 * the button**: the server keys `grant:admin:{telegramUserId}:{requestId}`, so the same
 * `requestId` sent twice for one account tops it up once and answers `isReplay: true`. Omit it
 * and the server mints one, which makes two presses two grants — the honest reading of two
 * presses. Anything coarser than one press (a ticket id, a resubmitted form) silently issues
 * nothing the second time.
 */
export const creditGrantRequestSchema = z.object({
  credits: z.number().int().min(MIN_GRANT_CREDITS).max(MAX_GRANT_CREDITS),
  requestId: uuidSchema.optional(),
  reasonCode: auditReasonCodeSchema,
  reasonRef: z.string().regex(REASON_REF_PATTERN).max(MAX_REASON_REF_CHARS).optional(),
  reasonText: z.string().max(MAX_REASON_TEXT_CHARS).optional(),
});
export type CreditGrantRequest = z.infer<typeof creditGrantRequestSchema>;

/**
 * What the grant did, and what the account looks like now.
 *
 * `isReplay` is the field that makes a retry safe to interpret: `true` means this exact
 * `requestId` had already been granted and **nothing moved**, so a client that retried a
 * timed-out request can tell "it worked the first time" from "it worked just now" without
 * guessing from the balance. Surface it — a success toast that says the same thing either way
 * is how an operator grants twice.
 *
 * `grantedCredits` is what THIS call asked for; on a replay the ledger row is authoritative
 * and the ledger page beside it shows it. `account` is read back inside the same transaction
 * after the write, so it is a reading rather than the request's arithmetic.
 *
 * There is **no 404** on this route: a grant opens the account it credits, which is precisely
 * the customer a goodwill comp is usually for.
 */
export const creditGrantResultViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  grantedCredits: z.number().int(),
  isReplay: z.boolean(),
  idempotencyKey: z.string(),
  account: creditAccountViewSchema,
});
export type CreditGrantResultView = z.infer<typeof creditGrantResultViewSchema>;

/* -------------------------------------------------------------------------- */
/* Wizard state — Redis, not the database                                      */
/* -------------------------------------------------------------------------- */

/** `charCount`: `null` = the key is absent; `0` = present and empty. Different facts. */
export const draftFieldViewSchema = z.object({
  key: draftFieldKeySchema,
  isPresent: z.boolean(),
  charCount: z.number().int().nullable(),
});
export type DraftFieldView = z.infer<typeof draftFieldViewSchema>;

/**
 * `choices` has SNAKE_CASE KEYS (`ui_language`, `occasion`, `genre`, `vocal_gender`,
 * `output_language`) and bare-`string` values: they come from Redis JSON that a
 * possibly-older build wrote, so `z.nativeEnum` here would drift on a stale draft.
 *
 * `textFields` is always exactly three entries, in the order note, recipient, lyrics.
 *
 * This endpoint NEVER 404s: the person it exists for is stuck mid-wizard and has no `users`
 * row at all, by construction.
 */
export const wizardStateViewSchema = z.object({
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  isStatePresent: z.boolean(),
  /** aiogram's raw state string, e.g. `"Wizard:note"`. */
  state: z.string().nullable(),
  sessionId: z.string().nullable(),
  choices: z.record(z.string(), z.string()),
  textFields: z.array(draftFieldViewSchema),
  lyricWrites: z.number().int().nullable(),
});
export type WizardStateView = z.infer<typeof wizardStateViewSchema>;

/* -------------------------------------------------------------------------- */
/* Admin accounts                                                              */
/* -------------------------------------------------------------------------- */

/** `passwordHash` is ABSENT, not masked. `username` is in the clear: staff, not customers. */
export const adminAccountViewSchema = z.object({
  id: uuidSchema,
  username: z.string(),
  role: adminRoleSchema,
  isActive: z.boolean(),
  mustChangePassword: z.boolean(),
  lastLoginAt: timestampSchema.nullable(),
  passwordChangedAt: timestampSchema,
  createdAt: timestampSchema,
});
export type AdminAccountView = z.infer<typeof adminAccountViewSchema>;

/** No `meta`: a bounded whole-table read, oldest account first. Deactivated accounts ARE
 *  in the list (`isActive: false`) — grey them, do not omit them. */
export const adminRosterResponseSchema = z.object({
  items: z.array(adminAccountViewSchema),
});
export type AdminRosterResponse = z.infer<typeof adminRosterResponseSchema>;

/* -------------------------------------------------------------------------- */
/* Retention                                                                   */
/* -------------------------------------------------------------------------- */

/** Every key required, none defaulted. `total` is a Python `@property` and is NOT on the
 *  wire — the sum arrives as `totalRowsAffected` / `totalRowsPastExpiry`. */
export const sweepCountsSchema = z.object({
  assetsDeleted: z.number().int(),
  briefNotesPurged: z.number().int(),
  briefIdentitiesPurged: z.number().int(),
  attemptIdentitiesPurged: z.number().int(),
  attemptTranscriptsPurged: z.number().int(),
  nameRecordsDeleted: z.number().int(),
  abandonedOrdersDeleted: z.number().int(),
  auditReasonsPurged: z.number().int(),
  auditRowsDeleted: z.number().int(),
  adminSessionsDeleted: z.number().int(),
  purgeRunsDeleted: z.number().int(),
  /** The `vendor_usage` telemetry table's own 400-day cutoff — not a customer-data clock. */
  vendorUsageDeleted: z.number().int(),
});
export type SweepCounts = z.infer<typeof sweepCountsSchema>;

export const storageTallySchema = z.object({
  keysReturned: z.number().int(),
  keysDeleted: z.number().int(),
  deleteFailures: z.number().int(),
  /** `max(0, keysReturned - keysDeleted)`. */
  unreconciledKeys: z.number().int(),
  reconciliation: storageReconciliationSchema,
});
export type StorageTally = z.infer<typeof storageTallySchema>;

export const purgeRunViewSchema = z.object({
  id: uuidSchema,
  ranAt: timestampSchema,
  trigger: purgeTriggerSchema,
  /** Set for `"manual"` runs only. */
  triggeredByUsername: z.string().nullable(),
  durationMs: z.number().int(),
  counts: sweepCountsSchema,
  totalRowsAffected: z.number().int(),
  storage: storageTallySchema,
  batchSize: z.number().int(),
  /** The sweep came back full: run it again. */
  isBatchFull: z.boolean(),
  /** Set when the sweep returned `Err`. */
  errorCode: z.string().nullable(),
});
export type PurgeRunView = z.infer<typeof purgeRunViewSchema>;

/**
 * There is deliberately no `isOverdue`.
 *
 * `storageReconciliation: null` is NOT `"nothing_to_reconcile"` — it means no run has ever
 * happened, and a scheduler that never fired must not light a clean badge.
 *
 * `rowsPastExpiry` is counted LIVE, not read off any run.
 */
export const retentionResponseSchema = z.object({
  /** Newest first. */
  runs: z.array(purgeRunViewSchema),
  rowsPastExpiry: sweepCountsSchema,
  totalRowsPastExpiry: z.number().int(),
  lastRunAt: timestampSchema.nullable(),
  hasEverRun: z.boolean(),
  isBatchFull: z.boolean(),
  storageReconciliation: storageReconciliationSchema.nullable(),
});
export type RetentionResponse = z.infer<typeof retentionResponseSchema>;

/* -------------------------------------------------------------------------- */
/* Ops and metrics                                                             */
/* -------------------------------------------------------------------------- */

/**
 * `successRate` is `null` when `terminalCount === 0` — NEVER `0.0` for "no data". A
 * dashboard that renders 0% because nothing has finished yet is the most alarming wrong
 * number on the screen.
 *
 * `inFlight` sits OUTSIDE the `successRate` denominator; `terminalCount` is the denominator.
 */
export const deliveryViewSchema = z.object({
  total: z.number().int(),
  delivered: z.number().int(),
  failed: z.number().int(),
  cancelled: z.number().int(),
  inFlight: z.number().int(),
  terminalCount: z.number().int(),
  successRate: z.number().nullable(),
});
export type DeliveryView = z.infer<typeof deliveryViewSchema>;

export const latencyViewSchema = z.object({
  sampleCount: z.number().int(),
  p50Seconds: z.number().nullable(),
  p95Seconds: z.number().nullable(),
});
export type LatencyView = z.infer<typeof latencyViewSchema>;

/** `errorCode: null` groups failures whose writer recorded no code. `isRetryable` is
 *  tri-state: `null` → render "unknown" and offer no retry. */
export const failureViewSchema = z.object({
  errorCode: z.string().nullable(),
  count: z.number().int(),
  share: z.number(),
  isRetryable: z.boolean().nullable(),
});
export type FailureView = z.infer<typeof failureViewSchema>;

/**
 * What this deployment can actually answer. Every one of these is `false` in production
 * today except as noted — branch on them and render "not instrumented" rather than a zero.
 * There is NO cost figure anywhere in the pulse.
 */
export const capabilitiesViewSchema = z.object({
  isCostTelemetry: z.boolean(),
  isLatencyTelemetry: z.boolean(),
  isAssetStorageKeyRecorded: z.boolean(),
  isChatCapture: z.boolean(),
  isPaymentLedger: z.boolean(),
  isStateTransitionLog: z.boolean(),
  /**
   * EIGHT keys since `vendor_usage` shipped, and the last two are a PAIR that answers two
   * different questions an operator would otherwise conflate.
   *
   * `isVendorUsage` is "does a `vendor_usage` row exist at all" — a writer probe, window
   * ignored. False means no worker in this deployment records vendor calls: tokens, calls
   * and spend are UNMEASURED, and every figure on `/vendors` would be an absence dressed as
   * a zero.
   *
   * `isVendorCost` is "does a row with a non-null `cost_usd` exist". It can be false while
   * `isVendorUsage` is true, and out of the box WHICH legs are priced is uneven rather than
   * uniformly absent: `bayram/config.py` ships `music_usd_per_minute` at `0.15`, so a music
   * render is priced from that placeholder rate and reports `costSource: "estimated"`, while
   * `elevenlabs_usd_per_character` and all four token rates ship at `0.0`, so speech,
   * transcription and every LLM call are recorded UNPRICED until an operator sets a rate. A
   * deployment that has recorded calls but not yet rendered music therefore reads
   * `isVendorCost: false` with plenty on the board. "Instrumented but nothing priced" and
   * "not instrumented" have different remedies — set a rate, versus deploy a writer — so
   * they are different flags.
   *
   * Both are measured by row probes rather than declared from settings, for the reason the
   * whole block exists: a configuration that claims a capability the data does not have is
   * how a zero becomes a number somebody believes.
   */
  isVendorUsage: z.boolean(),
  isVendorCost: z.boolean(),
});
export type CapabilitiesView = z.infer<typeof capabilitiesViewSchema>;

/** The one consolidated dashboard read (§11.5). Takes NO window parameters. */
export const pulseViewSchema = z.object({
  delivery: deliveryViewSchema,
  latency: latencyViewSchema,
  failures: z.array(failureViewSchema),
  capabilities: capabilitiesViewSchema,
});
export type PulseView = z.infer<typeof pulseViewSchema>;

/** A day with NO orders is ABSENT from the series, not zero-filled. The caller that chose
 *  the range fills the gaps for rendering. */
export const ordersPerDayViewSchema = z.object({
  day: isoDateSchema,
  total: z.number().int(),
  delivered: z.number().int(),
  failed: z.number().int(),
  paid: z.number().int(),
});
export type OrdersPerDayView = z.infer<typeof ordersPerDayViewSchema>;

/** `attempts` counts only rows where verification actually ran. */
export const strategyOutcomeViewSchema = z.object({
  strategy: nameStrategySchema,
  attempts: z.number().int(),
  verified: z.number().int(),
  verificationRate: z.number(),
});
export type StrategyOutcomeView = z.infer<typeof strategyOutcomeViewSchema>;

/* -------------------------------------------------------------------------- */
/* Name analytics — the whole of `/generations/names`                          */
/* -------------------------------------------------------------------------- */

/**
 * One bar of the similarity histogram, half-open `[from, to)` — the top bucket closes at 1.
 *
 * `from` is the ONE explicit alias in this API: it is a Python keyword, so the server field
 * is `from_` and the SPA's name wins. The edges are exact IEEE doubles (`i/bucketCount`), so
 * they are bit-identical to what the client-side bucketing produced before the server took
 * the job over.
 */
export const similarityBucketViewSchema = z.object({
  from: z.number(),
  to: z.number(),
  count: z.number().int(),
});
export type SimilarityBucketView = z.infer<typeof similarityBucketViewSchema>;

/**
 * The window the counts were taken over, echoed so an empty result can name it.
 *
 * **`from` is nullable and `to` is not**, and the asymmetry is the server's whole contract
 * for a one-sided range (`bayram.admin.schemas.dashboard.WindowView`). `?to=Y` with no lower
 * bound counted everything ever recorded up to `Y`, and there is no instant to echo for the
 * start — an epoch would be a timestamp the operator never chose, rendered as though they
 * had. `?from=X` always has an upper bound to echo, because `resolve_window` resolved it to
 * the moment the request was served.
 *
 * The SPA spelled `from` non-nullable until `/vendors` shipped; that was drift, not a
 * narrower contract, and a genuinely open-ended window would have raised SCHEMA_DRIFT on
 * `/generations/names` rather than rendering the em dash `formatTimestamp(null)` gives.
 */
export const windowViewSchema = z.object({
  from: timestampSchema.nullable(),
  to: timestampSchema,
});
export type WindowView = z.infer<typeof windowViewSchema>;

/**
 * One strategy's row in the bake-off, with its own distribution.
 *
 * A structural SUPERSET of `StrategyOutcomeView`, deliberately: `strategy`, `attempts`,
 * `verified` and `verificationRate` are identical, so the bake-off chart takes either.
 *
 * `verificationRate` is a plain number here and nullable at the top level, and that is not
 * an inconsistency — a strategy row exists only if it had attempts in the window, so it
 * always has a denominator. A strategy with nothing in the window is ABSENT from the array
 * rather than present at zero, and the chart renders "no attempts" from the gap.
 */
export const strategyAnalysisViewSchema = z.object({
  strategy: nameStrategySchema,
  attempts: z.number().int(),
  verified: z.number().int(),
  verificationRate: z.number(),
  scored: z.number().int(),
  /** `null` exactly when `threshold` is — never zero. See `nameAnalyticsViewSchema`. */
  nearThreshold: z.number().int().nullable(),
  buckets: z.array(similarityBucketViewSchema),
});
export type StrategyAnalysisView = z.infer<typeof strategyAnalysisViewSchema>;

/**
 * `GET /api/metrics/name-analytics` — bake-off, distribution and the cliff count, over ONE
 * window and ONE population.
 *
 * Three fields decide what the screen is allowed to say:
 *
 * - **`threshold` and `nearThreshold` are `null` TOGETHER.** The worker owns
 *   `name_match_min_similarity`; the panel knows it only if the deployment published it.
 *   Null means "this deployment publishes no threshold" — never zero, and never a default
 *   drawn on the one chart whose job is to argue about where the marker belongs.
 * - **`hasRecordedAttempts` is what makes `attempts: 0` readable.** It is a
 *   window-IGNORING probe, so it separates "nothing in the range you chose" (§11.4
 *   empty-FILTERED, which has a remedy — widen the window) from "verification has never run
 *   here" (empty-VIRGIN, which does not). A zero cannot say which.
 * - **`verificationRate` is `null` at the top level** when nothing was verified: no
 *   denominator, no rate. Not `0`.
 *
 * `thresholdBand` and `bucketCount` are on the wire so no consumer restates them: the
 * caption under the cliff count reads the band from the server rather than hard-coding 0.05.
 */
export const nameAnalyticsViewSchema = z.object({
  window: windowViewSchema.nullable(),
  threshold: z.number().nullable(),
  thresholdBand: z.number(),
  bucketCount: z.number().int(),
  attempts: z.number().int(),
  verified: z.number().int(),
  verificationRate: z.number().nullable(),
  scored: z.number().int(),
  nearThreshold: z.number().int().nullable(),
  hasRecordedAttempts: z.boolean(),
  strategies: z.array(strategyAnalysisViewSchema),
  buckets: z.array(similarityBucketViewSchema),
});
export type NameAnalyticsView = z.infer<typeof nameAnalyticsViewSchema>;

/** Bare JSON arrays, no envelope at all. */
export const ordersPerDaySeriesSchema = z.array(ordersPerDayViewSchema);
export const failureSeriesSchema = z.array(failureViewSchema);
export const strategyOutcomeSeriesSchema = z.array(strategyOutcomeViewSchema);

/* -------------------------------------------------------------------------- */
/* Vendor usage — `/vendors`                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One (vendor, operation, modelId) group of `vendor_usage`.
 *
 * **Every quantity here is `number | null` and the null arm is a THIRD state.** Each one is
 * a SQL `SUM()` over a NULLABLE column with no default, so a group in which nobody measured
 * that unit comes back `null` rather than `0` — and the distinction is the reason the table
 * exists. `promptTokens: null` on a music group means a music call has no tokens; `0` would
 * mean the vendor was asked to complete nothing. `billedCharacters: null` on a chat group
 * means the same for characters. Neither may render as a digit.
 *
 * `costUsd` and `costSource` travel TOGETHER (the database enforces it with
 * `ck_vendor_usage_cost_carries_its_source`), and `costUsd: null` means **not priced here**,
 * never "free": the call was made, and this deployment has no rate for the leg it used.
 *
 * `costedCalls` is what keeps a partial total from reading as a complete one. `costUsd` sums
 * only the rows that carry a cost, so a group of 100 calls of which 12 were priced reports
 * the 12 calls' money and says so. Rendering the sum without the count would tell an
 * operator that 100 calls cost that much.
 *
 * `successRate` is `null` when `calls === 0`, on the same rule as everywhere else in this
 * API: no denominator, no rate.
 */
export const vendorUsageRollupViewSchema = z.object({
  vendor: vendorSchema,
  operation: vendorOperationSchema,
  /** The vendor's OWN model id (`music_v2`, `google/gemma-4-31b-it:free`) — not our enum.
   *  Render it verbatim; `humaniseEnum` would mangle a name we do not own. */
  modelId: z.string().nullable(),
  calls: z.number().int(),
  successes: z.number().int(),
  failures: z.number().int(),
  successRate: z.number().nullable(),
  promptTokens: z.number().int().nullable(),
  completionTokens: z.number().int().nullable(),
  totalTokens: z.number().int().nullable(),
  billedCharacters: z.number().int().nullable(),
  audioMs: z.number().int().nullable(),
  costUsd: z.number().nullable(),
  /** `"mixed"` when the group priced its legs more than one way; `null` when none of them
   *  carried a cost at all. */
  costSource: costSourceSchema.nullable(),
  costedCalls: z.number().int(),
  avgLatencyMs: z.number().int().nullable(),
  maxLatencyMs: z.number().int().nullable(),
});
export type VendorUsageRollupView = z.infer<typeof vendorUsageRollupViewSchema>;

/**
 * The same sums over the whole window, in one row.
 *
 * Not derivable from `rows` in the browser, and deliberately not derived there: summing a
 * column of nulls in JavaScript yields `0` unless every call site remembers not to, which is
 * precisely the mistake this response shape refuses to make possible.
 */
export const vendorUsageTotalsViewSchema = z.object({
  calls: z.number().int(),
  successes: z.number().int(),
  failures: z.number().int(),
  successRate: z.number().nullable(),
  costUsd: z.number().nullable(),
  costedCalls: z.number().int(),
  totalTokens: z.number().int().nullable(),
  billedCharacters: z.number().int().nullable(),
  audioMs: z.number().int().nullable(),
  avgLatencyMs: z.number().int().nullable(),
});
export type VendorUsageTotalsView = z.infer<typeof vendorUsageTotalsViewSchema>;

/**
 * `GET /api/metrics/vendor-usage` — what each vendor was asked to do, and what it cost.
 *
 * THREE booleans, because "no numbers on this screen" has three different causes and only
 * one of them has a remedy the operator can reach for:
 *
 *  - `isInstrumented: false` — no `vendor_usage` row exists anywhere. Window IGNORED, by
 *    design: widening the range cannot conjure a writer. Empty-VIRGIN.
 *  - `isInstrumented && !hasRowsInWindow` — rows exist, none in the range chosen.
 *    Empty-FILTERED, whose remedy is the time picker.
 *  - `isCostPriced: false` — calls are recorded and not one of them carried a cost, so every
 *    money cell is `null`. The volume figures are real and the money column says "not
 *    priced". Window IGNORED for the same reason as the first. This is NOT the same claim as
 *    "no rate is configured": the music leg ships priced from a placeholder rate (see
 *    `capabilitiesViewSchema.isVendorCost`), so a deployment reads false here until a call
 *    actually uses a leg it has a rate for.
 *
 * A single zero could stand for any of the three, which is why none of them is a zero.
 */
export const vendorUsageResponseSchema = z.object({
  window: windowViewSchema.nullable(),
  isInstrumented: z.boolean(),
  isCostPriced: z.boolean(),
  hasRowsInWindow: z.boolean(),
  totals: vendorUsageTotalsViewSchema,
  /** One entry per (vendor, operation, modelId), calls DESC then vendor/operation/modelId
   *  ASC. Ordered server-side and never re-sorted here: a client-side sort over a grouped
   *  aggregate would silently disagree with the endpoint's own tie-breaks. */
  rows: z.array(vendorUsageRollupViewSchema),
});
export type VendorUsageResponse = z.infer<typeof vendorUsageResponseSchema>;

/** One (day, vendor) pair. A pair with no calls is ABSENT from the array, never zero-filled
 *  — the chart draws the gap rather than a measured nothing. */
export const vendorUsagePerDayViewSchema = z.object({
  day: isoDateSchema,
  vendor: vendorSchema,
  calls: z.number().int(),
  /** `null` when nothing that day was priced. Not `0`. */
  costUsd: z.number().nullable(),
  costedCalls: z.number().int(),
});
export type VendorUsagePerDayView = z.infer<typeof vendorUsagePerDayViewSchema>;

/** One (vendor, errorCode) group over FAILED calls only. `share` is that code's share of
 *  that vendor's failures in the window, so the shares sum to 1 per vendor and not overall.
 *  `errorCode: null` groups failures whose writer recorded no code — still a group. */
export const vendorErrorViewSchema = z.object({
  vendor: vendorSchema,
  errorCode: z.string().nullable(),
  count: z.number().int(),
  share: z.number(),
});
export type VendorErrorView = z.infer<typeof vendorErrorViewSchema>;

/** Bare JSON arrays, like every other metrics series. */
export const vendorUsagePerDaySeriesSchema = z.array(vendorUsagePerDayViewSchema);
export const vendorErrorSeriesSchema = z.array(vendorErrorViewSchema);

/* -------------------------------------------------------------------------- */
/* Audit                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * THE ONE ROLE-DEPENDENT RESPONSE IN THE API.
 *
 * At `AdminRole.ADMIN` the §12.2 cell is `M`, so `reasonText` is `null` while
 * `hasReasonText` may be `true`. Render that as `REASON_WITHHELD_LABEL` — never as "no
 * reason given".
 *
 * Contract D1: `bayram/admin/schemas/audit.py`'s docstring claims a masked response "omits the
 * field entirely". IT DOES NOT — `to_view` passes `reason_text=None` explicitly and
 * `exclude_unset` is off, so the wire carries `"reasonText": null`. Branch on
 * `hasReasonText`, never on key presence.
 *
 * `fieldNames` is an array of SNAKE_CASE DATABASE COLUMN NAMES (e.g. `"password_hash"`) —
 * the one array of snake_case strings inside the camelCase envelope.
 *
 * `chainHmac` is safe to publish: it cannot be recomputed without the key.
 */
export const auditEntryViewSchema = z.object({
  seq: z.number().int(),
  id: uuidSchema,
  at: timestampSchema,
  actorId: uuidSchema.nullable(),
  actorUsername: z.string(),
  actorRole: adminRoleSchema,
  action: auditActionSchema,
  subjectType: z.string(),
  subjectId: z.string().nullable(),
  fieldNames: z.array(z.string()).nullable(),
  recordCount: z.number().int().nullable(),
  reasonCode: auditReasonCodeSchema,
  reasonRef: z.string().nullable(),
  hasReasonText: z.boolean(),
  reasonText: z.string().nullable(),
  outcome: auditOutcomeSchema,
  errorCode: z.string().nullable(),
  correlationId: z.string().nullable(),
  ip: z.string().nullable(),
  configVersion: z.number().int().nullable(),
  chainHmac: z.string(),
});
export type AuditEntryView = z.infer<typeof auditEntryViewSchema>;

export const auditPageSchema = z.object({
  items: z.array(auditEntryViewSchema),
  meta: auditPageMetaSchema,
});
export type AuditPage = z.infer<typeof auditPageSchema>;

/**
 * A clean `ok: true` with `isComplete: false` is NOT a clean answer over the whole table —
 * the walk hit its row ceiling. Render both facts or neither.
 *
 * `truncationPoints` are seqs below which rows were deleted ON PURPOSE (retention), so a
 * gap there is not a break.
 */
export const chainVerifyResponseSchema = z.object({
  ok: z.boolean(),
  firstBreakSeq: z.number().int().nullable(),
  chainProtection: chainProtectionSchema,
  checkedRows: z.number().int(),
  lastSeq: z.number().int().nullable(),
  isComplete: z.boolean(),
  truncationPoints: z.array(z.number().int()),
});
export type ChainVerifyResponse = z.infer<typeof chainVerifyResponseSchema>;

/* -------------------------------------------------------------------------- */
/* Config — the admin PROCESS's own settings, not the bot's runtime config     */
/* -------------------------------------------------------------------------- */

/**
 * `databaseUrl`, `redisUrl`, `adminAuditHmacKey`, `adminProbeToken` and `adminAuditDsn` are
 * ABSENT IN EVERY FORM — not masked, absent. What is here is where the DSNs point, never
 * what they authenticate with.
 *
 * Mind the camelCase of the numeric-suffixed names; several are not what a guess produces.
 */
export const configViewSchema = z.object({
  // runtime
  environment: adminEnvironmentSchema,
  logLevel: logLevelSchema,
  isDebug: z.boolean(),
  isProduction: z.boolean(),

  // the panel
  adminEnabled: z.boolean(),
  adminConfigEnabled: z.boolean(),
  adminHost: z.string(),
  adminPort: z.number().int(),
  adminPublicOrigin: z.string(),
  isCookieSecure: z.boolean(),

  // sessions and step-up
  adminSessionTtlS: z.number().int(),
  adminSessionIdleTtlS: z.number().int(),
  adminStepUpGraceSeconds: z.number().int(),

  // argon2id
  adminArgon2TimeCost: z.number().int(),
  adminArgon2MemoryKib: z.number().int(),
  adminArgon2Parallelism: z.number().int(),

  // client IP derivation
  adminTrustedProxyHops: z.number().int(),
  adminTrustedProxyCidrs: z.array(z.string()),

  // reveal budgets
  adminRevealRecordsPerHour: z.number().int(),
  adminRevealConversationsPerDay: z.number().int(),

  // derived
  databaseHost: z.string().nullable(),
  databasePort: z.number().int().nullable(),
  redisHost: z.string().nullable(),
  redisPort: z.number().int().nullable(),
  isAuditDsnConfigured: z.boolean(),
  isProbeTokenConfigured: z.boolean(),
});
export type ConfigView = z.infer<typeof configViewSchema>;

/* -------------------------------------------------------------------------- */
/* Auth and health                                                             */
/* -------------------------------------------------------------------------- */

/** There is deliberately no `displayName` — §6.3 lists one, `admin_users` has no column. */
export const meResponseSchema = z.object({
  id: uuidSchema,
  username: z.string(),
  role: adminRoleSchema,
  lastLoginAt: timestampSchema.nullable(),
  mustChangePassword: z.boolean(),
});
export type MeResponse = z.infer<typeof meResponseSchema>;

export const loginResponseSchema = z.object({
  mustChangePassword: z.boolean(),
});
export type LoginResponse = z.infer<typeof loginResponseSchema>;

/**
 * Note the asymmetry with the request: the request's `scope` is a bare `StepUpAction`; the
 * response's `scope` is the COMPOSED grant, `"<action>:<subjectId>"`.
 *
 * `expiresAt - grantedAt` is zero for `"user.purge"` and `"config.write"` — do not assume a
 * window (see `ZERO_GRACE_STEP_UP_ACTIONS`).
 */
export const stepUpResponseSchema = z.object({
  scope: z.string(),
  grantedAt: timestampSchema,
  expiresAt: timestampSchema,
});
export type StepUpResponse = z.infer<typeof stepUpResponseSchema>;

/**
 * `/readyz` is the only response on the surface not produced by a pydantic model, and the
 * only one whose SHAPE depends on authorisation rather than on role (contract D8).
 *
 * Unauthorised callers get a constant `{status: "ok"}` whatever the deployment is doing.
 * The detailed arm is tried first so an authorised probe is not silently flattened.
 */
export const readyzDetailedSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  database: z.boolean(),
  redis: z.boolean(),
  /** `null` until Phase 7 publishes one. */
  configVersion: z.number().int().nullable(),
});
export type ReadyzDetailed = z.infer<typeof readyzDetailedSchema>;

export const readyzPublicSchema = z.object({ status: z.literal("ok") });
export type ReadyzPublic = z.infer<typeof readyzPublicSchema>;

export const readyzResponseSchema = z.union([readyzDetailedSchema, readyzPublicSchema]);
export type ReadyzResponse = z.infer<typeof readyzResponseSchema>;

/* -------------------------------------------------------------------------- */
/* Request bodies — the only three the API accepts                             */
/* -------------------------------------------------------------------------- */

/**
 * `extra="forbid"` applies to request bodies: an unexpected key is a 422, not a silently
 * ignored field. These schemas are what a form validates against BEFORE the round trip.
 */
export const loginRequestSchema = z.object({
  username: z.string().min(1).max(64),
  /** No minimum length by design — the bound is on the NEW password, not on an old one. */
  password: z.string().min(1).max(256),
});
export type LoginRequest = z.infer<typeof loginRequestSchema>;

/** `currentPassword` is required even on the forced-rotation path. */
export const passwordChangeRequestSchema = z.object({
  currentPassword: z.string().min(1).max(256),
  newPassword: z.string().min(8).max(256),
});
export type PasswordChangeRequest = z.infer<typeof passwordChangeRequestSchema>;

/** A `subjectId` that would not fit the composed scope is a 422, never truncated: a
 *  truncated scope is a WIDER grant. */
export const stepUpRequestSchema = z.object({
  password: z.string().min(1).max(256),
  /** The ACTION only, e.g. `"user.purge"` — never the composed `"action:subject"` pair. */
  scope: stepUpActionSchema,
  subjectId: z.string().min(1).max(96),
});
export type StepUpRequest = z.infer<typeof stepUpRequestSchema>;

/* -------------------------------------------------------------------------- */
/* The reveal — POST /api/reveal (§12.3)                                       */
/* -------------------------------------------------------------------------- */

/**
 * `RevealBudgetView` — what this reveal cost and what is left, for `RevealBudgetMeter`.
 *
 * **`*Remaining` is `null` when that counter was not touched, and `null` is not zero.** A
 * single-record reveal never reads the daily conversation budget, so it comes back `null`; a
 * meter that rendered "0 left" for "not asked" would stop an operator doing legitimate work.
 */
export const revealBudgetViewSchema = z.object({
  recordsCharged: z.number().int(),
  recordsRemaining: z.number().int().nullable(),
  conversationsCharged: z.number().int(),
  conversationsRemaining: z.number().int().nullable(),
});
export type RevealBudgetView = z.infer<typeof revealBudgetViewSchema>;

/**
 * One record's plaintext, byte-for-byte as it is stored.
 *
 * `fields` is keyed by `RevealField` VALUE (`"briefs.note"`), and the values are whatever the
 * column holds — a string for the text columns, a JSON array or object for
 * `recipient_candidates`, and `null` when the column is NULL. `z.unknown()` rather than
 * `z.string().nullable()` is deliberate: narrowing here would turn the candidates column into
 * a SCHEMA_DRIFT banner on the screen whose whole job is to show it.
 *
 * **`null` means the column is NULL — purged or never written. It is never a mask and never
 * `""`.** The two purge stamps travel with every record because "no name" and "name erased on
 * schedule on 2026-05-14" are different facts (§12.3), and a reveal that rendered them
 * identically could not answer the question a data-subject request asks.
 */
export const revealedRecordSchema = z.object({
  recordId: uuidSchema,
  createdAt: timestampSchema,
  fields: z.record(z.string(), z.unknown()),
  identityPurgedAt: timestampSchema.nullable(),
  textPurgedAt: timestampSchema.nullable(),
});
export type RevealedRecord = z.infer<typeof revealedRecordSchema>;

/**
 * Plaintext for the named fields only — never the whole object.
 *
 * `recordCount` is the number **charged and audited**, which is the page size the reveal was
 * authorised to return rather than the number of rows it found: an empty result cost a
 * step-up, a budget charge and an audit row, and a budget that let a miss cost nothing would
 * be a budget an operator could probe with.
 *
 * `nextCursor` is a POSITION, never a licence: continuing costs a fresh `POST /reveal`, with
 * its own step-up check, its own charge and its own audit row.
 */
export const revealResponseSchema = z.object({
  subjectType: revealSubjectTypeSchema,
  subjectId: uuidSchema,
  revealedAt: timestampSchema,
  reasonCode: auditReasonCodeSchema,
  recordCount: z.number().int(),
  revealedFields: z.array(revealFieldSchema),
  records: z.array(revealedRecordSchema),
  nextCursor: z.string().nullable(),
  budget: revealBudgetViewSchema,
});
export type RevealResponse = z.infer<typeof revealResponseSchema>;

/**
 * §12.3's body. The FOURTH request body this API accepts.
 *
 * `reasonCode` has no default and no optional arm — that is the whole of "a reveal without a
 * `reasonCode` is a 422", and it is why `RevealDialog` withholds its confirm button until one
 * is chosen rather than letting the server say so.
 *
 * The three refusals the server's model validator makes, restated so a form can refuse first:
 * `fields` must be distinct (a field revealed twice is audited twice), every field must share
 * one `RevealShape` (one `recordCount` cannot describe two shapes), and `limit`/`cursor` are
 * refused on a single-record reveal (a page control on something with no pages is how a caller
 * learns to expect one).
 */
export const revealRequestSchema = z.object({
  subjectType: revealSubjectTypeSchema,
  subjectId: uuidSchema,
  fields: z.array(revealFieldSchema).min(1).max(REVEAL_FIELD_VALUES.length),
  reasonCode: auditReasonCodeSchema,
  reasonRef: z.string().regex(REASON_REF_PATTERN).max(MAX_REASON_REF_CHARS).optional(),
  reasonText: z.string().max(MAX_REASON_TEXT_CHARS).optional(),
  limit: z.number().int().min(1).max(MAX_RECORDS_PER_REVEAL).optional(),
  cursor: z.string().max(MAX_REVEAL_CURSOR_CHARS).optional(),
});
export type RevealRequest = z.infer<typeof revealRequestSchema>;
