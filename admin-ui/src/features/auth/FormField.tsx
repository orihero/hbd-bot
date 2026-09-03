/**
 * One labelled input.
 *
 * Local to the auth screens because it is the only place in the console with a form that
 * takes typed secrets, and because a shared form primitive is not in the §11.4 inventory —
 * inventing one from a feature directory is how two half-finished ones end up in
 * `components/`.
 *
 * The label is a real `<label htmlFor>` rather than a placeholder: a placeholder disappears
 * on focus, and a password field whose label vanishes the moment you type into it is how the
 * current-password box and the new-password box get confused.
 *
 * ## The input carries a ground instead of a border
 *
 * That is the design's rule for every control, and it is what `--surface-control` exists for.
 * The invalid state is NOT a red border, because a border is the one channel this language
 * does not have: it is a light `--error-tint` ground plus the message below, which stays
 * legible in greyscale and reads the same to somebody who cannot pick red out of grey. The
 * focus ring is the global `:focus-visible` outline from `index.css` — 2px of `--focus-ring`
 * with an offset — so this input focuses exactly like every other control in the console
 * rather than inventing its own.
 */

import { type ReactElement } from "react";

import { cn } from "@/lib";

export interface FormFieldProps {
  readonly id: string;
  readonly label: string;
  readonly type: "text" | "password";
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly autoComplete?: string;
  readonly hint?: string | undefined;
  /** A client-side validation message. Server messages go through `AuthFailureNotice`. */
  readonly error?: string | undefined;
  readonly maxLength?: number | undefined;
  readonly autoFocus?: boolean;
}

export function FormField({
  id,
  label,
  type,
  value,
  onChange,
  autoComplete,
  hint,
  error,
  maxLength,
  autoFocus = false,
}: FormFieldProps): ReactElement {
  const describedBy = [hint === undefined ? null : `${id}-hint`, error === undefined ? null : `${id}-error`]
    .filter((entry): entry is string => entry !== null)
    .join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="type-body-sm font-semibold text-ink">
        {label}
      </label>
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        // The sign-in username is the only interactive element on a screen the operator
        // arrived at in order to type into it; nothing else is focusable to steal.
        autoFocus={autoFocus}
        aria-invalid={error !== undefined}
        aria-describedby={describedBy === "" ? undefined : describedBy}
        {...(autoComplete === undefined ? {} : { autoComplete })}
        {...(maxLength === undefined ? {} : { maxLength })}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className={cn(
          "type-body rounded-control px-4 py-2.5 text-ink",
          "transition-colors duration-fast ease-standard",
          // A tinted ground for the invalid state, not a red outline: this design has no
          // borders, and the message below carries the fact in words either way.
          error === undefined ? "bg-surface-control" : "bg-error-tint",
        )}
      />
      {hint === undefined ? null : (
        <p id={`${id}-hint`} className="type-body-sm text-ink-muted">
          {hint}
        </p>
      )}
      {error === undefined ? null : (
        <p id={`${id}-error`} className="type-body-sm text-error">
          {error}
        </p>
      )}
    </div>
  );
}
