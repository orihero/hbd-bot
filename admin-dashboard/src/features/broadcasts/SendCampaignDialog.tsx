/**
 * The send. The one control in this section that makes messages leave.
 *
 * Four things here are load-bearing rather than decorative:
 *
 * 1. **The exact recipient count is on the confirm button, not only in the prose.** The button
 *    is the last thing read before forty thousand people are messaged, and "Confirm" would name
 *    neither the number nor the act. The number is `progress.recipientCount` — the rows that
 *    will actually be attempted — beside the instant the audience was frozen, because the gap
 *    between the two is the whole reason a preview and a send disagree.
 * 2. **The step-up replays the SAME body.** A `403 STEP_UP_REQUIRED` is not an error: the
 *    variables are held in a ref, `StepUpDialog` takes `subjectId` VERBATIM from the refusal —
 *    the server compares `"broadcast.send:{id}"` whole, so a re-cased or re-printed id is a
 *    permanent silent 403 that looks exactly like a wrong password — and the identical object is
 *    sent again. The reason that reaches the audit row is the reason the operator authorised,
 *    never one rebuilt between the refusal and the retry.
 * 3. **Now and later are one route.** `POST /{id}/send` carries `scheduledFor` or omits it; a
 *    separate `/schedule` would be a second place to forget the step-up. So this dialog decides
 *    only the BODY — the field is present or it is absent — and one hook sends either.
 * 4. **A past instant is caught before the press.** `sendSchedule.tsx` owns that check, the
 *    field and the now/later toggle, and the wizard's review step reads the same module: two
 *    copies of the validator would be two clocks, and the day one stops refusing yesterday is
 *    the day a campaign goes out against a schedule the other half would have caught.
 *
 * There is no typed-count confirmation. That belongs to the wizard, where the audience is being
 * chosen; here the audience has been frozen for some time, the number is stated twice, and a
 * transcription box in front of the brake-adjacent action would be ceremony rather than a check.
 */

import { useEffect, useRef, useState, type JSX } from "react";

import {
  broadcastStateConflictOf,
  type BroadcastSendRequest,
  type BroadcastView,
} from "@/api/broadcasts";
import { MAX_REASON_TEXT_CHARS } from "@/api/constants";
import { stepUpTargetOf } from "@/api/reveal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import {
  BROADCAST_STATE_LABEL_KEY,
  formatAbsolute,
  formatCount,
  noteFor,
} from "@/features/broadcasts/broadcastFormat";
import {
  SendScheduleFieldset,
  sendBodyOf,
  useSendSchedule,
} from "@/features/broadcasts/sendSchedule";
import {
  useSendBroadcast,
  type BroadcastVariables,
} from "@/features/broadcasts/useBroadcasts";
import { StepUpDialog } from "@/features/reveal";
import {
  EMPTY_REASON,
  REASON_CODE_REQUIRED_HINT,
  REASON_TEXT_HINT,
  REASON_TEXT_LABEL,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useI18n } from "@/i18n";
import { failureOf, type AdminQueryError } from "@/lib/adminQuery";

export interface SendCampaignDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly broadcast: BroadcastView;
}

export function SendCampaignDialog({
  isOpen,
  onClose,
  broadcast,
}: SendCampaignDialogProps): JSX.Element {
  const { t } = useI18n();
  const schedule = useSendSchedule();
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  /**
   * The body in flight, held so a step-up can replay it byte for byte.
   *
   * A ref rather than state because nothing renders from it: what it has to survive is the
   * re-render between the refusal and the retry, not a paint.
   */
  const sentRef = useRef<BroadcastVariables<BroadcastSendRequest> | null>(null);

  const send = useSendBroadcast();
  const { reset } = send;
  const resetSchedule = schedule.reset;

  useEffect(() => {
    // A closed dialog holds no instant, no reason and no half-authorised body.
    if (isOpen) return;
    reset();
    resetSchedule();
    setReason(EMPTY_REASON);
    sentRef.current = null;
  }, [isOpen, reset, resetSchedule]);

  const failure = failureOf(send.error);
  const stepUpTarget = stepUpTargetOf(failure);
  const conflictState = broadcastStateConflictOf(failure);

  const count = broadcast.progress.recipientCount;
  const hasRecipients = count > 0;
  const whenError = schedule.error;

  function dispatch(variables: BroadcastVariables<BroadcastSendRequest>): void {
    sentRef.current = variables;
    send.mutate(variables, {
      onSuccess: () => {
        onClose();
      },
    });
  }

  function confirm(): void {
    const reasonBody = reasonBodyOf(reason);
    if (reasonBody === null || !hasRecipients || whenError !== null) return;
    // "Now" OMITS `scheduledFor`; `sendBodyOf` is the one place that distinction is spelled.
    dispatch({ broadcastId: broadcast.id, body: sendBodyOf(reasonBody, schedule) });
  }

  const confirmLabel =
    schedule.when === "now"
      ? t("broadcasts.sendDialog.confirmNow", { count: formatCount(count) })
      : t("broadcasts.sendDialog.confirmLater", { count: formatCount(count) });

  return (
    <>
      <ConfirmDialog
        /* The step-up takes the screen while it is open: two stacked modals would trap focus
           in the one underneath and leave the password box unreachable by keyboard. */
        isOpen={isOpen && stepUpTarget === null}
        onClose={onClose}
        title={t("broadcasts.sendDialog.title")}
        description={
          <>
            <span className="block">{t("broadcasts.sendDialog.description")}</span>
            <strong className="mt-2 block text-ink-900">
              {hasRecipients
                ? t("broadcasts.sendDialog.countWarning", { count: formatCount(count) })
                : t("broadcasts.sendDialog.noRecipients")}
            </strong>
            <span className="mt-1 block">
              {t("broadcasts.sendDialog.frozenNote", {
                at: formatAbsolute(broadcast.audienceEvaluatedAt),
              })}
            </span>
          </>
        }
        confirmLabel={confirmLabel}
        pendingLabel={t("broadcasts.sendDialog.pending")}
        isPending={send.isPending}
        isConfirmDisabled={!hasRecipients || whenError !== null || !canSubmitReason(reason)}
        onConfirm={confirm}
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
          send.error === null || stepUpTarget !== null ? undefined : conflictState !== null ? (
            <ErrorNote
              tone="error"
              title={t("broadcasts.conflict.title")}
              message={t("broadcasts.conflict.message", {
                state: t(BROADCAST_STATE_LABEL_KEY[conflictState]),
              })}
              retryable={false}
            />
          ) : (
            <SendFailure error={send.error} />
          )
        }
      >
        <div className="flex flex-col gap-4">
          <SendScheduleFieldset schedule={schedule} isDisabled={send.isPending} />

          <ReasonFieldset value={reason} onChange={setReason} isDisabled={send.isPending} />
          {reason.code === null ? (
            <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
          ) : null}
        </div>
      </ConfirmDialog>

      <StepUpDialog
        isOpen={isOpen && stepUpTarget !== null}
        /* Cancelling returns to the form with the instant and the reason intact. */
        onClose={reset}
        action={stepUpTarget?.action ?? "broadcast.send"}
        /* VERBATIM from the refusal: the campaign UUID as the handler compared it. */
        subjectId={stepUpTarget?.subjectId ?? broadcast.id}
        subjectLabel={broadcast.title}
        note={t("broadcasts.sendDialog.stepUpNote")}
        onGranted={() => {
          // The same body. Re-authenticating authorises the action; it does not compose a
          // second send, and it must not change what the audit row records.
          const held = sentRef.current;
          if (held !== null) dispatch(held);
        }}
      />
    </>
  );
}

/** Everything that is neither the step-up nor the 409, in the words a failed read gets. */
function SendFailure({ error }: { readonly error: AdminQueryError }): JSX.Element {
  const { t } = useI18n();
  const note = noteFor(error, false, t, t("broadcasts.sendDialog.title"));
  return (
    <ErrorNote
      tone={note.tone}
      title={note.title}
      message={note.message}
      hint={`${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`}
      retryable={false}
    />
  );
}
