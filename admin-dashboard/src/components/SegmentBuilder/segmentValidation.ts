/**
 * Every refusal the server would make, made here first — with the offending rule pointed at.
 *
 * A 422 from `/api/segments/preview` names a parameter (`segment`) and a limit, and that is
 * all it can name: the compiler deliberately keeps the caller's VALUE out of the error
 * context, and it has no idea which row of a builder the operator was looking at. So an
 * operator who breaches `maxAggregateRules` on their ninth rule gets "a value list may name at
 * most 50 members" attached to nothing, after a round trip, with the audience count blanked.
 * That is the failure this module exists to prevent: the same rules, applied on every
 * keystroke, each one carrying the PATH of the rule that broke it.
 *
 * The refusals are transcribed from `hbd/db/admin/segment.py` — `_check_limits`, `_as_members`,
 * `_as_days`, `_as_pair`, `_compile_rule`'s registry lookup and capability check, and
 * `_check_sort`'s `SORT_KEYS` membership — plus the two `GroupModel`/`SegmentModel` shape rules
 * (`a group must carry at least one rule`, and the version literal). Where the server and this
 * disagree the SERVER wins: nothing here blocks a request, it only says what will happen. A
 * document that is already over a limit still renders and still encodes, because a document
 * the operator cannot see is a document they cannot fix.
 *
 * Issues are DATA, not sentences. The codes below are formatted by
 * {@link formatSegmentIssue} against the locale catalogue, so the same check reads in three
 * languages and a test can assert on the code rather than on the copy.
 */

import type { SegmentFieldView, SegmentLimitsView } from "@/api/segments";
import {
  countRules,
  isSegmentGroup,
  isSegmentRule,
  isSupportedSegmentVersion,
  segmentDepth,
  takesListValue,
  takesValue,
  type Segment,
  type SegmentNode,
  type SegmentRule,
} from "@/lib/segmentCodec";

import { fieldLabel, type Translate } from "./segmentLabels";
import { aggregateRuleCount, pathKey, type SegmentPath } from "./segmentTree";

/** `MIN_RELATIVE_DAYS`/`MAX_RELATIVE_DAYS` — the bounds on `n` for the three relative operators. */
export const MIN_RELATIVE_DAYS = 1;
export const MAX_RELATIVE_DAYS = 3650;

/** Which refusal this is. One code per check the server makes, and no code without one. */
export type SegmentIssueCode =
  | "maxRules"
  | "maxDepth"
  | "maxValueMembers"
  | "maxAggregateRules"
  | "emptyGroup"
  | "missingValue"
  | "unknownField"
  | "unavailableField"
  | "unsupportedOp"
  | "betweenIncomplete"
  | "betweenOrder"
  | "daysOutOfRange"
  | "unsortableKey"
  | "versionMismatch";

export interface SegmentIssue {
  readonly code: SegmentIssueCode;
  /**
   * The rule or group this is about. `[]` is the document as a whole — the three limits and
   * the version, which no single row is responsible for.
   */
  readonly path: SegmentPath;
  /** The registry key at fault, where one rule is at fault. */
  readonly field?: string | undefined;
  /** The server's bound, and what the document actually carries. Both are numbers or absent. */
  readonly limit?: number | undefined;
  readonly actual?: number | undefined;
}

/**
 * Every refusal this document would earn, in reading order, document-wide issues first.
 *
 * `fields` is the registry as a map: a miss is `unknownField`, which is what a rule composed
 * against an older build of the server looks like. It is reported, never dropped — a rule that
 * disappears from the editor is a narrowing the operator did not make.
 */
export function segmentIssues(
  segment: Segment,
  options: {
    readonly fields: ReadonlyMap<string, SegmentFieldView>;
    readonly limits: SegmentLimitsView;
    /** `SegmentFieldsView.version`, when the registry has been read. */
    readonly version?: number | undefined;
  },
): readonly SegmentIssue[] {
  const { fields, limits, version } = options;
  const issues: SegmentIssue[] = [];

  if (version !== undefined && !isSupportedSegmentVersion(version)) {
    issues.push({ code: "versionMismatch", path: [], actual: version, limit: segment.v });
  }

  const rules = countRules(segment);
  if (rules > limits.maxRules) {
    issues.push({ code: "maxRules", path: [], limit: limits.maxRules, actual: rules });
  }

  const depth = segmentDepth(segment);
  if (depth > limits.maxDepth) {
    issues.push({ code: "maxDepth", path: [], limit: limits.maxDepth, actual: depth });
  }

  const aggregates = aggregateRuleCount(segment, fields);
  if (aggregates > limits.maxAggregateRules) {
    issues.push({
      code: "maxAggregateRules",
      path: [],
      limit: limits.maxAggregateRules,
      actual: aggregates,
    });
  }

  if (segment.sort !== undefined) {
    const sortField = fields.get(segment.sort.key);
    if (sortField === undefined || !sortField.sortable) {
      issues.push({ code: "unsortableKey", path: [], field: segment.sort.key });
    }
  }

  walk(segment.rules, [], fields, limits, issues);
  return issues;
}

/** Whether this document is one the server would accept. */
export function isSegmentValid(
  segment: Segment,
  options: {
    readonly fields: ReadonlyMap<string, SegmentFieldView>;
    readonly limits: SegmentLimitsView;
    readonly version?: number | undefined;
  },
): boolean {
  return segmentIssues(segment, options).length === 0;
}

/** The issues that belong to exactly one node, for the row that must show them. */
export function issuesAt(
  issues: readonly SegmentIssue[],
  path: SegmentPath,
): readonly SegmentIssue[] {
  const key = pathKey(path);
  return issues.filter((issue) => pathKey(issue.path) === key);
}

/**
 * One issue as a sentence.
 *
 * The field is named by its LABEL rather than its key — the operator chose "Songs delivered"
 * from a list and never saw `delivered_order_count` — and falls back to the key when this
 * bundle has no phrase for it, which is the same fallback the field list itself makes.
 */
export function formatSegmentIssue(t: Translate, issue: SegmentIssue): string {
  const params: Record<string, string | number> = {
    field: issue.field === undefined ? "" : fieldLabel(t, issue.field),
    limit: issue.limit ?? 0,
    actual: issue.actual ?? 0,
    expected: issue.limit ?? 0,
    min: MIN_RELATIVE_DAYS,
    max: MAX_RELATIVE_DAYS,
  };
  return t(`segments.issues.${issue.code}`, params);
}

/* -------------------------------------------------------------------------- */
/* internals                                                                   */
/* -------------------------------------------------------------------------- */

function walk(
  nodes: readonly SegmentNode[],
  path: SegmentPath,
  fields: ReadonlyMap<string, SegmentFieldView>,
  limits: SegmentLimitsView,
  issues: SegmentIssue[],
): void {
  nodes.forEach((node, index) => {
    const here = [...path, index];
    if (isSegmentGroup(node)) {
      // The root may be empty and means everyone; a NESTED empty group is silently TRUE and
      // drags its parent's negation with it, which is how a campaign reaches the whole
      // database while its author believes it was narrowed.
      if (node.rules.length === 0) issues.push({ code: "emptyGroup", path: here });
      walk(node.rules, here, fields, limits, issues);
      return;
    }
    if (isSegmentRule(node)) ruleIssues(node, here, fields, limits, issues);
  });
}

function ruleIssues(
  rule: SegmentRule,
  path: SegmentPath,
  fields: ReadonlyMap<string, SegmentFieldView>,
  limits: SegmentLimitsView,
  issues: SegmentIssue[],
): void {
  const field = fields.get(rule.field);
  if (field === undefined) {
    issues.push({ code: "unknownField", path, field: rule.field });
    return;
  }
  if (!field.isAvailable) {
    issues.push({ code: "unavailableField", path, field: rule.field });
  }
  if (!field.ops.includes(rule.op)) {
    issues.push({ code: "unsupportedOp", path, field: rule.field });
    return;
  }

  if (!takesValue(rule.op)) return;

  const value = rule.value;

  if (rule.op === "between") {
    if (!Array.isArray(value) || value.length !== 2) {
      issues.push({ code: "betweenIncomplete", path, field: rule.field });
      return;
    }
    const low: unknown = value[0];
    const high: unknown = value[1];
    if (!isFilled(low) || !isFilled(high)) {
      issues.push({ code: "betweenIncomplete", path, field: rule.field });
      return;
    }
    if (comparableAfter(low, high)) {
      issues.push({ code: "betweenOrder", path, field: rule.field });
    }
    return;
  }

  if (takesListValue(rule.op)) {
    if (!Array.isArray(value) || value.length === 0) {
      issues.push({ code: "missingValue", path, field: rule.field });
      return;
    }
    if (value.length > limits.maxValueMembers) {
      issues.push({
        code: "maxValueMembers",
        path,
        field: rule.field,
        limit: limits.maxValueMembers,
        actual: value.length,
      });
    }
    return;
  }

  if (
    rule.op === "within_last_days" ||
    rule.op === "not_within_last_days" ||
    rule.op === "within_next_days"
  ) {
    if (
      typeof value !== "number" ||
      !Number.isInteger(value) ||
      value < MIN_RELATIVE_DAYS ||
      value > MAX_RELATIVE_DAYS
    ) {
      issues.push({ code: "daysOutOfRange", path, field: rule.field });
    }
    return;
  }

  if (!isFilled(value)) {
    issues.push({ code: "missingValue", path, field: rule.field });
  }
}

/** A value the operator has actually supplied. `""` is a half-typed box, not a value. */
function isFilled(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  return typeof value !== "string" || value !== "";
}

/**
 * Whether a `between` ends before it starts — the server's own `_as_pair` check.
 *
 * Only compares two values of the same shape: an instant against an instant (lexicographic on
 * RFC 3339 is chronological once both carry an offset, and both bounds this builder mints are
 * `Z`), a number against a number. Anything else is left to the server, which has the types.
 */
function comparableAfter(low: unknown, high: unknown): boolean {
  if (typeof low === "number" && typeof high === "number") return high < low;
  if (typeof low === "string" && typeof high === "string") {
    const start = Date.parse(low);
    const end = Date.parse(high);
    if (Number.isNaN(start) || Number.isNaN(end)) return false;
    return end < start;
  }
  return false;
}
