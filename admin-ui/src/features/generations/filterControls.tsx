/**
 * `/generations`' filter controls. §11.4's inventory names `FilterBar` but no form controls
 * to put inside it, so the screen brings its own — plain elements over the design tokens,
 * no popover to position under the production CSP.
 *
 * `/generations` has one filter shape the other lists do not: `strategy` is a SINGLE
 * `NameStrategy`, not a repeated one, because `AttemptFilters.strategy` is scalar
 * server-side. It gets a `<select>` and not a toggle group precisely so the difference is
 * visible in the markup rather than discovered as a 422.
 *
 * The reskin took their borders away: a control here carries its own GROUND
 * (`--surface-control`) rather than a 1px outline, and "on" is the brand tint with the brand
 * hue as the label — the same pill the rail wears for the active route. Both states keep a
 * text-bar colour, `--ink-muted` off and `--brand` on. These deliberately match
 * `features/users/filterControls.tsx` class for class; if a third screen needs them, the
 * answer is a shared primitive under `components/data/`, not a cross-feature import.
 */

import type { ReactElement } from "react";

import { Button, segmentVariant } from "@/components/util";

export interface EnumToggleGroupProps<T extends string> {
  /** Our own closed vocabulary, in declaration order. */
  readonly values: readonly T[];
  readonly selected: readonly T[] | undefined;
  /** Emits `undefined` when the last member is turned off, so the parameter is dropped. */
  readonly onChange: (next: readonly T[] | undefined) => void;
  readonly format: (value: T) => string;
  readonly label: string;
}

/** A repeatable enum filter — `?kind=song&kind=greeting` — as toggles. OR within the field. */
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
  readonly trueLabel: string;
  readonly falseLabel: string;
  readonly anyLabel?: string;
}

/** A boolean filter with three positions, because `isSuccess` and `isOrphaned` have three. */
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

export interface SingleEnumSelectProps<T extends string> {
  readonly label: string;
  readonly values: readonly T[];
  readonly value: T | undefined;
  readonly onChange: (next: T | undefined) => void;
  readonly format: (value: T) => string;
  readonly anyLabel?: string;
}

/** A scalar enum filter. `?strategy=` (empty) is a 422, so absence writes no parameter. */
export function SingleEnumSelect<T extends string>({
  label,
  values,
  value,
  onChange,
  format,
  anyLabel = "any",
}: SingleEnumSelectProps<T>): ReactElement {
  return (
    <label className="type-body-sm flex items-center gap-2 text-ink-muted">
      <span>{label}</span>
      <select
        className="type-body-sm rounded-control bg-surface-control px-3 py-1.5 text-ink"
        value={value ?? ""}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === "" ? undefined : (next as T));
        }}
      >
        <option value="">{anyLabel}</option>
        {values.map((member) => (
          <option key={member} value={member}>
            {format(member)}
          </option>
        ))}
      </select>
    </label>
  );
}

export interface TextFilterProps {
  readonly label: string;
  readonly value: string | undefined;
  readonly onChange: (next: string | undefined) => void;
  readonly maxLength: number;
  readonly placeholder?: string;
}

/**
 * A free-text equality filter — `provider`, `errorCode`.
 *
 * Written on `change`, not on every keystroke's own history entry: `useSearchParamsState`
 * writes with `replace`, which is what keeps the back button usable while typing. The
 * `maxLength` mirrors the column's own bound (`PROVIDER_LENGTH`, `ERROR_CODE_LENGTH`), so an
 * over-long paste is refused here rather than by a 422.
 */
export function TextFilter({
  label,
  value,
  onChange,
  maxLength,
  placeholder,
}: TextFilterProps): ReactElement {
  return (
    <label className="type-body-sm flex items-center gap-2 text-ink-muted">
      <span>{label}</span>
      <input
        type="text"
        maxLength={maxLength}
        value={value ?? ""}
        placeholder={placeholder ?? ""}
        className="type-mono w-40 rounded-control bg-surface-control px-3 py-1.5 text-ink placeholder:text-ink-muted"
        onChange={(event) => {
          const next = event.target.value.trim();
          onChange(next === "" ? undefined : next);
        }}
      />
    </label>
  );
}
