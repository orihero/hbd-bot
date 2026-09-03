/**
 * §11.4's error state: **inline, scoped, keeps surrounding data**, and shows the code plus a
 * **copyable correlation id**.
 *
 * Scoped matters. A failed `/ops/latency` must not blank the delivery rate next to it; the
 * boundary that owns one panel renders this inside that panel and the rest of the screen
 * stays. A full-page error for a partial failure is how an operator concludes the system is
 * down when one query is.
 *
 * The correlation id is the join key between this console, the server log and the audit row
 * (§12.1's `X-Correlation-ID` on every response), so it is rendered verbatim in mono with a
 * copy button beside it and never truncated.
 *
 * `SCHEMA_DRIFT` gets its own, louder treatment. §11.1: "a distinct, loudly-rendered
 * SCHEMA_DRIFT banner naming the endpoint and the failing field path". It is the frontend
 * twin of the repo's decision to treat a `pydantic.ValidationError` on a stored row as a
 * deliberately loud data-integrity bug — the response parsed as valid JSON and was still
 * wrong, which means a deploy is half-rolled or a model changed, and the one thing that
 * must not happen is a quiet retry.
 */

import type { ApiFailure } from "@/api";
import { failureOf, refusedPermission } from "@/api";
import { cn } from "@/lib/utils";

import { Button } from "./Button";
import { CopyButton } from "./CopyButton";

export interface ErrorStateProps {
  /** The failure to render. Pass this OR `error`; `failure` wins when both are given. */
  readonly failure?: ApiFailure | null | undefined;
  /** A thrown value — a TanStack Query `error`. Unwrapped with `failureOf`. */
  readonly error?: unknown;
  /** Re-run the query. Omitted when nothing can be retried (a 403 stays a 403). */
  readonly onRetry?: (() => void) | undefined;
  /** What failed to load, in our words: "the delivery rate", "this order". */
  readonly what?: string;
  /**
   * Replace the derived headline.
   *
   * For the case where the code's ordinary wording would mislead. `STEP_UP_REQUIRED` reads
   * "This needs a step-up confirmation", which is true of a subject-scoped refusal and false
   * of a router guard that answers it to every caller and reads no grant — telling an
   * operator to confirm something that cannot be confirmed is worse than saying nothing.
   * Use it only where the caller knows something about the refusal that the code does not.
   */
  readonly title?: string | undefined;
  readonly className?: string;
}

/** A one-line summary that reads as prose rather than as a status code. */
function headline(failure: ApiFailure | null, what: string): string {
  if (failure === null) return `Could not load ${what}`;
  switch (failure.code) {
    case "SCHEMA_DRIFT":
      return `The server's answer for ${what} did not match this build`;
    case "UNAUTHENTICATED":
      return "Your session has ended";
    case "FORBIDDEN":
      return `Your role cannot read ${what}`;
    case "STEP_UP_REQUIRED":
      return "This needs a step-up confirmation";
    case "NETWORK_ERROR":
      return `Could not reach the server for ${what}`;
    case "REQUEST_ABORTED":
      return "That request was cancelled";
    case "CAPABILITY_DISABLED":
      return `${what} is not enabled in this deployment`;
    default:
      return `Could not load ${what}`;
  }
}

export function ErrorState({
  failure,
  error,
  onRetry,
  what = "this",
  title,
  className,
}: ErrorStateProps) {
  const resolved: ApiFailure | null = failure ?? failureOf(error);
  const isDrift = resolved?.code === "SCHEMA_DRIFT";
  const permission = refusedPermission(resolved?.details ?? null);

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col gap-3 rounded-card px-6 py-5",
        // Drift keeps its own louder treatment: the error tint as a ground plus the 1px
        // `--ring-error` outline that replaced the old glow. Everything else is an ordinary
        // card — this design separates with colour and a shadow, never with a border.
        isDrift ? "bg-error-tint shadow-ring-error" : "bg-surface-card shadow-card",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className={isDrift ? "text-error" : "text-caution"}>
          {isDrift ? "■" : "!"}
        </span>
        <span className="type-body font-semibold text-ink">
          {title ?? headline(resolved, what)}
        </span>
        {resolved === null ? null : (
          <code
            className={cn(
              "type-mono rounded-2xs px-2 py-0.5 text-ink",
              isDrift ? "bg-surface-card" : "bg-surface-control",
            )}
          >
            {resolved.code}
          </code>
        )}
        {resolved !== null && resolved.status !== 0 ? (
          <span className="type-caption num text-ink-muted">HTTP {resolved.status}</span>
        ) : null}
      </div>

      {resolved === null ? null : <p className="type-body-sm text-ink-muted">{resolved.message}</p>}

      {permission === null ? null : (
        <p className="type-body-sm text-ink-muted">
          It needs <code className="type-mono text-ink">{permission}</code>.
        </p>
      )}

      {resolved?.retryAfterS === null || resolved?.retryAfterS === undefined ? null : (
        <p className="type-body-sm text-ink-muted">
          Try again in <span className="num">{resolved.retryAfterS}</span>s.
        </p>
      )}

      {/*
       * The drift detail. Field paths, not a stack: "which field of which endpoint" is the
       * whole diagnosis, and it is what makes a bug report actionable in one paste.
       */}
      {isDrift ? (
        <div className="mt-1 flex flex-col gap-1 rounded-2xl bg-surface-card px-4 py-3">
          <p className="type-caption text-ink-muted">schema drift</p>
          <p className="type-mono text-ink">{resolved.endpoint}</p>
          <ul className="flex flex-col gap-0.5">
            {(resolved.issues ?? []).map((issue) => (
              <li key={`${issue.path}:${issue.message}`} className="type-mono text-ink-muted">
                <span className="text-error">{issue.path === "" ? "(root)" : issue.path}</span>
                {" — "}
                {issue.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-1 flex flex-wrap items-center gap-3">
        {resolved?.correlationId === null || resolved?.correlationId === undefined ? null : (
          <span className="flex items-center gap-1">
            <span className="type-caption text-ink-muted">correlation</span>
            <code className="type-mono text-ink">{resolved.correlationId}</code>
            <CopyButton value={resolved.correlationId} label="correlation id" />
          </span>
        )}
        {onRetry === undefined ? null : (
          /* The design's SECONDARY button: a tint of the hue with the hue as the label,
             never grey-on-grey. `--brand` on `--brand-tint` is 4.82:1 light, 4.60:1 dark. */
          <Button variant="secondary" shape="pill" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}
