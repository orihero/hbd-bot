/**
 * `POST /api/reveal` and `POST /api/auth/step-up` — the only path by which a masked value
 * on this surface becomes plaintext, and the re-authentication that unlocks it.
 *
 * Transcribed from `.openpencil-export/users-generations-openapi.json`, `admin/routers/
 * reveal.py`, `admin/schemas/reveal.py` and `admin/deps.py`.
 *
 * ## Four ordered steps, and the order is the control
 *
 * The handler validates the body, enforces a step-up ON THIS SUBJECT, charges the budget for
 * what the reveal is AUTHORISED to return, and then audits-then-reads. Three consequences a
 * UI must honour:
 *
 * 1. **A reason is not optional and not a formality.** `reasonCode` has no default, so a
 *    reveal without one is a 422 before anything is charged or logged. Collect it BEFORE
 *    asking, never after.
 * 2. **A refused step-up costs no budget.** Step 2 runs before step 3. Telling an operator
 *    who mistyped their password that they burned a record off their hourly ceiling is a
 *    lie that will stop them doing legitimate work.
 * 3. **The charge is knowable before it is paid.** `records_authorised` is `1` for a
 *    `single`-shaped reveal however many fields it names, and the page size for a `paged`
 *    one — never the number of rows found. `revealCost` in `features/reveal/revealFields.ts`
 *    computes it — ONE mirror of `plan_reveal`, so the cost a dialog shows cannot drift from
 *    the cost the budget is debited — against `RevealBudgetView` before the operator confirms.
 *
 * ## Plaintext is not data this app owns
 *
 * A `RevealResponse` is never cached in react-query, never logged, never put in a URL and
 * never persisted. It lives in the component state that asked for it and dies with it. That
 * is a rule about the RESULT of these two functions, and this module cannot enforce it — the
 * screens must.
 *
 * ## The role gate
 *
 * The router is guarded by `reveal.personal_data.read` (SUPPORT and above); VIEWER is a flat
 * 403 `FORBIDDEN` before the handler runs. So a reveal affordance is HIDDEN for VIEWER, not
 * disabled: a button that always fails is worse than no button, and clicking it writes a
 * `permission.denied` audit row against an operator who did nothing wrong.
 */

import { z } from "zod";

import { request, type ApiFailure, type ApiResult } from "./client";
import {
  AUTH_PREFIX,
  MAX_PASSWORD_CHARS,
  MAX_REASON_REF_CHARS,
  MAX_REASON_TEXT_CHARS,
  MAX_RECORDS_PER_REVEAL,
  MAX_REVEAL_FIELDS,
  MAX_STEP_UP_SUBJECT_CHARS,
  MIN_REVEAL_FIELDS,
  REASON_REF_PATTERN,
  REVEAL_PATH,
} from "./constants";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from the spec; a new member must be added here first        */
/* -------------------------------------------------------------------------- */

/**
 * `AuditReasonCode` — WHY a §9.2 action was taken, and the same closed vocabulary for every
 * one of them: reveal, block, unblock, grant.
 *
 * It is a code and not free text because `admin_audit_log` is queried by equality on it and
 * `reasonText` is on a 90-day sweep — "show me every reveal filed under `abuse_report`"
 * must not mean "read every row and grep the prose".
 */
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

/** `RevealSubjectType` — one reveal covers one subject. A mixed request is a 422. */
export const REVEAL_SUBJECT_TYPE_VALUES = ["order", "user"] as const;
export const revealSubjectTypeSchema = z.enum(REVEAL_SUBJECT_TYPE_VALUES);
export type RevealSubjectType = z.infer<typeof revealSubjectTypeSchema>;

/**
 * `RevealField` — the twelve columns that can be unmasked, spelled `table.column`.
 *
 * The spelling is the audit row's, so it is taken verbatim and never prettified on the wire;
 * labels for humans belong in the screen, beside the checkbox.
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
 * `StepUpAction` — what a grant is taken FOR. `POST /api/auth/step-up` stores
 * `"<scope>:<subjectId>"` and every guarded handler compares that string WHOLE.
 */
export const STEP_UP_ACTION_VALUES = [
  "reveal",
  "order.force_deliver",
  "user.block",
  "credit.grant",
  "moderation.decide",
  "user.purge",
  "config.write",
  "order.evidence_export",
  "audit.export",
  "admin.manage",
  /* `broadcast.send`, scoped to the campaign UUID. Both routes that cause a message to leave —
     the send and the test send — enforce it inside the handler on `str(broadcast_id)`. It is
     listed here because `stepUpTargetOf` PARSES this enum: a member missing from it turns a
     refusal the operator could fix with a password into "your role cannot do this". */
  "broadcast.send",
] as const;
export const stepUpActionSchema = z.enum(STEP_UP_ACTION_VALUES);
export type StepUpAction = z.infer<typeof stepUpActionSchema>;

/**
 * `RevealShape` — NOT on the wire. Derived from `fields`, it decides the charge, whether
 * there is paging, and which of the two budgets is touched. The server refuses a request
 * that mixes the two, because one `recordCount` cannot honestly describe a mixed reveal.
 */
export const REVEAL_SHAPE_VALUES = ["single", "paged"] as const;
export type RevealShape = (typeof REVEAL_SHAPE_VALUES)[number];

/**
 * `services.reveal.FIELD_SHAPES`, mirrored.
 *
 * A `briefs` row is 1:1 with the order and a `user_profiles` row is 1:1 with the account, so
 * each group costs ONE record however many of its columns are ticked — which is why they are
 * offered as a group. `generation_attempts` has a row per take, so its free text is the paged
 * reveal §12.3 caps at fifty and charges against the daily conversation ceiling as well.
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
 * `schemas.reveal.FIELD_SUBJECTS` — which subject each column is asked for under.
 *
 * Mirrored because the server checks it BEFORE the shape check and refuses with a 422: a
 * field asked for under the wrong subject would charge a step-up scoped to one table's id
 * and then read a different table by it. A dialog that offers only the fields belonging to
 * the subject it is open on cannot build that request in the first place.
 */
export const REVEAL_FIELD_SUBJECTS: Readonly<Record<RevealField, RevealSubjectType>> = {
  "briefs.recipient_name_display": "order",
  "briefs.recipient_name_raw": "order",
  "briefs.recipient_lookup_key": "order",
  "briefs.recipient_candidates": "order",
  "briefs.note": "order",
  "briefs.approved_lyrics": "order",
  "generation_attempts.stt_transcript": "order",
  "generation_attempts.name_candidate_text": "order",
  "user_profiles.phone_e164": "user",
  "user_profiles.first_name": "user",
  "user_profiles.last_name": "user",
  "user_profiles.telegram_username": "user",
};

/**
 * `security.budget.RevealBudgetScope` — which of the two separately-exhaustible ceilings
 * refused. Reaches the client only inside `error.details.budget` on a 429.
 *
 * Naming it is the difference between a message an operator can act on and "you have run
 * out": the two ceilings have different windows and spending one never spends the other.
 */
export const REVEAL_BUDGET_SCOPE_VALUES = ["records", "conversations"] as const;
export const revealBudgetScopeSchema = z.enum(REVEAL_BUDGET_SCOPE_VALUES);
export type RevealBudgetScope = z.infer<typeof revealBudgetScopeSchema>;

/* -------------------------------------------------------------------------- */
/* The reason trio, shared by every §9.2 action                                */
/* -------------------------------------------------------------------------- */

/**
 * `schemas.actions.ReasonedRequest` — inherited by `RevealRequest`, `UserBlockRequest` and
 * `CreditGrantRequest` rather than restated on each, because it is ONE audit column with one
 * scrubbing rule, and three copies of that rule drift apart one endpoint at a time.
 *
 * `reasonCode` has no default anywhere: that is the whole of "an action without a reason is
 * a 422". `reasonRef` is a ticket id (the pattern is the server's, restated so a form
 * refuses before a round trip that would write no audit row); `reasonText` is prose, on the
 * 90-day sweep — never put a customer's own words in it.
 */
export const reasonedRequestSchema = z.object({
  reasonCode: auditReasonCodeSchema,
  reasonRef: z.string().max(MAX_REASON_REF_CHARS).regex(REASON_REF_PATTERN).nullish(),
  reasonText: z.string().max(MAX_REASON_TEXT_CHARS).nullish(),
});
export type ReasonedRequest = z.infer<typeof reasonedRequestSchema>;

/* -------------------------------------------------------------------------- */
/* POST /api/reveal                                                            */
/* -------------------------------------------------------------------------- */

/**
 * §12.3's body. `limit`/`cursor` apply to a PAGED reveal only — sending either on a single
 * one is a 422, because a page control on something with no pages teaches a caller to expect
 * one.
 *
 * `subjectId` is a UUID and must be byte-identical to the id the step-up was taken for: for
 * `subjectType: "user"` it is `UserView.id` (the `users` row's UUID), NOT the Telegram id
 * that the block and grant routes are keyed on.
 */
export const revealRequestSchema = reasonedRequestSchema.extend({
  subjectType: revealSubjectTypeSchema,
  subjectId: z.string().uuid(),
  fields: z.array(revealFieldSchema).min(MIN_REVEAL_FIELDS).max(MAX_REVEAL_FIELDS),
  limit: z.number().int().min(1).max(MAX_RECORDS_PER_REVEAL).nullish(),
  cursor: z.string().max(256).nullish(),
});
export type RevealRequest = z.infer<typeof revealRequestSchema>;

/**
 * What this reveal cost and what is left, for §11.4's budget meter.
 *
 * `*Remaining` is `null` when that counter was not touched — a single-record reveal never
 * reads the daily conversation budget — and **null is not zero**: a meter rendering "0 left"
 * for "not asked" stops an operator doing legitimate work.
 */
export const revealBudgetViewSchema = z.object({
  recordsCharged: z.number().int(),
  recordsRemaining: z.number().int().nullable().default(null),
  conversationsCharged: z.number().int(),
  conversationsRemaining: z.number().int().nullable().default(null),
});
export type RevealBudgetView = z.infer<typeof revealBudgetViewSchema>;

/**
 * One record's plaintext, byte for byte as it is stored.
 *
 * `fields` maps a `RevealField` value to the column's value, and `null` there means **the
 * column is NULL** — never a mask, never an empty string. Typed as an open record of
 * `unknown` rather than keyed on `RevealField`: a value can be a string, a number, a boolean
 * or a JSON structure (`briefs.recipient_candidates`), and keying the record on the enum
 * would turn a thirteenth column shipped by the server into a permanent drift banner instead
 * of a field this build simply does not render.
 *
 * The two purge stamps travel with every record because "no name" and "name erased on
 * schedule on 2026-05-14" are different facts, and a screen that renders them alike cannot
 * answer the question a data-subject request asks. Both are `null` on a `user_profiles`
 * record and that is NOT "never purged": that table carries no clock, and `/forget` deletes
 * the row outright — an erased customer is a 404 here, never a record with stamps on it.
 */
export const revealedRecordSchema = z.object({
  recordId: z.string().uuid(),
  createdAt: timestampSchema,
  fields: z.record(z.string(), z.unknown()),
  identityPurgedAt: timestampSchema.nullable().default(null),
  textPurgedAt: timestampSchema.nullable().default(null),
});
export type RevealedRecord = z.infer<typeof revealedRecordSchema>;

/**
 * The reveal's answer. `recordCount` is what was CHARGED, which is what the reveal was
 * authorised to return — it is not `records.length`, and the gap is a page that found fewer
 * rows than it paid for.
 */
export const revealResponseSchema = z.object({
  subjectType: revealSubjectTypeSchema,
  subjectId: z.string().uuid(),
  revealedAt: timestampSchema,
  reasonCode: auditReasonCodeSchema,
  recordCount: z.number().int(),
  revealedFields: z.array(revealFieldSchema),
  records: z.array(revealedRecordSchema),
  /** Paged reveals only, and `null` at the end of the walk. */
  nextCursor: z.string().nullable().default(null),
  budget: revealBudgetViewSchema,
});
export type RevealResponse = z.infer<typeof revealResponseSchema>;

/** The name the screens were specified against. The wire calls it `RevealResponse`. */
export type RevealResultView = RevealResponse;

/* -------------------------------------------------------------------------- */
/* POST /api/auth/step-up                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Re-authentication for ONE action on ONE subject (§12.1 T2). Never session-wide.
 *
 * `subjectId` is a string on this route whatever the subject is — a UUID for a reveal, the
 * Telegram id as bare decimal digits for `user.block` and `credit.grant`. Take it from the
 * refusal's `details.subjectId` VERBATIM (`stepUpTargetOf` below) rather than re-formatting
 * a value of your own: the scope is compared whole, so a braced or upper-case spelling is a
 * mismatch nobody can debug from the 403.
 */
export const stepUpRequestSchema = z.object({
  password: z.string().min(1).max(MAX_PASSWORD_CHARS),
  scope: stepUpActionSchema,
  subjectId: z.string().min(1).max(MAX_STEP_UP_SUBJECT_CHARS),
});
export type StepUpRequest = z.infer<typeof stepUpRequestSchema>;

/**
 * The grant. `scope` is the composed `"<action>:<subjectId>"` the guard will compare, and
 * `expiresAt` is the expiry the guard will ACTUALLY honour — the configured grace for an
 * ordinary action and `grantedAt` itself for the two §12.1 T2 marks "grace 0", so a countdown
 * built from it never promises five minutes that the next request refuses.
 *
 * A grant is **not single-use**: nothing clears it, so within the window the same grant
 * admits the next request for the same action and subject, page two of a paged reveal
 * included. The budget bounds volume; the step-up does not.
 */
export const stepUpResponseSchema = z.object({
  scope: z.string(),
  grantedAt: timestampSchema,
  expiresAt: timestampSchema,
});
export type StepUpResponse = z.infer<typeof stepUpResponseSchema>;

/** The name the screens were specified against. The wire calls it `StepUpResponse`. */
export type StepUpResultView = StepUpResponse;

/**
 * The two actions the server grants for zero seconds — `max_age_for_action` returns 0, so
 * the grant must be taken in the same breath as the request it authorises. Neither is on
 * this phase's surface; listed so a countdown component never has to guess.
 */
export const ZERO_GRACE_STEP_UP_ACTIONS: readonly StepUpAction[] = ["user.purge", "config.write"];

/* -------------------------------------------------------------------------- */
/* Cost, before it is paid                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The shape of a set of fields, or `null` when they disagree (which the server refuses) or
 * the set is empty. Empty is `null` rather than `"single"`: nothing chosen is not a reveal.
 */
export function revealShapeOf(fields: readonly RevealField[]): RevealShape | null {
  const first = fields[0];
  if (first === undefined) return null;
  const shape = REVEAL_FIELD_SHAPES[first];
  return fields.every((field) => REVEAL_FIELD_SHAPES[field] === shape) ? shape : null;
}

/* -------------------------------------------------------------------------- */
/* Reading a refusal                                                           */
/* -------------------------------------------------------------------------- */

/** The two halves of a grant, read off the refusal that asked for it. */
export interface StepUpTarget {
  readonly action: StepUpAction;
  /** Byte-identical to the id the refusing handler compared against. */
  readonly subjectId: string;
}

/** Whether this failure is the one a re-authentication can fix. */
export function isStepUpRequired(failure: ApiFailure | null): boolean {
  return failure !== null && failure.code === "STEP_UP_REQUIRED";
}

/**
 * The grant to ask for, taken from `details.stepUpAction` and `details.subjectId`.
 *
 * `null` for a 403 that is not a step-up and — deliberately — for a `STEP_UP_REQUIRED`
 * carrying no details. That second case is the ROUTER-level refusal: `check_role` reports a
 * cell's step-up requirement without ever consulting a grant, so re-authenticating cannot
 * change its answer and offering a password box would be a loop the operator cannot win.
 * Render that one as "your role cannot do this", not as a prompt.
 */
export function stepUpTargetOf(failure: ApiFailure | null): StepUpTarget | null {
  if (!isStepUpRequired(failure) || failure === null || failure.details === null) return null;
  const action = failure.details["stepUpAction"];
  const subjectId = failure.details["subjectId"];
  if (typeof subjectId !== "string" || subjectId === "") return null;
  const parsed = stepUpActionSchema.safeParse(action);
  return parsed.success ? { action: parsed.data, subjectId } : null;
}

/** A spent ceiling, with everything the operator needs to know when to come back. */
export interface RevealBudgetRefusal {
  /** Which ceiling refused. `null` when the server could not name one. */
  readonly scope: RevealBudgetScope | null;
  readonly recordsRequested: number | null;
  readonly recordsRemaining: number | null;
  readonly conversationsRemaining: number | null;
  /** Seconds to the refusing window's reset, off `Retry-After`. */
  readonly retryAfterS: number | null;
}

/**
 * A 429 `REVEAL_BUDGET_EXHAUSTED`, unpacked — its own state, never a generic error.
 *
 * It is NOT `SERVICE_UNAVAILABLE`, which is what the same guard raises when the counter
 * store cannot answer: telling an operator their budget is spent for the hour Redis is down
 * would have them open an incident against the wrong system. Both carry `Retry-After`.
 */
export function revealBudgetRefusalOf(failure: ApiFailure | null): RevealBudgetRefusal | null {
  if (failure === null || failure.code !== "REVEAL_BUDGET_EXHAUSTED") return null;
  const details = failure.details ?? {};
  const scope = revealBudgetScopeSchema.safeParse(details["budget"]);
  return {
    scope: scope.success ? scope.data : null,
    recordsRequested: readInt(details["recordsRequested"]),
    recordsRemaining: readInt(details["recordsRemaining"]),
    conversationsRemaining: readInt(details["conversationsRemaining"]),
    retryAfterS: failure.retryAfterS,
  };
}

/** `details` is a server-shaped bag of `unknown`; a non-number there is "not reported". */
function readInt(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const REVEAL_ENDPOINT = {
  reveal: "POST /api/reveal",
  stepUp: "POST /api/auth/step-up",
} as const;

/**
 * Plaintext for the named fields of one subject — never the whole object.
 *
 * The result is not cacheable and must not be handed to react-query as query data. Every
 * failure after the audit step still leaves the audit row behind, which is the point of the
 * ordering: `STEP_UP_REQUIRED` (403), `FORBIDDEN` (403, VIEWER), `REVEAL_BUDGET_EXHAUSTED`
 * (429), `SERVICE_UNAVAILABLE` (503, the counter store), `NOT_FOUND` (404) and
 * `INVALID_INPUT` (422).
 */
export function reveal(
  body: RevealRequest,
  signal?: AbortSignal,
): Promise<ApiResult<RevealResponse>> {
  return request({
    endpoint: REVEAL_ENDPOINT.reveal,
    path: REVEAL_PATH,
    method: "POST",
    body,
    schema: revealResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Re-authenticate for one action on one subject.
 *
 * A wrong password is `FORBIDDEN` (403) and charges the re-auth budget;
 * `REAUTH_RATE_LIMITED` (429) is that budget spent, and it is scoped to the SESSION — its
 * remedy is signing in again, which is why it is a separate code from `LOGIN_RATE_LIMITED`.
 * A `subjectId` that could not be stored as a scope is `INVALID_INPUT` (422), never a 403,
 * so the SPA is not sent into a re-authentication loop it cannot win.
 */
export function stepUp(
  body: StepUpRequest,
  signal?: AbortSignal,
): Promise<ApiResult<StepUpResponse>> {
  return request({
    endpoint: REVEAL_ENDPOINT.stepUp,
    path: `${AUTH_PREFIX}/step-up`,
    method: "POST",
    body,
    schema: stepUpResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
