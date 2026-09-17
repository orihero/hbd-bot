/**
 * Pause, Resume and Cancel — the three lifecycle moves that need no step-up.
 *
 * They share one dialog because they are one shape: a reason, a conditional `UPDATE`, and a
 * campaign back. What differs is four strings and which mutation runs, and three copies of the
 * same component would drift by exactly the sentence that matters.
 *
 * **No re-authentication in front of the brake.** Pause and cancel only make FEWER messages
 * leave; the server takes the role half alone and no step-up, deliberately, because a password
 * box costs seconds at the moment somebody needs them. Resume is on the same cell for symmetry:
 * it does not widen an audience, it continues one that was already authorised.
 *
 * **Cancel does not recall anything.** The copy says so with the real `sentCount` in it: a
 * campaign cancelled halfway is a cancelled campaign with nine thousand messages delivered, and
 * a dialog that implied otherwise would be the console lying at the worst possible moment.
 *
 * **A 409 is not a generic error.** Every one of these routes is a conditional `UPDATE` against
 * a campaign a worker is moving in another process, so "it had already finished" is a real and
 * frequent answer. It is rendered as the state the server actually found —
 * `broadcastStateConflictOf` — rather than as a red box with a correlation id.
 */

import { useEffect, useState, type JSX } from "react";

import { broadcastStateConflictOf, type BroadcastView } from "@/api/broadcasts";
import { MAX_REASON_TEXT_CHARS } from "@/api/constants";
import type { ReasonedRequest } from "@/api/reveal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import {
  BROADCAST_STATE_LABEL_KEY,
  formatCount,
  noteFor,
} from "@/features/broadcasts/broadcastFormat";
import {
  useCancelBroadcast,
  usePauseBroadcast,
  useResumeBroadcast,
} from "@/features/broadcasts/useBroadcasts";
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
import type { TranslationPath } from "@/i18n/types";
import { failureOf, type AdminQueryError } from "@/lib/adminQuery";

/** The three moves this dialog drives. The send is its own component: it takes a step-up. */
export type CampaignAction = "pause" | "resume" | "cancel";

interface ActionCopy {
  readonly title: TranslationPath;
  readonly description: TranslationPath;
  readonly confirm: TranslationPath;
  readonly pending: TranslationPath;
}

const COPY: Readonly<Record<CampaignAction, ActionCopy>> = {
  pause: {
    title: "broadcasts.pauseDialog.title",
    description: "broadcasts.pauseDialog.description",
    confirm: "broadcasts.pauseDialog.confirm",
    pending: "broadcasts.pauseDialog.pending",
  },
  resume: {
    title: "broadcasts.resumeDialog.title",
    description: "broadcasts.resumeDialog.description",
    confirm: "broadcasts.resumeDialog.confirm",
    pending: "broadcasts.resumeDialog.pending",
  },
  cancel: {
    title: "broadcasts.cancelDialog.title",
    description: "broadcasts.cancelDialog.description",
    confirm: "broadcasts.cancelDialog.confirm",
    pending: "broadcasts.cancelDialog.pending",
  },
};

export interface CampaignActionDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly action: CampaignAction;
  readonly broadcast: BroadcastView;
}

export function CampaignActionDialog({
  isOpen,
  onClose,
  action,
  broadcast,
}: CampaignActionDialogProps): JSX.Element {
  const { t } = useI18n();
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  /*
   * All three mutations are created, and one is used. Hooks cannot be called conditionally, and
   * the alternative — three dialogs, or a mutation threaded in from the screen — would put the
   * same four decisions in three places. Each is idle until it is asked for.
   */
  const pause = usePauseBroadcast();
  const resume = useResumeBroadcast();
  const cancel = useCancelBroadcast();
  const mutation = action === "pause" ? pause : action === "resume" ? resume : cancel;
  const { reset } = mutation;

  useEffect(() => {
    // A closed dialog holds no reason and no previous refusal: reopening it is a new decision.
    if (isOpen) return;
    reset();
    setReason(EMPTY_REASON);
  }, [isOpen, reset]);

  const copy = COPY[action];
  const failure = failureOf(mutation.error);
  const conflictState = broadcastStateConflictOf(failure);

  function confirm(): void {
    const body: ReasonedRequest | null = reasonBodyOf(reason);
    if (body === null) return;
    mutation.mutate(
      { broadcastId: broadcast.id, body },
      {
        // The response IS the campaign, and the hook has already seeded the detail cache with
        // it — so closing here shows the new state rather than the one that was just left.
        onSuccess: () => {
          onClose();
        },
      },
    );
  }

  return (
    <ConfirmDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t(copy.title)}
      description={
        <>
          <span className="block">{t(copy.description)}</span>
          {action === "cancel" ? (
            <span className="mt-2 block">
              {t("broadcasts.cancelDialog.noRecall", {
                count: formatCount(broadcast.progress.sentCount),
              })}
            </span>
          ) : null}
        </>
      }
      confirmLabel={t(copy.confirm)}
      pendingLabel={t(copy.pending)}
      tone={action === "cancel" ? "danger" : "default"}
      isPending={mutation.isPending}
      isConfirmDisabled={!canSubmitReason(reason)}
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
        mutation.error === null ? undefined : conflictState !== null ? (
          <ErrorNote
            tone="error"
            title={t("broadcasts.conflict.title")}
            message={t("broadcasts.conflict.message", {
              state: t(BROADCAST_STATE_LABEL_KEY[conflictState]),
            })}
            /* Nothing to retry: the campaign moved, and asking again asks the same refused
               question. The screen behind is already re-reading it. */
            retryable={false}
          />
        ) : (
          <ActionFailure
            title={t(copy.title)}
            message={mutation.error.message}
            error={mutation.error}
          />
        )
      }
    >
      <div className="flex flex-col gap-3">
        <ReasonFieldset value={reason} onChange={setReason} isDisabled={mutation.isPending} />
        {reason.code === null ? (
          <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
        ) : null}
      </div>
    </ConfirmDialog>
  );
}

/**
 * Everything that is not the 409, said in the same words a failed read gets.
 *
 * The subject is the ACTION rather than the campaign — "Pause this campaign failed" reads as a
 * fact about the press, which is what the operator is holding.
 */
function ActionFailure({
  title,
  message,
  error,
}: {
  readonly title: string;
  readonly message: string;
  readonly error: AdminQueryError;
}): JSX.Element {
  const { t } = useI18n();
  const note = noteFor(error, false, t, title);
  return (
    <ErrorNote
      tone={note.tone}
      title={note.title}
      message={note.message === "" ? message : note.message}
      hint={`${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`}
      retryable={false}
    />
  );
}
