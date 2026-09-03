/**
 * Turning zod-parsed URL search params into `FilterBar` chips.
 *
 * §11.1: "URL search params (zod-parsed) for all filter state so an operator can paste 'the
 * failed orders I'm looking at' into Slack." The chips are the visible half of that
 * sentence: what the URL says, restated as removable tokens, with removal writing back to
 * the URL rather than to a component's `useState`. There is no second copy of filter state
 * anywhere in this directory, and that is the point — one source, and it is the address bar.
 *
 * Two behaviours are worth stating because they look like details and are not:
 *
 *  - **A repeated parameter yields one chip per value.** `?state=failed&state=cancelled` is
 *    two chips, and removing one leaves the other. Collapsing them into `state: 2 selected`
 *    would make the operator open a menu to find out what they are filtering by.
 *  - **Removal drops the cursor.** It goes through `SearchParamsState.patch`, which discards
 *    `cursor` by default. A keyset cursor cut against the old filter continues a list that
 *    no longer exists.
 *
 * This file exports no components on purpose: `FilterBar.tsx` may then stay a pure module of
 * components for Fast Refresh.
 */

import type { SearchParamsState } from "@/lib";
import { humaniseEnum } from "@/lib";

/** One removable token. `FilterBar` renders these and nothing else. */
export interface FilterChipModel {
  /** Unique within the bar: `state:failed`, `telegramUserId`. Also the React key. */
  readonly id: string;
  /** The parameter's human name — `state`, `provider`, `paid`. */
  readonly label: string;
  /** The value as the operator should read it. */
  readonly value: string;
  /** Write the removal back to the URL. */
  readonly remove: () => void;
}

/** A primitive a search parameter can hold once zod has parsed it. */
export type FilterScalar = string | number | boolean;

export interface FilterFieldDescriptor<T> {
  /** The key in the parsed filter object, which is also the URL parameter name. */
  readonly key: Extract<keyof T, string>;
  /** What the chip calls it. Sentence case, no trailing colon. */
  readonly label: string;
  /**
   * How one value renders. Defaults to `humaniseEnum` for strings (safe: these are OUR
   * closed vocabularies and opaque ids, never user content), `yes`/`no` for booleans, and
   * the bare digits for numbers — never grouped, because a grouped `770,000,123` is not a
   * telegram id anybody can paste back.
   */
  readonly format?: (value: FilterScalar) => string;
}

export function defaultChipFormat(value: FilterScalar): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return String(value);
  return humaniseEnum(value);
}

/**
 * Derive the chips for a filter state.
 *
 * Not a hook — it uses no React state, so it can be called inside a `useMemo`, inside a
 * test, or not at all.
 */
export function buildFilterChips<T extends Record<string, unknown>>(
  state: SearchParamsState<T>,
  fields: readonly FilterFieldDescriptor<T>[],
): readonly FilterChipModel[] {
  const chips: FilterChipModel[] = [];

  for (const field of fields) {
    const raw: unknown = state.value[field.key];
    if (raw === undefined || raw === null || raw === "") continue;
    const format = field.format ?? defaultChipFormat;

    if (Array.isArray(raw)) {
      const members = raw.filter(isFilterScalar);
      for (const member of members) {
        chips.push({
          id: `${field.key}:${String(member)}`,
          label: field.label,
          value: format(member),
          remove: () => {
            const kept = members.filter((candidate) => candidate !== member);
            state.patch(patchOf<T>(field.key, kept.length === 0 ? undefined : kept));
          },
        });
      }
      continue;
    }

    if (!isFilterScalar(raw)) continue;
    chips.push({
      id: field.key,
      label: field.label,
      value: format(raw),
      remove: () => {
        state.patch(patchOf<T>(field.key, undefined));
      },
    });
  }

  return chips;
}

function isFilterScalar(value: unknown): value is FilterScalar {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

/**
 * `{ [key]: value }` as a `Partial<T>`.
 *
 * The assertion is unavoidable: TypeScript types a computed-key object literal as
 * `{ [x: string]: … }` and cannot prove it lines up with `Partial<T>`. It is contained to
 * this one function so no caller has to write it.
 */
function patchOf<T>(key: Extract<keyof T, string>, value: unknown): Partial<T> {
  return { [key]: value } as Partial<T>;
}
