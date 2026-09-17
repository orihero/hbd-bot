/**
 * "Send it to me first" — the one way to read a composed message in Telegram before the audience
 * does.
 *
 * **It needs a campaign, and a campaign freezes the audience.** `POST /{id}/test-send` addresses a
 * campaign row and its bodies; there is no route that renders a draft nobody has saved. So
 * pressing this before the review step is what CREATES the campaign — the recipient rows are
 * materialised, the audience stops moving — and that consequence is stated in the dialog rather
 * than discovered on the next screen. Nothing is sent to that audience: the send is still the
 * review step's own authorisation.
 *
 * **The allowlist is the control, and it is configuration.** The server refuses any id outside
 * `admin_broadcast_test_recipients`, which ships empty — whoever may edit `.env.admin` is a
 * smaller population than whoever holds an admin session, and a limit the caller supplies is not a
 * limit. A 403 here means "this deployment has not named any test recipients", not "your role
 * cannot do this", and the copy says so.
 *
 * **The step-up is the campaign's own.** A test send takes `broadcast.send` scoped to the same
 * campaign id as the real send, so one grant admits both — the screen owns that dialog and the
 * replay, because both actions share it.
 */

import { useEffect, useState, type JSX, type ReactNode } from "react";

import type { BroadcastTestSendRequest, BroadcastTestSendResultView } from "@/api/broadcasts";
import { MAX_REASON_TEXT_CHARS } from "@/api/constants";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FIELD_CONTROL_CLASS, SECTION_LABEL_CLASS } from "@/features/reveal/controls";
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

export interface TestSendDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** True while no campaign exists yet: confirming will freeze the audience. */
  readonly willFreezeAudience: boolean;
  readonly isPending: boolean;
  readonly result: BroadcastTestSendResultView | null;
  readonly error?: ReactNode;
  readonly onConfirm: (body: BroadcastTestSendRequest) => void;
}

export function TestSendDialog({
  isOpen,
  onClose,
  willFreezeAudience,
  isPending,
  result,
  error,
  onConfirm,
}: TestSendDialogProps): JSX.Element {
  const { t } = useI18n();
  const [recipient, setRecipient] = useState("");
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  useEffect(() => {
    // A closed dialog holds no recipient and no half-authorised reason.
    if (isOpen) return;
    setRecipient("");
    setReason(EMPTY_REASON);
  }, [isOpen]);

  const telegramUserId = /^\d+$/u.test(recipient.trim()) ? Number(recipient.trim()) : null;
  const isRecipientValid = telegramUserId !== null && telegramUserId >= 1;

  function confirm(): void {
    const reasonBody = reasonBodyOf(reason);
    if (reasonBody === null || telegramUserId === null || !isRecipientValid) return;
    onConfirm({ ...reasonBody, telegramUserId });
  }

  return (
    <ConfirmDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t("broadcasts.wizard.message.testSend.title")}
      description={
        <>
          <span className="block">{t("broadcasts.wizard.message.testSend.description")}</span>
          {willFreezeAudience ? (
            <strong className="mt-2 block text-ink-900">
              {t("broadcasts.wizard.message.testSend.freezeWarning")}
            </strong>
          ) : null}
          <span className="mt-1 block">
            {t("broadcasts.wizard.message.testSend.allowlistNote")}
          </span>
        </>
      }
      confirmLabel={t("broadcasts.wizard.message.testSend.confirm")}
      pendingLabel={t("broadcasts.wizard.message.testSend.pending")}
      isPending={isPending}
      isConfirmDisabled={!isRecipientValid || !canSubmitReason(reason)}
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
      error={error}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="wizard-test-recipient" className={SECTION_LABEL_CLASS}>
            {t("broadcasts.wizard.message.testSend.recipientLabel")}
          </label>
          <input
            id="wizard-test-recipient"
            type="text"
            inputMode="numeric"
            value={recipient}
            onChange={(event) => {
              setRecipient(event.target.value);
            }}
            aria-describedby="wizard-test-recipient-hint"
            aria-invalid={recipient !== "" && !isRecipientValid}
            className={FIELD_CONTROL_CLASS}
          />
          <p id="wizard-test-recipient-hint" className="m-0 text-[12px] leading-4 text-ink-400">
            {t("broadcasts.wizard.message.testSend.recipientHint")}
          </p>
        </div>

        <ReasonFieldset value={reason} onChange={setReason} isDisabled={isPending} />
        {reason.code === null ? (
          <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
        ) : null}

        {result === null ? null : (
          <p role="status" className="m-0 text-[13px] font-medium text-ink-800">
            {t("broadcasts.wizard.message.testSend.sent", {
              recipient: result.telegramUserIdMasked,
            })}
          </p>
        )}
      </div>
    </ConfirmDialog>
  );
}
