/**
 * Every closed vocabulary the API emits, as a zod enum plus the inferred TS union plus the
 * ordered value tuple.
 *
 * Three conventions, applied without exception:
 *
 *  - `xSchema` is the zod schema, `X` is the type, `X_VALUES` is the tuple in DECLARATION
 *    order. Declaration order is render order for `PIPELINE_STAGE_VALUES` and for
 *    `ORDER_STATE_VALUES`; a `.sort()` on either is a bug, and `.sort()` on user content is
 *    banned outright (see eslint.config.js).
 *  - The wire value is a `StrEnum`'s VALUE, which is not always its member name.
 *    `AuditAction` is dotted and abbreviated (`login.limited`, not `LOGIN_RATE_LIMITED`);
 *    `ChainProtection` contains `+` and `-`.
 *  - `AdminRole`'s third member is `"admin"`. The plan's draft called it `OPERATOR`; the
 *    shipped value is `"admin"`.
 */

import { z } from "zod";

/* -------------------------------------------------------------------------- */
/* Domain — bayram.contracts, bayram.db.enums                                        */
/* -------------------------------------------------------------------------- */

export const ORDER_STATE_VALUES = [
  "draft",
  "brief_ready",
  "lyrics_ready",
  "authorized",
  "generating",
  "delivered",
  "failed",
  "cancelled",
] as const;
export const orderStateSchema = z.enum(ORDER_STATE_VALUES);
export type OrderState = z.infer<typeof orderStateSchema>;

/**
 * The three states an order detail screen polls at 3s for (§11.5). `held_for_review` is in
 * §11.5's prose but is NOT an `OrderState` member on this build — the shipped enum has eight
 * members and no held state, so the poll condition is these two.
 */
export const IN_FLIGHT_ORDER_STATES: readonly OrderState[] = ["authorized", "generating"];

export const GENERATION_KIND_VALUES = [
  "song",
  "song_inpaint",
  "greeting",
  "lyrics",
  "name_preview",
  "name_verification",
  "cover",
] as const;
export const generationKindSchema = z.enum(GENERATION_KIND_VALUES);
export type GenerationKind = z.infer<typeof generationKindSchema>;

export const ASSET_KIND_VALUES = ["song", "greeting", "lyric_sheet", "cover"] as const;
export const assetKindSchema = z.enum(ASSET_KIND_VALUES);
export type AssetKind = z.infer<typeof assetKindSchema>;

export const LANGUAGE_VALUES = ["uz_latn", "uz_cyrl", "ru", "en"] as const;
export const languageSchema = z.enum(LANGUAGE_VALUES);
export type Language = z.infer<typeof languageSchema>;

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

export const VOICE_GENDER_VALUES = ["female", "male", "duet", "any"] as const;
export const voiceGenderSchema = z.enum(VOICE_GENDER_VALUES);
export type VoiceGender = z.infer<typeof voiceGenderSchema>;

export const SCRIPT_VALUES = ["latin", "cyrillic"] as const;
export const scriptSchema = z.enum(SCRIPT_VALUES);
export type Script = z.infer<typeof scriptSchema>;

export const NAME_STRATEGY_VALUES = [
  "canonical",
  "stripped",
  "ascii",
  "cyrillic",
  "hyphenated",
  "phonetic",
] as const;
export const nameStrategySchema = z.enum(NAME_STRATEGY_VALUES);
export type NameStrategy = z.infer<typeof nameStrategySchema>;

export const RETENTION_CLASS_VALUES = ["paid_audio", "free_output", "ephemeral"] as const;
export const retentionClassSchema = z.enum(RETENTION_CLASS_VALUES);
export type RetentionClass = z.infer<typeof retentionClassSchema>;

/* -------------------------------------------------------------------------- */
/* Credits — bayram.db.enums.CreditEntryKind / CreditReason                       */
/* -------------------------------------------------------------------------- */

/**
 * What one `credit_ledger` row did to the balance. The four are NOT interchangeable labels:
 * each is a different arithmetic SIGN, pinned at the database by
 * `ck_credit_ledger_delta_matches_kind` — `grant` and `refund` are positive, `debit` is
 * negative, and `consume` is **exactly 0**.
 *
 * `consume` looks redundant and is not. It moves nothing; it marks a debit *settled*, which
 * is what frees the in-flight slot. So a ledger table must not colour it as an increase or a
 * decrease, and must not hide it as a no-op row: it is the row that explains why a customer
 * who "used" a credit was never refunded it.
 */
export const CREDIT_ENTRY_KIND_VALUES = ["grant", "debit", "refund", "consume"] as const;
export const creditEntryKindSchema = z.enum(CREDIT_ENTRY_KIND_VALUES);
export type CreditEntryKind = z.infer<typeof creditEntryKindSchema>;

/**
 * Why a `credit_ledger` row was written — a closed enum rather than a note, because free text
 * here would be text *about a person* and would put the one audit trail that outlives every
 * purge onto a retention clock.
 *
 * `admin_grant` is the one an operator writes: it is what `POST /credits/grant` records. The
 * rest are the pipeline's own: two allowances, the render debit, and the four settlements.
 *
 * The last two are what a PAYING account writes, and they are the reason this list has to
 * move in step with `bayram.db.enums.CreditReason`: `credit_ledger` rows are parsed with
 * `z.enum`, so a reason the panel has never heard of fails the parse and the credit-ledger
 * table renders nothing at all — for exactly the accounts an operator most wants to look at.
 * `topup_purchase` is a single song somebody bought; `plan_song` is one song minted out of a
 * live plan at the moment it was charged for, which is why a plan customer's history shows
 * twelve of them spread over a month rather than one grant of twelve on the day they paid.
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
/* Order financials — bayram.db.admin.views                                       */
/* -------------------------------------------------------------------------- */

/**
 * Where one order stands in `credit_ledger`, in the algebra the authorisation gate itself
 * uses over `net = SUM(delta)` and the counts of `refund` / `consume` rows.
 *
 *  - `pending` — `net < 0`, no consume. A debit stands open; the render is in flight, or it
 *    died without settling. This holds an in-flight slot the customer cannot see.
 *  - `settled` — `net < 0` with a consume. The charge stands and was closed.
 *  - `refunded` — `net >= 0` with a refund. Net 0 is precisely what makes the order
 *    **chargeable again** at `generation + 1`, so this is NOT an ending — do not draw it as
 *    one.
 *  - `unmetered` — everything else, which in practice means no ledger row at all. It is the
 *    state most orders on this deployment are in (a draft never reached authorisation) and a
 *    fourth member where §5.1 of the redesign plan named three. Folding it into `pending`
 *    would claim a credit is held that is not; folding it into `settled` would invent a sale.
 *
 * Declaration order is `OrderLedgerStatus`'s, which is not the plan's.
 */
export const ORDER_LEDGER_STATUS_VALUES = [
  "unmetered",
  "pending",
  "settled",
  "refunded",
] as const;
export const orderLedgerStatusSchema = z.enum(ORDER_LEDGER_STATUS_VALUES);
export type OrderLedgerStatus = z.infer<typeof orderLedgerStatusSchema>;

/**
 * What paid for one order — restricted to what the schema can actually prove.
 *
 * §5.1's `telegram_stars` and `admin_grant` are deliberately ABSENT and must not be invented
 * in the UI: no payment rail writes anywhere in `src/`, and `credit_accounts.balance` is
 * fungible, so no query can say whether a debit spent an allowance credit or a comped one.
 *
 *  - `credits` — a charge stands or stood against this order; the customer's balance paid.
 *  - `unenforced` — `credits_enforced` was off and the account could not afford the render,
 *    so the shortfall was minted. Nobody paid; a configuration flag did. This is the closest
 *    thing to "was it comped?" the ledger can prove, and it is orthogonal to the status — a
 *    dark render is charged *and* comped.
 *  - `none` — no ledger row references this order. Unmetered, NOT free.
 */
export const ORDER_PAYMENT_RAIL_VALUES = ["none", "credits", "unenforced"] as const;
export const orderPaymentRailSchema = z.enum(ORDER_PAYMENT_RAIL_VALUES);
export type OrderPaymentRail = z.infer<typeof orderPaymentRailSchema>;

/* -------------------------------------------------------------------------- */
/* Pipeline — bayram.pipeline.events, bayram.admin.serializers.stage_plan            */
/* -------------------------------------------------------------------------- */

/**
 * ELEVEN stages, in `STAGE_ORDER`. `StagePlanView.stages` always carries all eleven; §11.2's
 * "9 stages by default, not 11" is about how many are SCHEDULED (`greetings_per_kit=0` is
 * shipped, so the two greeting stages are unplanned) — the unplanned ones are ghosted, not
 * dropped. Read `scheduledStageCount`, never `stages.length`.
 */
export const PIPELINE_STAGE_VALUES = [
  "validating",
  "authorizing",
  "moderating",
  "writing_lyrics",
  "writing_scripts",
  "composing_song",
  "verifying_name",
  "rendering_greetings",
  "post_processing",
  "persisting",
  "delivering",
] as const;
export const pipelineStageSchema = z.enum(PIPELINE_STAGE_VALUES);
export type PipelineStage = z.infer<typeof pipelineStageSchema>;

/**
 * `"not_observed"` means NO RECORD — seven of the eleven stages write no attempt row and are
 * always `"not_observed"`. It never means "did not run". `"skipped"` is narrower: it is
 * reserved for the two greeting stages of a conclusively finished order.
 */
export const STAGE_OUTCOME_VALUES = ["succeeded", "failed", "not_observed", "skipped"] as const;
export const stageOutcomeSchema = z.enum(STAGE_OUTCOME_VALUES);
export type StageOutcome = z.infer<typeof stageOutcomeSchema>;

export const GREETING_EVIDENCE_VALUES = ["present", "absent"] as const;
export const greetingEvidenceSchema = z.enum(GREETING_EVIDENCE_VALUES);
export type GreetingEvidence = z.infer<typeof greetingEvidenceSchema>;

export const TIMELINE_EVENT_KIND_VALUES = [
  "order_created",
  "brief_recorded",
  "attempt_succeeded",
  "attempt_failed",
  "asset_stored",
  "order_delivered",
  "order_failed",
  "order_last_touched",
] as const;
export const timelineEventKindSchema = z.enum(TIMELINE_EVENT_KIND_VALUES);
export type TimelineEventKind = z.infer<typeof timelineEventKindSchema>;

export const TIMELINE_SOURCE_VALUES = [
  "order",
  "attempts",
  "assets",
  "chat",
  "payments",
  "audit",
] as const;
export const timelineSourceSchema = z.enum(TIMELINE_SOURCE_VALUES);
export type TimelineSource = z.infer<typeof timelineSourceSchema>;

/* -------------------------------------------------------------------------- */
/* Vendor usage — bayram.contracts.Vendor / VendorOperation / CostSource          */
/* -------------------------------------------------------------------------- */

/**
 * Which third party answered one call, from `vendor_usage.vendor`.
 *
 * `openrouter` and `openai_compatible` are two members and not one, because they are two
 * different claims about the SAME adapter: both instances of `OpenAiCompatLlmProvider`
 * report `provider = "openai-compat"`, and only OpenRouter is asked for — and reports — a
 * per-call cost. Collapsing them would put a `vendor_reported` figure and a derived one in
 * the same group and let a rollup average them.
 *
 * `fake` is `BAYRAM_USE_FAKE_PROVIDERS`. A demo run is RECORDED rather than dropped, so a
 * deployment that has only ever run fakes reads as "instrumented, and none of it was spend"
 * rather than as silence — but it must never be totalled as money, which is what the
 * separate member is for.
 */
export const VENDOR_VALUES = [
  "elevenlabs",
  "openrouter",
  "gemini",
  "openai_compatible",
  "fake",
] as const;
export const vendorSchema = z.enum(VENDOR_VALUES);
export type Vendor = z.infer<typeof vendorSchema>;

/**
 * What we asked the vendor to DO, from `vendor_usage.operation`.
 *
 * `health` is in the list and is not spend: a quota probe records a row so an operator can
 * see the adapter is reachable, and its `costUsd` is always `null`. A rollup that treated
 * probes as calls-with-no-cost would drag a group's costed share down for a reason that has
 * nothing to do with pricing.
 */
export const VENDOR_OPERATION_VALUES = [
  "music_compose",
  "music_inpaint",
  "speech_synthesis",
  "transcription",
  "chat_completion",
  "health",
] as const;
export const vendorOperationSchema = z.enum(VENDOR_OPERATION_VALUES);
export type VendorOperation = z.infer<typeof vendorOperationSchema>;

/**
 * WHERE a cost figure came from — the provenance that makes it readable.
 *
 * Three of these are `bayram.contracts.CostSource`; `"mixed"` is not a stored value and exists
 * only on a ROLLUP, where one (vendor, operation, model) group contained more than one
 * source. It is the honest answer to "how was this total arrived at" for a group whose legs
 * were priced differently, and it is why the label is rendered beside every aggregate:
 *
 *  - `vendor_reported` — the vendor itself told us the number (OpenRouter's `usage.cost`).
 *  - `derived` — arithmetic over vendor-reported counts against a rate we configured.
 *  - `estimated` — arithmetic over a quantity WE chose (a requested duration, `len(text)`).
 *    The weakest claim on the screen, and the one that must never be read as a bill.
 *  - `mixed` — more than one of the above inside one group.
 *
 * `null` is a FOURTH state and not a member: the group has no priced call at all, which
 * renders as "not priced" and never as `$0.00`.
 */
export const COST_SOURCE_VALUES = ["vendor_reported", "derived", "estimated", "mixed"] as const;
export const costSourceSchema = z.enum(COST_SOURCE_VALUES);
export type CostSource = z.infer<typeof costSourceSchema>;

/* -------------------------------------------------------------------------- */
/* Admin — bayram.db.enums, bayram.admin.*                                          */
/* -------------------------------------------------------------------------- */

export const ADMIN_ROLE_VALUES = ["owner", "admin", "support", "viewer"] as const;
export const adminRoleSchema = z.enum(ADMIN_ROLE_VALUES);
export type AdminRole = z.infer<typeof adminRoleSchema>;

/** 34 members. Values are DOTTED and abbreviated — never the Python member name. */
export const AUDIT_ACTION_VALUES = [
  "login.success",
  "login.failure",
  "login.limited",
  "logout",
  "step_up.success",
  "step_up.failure",
  "session.revoked",
  "reveal.personal",
  "asset.stream",
  "order.retry",
  "order.reenqueue",
  "order.deliver",
  "order.cancel",
  "user.block",
  "user.unblock",
  "user.purge.req",
  "user.purge.done",
  "user.purge.fail",
  "moderation.approve",
  "moderation.reject",
  "config.validate",
  "config.commit",
  "config.rollback",
  "retention.extended",
  "retention.run",
  "export.aggregate",
  "export.order",
  "export.audit",
  "admin.create",
  "admin.role",
  "admin.deactivate",
  "admin.password",
  "permission.denied",
  /**
   * `POST /api/users/{telegram_user_id}/credits/grant`. Last in `AuditAction`'s declaration
   * order because it is the newest member, and the only one this tuple has ever been missing:
   * every other member has been here since Phase 1, and the drift was invisible because no
   * grant had been written yet. A row this enum does not carry is a `SCHEMA_DRIFT` banner on
   * `/audit` rather than an unlabelled row — `auditEntryViewSchema.action` is
   * `auditActionSchema` — so the FIRST real grant would have broken the whole screen.
   */
  "credit.grant",
] as const;
export const auditActionSchema = z.enum(AUDIT_ACTION_VALUES);
export type AuditAction = z.infer<typeof auditActionSchema>;

/**
 * §11.2: "/audit — Who did something destructive?" These are the actions that count toward
 * the destructive-in-24h figure, which is charted separately from the row count, and whose
 * volume is charted by `recordCount` rather than by rows.
 */
export const DESTRUCTIVE_AUDIT_ACTIONS: readonly AuditAction[] = [
  "reveal.personal",
  "order.deliver",
  "order.cancel",
  "user.block",
  "user.purge.req",
  "user.purge.done",
  /**
   * The only action on the panel that ISSUES value rather than reading or revoking it, and the
   * ledger it writes to is append-only — a mistaken grant is corrected by a compensating entry,
   * never by deleting the row. It belongs in the 24h destructive figure for the same reason
   * `user.block` does: it is what an operator would want to see reviewed at the end of a shift.
   */
  "credit.grant",
  "config.commit",
  "config.rollback",
  "retention.run",
  "export.order",
  "export.audit",
  "admin.create",
  "admin.role",
  "admin.deactivate",
  "admin.password",
];

export const AUDIT_OUTCOME_VALUES = ["ok", "denied", "error"] as const;
export const auditOutcomeSchema = z.enum(AUDIT_OUTCOME_VALUES);
export type AuditOutcome = z.infer<typeof auditOutcomeSchema>;

export const AUDIT_REASON_CODE_VALUES = [
  "customer_request",
  "gdpr_erasure",
  "abuse_report",
  "support_investigation",
  "incident",
  "bake_off",
  "routine_ops",
  "other",
] as const;
export const auditReasonCodeSchema = z.enum(AUDIT_REASON_CODE_VALUES);
export type AuditReasonCode = z.infer<typeof auditReasonCodeSchema>;

/** The values contain `+` and `-`. Render them verbatim; they are not slugs. */
export const CHAIN_PROTECTION_VALUES = ["revoke+hmac", "hmac-only"] as const;
export const chainProtectionSchema = z.enum(CHAIN_PROTECTION_VALUES);
export type ChainProtection = z.infer<typeof chainProtectionSchema>;

export const PURGE_TRIGGER_VALUES = ["cron", "manual", "user_request"] as const;
export const purgeTriggerSchema = z.enum(PURGE_TRIGGER_VALUES);
export type PurgeTrigger = z.infer<typeof purgeTriggerSchema>;

/**
 * `"keys_unrecorded"` is today's normal answer and means UNKNOWN, never clean. A `null`
 * `storageReconciliation` on the retention response is different again: no run has happened,
 * and a scheduler that never fired must not light a clean badge.
 */
export const STORAGE_RECONCILIATION_VALUES = [
  "reconciled",
  "leaked",
  "keys_unrecorded",
  "nothing_to_reconcile",
] as const;
export const storageReconciliationSchema = z.enum(STORAGE_RECONCILIATION_VALUES);
export type StorageReconciliation = z.infer<typeof storageReconciliationSchema>;

/** The request body value on `/api/auth/step-up` — the ACTION only, never the composed pair. */
export const STEP_UP_ACTION_VALUES = [
  "reveal",
  "order.force_deliver",
  "user.block",
  /**
   * Its OWN action rather than a reuse of `user.block`, and the distinction is load-bearing:
   * a step-up collected to bar an abuser must not also authorise minting them spendable
   * credit. `POST /users/{id}/credits/grant` scopes it to the Telegram id as a bare decimal
   * string — `"credit.grant:770000123"` — never to `users.id`.
   */
  "credit.grant",
  "moderation.decide",
  "user.purge",
  "config.write",
  "order.evidence_export",
  "audit.export",
  "admin.manage",
] as const;
export const stepUpActionSchema = z.enum(STEP_UP_ACTION_VALUES);
export type StepUpAction = z.infer<typeof stepUpActionSchema>;

/**
 * The two actions whose grace window is ZERO (§12.1 T2). `expiresAt === grantedAt` for
 * these, so a UI must not assume it has a window to spend.
 */
export const ZERO_GRACE_STEP_UP_ACTIONS: readonly StepUpAction[] = ["user.purge", "config.write"];

export const ADMIN_ENVIRONMENT_VALUES = ["dev", "staging", "prod"] as const;
export const adminEnvironmentSchema = z.enum(ADMIN_ENVIRONMENT_VALUES);
export type AdminEnvironment = z.infer<typeof adminEnvironmentSchema>;

/** UPPERCASE on the wire. */
export const LOG_LEVEL_VALUES = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;
export const logLevelSchema = z.enum(LOG_LEVEL_VALUES);
export type LogLevel = z.infer<typeof logLevelSchema>;

/** Appears only inside `error.details.permission` on a 403. */
export const PERMISSION_VALUES = [
  "session.self",
  "dashboard.read",
  "records.read",
  "chat.index.read",
  "wizard_state.read",
  "moderation.queue.read",
  "config.read",
  "retention.read",
  "reveal.personal_data",
  "reveal.media",
  "order.retry",
  "order.force_deliver",
  "user.block",
  // The ROLE halves of the two `W+S` cells above and below. A router cannot enforce a `W+S`
  // cell — `require_permission` resolves to `check_role`, which holds no subject and so never
  // consults a grant, and would answer `STEP_UP_REQUIRED` to a correctly re-authenticated
  // ADMIN for ever. So `POST /users/{id}/block` guards its ROUTER on `user.block.write` (the
  // bare `W`) and its HANDLER on `user.block`'s subject-scoped step-up. A 403 from the router
  // therefore names `user.block.write`, never `user.block`.
  "user.block.write",
  "credit.grant",
  "credit.grant.write",
  "moderation.reveal",
  "moderation.decide",
  "retention.sweep",
  "audit.read",
  "reveal.volume.read",
  "export.aggregate",
  "user.purge",
  "config.write",
  "order.evidence_export",
  "audit.export",
  // Two rows for the five `/admins` endpoints, per §6.8 line 949 rather than §12.2's
  // once-collapsed row: `admin.read` is the roster GET (owner, no step-up) and
  // `admin.manage` is the four account writes' `W+S`. A 403 on `GET /api/admins` therefore
  // names `admin.read`.
  "admin.read",
  "admin.manage",
] as const;
export const permissionSchema = z.enum(PERMISSION_VALUES);
export type Permission = z.infer<typeof permissionSchema>;

/* -------------------------------------------------------------------------- */
/* Wizard state — the one place snake_case KEYS survive inside camelCase       */
/* -------------------------------------------------------------------------- */

/**
 * `WizardStateView.choices` is an object whose KEYS are these, snake_case, from
 * `WIZARD_CHOICE_FIELDS`. A key is present only when the Redis draft holds a `str` under it.
 *
 * The VALUES are closed-vocabulary strings (`Language`/`Occasion`/`Genre`/`VoiceGender`) but
 * are typed as bare `string` on the wire and must be parsed as such: they come from Redis
 * JSON written by a possibly-older build, and a `z.enum` here would turn a stale draft into
 * a SCHEMA_DRIFT banner on a screen whose entire job is to show a stuck customer's draft.
 */
export const WIZARD_CHOICE_KEYS = [
  "ui_language",
  "occasion",
  "genre",
  "vocal_gender",
  "output_language",
] as const;
export type WizardChoiceKey = (typeof WIZARD_CHOICE_KEYS)[number];

/** `WizardStateView.textFields` is always exactly these three, in this order. */
export const DRAFT_FIELD_KEY_VALUES = ["note", "recipient", "lyrics"] as const;
export const draftFieldKeySchema = z.enum(DRAFT_FIELD_KEY_VALUES);
export type DraftFieldKey = z.infer<typeof draftFieldKeySchema>;

/* -------------------------------------------------------------------------- */
/* Reveal — the closed vocabularies of POST /api/reveal (§12.3)                */
/* -------------------------------------------------------------------------- */

/**
 * `bayram.admin.schemas.reveal.RevealSubjectType` — a SUBSET of `audit.SUBJECT_TYPES`, two
 * members today.
 *
 * `"user"` joins `"order"` because a `user_profiles` row now holds customer-authored PII —
 * the phone number, the Telegram handle, the two name parts — that the list and detail
 * screens can only show masked. It is legal in the server's `audit.SUBJECT_TYPES`, and its
 * subject id is **`users.id`**, the UUID, never `telegramUserId`: `revealRequestSchema`
 * types `subjectId` as a UUID and the server compares the composed `"reveal:<subjectId>"`
 * step-up scope whole, so an integer here would be a permanent, undebuggable 403.
 *
 * §12.3's three still-absent subjects (`chat` bodies, `wizard_draft` keys, moderation detail)
 * stay absent for the same reason as before: each names a table or a route this build does
 * not have, and listing one would put a value on the wire that answers 500. They arrive with
 * their sources — `chat` and `wizard_draft` in Phase 3, audio through the asset stream's own
 * route rather than through this endpoint at all.
 */
export const REVEAL_SUBJECT_TYPE_VALUES = ["order", "user"] as const;
export const revealSubjectTypeSchema = z.enum(REVEAL_SUBJECT_TYPE_VALUES);
export type RevealSubjectType = z.infer<typeof revealSubjectTypeSchema>;

/**
 * `RevealField` — the closed list of columns a reveal may unmask, spelled `table.column`.
 *
 * **The values are lowercase and dotted because they land in `admin_audit_log.field_names`
 * verbatim.** `audit._FIELD_NAME_PATTERN` is `^[a-z][a-z0-9_.]{0,63}$`; a camelCase spelling
 * here would raise deep inside the audit append, which `audit_sink` would swallow and retry
 * with `subject_id=None, ip=None` — a 200 carrying an audit row that has lost the subject and
 * the address. This is the one place in the SPA where a wire value is NOT camelCase, and it
 * is the reason `AuditEntryView.fieldNames` is not either.
 */
export const REVEAL_FIELD_VALUES = [
  "briefs.recipient_name_display",
  "briefs.recipient_name_raw",
  "briefs.recipient_lookup_key",
  "briefs.recipient_candidates",
  "briefs.note",
  "briefs.approved_lyrics",
  "generation_attempts.stt_transcript",
  "generation_attempts.name_candidate_text",
  "user_profiles.phone_e164",
  "user_profiles.first_name",
  "user_profiles.last_name",
  "user_profiles.telegram_username",
] as const;
export const revealFieldSchema = z.enum(REVEAL_FIELD_VALUES);
export type RevealField = z.infer<typeof revealFieldSchema>;

/**
 * `RevealShape` — NOT on the wire. It is derived from `fields` and decides the charge, the
 * paging and which budget is touched, and the server refuses a request that mixes the two
 * because one `recordCount` cannot honestly describe a mixed reveal.
 */
export const REVEAL_SHAPE_VALUES = ["single", "paged"] as const;
export type RevealShape = (typeof REVEAL_SHAPE_VALUES)[number];

/**
 * `reveal.FIELD_SHAPES`, mirrored. A `briefs` column is 1:1 with the order, so it is one
 * record; `generation_attempts` has a row per take, so its customer-authored free text is the
 * paged reveal §12.3 caps at fifty and charges against the daily conversation ceiling too.
 *
 * A `user_profiles` row is 1:1 with the account — one phone, one handle, one pair of name
 * parts — so its four columns together are ONE record, the same shape as a brief's six, and
 * all four are `"single"`. That is why they can be offered as a single group without the
 * group costing four times what it charges for.
 *
 * Phase 3's `chat_messages.body` joins the `paged` half — §12.3's paged row is that column,
 * and the table does not exist yet.
 */
export const REVEAL_FIELD_SHAPES: Readonly<Record<RevealField, RevealShape>> = {
  "briefs.recipient_name_display": "single",
  "briefs.recipient_name_raw": "single",
  "briefs.recipient_lookup_key": "single",
  "briefs.recipient_candidates": "single",
  "briefs.note": "single",
  "briefs.approved_lyrics": "single",
  "generation_attempts.stt_transcript": "paged",
  "generation_attempts.name_candidate_text": "paged",
  "user_profiles.phone_e164": "single",
  "user_profiles.first_name": "single",
  "user_profiles.last_name": "single",
  "user_profiles.telegram_username": "single",
};

/**
 * `budget.RevealBudgetScope` — which of the two separately-exhaustible budgets answered.
 *
 * Reaches the client only inside `error.details.budget` on a 429 `REVEAL_BUDGET_EXHAUSTED`.
 * Naming it is the difference between a message an operator can act on and "you have run
 * out": the two ceilings have different windows and spending one never spends the other.
 */
export const REVEAL_BUDGET_SCOPE_VALUES = ["records", "conversations"] as const;
export const revealBudgetScopeSchema = z.enum(REVEAL_BUDGET_SCOPE_VALUES);
export type RevealBudgetScope = z.infer<typeof revealBudgetScopeSchema>;
