/**
 * The last line of defence: a render-time throw that would otherwise unmount the whole app.
 *
 * This is NOT where API failures go. `ApiResult` never throws (§11.1) and `unwrapAsync` at a
 * query boundary turns a failure into a rejection that `AsyncBoundary` renders **inline and
 * scoped**. If a failure reaches here, something rendered a bad assumption — an array index
 * under `noUncheckedIndexedAccess` that was defended with `!`, a `Symbol` in JSX — and the
 * honest answer is a caught crash with a Reload, not a blank page.
 *
 * Placement matters more than the component. One boundary around the whole shell turns a bug
 * on the audit screen into "the console is down"; the shell puts one around `<main>` so the
 * NavRail, TopBar and the player survive, and a screen may nest its own around a panel.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./Button";

export interface ErrorBoundaryProps {
  readonly children: ReactNode;
  /** Custom rendering. Gets the error and a `reset` that clears the boundary and re-renders. */
  readonly fallback?: ((error: Error, reset: () => void) => ReactNode) | undefined;
  /** Called on catch. The shell uses it to log; do not use it to retry. */
  readonly onError?: ((error: Error, info: ErrorInfo) => void) | undefined;
  /**
   * Changing any of these resets the boundary. Pass the route key so navigating away from a
   * screen that crashed does not leave the error stuck on the next one.
   */
  readonly resetKeys?: readonly unknown[] | undefined;
  readonly className?: string | undefined;
}

interface ErrorBoundaryState {
  readonly error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public override state: ErrorBoundaryState = { error: null };

  public static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  public override componentDidCatch(error: Error, info: ErrorInfo): void {
    this.props.onError?.(error, info);
  }

  public override componentDidUpdate(previous: ErrorBoundaryProps): void {
    if (this.state.error === null) return;
    const before = previous.resetKeys;
    const after = this.props.resetKeys;
    if (before === undefined || after === undefined) return;
    const changed =
      before.length !== after.length || before.some((value, index) => value !== after[index]);
    if (changed) this.reset();
  }

  private readonly reset = (): void => {
    this.setState({ error: null });
  };

  public override render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback(error, this.reset);

    return (
      <div
        role="alert"
        className={cn(
          "m-gutter flex flex-col items-start gap-3 rounded-card px-6 py-5",
          // The same louder treatment `ErrorState` gives SCHEMA_DRIFT, for the same reason:
          // this is a bug, not a refusal, and it must not read as one more empty panel.
          "bg-error-tint shadow-ring-error",
          this.props.className,
        )}
      >
        <p className="type-h2 text-ink">This part of the console stopped rendering</p>
        <p className="type-body-sm text-ink-muted">
          It is a bug in the panel, not a failed request — the rest of the console is still
          live. The message below is what to paste into the report.
        </p>
        <pre className="type-mono w-full overflow-x-auto rounded-2xl bg-surface-card px-4 py-3 text-ink">
          {error.message}
        </pre>
        <Button variant="secondary" shape="pill" onClick={this.reset}>
          Try rendering again
        </Button>
      </div>
    );
  }
}
