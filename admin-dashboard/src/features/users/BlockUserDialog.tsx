/**
 * Block / unblock — the destructive half of this screen's two operator actions.
 *
 * Five properties of `POST /users/{id}/block` and `/unblock` shape this component, and each
 * one is a defect if it is dropped:
 *
 * 1. **`isBlocked` picks the ROUTE, never a body field.** The two routes write different audit
 *    actions (`user.block` and `user.unblock`), so one endpoint taking a boolean would be an
 *    unblock that audits as a block. What is passed in is the state ON SCREEN; the action moves
 *    to its opposite.
 * 2. **The button does not disable itself on the state it is showing.** Blocking an
 *    already-blocked account is an idempotent upsert that answers 200 and still writes an audit
 *    row. The flag on screen can be stale, and refusing the second press client-side would
 *    suppress the record of an operator who meant it. There is no conflict code on these routes.
 * 3. **A `STEP_UP_REQUIRED` is recovered, not reported.** The scope is `user.block:{id}` with
 *    the Telegram id as bare decimal digits, and it is taken from `details` VERBATIM — the
 *    server compares the composed scope whole, so an id this component re-formatted is a
 *    permanent, silent 403. The same body then goes again unchanged: a grant authorises an
 *    action on a subject, not a request.
 * 4. **A refusal keeps the reason.** The typed reason lives above `<ConfirmDialog>`, so a
 *    step-up, a 422 or a timeout never costs the operator what they wrote.
 * 5. **There is no 404.** The block writer upserts, because the customer these buttons are
 *    reached for often has no `users` row — and refusing would make the route an existence
 *    oracle for guessable Telegram ids. So this never renders "no such user".
 *
 * The step-up is drawn INSTEAD of the confirm dialog rather than over it. `<ConfirmDialog>` and
 * `<DialogShell>` each install a document-level focus fence, and two fences fight over the
 * password field; closing one while the other is open is also the honest picture, since the
 * decision has been made and what is missing is a credential.
 */

import { useEffect, useRef, useState, type JSX } from "react";

import { MAX_REASON_TEXT_CHARS } from "@/api/constants";
import { stepUpTargetOf } from "@/api/reveal";
import type { UserBlockRequest, UserBlockResultView } from "@/api/users";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StepUpDialog } from "@/features/reveal";
import { failureOf } from "@/lib/adminQuery";

import { QueryErrorNote } from "./detailKit";
import {
  EMPTY_REASON,
  REASON_CODE_REQUIRED_HINT,
  REASON_TEXT_HINT,
  REASON_TEXT_LABEL,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "./ReasonFieldset";
import { useBlockUser, useUnblockUser } from "./useUsers";

export interface BlockUserDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** The route key. Never drawn — `subjectLabel` is what reaches the DOM. */
  readonly telegramUserId: number;
  /** OUR words for the subject: the masked Telegram id. Never a name. */
  readonly subjectLabel: string;
  /** The state on screen. The action moves to its opposite. */
  readonly isBlocked: boolean;
  /** Handed the server's own answer, so the screen reflects `isBlocked`/`changedAt` rather than guessing. */
  readonly onBlocked: (result: UserBlockResultView) => void;
  /** Called on the conflict this route does not currently raise. See the note below. */
  readonly onConflict?: (() => void) | undefined;
}

export function BlockUserDialog({
  isOpen,
  onClose,
  telegramUserId,
  subjectLabel,
  isBlocked,
  onBlocked,
  onConflict,
}: BlockUserDialogProps): JSX.Element {
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);
  /** The body actually sent, kept so a step-up retry can resend it BYTE-IDENTICAL. */
  const [pending, setPending] = useState<UserBlockRequest | null>(null);

  /* What pressing the button DOES, which is the negation of what it is showing. */
  const isBlocking = !isBlocked;
  const verb = isBlocking ? "Block" : "Unblock";

  /* Both hooks, unconditionally; the route is chosen from the pair, not from a boolean sent
     to one endpoint. Only the chosen one is ever mutated, so the other holds no state. */
  const block = useBlockUser();
  const unblock = useUnblockUser();
  const action = isBlocking ? block : unblock;

  const { reset } = action;
  useEffect(() => {
    // A reopened dialog starts clean. A previous subject's reason carried into the next
    // action is how "abuse report" ends up on somebody else's audit row.
    if (isOpen) return;
    reset();
    setReason(EMPTY_REASON);
    setPending(null);
  }, [isOpen, reset]);

  const failure = failureOf(action.error);
  const stepUpTarget = stepUpTargetOf(failure);

  /*
   * Defensive, and deliberately so: the taxonomy carries `CONFLICT` but no route in this
   * slice raises it, because block and unblock are idempotent upserts. If one ever does, the
   * only honest response is to re-read the record rather than to retry the same bytes into
   * the same race — so the screen refetches and the operator reads what the state actually is.
   */
  const conflictSeen = useRef(false);
  useEffect(() => {
    if (failure === null || failure.code !== "CONFLICT") {
      conflictSeen.current = false;
      return;
    }
    if (conflictSeen.current) return;
    conflictSeen.current = true;
    onConflict?.();
  }, [failure, onConflict]);

  function submit(body: UserBlockRequest): void {
    setPending(body);
    action.mutate(
      { telegramUserId, body },
      {
        onSuccess: (result) => {
          onBlocked(result);
          onClose();
        },
      },
    );
  }

  return (
    <>
      <ConfirmDialog
        /* Closed while the password is being asked for: two focus fences cannot share a
           keyboard, and the reason below survives because it lives in this component. */
        isOpen={isOpen && stepUpTarget === null}
        onClose={onClose}
        title={isBlocking ? "Block this account" : "Unblock this account"}
        tone={isBlocking ? "danger" : "default"}
        description={
          isBlocking
            ? `${subjectLabel} will be refused by the bot: they cannot start or pay for an order until this is lifted. It takes effect immediately, and it is recorded on the audit log with the reason you give. Blocking an account that is already blocked is a no-op that still writes a row.`
            : `${subjectLabel} will be able to order again. It takes effect immediately, and it is recorded on the audit log with the reason you give.`
        }
        confirmLabel={`${verb} ${subjectLabel}`}
        pendingLabel={isBlocking ? "Blocking…" : "Unblocking…"}
        isPending={action.isPending}
        isConfirmDisabled={!canSubmitReason(reason)}
        onConfirm={() => {
          const body = reasonBodyOf(reason);
          if (body === null) return;
          submit(body);
        }}
        reason={{
          label: REASON_TEXT_LABEL,
          value: reason.text,
          onChange: (text) => {
            setReason((current) => ({ ...current, text }));
          },
          hint: REASON_TEXT_HINT,
          maxLength: MAX_REASON_TEXT_CHARS,
          isRequired: false,
        }}
        error={
          action.error === null || stepUpTarget !== null ? undefined : (
            <QueryErrorNote error={action.error} noun={`the ${verb.toLowerCase()}`} />
          )
        }
      >
        <div className="flex flex-col gap-3">
          <ReasonFieldset value={reason} onChange={setReason} isDisabled={action.isPending} />
          {reason.code === null ? (
            <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
          ) : null}
        </div>
      </ConfirmDialog>

      <StepUpDialog
        isOpen={isOpen && stepUpTarget !== null}
        /* Cancelling drops back to the confirm dialog with the reason still typed: the
           operator declined to re-authenticate, they did not abandon the decision. */
        onClose={reset}
        action={stepUpTarget?.action ?? "user.block"}
        /* Verbatim from the refusal — the Telegram id as bare decimal digits, never a number
           this component re-formatted or a UUID from somewhere else on the screen. */
        subjectId={stepUpTarget?.subjectId ?? String(telegramUserId)}
        subjectLabel={subjectLabel}
        note={`${verb}ing ${subjectLabel} needs a grant scoped to this account.`}
        onGranted={() => {
          // The server has no memory of what was being attempted, so the SAME body goes again.
          if (pending !== null) submit(pending);
        }}
      />
    </>
  );
}
