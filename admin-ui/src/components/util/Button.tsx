/**
 * The console's `<button>`.
 *
 * The variants, the contrast measurements and the reasoning all live next door in
 * `buttonVariants.ts`, deliberately: a `<Link>`, a Radix trigger and a `<label>` all need the
 * same classes and none of them can be this component, so the definition has to be a
 * stylesheet-shaped thing that a `cn()` can consume. This file is the ergonomic wrapper for
 * the common case, nothing more — it adds no colour of its own.
 *
 * Two rules for callers:
 *
 *  1. **Never pass a colour in `className`.** `cn()` merges by Tailwind group, so a
 *     `bg-…`/`text-…` in `className` silently wins over the variant and the console grows a
 *     fifth button style. Pass `variant`; if none of the four fits, that is a design
 *     question, not a call-site one.
 *  2. **A segment passes `variant={segmentVariant(isSelected)}`** and carries `aria-pressed`
 *     or `aria-selected` itself. The helper is the only place the selected/unselected pairing
 *     is decided.
 */

import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

import { buttonVariants, type ButtonVariantProps } from "./buttonVariants";

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    ButtonVariantProps {
  /**
   * Layout, spacing and type only. A colour utility here defeats the variant — see the note
   * above.
   */
  readonly className?: string | undefined;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, shape, className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      // Defaulted rather than required: an unlabelled `<button>` inside a `<form>` submits it,
      // and every button in this console that is not a submit had to remember to say so.
      type={type}
      className={cn(buttonVariants({ variant, size, shape }), className)}
      {...rest}
    />
  );
});
