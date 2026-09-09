/**
 * Editing a segment document without mutating one.
 *
 * The builder is state-free by contract — the URL or the wizard owns the value and hands it
 * back through `onChange` — so every edit here is a pure function from one document to the
 * next, addressed by a **path**: the indexes to walk down `rules` from the root. `[2]` is the
 * root's third child; `[2, 0]` is the first child of that child, which must be a group.
 *
 * Two rules are enforced here rather than left to each call site:
 *
 * **A nested group is never left empty.** `GroupModel` refuses `rules: []` at any depth but
 * the root, so deleting the last rule out of a nested group would compose a document the
 * server answers with a 422 that names nothing the operator can see. {@link removeAt} prunes
 * the group instead, and prunes ITS parent if that emptied too. An empty ROOT is legal and
 * means everyone — the one place the builder must say so out loud rather than tidy it away.
 *
 * **Changing a field resets the operator and the value.** Carrying them over is how
 * `{"field": "joined_at", "op": "gte", "value": 3}` gets composed: an operator the new field
 * may not even take, over a value from a different kind entirely. {@link ruleWithField} picks
 * the new field's own first sensible operator and starts the value again.
 *
 * Nothing in this module reads the registry's LIMITS. `segmentValidation.ts` does that, and
 * the split is deliberate: an edit that breaches a limit still applies, and the breach is
 * named on screen. Refusing the keystroke instead leaves an operator holding a document they
 * cannot see the problem with.
 */

import type { SegmentFieldView, SegmentLimitsView } from "@/api/segments";
import {
  isSegmentGroup,
  isSegmentRule,
  takesListValue,
  takesValue,
  type MatchMode,
  type Segment,
  type SegmentGroup,
  type SegmentNode,
  type SegmentOp,
  type SegmentRule,
  type SegmentSort,
  type SegmentValue,
} from "@/lib/segmentCodec";

/** Indexes into `rules`, from the root down. `[]` is the root group itself. */
export type SegmentPath = readonly number[];

/** A stable string for a React key, an id or a chip. Paths are small and shallow by construction. */
export function pathKey(path: SegmentPath): string {
  return path.length === 0 ? "root" : path.join(".");
}

/** The path of a node's parent group. `[]` for a child of the root. */
export function parentPath(path: SegmentPath): SegmentPath {
  return path.slice(0, -1);
}

/** The children of the group at `path`, or `null` when the path names a rule or nothing. */
export function childrenAt(segment: Segment, path: SegmentPath): readonly SegmentNode[] | null {
  if (path.length === 0) return segment.rules;
  const node = nodeAt(segment, path);
  if (node === null || !isSegmentGroup(node)) return null;
  return node.rules;
}

/** The node at `path`, or `null` when nothing lives there. */
export function nodeAt(segment: Segment, path: SegmentPath): SegmentNode | null {
  let nodes: readonly SegmentNode[] = segment.rules;
  let found: SegmentNode | null = null;
  for (const index of path) {
    const next = nodes[index];
    if (next === undefined) return null;
    found = next;
    nodes = isSegmentGroup(next) ? next.rules : [];
  }
  return found;
}

/** What an edit does to the node it addresses: replace it, or (with `null`) delete it. */
type NodeUpdate = (node: SegmentNode) => SegmentNode | null;

function withoutAt(nodes: readonly SegmentNode[], index: number): readonly SegmentNode[] {
  return [...nodes.slice(0, index), ...nodes.slice(index + 1)];
}

function applyAt(
  nodes: readonly SegmentNode[],
  path: SegmentPath,
  update: NodeUpdate,
): readonly SegmentNode[] {
  const head = path[0];
  if (head === undefined) return nodes;
  const target = nodes[head];
  if (target === undefined) return nodes;

  if (path.length === 1) {
    const next = update(target);
    if (next === null) return withoutAt(nodes, head);
    return [...nodes.slice(0, head), next, ...nodes.slice(head + 1)];
  }

  if (!isSegmentGroup(target)) return nodes;
  const children = applyAt(target.rules, path.slice(1), update);
  // An emptied NESTED group is a 422, so it goes with its last rule rather than travelling.
  if (children.length === 0) return withoutAt(nodes, head);
  const replaced: SegmentGroup = { match: target.match, rules: children };
  return [...nodes.slice(0, head), replaced, ...nodes.slice(head + 1)];
}

/** Replace the node at `path`. A path that names nothing leaves the document untouched. */
export function replaceAt(segment: Segment, path: SegmentPath, node: SegmentNode): Segment {
  if (path.length === 0) return segment;
  return { ...segment, rules: applyAt(segment.rules, path, () => node) };
}

/** Delete the node at `path`, pruning any nested group its removal emptied. */
export function removeAt(segment: Segment, path: SegmentPath): Segment {
  if (path.length === 0) return segment;
  return { ...segment, rules: applyAt(segment.rules, path, () => null) };
}

/** Append a node to the group at `groupPath`. `[]` appends to the root. */
export function appendAt(segment: Segment, groupPath: SegmentPath, node: SegmentNode): Segment {
  if (groupPath.length === 0) {
    return { ...segment, rules: [...segment.rules, node] };
  }
  return {
    ...segment,
    rules: applyAt(segment.rules, groupPath, (target) => {
      if (!isSegmentGroup(target)) return target;
      return { match: target.match, rules: [...target.rules, node] };
    }),
  };
}

/** Change how a group combines its children. `[]` changes the root's own mode. */
export function setMatchAt(segment: Segment, path: SegmentPath, match: MatchMode): Segment {
  if (path.length === 0) return { ...segment, match };
  return {
    ...segment,
    rules: applyAt(segment.rules, path, (target) => {
      if (!isSegmentGroup(target)) return target;
      return { match, rules: target.rules };
    }),
  };
}

/**
 * Set or clear the document's sort.
 *
 * `null` DROPS the key rather than writing the registry's default into it: an absent `sort` is
 * shorter on the wire, is what `exclude_none` produces server-side, and — because
 * `segmentToken` treats an unfiltered, unsorted document as no parameter at all — is what
 * keeps the plain list one cache key instead of two.
 */
export function withSort(segment: Segment, sort: SegmentSort | null): Segment {
  if (sort !== null) return { ...segment, sort };
  // Rebuilt key by key rather than spread-and-delete: `exactOptionalPropertyTypes` makes
  // `sort: undefined` a different thing from an absent `sort`, and only the absence encodes.
  return { v: segment.v, match: segment.match, rules: segment.rules };
}

/** The empty document a cleared builder returns to, keeping the root's own combining mode. */
export function clearRules(segment: Segment): Segment {
  return { ...segment, rules: [] };
}

/* -------------------------------------------------------------------------- */
/* Building a rule                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Which operator a freshly-chosen field starts on.
 *
 * Ordered by what an operator most often means by that kind of field, filtered by what the
 * REGISTRY says this particular field takes — so the preference never widens the operator set,
 * it only picks inside it. The registry's own `ops` array is the fallback and is already
 * sorted, which is why an unlisted kind still lands somewhere legal.
 *
 * The four audiences this feature was asked for by name land on three of these by default:
 * `plan_status` opens on `in`, `joined_at` on `between`, `delivered_order_count` on `gte`. The
 * fourth — "inactive for months" — wants `not_within_last_days`, which is not what anyone
 * means by a date field most of the time, so it stays one operator change away.
 */
const PREFERRED_OPS: Readonly<Record<string, readonly SegmentOp[]>> = {
  int: ["gte", "eq", "in", "between"],
  bool: ["is_true", "is_false"],
  enum: ["in", "eq"],
  instant: ["between", "within_last_days", "gte"],
  token: ["in"],
};

export function defaultOpFor(field: SegmentFieldView): SegmentOp {
  const preferred = PREFERRED_OPS[field.kind] ?? [];
  for (const op of preferred) {
    if (field.ops.includes(op)) return op;
  }
  const first = field.ops[0];
  // A field the server published with no operators at all cannot be ruled on; `eq` is what the
  // rule then carries, and `unsupportedOp` is what the operator reads.
  return first ?? "eq";
}

/**
 * The value a rule starts with.
 *
 * `undefined` for the no-operand operators, because `exclude_none` drops the key and a stale
 * value beside `is_true` is a lie the URL does not tell. `[]` for the list operators, so the
 * editor has something to append to and the validator has an emptiness to name. A relative-day
 * operator opens on 30, which is inside the server's `1..3650` and is the shortest window
 * anybody describes in months.
 */
export function defaultValueFor(op: SegmentOp): SegmentValue | undefined {
  if (!takesValue(op)) return undefined;
  if (takesListValue(op)) return [];
  if (op === "within_last_days" || op === "not_within_last_days" || op === "within_next_days") {
    return DEFAULT_RELATIVE_DAYS;
  }
  return undefined;
}

/** The window a relative-day rule opens on. A month, in the unit the server counts in. */
export const DEFAULT_RELATIVE_DAYS = 30;

/** A brand-new rule on this field: its own first operator, and that operator's own empty value. */
export function ruleForField(field: SegmentFieldView): SegmentRule {
  const op = defaultOpFor(field);
  const value = defaultValueFor(op);
  return value === undefined ? { field: field.key, op } : { field: field.key, op, value };
}

/** Point an existing rule at a different field. The operator and the value start again. */
export function ruleWithField(field: SegmentFieldView): SegmentRule {
  return ruleForField(field);
}

/**
 * Change a rule's operator, keeping the value only where it still means the same thing.
 *
 * "The same thing" is narrow on purpose: a list survives a move between the two list
 * operators, a scalar survives a move between the scalar comparisons, and everything else
 * starts again. Carrying a `between` pair onto `gte` would silently compare against the first
 * bound alone.
 */
export function ruleWithOp(rule: SegmentRule, op: SegmentOp): SegmentRule {
  if (!takesValue(op)) return { field: rule.field, op };
  const wasList = takesListValue(rule.op);
  const isList = takesListValue(op);
  const isRange = op === "between";
  const wasRange = rule.op === "between";
  const carries = wasList === isList && wasRange === isRange;
  const value = carries ? rule.value : defaultValueFor(op);
  return value === undefined ? { field: rule.field, op } : { field: rule.field, op, value };
}

/** Write a value onto a rule, dropping the key entirely when there is nothing to carry. */
export function ruleWithValue(rule: SegmentRule, value: SegmentValue | undefined): SegmentRule {
  if (value === undefined || value === null) return { field: rule.field, op: rule.op };
  return { field: rule.field, op: rule.op, value };
}

/**
 * A brand-new nested group.
 *
 * It opens on `any`, and that is the point of adding one at all: the root is `all` by default,
 * so the only reason to nest is to say "…and at least one of these". A nested `all` inside an
 * `all` is a group that changes nothing, which is a control an operator learns to distrust.
 * It starts with one rule because an empty nested group is a 422 the moment it is sent.
 */
export function groupForField(field: SegmentFieldView): SegmentGroup {
  return { match: "any", rules: [ruleForField(field)] };
}

/* -------------------------------------------------------------------------- */
/* Reading, for the controls that need a number                                */
/* -------------------------------------------------------------------------- */

/** How deep the group at `path` sits, counting the root as 1 — comparable with `maxDepth`. */
export function depthOf(path: SegmentPath): number {
  return path.length + 1;
}

/** Whether another group may be nested inside the group at `path`. */
export function canNestAt(path: SegmentPath, limits: SegmentLimitsView): boolean {
  return depthOf(path) + 1 <= limits.maxDepth;
}

/** How many leaf rules the document carries whose field is a correlated subquery. */
export function aggregateRuleCount(
  segment: Segment,
  fields: ReadonlyMap<string, SegmentFieldView>,
): number {
  let total = 0;
  const walk = (nodes: readonly SegmentNode[]): void => {
    for (const node of nodes) {
      if (isSegmentRule(node)) {
        if (fields.get(node.field)?.isAggregate === true) total += 1;
        continue;
      }
      walk(node.rules);
    }
  };
  walk(segment.rules);
  return total;
}
