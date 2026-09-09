import { useEffect, useId, useRef, useState, type JSX, type ReactNode } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * The Audit filter panel's controls.
 *
 * The kit ships a toolbar with a **Filters** button and no controls to put behind it, so this
 * screen brings its own — plain elements over the design tokens, no popover to position and
 * nothing to load under the production CSP. Every measurement is the kit's: a 47-high field at
 * radius 10 with a 1px `--stroke` edge, the 16/400/-0.64 `--ink-300` column-header type for a
 * group label, and the toolbar's 12/600 for a chip-shaped toggle.
 *
 * These mirror `features/generations/filterControls.tsx` field for field, and they are
 * duplicated rather than imported for the reason that file's own docstring gives: they are one
 * feature's controls, not a shared primitive, and the answer for a third screen is a component
 * under `src/components/` — not a deep import into a sibling feature. Promoting them is a real
 * change to make one day; it means editing the two screens that already import them, which is a
 * different change from adding this one.
 *
 * Four shapes, because `/api/audit` has four, and the difference between them is a 422 rather
 * than a preference:
 *
 *  - **`action` and `outcome` REPEAT** (`?outcome=denied&outcome=error` — OR within the field,
 *    AND across fields), so both are toggle groups. An empty selection omits the parameter,
 *    which means "do not filter" and not "match nothing".
 *  - **`action` has THIRTY-FOUR members**, which is why it gets `GroupedEnumToggles` rather
 *    than one undifferentiated wrap. A control nobody can scan is a filter nobody sets, and an
 *    audit filter nobody sets is an investigation that comes back empty and reads as "it never
 *    happened".
 *  - **`actor` is one field with two meanings** — matched as `actor_id` when it parses as a
 *    UUID and as an exact casefolded `actor_username` otherwise. It is one box because the
 *    router made it one parameter: two boxes would be two ways to ask one question, and the
 *    wrong one silently matches nothing.
 *  - **`from`/`to` are INCLUSIVE at both ends.** This route deliberately does not use
 *    `resolve_window`, so its window is not the half-open one every other list on this API
 *    takes. The hint says so, because the difference is a row at the boundary.
 *
 * `subjectType` is a `<select>` over the nine values `SUBJECT_TYPES` allows to be stored even
 * though the parameter is a plain `str` with no enum check: a tenth value cannot exist in the
 * column, so a free-text box there would only ever produce an empty page. `subjectId` IS free
 * text, because it is an opaque identifier somebody pastes.
 */

/* -------------------------------------------------------------------------- */
/* The kit's control metrics                                                   */
/* -------------------------------------------------------------------------- */

const FIELD_CLASS = cn(
  "h-[47px] w-full rounded-field border border-stroke bg-card py-[10px] pl-[12px] pr-[10px]",
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-label",
  "shadow-field outline-none transition-shadow",
  "placeholder:text-muted",
  "focus:border-accent-deep focus:ring-2 focus:ring-accent",
);

/** The kit's column-header type, which is also how every group of controls is labelled. */
const GROUP_LABEL_CLASS =
  "text-[16px] font-normal leading-[21.856px] tracking-[-0.64px] text-ink-300";

/** A family heading INSIDE a group — quieter than the group's own label, which outranks it. */
const SUBGROUP_LABEL_CLASS =
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-400";

const HINT_CLASS = "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-400";

/** How long a free-text box waits after the last keystroke before it writes to the URL. */
const FILTER_DEBOUNCE_MS = 300;

const TOGGLE_CLASS = cn(
  "cursor-pointer rounded-chip px-3 py-[6px]",
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px]",
  "transition-[background-color,color]",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
);

function toggleTone(isActive: boolean): string {
  return isActive
    ? "bg-accent-70 text-ink-800"
    : "border border-stroke bg-card text-ink-500 hover:bg-bg";
}

/* -------------------------------------------------------------------------- */
/* The panel and its fields                                                    */
/* -------------------------------------------------------------------------- */

interface FilterPanelProps {
  /** Matches the disclosing button's `aria-controls`. */
  readonly id: string;
  readonly children: ReactNode;
  readonly className?: string | undefined;
}

/** The disclosed card: the kit's white 15-radius surface with its 1px edge. */
export function FilterPanel({ id, children, className }: FilterPanelProps): JSX.Element {
  return (
    <div
      id={id}
      className={cn(
        "grid grid-cols-1 gap-x-5 gap-y-4 rounded-card border border-stroke bg-card p-4",
        "sm:grid-cols-2 xl:grid-cols-3",
        className,
      )}
    >
      {children}
    </div>
  );
}

interface FilterFieldProps {
  readonly label: string;
  /** One line under the control, for a rule that is otherwise learned from a 422. */
  readonly hint?: string | undefined;
  readonly children: ReactNode;
  /** For a field whose control is a group rather than a single labellable element. */
  readonly as?: "label" | "div";
  readonly className?: string | undefined;
}

/** One labelled control. `as="div"` for a toggle group, which labels itself with `role`. */
export function FilterField({
  label,
  hint,
  children,
  as = "label",
  className,
}: FilterFieldProps): JSX.Element {
  const Wrapper = as;
  return (
    <Wrapper className={cn("flex min-w-0 flex-col gap-2", className)}>
      <span className={GROUP_LABEL_CLASS}>{label}</span>
      {children}
      {hint === undefined ? null : <span className={HINT_CLASS}>{hint}</span>}
    </Wrapper>
  );
}

/* -------------------------------------------------------------------------- */
/* Controls                                                                    */
/* -------------------------------------------------------------------------- */

interface EnumToggleGroupProps<T extends string> {
  readonly label: string;
  /** Our own closed vocabulary, in declaration order. */
  readonly values: readonly T[];
  readonly selected: readonly T[];
  /** Emits an EMPTY array when the last member is turned off — the parameter is then dropped. */
  readonly onChange: (next: readonly T[]) => void;
  readonly format: (value: T) => string;
  /** A native tooltip per member, for a word whose meaning is not in the word. */
  readonly describe?: ((value: T) => string) | undefined;
  readonly hint?: string | undefined;
}

/** A repeatable enum filter, as toggles. OR within the field. */
export function EnumToggleGroup<T extends string>({
  label,
  values,
  selected,
  onChange,
  format,
  describe,
  hint,
}: EnumToggleGroupProps<T>): JSX.Element {
  return (
    <FilterField label={label} hint={hint} as="div">
      {/* The group is named for assistive tech; `aria-pressed` is the channel that does not
          depend on seeing which chip carries the accent ground. */}
      <div role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
        {values.map((value) => {
          const isActive = selected.includes(value);
          return (
            <button
              key={value}
              type="button"
              aria-pressed={isActive}
              title={describe === undefined ? undefined : describe(value)}
              onClick={() => {
                onChange(
                  isActive ? selected.filter((member) => member !== value) : [...selected, value],
                );
              }}
              className={cn(TOGGLE_CLASS, toggleTone(isActive))}
            >
              {format(value)}
            </button>
          );
        })}
      </div>
    </FilterField>
  );
}

interface ToggleGroupSection<T extends string> {
  /** A stable slug — it becomes half of a DOM id, so it must be one. */
  readonly family: string;
  readonly label: string;
  readonly values: readonly T[];
}

interface GroupedEnumTogglesProps<T extends string> {
  readonly label: string;
  readonly groups: readonly ToggleGroupSection<T>[];
  readonly selected: readonly T[];
  readonly onChange: (next: readonly T[]) => void;
  readonly format: (value: T) => string;
  readonly hint?: string | undefined;
  readonly className?: string | undefined;
}

/**
 * One repeatable enum filter whose vocabulary is too large to wrap in a single row.
 *
 * The sections are ours and the members are the server's: nothing here filters the vocabulary
 * down, so every member is reachable and the OR semantics are unchanged — a selection spanning
 * two sections is one `?action=…&action=…` request, exactly as if the sections were not there.
 *
 * Each section is its own `role="group"`, named through `aria-labelledby` pointing at the
 * heading it already draws. The id is built from `useId()` plus the section's SLUG and never
 * from its label: `id="toggle-Operator accounts"` is invalid HTML, and since `aria-labelledby`
 * reads a space-separated list of ids, the group would end up unnamed rather than mislabelled.
 */
export function GroupedEnumToggles<T extends string>({
  label,
  groups,
  selected,
  onChange,
  format,
  hint,
  className,
}: GroupedEnumTogglesProps<T>): JSX.Element {
  const baseId = useId();

  return (
    <FilterField label={label} hint={hint} as="div" className={className}>
      <div className="flex flex-col gap-3">
        {groups.map((group) => {
          const headingId = `${baseId}-${group.family}`;
          return (
            <div key={group.family} className="flex flex-col gap-[6px]">
              <span id={headingId} className={SUBGROUP_LABEL_CLASS}>
                {group.label}
              </span>
              <div
                role="group"
                aria-labelledby={headingId}
                className="flex flex-wrap items-center gap-2"
              >
                {group.values.map((value) => {
                  const isActive = selected.includes(value);
                  return (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={isActive}
                      onClick={() => {
                        onChange(
                          isActive
                            ? selected.filter((member) => member !== value)
                            : [...selected, value],
                        );
                      }}
                      className={cn(TOGGLE_CLASS, "font-mono", toggleTone(isActive))}
                    >
                      {format(value)}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </FilterField>
  );
}

interface SingleEnumSelectProps<T extends string> {
  readonly label: string;
  readonly values: readonly T[];
  readonly value: T | null;
  readonly onChange: (next: T | null) => void;
  readonly format: (value: T) => string;
  readonly anyLabel?: string;
  readonly hint?: string | undefined;
}

/**
 * A scalar filter over a closed picker. `?subjectType=` (empty) filters on an empty string, so
 * "any" writes no parameter at all.
 *
 * The chosen member is looked up in `values` rather than cast out of the event, so a `<select>`
 * whose options ever fall out of step with the vocabulary cannot smuggle an unknown string into
 * a request.
 */
export function SingleEnumSelect<T extends string>({
  label,
  values,
  value,
  onChange,
  format,
  anyLabel = "any",
  hint,
}: SingleEnumSelectProps<T>): JSX.Element {
  return (
    <FilterField label={label} hint={hint}>
      <select
        className={FIELD_CLASS}
        value={value ?? ""}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(values.find((member) => member === raw) ?? null);
        }}
      >
        <option value="">{anyLabel}</option>
        {values.map((member) => (
          <option key={member} value={member}>
            {format(member)}
          </option>
        ))}
      </select>
    </FilterField>
  );
}

interface TextFilterProps {
  readonly label: string;
  readonly value: string | null;
  /** `""` is emitted as `null`, because an empty parameter is not an empty filter. */
  readonly onChange: (next: string | null) => void;
  /** The column's own width, where the server declares one. Over-length is a 422. */
  readonly maxLength?: number | undefined;
  readonly placeholder?: string | undefined;
  readonly hint?: string | undefined;
}

/**
 * A free-text equality filter — `actor`, `subjectId`. Exact match, never a substring.
 *
 * The box writes to the URL when typing STOPS, not on every keystroke. Every filter lives in
 * the address bar and the URL is the query key, so a keystroke-per-request box fires one
 * `/api/audit` call per character, and every intermediate value is an exact-match filter that
 * matches nothing: the table flashes "No entries match these filters" all the way through a
 * username before settling.
 *
 * Trimming happens at COMMIT and never on the way in. Trimming a controlled value on every
 * change erases a space the operator actually pressed, which reads as a broken field.
 */
export function TextFilter({
  label,
  value,
  onChange,
  maxLength,
  placeholder,
  hint,
}: TextFilterProps): JSX.Element {
  const [draft, setDraft] = useState(value ?? "");
  /** The last value this control PUT in the URL, so an echo of our own write is not a change. */
  const committed = useRef(value ?? "");
  const timer = useRef<number | null>(null);

  function cancel(): void {
    if (timer.current === null) return;
    window.clearTimeout(timer.current);
    timer.current = null;
  }

  function commit(next: string): void {
    cancel();
    const trimmed = next.trim();
    if (trimmed === committed.current) return;
    committed.current = trimmed;
    onChange(trimmed === "" ? null : trimmed);
  }

  /* The URL moved without us — a chip removal, Clear all, a pasted link, the back button. */
  useEffect(() => {
    const next = value ?? "";
    if (next === committed.current) return;
    committed.current = next;
    setDraft(next);
  }, [value]);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  return (
    <FilterField label={label} hint={hint}>
      <input
        type="text"
        inputMode="text"
        autoComplete="off"
        spellCheck={false}
        maxLength={maxLength}
        value={draft}
        placeholder={placeholder}
        className={cn(FIELD_CLASS, "font-mono text-[13px]")}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          cancel();
          timer.current = window.setTimeout(() => {
            timer.current = null;
            commit(next);
          }, FILTER_DEBOUNCE_MS);
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
    </FilterField>
  );
}

interface TimeRangeFilterProps {
  /** RFC 3339 with an offset, or `null`. Either bound may stand alone. */
  readonly from: string | null;
  readonly to: string | null;
  readonly onChange: (next: { readonly from: string | null; readonly to: string | null }) => void;
  /** `UTC+5` — which clock these two boxes are in. */
  readonly zoneLabel: string;
  /** Local `YYYY-MM-DDTHH:mm` values, converted by the caller. */
  readonly fromInput: string;
  readonly toInput: string;
  /** Local input value → RFC 3339, or `null` when the box was cleared. */
  readonly toIso: (localValue: string) => string | null;
}

/**
 * `at`, INCLUSIVE at both ends — `at >= from AND at <= to`.
 *
 * Not a half-open window, and the difference is a row rather than a nicety: this route
 * deliberately does not go through `resolve_window`, so `from` and `to` arrive as two
 * independent bounds and a row landing exactly on `to` is IN the answer. There is also no
 * `to < from` check on this route, so an inverted pair is an empty page rather than a refusal —
 * which is why the boxes say which end is which rather than calling themselves a range.
 *
 * The boxes are LOCAL time and say so: an operator setting a window against a support
 * conversation is reading a wall clock, and the API wants an offset either way — a naive
 * instant is a 422 that names the parameter.
 */
export function TimeRangeFilter({
  from,
  to,
  onChange,
  zoneLabel,
  fromInput,
  toInput,
  toIso,
}: TimeRangeFilterProps): JSX.Element {
  const { t } = useI18n();

  return (
    <FilterField
      label={t("reveal.dateRange.recorded")}
      hint={t("reveal.dateRange.bothEndsHint", { zone: zoneLabel })}
      as="div"
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="datetime-local"
          aria-label={t("reveal.dateRange.recordedFrom")}
          value={fromInput}
          className={cn(FIELD_CLASS, "w-auto min-w-0 flex-1")}
          onChange={(event) => {
            onChange({ from: toIso(event.target.value), to });
          }}
        />
        <span aria-hidden className="text-[12px] text-ink-300">
          to
        </span>
        <input
          type="datetime-local"
          aria-label={t("reveal.dateRange.recordedTo")}
          value={toInput}
          className={cn(FIELD_CLASS, "w-auto min-w-0 flex-1")}
          onChange={(event) => {
            onChange({ from, to: toIso(event.target.value) });
          }}
        />
      </div>
    </FilterField>
  );
}
