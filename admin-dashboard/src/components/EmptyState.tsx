import type { JSX, ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A list that has nothing in it, said quietly and specifically.
 *
 * "No results" is the failure this component exists to prevent. On these screens an empty page
 * has at least four different causes and they are not interchangeable: nobody matches the
 * filters; the filters are narrower than the operator remembers; the id searched for is not a
 * Telegram id and so could never have matched (`q` is a substring of the Telegram id and
 * NOTHING else — never a name); or the window is simply before this customer's first contact.
 * The `title` and `message` are where the screen says which, in words the operator can act on.
 *
 * `action` is optional and is usually "Clear filters" — the one move that changes the answer.
 */

interface EmptyStateProps {
  readonly title: string;
  /** The specifics: what was searched, over what window, under which filters. */
  readonly message?: ReactNode;
  /** Decorative. The title carries the meaning. */
  readonly icon?: ReactNode;
  readonly action?: ReactNode;
  readonly className?: string | undefined;
}

export function EmptyState({
  title,
  message,
  icon,
  action,
  className,
}: EmptyStateProps): JSX.Element {
  return (
    <div
      className={cn(
        "mx-auto flex max-w-[420px] flex-col items-center gap-2 px-4 py-8 text-center",
        className,
      )}
    >
      {icon === undefined ? null : (
        <span aria-hidden className="flex h-6 w-6 items-center justify-center text-ink-300">
          {icon}
        </span>
      )}
      <p className="m-0 text-[16px] font-semibold leading-[21.856px] tracking-[-0.32px] text-ink-900">
        {title}
      </p>
      {message === undefined ? null : (
        <p className="m-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500">
          {message}
        </p>
      )}
      {action === undefined ? null : <div className="mt-2">{action}</div>}
    </div>
  );
}
