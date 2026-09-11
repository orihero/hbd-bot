/**
 * The pause / resume confirmation. One dialog, both directions, one Redis key.
 *
 * ## No step-up, and it is argued rather than overlooked
 *
 * `bayram/payme/pause.py` states in its own docstring that this switch "is not a security
 * control and must never be documented, tested or relied upon as one. It is an operator
 * convenience with a known open failure mode." Putting the panel's heaviest gate on a control
 * the owning module has explicitly disclaimed would be an inconsistency that module would
 * contradict on sight — and the blast radius is not in the step-up class: pressing this stops
 * the bot QUOTING new checkouts. No money moves, no personal data is disclosed, no credit is
 * minted, no message is sent, and the next operator undoes it in one press. Compare what does
 * carry a step-up here: revealing a person, blocking a person, minting credit, messaging forty
 * thousand people.
 *
 * It is also an incident brake, and the moment somebody needs a brake is the moment they can
 * least afford ninety seconds of password box. `pause.py` already made exactly this
 * availability-over-strictness trade on the read path.
 *
 * What it gets instead: ADMIN and OWNER only, a mandatory `reasonCode`, this confirmation, and
 * an `admin_audit_log` row per press.
 *
 * ## The response is re-read, so the header shows the switch AS STORED
 *
 * The handler writes the key and then reads it back rather than echoing the request. The two
 * differ exactly when something went wrong, which is the case worth showing — so this dialog
 * hands its caller the RESPONSE, and the caller renders that.
 *
 * ## A refusal with no remedy is not a password box
 *
 * A `403 STEP_UP_REQUIRED` from this route would be a server bug (this cell is not in
 * `STEP_UP_ACTIONS`), and a 403 with no `details` is a plain role refusal. Either way there is
 * nothing an operator can do in a dialog, so the failure renders as text and never as a
 * credential prompt — a prompt there offers a loop nobody can win.
 */

import { useState, type JSX } from "react";

import type { RailSwitch } from "@/api/billing";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import {
  EMPTY_REASON,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useI18n } from "@/i18n";
import type { AdminQueryError } from "@/lib/adminQuery";

import { useRailSwitch } from "./useRail";

export interface RailPauseDialogProps {
  readonly isOpen: boolean;
  /** `true` opens the PAUSE confirmation, `false` the resume one. */
  readonly willPause: boolean;
  readonly onClose: () => void;
  /** Handed the switch as the server re-read it, never as it was requested. */
  readonly onDone: (result: RailSwitch) => void;
}

export function RailPauseDialog({
  isOpen,
  willPause,
  onClose,
  onDone,
}: RailPauseDialogProps): JSX.Element | null {
  const { t } = useI18n();
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);
  const flip = useRailSwitch();

  if (!isOpen) return null;

  const body = reasonBodyOf(reason);
  const error: AdminQueryError | null = flip.error;

  function close(): void {
    // The reason dies with the dialog. Carrying it to the next press would attach one
    // operator's stated reason to a different decision, on a row that outlives both.
    setReason(EMPTY_REASON);
    flip.reset();
    onClose();
  }

  return (
    <ConfirmDialog
      isOpen={isOpen}
      title={willPause ? t("billing.pause.pauseTitle") : t("billing.pause.resumeTitle")}
      description={willPause ? t("billing.pause.pauseBody") : t("billing.pause.resumeBody")}
      confirmLabel={willPause ? t("billing.pause.pauseLabel") : t("billing.pause.resumeLabel")}
      pendingLabel={
        willPause ? t("billing.pause.pausePending") : t("billing.pause.resumePending")
      }
      /* `danger` for the pause: it stops the business quoting checkouts, and the button should
         look like the decision it is. Resuming is the ordinary direction. */
      tone={willPause ? "danger" : "default"}
      isPending={flip.isPending}
      isConfirmDisabled={!canSubmitReason(reason)}
      error={
        error === null ? undefined : (
          <ErrorNote
            /* `denied` for a refusal — no Retry, because asking again cannot change a role.
               Everything else is an `error` the operator may usefully re-press. */
            tone={error.status === 403 ? "denied" : "error"}
            title={t("billing.pause.reasonLabel")}
            message={error.message}
            hint={
              error.correlationId === null
                ? undefined
                : `${error.endpoint} · ${error.correlationId}`
            }
            retryable={false}
          />
        )
      }
      reason={{
        label: t("billing.pause.reasonLabel"),
        hint: t("billing.pause.reasonHint"),
        value: reason.text,
        isRequired: false,
        onChange: (text) => {
          setReason({ ...reason, text });
        },
      }}
      onConfirm={() => {
        if (body === null) return;
        flip.mutate(
          { paused: willPause, body },
          {
            onSuccess: (result) => {
              onDone(result);
              close();
            },
          },
        );
      }}
      onClose={close}
    >
      <ReasonFieldset value={reason} onChange={setReason} isDisabled={flip.isPending} />
    </ConfirmDialog>
  );
}
