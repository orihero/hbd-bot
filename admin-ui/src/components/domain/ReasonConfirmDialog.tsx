/**
 * `<ReasonConfirmDialog>` — the accountability half of every operator action, once.
 *
 * Server-side, `ReasonedRequest` (`bayram.admin.schemas.actions`) is the base class every write
 * body inherits: a `reasonCode` with **no default**, an optional `reasonRef` matching
 * `^[A-Za-z0-9#_-]{1,64}$`, and an optional `reasonText` whose control characters are stripped
 * before it reaches a 90-day column. That is one shape shared by the grant, the block, the
 * unblock and everything §9.2 adds later — so it is one dialog here rather than a reason block
 * copied into each screen, for the same reason the server refactored two copies into one base:
 * two copies disagree, and `admin_audit_log.reason_text` is a single column.
 *
 * Three rules this component exists to hold:
 *
 * 1. **No `reasonCode`, no confirm.** The server answers 422 without one; a form that lets the
 *    press through and reports the 422 has decided accountability is the server's problem.
 * 2. **The typed reason survives a refusal.** A `403 STEP_UP_REQUIRED` puts a password box in
 *    the `banner` slot and hides the fields — it does not unmount them. The operator
 *    re-authenticates and the SAME body goes again, with the reason they already wrote.
 * 3. **`reasonRef` is validated here, in both of the server's two spellings.** The field's own
 *    pattern allows 64 characters; the audit boundary independently refuses any 40-character
 *    run of `[A-Za-z0-9_-]` as a possible credential. An operator who pasted a long slug is
 *    told before they spend the round trip.
 * 4. **A write in flight, or an outcome not yet read, cannot be dismissed away.** The caller
 *    sets `isDismissLocked` and every route out of the dialog closes: Esc, the scrim, the X
 *    and Cancel. Without it the operator who presses Grant and then Esc is told nothing about
 *    a request that lands anyway — not that it landed, and not whether it was a replay — and
 *    the next press mints a new key and comps the account twice. There is no toast host in
 *    this console to catch that outcome after the fact, so the dialog has to hold still until
 *    the caller says the outcome has been read.
 *
 * The caller owns everything above the reason block (`children`) and everything that replaces
 * it (`banner`, `isFieldsHidden`): how many credits, which account, the result panel. This
 * component owns the reason, its validation, and the confirm.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useState, type ReactElement, type ReactNode } from "react";

import {
  AUDIT_REASON_CODE_VALUES,
  LONG_REASON_REF_CHARS,
  MAX_REASON_REF_CHARS,
  MAX_REASON_TEXT_CHARS,
  REASON_REF_PATTERN,
  type AuditReasonCode,
} from "@/api";
import { Button, type ButtonProps } from "@/components/util/Button";
import { cn } from "@/lib";

import { LONG_REF_WARNING } from "./RevealDialog";
import { REVEAL_REASON_LABELS } from "./revealFields";

/**
 * Withheld until a reason is chosen, and this is why.
 *
 * A sibling of `RevealDialog`'s `REASON_REQUIRED_HINT`, which says "the reveal" because that
 * is the only thing it guards. This one guards a grant, a block and an unblock, so it names
 * the action instead.
 */
/** Why the X and Cancel refuse, said on hover rather than left as a dead control. */
export const DISMISS_LOCKED_HINT =
  "The action is still running, or its answer has not been read yet. Wait for it — closing now would throw the answer away.";

export const ACTION_REASON_REQUIRED_HINT =
  "Choose a reason code. It is required, it goes on the audit row, and the server refuses the action without one.";

/** What the operator wrote, in the shape `ReasonedRequest` accepts. */
export interface ReasonValue {
  readonly reasonCode: AuditReasonCode;
  /** Omitted rather than empty: `""` is not a ticket reference and the pattern refuses it. */
  readonly reasonRef?: string;
  readonly reasonText?: string;
}

export interface ReasonConfirmDialogProps {
  readonly isOpen: boolean;
  readonly onOpenChange: (isOpen: boolean) => void;
  /** Our words for what is about to happen. Never customer content. */
  readonly title: string;
  /** One line under the title — what this action does, and to whom. */
  readonly description?: ReactNode | undefined;
  /** The confirm button's words. Say the consequence: "Grant 3 credits". */
  readonly confirmLabel: ReactNode;
  readonly onConfirm: (reason: ReasonValue) => void;
  /** The action's own fields, above the reason block. */
  readonly children?: ReactNode | undefined;
  /** Above everything: a step-up prompt, a failure notice, a result panel. */
  readonly banner?: ReactNode | undefined;
  /**
   * Hide the fields and the confirm without unmounting them — the caller has taken the
   * dialog over. The state behind them is kept, which is what makes a step-up recoverable.
   */
  readonly isFieldsHidden?: boolean | undefined;
  readonly isPending?: boolean | undefined;
  /**
   * Refuse every dismissal — Esc, the scrim, the X, Cancel — because closing now would throw
   * away an answer the operator has not read. See rule 4. The caller's own controls (a
   * result panel's "Done", a step-up's Cancel) still call `onOpenChange` directly and are
   * how the dialog is meant to be left while this is set.
   */
  readonly isDismissLocked?: boolean | undefined;
  /** The caller's own validity: a credits box out of range, an empty selection. */
  readonly isConfirmDisabled?: boolean | undefined;
  /** `primary` by default; `danger` for a block. */
  readonly confirmVariant?: ButtonProps["variant"] | undefined;
  readonly testId?: string | undefined;
}

export function ReasonConfirmDialog({
  isOpen,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  children,
  banner,
  isFieldsHidden = false,
  isPending = false,
  isDismissLocked = false,
  isConfirmDisabled = false,
  confirmVariant = "primary",
  testId = "reason-confirm-dialog",
}: ReasonConfirmDialogProps): ReactElement {
  const [reasonCode, setReasonCode] = useState<AuditReasonCode | null>(null);
  const [reasonRef, setReasonRef] = useState("");
  const [reasonText, setReasonText] = useState("");

  // A reopened dialog starts clean. Carrying the last subject's reason into the next action
  // is how "abuse report" ends up on a goodwill comp.
  useEffect(() => {
    if (isOpen) return;
    setReasonCode(null);
    setReasonRef("");
    setReasonText("");
  }, [isOpen]);

  const isRefMalformed = reasonRef !== "" && !REASON_REF_PATTERN.test(reasonRef);
  const isRefLong = looksLikeCredential(reasonRef);
  const canConfirm = reasonCode !== null && !isRefMalformed && !isPending && !isConfirmDisabled;

  /** The one exit every dismissal goes through, so rule 4 cannot be routed around. */
  const requestClose = (): void => {
    if (isDismissLocked) return;
    onOpenChange(false);
  };

  return (
    <Dialog.Root
      open={isOpen}
      onOpenChange={(next) => {
        if (next) {
          onOpenChange(true);
          return;
        }
        requestClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-ink opacity-40 dark:bg-surface dark:opacity-75" />
        <Dialog.Content
          data-testid={testId}
          className={cn(
            "fixed left-1/2 top-[8vh] z-50 w-[min(34rem,94vw)] -translate-x-1/2",
            "flex max-h-[84vh] flex-col overflow-hidden rounded-card",
            "bg-surface-card shadow-overlay",
          )}
        >
          <header className="flex items-start gap-3 px-card pb-3 pt-card">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <Dialog.Title className="type-h2 text-ink">{title}</Dialog.Title>
              <Dialog.Description className="type-body-sm text-ink-muted">
                {description ?? "This action is recorded on the audit log with the reason you give."}
              </Dialog.Description>
            </div>
            <Dialog.Close
              aria-label="Close"
              disabled={isDismissLocked}
              title={isDismissLocked ? DISMISS_LOCKED_HINT : undefined}
              className="rounded-full p-2 text-ink-muted transition-colors duration-fast ease-standard hover:bg-surface-control-hover hover:text-ink disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <X aria-hidden="true" className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
            {banner}

            {isFieldsHidden ? null : (
              <>
                {children}

                <div className="flex flex-col gap-3">
                  <label className="flex flex-col gap-1">
                    <span className="type-caption text-ink-muted">reason code (required)</span>
                    <select
                      data-testid="action-reason-code"
                      value={reasonCode ?? ""}
                      onChange={(event) => {
                        const value = event.target.value;
                        setReasonCode(value === "" ? null : (value as AuditReasonCode));
                      }}
                      className="type-body-sm rounded-control bg-surface-control px-3 py-2 text-ink"
                    >
                      <option value="">— choose a reason —</option>
                      {AUDIT_REASON_CODE_VALUES.map((code) => (
                        <option key={code} value={code}>
                          {REVEAL_REASON_LABELS[code]}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="flex flex-col gap-1">
                    <span className="type-caption text-ink-muted">ticket reference (optional)</span>
                    <input
                      type="text"
                      data-testid="action-reason-ref"
                      value={reasonRef}
                      maxLength={MAX_REASON_REF_CHARS}
                      onChange={(event) => {
                        setReasonRef(event.target.value);
                      }}
                      placeholder="SUP-1423"
                      className="type-body-sm rounded-control bg-surface-control px-3 py-2 text-ink"
                    />
                    {isRefMalformed ? (
                      <span role="alert" className="type-caption text-error">
                        Letters, digits, #, _ and - only, up to 64 characters.
                      </span>
                    ) : null}
                    {isRefLong ? (
                      <span
                        role="alert"
                        data-testid="action-ref-credential-warning"
                        className="type-caption text-caution"
                      >
                        {LONG_REF_WARNING}
                      </span>
                    ) : null}
                  </label>

                  <label className="flex flex-col gap-1">
                    <span className="type-caption text-ink-muted">
                      {`why (optional, ${String(MAX_REASON_TEXT_CHARS)} characters, kept for 90 days)`}
                    </span>
                    <textarea
                      data-testid="action-reason-text"
                      value={reasonText}
                      maxLength={MAX_REASON_TEXT_CHARS}
                      rows={2}
                      onChange={(event) => {
                        setReasonText(event.target.value);
                      }}
                      className="type-body-sm rounded-control bg-surface-control px-3 py-2 text-ink"
                    />
                  </label>
                </div>
              </>
            )}
          </div>

          {isFieldsHidden ? null : (
            <footer className="flex flex-wrap items-center gap-2 px-card pb-card pt-4">
              <Button
                variant={confirmVariant}
                data-testid="action-confirm"
                disabled={!canConfirm}
                onClick={() => {
                  if (reasonCode === null) return;
                  onConfirm({
                    reasonCode,
                    ...(reasonRef === "" ? {} : { reasonRef }),
                    ...(reasonText === "" ? {} : { reasonText }),
                  });
                }}
              >
                {confirmLabel}
              </Button>
              <Button
                variant="quiet"
                disabled={isDismissLocked}
                title={isDismissLocked ? DISMISS_LOCKED_HINT : undefined}
                onClick={requestClose}
              >
                Cancel
              </Button>
              {reasonCode === null ? (
                <span data-testid="action-reason-required" className="type-body-sm text-ink-muted">
                  {ACTION_REASON_REQUIRED_HINT}
                </span>
              ) : null}
            </footer>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Whether `reasonRef` trips `audit._CREDENTIAL_SHAPES`' `[A-Za-z0-9_-]{40,}` rule.
 *
 * The same guard `RevealDialog` applies, restated rather than imported because it is four
 * lines and importing a private helper out of a dialog is a worse coupling than a regex. The
 * two spellings disagree by design — see rule 3 in the file docstring.
 */
function looksLikeCredential(value: string): boolean {
  return new RegExp(`[A-Za-z0-9_-]{${String(LONG_REASON_REF_CHARS)},}`).test(value);
}
