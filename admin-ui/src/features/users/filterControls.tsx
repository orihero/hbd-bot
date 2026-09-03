/**
 * The two filter controls `/users` needs and §11.4's component inventory does not name.
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
 * Both are local to this screen on purpose. If a third screen needs either, the answer is a
 * shared primitive under `components/data/`, not a cross-feature import.
 */

import type { ReactElement } from "react";

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
