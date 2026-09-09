/**
 * The reveal's vocabulary: the twelve columns, grouped by the subject they are asked for
 * under, in the words an operator uses rather than the words the column has.
 *
 * Two of the groupings are load-bearing rather than cosmetic.
 *
 * **By SUBJECT**, because the server checks the subject before it checks anything else. A
 * field asked for under the wrong `subjectType` is a 422, and it would be one that charged a
 * step-up scoped to one table's id in order to read a different table by it. A dialog that
 * only ever offers the fields belonging to the subject it is open on cannot build that
 * request in the first place.
 *
 * **By SHAPE**, because the shape is the price. `plan_reveal` charges `1` for a single-shaped
 * reveal however many columns it names, and the page size for a paged one — before the read,
 * never the row count. So the six brief columns cost one record between them and the four
 * profile columns cost one between them, and an operator who reveals the phone now and the
 * username in a minute has paid twice and written two audit rows for nothing.
 *
 * Every string here is OURS — chrome the panel wrote, never customer content. The revealed
 * VALUES never pass through this file.
 */

import { MAX_RECORDS_PER_REVEAL } from "@/api/constants";
import {
  REVEAL_FIELD_SHAPES,
  REVEAL_FIELD_SUBJECTS,
  REVEAL_FIELD_VALUES,
  revealShapeOf,
  type AuditReasonCode,
  type RevealedRecord,
  type RevealField,
  type RevealResponse,
  type RevealShape,
  type RevealSubjectType,
} from "@/api/reveal";
import type { TranslationPath } from "@/i18n/types";

/* -------------------------------------------------------------------------- */
/* Labels                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * What each column is.
 *
 * `recipient_name_display` and `_raw` are two different strings on one brief — the normalised
 * one the pipeline sang and the keystrokes the customer actually sent — and an operator
 * chasing a failed name verification needs to know which is which before spending a record.
 *
 * The `user_profiles` labels say WHOSE name it is. A user's screen shows the customer's own
 * Telegram name a few hundred pixels from the recipient names on their orders; a checkbox
 * reading only "first name" is an operator spending a step-up and an audit row to unmask the
 * wrong person.
 */

export const REVEAL_FIELD_LABEL_KEYS: Readonly<Record<RevealField, TranslationPath>> = {
  "briefs.recipient_name_display": "reveal.fields.recipientNameDisplay",
  "briefs.recipient_name_raw": "reveal.fields.recipientNameRaw",
  "briefs.recipient_lookup_key": "reveal.fields.recipientLookupKey",
  "briefs.recipient_candidates": "reveal.fields.recipientCandidates",
  "briefs.note": "reveal.fields.note",
  "briefs.approved_lyrics": "reveal.fields.approvedLyrics",
  "generation_attempts.stt_transcript": "reveal.fields.sttTranscript",
  "generation_attempts.name_candidate_text": "reveal.fields.nameCandidateText",
  "user_profiles.phone_e164": "reveal.fields.phone",
  "user_profiles.first_name": "reveal.fields.firstName",
  "user_profiles.last_name": "reveal.fields.lastName",
  "user_profiles.telegram_username": "reveal.fields.telegramUsername",
};

/** One line under each checkbox, saying what is about to be unmasked. */

export const REVEAL_FIELD_HINT_KEYS: Readonly<Record<RevealField, TranslationPath>> = {
  "briefs.recipient_name_display": "reveal.fieldHints.recipientNameDisplay",
  "briefs.recipient_name_raw": "reveal.fieldHints.recipientNameRaw",
  "briefs.recipient_lookup_key": "reveal.fieldHints.recipientLookupKey",
  "briefs.recipient_candidates": "reveal.fieldHints.recipientCandidates",
  "briefs.note": "reveal.fieldHints.note",
  "briefs.approved_lyrics": "reveal.fieldHints.approvedLyrics",
  "generation_attempts.stt_transcript": "reveal.fieldHints.sttTranscript",
  "generation_attempts.name_candidate_text": "reveal.fieldHints.nameCandidateText",
  "user_profiles.phone_e164": "reveal.fieldHints.phone",
  "user_profiles.first_name": "reveal.fieldHints.firstName",
  "user_profiles.last_name": "reveal.fieldHints.lastName",
  "user_profiles.telegram_username": "reveal.fieldHints.telegramUsername",
};

/** §12.3's closed reason vocabulary, in the words the select shows. */
export const REVEAL_REASON_KEYS: Readonly<Record<AuditReasonCode, TranslationPath>> = {
  customer_request: "reveal.reasons.customerRequest",
  gdpr_erasure: "reveal.reasons.gdprErasure",
  abuse_report: "reveal.reasons.abuseReport",
  support_investigation: "reveal.reasons.supportInvestigation",
  incident: "reveal.reasons.incident",
  bake_off: "reveal.reasons.bakeOff",
  routine_ops: "reveal.reasons.routineOps",
  other: "reveal.reasons.other",
};

/** The two shapes, named for a caption rather than for the wire. */
export const REVEAL_SHAPE_KEYS: Readonly<Record<RevealShape, TranslationPath>> = {
  single: "reveal.shapes.single",
  paged: "reveal.shapes.paged",
};

/* -------------------------------------------------------------------------- */
/* The groups                                                                  */
/* -------------------------------------------------------------------------- */

/** One offered column: what it is called, what it belongs to, and what it costs. */
export interface RevealFieldSpec {
  readonly field: RevealField;
  readonly labelKey: TranslationPath;
  readonly hintKey: TranslationPath;
  readonly subjectType: RevealSubjectType;
  readonly shape: RevealShape;
}

/** The twelve, in the spec's own order, each carrying its subject and its shape. */
export const REVEAL_FIELD_SPECS: readonly RevealFieldSpec[] = REVEAL_FIELD_VALUES.map(
  (field): RevealFieldSpec => ({
    field,
    labelKey: REVEAL_FIELD_LABEL_KEYS[field],
    hintKey: REVEAL_FIELD_HINT_KEYS[field],
    subjectType: REVEAL_FIELD_SUBJECTS[field],
    shape: REVEAL_FIELD_SHAPES[field],
  }),
);

/**
 * The brief's six columns — one record between them, whichever are ticked.
 *
 * Offered together for exactly that reason: ticking all six costs what ticking one costs.
 */
export const BRIEF_REVEAL_FIELDS: readonly RevealField[] = [
  "briefs.recipient_name_display",
  "briefs.recipient_name_raw",
  "briefs.recipient_lookup_key",
  "briefs.recipient_candidates",
  "briefs.note",
  "briefs.approved_lyrics",
];

/**
 * The attempts' free text — the paged shape, charged per page AND against the separate daily
 * conversations ceiling. Same subject (`order`) as the brief, a different price.
 */
export const ATTEMPT_REVEAL_FIELDS: readonly RevealField[] = [
  "generation_attempts.stt_transcript",
  "generation_attempts.name_candidate_text",
];

/**
 * The customer's own contact details — one record between them, whichever are ticked.
 *
 * The AVATAR is deliberately absent and is not a reveal at all: it is an ordinary read with no
 * step-up, no budget unit and no audit row. Do not add a media field here.
 */
export const USER_PROFILE_REVEAL_FIELDS: readonly RevealField[] = [
  "user_profiles.phone_e164",
  "user_profiles.first_name",
  "user_profiles.last_name",
  "user_profiles.telegram_username",
];

/**
 * A named group of columns that share one subject AND one shape, which is the unit a dialog
 * can offer as a set: everything in it is charged once, together.
 */
export interface RevealFieldGroup {
  readonly key: string;
  readonly title: string;
  /** Why these are one group — the sentence that stops an operator paying twice. */
  readonly note: string;
  readonly subjectType: RevealSubjectType;
  readonly shape: RevealShape;
  readonly fields: readonly RevealField[];
}

export const REVEAL_FIELD_GROUPS: readonly RevealFieldGroup[] = [
  {
    key: "brief",
    title: "the brief",
    note: "One record between them: revealing all six costs exactly what revealing one costs, and writes one audit row instead of six.",
    subjectType: "order",
    shape: "single",
    fields: BRIEF_REVEAL_FIELDS,
  },
  {
    key: "attempts",
    title: "the attempts' free text",
    note: "Paged: charged its page size before the read — a page of fifty that finds three still costs fifty — plus one against the daily conversations ceiling.",
    subjectType: "order",
    shape: "paged",
    fields: ATTEMPT_REVEAL_FIELDS,
  },
  {
    key: "profile",
    title: "the customer's contact details",
    note: "One record between them, on the profile row. This table is on no retention clock: it is kept while the account exists, and /forget deletes it outright.",
    subjectType: "user",
    shape: "single",
    fields: USER_PROFILE_REVEAL_FIELDS,
  },
];

/** Every column that can be asked for under this subject. Never offer anything else. */
export function revealFieldsFor(subjectType: RevealSubjectType): readonly RevealField[] {
  return REVEAL_FIELD_VALUES.filter((field) => REVEAL_FIELD_SUBJECTS[field] === subjectType);
}

/** The groups belonging to one subject, in offered order. */
export function revealGroupsFor(subjectType: RevealSubjectType): readonly RevealFieldGroup[] {
  return REVEAL_FIELD_GROUPS.filter((group) => group.subjectType === subjectType);
}

/** The fields in a stable, offered order — never the order a `Set` happens to iterate in. */
export function orderFields(
  offered: readonly RevealField[],
  chosen: ReadonlySet<RevealField>,
): RevealField[] {
  return offered.filter((field) => chosen.has(field));
}

/* -------------------------------------------------------------------------- */
/* Cost, before it is paid                                                     */
/* -------------------------------------------------------------------------- */

/** What one reveal will be charged, in the units the two separate ceilings count. */
export interface RevealCost {
  /** Against the hourly records ceiling. `1` for any well-formed single reveal. */
  readonly records: number;
  /** Against the daily conversations ceiling. `0` for every single-record reveal. */
  readonly conversations: number;
}

export const FREE_REVEAL: RevealCost = { records: 0, conversations: 0 };

/**
 * The charge, computed the way `plan_reveal` computes it, so the dialog can show it BEFORE
 * the operator confirms. An empty or mixed selection costs nothing because it is not a
 * request that can be sent.
 */
export function revealCost(
  fields: readonly RevealField[],
  limit: number | null = null,
): RevealCost {
  const shape = revealShapeOf(fields);
  if (shape === null) return FREE_REVEAL;
  if (shape === "single") return { records: 1, conversations: 0 };
  return { records: limit ?? MAX_RECORDS_PER_REVEAL, conversations: 1 };
}

/**
 * The cost in words. Spells the unit out deliberately: "1" beside a budget of 200 is a number
 * an operator has to decode; "1 record" beside "199 records left this hour" is one they can
 * act on.
 */
export function describeRevealCost(
  cost: RevealCost,
  t: (path: TranslationPath, params?: Record<string, string | number>) => string,
): string {
  const records = t(
    cost.records === 1 ? "reveal.dialog.costRecordsOne" : "reveal.dialog.costRecordsMany",
    { count: cost.records },
  );
  if (cost.conversations === 0) return records;
  const conversations = t(
    cost.conversations === 1
      ? "reveal.dialog.costConversationsOne"
      : "reveal.dialog.costConversationsMany",
    { count: cost.conversations },
  );
  return t("reveal.dialog.costAnd", { records, conversations });
}

/**
 * Whether a selection is one the server would accept — used to withhold the confirm.
 *
 * Three conditions, each mirroring a server refusal rather than inventing a client rule: at
 * least one field, one shape between them, and a reason code. A round trip that fails on
 * something the form could see is a form that has decided accountability is somebody else's
 * problem.
 */
export function canSubmitReveal(input: {
  readonly fields: readonly RevealField[];
  readonly reasonCode: AuditReasonCode | null;
}): boolean {
  return (
    input.fields.length > 0 && revealShapeOf(input.fields) !== null && input.reasonCode !== null
  );
}

/* -------------------------------------------------------------------------- */
/* Reading a result                                                            */
/* -------------------------------------------------------------------------- */

/** One column's plaintext on one record, with the record's own retention stamps. */
export interface RevealedFieldValue {
  readonly recordId: string;
  readonly createdAt: string;
  /** `null` means the COLUMN IS NULL — purged, or never written. Never a mask, never `""`. */
  readonly value: unknown;
  readonly identityPurgedAt: string | null;
  readonly textPurgedAt: string | null;
}

/** Every record's value for one column, in the order the server returned them. */
export function revealedValuesOf(
  result: RevealResponse,
  field: RevealField,
): readonly RevealedFieldValue[] {
  return result.records.map((record: RevealedRecord) => ({
    recordId: record.recordId,
    createdAt: record.createdAt,
    value: record.fields[field] ?? null,
    identityPurgedAt: record.identityPurgedAt,
    textPurgedAt: record.textPurgedAt,
  }));
}

/**
 * A revealed value as text, for the one-line inline case.
 *
 * Strings pass through BYTE FOR BYTE. No trimming, no case folding, no normalisation: a
 * customer's `Gʻulom` must reach the screen as they typed it, on a panel that is
 * simultaneously reporting whether that name verified. Structures are printed as JSON rather
 * than summarised, because a summary of personal data is still personal data and a wrong one
 * is worse than none.
 */
export function formatRevealedValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null || value === undefined) return "";
  // `JSON.stringify` is typed as returning a string but returns `undefined` for values JSON
  // has no spelling of. The wire cannot carry one — this came from `JSON.parse` — so the
  // fallback is a guard against a future caller, not a case that happens today.
  const json: unknown = JSON.stringify(value);
  return typeof json === "string" ? json : "";
}
