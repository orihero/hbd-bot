/**
 * The reveal's vocabulary, and the arithmetic that makes its cost knowable BEFORE it is paid.
 *
 * §11.4 gives `RevealDialog` one non-obvious requirement: it "shows the record cost of the
 * reveal against the remaining budget **before** the operator confirms". That is only
 * possible because the charge is deterministic — `plan_reveal` charges `1` for a brief column
 * and the page size for the attempts' free text, before the read, and never the number of
 * rows it turned out to find. So the cost is a pure function of the chosen fields and the
 * page size, and it is computed here rather than inside a component, where it could not be
 * tested against the server's rule.
 *
 * **The labels are OURS.** Every string in this file is chrome the panel wrote, never
 * customer content, so `humaniseEnum`-style formatting is safe on them. The revealed VALUES
 * never come near here — they reach the DOM through `<NameText>` and nothing else.
 */

import {
  MAX_RECORDS_PER_REVEAL,
  REVEAL_FIELD_SHAPES,
  type AuditReasonCode,
  type RevealField,
  type RevealShape,
} from "@/api";

/**
 * What each column is, in an operator's words rather than the column's.
 *
 * `recipient_name_display` and `_raw` are two different strings on the same brief — the
 * normalised one the pipeline used and the one the customer actually typed — and an operator
 * chasing a failed verification wants to know which is which before spending a record on it.
 */
export const REVEAL_FIELD_LABELS: Readonly<Record<RevealField, string>> = {
  "briefs.recipient_name_display": "recipient name, as displayed",
  "briefs.recipient_name_raw": "recipient name, exactly as typed",
  "briefs.recipient_lookup_key": "recipient lookup key",
  "briefs.recipient_candidates": "recipient candidates",
  "briefs.note": "the note to the recipient",
  "briefs.approved_lyrics": "approved lyrics",
  "generation_attempts.stt_transcript": "voice-note transcripts",
  "generation_attempts.name_candidate_text": "name candidates, as heard",
};

/** One line under each checkbox saying what an operator is about to unmask. */
export const REVEAL_FIELD_HINTS: Readonly<Record<RevealField, string>> = {
  "briefs.recipient_name_display":
    "The name the pipeline sang. Masked to its first grapheme cluster everywhere else.",
  "briefs.recipient_name_raw":
    "The keystrokes the customer sent. The answer to “which apostrophe did they type”.",
  "briefs.recipient_lookup_key": "The folded key the name matcher compared against.",
  "briefs.recipient_candidates":
    "Every candidate spelling considered, with the strategy that produced it.",
  "briefs.note": "Free text the customer wrote about the recipient. On the 30-day clock.",
  "briefs.approved_lyrics": "The full lyric the customer approved.",
  "generation_attempts.stt_transcript":
    "What speech-to-text heard, one record per take. Paged and charged per page.",
  "generation_attempts.name_candidate_text":
    "The name text each attempt proposed, one record per take. Paged and charged per page.",
};

/**
 * The brief's six columns — one record between them, whichever are ticked.
 *
 * That is the single most useful fact about this group and it is why they are offered
 * together: `records_authorised` is `1` for a `single`-shaped reveal regardless of how many
 * fields it names, so ticking all six costs exactly what ticking one costs. An operator who
 * reveals the name now and the note in a minute pays twice and writes two audit rows.
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
 * The attempts' free text — the paged shape, charged per page and against the daily
 * conversation ceiling as well.
 *
 * §12.3's paged row is `chat_messages.body` and that table lands in Phase 3. Until it does,
 * these two columns are the paged, customer-authored free text that exists, and the shape is
 * identical: fifty records a page, a `nextCursor` that costs a fresh reveal, two budgets.
 */
export const ATTEMPT_REVEAL_FIELDS: readonly RevealField[] = [
  "generation_attempts.stt_transcript",
  "generation_attempts.name_candidate_text",
];

/**
 * §12.3's closed reason vocabulary, in the words the select shows.
 *
 * `reasonCode` is required and comes from `AuditReasonCode`; there is deliberately no
 * default here and none on the server. A default of "routine ops" would make the
 * accountability optional and the modal value meaningless — which is the failure the closed
 * vocabulary exists to avoid — so the dialog withholds its confirm until one is chosen.
 */
export const REVEAL_REASON_LABELS: Readonly<Record<AuditReasonCode, string>> = {
  customer_request: "the customer asked",
  gdpr_erasure: "erasure request",
  abuse_report: "abuse report",
  support_investigation: "support investigation",
  incident: "incident",
  bake_off: "strategy bake-off",
  routine_ops: "routine operations",
  other: "other — say why below",
};

/** The two shapes, named for a caption rather than for the wire. */
export const REVEAL_SHAPE_LABELS: Readonly<Record<RevealShape, string>> = {
  single: "one record",
  paged: "one page of records",
};

/** What one reveal will be charged, in the units the two budgets count. */
export interface RevealCost {
  /** Against `admin_reveal_records_per_hour`. Always ≥ 1 for a well-formed reveal. */
  readonly records: number;
  /** Against `admin_reveal_conversations_per_day`. `0` for every single-record reveal. */
  readonly conversations: number;
}

export const FREE: RevealCost = { records: 0, conversations: 0 };

/**
 * The one shape every chosen field agrees on, or `null` when they do not agree.
 *
 * `null` is a refusal the FORM makes, matching the server's: a request mixing a brief column
 * with an attempt column would have to charge one `recordCount` for two record shapes, and a
 * budget can only measure exposure if the number it is handed is the number of records the
 * caller is authorised to return. An empty selection is `null` too — nothing to charge.
 */
export function revealShapeOf(fields: readonly RevealField[]): RevealShape | null {
  const shapes = new Set(fields.map((field) => REVEAL_FIELD_SHAPES[field]));
  if (shapes.size !== 1) return null;
  const [only] = [...shapes];
  return only ?? null;
}

/**
 * What this reveal will cost, computed the way `plan_reveal` computes it.
 *
 * A `single` reveal is one record and touches no conversation counter, however many brief
 * columns are named. A `paged` reveal is charged its PAGE SIZE — `limit`, defaulting to the
 * fifty-record cap — plus one conversation, before the read and regardless of how many rows
 * exist. An empty or mixed selection costs nothing because it is not a request that can be
 * sent.
 */
export function revealCost(
  fields: readonly RevealField[],
  limit: number | null = null,
): RevealCost {
  const shape = revealShapeOf(fields);
  if (shape === null) return FREE;
  if (shape === "single") return { records: 1, conversations: 0 };
  return { records: limit ?? MAX_RECORDS_PER_REVEAL, conversations: 1 };
}

/**
 * The cost in words, for the line above the confirm button.
 *
 * Deliberately spells the unit out. "1" beside a budget of 200 is a number an operator has to
 * decode; "1 record" beside "199 of 200 records left this hour" is one they can act on.
 */
export function describeRevealCost(cost: RevealCost): string {
  const records = `${String(cost.records)} ${cost.records === 1 ? "record" : "records"}`;
  if (cost.conversations === 0) return records;
  const conversations = `${String(cost.conversations)} ${
    cost.conversations === 1 ? "conversation" : "conversations"
  }`;
  return `${records} and ${conversations}`;
}

/**
 * Whether a selection is one this API would accept — used to withhold the confirm button.
 *
 * Three conditions, and each mirrors a server refusal rather than inventing a client rule:
 * at least one field, one shape between them, and a `reasonCode`. Duplicate fields cannot
 * happen through a checkbox set, and the request builder re-derives the array from a `Set`
 * so it cannot happen through the cursor path either.
 */
export function canSubmitReveal(input: {
  readonly fields: readonly RevealField[];
  readonly reasonCode: AuditReasonCode | null;
}): boolean {
  return input.fields.length > 0 && revealShapeOf(input.fields) !== null && input.reasonCode !== null;
}

/** The fields in a stable, offered order — never the order a `Set` happens to iterate in. */
export function orderFields(
  offered: readonly RevealField[],
  chosen: ReadonlySet<RevealField>,
): RevealField[] {
  return offered.filter((field) => chosen.has(field));
}
