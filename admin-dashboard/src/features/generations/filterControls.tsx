import { useEffect, useId, useRef, useState, type JSX, type ReactNode } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * The Generations filter panel's controls.
 *
 * The kit ships a toolbar with a **Filters** button and no controls to put behind it, so this
 * screen brings its own — plain elements over the design tokens, no popover to position and
 * nothing to load under the production CSP. Every measurement is the kit's: a 47-high field at
 * radius 10 with a 1px `--stroke` edge (the login form's exact box), the 16/400/-0.64 `--ink-300`
 * column-header type for a group label, and the toolbar's 12/600 for a chip-shaped toggle.
 *
 * Three shapes, because the API has three, and the difference between them is a 422 rather
 * than a preference:
 *
 *  - **`kind` REPEATS** (`?kind=song&kind=lyrics` — OR within the field, AND across fields), so
 *    it is a toggle group. An empty selection omits the parameter, which means "do not filter"
 *    and not "match nothing".
 *  - **`strategy` is SCALAR.** `AttemptFilters.strategy` is one `NameStrategy`, and a repeated
 *    parameter is a 422 — so it gets a `<select>`, and the difference is visible in the markup
 *    instead of being discovered from a refused request.
 *  - **`isSuccess` and `isOrphaned` are TRI-STATE.** Absent, `true` and `false` are three
 *    different questions, and `?isSuccess=` is a 422. So "any" is a real option that writes no
 *    parameter, not a `false` in disguise.
 *
 * `provider` and `errorCode` are free-form on the wire because their vocabularies belong to a
 * vendor and to the pipeline. The provider input therefore SUGGESTS the nine adapter names this
 * deployment actually writes without constraining them: a picker that refused an adapter shipped
 * tomorrow would return an empty page for ever and read as an outage. Both inputs cap their own
 * length, because an over-long value is a 422 naming the parameter and truncating it here would
 * hide that behind a page nobody asked for.
 *
 * The class lists mirror `features/reveal/controls.ts` field for field. They are duplicated
 * rather than cross-imported because they are one feature's controls, not a shared primitive;
 * if a third screen needs them the answer is a component under `src/components/`, not a deep
 * import into a sibling feature.
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

/** How long a free-text box waits after the last keystroke before it writes to the URL. */
const FILTER_DEBOUNCE_MS = 300;

const TOGGLE_CLASS = cn(
  "cursor-pointer rounded-chip px-3 py-[6px]",
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px]",
  "transition-[background-color,color]",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
);

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
      {hint === undefined ? null : (
        <span className="text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-400">
          {hint}
        </span>
      )}
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
}

/** A repeatable enum filter, as toggles. OR within the field. */
export function EnumToggleGroup<T extends string>({
  label,
  values,
  selected,
  onChange,
  format,
}: EnumToggleGroupProps<T>): JSX.Element {
  return (
    <FilterField label={label} as="div">
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
              onClick={() => {
                onChange(
                  isActive ? selected.filter((member) => member !== value) : [...selected, value],
                );
              }}
              className={cn(
                TOGGLE_CLASS,
                isActive
                  ? "bg-accent-70 text-ink-800"
                  : "border border-stroke bg-card text-ink-500 hover:bg-bg",
              )}
            >
              {format(value)}
            </button>
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
 * A scalar enum filter. `?strategy=` (empty) is a 422, so "any" writes no parameter at all.
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

interface TriStateSelectProps {
  readonly label: string;
  /** `null` is a THIRD state — the parameter is absent, which is not the same as `false`. */
  readonly value: boolean | null;
  readonly onChange: (next: boolean | null) => void;
  readonly trueLabel: string;
  readonly falseLabel: string;
  readonly anyLabel?: string;
  readonly hint?: string | undefined;
}

/** A boolean filter with the three positions the API actually has. */
export function TriStateSelect({
  label,
  value,
  onChange,
  trueLabel,
  falseLabel,
  anyLabel = "any",
  hint,
}: TriStateSelectProps): JSX.Element {
  return (
    <FilterField label={label} hint={hint}>
      <select
        className={FIELD_CLASS}
        value={value === null ? "" : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === "" ? null : raw === "true");
        }}
      >
        <option value="">{anyLabel}</option>
        <option value="true">{trueLabel}</option>
        <option value="false">{falseLabel}</option>
      </select>
    </FilterField>
  );
}

interface TextFilterProps {
  readonly label: string;
  readonly value: string | null;
  /** `""` is emitted as `null`, because an empty parameter is not an empty filter. */
  readonly onChange: (next: string | null) => void;
  /** The column's own width. An over-long value is a 422 naming the parameter. */
  readonly maxLength: number;
  readonly placeholder?: string | undefined;
  /**
   * Offered, never enforced. The column is free-form `varchar`, so a vendor adapter added
   * tomorrow must still be typeable — a closed picker here would answer an empty page for ever
   * and read as an outage.
   */
  readonly suggestions?: readonly string[] | undefined;
  readonly hint?: string | undefined;
}

/**
 * A free-text equality filter — `provider`, `errorCode`. Exact match, never a substring.
 *
 * The box writes to the URL when typing STOPS, not on every keystroke. Every filter lives in
 * the address bar and the URL is the query key, so a keystroke-per-request box fires one
 * `/api/generations` call — plus its `bounded_total` count — per character, and every
 * intermediate value is an exact-match filter that matches nothing: the table flashes "No
 * attempts match these filters" all the way through a provider name before settling.
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
  suggestions,
  hint,
}: TextFilterProps): JSX.Element {
  const listId = useId();
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
        list={suggestions === undefined ? undefined : listId}
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
      {suggestions === undefined ? null : (
        <datalist id={listId}>
          {suggestions.map((suggestion) => (
            <option key={suggestion} value={suggestion} />
          ))}
        </datalist>
      )}
    </FilterField>
  );
}

interface TimeRangeFilterProps {
  /** RFC 3339, or `null`. Either end may stand alone — `resolve_window` accepts a half window. */
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
 * `created_at`, half-open `[from, to)`.
 *
 * Either end may stand alone: the opaque cursor carries `(created_at, id)`, so page two
 * resumes strictly before page one's last row however the upper bound has moved — which is
 * why the router stopped refusing a half window. The boxes are LOCAL time and say so, because
 * an operator setting a window against a support conversation is reading a wall clock.
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
      label={t("reveal.dateRange.created")}
      hint={t("reveal.dateRange.halfOpenHint", { zone: zoneLabel })}
      as="div"
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="datetime-local"
          aria-label={t("reveal.dateRange.createdFrom")}
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
          aria-label={t("reveal.dateRange.createdTo")}
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
