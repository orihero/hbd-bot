/**
 * The form controls the Users toolbar puts inside its filter panel.
 *
 * The kit draws a toolbar with a "Filters" button and no controls to put behind it, so this
 * file supplies them in the toolbar's own language: 48-high boxes at radius 10 over a 1px
 * --stroke, the same geometry as `ToolbarButton`, so the panel reads as part of the bar it
 * opened from. Plain `<input>`, `<select>` and `<button>` over the tokens — there is no
 * popover to position, keyboard behaviour is the platform's, and every control's whole
 * surface is one value.
 *
 * Three decisions here are not cosmetic:
 *
 * 1. **A boolean filter has THREE positions.** `?isBlocked=` absent asks for everyone,
 *    `=true` for the blocked, `=false` for the demonstrably not-blocked — and on
 *    `hasBalance`, `false` deliberately includes the customer with no `credit_accounts` row
 *    at all. A checkbox would collapse absent and `false` into one control and silently halve
 *    the list, so `<TriStateSelect>` spells all three.
 * 2. **A repeated parameter is drawn as toggles.** `?uiLanguage=ru&uiLanguage=en` is an OR
 *    within the field; a `<select multiple>` hides that behind a modifier key nobody presses.
 *    `uz_latn` and `uz_cyrl` are two SCRIPTS and each gets its own toggle — collapsing them
 *    into "Uzbek" would ask a question the API cannot answer.
 * 3. **The text box writes to the URL when typing STOPS.** Every filter lives in the address
 *    bar, but a keystroke-per-request box fires one `/api/users` call per character and
 *    throws away every answer but the last. The draft is component state; the URL is written
 *    on a pause, on Enter and on blur. The draft also follows the URL back the other way, so
 *    removing a chip empties the box instead of leaving it primed to reapply itself.
 */

import { useEffect, useId, useRef, useState, type JSX } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/* -------------------------------------------------------------------------- */
/* Shared geometry                                                             */
/* -------------------------------------------------------------------------- */

/** A field, sized to the toolbar's 48-high button so a filter row lines up with it. */
const FIELD_CLASS = cn(
  "h-12 rounded-field border border-stroke bg-card px-3",
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-label",
  "outline-none transition-shadow placeholder:text-muted",
  "focus:border-accent-deep focus:ring-2 focus:ring-accent",
);

/** The kit's column-header type, reused as the label above a control. */
const CONTROL_LABEL_CLASS =
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-500";

/** The sentence under a control that says what it actually asks the API for. */
const CONTROL_HINT_CLASS =
  "m-0 max-w-[38ch] text-[11px] font-normal leading-[1.35] text-ink-400";

function ControlHint({
  hint,
}: {
  readonly hint: string | undefined;
}): JSX.Element | null {
  if (hint === undefined) return null;
  return <p className={CONTROL_HINT_CLASS}>{hint}</p>;
}

/* -------------------------------------------------------------------------- */
/* Search                                                                      */
/* -------------------------------------------------------------------------- */

/** How long the box waits after the last keystroke before it writes to the URL. */
export const FILTER_DEBOUNCE_MS = 300;

export interface SearchFieldProps {
  /** The COMMITTED value — what the URL says. `null` means the parameter is absent. */
  readonly value: string | null;
  /** Fired once the typing settles, and immediately on Enter or on blur. */
  readonly onChange: (next: string | null) => void;
  /**
   * The control's accessible name. It MUST name what is searchable: this box matches a
   * substring of the Telegram id and nothing else, and a label naming the people rather than
   * the id would send an operator hunting for a name and teach them the list is broken.
   */
  readonly label: string;
  readonly placeholder: string;
  /** Said where the placeholder has no room — on hover and to a screen reader. */
  readonly hint: string;
  /**
   * The server's own cap on the parameter, mirrored on the INPUT.
   *
   * Without it a pasted paragraph is sent verbatim and the request is refused whole, so an
   * over-long paste does not narrow the list — it empties it behind a 422 naming a parameter
   * rather than the box that was pasted into. Nothing is truncated after the fact: a value
   * that arrives over-length in a pasted URL is still sent, and its 422 is rendered.
   */
  readonly maxLength: number;
  readonly delayMs?: number;
  readonly className?: string | undefined;
  /**
   * Which soft keyboard a phone should raise. Defaults to `"numeric"`, which is what every
   * filter on the records screen wants: all four of them search a Telegram id, and a digit
   * pad is the difference between a two-second lookup and a scroll through a QWERTY layout.
   *
   * It became a prop when the support board reused this control for two TEXT filters — a
   * reference and an operator's username. A word search on a numeric pad is a keyboard the
   * reader has to dismiss before they can type, which is worse than no hint at all. The
   * default stays numeric rather than becoming `"text"` so that the four filters this
   * control was built for keep the behaviour they were given deliberately; a caller
   * searching words asks for `"search"`.
   */
  readonly inputMode?: "numeric" | "search";
}

export function SearchField({
  value,
  onChange,
  label,
  placeholder,
  hint,
  maxLength,
  delayMs = FILTER_DEBOUNCE_MS,
  className,
  inputMode = "numeric",
}: SearchFieldProps): JSX.Element {
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
    <label className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="sr-only">{label}</span>
      <input
        type="search"
        value={draft}
        placeholder={placeholder}
        title={hint}
        aria-label={label}
        inputMode={inputMode}
        maxLength={maxLength}
        className={cn(FIELD_CLASS, "w-full min-w-0")}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          cancel();
          timer.current = window.setTimeout(() => {
            timer.current = null;
            commit(next);
          }, delayMs);
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
    </label>
  );
}

/* -------------------------------------------------------------------------- */
/* Tri-state                                                                   */
/* -------------------------------------------------------------------------- */

export interface TriStateSelectProps {
  readonly label: string;
  /** `null` is a THIRD state — the parameter is absent, not `false`. */
  readonly value: boolean | null;
  readonly onChange: (next: boolean | null) => void;
  readonly trueLabel: string;
  readonly falseLabel: string;
  /** What absence reads as. "Any", always — it is not a filter. */
  readonly anyLabel?: string;
  /** What the two named positions actually ask the API for. */
  readonly hint?: string | undefined;
}

export function TriStateSelect({
  label,
  value,
  onChange,
  trueLabel,
  falseLabel,
  anyLabel,
  hint,
}: TriStateSelectProps): JSX.Element {
  const { t } = useI18n();

  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className={CONTROL_LABEL_CLASS}>{label}</span>
      <select
        className={cn(FIELD_CLASS, "w-full min-w-[10rem] pr-2")}
        value={value === null ? "" : String(value)}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === "" ? null : next === "true");
        }}
      >
        <option value="">{anyLabel ?? t("common.any")}</option>
        <option value="true">{trueLabel}</option>
        <option value="false">{falseLabel}</option>
      </select>
      <ControlHint hint={hint} />
    </label>
  );
}

/* -------------------------------------------------------------------------- */
/* Repeatable enum                                                             */
/* -------------------------------------------------------------------------- */

export interface EnumToggleGroupProps<T extends string> {
  readonly label: string;
  /** Our own closed vocabulary, in declaration order — never sorted, never user content. */
  readonly values: readonly T[];
  /** The members currently selected. An empty list means "no filter", not "none selected". */
  readonly selected: readonly T[];
  readonly onChange: (next: readonly T[]) => void;
  /** How one member reads. Never the wire spelling. */
  readonly format: (value: T) => string;
  readonly hint?: string | undefined;
}

/** A repeated parameter — `?uiLanguage=ru&uiLanguage=en` — as toggles, because it is an OR. */
export function EnumToggleGroup<T extends string>({
  label,
  values,
  selected,
  onChange,
  format,
  hint,
}: EnumToggleGroupProps<T>): JSX.Element {
  /* Minted, never derived from the label: `id="toggle-Bot language"` is invalid HTML, and
     `aria-labelledby` reads a SPACE-SEPARATED list of ids — so a label with a space in it
     resolves to two ids that do not exist and the group ends up with no accessible name. */
  const labelId = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className={CONTROL_LABEL_CLASS} id={labelId}>
        {label}
      </span>
      <div
        role="group"
        aria-labelledby={labelId}
        className="flex flex-wrap gap-2"
      >
        {values.map((value) => {
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
              className={cn(
                "h-9 cursor-pointer rounded-chip px-3",
                "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px]",
                "transition-[background-color,color,filter]",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
                isActive
                  ? "bg-accent-70 text-ink-800 hover:brightness-95"
                  : "border border-stroke bg-card text-ink-500 hover:bg-bg",
              )}
            >
              {format(value)}
            </button>
          );
        })}
      </div>
      <ControlHint hint={hint} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Date range                                                                  */
/* -------------------------------------------------------------------------- */

const DATE_INPUT_PATTERN = /^\d{4}-\d{2}-\d{2}$/u;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * `YYYY-MM-DD` from a date input → the RFC 3339 instant that day BEGINS, in the operator's
 * own zone.
 *
 * Local, not UTC: an operator filtering "from the 7th" means their 7th. `null` for anything
 * that is not a date — a half-typed field must drop the parameter rather than send a string
 * the server will 422, because a 422 empties the table and blames a parameter nobody typed.
 */
export function startOfLocalDayIso(date: string): string | null {
  if (!DATE_INPUT_PATTERN.test(date)) return null;
  const parts = date.split("-");
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  const at = new Date(year, month - 1, day);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString();
}

/**
 * The same, for the END of the range.
 *
 * The window is half-open `[from, to)`, so "to the 7th" is the instant the 8th begins —
 * anything else drops the last day's orders and reads as a customer who stopped a day early.
 */
export function endOfLocalDayExclusiveIso(date: string): string | null {
  if (!DATE_INPUT_PATTERN.test(date)) return null;
  const parts = date.split("-");
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  const at = new Date(year, month - 1, day + 1);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString();
}

/**
 * An instant from the URL, back into what the date input shows.
 *
 * The exclusive end is stepped back a millisecond first, so the day the operator picked is
 * the day the box redisplays. An instant this screen did not mint — a hand-edited link —
 * renders as the local day it falls in; the URL keeps the exact value until the field is
 * changed, so nothing is silently rounded behind an operator's back.
 */
export function dateInputValue(
  iso: string | null,
  bound: "start" | "endExclusive",
): string {
  if (iso === null) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const shown = bound === "endExclusive" ? new Date(at.getTime() - 1) : at;
  return `${String(shown.getFullYear())}-${pad(shown.getMonth() + 1)}-${pad(shown.getDate())}`;
}

export interface DateRangeFieldsProps {
  readonly label: string;
  /** RFC 3339 instants, or `null`. Either end may stand alone. */
  readonly from: string | null;
  readonly to: string | null;
  readonly onChange: (next: {
    readonly from: string | null;
    readonly to: string | null;
  }) => void;
  readonly hint?: string | undefined;
}

/** The account-creation window, as two day pickers over a half-open range. */
export function DateRangeFields({
  label,
  from,
  to,
  onChange,
  hint,
}: DateRangeFieldsProps): JSX.Element {
  const { t } = useI18n();
  /* See `EnumToggleGroup`: a derived id carrying a space names nothing. */
  const labelId = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className={CONTROL_LABEL_CLASS} id={labelId}>
        {label}
      </span>
      <div
        role="group"
        aria-labelledby={labelId}
        className="flex flex-wrap items-center gap-2"
      >
        <input
          type="date"
          aria-label={t("common.rangeFrom", { label })}
          value={dateInputValue(from, "start")}
          className={cn(FIELD_CLASS, "min-w-[9.5rem]")}
          onChange={(event) => {
            onChange({ from: startOfLocalDayIso(event.target.value), to });
          }}
        />
        <span aria-hidden className="text-[12px] text-ink-300">
          {t("common.to")}
        </span>
        <input
          type="date"
          aria-label={t("common.rangeTo", { label })}
          value={dateInputValue(to, "endExclusive")}
          className={cn(FIELD_CLASS, "min-w-[9.5rem]")}
          onChange={(event) => {
            onChange({
              from,
              to: endOfLocalDayExclusiveIso(event.target.value),
            });
          }}
        />
      </div>
      <ControlHint hint={hint} />
    </div>
  );
}
