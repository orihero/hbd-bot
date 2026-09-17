/**
 * The one place a registry key becomes a phrase, and the only place it may.
 *
 * `GET /api/segments/fields` publishes `key`, `kind`, `ops`, `sortable`, `isAggregate`,
 * `capability`, `isAvailable` and `doc`. It publishes **no label** — `doc` is the field's own
 * safety argument in prose, written for a reader deciding whether pointing a campaign at this
 * field is defensible, and it is rendered verbatim as help text rather than squeezed into a
 * `<select>` option. So the option text has to come from somewhere, and it comes from the
 * locale catalogue: `segments.fields.<key>`, in all three languages.
 *
 * **This is not a second copy of the registry.** Nothing here decides which fields exist,
 * which operators apply or which members are legal — every one of those questions is answered
 * by the response, and this module only names what the response already offered. Two rules
 * keep it that way:
 *
 * 1. **A miss falls back to the server's own spelling.** A field the registry publishes and
 *    this catalogue has not caught up with renders as `order_count`, not as nothing. A field
 *    that vanishes from the registry renders nowhere, whatever this file still says about it.
 * 2. **The enum members are an aid to typing, never an allowlist.** `segmentEnumMembers`
 *    returns `null` for a field this bundle has no vocabulary for, and the editor falls back
 *    to a free-form list the operator types into — the server refuses a typo either way
 *    (`_as_enum` resolves through the enum class before any SQL exists).
 *
 * The operator names are split in two because the numeric wording is a lie on a date: `gt` is
 * "is more than" on a count and "after" on an instant, and an operator reading "Last order is
 * more than 1 June" has been handed a sentence that does not parse. `segments.opsInstant`
 * holds the five that differ; everything else falls through to `segments.ops`.
 */

import {
  segmentEnumMembers,
  type FieldKind,
  type SegmentFieldView,
} from "@/api/segments";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import type { MatchMode, SegmentOp } from "@/lib/segmentCodec";

/**
 * The catalogue lookup, as this folder consumes it.
 *
 * Structurally what `useI18n((state) => state.t)` hands back, so a component passes its own
 * `t` straight in and every string in the tree follows the operator's locale.
 */
export type Translate = (
  path: TranslationPath,
  params?: Record<string, string | number>,
) => string;

/**
 * The catalogue, bound to the operator's current locale.
 *
 * One selector over the i18n store rather than a prop threaded from the screen: the builder is
 * rendered inside two very different owners (a filter panel and a wizard step) and neither
 * should have to know that the tree below it speaks three languages.
 */
export function useTranslate(): Translate {
  return useI18n((state) => state.t);
}

/**
 * A lookup that can miss.
 *
 * `translate()` returns the PATH when a key is absent — in this catalogue and in English
 * both — so comparing the answer to the path is exactly the "no such key" signal, and the
 * caller's fallback (the server's own spelling) takes over. The cast is the price of a
 * dynamic key: every key this module composes is declared in `i18n/types.ts`, and the ones
 * that are not are precisely the ones this function is here to catch.
 */
function lookup(
  t: Translate,
  path: string,
  fallback: string,
  params?: Record<string, string | number>,
): string {
  const value = t(path as TranslationPath, params);
  return value === path ? fallback : value;
}

/** What a registry key is called, or the key itself when this bundle has no phrase for it. */
export function fieldLabel(t: Translate, key: string): string {
  return lookup(t, `segments.fields.${key}`, key);
}

/**
 * What an operator is called, in the wording that is true for this KIND.
 *
 * `instant` takes the temporal spelling where one exists (`after`, `before`, `on or after`,
 * `on or before`, `never happened`); every other kind, and every operator with no temporal
 * form, falls through to the general list.
 */
export function opLabel(t: Translate, op: SegmentOp, kind: FieldKind | null): string {
  const general = lookup(t, `segments.ops.${op}`, op);
  if (kind !== "instant") return general;
  return lookup(t, `segments.opsInstant.${op}`, general);
}

/** The sentence under a rule row that says what this operator actually asks for. `null` when there is nothing to add. */
export function opHint(t: Translate, op: SegmentOp): string | null {
  const hint = lookup(t, `segments.opHints.${op}`, "");
  return hint === "" ? null : hint;
}

/** What one enum member is called, or the wire spelling when this bundle has no phrase for it. */
export function memberLabel(t: Translate, fieldKey: string, member: string): string {
  return lookup(t, `segments.members.${fieldKey}.${member}`, member);
}

/** How a group's combining mode reads as a word: "All", "Any", "None". */
export function matchLabel(t: Translate, match: MatchMode): string {
  return lookup(t, `segments.match.${match}`, match);
}

/** The sentence a group heads itself with — the whole point of which is that AND/OR is READ, not inferred. */
export function matchHeading(t: Translate, match: MatchMode): string {
  return lookup(t, `segments.heading.${match}`, match);
}

/** The connective that joins several values of one rule, in this group's own mode. */
export function connective(t: Translate, match: MatchMode): string {
  switch (match) {
    case "any":
      return lookup(t, "segments.chips.separatorOr", "or");
    case "none":
      return lookup(t, "segments.chips.separatorNone", "nor");
    case "all":
    default:
      return lookup(t, "segments.chips.separatorAnd", "and");
  }
}

/**
 * The members a multi-select may offer for this field, already labelled.
 *
 * `null` — not an empty list — when this bundle holds no vocabulary for the key, which is the
 * signal to fall back to a free-form editor rather than to render a select with nothing in it.
 */
export function labelledMembers(
  t: Translate,
  field: SegmentFieldView,
): readonly { readonly value: string; readonly label: string }[] | null {
  const members = segmentEnumMembers(field.key);
  if (members === null) return null;
  return members.map((member) => ({ value: member, label: memberLabel(t, field.key, member) }));
}

/**
 * A field as one option reads: its name, plus why it cannot be chosen when it cannot.
 *
 * A capability-gated field this deployment does not hold is LISTED and disabled rather than
 * filtered out — "the table is not installed here" and "nobody matched" must not look the
 * same, and a field silently missing from the list is a field an operator concludes was never
 * designed.
 */
export function fieldOptionLabel(t: Translate, field: SegmentFieldView): string {
  const label = fieldLabel(t, field.key);
  if (field.isAvailable) return label;
  return lookup(t, "segments.unavailableOption", `${label} — unavailable`, { label });
}
