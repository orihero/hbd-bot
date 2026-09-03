/**
 * `<StepUpPrompt>` — the app's ONE re-authentication form, and the thing four later phases
 * should reuse rather than reinvent.
 *
 * A `403 STEP_UP_REQUIRED` is not an error state. §11.4's error state exists for things the
 * operator cannot fix; this is a thing they can fix in ten seconds, and rendering it as a red
 * banner with a correlation id is how an operator learns that half the console is broken. So
 * the refusal routes HERE, the operator types the password they already know, and the ORIGINAL
 * request is sent again unchanged.
 *
 * ## Reusing it
 *
 * ```tsx
 * const target = stepUpTargetOf(failureOf(mutation.error));
 * …
 * {target === null ? null : (
 *   <StepUpPrompt
 *     action={target.action}
 *     subjectId={target.subjectId}
 *     subjectLabel="order 3f2a…"          // OUR text. Never a recipient name.
 *     onGranted={() => { mutation.mutate(sameBodyAsBefore); }}
 *     onCancel={close}
 *   />
 * )}
 * ```
 *
 * Two rules that are easy to get wrong and expensive to debug:
 *
 * 1. **Pass the `subjectId` through from the failure, untouched.** `check_step_up` compares
 *    the composed `"<action>:<subjectId>"` scope byte-for-byte, so an id you re-formatted —
 *    braced, upper-cased, trimmed — is a permanent silent 403 that looks exactly like a wrong
 *    password.
 * 2. **Retry the same body.** A grant authorises an action on a subject, not a request; the
 *    server has no memory of what you were trying to do.
 *
 * The password field is `type="password"` with `autoComplete="current-password"` and its value
 * is dropped the moment a grant lands. `POST /auth/step-up` is metered exactly like a login
 * (with a refund on success), so a wrong password here is a 403 and a burst of them is a 429
 * `REAUTH_RATE_LIMITED` whose remedy — sign in again for a fresh window — is on the message.
 */

import { ShieldCheck } from "lucide-react";
import { useState, type FormEvent, type ReactElement, type ReactNode } from "react";

import { failureOf, type StepUpAction, type StepUpResponse } from "@/api";
import { Button } from "@/components/util/Button";
import { cn } from "@/lib";

import { grantWindowS, graceNote, STEP_UP_EXPLANATION } from "./stepUp";
import { useStepUp } from "./useReveal";

export const STEP_UP_TITLE = "Re-authenticate for this action";

export interface StepUpPromptProps {
  readonly action: StepUpAction;
  /** Byte-identical to the id the refusing handler compared against. */
  readonly subjectId: string;
  /** OUR words for the subject — an order reference, an asset kind. Never customer content. */
  readonly subjectLabel?: string | undefined;
  /** `adminStepUpGraceSeconds` from `/api/config`, so the grace note is this deployment's. */
  readonly graceS?: number | null | undefined;
  /** Extra context above the field — usually what the operator was trying to do. */
  readonly note?: ReactNode;
  readonly onGranted: (grant: StepUpResponse) => void;
  readonly onCancel?: (() => void) | undefined;
  readonly className?: string | undefined;
}

export function StepUpPrompt({
  action,
  subjectId,
  subjectLabel,
  graceS,
  note,
  onGranted,
  onCancel,
  className,
}: StepUpPromptProps): ReactElement {
  const [password, setPassword] = useState("");
  const stepUp = useStepUp();
  const failure = failureOf(stepUp.error);
  const windowS = grantWindowS(action, graceS ?? 0);

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (password.length === 0 || stepUp.isPending) return;
    stepUp.mutate(
      { password, scope: action, subjectId },
      {
        onSuccess: (grant) => {
          // The credential leaves this component the instant it has done its work. Nothing
          // upstream ever sees it: `onGranted` is handed the grant, never the password.
          setPassword("");
          onGranted(grant);
        },
      },
    );
  };

  return (
    <form
      onSubmit={onSubmit}
      data-testid="step-up-prompt"
      data-step-up-action={action}
      data-step-up-subject={subjectId}
      // A step-up is a raised surface, not a boxed one: paper, a 24px radius and a shadow.
      className={cn("flex flex-col gap-3 rounded-2xl bg-surface-card p-5 shadow-md", className)}
      noValidate
    >
      <div className="flex items-start gap-2">
        <ShieldCheck aria-hidden="true" className="mt-0.5 h-4 w-4 text-accent" />
        <div className="flex flex-col gap-1">
          <h3 className="type-h2 text-ink">{STEP_UP_TITLE}</h3>
          <p className="type-body-sm text-ink-muted">{STEP_UP_EXPLANATION}</p>
        </div>
      </div>

      {note === undefined ? null : <div className="type-body-sm text-ink-muted">{note}</div>}

      <p className="type-caption text-ink-muted">
        {"action "}
        <span className="type-mono text-ink">{action}</span>
        {" · subject "}
        <span className="type-mono text-ink">{subjectLabel ?? subjectId}</span>
      </p>

      <label className="flex flex-col gap-1">
        <span className="type-caption text-ink-muted">Your password</span>
        <input
          // The dialog put the operator here; a second keystroke to reach the field is a
          // second chance to lose the thread of a support call.
          autoFocus
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
          className={cn(
            // An input carries a ground instead of a border in this language; the focus
            // ring from index.css is what marks it while it is being typed into.
            "type-body rounded-control bg-surface-control px-3 py-2 text-ink",
            "outline-none",
          )}
        />
      </label>

      <p className="type-caption text-ink-muted">{graceNote(windowS)}</p>

      {failure === null ? null : (
        <p role="alert" data-testid="step-up-error" className="type-body-sm text-error">
          <span className="type-mono">{failure.code}</span>
          {` — ${failure.message}`}
          {failure.code === "REAUTH_RATE_LIMITED"
            ? " Signing in again starts a fresh window."
            : ""}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          disabled={password.length === 0 || stepUp.isPending}
        >
          {stepUp.isPending ? "Re-authenticating…" : "Re-authenticate"}
        </Button>
        {onCancel === undefined ? null : (
          <Button variant="quiet" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
