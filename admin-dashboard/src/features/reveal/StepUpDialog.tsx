/**
 * `<StepUpDialog>` — the app's ONE re-authentication, and the thing every later A+S action
 * (block, grant, force-deliver, purge) should reuse rather than reinvent.
 *
 * A `403 STEP_UP_REQUIRED` is not an error. It is a thing the operator can fix in ten
 * seconds, and rendering it as a red banner with a correlation id is how somebody concludes
 * the console is broken. So the refusal routes here, the operator types the password they
 * already know, and the ORIGINAL request goes again unchanged.
 *
 * Two rules that are cheap to break and expensive to debug:
 *
 * 1. **The subject id is passed through untouched.** The server composes `"<action>:<id>"`
 *    and compares it WHOLE, so an id that was re-formatted anywhere — braced, upper-cased,
 *    a number re-printed — is a permanent silent 403 that looks exactly like a wrong
 *    password. Take it from the refusal's `details`, which is what `stepUpTargetOf` reads.
 * 2. **The grant authorises an ACTION on a SUBJECT, not a request.** The server has no memory
 *    of what was being attempted, so the caller replays its own body.
 *
 * The password is `type="password"` with `autoComplete="current-password"`, lives in this
 * component's state and nowhere else, and is cleared the moment a grant lands, on cancel and
 * on close. `onGranted` is handed the GRANT; nothing upstream ever sees the credential.
 */

import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { MAX_PASSWORD_CHARS } from "@/api/constants";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { ZERO_GRACE_STEP_UP_ACTIONS, type StepUpAction, type StepUpResponse } from "@/api/reveal";

import { FIELD_CONTROL_CLASS, MONO_CLASS, PRIMARY_BUTTON_CLASS, SECONDARY_BUTTON_CLASS } from "./controls";
import { DialogShell, Notice } from "./DialogShell";
import {
  STEP_UP_CHANGES_NOTHING_NOTE,
  STEP_UP_COSTS_NO_BUDGET_NOTE,
  useStepUp,
} from "./useReveal";

/** What each scope actually unlocks, in the operator's terms rather than the matrix's. */
export const STEP_UP_ACTION_KEYS: Readonly<Record<StepUpAction, TranslationPath>> = {
  reveal: "reveal.actions.reveal",
  "order.force_deliver": "reveal.actions.orderForceDeliver",
  "user.block": "reveal.actions.userBlock",
  "credit.grant": "reveal.actions.creditGrant",
  "moderation.decide": "reveal.actions.moderationDecide",
  "user.purge": "reveal.actions.userPurge",
  "config.write": "reveal.actions.configWrite",
  "order.evidence_export": "reveal.actions.orderEvidenceExport",
  "audit.export": "reveal.actions.auditExport",
  "admin.manage": "reveal.actions.adminManage",
  "broadcast.send": "reveal.actions.broadcastSend",
};

/** The footer's submit button lives outside the `<form>`; this is what binds them. */
const FORM_ID = "step-up-form";

/* Why holding the permission was not enough is `reveal.stepUpExplanation`, said plainly
 * above the field; the dialog's own name is `reveal.stepUp.title`. */

export interface StepUpDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** The scope, verbatim from the refusal. */
  readonly action: StepUpAction;
  /** Byte-identical to the id the refusing handler compared against. Never re-formatted. */
  readonly subjectId: string;
  /** OUR words for the subject — an order reference, a Telegram id. Never customer content. */
  readonly subjectLabel?: string | undefined;
  /** What the operator was trying to do, so the password box has a reason attached. */
  readonly note?: ReactNode;
  readonly onGranted: (grant: StepUpResponse) => void;
}

export function StepUpDialog({
  isOpen,
  onClose,
  action,
  subjectId,
  subjectLabel,
  note,
  onGranted,
}: StepUpDialogProps) {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const stepUp = useStepUp();
  const { reset } = stepUp;

  useEffect(() => {
    // A closed dialog holds no credential and no previous failure. This runs on close rather
    // than on open so nothing survives in memory between two attempts.
    if (isOpen) return;
    setPassword("");
    reset();
  }, [isOpen, reset]);

  const isZeroGrace = ZERO_GRACE_STEP_UP_ACTIONS.includes(action);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (password.length === 0 || stepUp.isPending) return;
    stepUp.submit({ password, scope: action, subjectId }, (grant) => {
      // The credential leaves the component the instant it has done its work.
      setPassword("");
      onGranted(grant);
    });
  }

  const failure = stepUp.failure;

  return (
    <DialogShell
      isOpen={isOpen}
      onClose={onClose}
      isBusy={stepUp.isPending}
      testId="step-up-dialog"
      title={t("reveal.stepUp.title")}
      description={t("reveal.stepUpExplanation")}
      footer={
        <>
          {/* Outside the <form> element but bound to it by `form=`, so the panel's footer can
              stay pinned under a scrolling body and Enter in the field still submits. */}
          <button
            type="submit"
            form={FORM_ID}
            disabled={password.length === 0 || stepUp.isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            {stepUp.isPending
              ? t("reveal.stepUpDialog.pending")
              : t("reveal.stepUpDialog.submit")}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={stepUp.isPending}
            className={SECONDARY_BUTTON_CLASS}
          >
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <form id={FORM_ID} onSubmit={handleSubmit} className="flex flex-col gap-5" noValidate>
        {note === undefined ? null : (
          <div className="text-[14px] leading-5 text-ink-500">{note}</div>
        )}

        {/* What is being unlocked, in words AND in the exact strings the server compares. The
            words are for the decision; the strings are so an operator can match a 403 in the
            log against what they actually authorised. */}
        <dl className="flex flex-col gap-3 rounded-card bg-bg p-4">
          <div className="flex flex-col gap-1">
            <dt className="text-[12px] font-semibold uppercase leading-4 tracking-[0.4px] text-ink-300">
              you are unlocking
            </dt>
            <dd className="text-[14px] font-medium leading-5 text-ink-900">
              {t(STEP_UP_ACTION_KEYS[action])}
            </dd>
            <dd className={`${MONO_CLASS} text-ink-400`}>{action}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-[12px] font-semibold uppercase leading-4 tracking-[0.4px] text-ink-300">
              on this subject only
            </dt>
            {subjectLabel === undefined ? null : (
              <dd className="text-[14px] font-medium leading-5 text-ink-900">{subjectLabel}</dd>
            )}
            <dd className={`${MONO_CLASS} text-ink-400`}>{subjectId}</dd>
          </div>
        </dl>

        <label className="flex flex-col gap-1">
          <span className="text-[14px] font-medium leading-5 tracking-[-0.084px] text-label">
            {t("reveal.stepUpDialog.passwordLabel")}
          </span>
          <input
            type="password"
            name="password"
            // The operator was sent here to type this; a second keystroke to reach the field
            // is a second chance to lose the thread of a support call.
            autoFocus
            autoComplete="current-password"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            maxLength={MAX_PASSWORD_CHARS}
            disabled={stepUp.isPending}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={failure !== null}
            className={FIELD_CONTROL_CLASS}
          />
          <span className="text-[12px] leading-4 text-ink-400">
            Your own account password — never the customer's, and it is not stored anywhere by
            this panel.
          </span>
        </label>

        <p className="text-[12px] leading-4 text-ink-400">
          {isZeroGrace
            ? t("reveal.stepUpDialog.zeroGrace")
            : t("reveal.stepUpDialog.graceWindow")}
        </p>

        {/* Only `reveal` is metered: `enforce_reveal_budget` runs on that route and nowhere
            else, so the budget sentence on a block or a grant would teach an operator that
            those writes spend a ceiling they cannot spend. */}
        <p className="text-[12px] leading-4 text-ink-400">
          {action === "reveal" ? STEP_UP_COSTS_NO_BUDGET_NOTE : STEP_UP_CHANGES_NOTHING_NOTE}
        </p>

        {failure === null ? null : (
          <Notice
            tone="refusal"
            testId="step-up-failure"
            title={
              failure.code === "FORBIDDEN"
                ? t("reveal.stepUpDialog.wrongPassword")
                : t("reveal.stepUpDialog.refused")
            }
            code={failure.correlationId === null ? failure.code : `${failure.code} · ${failure.correlationId}`}
          >
            <p>{failure.message}</p>
            {failure.code === "REAUTH_RATE_LIMITED" ? (
              <p>{t("reveal.stepUpDialog.rateLimited")}</p>
            ) : null}
            {failure.code === "INVALID_INPUT" ? (
              <p>{t("reveal.stepUpDialog.invalidScope")}</p>
            ) : null}
          </Notice>
        )}
      </form>
    </DialogShell>
  );
}
