/**
 * Grant credits — the one control on this screen that moves money.
 *
 * One credit is one render, which is real vendor spend, so three things here are stricter than
 * they look:
 *
 * 1. **The idempotency key belongs to the PRESS, not to the call.** `beginCreditGrant` mints it
 *    once and this component keeps it; a step-up round trip, a timeout and a second press of
 *    Confirm with the same amount all resend the SAME attempt, so the server answers the second
 *    one `isReplay: true` with nothing moved. A key minted per call turns one retried timeout
 *    into two grants. The key is re-minted when the AMOUNT changes, because a different amount
 *    is a different decision — and on close, because a reopened dialog is a new decision too.
 * 2. **The confirm button states the amount and the recipient.** It is the last thing read
 *    before money moves, and "Confirm" would name neither.
 * 3. **A replay is a SUCCESS in which nothing moved.** This dialog hands the whole result up
 *    rather than reporting "granted"; the screen prints `isReplay` plainly and shows
 *    `account.balance`, which the server read back from the database rather than computed.
 *
 * There is no 404 on this route: the writer OPENS an account that has never been metered, which
 * is exactly the customer a goodwill comp is for. So this never renders "no such user", and a
 * `null` balance beside it means "no `credit_accounts` row", not a balance of zero.
 */

import { useEffect, useRef, useState, type JSX } from "react";

import { useI18n } from "@/i18n";

import {
  MAX_GRANT_CREDITS,
  MAX_REASON_TEXT_CHARS,
  MIN_GRANT_CREDITS,
} from "@/api/constants";
import { stepUpTargetOf } from "@/api/reveal";
import type { CreditGrantResultView } from "@/api/users";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StepUpDialog } from "@/features/reveal";
import { FIELD_CONTROL_CLASS, SECTION_LABEL_CLASS } from "@/features/reveal/controls";
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
import { beginCreditGrant, useGrantCredits, type CreditGrantAttempt } from "./useUsers";

/** The default ask: one credit is one song, and one song is what a goodwill comp usually is. */
const DEFAULT_CREDITS = "1";

export const CREDITS_OUT_OF_RANGE = `Whole credits, ${String(MIN_GRANT_CREDITS)} to ${String(MAX_GRANT_CREDITS)}. The cap is a blast radius, not a policy — grant twice if the case genuinely needs more.`;

export interface GrantCreditsDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** The route key AND what the step-up scope is built from. Never drawn. */
  readonly telegramUserId: number;
  /** OUR words for the subject: the masked Telegram id. Never a name. */
  readonly subjectLabel: string;
  /** Handed the whole result, `isReplay` included, so the screen can be honest about it. */
  readonly onGranted: (result: CreditGrantResultView) => void;
}

export function GrantCreditsDialog({
  isOpen,
  onClose,
  telegramUserId,
  subjectLabel,
  onGranted,
}: GrantCreditsDialogProps): JSX.Element {
  const { t } = useI18n();
  const [creditsText, setCreditsText] = useState(DEFAULT_CREDITS);
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  /**
   * The attempt in flight, and therefore the idempotency key. A ref rather than state because
   * nothing renders from it: what it must survive is a re-render between the refusal and the
   * retry, not a paint.
   */
  const attemptRef = useRef<CreditGrantAttempt | null>(null);

  const grant = useGrantCredits();
  const { reset } = grant;

  useEffect(() => {
    // A closed dialog holds no amount, no reason and NO KEY. The next opening is a new
    // decision, and a new decision must be able to grant the same amount again.
    if (isOpen) return;
    reset();
    setCreditsText(DEFAULT_CREDITS);
    setReason(EMPTY_REASON);
    attemptRef.current = null;
  }, [isOpen, reset]);

  const credits = parseCredits(creditsText);
  const isCreditsValid = credits !== null;
  const failure = failureOf(grant.error);
  const stepUpTarget = stepUpTargetOf(failure);

  function send(attempt: CreditGrantAttempt): void {
    attemptRef.current = attempt;
    grant.mutate(attempt, {
      onSuccess: (result) => {
        onGranted(result);
        onClose();
      },
    });
  }

  function confirm(): void {
    const body = reasonBodyOf(reason);
    if (body === null || credits === null) return;
    const held = attemptRef.current;
    /*
     * The same amount is the same decision, so a second press after a refusal reuses the key
     * and the server can tell us it already happened. A different amount is a different
     * decision and gets its own.
     */
    // Spreading the held attempt keeps its `requestId` — which is the whole point — while
    // letting a reason the operator has since corrected reach the audit row. It is the one
    // legitimate way past `beginCreditGrant`, because the alternative is either a new key
    // (a possible double grant) or sending a reason the operator has already replaced.
    const attempt =
      held !== null && held.credits === credits
        ? { ...held, reason: body }
        : beginCreditGrant({ telegramUserId, credits, reason: body });
    send(attempt);
  }

  return (
    <>
      <ConfirmDialog
        isOpen={isOpen && stepUpTarget === null}
        onClose={onClose}
        title={t("users.grantDialog.title")}
        description={`${subjectLabel} will be able to order again immediately. One credit is one rendered song, so this is real spend; it is recorded on the audit log with the reason you give, and it opens a credit account if this customer has never had one.`}
        confirmLabel={
          credits === null
            ? "Grant credits"
            : `Grant ${String(credits)} ${credits === 1 ? "credit" : "credits"} to ${subjectLabel}`
        }
        pendingLabel={t("users.grantDialog.granting")}
        isPending={grant.isPending}
        isConfirmDisabled={!isCreditsValid || !canSubmitReason(reason)}
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
          grant.error === null || stepUpTarget !== null ? undefined : (
            <QueryErrorNote error={grant.error} noun={t("users.detailNouns.grant")} />
          )
        }
      >
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className={SECTION_LABEL_CLASS}>credits (required)</span>
            <input
              type="number"
              inputMode="numeric"
              data-testid="grant-credits"
              value={creditsText}
              min={MIN_GRANT_CREDITS}
              max={MAX_GRANT_CREDITS}
              step={1}
              disabled={grant.isPending}
              aria-invalid={!isCreditsValid}
              onChange={(event) => {
                setCreditsText(event.target.value);
              }}
              className={FIELD_CONTROL_CLASS}
            />
            {isCreditsValid ? null : (
              <span role="alert" className="text-[12px] leading-4 text-required-deep">
                {CREDITS_OUT_OF_RANGE}
              </span>
            )}
          </label>

          <ReasonFieldset value={reason} onChange={setReason} isDisabled={grant.isPending} />
          {reason.code === null ? (
            <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
          ) : null}
        </div>
      </ConfirmDialog>

      <StepUpDialog
        isOpen={isOpen && stepUpTarget !== null}
        /* Cancelling returns to the form with the amount and the reason intact — and, because
           the key lives in a ref, with the SAME idempotency key. */
        onClose={reset}
        action={stepUpTarget?.action ?? "credit.grant"}
        /* Verbatim from the refusal: the Telegram id as bare decimal digits. */
        subjectId={stepUpTarget?.subjectId ?? String(telegramUserId)}
        subjectLabel={subjectLabel}
        note={`Granting ${credits === null ? "credits" : `${String(credits)} credits`} to ${subjectLabel} needs a grant scoped to this account.`}
        onGranted={() => {
          // The same attempt, key included: re-authenticating authorises the action, it does
          // not make this a second grant.
          const held = attemptRef.current;
          if (held !== null) send(held);
        }}
      />
    </>
  );
}

/** The typed amount, or `null` when it is not a whole number the server would accept. */
function parseCredits(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const parsed = Number.parseInt(value, 10);
  if (parsed < MIN_GRANT_CREDITS || parsed > MAX_GRANT_CREDITS) return null;
  return parsed;
}
