/**
 * One leaf predicate, as three controls: a field, a condition, and whatever that pair needs.
 *
 * The order is the sentence an operator reads left to right — "Songs delivered · is at least ·
 * 3" — and each control narrows the next. **Choosing a field resets the operator and the
 * value** rather than trying to carry them: an operator the new field may not take, over a
 * value from a different kind entirely, is a rule that renders as if it were applied and is
 * then refused by the compiler with a message that names neither.
 *
 * ## Everything offered here comes off the registry
 *
 * The field `<select>` lists `GET /api/segments/fields` and nothing else — no derived list, no
 * hard-coded set — which is what puts the privacy allowlist in exactly one place. The condition
 * `<select>` lists that field's own `ops`. The value control is picked by that field's `kind`.
 * A rule whose field the registry no longer publishes keeps its own disabled option so the row
 * still renders and can be deleted; dropping it silently would be a narrowing the operator
 * never made.
 *
 * A capability-gated field this deployment does not hold is listed and DISABLED, with the
 * table named. "The table is not installed here" and "nobody matched" must not look the same on
 * a screen somebody is about to send forty thousand messages from.
 *
 * ## `doc` is rendered, not paraphrased
 *
 * `FieldSpec.doc` is the field's own argument for why exposing it is safe, written in the
 * voice the rest of that package argues in. It is shown verbatim under the row. The label
 * above it is this app's (the server publishes none), but the meaning is the server's — and a
 * second copy of that sentence in TypeScript would be a second copy to keep true.
 */

import { useEffect, useRef, type JSX } from "react";
import { Trash2 } from "lucide-react";

import type { SegmentFieldView, SegmentLimitsView } from "@/api/segments";
import { cn } from "@/lib/cn";
import type { SegmentOp, SegmentRule, SegmentValue } from "@/lib/segmentCodec";

import {
  fieldOptionLabel,
  opHint,
  opLabel,
  type Translate,
} from "./segmentLabels";
import { ruleWithField, ruleWithOp, ruleWithValue, type SegmentPath } from "./segmentTree";
import { formatSegmentIssue, type SegmentIssue } from "./segmentValidation";
import {
  CONTROL_HINT_CLASS,
  CONTROL_LABEL_CLASS,
  FIELD_CLASS,
  ValueEditorSlot,
} from "./valueEditors";

export interface RuleRowProps {
  readonly rule: SegmentRule;
  readonly path: SegmentPath;
  /** 1-based, for the row's accessible name. Positional, because a rule has no other identity. */
  readonly index: number;
  readonly fields: readonly SegmentFieldView[];
  readonly fieldIndex: ReadonlyMap<string, SegmentFieldView>;
  readonly limits: SegmentLimitsView;
  /** Only the issues that belong to THIS rule; the document-wide ones live under the builder. */
  readonly issues: readonly SegmentIssue[];
  readonly disabled: boolean;
  readonly onChange: (next: SegmentRule) => void;
  readonly onRemove: () => void;
  readonly t: Translate;
  /** Set on a rule that was just added, so the keyboard lands on it instead of on the page top. */
  readonly autoFocus?: boolean | undefined;
}

export function RuleRow({
  rule,
  index,
  fields,
  fieldIndex,
  limits,
  issues,
  disabled,
  onChange,
  onRemove,
  t,
  autoFocus = false,
}: RuleRowProps): JSX.Element {
  const field = fieldIndex.get(rule.field) ?? null;
  const label = t("segments.ruleLabel", { index });
  const fieldSelect = useRef<HTMLSelectElement | null>(null);

  useEffect(() => {
    if (!autoFocus) return;
    fieldSelect.current?.focus();
  }, [autoFocus]);

  return (
    <div
      role="group"
      aria-label={label}
      className="flex flex-col gap-2 rounded-card border border-stroke bg-card px-3 py-3"
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-0 flex-col gap-1">
          <span className={CONTROL_LABEL_CLASS}>{t("segments.fieldLabel")}</span>
          <select
            ref={fieldSelect}
            className={cn(FIELD_CLASS, "min-w-[12rem] pr-2")}
            disabled={disabled}
            value={rule.field}
            onChange={(event) => {
              const chosen = fieldIndex.get(event.target.value);
              if (chosen === undefined) return;
              onChange(ruleWithField(chosen));
            }}
          >
            {field === null ? (
              /* The registry stopped publishing this key. Keep it visible and unusable so the
                 row can be read and deleted, rather than silently re-pointing it somewhere. */
              <option value={rule.field} disabled>
                {t("segments.unknownField", { key: rule.field })}
              </option>
            ) : null}
            {fields.map((candidate) => (
              <option
                key={candidate.key}
                value={candidate.key}
                disabled={!candidate.isAvailable}
              >
                {fieldOptionLabel(t, candidate)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex min-w-0 flex-col gap-1">
          <span className={CONTROL_LABEL_CLASS}>{t("segments.conditionLabel")}</span>
          <select
            className={cn(FIELD_CLASS, "min-w-[11rem] pr-2")}
            disabled={disabled || field === null}
            value={rule.op}
            onChange={(event) => {
              onChange(ruleWithOp(rule, event.target.value as SegmentOp));
            }}
          >
            {field !== null && field.ops.includes(rule.op) ? null : (
              <option value={rule.op} disabled>
                {opLabel(t, rule.op, field?.kind ?? null)}
              </option>
            )}
            {(field?.ops ?? []).map((op) => (
              <option key={op} value={op}>
                {opLabel(t, op, field?.kind ?? null)}
              </option>
            ))}
          </select>
        </label>

        <div className="flex min-w-0 flex-col gap-1">
          <span className={CONTROL_LABEL_CLASS}>{t("segments.valueLabel")}</span>
          {field === null ? (
            <p className={CONTROL_HINT_CLASS}>{t("segments.value.none")}</p>
          ) : (
            <ValueEditorSlot
              field={field}
              op={rule.op}
              value={rule.value}
              limits={limits}
              disabled={disabled}
              t={t}
              label={label}
              onChange={(next: SegmentValue | undefined) => {
                onChange(ruleWithValue(rule, next));
              }}
            />
          )}
        </div>

        <button
          type="button"
          disabled={disabled}
          onClick={onRemove}
          aria-label={`${t("segments.removeRule")}: ${label}`}
          className={cn(
            "ml-auto flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center",
            "rounded-field border border-stroke bg-card text-ink-500",
            "transition-colors hover:bg-bg hover:text-ink-900",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
            "disabled:cursor-not-allowed disabled:text-ink-300",
          )}
        >
          <Trash2 className="h-4 w-4" strokeWidth={1.75} aria-hidden />
        </button>
      </div>

      {field === null ? null : (
        <div className="flex flex-col gap-1">
          {/* Verbatim from the registry: the field's own argument for why it is safe to point
              an audience at. Never rewritten here. */}
          <p className={CONTROL_HINT_CLASS}>{field.doc}</p>
          {field.isAvailable ? null : (
            <p className={CONTROL_HINT_CLASS}>
              {t("segments.unavailableField", { capability: field.capability ?? "" })}
            </p>
          )}
          {field.isAggregate ? (
            <p className={CONTROL_HINT_CLASS}>{t("segments.aggregateField")}</p>
          ) : null}
          {renderOpHint(t, rule.op)}
        </div>
      )}

      {issues.length === 0 ? null : (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {issues.map((issue) => (
            <li
              key={issue.code}
              className="m-0 text-[11px] font-semibold leading-[1.35] text-required-deep"
            >
              {formatSegmentIssue(t, issue)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function renderOpHint(t: Translate, op: SegmentOp): JSX.Element | null {
  const hint = opHint(t, op);
  if (hint === null) return null;
  return <p className={CONTROL_HINT_CLASS}>{hint}</p>;
}
