/**
 * The segment document — the one JSON both `?segment=` and a campaign's audience carry — and
 * the base64url envelope it rides in.
 *
 * This is the client half of `bayram.admin.schemas.segment`. It owns the wire SHAPE and the
 * envelope, and it decides no audience whatsoever: which fields exist, which operator applies
 * to which kind and how many rules a document may carry are questions
 * `bayram.db.admin.segment` answers, published to this app as data by
 * `GET /api/segments/fields` (`api/segments.ts`). Nothing here is a second copy of that
 * registry, and nothing here may become one — a builder generated from a hand-kept list
 * eventually offers a field the compiler refuses, which is a 422 the operator cannot read.
 *
 * ## Three properties this module exists to hold
 *
 * **The token is byte-identical to the one Python mints.** `encode_segment` is
 * `json.dumps(..., separators=(",", ":"))` over `model_dump(by_alias=True, exclude_none=True)`
 * then `urlsafe_b64encode`, so this module emits keys in the model's declaration order, drops
 * exactly the `null`s pydantic drops, escapes non-ASCII the way `ensure_ascii=True` does and
 * keeps the `=` padding. It is not tidiness: an operator pastes a URL from the Users screen
 * into the wizard and the wizard sends the document back, and a token that re-encodes
 * differently is two react-query keys, two request-log lines and — the day a saved campaign is
 * compared against the preview it was approved from — two documents that must be equal by
 * value and are only ever compared as strings.
 *
 * **The decoder never throws.** `?segment=` is text a browser hands us: hand-edited, truncated
 * by a chat client, or from a build that spoke a version this one does not. Every one of those
 * is `null` — "no segment" — and the screen renders the unfiltered list, which is the same
 * posture `decode_segment` takes on the server (a `Result`, never an exception) and for the
 * same reason. A white screen over a bad query string is the one failure mode a filter cannot
 * recover from, because the URL that caused it is the URL the operator reloads.
 *
 * **A document this build cannot read is refused, not half-read.** The object schemas are
 * `.strict()`, mirroring `ApiModel`'s `extra="forbid"`, and the version is a literal rather
 * than a range. A node carrying both `field` and `match` matches neither branch of the union
 * here exactly as it matches neither model there, so no guess is made about which half was
 * meant — and a rule the server would refuse never renders in the builder as a filter the
 * operator believes is applied.
 *
 * ## What is deliberately NOT checked here
 *
 * The limits (`maxRules`, `maxDepth`, `maxValueMembers`, `maxAggregateRules`) travel on the
 * fields view and are the builder's to enforce as it edits — `countRules` and `segmentDepth`
 * below are what it counts with. Decoding does not apply them: a document that is over a limit
 * is still the document the operator wrote, and the honest thing is to show it and let the
 * server's refusal name the limit, rather than to silently drop half an audience.
 */

import { z } from "zod";

import {
  MAX_SEGMENT_CHARS,
  MAX_SEGMENT_KEY_CHARS,
  MAX_SEGMENT_VALUE_CHARS,
  SEGMENT_SCHEMA_VERSION,
} from "@/api/constants";

/* -------------------------------------------------------------------------- */
/* Vocabulary — verbatim from the server enums; a new member is added here first */
/* -------------------------------------------------------------------------- */

/**
 * `MatchMode` — how a group combines its children.
 *
 * `none` is the ONE negation this DSL has: there is no per-rule `negate`, so the NULL
 * semantics are reasoned about in a single place rather than re-derived per rule row.
 */
export const MATCH_MODE_VALUES = ["all", "any", "none"] as const;
export const matchModeSchema = z.enum(MATCH_MODE_VALUES);
export type MatchMode = z.infer<typeof matchModeSchema>;

/**
 * `SegmentOp` — every comparison a rule may make.
 *
 * A closed set, and which members apply is a per-FIELD question: `SegmentFieldView.ops` is
 * the allowlist the operator dropdown renders, never this list.
 */
export const SEGMENT_OP_VALUES = [
  "eq",
  "neq",
  "in",
  "not_in",
  "gt",
  "gte",
  "lt",
  "lte",
  "between",
  "is_true",
  "is_false",
  "is_null",
  "is_not_null",
  "within_last_days",
  "not_within_last_days",
  "within_next_days",
] as const;
export const segmentOpSchema = z.enum(SEGMENT_OP_VALUES);
export type SegmentOp = z.infer<typeof segmentOpSchema>;

/** `SortDirection`. Two members and no third — the server types it as a `Literal` pair. */
export const SORT_DIRECTION_VALUES = ["asc", "desc"] as const;
export const sortDirectionSchema = z.enum(SORT_DIRECTION_VALUES);
export type SortDirection = z.infer<typeof sortDirectionSchema>;

/**
 * The operators that carry no value at all (`RuleModel.value` stays `None` and `exclude_none`
 * drops it). A value editor must render nothing for these, and a rule must not keep a stale
 * value beside one — the encoder drops it, so a carried-over value is a lie the URL does not
 * tell.
 */
export const VALUELESS_OPS: readonly SegmentOp[] = [
  "is_true",
  "is_false",
  "is_null",
  "is_not_null",
];

/** Whether this operator takes an operand. The one place a value editor asks. */
export function takesValue(op: SegmentOp): boolean {
  return !VALUELESS_OPS.includes(op);
}

/**
 * The operators whose value is a LIST — `in`/`not_in` (any length, capped by
 * `maxValueMembers`) and `between` (exactly two bounds, in order).
 */
export const LIST_VALUE_OPS: readonly SegmentOp[] = ["in", "not_in", "between"];

export function takesListValue(op: SegmentOp): boolean {
  return LIST_VALUE_OPS.includes(op);
}

/* -------------------------------------------------------------------------- */
/* The document                                                                */
/* -------------------------------------------------------------------------- */

/**
 * One member of a rule's value. Bounded scalars and nothing else — a nested object is not a
 * value any operator takes.
 *
 * `boolean` is its own member rather than an alias for `1`: the compiler refuses a bool where
 * a number is wanted (`_as_int` rejects it explicitly), which is what stops
 * `{"field": "order_count", "op": "gte", "value": true}` compiling to `order_count >= 1`.
 */
export type RuleValue = boolean | number | string;

/** What a rule carries. `null`/absent for a no-operand operator; the list is flat. */
export type SegmentValue = RuleValue | readonly RuleValue[] | null;

/** What the result is ordered by. `key` is a NAME the registry resolves, never an expression. */
export interface SegmentSort {
  readonly key: string;
  readonly dir: SortDirection;
}

/** One leaf predicate: a registry key, an operator, and the operator's value. */
export interface SegmentRule {
  readonly field: string;
  readonly op: SegmentOp;
  readonly value?: SegmentValue | undefined;
}

/**
 * A nested boolean node, which must carry at least one rule.
 *
 * Only the NESTED case is this type; the root is {@link Segment} itself. An empty root means
 * "everyone" and an operator can see that the filter is cleared; an empty `any` buried two
 * levels down is invisibly TRUE and drags its group's negation with it, which is how a
 * campaign reaches the whole database while its author believes it was narrowed.
 */
export interface SegmentGroup {
  readonly match: MatchMode;
  readonly rules: readonly SegmentNode[];
}

/** A node is one or the other, never a hybrid — the two shapes are disjoint under `.strict()`. */
export type SegmentNode = SegmentRule | SegmentGroup;

/** A whole document: a version, the root group inline, and an optional sort. */
export interface Segment {
  readonly v: typeof SEGMENT_SCHEMA_VERSION;
  readonly match: MatchMode;
  /** Empty means everyone — the unfiltered list, and the only place empty is legal. */
  readonly rules: readonly SegmentNode[];
  /** Absent means the registry's own `defaultSort` (`joined_at` descending). */
  readonly sort?: SegmentSort | undefined;
}

/** The unfiltered document: everyone, in the default order. The value a builder starts from. */
export const EMPTY_SEGMENT: Segment = {
  v: SEGMENT_SCHEMA_VERSION,
  match: "all",
  rules: [],
};

export function isSegmentRule(node: SegmentNode): node is SegmentRule {
  return "field" in node;
}

export function isSegmentGroup(node: SegmentNode): node is SegmentGroup {
  return "match" in node;
}

/* -------------------------------------------------------------------------- */
/* Schemas — the shape refusals, mirroring pydantic's                          */
/* -------------------------------------------------------------------------- */

const ruleValueSchema = z.union([
  // `boolean` leads the union so JSON's `true` stays a boolean rather than being read as 1.
  z.boolean(),
  z.number().int(),
  z.string().max(MAX_SEGMENT_VALUE_CHARS),
]);

const segmentValueSchema = z.union([ruleValueSchema, z.array(ruleValueSchema)]).nullable();

/** `SortModel`. `dir` defaults the way the server's field default does. */
export const segmentSortSchema: z.ZodType<SegmentSort, z.ZodTypeDef, unknown> = z
  .object({
    key: z.string().max(MAX_SEGMENT_KEY_CHARS),
    dir: sortDirectionSchema.default("desc"),
  })
  .strict();

const segmentRuleSchema: z.ZodType<SegmentRule, z.ZodTypeDef, unknown> = z
  .object({
    field: z.string().max(MAX_SEGMENT_KEY_CHARS),
    op: segmentOpSchema,
    value: segmentValueSchema.optional(),
  })
  .strict();

/*
 * `z.lazy` because the two shapes are mutually recursive. The union is unordered on purpose:
 * `.strict()` makes a rule and a group disjoint, so nothing is decided by which branch is
 * tried first — the same property `extra="forbid"` buys the server.
 */
const segmentNodeSchema: z.ZodType<SegmentNode, z.ZodTypeDef, unknown> = z.lazy(() =>
  z.union([segmentRuleSchema, segmentGroupSchema]),
);

const segmentGroupSchema: z.ZodType<SegmentGroup, z.ZodTypeDef, unknown> = z
  .object({
    match: matchModeSchema,
    // At least one: see `SegmentGroup`'s doc on why an empty NESTED group is a refusal.
    rules: z.array(segmentNodeSchema).min(1),
  })
  .strict();

/**
 * The whole document.
 *
 * `v` is a LITERAL, not a range: a document from a build that renamed a field is a document
 * whose shape this one does not know, and reading it as if it were version 1 is how a campaign
 * targets something nobody wrote. The registry publishes the version it expects
 * (`SegmentFieldsView.version`); {@link isSupportedSegmentVersion} is what compares them.
 */
export const segmentSchema: z.ZodType<Segment, z.ZodTypeDef, unknown> = z
  .object({
    v: z.literal(SEGMENT_SCHEMA_VERSION),
    match: matchModeSchema,
    rules: z.array(segmentNodeSchema).default([]),
    sort: segmentSortSchema.optional(),
  })
  .strict();

/** Whether the version the server's registry asks for is the one this bundle speaks. */
export function isSupportedSegmentVersion(version: number): boolean {
  return version === SEGMENT_SCHEMA_VERSION;
}

/* -------------------------------------------------------------------------- */
/* The codec                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Serialise a document to the opaque base64url token `?segment=` carries.
 *
 * Byte-for-byte what `encode_segment` produces for the same document — see this module's
 * header for why that matters. Three details carry that promise and none of them is
 * cosmetic: keys are written in the pydantic models' declaration order, a `null`/absent
 * `value` and an absent `sort` are dropped exactly as `exclude_none=True` drops them, and
 * `rules` is always present (an empty tuple is not `None`, so the server emits `[]` too).
 */
export function encodeSegment(segment: Segment): string {
  return toBase64Url(asciiJson(documentOf(segment)));
}

/**
 * Parse a document out of a query string. Returns `null` for anything that did not come from
 * us, and never throws.
 *
 * Every refusal collapses into that one `null`, exactly as the server collapses four into one
 * message: too long, not base64, not UTF-8, not JSON, not this shape, not this version. A
 * screen has one thing to do with all six — render the unfiltered list — and a taxonomy
 * nobody branches on is a taxonomy that goes stale.
 *
 * The length is checked BEFORE anything decodes, which is what bounds the work every later
 * step does; the outer `try` is the belt to that brace, because a pathologically nested
 * document is the one failure a recursive-descent parser reports by unwinding the stack.
 */
export function decodeSegment(raw: string | null | undefined): Segment | null {
  if (raw === null || raw === undefined || raw === "") return null;
  if (raw.length > MAX_SEGMENT_CHARS) return null;
  try {
    const json = fromBase64Url(raw);
    if (json === null) return null;
    return parseSegmentDocument(JSON.parse(json));
  } catch {
    return null;
  }
}

/**
 * A document that arrived as JSON rather than as a token — a campaign's frozen audience, read
 * back off `GET /api/broadcasts/{id}`. Same refusals, same `null`, and it never throws either.
 */
export function parseSegmentDocument(value: unknown): Segment | null {
  try {
    const parsed = segmentSchema.safeParse(value);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/**
 * The token for a URL or a react-query key, or `null` when there is nothing to filter on.
 *
 * An unfiltered document is not a filter: `?segment=` carrying "everyone" would be a second
 * spelling of the plain list — two cache keys and two log lines for one question — so an
 * empty root with no sort omits the parameter entirely. A sort alone still travels, because a
 * sorted walk is a different request from an unsorted one.
 */
export function segmentToken(segment: Segment | null | undefined): string | null {
  if (segment === null || segment === undefined) return null;
  if (isSegmentEmpty(segment) && segment.sort === undefined) return null;
  return encodeSegment(segment);
}

/* -------------------------------------------------------------------------- */
/* Reading a document                                                          */
/* -------------------------------------------------------------------------- */

/**
 * How many LEAF rules the document carries, at every depth. What `maxRules` bounds, and what
 * an "N filters" chip count must say: counting the one `segment` URL key instead would let
 * "Clear all 1 filter" stand over a nine-clause audience.
 */
export function countRules(segment: Segment): number {
  return segment.rules.reduce((total, node) => total + countNodeRules(node), 0);
}

/**
 * How deep the document nests, counting the root group as one level — the same arithmetic
 * `_depth` does, so this number and `maxDepth` are comparable without an off-by-one.
 */
export function segmentDepth(segment: Segment): number {
  return nodeDepth({ match: segment.match, rules: segment.rules });
}

/** Whether the root carries no rules at all — "everyone", and the only legal empty. */
export function isSegmentEmpty(segment: Segment | null | undefined): boolean {
  return segment === null || segment === undefined || segment.rules.length === 0;
}

/** Every leaf rule in the document, in reading order. For chips and for per-field counts. */
export function segmentRules(segment: Segment): readonly SegmentRule[] {
  const found: SegmentRule[] = [];
  collectRules(segment.rules, found);
  return found;
}

/* -------------------------------------------------------------------------- */
/* internals                                                                   */
/* -------------------------------------------------------------------------- */

function countNodeRules(node: SegmentNode): number {
  if (isSegmentRule(node)) return 1;
  return node.rules.reduce((total, child) => total + countNodeRules(child), 0);
}

function nodeDepth(node: SegmentNode): number {
  if (isSegmentRule(node)) return 0;
  return 1 + node.rules.reduce((deepest, child) => Math.max(deepest, nodeDepth(child)), 0);
}

function collectRules(nodes: readonly SegmentNode[], found: SegmentRule[]): void {
  for (const node of nodes) {
    if (isSegmentRule(node)) {
      found.push(node);
      continue;
    }
    collectRules(node.rules, found);
  }
}

/** One JSON-ready object per model, with the keys in the order pydantic declares them. */
function documentOf(segment: Segment): Record<string, unknown> {
  const document: Record<string, unknown> = {
    v: segment.v,
    match: segment.match,
    rules: segment.rules.map(nodeDocumentOf),
  };
  // `exclude_none`: an absent sort is not a sort, and spelling out the default would ride in
  // every "next page" link this parameter travels with.
  if (segment.sort !== undefined) {
    document["sort"] = { key: segment.sort.key, dir: segment.sort.dir };
  }
  return document;
}

function nodeDocumentOf(node: SegmentNode): Record<string, unknown> {
  if (isSegmentGroup(node)) {
    return { match: node.match, rules: node.rules.map(nodeDocumentOf) };
  }
  const rule: Record<string, unknown> = { field: node.field, op: node.op };
  if (node.value !== undefined && node.value !== null) {
    rule["value"] = node.value;
  }
  return rule;
}

/**
 * `json.dumps(..., separators=(",", ":"))` — which is `ensure_ascii=True` by default.
 *
 * `JSON.stringify` is already separator-compact but leaves non-ASCII as literal characters,
 * so anything outside `\x20`–`\x7e` is escaped here the way CPython's `ESCAPE_ASCII` escapes
 * it. Astral characters come out as the same surrogate pair, because a JS string is UTF-16 and
 * Python writes the pair too. Today every legal value is ASCII (enum members, wizard steps,
 * RFC 3339 instants), so this changes no byte anybody has seen — it is here so the promise
 * survives the first field whose values are not.
 */
function asciiJson(value: unknown): string {
  return JSON.stringify(value).replace(
    /[^ -~]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

/** UTF-8, then base64url WITH its padding — `base64.urlsafe_b64encode` keeps the `=`. */
function toBase64Url(json: string): string {
  const bytes = new TextEncoder().encode(json);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_");
}

/**
 * The inverse, tolerant of a stripped padding — a URL-safe encoder elsewhere may have dropped
 * it, which is the same allowance `decode_segment` makes. `null` for anything that is not
 * base64url or is not UTF-8; `fatal: true` is what makes the second half of that true rather
 * than a string full of replacement characters that then fails to parse as JSON for the wrong
 * reason.
 */
function fromBase64Url(raw: string): string | null {
  try {
    const standard = raw.replaceAll("-", "+").replaceAll("_", "/");
    const padded = standard + "=".repeat((4 - (standard.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}
