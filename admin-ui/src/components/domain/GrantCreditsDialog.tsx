/**
 * `<GrantCreditsDialog>` / `<GrantCreditsButton>` — the operator's goodwill comp.
 *
 * `POST /api/users/{telegram_user_id}/credits/grant` has been complete, guarded and tested on
 * the server for months with nothing on the surface that could call it. Four properties of
 * that route decide the shape of this dialog, and each one is a defect if it is dropped:
 *
 * 1. **A fresh `requestId` per ATTEMPT — and the SAME one for a retry of that attempt.** The
 *    server keys the write `grant:admin:{telegramUserId}:{requestId}`, so the same value sent
 *    twice tops the account up once and answers `isReplay: true` with nothing moved. That is
 *    what makes a retry after a timeout safe, and it only works if the retry carries the id
 *    the timed-out request carried. Minting on every press would defeat it exactly when it
 *    matters: the write commits, the gateway times out, `NETWORK_ERROR` comes back,
 *    `mutations.retry: false` makes the operator the retry mechanism, and their second press
 *    with a new id writes a second grant. So the id is minted when the FORM changes — a
 *    different amount, a different reason — and reused while it has not. It must equally not
 *    come from anything coarser than that: an id derived from a ticket number, or minted once
 *    when the dialog opened, silently grants nothing the second time an operator legitimately
 *    grants again. A reopened dialog is a new attempt and mints afresh.
 * 2. **`isReplay` is surfaced.** "Granted 3 credits" for both outcomes is how an operator
 *    grants twice, or believes they did. The two sentences differ.
 * 3. **A `403 STEP_UP_REQUIRED` is recovered, not reported.** The handler consumes a
 *    subject-scoped grant, and its subject id is the Telegram integer as a bare decimal
 *    string — NOT a UUID. It goes through `stepUpTargetOf` and `<StepUpPrompt>` verbatim; the
 *    scope is compared byte-for-byte and a re-formatted id is a permanent, silent 403. The
 *    typed reason and the credits stay on screen throughout, and the SAME body (same
 *    `requestId`) is sent again — a grant authorises an action on a subject, not a request.
 * 4. **1..100.** `credits` is `ge=1, le=100` server-side; the cap is a blast radius, not a
 *    validation nicety — the number it exists to refuse is the `1000` that was meant to be
 *    `10`. A credit is one render and one render is real vendor spend.
 *
 * ## Where the success goes
 *
 * There is no toast host in this console — nothing renders transient notifications, and this
 * is not the place to invent one. The result is stated inside the dialog, in a `role="status"`
 * panel that names the new balance and says which of the two things happened; the caller gets
 * `onSuccess` for whatever else it needs to refresh. Because the panel lives inside the
 * dialog, the dialog is `isDismissLocked` from the press until the result is acknowledged
 * with **Done**: an Esc a beat after Grant would otherwise let real credits land with the
 * operator told nothing, and a toast is the only other thing that could have caught that.
 * The keys under `users` are invalidated
 * here rather than left to the caller, because `creditsProjected` on the detail and
 * `account.balance` on the ledger both move on a grant and a screen that refreshed one without
 * the other shows the pair this feature exists to compare disagreeing with itself.
 *
 * ## Who sees it
 *
 * `credit.grant.write` — the permission the ROUTER names (`credit.grant` is the step-up cell,
 * which is a different thing and is enforced inside the handler). §11.4: hiding, not
 * disabling, so a VIEWER sees no button and, if one is rendered anyway, no dialog.
 */

import { useEffect, useState, type ReactElement } from "react";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  failureOf,
  MAX_GRANT_CREDITS,
  MIN_GRANT_CREDITS,
  postCreditGrant,
  unwrapAsync,
  type CreditGrantRequest,
  type CreditGrantResultView,
} from "@/api";
import { Button } from "@/components/util/Button";
import { PermissionGate } from "@/components/util/PermissionGate";
import { formatInteger, queryKeys } from "@/lib";

import { ReasonConfirmDialog, type ReasonValue } from "./ReasonConfirmDialog";
import { stepUpTargetOf } from "./stepUp";
import { StepUpPrompt } from "./StepUpPrompt";
import { useRevealCeilings } from "./useReveal";

export const GRANT_TITLE = "Grant credits";

/** What `credits` may be, said before the 422 rather than by it. */
export const CREDITS_RANGE_HINT = `Between ${String(MIN_GRANT_CREDITS)} and ${String(MAX_GRANT_CREDITS)} whole credits. One credit is one render, which is real vendor spend — the cap is a blast radius, not a form rule.`;

/** The two success sentences. They differ because the two outcomes differ. */
export const FRESH_GRANT_NOTICE = "The credits were added just now.";
export const REPLAY_NOTICE =
  "This exact request had already been granted, so NOTHING moved — the balance below is what the earlier grant left. Press Grant again only if you meant to add more.";

export interface GrantCreditsDialogProps {
  readonly isOpen: boolean;
  readonly onOpenChange: (isOpen: boolean) => void;
  /** The account being credited. It is the path parameter and never a body field. */
  readonly telegramUserId: number;
  /** OUR words for the subject — the masked id. Never a recipient's name. */
  readonly subjectLabel?: string | undefined;
  /** Fired once the grant lands, so the caller can refresh anything outside `users`. */
  readonly onSuccess?: ((result: CreditGrantResultView) => void) | undefined;
}

export function GrantCreditsDialog({
  isOpen,
  onOpenChange,
  telegramUserId,
  subjectLabel,
  onSuccess,
}: GrantCreditsDialogProps): ReactElement {
  const [credits, setCredits] = useState<string>(String(MIN_GRANT_CREDITS));
  /** The body actually sent, kept so a step-up retry can resend it UNCHANGED. */
  const [pending, setPending] = useState<CreditGrantRequest | null>(null);

  const queryClient = useQueryClient();
  const ceilings = useRevealCeilings(isOpen);

  const grant = useMutation<CreditGrantResultView, unknown, CreditGrantRequest>({
    mutationFn: (body: CreditGrantRequest) => unwrapAsync(postCreditGrant(telegramUserId, body)),
    onSuccess: (result: CreditGrantResultView) => {
      // Everything under `users` — the list's balance column, the detail's projection and
      // the ledger page — moves on a grant. One prefix, so none of them can be missed.
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      onSuccess?.(result);
    },
  });

  const { reset } = grant;
  // A reopened dialog starts clean: a previous account's reason, credits or result carried
  // into the next grant is how the wrong customer gets comped.
  useEffect(() => {
    if (isOpen) return;
    reset();
    setCredits(String(MIN_GRANT_CREDITS));
    setPending(null);
  }, [isOpen, reset]);

  const parsedCredits = Number(credits);
  const isCreditsValid =
    credits.trim() !== "" &&
    Number.isInteger(parsedCredits) &&
    parsedCredits >= MIN_GRANT_CREDITS &&
    parsedCredits <= MAX_GRANT_CREDITS;

  const failure = failureOf(grant.error);
  const stepUpTarget = stepUpTargetOf(failure);
  const result = grant.data;

  return (
    <PermissionGate permission="credit.grant.write">
      <ReasonConfirmDialog
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        testId="grant-credits-dialog"
        title={GRANT_TITLE}
        description={
          subjectLabel === undefined
            ? "The grant opens an account if there is not one yet, and writes an audit row inside the same transaction."
            : `Credits for ${subjectLabel}. The grant opens an account if there is not one yet, and writes an audit row inside the same transaction.`
        }
        confirmLabel={
          grant.isPending
            ? "Granting…"
            : `Grant ${isCreditsValid ? formatInteger(parsedCredits) : "—"} credits`
        }
        isConfirmDisabled={!isCreditsValid}
        isPending={grant.isPending}
        // Locked from the press until the outcome is read: while the write is unsettled, and
        // while a result panel is on screen waiting for Done. See rule 2 and "Where the
        // success goes" — the caller's own Done and the step-up's Cancel still close it.
        isDismissLocked={grant.isPending || result !== undefined}
        isFieldsHidden={stepUpTarget !== null || result !== undefined}
        onConfirm={(reason: ReasonValue) => {
          const attempt = { credits: parsedCredits, ...reason };
          /*
           * The same attempt pressed again is a RETRY, and a retry must carry the id the
           * first try carried or the server has no way to recognise it — see rule 1. The
           * only thing that mints a new id is a changed form, which is a different grant.
           */
          const body: CreditGrantRequest =
            pending !== null && isSameAttempt(pending, attempt)
              ? pending
              : { ...attempt, requestId: mintRequestId() };
          setPending(body);
          grant.mutate(body);
        }}
        banner={
          <>
            {stepUpTarget === null ? null : (
              <StepUpPrompt
                action={stepUpTarget.action}
                subjectId={stepUpTarget.subjectId}
                subjectLabel={subjectLabel ?? String(telegramUserId)}
                graceS={ceilings.stepUpGraceS}
                note={
                  <span>
                    {`Granting ${credits} credits to this account needs a grant scoped to it.`}
                  </span>
                }
                onGranted={() => {
                  // The SAME body, `requestId` included: the server has no memory of what we
                  // were trying to do, and a fresh id here would make a retried grant a
                  // second grant.
                  if (pending !== null) grant.mutate(pending);
                }}
                onCancel={() => {
                  onOpenChange(false);
                }}
              />
            )}

            {failure !== null && stepUpTarget === null ? (
              <p
                role="alert"
                data-testid="grant-failure"
                data-code={failure.code}
                className="type-body-sm rounded-2xl bg-surface-control p-4 text-error"
              >
                <span className="type-mono">{failure.code}</span>
                {` — ${failure.message}`}
              </p>
            ) : null}

            {result === undefined ? null : (
              <GrantResult
                result={result}
                onDone={() => {
                  onOpenChange(false);
                }}
              />
            )}
          </>
        }
      >
        <label className="flex flex-col gap-1">
          <span className="type-caption text-ink-muted">credits to add (required)</span>
          <input
            type="number"
            inputMode="numeric"
            data-testid="grant-credits-amount"
            value={credits}
            min={MIN_GRANT_CREDITS}
            max={MAX_GRANT_CREDITS}
            step={1}
            onChange={(event) => {
              setCredits(event.target.value);
            }}
            className="type-body num rounded-control bg-surface-control px-3 py-2 text-ink"
          />
          <span className="type-caption text-ink-muted">{CREDITS_RANGE_HINT}</span>
          {isCreditsValid ? null : (
            <span role="alert" data-testid="grant-credits-invalid" className="type-caption text-error">
              {`Enter a whole number from ${String(MIN_GRANT_CREDITS)} to ${String(MAX_GRANT_CREDITS)}.`}
            </span>
          )}
        </label>
      </ReasonConfirmDialog>
    </PermissionGate>
  );
}

/* -------------------------------------------------------------------------- */
/* The trigger                                                                 */
/* -------------------------------------------------------------------------- */

export interface GrantCreditsButtonProps
  extends Omit<GrantCreditsDialogProps, "isOpen" | "onOpenChange"> {
  readonly label?: string | undefined;
  readonly className?: string | undefined;
}

/**
 * The affordance, gated where it is drawn.
 *
 * Same argument as `<RevealButton>`: putting the gate inside the control means a screen
 * cannot wire the grant in and forget it, which is how a `permission.denied` audit row gets
 * written by curiosity rather than by an attack.
 */
export function GrantCreditsButton({
  label = GRANT_TITLE,
  className,
  ...dialog
}: GrantCreditsButtonProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <PermissionGate permission="credit.grant.write">
      <Button
        variant="secondary"
        data-testid="grant-credits-button"
        className={className}
        onClick={() => {
          setIsOpen(true);
        }}
      >
        {label}
      </Button>
      <GrantCreditsDialog {...dialog} isOpen={isOpen} onOpenChange={setIsOpen} />
    </PermissionGate>
  );
}

/* -------------------------------------------------------------------------- */
/* Pieces                                                                      */
/* -------------------------------------------------------------------------- */

function GrantResult({
  result,
  onDone,
}: {
  readonly result: CreditGrantResultView;
  readonly onDone: () => void;
}): ReactElement {
  return (
    <div
      role="status"
      data-testid="grant-result"
      data-replay={result.isReplay ? "true" : "false"}
      className="flex flex-col gap-2 rounded-2xl bg-surface-control p-4"
    >
      <p className="type-body-sm text-ink">
        {`${formatInteger(result.grantedCredits)} credits — ${result.isReplay ? REPLAY_NOTICE : FRESH_GRANT_NOTICE}`}
      </p>
      <p className="type-body-sm text-ink">
        {"balance now "}
        <span className="num">{formatInteger(result.account.balance)}</span>
        {" · lifetime granted "}
        <span className="num">{formatInteger(result.account.lifetimeGranted)}</span>
      </p>
      {/* The key the server actually wrote under, so a support thread can quote it. */}
      <p className="type-caption text-ink-muted">
        {"idempotency key "}
        <span className="type-mono text-ink">{result.idempotencyKey}</span>
      </p>
      <div>
        <Button variant="quiet" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}

/**
 * Whether a press is a retry of the body already sent, rather than a new grant.
 *
 * Everything the operator can change is compared — the amount and all three reason fields —
 * because any of them changing makes this a different write that the server must not fold
 * into the last one. `requestId` is excluded for the obvious reason: it is the answer.
 */
function isSameAttempt(
  sent: CreditGrantRequest,
  attempt: Omit<CreditGrantRequest, "requestId">,
): boolean {
  return (
    sent.credits === attempt.credits &&
    sent.reasonCode === attempt.reasonCode &&
    sent.reasonRef === attempt.reasonRef &&
    sent.reasonText === attempt.reasonText
  );
}

/**
 * A v4 UUID for THIS attempt.
 *
 * `crypto.randomUUID` is secure-context only. This console is served over HTTPS with Secure
 * cookies, so it is there in practice — but an operator on a plain-HTTP LAN deployment would
 * otherwise get a `TypeError` on the one button that spends money, so the fallback builds the
 * same shape out of `getRandomValues`, which has no such restriction. Omitting `requestId`
 * instead would be worse than either: the server would mint one per request, and a retried
 * grant would become a second grant.
 */
function mintRequestId(): string {
  // `Partial<Crypto>`, not `Crypto`: `lib.dom` types both members as always present, and the
  // whole point here is that `randomUUID` is not, outside a secure context.
  const source: Partial<Crypto> = globalThis.crypto;
  if (typeof source.randomUUID === "function") return source.randomUUID();

  const bytes = new Uint8Array(16);
  source.getRandomValues?.(bytes);
  const octet = (index: number): number => bytes[index] ?? 0;
  const hex = Array.from({ length: 16 }, (_unused, index) => {
    const value =
      index === 6
        ? (octet(6) & 0x0f) | 0x40 // version 4
        : index === 8
          ? (octet(8) & 0x3f) | 0x80 // variant 10xx
          : octet(index);
    return value.toString(16).padStart(2, "0");
  }).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
