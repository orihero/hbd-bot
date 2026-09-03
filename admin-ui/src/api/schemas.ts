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
 *    `hbd.errors` claims the code — render "unknown" and offer no retry. Likewise
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
  draftFieldKeySchema,
  generationKindSchema,
  genreSchema,
  greetingEvidenceSchema,
  languageSchema,
  logLevelSchema,
  nameStrategySchema,
  occasionSchema,
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
 * `hbd/admin/schemas/page.py`. Used by orders, users, attempts and assets.
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
  /** Tri-state: `null` = no `hbd.errors` class claims the code. */
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
});
export type OrderView = z.infer<typeof orderViewSchema>;

export const ordersPageSchema = pageSchema(orderViewSchema);
export type OrdersPage = z.infer<typeof ordersPageSchema>;

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
 * There is deliberately NO `lastSeenAt`. §11.2: the column heading reads **"last order"**
 * until Phase 3 gives `lastSeenAt` a real writer. Use `LAST_ORDER_COLUMN_LABEL`.
 *
 * `id` is the `users.id` PK and is NOT the route key. `/api/users/**` is keyed on
 * `telegramUserId`, the integer.
 */
export const userViewSchema = z.object({
  id: uuidSchema,
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  uiLanguage: languageSchema,
  isBlocked: z.boolean(),
  /** When the FIRST order was created — there is no signup event to date an account from. */
  accountCreatedAt: timestampSchema,
  firstOrderAt: timestampSchema.nullable(),
  lastOrderAt: timestampSchema.nullable(),
  orderCount: z.number().int(),
  paidOrderCount: z.number().int(),
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
});
export type UserDetailView = z.infer<typeof userDetailViewSchema>;

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

/** The window the counts were taken over, echoed so an empty result can name it. */
export const windowViewSchema = z.object({
  from: timestampSchema,
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
/* Audit                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * THE ONE ROLE-DEPENDENT RESPONSE IN THE API.
 *
 * At `AdminRole.ADMIN` the §12.2 cell is `M`, so `reasonText` is `null` while
 * `hasReasonText` may be `true`. Render that as `REASON_WITHHELD_LABEL` — never as "no
 * reason given".
 *
 * Contract D1: `hbd/admin/schemas/audit.py`'s docstring claims a masked response "omits the
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
  newPassword: z.string().min(12).max(256),
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
