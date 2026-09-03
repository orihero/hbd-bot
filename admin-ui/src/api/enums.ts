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
/* Domain — hbd.contracts, hbd.db.enums                                        */
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

export const OCCASION_VALUES = ["birthday", "anniversary", "custom"] as const;
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
/* Pipeline — hbd.pipeline.events, hbd.admin.serializers.stage_plan            */
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
/* Admin — hbd.db.enums, hbd.admin.*                                          */
/* -------------------------------------------------------------------------- */

export const ADMIN_ROLE_VALUES = ["owner", "admin", "support", "viewer"] as const;
export const adminRoleSchema = z.enum(ADMIN_ROLE_VALUES);
export type AdminRole = z.infer<typeof adminRoleSchema>;

/** 33 members. Values are DOTTED and abbreviated — never the Python member name. */
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
 * `hbd.admin.schemas.reveal.RevealSubjectType` — a SUBSET of `audit.SUBJECT_TYPES`, and one
 * member today.
 *
 * §12.3 names four more reveal subjects (`chat` bodies, `wizard_draft` keys, moderation
 * detail, audio) and every one of them names a table or a route that does not exist on this
 * build. Listing them here would put values on the wire that answer 500, so they arrive with
 * their sources — `chat` and `wizard_draft` in Phase 3, audio through the asset stream's own
 * route rather than through this endpoint at all.
 */
export const REVEAL_SUBJECT_TYPE_VALUES = ["order"] as const;
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
