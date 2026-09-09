/**
 * The value half of a rule row: one editor per FIELD KIND, chosen from the registry and never
 * from a guess.
 *
 * `GET /api/segments/fields` publishes `kind` precisely so a client can draw the right
 * control: `instant` is a date, `enum` a multi-select, `int` a number, `bool` a condition with
 * no value at all, `token` a short vocabulary the bot writes. {@link VALUE_EDITORS} is that
 * mapping and it is total over `FieldKind` — a `satisfies Record<FieldKind, …>` makes a kind
 * the server adds a compile error here rather than a blank space on screen. **A date field
 * cannot offer a number input**, structurally, because the editor is picked by the kind before
 * the operator is looked at.
 *
 * Inside a kind, the OPERATOR chooses the shape: `between` is two bounds, `in`/`not_in` is a
 * list, `within_last_days` is a day count, and the four no-operand operators render nothing at
 * all. That branch is per-kind rather than shared because the same operator means different
 * controls on different kinds — `between` is two numbers on a count and two days plus a month
 * shortcut on an instant.
 *
 * ## Three conventions carried over from the existing filter controls
 *
 * **Typing commits on a pause, on Enter and on blur** ({@link DEBOUNCE_MS}), because this
 * value is written into the URL by the Users screen and a keystroke-per-history-entry box is
 * unusable with the back button — and because the wizard's audience preview is a request per
 * commit. The draft also follows the value back the other way, so removing a chip empties the
 * box rather than leaving it primed to reapply itself.
 *
 * **A half-typed range keeps its other bound.** `between` needs two, and the honest way to
 * hold one is to write the pair with the missing slot empty rather than to drop the bound the
 * operator did type. `segmentValidation` names it (`betweenIncomplete`) and the builder blocks
 * on it; nothing half-typed is quietly discarded and nothing half-typed is quietly sent.
 *
 * **A known vocabulary is an aid to typing, not an allowlist.** `enum` members come from
 * `SEGMENT_ENUM_MEMBERS`, and a field with no entry there falls back to a free-form list: the
 * operator types the member and the server resolves it through the enum class, refusing a typo
 * exactly as it would have refused one chosen from a select.
 */

import { useEffect, useRef, useState, type JSX } from "react";

import { segmentEnumMembers, type FieldKind, type SegmentFieldView, type SegmentLimitsView } from "@/api/segments";
import { MAX_SEGMENT_VALUE_CHARS } from "@/api/constants";
import { cn } from "@/lib/cn";
import { takesListValue, takesValue, type RuleValue, type SegmentOp, type SegmentValue } from "@/lib/segmentCodec";

import {
  dateInputValue,
  endOfLocalDayExclusiveIso,
  monthInputValue,
  monthRangeIso,
  startOfLocalDayIso,
} from "./instants";
import { memberLabel, type Translate } from "./segmentLabels";
import { MAX_RELATIVE_DAYS, MIN_RELATIVE_DAYS } from "./segmentValidation";

/* -------------------------------------------------------------------------- */
/* Shared geometry — the toolbar's own field, so a rule row lines up with it    */
/* -------------------------------------------------------------------------- */

export const FIELD_CLASS = cn(
  "h-10 rounded-field border border-stroke bg-card px-3",
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-label",
  "outline-none transition-shadow placeholder:text-muted",
  "focus:border-accent-deep focus:ring-2 focus:ring-accent",
  "disabled:cursor-not-allowed disabled:text-ink-300",
);

export const CONTROL_LABEL_CLASS =
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-500";

export const CONTROL_HINT_CLASS =
  "m-0 max-w-[52ch] text-[11px] font-normal leading-[1.35] text-ink-400";

/** The pause after the last keystroke before a value reaches the document — and the URL. */
export const DEBOUNCE_MS = 400;

/** The relative-day windows an operator actually asks for, so "months" is one press. */
export const DAY_PRESETS: readonly number[] = [7, 30, 60, 90, 180, 365];

/* -------------------------------------------------------------------------- */
/* The editor contract                                                         */
/* -------------------------------------------------------------------------- */

export interface ValueEditorProps {
  readonly field: SegmentFieldView;
  readonly op: SegmentOp;
  /** Whatever the document carries. Never trusted: an editor renders what it recognises. */
  readonly value: SegmentValue | undefined;
  /** `undefined` clears the key entirely, which is what `exclude_none` does server-side. */
  readonly onChange: (next: SegmentValue | undefined) => void;
  readonly limits: SegmentLimitsView;
  readonly disabled: boolean;
  readonly t: Translate;
  /** The rule's own name, so every control inside can say which rule it belongs to. */
  readonly label: string;
}

export type ValueEditor = (props: ValueEditorProps) => JSX.Element | null;

/* -------------------------------------------------------------------------- */
/* Primitives                                                                  */
/* -------------------------------------------------------------------------- */

interface DebouncedFieldProps {
  readonly type: "number" | "date" | "text";
  readonly value: string;
  readonly onCommit: (next: string) => void;
  readonly ariaLabel: string;
  readonly disabled: boolean;
  readonly placeholder?: string | undefined;
  readonly maxLength?: number | undefined;
  readonly min?: number | undefined;
  readonly max?: number | undefined;
  readonly className?: string | undefined;
}

/**
 * A box that writes to the document when typing STOPS — and immediately on Enter or blur.
 *
 * The committed value is remembered so an echo of our own write is not read as an external
 * change; a value that moved for any other reason (a chip removed, a pasted link, the back
 * button) replaces the draft.
 */
function DebouncedField({
  type,
  value,
  onCommit,
  ariaLabel,
  disabled,
  placeholder,
  maxLength,
  min,
  max,
  className,
}: DebouncedFieldProps): JSX.Element {
  const [draft, setDraft] = useState(value);
  const committed = useRef(value);
  const timer = useRef<number | null>(null);

  function cancel(): void {
    if (timer.current === null) return;
    window.clearTimeout(timer.current);
    timer.current = null;
  }

  function commit(next: string): void {
    cancel();
    if (next === committed.current) return;
    committed.current = next;
    onCommit(next);
  }

  useEffect(() => {
    if (value === committed.current) return;
    committed.current = value;
    setDraft(value);
  }, [value]);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  return (
    <input
      type={type}
      value={draft}
      aria-label={ariaLabel}
      disabled={disabled}
      className={cn(FIELD_CLASS, className)}
      {...(placeholder === undefined ? {} : { placeholder })}
      {...(maxLength === undefined ? {} : { maxLength })}
      {...(min === undefined ? {} : { min })}
      {...(max === undefined ? {} : { max })}
      onChange={(event) => {
        const next = event.target.value;
        setDraft(next);
        cancel();
        timer.current = window.setTimeout(() => {
          timer.current = null;
          commit(next);
        }, DEBOUNCE_MS);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter") return;
        // Somebody who pressed Enter has finished typing and should not wait out a timer.
        event.preventDefault();
        commit(draft);
      }}
      onBlur={() => {
        commit(draft);
      }}
    />
  );
}

/** The kit's chip button, in its on and off states. Used for members and for day presets. */
function ToggleChip({
  label,
  isActive,
  onClick,
  disabled,
  ariaLabel,
}: {
  readonly label: string;
  readonly isActive: boolean;
  readonly onClick: () => void;
  readonly disabled: boolean;
  readonly ariaLabel?: string | undefined;
}): JSX.Element {
  return (
    <button
      type="button"
      aria-pressed={isActive}
      disabled={disabled}
      onClick={onClick}
      {...(ariaLabel === undefined ? {} : { "aria-label": ariaLabel })}
      className={cn(
        "h-8 cursor-pointer rounded-chip px-3",
        "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px]",
        "transition-[background-color,color,filter]",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
        "disabled:cursor-not-allowed disabled:opacity-60",
        isActive
          ? "bg-accent-70 text-ink-800 hover:brightness-95"
          : "border border-stroke bg-card text-ink-500 hover:bg-bg",
      )}
    >
      {label}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Reading the document's value without trusting it                            */
/* -------------------------------------------------------------------------- */

/**
 * A type guard rather than a bare `Array.isArray`: TS cannot subtract a `readonly` array from
 * a union on `Array.isArray` alone, so without this the scalar branches below would still be
 * holding a possible array and the list branches would be holding `any[]`.
 */
function isList(value: SegmentValue | undefined): value is readonly RuleValue[] {
  return Array.isArray(value);
}

function asList(value: SegmentValue | undefined): readonly RuleValue[] {
  return isList(value) ? value : [];
}

/** The two bounds of a range, with an unfilled slot as `""` so the other one survives typing. */
function asPair(value: SegmentValue | undefined): readonly [RuleValue, RuleValue] {
  const list = asList(value);
  return [list[0] ?? "", list[1] ?? ""];
}

function numberText(value: RuleValue | undefined): string {
  return typeof value === "number" ? String(value) : "";
}

/**
 * A whole number, or `""` — which every caller reads as "this slot is empty".
 *
 * Anything that is not an integer clears rather than being stored as typed: the compiler
 * refuses a float and refuses a bool (`_as_int` rejects `true` explicitly, so `order_count >= 1`
 * cannot be composed by accident), and a half-typed `3.` sitting in the URL is a document that
 * says something nobody wrote.
 */
function parseNumber(text: string): RuleValue {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) ? parsed : "";
}

/* -------------------------------------------------------------------------- */
/* int                                                                         */
/* -------------------------------------------------------------------------- */

function IntEditor(props: ValueEditorProps): JSX.Element | null {
  const { op, value, onChange, disabled, t, label, limits } = props;
  if (!takesValue(op)) return null;

  if (op === "between") {
    const [low, high] = asPair(value);
    return (
      <div className="flex flex-wrap items-center gap-2">
        <DebouncedField
          type="number"
          value={numberText(low)}
          disabled={disabled}
          ariaLabel={`${label}: ${t("segments.value.numberFrom")}`}
          placeholder={t("segments.value.numberFrom")}
          className="w-28"
          onCommit={(next) => {
            onChange([parseNumber(next), high]);
          }}
        />
        <span aria-hidden className="text-[12px] text-ink-300">
          –
        </span>
        <DebouncedField
          type="number"
          value={numberText(high)}
          disabled={disabled}
          ariaLabel={`${label}: ${t("segments.value.numberTo")}`}
          placeholder={t("segments.value.numberTo")}
          className="w-28"
          onCommit={(next) => {
            onChange([low, parseNumber(next)]);
          }}
        />
      </div>
    );
  }

  if (takesListValue(op)) {
    return (
      <MemberListEditor
        {...props}
        kind="number"
        members={asList(value)}
        onMembers={(next) => {
          onChange(next);
        }}
        max={limits.maxValueMembers}
      />
    );
  }

  return (
    <DebouncedField
      type="number"
      value={numberText(typeof value === "number" ? value : undefined)}
      disabled={disabled}
      ariaLabel={`${label}: ${t("segments.value.number")}`}
      placeholder={t("segments.value.number")}
      className="w-32"
      onCommit={(next) => {
        const parsed = parseNumber(next);
        onChange(parsed === "" ? undefined : parsed);
      }}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* instant                                                                     */
/* -------------------------------------------------------------------------- */

function InstantEditor(props: ValueEditorProps): JSX.Element | null {
  const { op, value, onChange, disabled, t, label } = props;
  if (!takesValue(op)) return null;

  if (op === "within_last_days" || op === "not_within_last_days" || op === "within_next_days") {
    return <RelativeDaysEditor {...props} />;
  }

  if (op === "between") {
    const [low, high] = asPair(value);
    const month = monthInputValue(low, high);
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <DebouncedField
            type="date"
            value={dateInputValue(low, "start")}
            disabled={disabled}
            ariaLabel={`${label}: ${t("segments.value.dateFrom")}`}
            className="min-w-[9.5rem]"
            onCommit={(next) => {
              onChange([startOfLocalDayIso(next) ?? "", high]);
            }}
          />
          <span aria-hidden className="text-[12px] text-ink-300">
            –
          </span>
          <DebouncedField
            type="date"
            value={dateInputValue(high, "endExclusive")}
            disabled={disabled}
            ariaLabel={`${label}: ${t("segments.value.dateTo")}`}
            className="min-w-[9.5rem]"
            onCommit={(next) => {
              onChange([low, endOfLocalDayExclusiveIso(next) ?? ""]);
            }}
          />
        </div>
        <label className="flex flex-wrap items-center gap-2">
          <span className={CONTROL_LABEL_CLASS}>{t("segments.value.wholeMonth")}</span>
          <input
            type="month"
            value={month}
            disabled={disabled}
            aria-label={`${label}: ${t("segments.value.wholeMonth")}`}
            className={cn(FIELD_CLASS, "min-w-[9rem]")}
            onChange={(event) => {
              const range = monthRangeIso(event.target.value);
              if (range === null) return;
              onChange([range[0], range[1]]);
            }}
          />
        </label>
        <p className={CONTROL_HINT_CLASS}>{t("segments.value.wholeMonthHint")}</p>
      </div>
    );
  }

  return (
    <DebouncedField
      type="date"
      value={dateInputValue(value, "start")}
      disabled={disabled}
      ariaLabel={`${label}: ${t("segments.value.date")}`}
      className="min-w-[9.5rem]"
      onCommit={(next) => {
        onChange(startOfLocalDayIso(next) ?? undefined);
      }}
    />
  );
}

/** `n` for the three relative operators, with the windows an operator actually asks for. */
function RelativeDaysEditor({
  value,
  onChange,
  disabled,
  t,
  label,
}: ValueEditorProps): JSX.Element {
  const days = typeof value === "number" ? value : undefined;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <DebouncedField
          type="number"
          value={days === undefined ? "" : String(days)}
          disabled={disabled}
          min={MIN_RELATIVE_DAYS}
          max={MAX_RELATIVE_DAYS}
          ariaLabel={`${label}: ${t("segments.value.days")}`}
          placeholder={t("segments.value.days")}
          className="w-24"
          onCommit={(next) => {
            const parsed = parseNumber(next);
            onChange(parsed === "" ? undefined : parsed);
          }}
        />
        {DAY_PRESETS.map((preset) => (
          <ToggleChip
            key={preset}
            label={t("segments.value.daysPreset", { days: preset })}
            isActive={days === preset}
            disabled={disabled}
            onClick={() => {
              onChange(preset);
            }}
          />
        ))}
      </div>
      <p className={CONTROL_HINT_CLASS}>
        {t("segments.value.daysRange", { min: MIN_RELATIVE_DAYS, max: MAX_RELATIVE_DAYS })}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* bool                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Nothing at all.
 *
 * A bool field's only operators are `is_true` and `is_false`, both of which carry no value —
 * the operator select IS the control, and a second yes/no beside it would be two places to say
 * one thing, which is two places for them to disagree.
 */
function BoolEditor({ t }: ValueEditorProps): JSX.Element {
  return <p className={CONTROL_HINT_CLASS}>{t("segments.value.none")}</p>;
}

/* -------------------------------------------------------------------------- */
/* enum and token                                                              */
/* -------------------------------------------------------------------------- */

function EnumEditor(props: ValueEditorProps): JSX.Element | null {
  const { field, op, value, onChange, disabled, t, label, limits } = props;
  if (!takesValue(op)) return null;

  const members = segmentEnumMembers(field.key);

  if (takesListValue(op)) {
    if (members === null) {
      return (
        <MemberListEditor
          {...props}
          kind="text"
          members={asList(value)}
          onMembers={onChange}
          max={limits.maxValueMembers}
        />
      );
    }
    const selected = asList(value).map(String);
    return (
      <div className="flex flex-wrap gap-2">
        {members.map((member) => {
          const isActive = selected.includes(member);
          return (
            <ToggleChip
              key={member}
              label={memberLabel(t, field.key, member)}
              isActive={isActive}
              disabled={disabled}
              onClick={() => {
                onChange(
                  isActive
                    ? selected.filter((chosen) => chosen !== member)
                    : [...selected, member],
                );
              }}
            />
          );
        })}
      </div>
    );
  }

  if (members === null) {
    return (
      <DebouncedField
        type="text"
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        maxLength={MAX_SEGMENT_VALUE_CHARS}
        ariaLabel={`${label}: ${t("segments.valueLabel")}`}
        placeholder={t("segments.value.memberPlaceholder")}
        className="min-w-[10rem]"
        onCommit={(next) => {
          onChange(next === "" ? undefined : next);
        }}
      />
    );
  }

  return (
    <select
      className={cn(FIELD_CLASS, "min-w-[10rem] pr-2")}
      disabled={disabled}
      aria-label={`${label}: ${t("segments.valueLabel")}`}
      value={typeof value === "string" ? value : ""}
      onChange={(event) => {
        const next = event.target.value;
        onChange(next === "" ? undefined : next);
      }}
    >
      <option value="">{t("segments.value.memberPlaceholder")}</option>
      {members.map((member) => (
        <option key={member} value={member}>
          {memberLabel(t, field.key, member)}
        </option>
      ))}
    </select>
  );
}

/**
 * `token` — a short string from the bot's OWN closed vocabulary, which the server does not
 * publish (`wizard_step` is a plain column, not an enum).
 *
 * So it is typed rather than chosen, capped at the column's own width, and it takes `in`/
 * `not_in` alone. It is never free text a customer wrote: `chat_messages.body` is in
 * `SEGMENT_REFUSALS` and there is no field of any kind over it.
 */
function TokenEditor(props: ValueEditorProps): JSX.Element | null {
  const { op, value, onChange, limits } = props;
  if (!takesValue(op)) return null;
  return (
    <MemberListEditor
      {...props}
      kind="text"
      members={asList(value)}
      onMembers={onChange}
      max={limits.maxValueMembers}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* The list editor both `in` and `not_in` use                                  */
/* -------------------------------------------------------------------------- */

interface MemberListEditorProps extends ValueEditorProps {
  readonly kind: "number" | "text";
  readonly members: readonly RuleValue[];
  readonly onMembers: (next: readonly RuleValue[]) => void;
  readonly max: number;
}

/**
 * A list of values, added one at a time and removed one at a time.
 *
 * A `<select multiple>` would hide the OR behind a modifier key nobody presses, and a
 * comma-separated box would make one typo swallow the whole list. The count against the
 * server's `maxValueMembers` is on screen because the refusal it prevents names a limit and
 * not a control.
 */
function MemberListEditor({
  kind,
  members,
  onMembers,
  max,
  disabled,
  t,
  label,
}: MemberListEditorProps): JSX.Element {
  const [draft, setDraft] = useState("");
  const isFull = members.length >= max;

  function add(): void {
    const text = draft.trim();
    if (text === "") return;
    const member: RuleValue = kind === "number" ? parseNumber(text) : text;
    if (member === "") return;
    if (members.some((existing) => String(existing) === String(member))) {
      setDraft("");
      return;
    }
    onMembers([...members, member]);
    setDraft("");
  }

  return (
    <div className="flex flex-col gap-2">
      {members.length === 0 ? null : (
        <div className="flex flex-wrap gap-2">
          {members.map((member) => (
            <span
              key={String(member)}
              className="inline-flex items-center gap-2 rounded bg-accent-70 py-[6px] pl-2 pr-1 text-[12px] leading-[16.392px] tracking-[-0.36px] text-ink-800"
            >
              {String(member)}
              <button
                type="button"
                disabled={disabled}
                aria-label={t("segments.value.removeMember", { value: String(member) })}
                className={cn(
                  "flex h-4 w-4 cursor-pointer items-center justify-center rounded-full border-0 bg-transparent p-0 text-ink-800",
                  "transition-[background-color] hover:bg-card",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
                )}
                onClick={() => {
                  onMembers(members.filter((existing) => String(existing) !== String(member)));
                }}
              >
                <span aria-hidden>×</span>
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type={kind === "number" ? "number" : "text"}
          value={draft}
          disabled={disabled || isFull}
          maxLength={MAX_SEGMENT_VALUE_CHARS}
          aria-label={`${label}: ${t("segments.value.members")}`}
          placeholder={t("segments.value.memberPlaceholder")}
          className={cn(FIELD_CLASS, "w-40")}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            // Enter adds the member rather than submitting whatever form this sits inside.
            event.preventDefault();
            add();
          }}
        />
        <button
          type="button"
          disabled={disabled || isFull || draft.trim() === ""}
          onClick={add}
          className={cn(
            "h-8 cursor-pointer rounded-chip border border-stroke bg-card px-3",
            "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-900",
            "transition-[background-color,filter] hover:bg-bg",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
            "disabled:cursor-not-allowed disabled:text-ink-300",
          )}
        >
          {t("segments.value.addMember")}
        </button>
        <span className={CONTROL_HINT_CLASS}>
          {t("segments.value.memberCount", { count: members.length, max })}
        </span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The registry                                                                */
/* -------------------------------------------------------------------------- */

/**
 * One editor per kind, and the `satisfies` is the point: a kind the server adds is a compile
 * error here, not a rule row with no way to fill it in.
 */
export const VALUE_EDITORS = {
  int: IntEditor,
  bool: BoolEditor,
  enum: EnumEditor,
  instant: InstantEditor,
  token: TokenEditor,
} satisfies Record<FieldKind, ValueEditor>;

export function valueEditorFor(kind: FieldKind): ValueEditor {
  return VALUE_EDITORS[kind];
}

/**
 * The value control for one rule, or the "no value" note when the operator takes none.
 *
 * The no-operand branch is here rather than inside each editor so that the FOUR valueless
 * operators read identically whatever the field's kind is — and so that a rule can never carry
 * a stale value beside `is_true`, which `exclude_none` would drop from the token anyway and
 * which would therefore be a filter the URL does not describe.
 */
export function ValueEditorSlot(props: ValueEditorProps): JSX.Element | null {
  if (!takesValue(props.op)) {
    return <p className={CONTROL_HINT_CLASS}>{props.t("segments.value.none")}</p>;
  }
  const Editor = valueEditorFor(props.field.kind);
  return <Editor {...props} />;
}
