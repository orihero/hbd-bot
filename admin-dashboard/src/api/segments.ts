/**
 * `/api/segments` — the filter vocabulary, and how many people one filter selects.
 *
 * Transcribed from `hbd/admin/routers/segments.py` and `hbd/admin/schemas/segment.py`. Two
 * routes, two permissions, and the split is the whole design:
 *
 * **`GET /segments/fields` is the builder's source of truth** (`broadcast.read`). The registry
 * is an ALLOWLIST — a key that is not in it is unaddressable under any spelling, and the four
 * identity columns a campaign must never target are refused there by name. So the rule builder
 * is generated from this response and from nothing else. **Never derive a field list from a
 * row schema, and never hard-code one here**: a client-side copy drifts in the one direction
 * that matters — it keeps offering a field after the server withdrew it, and the operator
 * composes an audience the compiler then refuses.
 *
 * **`GET /segments/preview` is the number a human authorises a send against** (`records.read`
 * — the same cell as the list it counts, deliberately, because an audience total must not be
 * harder to obtain than the accounts it counts). `matched` is an exact `count(*)`, never the
 * list's bounded `total`: `10,000+` is a refusal to answer, not an approximation, and nobody
 * can approve a broadcast against a ceiling.
 *
 * ## Two things this wire does not carry, and both are deliberate
 *
 * **No customer row.** The preview answers with counts only. There is no `sample` of matching
 * accounts: `UserView` carries the raw Telegram id by design, and a second differently-masked
 * projection of the same row would be a second copy to keep true. An operator who wants to see
 * the people opens the Users screen with the SAME `?segment=` token — same document, same
 * compiler, same permission.
 *
 * **The three refusal counts overlap; never add them up.** `skippedBlocked` is our own bar and
 * `skippedBotBlocked` is the customer's, and one account can be both. Only `reachable` is a
 * complement of `matched`, and it is the number a send would actually attempt — so it is the
 * number a wizard gates on and the one a review step restates.
 */

import { z } from "zod";

import {
  encodeSegment,
  segmentOpSchema,
  segmentSortSchema,
  type Segment,
  type SegmentOp,
  type SegmentSort,
} from "@/lib/segmentCodec";

import { request, type ApiResult } from "./client";
import { SEGMENT_FIELDS_PATH, SEGMENT_PREVIEW_PATH } from "./constants";
import { appendParam, queryOf } from "./pagination";
import { LANGUAGE_VALUES, ORDER_STATE_VALUES, languageSchema, type Language } from "./users";

export type { Segment, SegmentOp, SegmentSort };

/* -------------------------------------------------------------------------- */
/* GET /api/segments/fields                                                    */
/* -------------------------------------------------------------------------- */

/**
 * `FieldKind` — what a field's values ARE, so the builder can render the right control.
 *
 * Part of the contract and the one thing a value editor switches on: `instant` is a date
 * control, `enum` a multi-select, `int` a number, `bool` a yes/no with no value at all, and
 * `token` a closed vocabulary the bot writes (`wizard_step`, and it takes `in` alone).
 */
export const FIELD_KIND_VALUES = ["int", "bool", "enum", "instant", "token"] as const;
export const fieldKindSchema = z.enum(FIELD_KIND_VALUES);
export type FieldKind = z.infer<typeof fieldKindSchema>;

/**
 * One entry of the registry, as the rule builder reads it.
 *
 * `doc` is the field's own safety argument, carried verbatim from the server rather than
 * paraphrased into a UI label — an operator choosing an audience should be able to read what
 * the field actually means, and a second copy of that sentence in TypeScript is a second copy
 * to keep true. Render it; do not rewrite it.
 */
export const segmentFieldViewSchema = z.object({
  key: z.string(),
  kind: fieldKindSchema,
  /** Sorted by the server, so two reads of an unchanged registry are byte-identical. */
  ops: z.array(segmentOpSchema),
  /** Whether this key may appear in `sort` — read from `SORT_KEYS`, not from the field alone. */
  sortable: z.boolean(),
  /**
   * True when the predicate is a correlated subquery. What makes a rule expensive, what
   * `maxAggregateRules` counts, and what makes `?withTotal=` refuse to run beside a sort on
   * it — an SPA that could not see it would discover both by getting a 422.
   */
  isAggregate: z.boolean(),
  /** The table this field needs, or `null` when it always works. */
  capability: z.string().nullable(),
  /**
   * Whether THIS deployment has that table. A field whose capability is missing is still
   * listed: show it disabled rather than pretending it was never designed, because a rule on
   * it is a refusal naming the field, and "the table is not installed here" must not look like
   * "nobody matched".
   */
  isAvailable: z.boolean(),
  doc: z.string(),
});
export type SegmentFieldView = z.infer<typeof segmentFieldViewSchema>;

/** `SEGMENT_LIMITS`, so the editor stops before the server does. Every breach is a refusal. */
export const segmentLimitsViewSchema = z.object({
  /** Total LEAF rules across every group. */
  maxRules: z.number().int(),
  /** Root plus nested levels, counted the way `segmentDepth` counts. */
  maxDepth: z.number().int(),
  /** `in`/`not_in` list length. */
  maxValueMembers: z.number().int(),
  /** Rules whose field is a correlated subquery — the only limit here that is about cost. */
  maxAggregateRules: z.number().int(),
});
export type SegmentLimitsView = z.infer<typeof segmentLimitsViewSchema>;

/** `GET /api/segments/fields` — the whole vocabulary of a segment document. */
export const segmentFieldsViewSchema = z.object({
  /**
   * The document version a client must send. Published rather than assumed, so a bundle that
   * speaks an older shape can SAY so instead of composing a document the server refuses —
   * compare it with `isSupportedSegmentVersion`.
   */
  version: z.number().int(),
  /** What a page is ordered by when nobody said: `joined_at` descending. */
  defaultSort: segmentSortSchema,
  limits: segmentLimitsViewSchema,
  /** Ordered by key. */
  fields: z.array(segmentFieldViewSchema),
});
export type SegmentFieldsView = z.infer<typeof segmentFieldsViewSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/segments/preview                                                   */
/* -------------------------------------------------------------------------- */

/** One language and how many of the audience read it. A language nobody reads is ABSENT. */
export const languageCountSchema = z.object({
  language: languageSchema,
  count: z.number().int(),
});
export type LanguageCount = z.infer<typeof languageCountSchema>;

/**
 * How many people, and how many of them are reachable.
 *
 * `matched` is exact. `reachable` is what a send would attempt. The two `skipped*` counts
 * OVERLAP — see this module's header — so render them as reasons, never as a sum.
 */
export const segmentPreviewViewSchema = z.object({
  matched: z.number().int(),
  reachable: z.number().int(),
  /** Barred by US. */
  skippedBlocked: z.number().int(),
  /** Blocked by THEM. Opposite facts with opposite subjects; never collapse the two. */
  skippedBotBlocked: z.number().int(),
  /** The per-language split a message editor needs: one body per language present here. */
  byLanguage: z.array(languageCountSchema),
});
export type SegmentPreviewView = z.infer<typeof segmentPreviewViewSchema>;

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const SEGMENT_ENDPOINT = {
  fields: "GET /api/segments/fields",
  preview: "GET /api/segments/preview",
} as const;

/**
 * The registry. No database behind it, so it is cheap — but it is guarded (the vocabulary
 * names every dimension the panel can ask about a customer), and it is deployment-specific:
 * `isAvailable` answers for the deployment this bundle is actually talking to. Cache it for a
 * session; do not bake it into a build.
 */
export function getSegmentFields(signal?: AbortSignal): Promise<ApiResult<SegmentFieldsView>> {
  return request({
    endpoint: SEGMENT_ENDPOINT.fields,
    path: SEGMENT_FIELDS_PATH,
    schema: segmentFieldsViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * The exact audience for one document, and its eligibility breakdown.
 *
 * The document is encoded here rather than by the caller so that this preview and the
 * `?segment=` the Users screen walks are provably the same bytes. `null` — or a document with
 * no rules — asks for the whole population, which is the honest answer to an unfiltered
 * builder and is what an operator must see before they widen anything.
 *
 * There is no `limit` and no cursor: there is nothing here to page.
 */
export function previewSegment(
  segment: Segment | null,
  signal?: AbortSignal,
): Promise<ApiResult<SegmentPreviewView>> {
  const params = new URLSearchParams();
  appendParam(params, "segment", segment === null ? null : encodeSegment(segment));
  return request({
    endpoint: SEGMENT_ENDPOINT.preview,
    path: `${SEGMENT_PREVIEW_PATH}${queryOf(params)}`,
    schema: segmentPreviewViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* Reading the registry                                                        */
/* -------------------------------------------------------------------------- */

/**
 * The registry keyed for lookup — what a rule row resolves `rule.field` through to find its
 * kind, its operator set and its availability.
 *
 * A miss is `undefined` and means the server no longer publishes that key: render the rule as
 * unknown and let the operator delete it. Do not drop it silently — a rule that vanishes from
 * the editor is a narrowing the operator did not make.
 */
export function segmentFieldIndex(
  view: SegmentFieldsView,
): ReadonlyMap<string, SegmentFieldView> {
  return new Map(view.fields.map((field) => [field.key, field]));
}

/** Whether a field takes this operator. The registry's own set, never a per-kind guess. */
export function supportsOp(field: SegmentFieldView, op: SegmentOp): boolean {
  return field.ops.includes(op);
}

/**
 * The languages the audience actually reads, in the order the server counted them.
 *
 * The message step needs exactly this: one body per language PRESENT, because a campaign body
 * is written per language and a language with no readers is a body nobody should be made to
 * write.
 */
export function audienceLanguages(preview: SegmentPreviewView): readonly Language[] {
  return preview.byLanguage.map((entry) => entry.language);
}

/* -------------------------------------------------------------------------- */
/* The closed vocabularies the registry does NOT publish                       */
/* -------------------------------------------------------------------------- */

/**
 * `hbd.checkout.PlanStatus` — the four mutually-exclusive, exhaustive cases the compiler
 * lowers `plan_status` to.
 *
 * **There is no renewal in this product**: no auto-renew, no `renewed_at`, no recurring
 * billing. `lapsed` is therefore the only truthful spelling of "did not renew" — a plan that
 * ran out and was not bought again — and the label the builder shows must say that rather
 * than "did not renew", or a campaign goes out telling people their subscription lapsed when
 * they never had one.
 */
export const PLAN_STATUS_VALUES = ["none", "active", "exhausted", "lapsed"] as const;
export const planStatusSchema = z.enum(PLAN_STATUS_VALUES);
export type PlanStatus = z.infer<typeof planStatusSchema>;

/**
 * Which members each `enum` field accepts, keyed by registry key.
 *
 * `GET /api/segments/fields` publishes a field's KIND and its OPERATORS and stops there: the
 * members an `enum` compares against are resolved server-side through the enum class itself
 * (`_as_enum`), so an unknown member is a 422 before any SQL exists and the wire never has to
 * carry the list. A multi-select still has to offer something, so these three vocabularies —
 * and only these three — are transcribed from the enums the compiler actually calls:
 * `Language`, `OrderState` and {@link PLAN_STATUS_VALUES}.
 *
 * A key missing from this map is NOT an error and must not hide the field: the builder falls
 * back to a free-form value list, the operator types the member, and the server refuses a
 * typo the same way it refuses one from a select. That is the only shape in which a
 * client-side vocabulary is safe — an aid to typing, never the allowlist.
 */
export const SEGMENT_ENUM_MEMBERS: Readonly<Record<string, readonly string[]>> = {
  ui_language: LANGUAGE_VALUES,
  order_state: ORDER_STATE_VALUES,
  plan_status: PLAN_STATUS_VALUES,
};

/** The members this bundle can offer for a field, or `null` when it must ask the operator. */
export function segmentEnumMembers(fieldKey: string): readonly string[] | null {
  return SEGMENT_ENUM_MEMBERS[fieldKey] ?? null;
}
