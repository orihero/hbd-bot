/**
 * The four filter controls `/users` needs and §11.4's component inventory does not name.
 *
 * The inventory lists `FilterBar` (the URL-backed removable chips) but no form controls to
 * put inside it, so each screen brings its own. These are deliberately plain `<button>` and
 * `<select>` elements over the design tokens rather than a Radix `Select`: the whole surface
 * of the control is one value, keyboard behaviour is the platform's, and there is no popover
 * to position under the production CSP.
 *
 * The reskin took their borders away. In this language a control carries its own GROUND
 * (`--surface-control`) instead of a 1px outline, and "on" is the brand tint with the brand
 * hue as the label — the same pill the nav rail wears for the active route, so "selected"
 * means one thing everywhere. Both states keep a text-bar colour: `--ink-muted` off,
 * `--brand` on, each measured over the ground it actually sits on.
 *
 * All four are local to this screen on purpose. If a second screen needs one of them, the
 * answer is a shared primitive under `components/data/`, not a cross-feature import.
 */

import { useEffect, useRef, useState, type ReactElement } from "react";

import { Button, segmentVariant } from "@/components/util";

export interface EnumToggleGroupProps<T extends string> {
  /** Our own closed vocabulary, in declaration order — never sorted, never user content. */
  readonly values: readonly T[];
  /** The members currently selected. `undefined` means "no filter", not "none selected". */
  readonly selected: readonly T[] | undefined;
  /** Emits `undefined` when the last member is turned off, so the parameter is dropped. */
  readonly onChange: (next: readonly T[] | undefined) => void;
  /** How one member reads. `humaniseEnum`, usually. */
  readonly format: (value: T) => string;
  readonly label: string;
}

/**
 * A repeatable enum filter — `?uiLanguage=ru&uiLanguage=en` — as toggles.
 *
 * Toggles rather than a `<select multiple>` because the API's repeated parameter is an OR
 * and a multi-select hides that: an operator has to know to hold a modifier to express it,
 * and cannot see at a glance which members are on.
 */
export function EnumToggleGroup<T extends string>({
  values,
  selected,
  onChange,
  format,
  label,
}: EnumToggleGroupProps<T>): ReactElement {
  const active = selected ?? [];
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1">
      {/* `type-body-sm`, not `type-caption`: the caption scale uppercases, and this label
          sits inches from the `<select>` labels in the same bar, which do not. One filter
          bar should not carry two label typographies. */}
      <span className="type-body-sm text-ink-muted">{label}</span>
      {values.map((value) => {
        const isActive = active.includes(value);
        return (
          /* Selected is the secondary idiom, unselected is `quiet` — one helper, the same
             pairing as the tab strip and the nav rail. `aria-pressed` is the channel that
             depends on seeing neither. */
          <Button
            key={value}
            variant={segmentVariant(isActive)}
            size="xs"
            shape="pill"
            aria-pressed={isActive}
            onClick={() => {
              const next = isActive
                ? active.filter((member) => member !== value)
                : [...active, value];
              onChange(next.length === 0 ? undefined : next);
            }}
          >
            {format(value)}
          </Button>
        );
      })}
    </div>
  );
}

export interface TriStateSelectProps {
  readonly label: string;
  /** `undefined` is a THIRD state — the parameter is absent, not `false`. */
  readonly value: boolean | undefined;
  readonly onChange: (next: boolean | undefined) => void;
  /** What `true` reads as, e.g. `blocked`. */
  readonly trueLabel: string;
  /** What `false` reads as, e.g. `not blocked`. */
  readonly falseLabel: string;
  /** What absence reads as, e.g. `any`. */
  readonly anyLabel?: string;
}

/**
 * A boolean filter with three positions, because `isBlocked` has three.
 *
 * Absent is not `false` here any more than it is on the wire: `?isBlocked=false` asks for
 * the people who are demonstrably not blocked, and no parameter at all asks for everyone.
 * A checkbox would collapse the two and quietly halve the list.
 */
export function TriStateSelect({
  label,
  value,
  onChange,
  trueLabel,
  falseLabel,
  anyLabel = "any",
}: TriStateSelectProps): ReactElement {
  return (
    <label className="type-body-sm flex items-center gap-2 text-ink-muted">
      <span>{label}</span>
      <select
        className="type-body-sm rounded-control bg-surface-control px-3 py-1.5 text-ink"
        value={value === undefined ? "" : String(value)}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === "" ? undefined : next === "true");
        }}
      >
        <option value="">{anyLabel}</option>
        <option value="true">{trueLabel}</option>
        <option value="false">{falseLabel}</option>
      </select>
    </label>
  );
}

/** How long the box waits after the last keystroke before it writes to the URL. */
export const FILTER_DEBOUNCE_MS = 300;

export interface DebouncedTextInputProps {
  readonly label: string;
  /** The COMMITTED value — what the URL says. `undefined` means the parameter is absent. */
  readonly value: string | undefined;
  /** Fired once the typing settles, and immediately on Enter or on blur. */
  readonly onChange: (next: string | undefined) => void;
  /** Must say what is actually searchable. See the note on `q` in `endpoints.ts`. */
  readonly placeholder: string;
  /** Explains the control's narrowness where a placeholder has no room to. */
  readonly title?: string;
  /** Digits only: strips everything else as it is typed, and asks for a numeric keypad. */
  readonly isNumeric?: boolean;
  /**
   * Hard character cap, mirroring the server's own limit on the parameter.
   *
   * Without it a pasted paragraph is sent verbatim and the SERVER rejects the whole request —
   * so an over-long paste does not narrow the list, it empties it behind a 422 that names a
   * parameter rather than the box the operator pasted into.
   */
  readonly maxLength?: number;
  readonly delayMs?: number;
  readonly widthClassName?: string;
}

/**
 * A text filter that writes to the URL when the typing STOPS, not on every keystroke.
 *
 * Every filter on this screen lives in the address bar (§11.1), and `patch` writes with
 * `replace` — but a keystroke-per-request box still fires one `/api/users` call per character
 * and throws away every response but the last. So the draft is component state and the URL is
 * written once the operator pauses, which is the only piece of filter state on this screen
 * that is briefly not in the URL.
 *
 * The draft follows the URL back the other way as well: removing the chip, or pressing Clear,
 * empties the box. Without that the removed filter would still be sitting in the input,
 * waiting for one more keystroke to reapply itself.
 */
export function DebouncedTextInput({
  label,
  value,
  onChange,
  placeholder,
  title,
  isNumeric = false,
  maxLength,
  delayMs = FILTER_DEBOUNCE_MS,
  widthClassName = "w-48",
}: DebouncedTextInputProps): ReactElement {
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
    if (next === committed.current) return;
    committed.current = next;
    onChange(next === "" ? undefined : next);
  }

  /* The URL moved without us — a chip removal, Clear, a pasted link, the back button. */
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
    <label className="type-body-sm flex items-center gap-2 text-ink-muted">
      <span>{label}</span>
      <input
        type="text"
        value={draft}
        placeholder={placeholder}
        {...(title === undefined ? {} : { title })}
        {...(isNumeric ? ({ inputMode: "numeric" } as const) : {})}
        {...(maxLength === undefined ? {} : { maxLength })}
        className={`type-body-sm rounded-control bg-surface-control px-3 py-1.5 text-ink placeholder:text-ink-muted ${widthClassName}`}
        onChange={(event) => {
          // Digits are stripped in the CONTROL rather than by the parent's parse, so the box
          // never shows a value the filter is quietly ignoring.
          const next = isNumeric ? event.target.value.replace(/\D/gu, "") : event.target.value;
          setDraft(next);
          cancel();
          timer.current = window.setTimeout(() => {
            timer.current = null;
            commit(next);
          }, delayMs);
        }}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          // An operator who pressed Enter has finished typing and should not wait out a timer.
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

export interface QuickFilterChipProps {
  readonly label: string;
  readonly isActive: boolean;
  /** Receives the state being moved TO, so the caller writes one `patch` and no negation. */
  readonly onToggle: (isActive: boolean) => void;
  /** What the preset actually asks the API for. */
  readonly title?: string;
}

/**
 * A one-click preset over a filter that already exists.
 *
 * It is deliberately a TOGGLE and not a link to a pre-built URL: `aria-pressed` is what tells
 * a screen reader the list is narrowed, and pressing it a second time has to widen the list
 * again rather than stack a second copy of the same parameter. It owns no state — "on" is
 * read back out of the URL, so a chip and the control it shortcuts can never disagree.
 */
export function QuickFilterChip({
  label,
  isActive,
  onToggle,
  title,
}: QuickFilterChipProps): ReactElement {
  return (
    <Button
      variant={segmentVariant(isActive)}
      size="xs"
      shape="pill"
      aria-pressed={isActive}
      data-quick-filter={label}
      {...(title === undefined ? {} : { title })}
      onClick={() => {
        onToggle(!isActive);
      }}
    >
      {label}
    </Button>
  );
}
