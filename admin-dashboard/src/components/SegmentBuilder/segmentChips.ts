/**
 * A segment, as the row of removable chips that already sits under every list on this console.
 *
 * `FilterChips` states a FIELD and its VALUE in words — "Provider: gemini", never "gemini" —
 * because a filter an operator cannot see is a filter they will read a wrong conclusion
 * through. A segment is the same problem one order of magnitude up: it lives in the URL as one
 * opaque base64 token, so without this the whole audience is invisible and "Clear all 1 filter"
 * stands over a nine-clause document.
 *
 * Three rules, all of them about not lying:
 *
 * **The count is LEAF RULES, at every depth.** `activeFilterCount` must never be "1 segment" —
 * {@link segmentFilterCount} is `countRules`, so nine clauses read as nine.
 *
 * **A nested rule says which group it is in.** A chip lifted out of an `any` group and shown
 * beside the `all` rules reads as one more thing every account must match, which inverts the
 * audience. So a nested chip is prefixed with its own group's mode — "Any · Songs delivered:
 * at least 3" — and the root's own mode is on the group label.
 *
 * **Removing a chip removes exactly that rule.** `removeAt` prunes a nested group its removal
 * emptied, because an empty nested group is a 422 and an operator who deleted one rule did not
 * ask for a document the server refuses.
 */

import type { SegmentFieldView } from "@/api/segments";
import type { FilterChip } from "@/components/FilterChips";
import {
  countRules,
  isSegmentGroup,
  isSegmentRule,
  takesValue,
  type MatchMode,
  type RuleValue,
  type Segment,
  type SegmentNode,
  type SegmentRule,
  type SegmentValue,
} from "@/lib/segmentCodec";

import { formatInstantDay } from "./instants";
import {
  connective,
  fieldLabel,
  matchLabel,
  memberLabel,
  opLabel,
  type Translate,
} from "./segmentLabels";
import { pathKey, removeAt, type SegmentPath } from "./segmentTree";

export interface SegmentChipOptions {
  readonly segment: Segment;
  /** The registry, keyed. A rule on a key the server no longer publishes still gets a chip. */
  readonly fields: ReadonlyMap<string, SegmentFieldView>;
  readonly t: Translate;
  /** The operator's locale, for the dates inside a chip. `useI18n((state) => state.locale)`. */
  readonly locale: string;
  /** Handed the document with that one rule gone. */
  readonly onChange: (next: Segment) => void;
}

/** How many filters are actually applied: leaf rules, at every depth, never the one URL key. */
export function segmentFilterCount(segment: Segment): number {
  return countRules(segment);
}

/** Names the chip row for assistive tech, including the root's own combining mode. */
export function segmentChipsLabel(t: Translate, segment: Segment): string {
  return `${t("segments.chips.label")} — ${matchLabel(t, segment.match)}`;
}

/** One chip per leaf rule, in reading order. */
export function buildSegmentChips(options: SegmentChipOptions): readonly FilterChip[] {
  const { segment, onChange } = options;
  const chips: FilterChip[] = [];
  collect(segment.rules, [], segment.match, options, chips, onChange);
  return chips;
}

/**
 * One rule as a field and a value, both in words.
 *
 * "Songs delivered" / "is at least 3", "First contact" / "is between 1 Jun 2026 and 1 Jul
 * 2026", "Last activity" / "not in the last 90 days". The operator is folded into the VALUE
 * half so the field half stays the field, which is what `FilterChips` renders in bold.
 */
export function describeSegmentRule(
  rule: SegmentRule,
  options: {
    readonly field: SegmentFieldView | undefined;
    readonly t: Translate;
    readonly locale: string;
  },
): { readonly field: string; readonly value: string } {
  const { field, t } = options;
  const kind = field?.kind ?? null;
  const name = fieldLabel(t, rule.field);
  const op = opLabel(t, rule.op, kind);
  if (!takesValue(rule.op)) return { field: name, value: op };
  const rendered = renderValue(rule, options);
  if (rendered === "") return { field: name, value: op };
  // Composed through the catalogue rather than concatenated, because the two halves do not
  // read in the same ORDER in every language: English puts the operator first ("is at least
  // 3"), Uzbek puts the value first ("3 dan kam emas").
  return { field: name, value: t("segments.chips.rule", { op, value: rendered }) };
}

/* -------------------------------------------------------------------------- */
/* internals                                                                   */
/* -------------------------------------------------------------------------- */

function collect(
  nodes: readonly SegmentNode[],
  path: SegmentPath,
  match: MatchMode,
  options: SegmentChipOptions,
  chips: FilterChip[],
  onChange: (next: Segment) => void,
): void {
  const { segment, fields, t, locale } = options;
  nodes.forEach((node, index) => {
    const here = [...path, index];
    if (isSegmentGroup(node)) {
      collect(node.rules, here, node.match, options, chips, onChange);
      return;
    }
    if (!isSegmentRule(node)) return;
    const described = describeSegmentRule(node, { field: fields.get(node.field), t, locale });
    // A rule nested inside a group carries that group's connective, or the chip reads as one
    // more thing EVERY account must match — which is the opposite of what an `any` group says.
    const prefix = path.length === 0 ? "" : `${matchLabel(t, match)} · `;
    chips.push({
      id: pathKey(here),
      field: `${prefix}${described.field}`,
      value: described.value,
      onRemove: () => {
        onChange(removeAt(segment, here));
      },
    });
  });
}

function renderValue(
  rule: SegmentRule,
  options: {
    readonly field: SegmentFieldView | undefined;
    readonly t: Translate;
    readonly locale: string;
  },
): string {
  const { t } = options;
  const value = rule.value;

  if (
    rule.op === "within_last_days" ||
    rule.op === "not_within_last_days" ||
    rule.op === "within_next_days"
  ) {
    return typeof value === "number" ? t("segments.value.daysPreset", { days: value }) : "";
  }

  if (isList(value)) {
    const members = value;
    if (rule.op === "between") {
      const low = members[0];
      const high = members[1];
      if (low === undefined || high === undefined) return "";
      return `${one(low, options)} – ${one(high, options)}`;
    }
    // `in`/`not_in` is an OR within one field, whatever the enclosing group says.
    const joiner = ` ${connective(t, "any")} `;
    return members.map((member) => one(member, options)).join(joiner);
  }

  if (value === undefined || value === null) return "";
  return one(value, options);
}

/**
 * A type guard rather than a bare `Array.isArray`, so the NEGATIVE branch narrows too: TS
 * cannot subtract a `readonly` array from a union on `Array.isArray` alone, and the scalar
 * branch below has to know it is holding a scalar.
 */
function isList(value: SegmentValue | undefined): value is readonly RuleValue[] {
  return Array.isArray(value);
}

function one(
  member: RuleValue,
  options: {
    readonly field: SegmentFieldView | undefined;
    readonly t: Translate;
    readonly locale: string;
  },
): string {
  const { field, t, locale } = options;
  if (field?.kind === "instant") return formatInstantDay(member, locale);
  if (field?.kind === "enum") return memberLabel(t, field.key, String(member));
  return String(member);
}
