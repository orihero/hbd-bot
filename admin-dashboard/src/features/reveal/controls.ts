/**
 * The kit's controls, as class lists, so the two dialogs cannot drift apart from each other
 * or from the toolbar these buttons are measured off.
 *
 * Every number here is measured from `.openpencil-export/projects-toolbar.jsx`: both buttons
 * are 48 tall at 12/16 padding, radius 6, with an 18/500/-0.36 label; the secondary carries a
 * 1px #E8E8E8 stroke on white and the primary a #75FC96 ground. Colours are tokens, never
 * literals; the geometry is arbitrary values because it is geometry, not a decision.
 *
 * The kit draws no focus, hover, disabled or invalid state at all. Those are ours, and they
 * are the app's existing idiom (`features/auth/LabelledField.tsx`): a brightness step for
 * hover, an `--accent` ring on focus.
 */

const BUTTON_BASE =
  "inline-flex h-12 items-center justify-center gap-2 rounded-button px-4 py-3 " +
  "text-[18px] font-medium leading-[24.588px] tracking-[-0.36px] " +
  "transition-[filter,background-color,color] hover:brightness-95 active:brightness-90 " +
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent-deep " +
  "disabled:cursor-not-allowed disabled:brightness-100";

/** The consequential action. One per dialog — a screen with two primaries has neither. */
export const PRIMARY_BUTTON_CLASS = `${BUTTON_BASE} bg-accent text-on-accent disabled:bg-stroke disabled:text-ink-300`;

/** Everything else that is still an action: cancel, close, next page. */
export const SECONDARY_BUTTON_CLASS = `${BUTTON_BASE} border border-stroke bg-card text-ink-800 disabled:text-ink-300`;

/**
 * A text input or a select. 47 tall, radius 10, 1px stroke, the login form's exact box —
 * an operator should not be able to tell the reveal dialog was built later.
 */
export const FIELD_CONTROL_CLASS =
  "h-[47px] w-full rounded-field border border-stroke bg-card py-[10px] pl-[12px] pr-[10px] " +
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-label " +
  "shadow-field outline-none transition-shadow " +
  "placeholder:text-muted " +
  "focus:border-accent-deep focus:ring-2 focus:ring-accent " +
  "disabled:cursor-not-allowed disabled:opacity-60";

/** The same box, grown for prose. `reasonText` is two lines of context, not a paragraph. */
export const TEXTAREA_CONTROL_CLASS = FIELD_CONTROL_CLASS.replace(
  "h-[47px]",
  "min-h-[72px] resize-y",
);

/** The kit's column-header type: 16/400, -0.64 tracking, #8D8D8D. Used for every group label. */
export const SECTION_LABEL_CLASS =
  "text-[16px] font-normal leading-[21.856px] tracking-[-0.64px] text-ink-300";

/** The table's primary cell: 12/600, -0.36, black. The strongest small type in the kit. */
export const CELL_PRIMARY_CLASS =
  "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800";

/** The table's secondary cell: same metrics, 12/400, the measured #00000066. */
export const CELL_SECONDARY_CLASS =
  "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-cell-2";

/** Body copy inside a panel — the toolbar's 16/400 subtitle line. */
export const PANEL_BODY_CLASS =
  "text-[16px] font-normal leading-[21.856px] tracking-[-0.32px] text-ink-400";

/** The panel's own title: the toolbar's 22/600. */
export const PANEL_TITLE_CLASS =
  "text-[22px] font-semibold leading-[30.052px] tracking-[-0.44px] text-ink-900";

/**
 * A column name, a subject id, a scope — printed for recognition, not for reading.
 *
 * Monospace because these are strings an operator compares character by character against an
 * audit row or a log line, and a proportional font hides the difference between `l` and `1`
 * in exactly the identifier where it matters.
 */
export const MONO_CLASS = "font-mono text-[12px] leading-[16px] tracking-[-0.2px] break-all";
