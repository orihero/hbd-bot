import type { ReactNode } from "react";

/**
 * The kit's "Text Input [1.0]" block: a 14/500/20 label with a red asterisk, 4px above the
 * 47px control. The two fields on the login screen differ only in what sits inside the
 * control, so the label half lives here and the input half is passed in.
 */

/**
 * The control's own class list, shared so both fields sit on the same box.
 * Geometry is the design's (h47, r10, 1px #E8E8E8, pt/pr/pb/pl 10/10/10/12, shadow
 * 0 1 2 rgba(10,13,20,.03)); the focus ring is ours — the kit draws no focus state.
 */
export const FIELD_CONTROL_CLASS =
  "h-[47px] w-full rounded-field border border-stroke bg-card py-[10px] pl-[12px] pr-[10px] " +
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-label " +
  "shadow-field outline-none transition-shadow " +
  "placeholder:text-muted " +
  "focus:border-accent-deep focus:ring-2 focus:ring-accent " +
  "disabled:cursor-not-allowed disabled:opacity-60";

interface LabelledFieldProps {
  /** Must match the `id` of the control rendered as `children`. */
  readonly htmlFor: string;
  readonly label: string;
  readonly children: ReactNode;
}

export function LabelledField({ htmlFor, label, children }: LabelledFieldProps) {
  return (
    <div className="flex flex-col gap-1">
      <label
        htmlFor={htmlFor}
        className="flex items-center gap-px text-[14px] font-medium leading-5 tracking-[-0.084px] text-label"
      >
        {label}
        {/* The control's own `required` already announces this; the glyph is decoration. */}
        <span aria-hidden className="text-required">
          *
        </span>
      </label>
      {children}
    </div>
  );
}
