/**
 * "Re-send the confirmation" — the one nudge this section ships.
 *
 * It sends a message the customer was already owed. It writes no money row, mints no credit and
 * creates no state a customer can spend, which is why it carries no step-up and why SUPPORT
 * holds it: support is who takes the "I paid and nothing happened" call, and this is the single
 * most common answer to it.
 *
 * ## Its idempotency is structural, not promised
 *
 * `payme_notify_job_id(publicRef)` is deterministic, so ARQ collapses a double press into one
 * job; and `mark_intent_notified` stamps `notified_at` only `WHERE notified_at IS NULL`, so
 * this enqueue and the worker's own five-minute backstop cannot both message one person. A
 * replay is therefore a SUCCESS with a different sentence — "already queued, this press changed
 * nothing" — and not a failure to retry.
 *
 * ## The three refusals are shown before the round trip and re-checked after it
 *
 * `notify.canNotify` and `notify.refusalCode` ride on the dossier read, so the button is
 * disabled with its reason visible rather than discovering the refusal as a red banner. The
 * server re-checks all three anyway and answers 409 with `details.refusalCode` from the SAME
 * vocabulary — a disabled button is a courtesy and the handler is the authority. There is one
 * set of words for these three facts, not two.
 *
 * ## What it does not claim
 *
 * `notified_at` says we enqueued and the worker sent. Whether the customer SAW it is a Telegram
 * fact this database does not hold, and the dialog says so rather than inventing a delivery
 * status it cannot know.
 */

import { useState, type JSX } from "react";

import { notifyRefusalOf, type NotifyEnqueued, type NotifyRefusal } from "@/api/billing";
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
import type { TranslationPath } from "@/i18n/types";

import { useNotifyPayment } from "./useRail";

/** One sentence per refusal, shared by the disabled button and the server's 409. */
export const NOTIFY_REFUSAL_KEYS: Readonly<Record<NotifyRefusal, TranslationPath>> = {
  not_paid: "billing.notify.refusalNotPaid",
  buyer_erased: "billing.notify.refusalBuyerErased",
  already_notified: "billing.notify.refusalAlreadyNotified",
};

export interface NotifyDialogProps {
  readonly isOpen: boolean;
  readonly intentId: string;
  readonly onClose: () => void;
  /** Handed the queue's answer — `isReplay` decides which of two success sentences is shown. */
  readonly onDone: (result: NotifyEnqueued) => void;
}

export function NotifyDialog({
  isOpen,
  intentId,
  onClose,
  onDone,
}: NotifyDialogProps): JSX.Element | null {
  const { t } = useI18n();
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);
  const notify = useNotifyPayment();

  if (!isOpen) return null;

  const body = reasonBodyOf(reason);
  const error = notify.error;
  /* A 409 carries the refusal in `details`. Read through the typed helper, never by casting:
     the bag is server-shaped, and a wrong guess would render "already notified" for a refusal
     that said something else entirely. */
  const refusal = error === null ? null : notifyRefusalOf(error.details);

  function close(): void {
    setReason(EMPTY_REASON);
    notify.reset();
    onClose();
  }

  return (
    <ConfirmDialog
      isOpen={isOpen}
      title={t("billing.notify.confirmTitle")}
      description={
        <>
          <span>{t("billing.notify.confirmBody")}</span>{" "}
          <span className="text-ink-400">{t("billing.notify.notDelivered")}</span>
        </>
      }
      confirmLabel={t("billing.notify.confirmLabel")}
      pendingLabel={t("billing.notify.pending")}
      isPending={notify.isPending}
      isConfirmDisabled={!canSubmitReason(reason)}
      error={
        error === null ? undefined : (
          <ErrorNote
            tone={error.status === 403 ? "denied" : "error"}
            title={t("billing.notify.action")}
            /* The refusal's own sentence when the server named one, and the raw message
               otherwise. Both are safe to render: server messages are already redacted. */
            message={refusal === null ? error.message : t(NOTIFY_REFUSAL_KEYS[refusal])}
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
        label: t("billing.notify.reasonLabel"),
        hint: t("billing.notify.reasonHint"),
        value: reason.text,
        isRequired: false,
        onChange: (text) => {
          setReason({ ...reason, text });
        },
      }}
      onConfirm={() => {
        if (body === null) return;
        notify.mutate(
          { intentId, body },
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
      <ReasonFieldset value={reason} onChange={setReason} isDisabled={notify.isPending} />
    </ConfirmDialog>
  );
}
