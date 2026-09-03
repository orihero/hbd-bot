/**
 * The client-side 404.
 *
 * Reached only for a path the SPA itself does not route. The API's own 404s are a different
 * thing entirely and arrive as `{ok: false, code: "NOT_FOUND"}` from the client — the server
 * never serves this page for an `/api/**` path (see `_mount_spa` in
 * `src/hbd/admin/app.py`), because a JSON caller that got HTML back would be told the wrong
 * story about what went wrong.
 *
 * The reskin gives it the language's own shape for an absence, the same one `EmptyState`
 * wears: a centred card on the page ground, generous padding, a glyph, one bold line, one
 * muted line, and a single pill button home. It is deliberately NOT `<EmptyState>` itself —
 * this is a whole screen with the page's only `h1` on it, and `EmptyState` renders a
 * `role="status"` region with a `<p>` for its title, which would leave a route with no
 * heading at all.
 */

import { Link, useLocation } from "react-router-dom";

import { buttonVariants } from "@/components/util";
import { cn } from "@/lib";

export function NotFoundScreen() {
  const location = useLocation();
  return (
    // A `<section>`, not a `<main>`: this route renders INSIDE `AppShell`'s `<main id="main">`
    // and a nested main landmark is two documents to a screen reader.
    <section className="flex min-h-[70vh] items-center justify-center px-gutter py-gutter">
      <div className="flex w-full max-w-lg flex-col items-center gap-3 rounded-card bg-surface-card px-8 py-14 text-center shadow-card">
        {/*
         * Decorative, `aria-hidden`, and painted with `--ink-muted` rather than the policed
         * `--ink-mark`: it is the largest thing on an otherwise empty card, so it clears the
         * 4.5:1 text bar even though 1.4.11's 3:1 would formally do. No waiver needed, which
         * is the other half of the point.
         */}
        <span aria-hidden="true" className="text-[40px] leading-none text-ink-muted">
          ⊘
        </span>
        <p className="type-caption text-ink-muted">404</p>
        <h1 className="type-h1 text-ink">No screen at that address</h1>
        <p className="type-body max-w-prose text-ink-muted">
          The console has no route for{" "}
          <span className="type-mono text-ink">{location.pathname}</span>.
        </p>
        {/* A `<Link>` cannot be the `<Button>` component, so it takes the CLASSES from the
            shared definition instead. Same variant, same box, one source. */}
        <Link
          className={cn(buttonVariants({ variant: "primary", shape: "pill" }), "mt-3")}
          to="/"
        >
          Back to Live Ops
        </Link>
      </div>
    </section>
  );
}

export const Component = NotFoundScreen;
