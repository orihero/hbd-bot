/**
 * The chrome the two unauthenticated-ish screens share: a centred card, and one way of
 * rendering an `ApiFailure` from a form submission.
 *
 * A form failure is not a query failure, which is why `ErrorState` is not reused here: there
 * is nothing to retry automatically, the operator is holding the remedy (a different
 * password, or a wait), and the affordance that matters is the correlation id — the one
 * string that ties what they just saw to the WARNING the server logged.
 *
 * ## Why this file carries the most design weight in the console
 *
 * It is the first screen anyone sees and, until they sign in, the only one. The shell is not
 * mounted: there is no rail, no top bar, no brand mark anywhere else on the page. So the
 * mark is here, above the card, in the same lower-case `hbd` the top bar uses — the same
 * word in the same face, so signing in and arriving do not look like two products.
 *
 * The card is the language's own: `--surface-card` at 28px on the `--surface` ground,
 * separated by `--shadow-card` and nothing else. No border, no rule under the header, no
 * rule above the footer — where the old panel drew a line, this one leaves space.
 *
 * ## The failure notice keeps its second channel
 *
 * The old notice hung a 2px coloured rule down its left edge. This design has no rules, so
 * the hue moved into a tinted GROUND with a glyph on it and the words in `--ink`: `⚠` for a
 * rate limit, `✗` for a refusal. That is three channels (glyph, word, tint) where there were
 * two, and it keeps the server's own message at 6.6:1 instead of painting it at the hue's
 * 4.5:1 floor.
 */

import type { ReactElement, ReactNode } from "react";

import type { ApiFailure } from "@/api";
import { CopyButton } from "@/components/util";
import { cn } from "@/lib";

import { ORIGIN_REJECTED_HINT, RATE_LIMITED_TITLE } from "./authCopy";

export interface AuthPanelProps {
  readonly title: string;
  readonly subtitle?: ReactNode;
  readonly children: ReactNode;
  readonly footer?: ReactNode;
}

export function AuthPanel({ title, subtitle, children, footer }: AuthPanelProps): ReactElement {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[26rem] flex-col justify-center gap-5 px-6 py-12">
      {/*
       * The mark, OUTSIDE the card and above it. The shell is not mounted on this route, so
       * without it the operator is asked for a credential by an anonymous white rectangle.
       */}
      <div className="flex items-baseline gap-2 px-1">
        <span className="type-h2 text-ink">hbd</span>
        <span className="type-caption text-ink-muted">admin console</span>
      </div>

      <section className="flex flex-col gap-5 rounded-card bg-surface-card px-7 py-8 shadow-lg">
        <header className="flex flex-col gap-1.5">
          <h1 className="type-h1 text-ink">{title}</h1>
          {subtitle === undefined ? null : (
            <p className="type-body-sm text-ink-muted">{subtitle}</p>
          )}
        </header>
        {children}
        {/* Space, not a rule — the whole design separates this way. */}
        {footer === undefined ? null : <div className="pt-1">{footer}</div>}
      </section>
    </main>
  );
}

export interface AuthFailureNoticeProps {
  readonly failure: ApiFailure;
  /** Seconds left on a `Retry-After`, when the failure carried one. */
  readonly secondsLeft?: number | null;
  /** Screen-specific explanation — the no-enumeration note, the re-auth remedy. */
  readonly note?: ReactNode;
}

const LIMIT_CODES = new Set(["LOGIN_RATE_LIMITED", "REAUTH_RATE_LIMITED"]);

export function AuthFailureNotice({
  failure,
  secondsLeft,
  note,
}: AuthFailureNoticeProps): ReactElement {
  const isLimited = LIMIT_CODES.has(failure.code);

  return (
    <div
      role="alert"
      data-testid="auth-failure"
      data-code={failure.code}
      /*
       * The tint is the ground and the word is `--ink` — the palette's own recommendation
       * for a tinted block, and the reason the server's message reads at 6.6:1 here rather
       * than at whatever the hue happens to be.
       */
      className={cn(
        "flex flex-col gap-1.5 rounded-2xl px-4 py-3",
        isLimited ? "bg-caution-tint" : "bg-error-tint",
      )}
    >
      <p className="type-body-sm flex items-baseline gap-2 font-semibold text-ink">
        {/* Glyph and word, so the two cases are told apart without colour. */}
        <span aria-hidden="true" className={isLimited ? "text-caution" : "text-error"}>
          {isLimited ? "⚠" : "✗"}
        </span>
        {isLimited ? RATE_LIMITED_TITLE : "Not signed in"}
      </p>
      {/* The server's own words. Never rewritten, never made more specific. */}
      <p className="type-body text-ink">{failure.message}</p>

      {isLimited && secondsLeft !== undefined && secondsLeft !== null ? (
        <p className="type-body-sm num text-ink-muted" data-testid="auth-retry-countdown">
          {secondsLeft > 0
            ? `Try again in ${String(secondsLeft)}s.`
            : "You can try again now."}
        </p>
      ) : null}

      {note === undefined ? null : <p className="type-body-sm text-ink-muted">{note}</p>}

      {failure.code === "ORIGIN_REJECTED" ? (
        <p className="type-body-sm text-ink-muted">{ORIGIN_REJECTED_HINT}</p>
      ) : null}

      {failure.issues === null || failure.issues.length === 0 ? null : (
        <ul className="type-mono text-ink-muted">
          {failure.issues.map((issue) => (
            <li key={`${issue.path}:${issue.message}`}>{`${issue.path}: ${issue.message}`}</li>
          ))}
        </ul>
      )}

      <p className="type-caption flex flex-wrap items-center gap-2 text-ink-muted">
        <code className="type-mono">{failure.code}</code>
        {failure.correlationId === null ? null : (
          <>
            <code className="type-mono">{failure.correlationId}</code>
            <CopyButton value={failure.correlationId} label="correlation id" />
          </>
        )}
      </p>
    </div>
  );
}
