import type { JSX, ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * The kit's pill — radius 4, 6/8 padding, a 12/-0.36 label — in five tones.
 *
 * The kit ships exactly one: the accent ground at #75FC96B2, which is `accent`. The other four
 * are additions this console needs, because a list of orders and attempts has to say `failed`
 * and `purged` as well as `delivered`, and one ground for all of them says nothing.
 *
 * Every tone pairs a GROUND with its own INK rather than reusing the pure alarm colour as
 * text: --required on --required-24 is 3.3:1, which is under AA for a 12px label. Grounds carry
 * the tone, ink carries the contrast. Measured, all five clear 4.5:1 on --card and on --bg.
 *
 * A badge is a label, never a status announcement: the word inside it has to be readable on its
 * own, because colour is not information anyone is required to be able to see.
 */

export type BadgeTone = "neutral" | "accent" | "warning" | "danger" | "muted";

const TONE: Record<BadgeTone, string> = {
  neutral: "bg-bg text-ink-900",
  accent: "bg-accent-70 text-ink-800",
  warning: "bg-warn-18 text-warn-deep",
  danger: "bg-required-24 text-required-deep",
  muted: "bg-bg text-ink-400",
};

interface BadgeProps {
  readonly children: ReactNode;
  readonly tone?: BadgeTone;
  /** Decorative; the label carries the meaning. Sized to the kit's 12px mark. */
  readonly icon?: ReactNode;
  /** A native tooltip for the long form of a shortened label. Not a substitute for the label. */
  readonly title?: string | undefined;
  readonly className?: string | undefined;
}

export function Badge({
  children,
  tone = "neutral",
  icon,
  title,
  className,
}: BadgeProps): JSX.Element {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded px-2 py-[6px]",
        "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px]",
        TONE[tone],
        className,
      )}
    >
      {icon === undefined ? null : (
        <span aria-hidden className="flex h-3 w-3 shrink-0 items-center justify-center">
          {icon}
        </span>
      )}
      <span className="truncate">{children}</span>
    </span>
  );
}
