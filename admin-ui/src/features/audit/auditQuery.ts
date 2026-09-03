/**
 * `/audit` filter state, and the two derivations the screen's dominant signal needs.
 *
 * The audit list departs from every other list on the surface in three ways, and all three
 * show up here: `from`/`to` are INDEPENDENT (neither implies the other), there is no
 * `withTotal`, and its cursor is a `seq` encoding that no other endpoint accepts. So the
 * codec has no `withTotal` key at all rather than one the endpoint would ignore.
 */

import { z } from "zod";

import {
  AUDIT_ACTION_VALUES,
  AUDIT_OUTCOME_VALUES,
  DESTRUCTIVE_AUDIT_ACTIONS,
  DEFAULT_PAGE_LIMIT,
  MAX_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  type AuditAction,
  type AuditEntryView,
  type AuditQuery,
} from "@/api";
import type { FilterFieldDescriptor, FilterScalar } from "@/components/data";
import {
  zEnumList,
  zInstantParam,
  zIntParam,
  zStringParam,
  type SearchParamsSchema,
} from "@/lib";

const auditFilterCodec = z.object({
  actor: zStringParam,
  action: zEnumList(AUDIT_ACTION_VALUES),
  subjectType: zStringParam,
  subjectId: zStringParam,
  outcome: zEnumList(AUDIT_OUTCOME_VALUES),
  from: zInstantParam,
  to: zInstantParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
  cursor: zStringParam,
});

export type AuditFilters = z.output<typeof auditFilterCodec>;

/** Annotated rather than asserted — `SearchParamsSchema<T>` leaves zod's INPUT side
 *  `unknown`, which is what a URL codec actually accepts. See `assets/assetsQuery.ts`. */
export const auditFilterSchema: SearchParamsSchema<AuditFilters> = auditFilterCodec;

export const AUDIT_FILTERS_EMPTY: AuditFilters = {};

/** The window the dominant signal counts over. §11.2: "destructive actions in the last 24 h". */
export const DESTRUCTIVE_WINDOW_MS = 86_400_000;

/** The window the reveal-exposure chart covers — §12.3 charts records-per-actor over 7 days. */
export const EXPOSURE_WINDOW_MS = 7 * 86_400_000;

/**
 * How many rows either counting query will look at.
 *
 * The audit list has no `total` and takes no `withTotal`, so a count means counting rows,
 * and a count of rows means a ceiling. When the page comes back with a `nextCursor` the
 * figure is a LOWER BOUND and the screen renders it with a `+` — never as if it were the
 * whole answer.
 */
export const COUNTING_LIMIT = MAX_PAGE_LIMIT;

export function toAuditQuery(filters: AuditFilters): AuditQuery {
  return {
    ...(filters.actor === undefined ? {} : { actor: filters.actor }),
    ...(filters.action === undefined ? {} : { action: filters.action }),
    ...(filters.subjectType === undefined ? {} : { subjectType: filters.subjectType }),
    ...(filters.subjectId === undefined ? {} : { subjectId: filters.subjectId }),
    ...(filters.outcome === undefined ? {} : { outcome: filters.outcome }),
    ...(filters.from === undefined ? {} : { from: filters.from }),
    ...(filters.to === undefined ? {} : { to: filters.to }),
    ...(filters.cursor === undefined ? {} : { cursor: filters.cursor }),
    limit: filters.limit ?? DEFAULT_PAGE_LIMIT,
  };
}

export function auditFilterFields(
  formatInstant: (value: FilterScalar) => string,
): readonly FilterFieldDescriptor<AuditFilters>[] {
  return [
    // `actor` and the two subject fields are opaque identifiers an operator pasted, so they
    // are shown verbatim rather than run through `humaniseEnum`.
    { key: "actor", label: "actor", format: (value) => String(value) },
    { key: "action", label: "action" },
    { key: "outcome", label: "outcome" },
    { key: "subjectType", label: "subject type" },
    { key: "subjectId", label: "subject id", format: (value) => String(value) },
    { key: "from", label: "after", format: formatInstant },
    { key: "to", label: "before", format: formatInstant },
  ];
}

/** §11.2's "destructive" set, as a predicate. The list itself lives in `@/api/enums`. */
export function isDestructiveAction(action: AuditAction): boolean {
  return DESTRUCTIVE_AUDIT_ACTIONS.includes(action);
}

/**
 * One actor's exposure over the window.
 *
 * §11.2: **reveals are charted by `record_count`, not by row count.** One reveal that
 * touches 500 records is not one unit of exposure, and a bar chart of row counts would show
 * the operator who revealed one name and the operator who pulled a 90-day conversation as
 * the same height. `recordCount` is `null` on rows whose writer recorded no count; those are
 * counted as reveals and excluded from the records total rather than silently read as zero,
 * because "no count recorded" and "zero records" are different facts.
 */
export interface RevealExposureRow {
  readonly actor: string;
  readonly records: number;
  readonly reveals: number;
  readonly uncountedReveals: number;
}

export function revealExposureByActor(
  entries: readonly AuditEntryView[],
): readonly RevealExposureRow[] {
  const byActor = new Map<string, { records: number; reveals: number; uncountedReveals: number }>();
  for (const entry of entries) {
    const current = byActor.get(entry.actorUsername) ?? {
      records: 0,
      reveals: 0,
      uncountedReveals: 0,
    };
    byActor.set(entry.actorUsername, {
      records: current.records + (entry.recordCount ?? 0),
      reveals: current.reveals + 1,
      uncountedReveals: current.uncountedReveals + (entry.recordCount === null ? 1 : 0),
    });
  }
  // Sorted by exposure, descending. Ties keep insertion order (`Array.prototype.sort` is
  // stable) rather than being broken by `localeCompare`, which the SPA does not call.
  return [...byActor.entries()]
    .map(([actor, tally]) => ({ actor, ...tally }))
    .sort((left, right) => right.records - left.records);
}

/** Rows whose action is in §11.2's destructive set. */
export function countDestructive(entries: readonly AuditEntryView[]): number {
  return entries.filter((entry) => isDestructiveAction(entry.action)).length;
}

/** Everything else — counted separately, which is the whole point of the signal. */
export function countRoutine(entries: readonly AuditEntryView[]): number {
  return entries.filter((entry) => !isDestructiveAction(entry.action)).length;
}
