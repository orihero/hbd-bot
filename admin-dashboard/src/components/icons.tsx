/**
 * Design vectors, inlined.
 *
 * Every path here is the real geometry exported from the OpenPencil source (see the
 * provenance copies in src/assets/), not a redrawn approximation. They are inline rather
 * than <img src="…svg"> so they can take `currentColor` and a Tailwind size class.
 *
 * All three are decorative: they never carry the accessible name, the surrounding label or
 * button text does. Hence the unconditional aria-hidden.
 */

import { clsx } from "clsx";

import logoUrl from "@/assets/logo.png";

interface IconProps {
  /** Sizing and colour come from the caller; these have no intrinsic dimensions. */
  readonly className?: string;
}

/** The brand logo mark (src/assets/logo.png). */
export function BrandMark({ className }: IconProps) {
  return (
    <img
      src={logoUrl}
      alt="Bayram logo"
      className={clsx("rounded-full object-cover shrink-0 select-none", className)}
      aria-hidden="true"
      draggable={false}
    />
  );
}

/**
 * The password field's eye. src/assets/eye.svg — OpenPencil node 0:3010.
 *
 * `slashed` is an addition: the kit ships only the open eye, and a toggle whose icon never
 * changes gives a sighted user no read on which state they are in. The slash is drawn to the
 * icon's own stroke spec (1.5, round caps) so it sits in the same family.
 */
export function EyeIcon({ className, slashed = false }: IconProps & { readonly slashed?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      <path
        transform="translate(8.42, 8.42)"
        d="M7.16 3.58C7.16 5.56 5.56 7.16 3.58 7.16C1.6 7.16 0 5.56 0 3.58C0 1.6 1.6 0 3.58 0C5.56 0 7.16 1.6 7.16 3.58Z"
      />
      <path
        transform="translate(2.21, 3.72)"
        d="M9.78 16.55C13.31 16.55 16.61 14.47 18.9 10.87C19.8 9.46 19.8 7.09 18.9 5.68C16.61 2.08 13.31 0 9.78 0C6.25 0 2.96 2.08 0.67 5.68C-0.23 7.09 -0.23 9.46 0.67 10.87C2.96 14.47 6.25 16.55 9.78 16.55Z"
      />
      {slashed ? <path d="M3.5 20.5L20.5 3.5" /> : null}
    </svg>
  );
}

/** The checkbox tick. Not in the kit — it only draws the unchecked box. */
export function CheckIcon({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      <path d="M5 12.5L9.75 17.25L19 7" />
    </svg>
  );
}
