import type { JSX, ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * The kit's Projects toolbar: an 82px white bar at radius 15 with a 1px --stroke edge, a
 * title/subtitle block on the left, filter controls in the middle behind a vertical rule, and
 * the actions on the right behind another. Every measurement is from
 * `.openpencil-export/projects-toolbar.jsx`.
 *
 * The one departure is that the bar WRAPS. The kit draws a 1392px canvas and positions each
 * child absolutely; a real console gets resized, and a toolbar that overflows takes its
 * primary action off the screen. So the height is a minimum rather than a fixed 82, and the
 * two rules disappear at the width where the row stacks — a divider between things that are
 * no longer side by side divides nothing.
 */

interface ToolbarProps {
  readonly title: string;
  /** One line under the title. The place to say what the list is scoped to. */
  readonly subtitle?: ReactNode;
  /** Search fields, segmented controls — whatever narrows the list below. */
  readonly filters?: ReactNode;
  /** Right-hand slot. `<ToolbarButton>` belongs here. */
  readonly actions?: ReactNode;
  /**
   * An index screen's toolbar title is the page's heading; a panel's is not. Defaults to the
   * page heading, because that is the common case and a page with no h1 is the worse failure.
   */
  readonly titleAs?: "h1" | "h2";
  readonly className?: string | undefined;
}

/** 1px × 48, --stroke. The kit's `Line 181`/`Line 182`. */
function ToolbarDivider(): JSX.Element {
  return <span aria-hidden className="hidden h-12 w-px shrink-0 bg-stroke lg:block" />;
}

export function Toolbar({
  title,
  subtitle,
  filters,
  actions,
  titleAs = "h1",
  className,
}: ToolbarProps): JSX.Element {
  const Heading = titleAs;

  return (
    <div
      className={cn(
        "flex min-h-[82px] flex-wrap items-center gap-x-5 gap-y-3 rounded-card border border-stroke bg-card px-4 py-4",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-[6px]">
        <Heading className="m-0 text-[22px] font-semibold leading-[30.052px] tracking-[-0.44px] text-ink-800">
          {title}
        </Heading>
        {subtitle === undefined ? null : (
          <p className="m-0 text-[16px] font-normal leading-[21.856px] tracking-[-0.32px] text-ink-500">
            {subtitle}
          </p>
        )}
      </div>

      {filters === undefined ? null : (
        <>
          <ToolbarDivider />
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">{filters}</div>
        </>
      )}

      {actions === undefined ? null : (
        <>
          {filters === undefined ? null : <ToolbarDivider />}
          <div className={cn("flex flex-wrap items-center gap-3", filters === undefined && "ml-auto")}>
            {actions}
          </div>
        </>
      )}
    </div>
  );
}

interface ToolbarButtonProps {
  readonly children: ReactNode;
  readonly onClick?: (() => void) | undefined;
  /** `secondary` is the kit's outlined Filters button; `primary` its accent Create task. */
  readonly variant?: "primary" | "secondary";
  /** Sized to the kit's 24px slot whatever the icon's own dimensions are. */
  readonly icon?: ReactNode;
  readonly type?: "button" | "submit";
  readonly disabled?: boolean | undefined;
  /** For an icon-only button, or one whose visible label is shorter than what it does. */
  readonly ariaLabel?: string | undefined;
  readonly ariaExpanded?: boolean | undefined;
  readonly ariaControls?: string | undefined;
  readonly className?: string | undefined;
}

const BUTTON_VARIANT: Record<"primary" | "secondary", string> = {
  primary: "bg-accent text-on-accent hover:brightness-95 active:brightness-90",
  secondary: "border border-stroke bg-card text-ink-800 hover:bg-bg active:brightness-95",
};

export function ToolbarButton({
  children,
  onClick,
  variant = "secondary",
  icon,
  type = "button",
  disabled = false,
  ariaLabel,
  ariaExpanded,
  ariaControls,
  className,
}: ToolbarButtonProps): JSX.Element {
  return (
    <button
      type={type === "submit" ? "submit" : "button"}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-expanded={ariaExpanded}
      aria-controls={ariaControls}
      className={cn(
        "flex h-12 shrink-0 cursor-pointer items-center gap-2 rounded-button px-4 py-3 font-sans",
        "text-[18px] font-medium leading-[24.588px] tracking-[-0.36px]",
        "transition-[color,background-color,filter]",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:brightness-100",
        BUTTON_VARIANT[variant],
        className,
      )}
    >
      {icon === undefined ? null : (
        <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center">
          {icon}
        </span>
      )}
      {children}
    </button>
  );
}
