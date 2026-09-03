/**
 * The band at the top of every screen: where you are, what this page is, and the one number
 * it exists to show.
 *
 * §11.2 gives each route a **dominant signal** — "24 h delivery success rate at 44px",
 * "assets expiring within 7 days", "oldest waiting age" — and says it must be the first
 * thing the eye reaches. `signal` is that slot, and it sits on the header's baseline rather
 * than inside the page body so it cannot drift below a filter bar as a screen grows.
 *
 * The title is `h1` and there is exactly one per screen, because the rail already names the
 * section and a second heading level competing with it makes the page hierarchy unreadable
 * to a screen reader.
 *
 * ## The breadcrumb trail
 *
 * New with the reskin, and derived from the route — see `breadcrumbs.ts` for why it is
 * derived rather than passed, and for the rule that keeps a customer's string out of it.
 *
 * It is a `<nav aria-label="Breadcrumb">` wrapping an ordered list, which is the shape
 * assistive technology expects, and deliberately NOT a set of headings: the screen still has
 * exactly one `h1` and the browser gate's `getByRole("heading", { name: "Orders", level: 1 })`
 * still resolves to one element. The trail sits BELOW the title in the DOM as well as on the
 * screen, so the first thing a screen reader reaches on a new page is still the page's name.
 *
 * The band no longer draws a bottom rule. It sits on the page ground with the content, and
 * the cards below it separate themselves with `--shadow-card`; a rule here would be the one
 * hard line left in a language that has none.
 */

import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { cn } from "@/lib/utils";

import { breadcrumbTrail } from "./breadcrumbs";

export interface PageHeaderProps {
  /** Our own chrome label for the screen. Never a customer's string. */
  readonly title: string;
  /** One sentence: the question §11.2 says this screen answers. */
  readonly description?: ReactNode;
  /**
   * §11.2's dominant signal — the largest thing on the screen. Rendered to the right on wide
   * viewports and below the title on narrow ones, so it is never clipped.
   */
  readonly signal?: ReactNode;
  /** Buttons. Anything destructive belongs behind a `PermissionGate` and a step-up. */
  readonly actions?: ReactNode;
  /** A filter bar, a tab strip — anything that belongs to the header rather than the body. */
  readonly children?: ReactNode;
  readonly className?: string;
}

function Breadcrumbs() {
  const { pathname } = useLocation();
  const crumbs = breadcrumbTrail(pathname);

  return (
    <nav aria-label="Breadcrumb" className="mt-1">
      <ol className="type-body-sm flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-muted">
        {crumbs.map((crumb, index) => (
          <li key={`${crumb.label}-${String(index)}`} className="flex items-center gap-x-2">
            {index === 0 ? null : (
              // The separator is decoration between two words that already say where they
              // are, so it is hidden from the accessibility tree rather than read aloud
              // between every crumb.
              <span aria-hidden="true" className="text-ink-muted">
                /
              </span>
            )}
            {crumb.href === null ? (
              <span aria-current="page">{crumb.label}</span>
            ) : (
              <Link
                to={crumb.href}
                className="rounded-4xs transition-colors duration-fast ease-standard hover:text-brand"
              >
                {crumb.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({
  title,
  description,
  signal,
  actions,
  children,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn("px-gutter pb-4 pt-gutter", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="min-w-0">
          <h1 className="type-h1 text-ink">{title}</h1>
          <Breadcrumbs />
          {description === undefined ? null : (
            <p className="type-body-sm mt-2 max-w-prose text-ink-muted">{description}</p>
          )}
        </div>
        {signal === undefined ? null : <div className="shrink-0">{signal}</div>}
        {actions === undefined ? null : (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        )}
      </div>
      {children === undefined ? null : <div className="mt-5">{children}</div>}
    </header>
  );
}
