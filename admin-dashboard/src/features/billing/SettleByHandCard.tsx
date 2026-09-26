/**
 * The recovery command, rendered as text. **There is no submit path and there must not be one.**
 *
 * This card contains one button and it copies a string to the clipboard. It issues no request,
 * it has no form, and the console has no route behind it — `MOUNTED_ROUTES` on the server has
 * no settle entry, so there is nothing here to accidentally wire up later.
 *
 * Five reasons force-settle stays in a terminal, and any one of the last two would be enough:
 *
 * 1. **The panel cannot see the evidence.** `app.py::derive_forbidden_env_vars` refuses to boot
 *    in production if `BAYRAM_PAYME_MERCHANT_KEY` is even reachable in this process, which is
 *    the mechanism that keeps the merchant endpoint a fourth process. So the console can show
 *    every fact about this payment EXCEPT the one that authorises the press: a charge in the
 *    Payme merchant cabinet.
 * 2. **The action mints money nobody can unmint.** It writes a `credit_ledger` GRANT against a
 *    `credit_accounts.balance` that is a fungible scalar with no lot structure. That is the
 *    same reason a cancel-after-perform is refused with -31007.
 * 3. **There is already an honest front door** for "customer paid and got nothing":
 *    `POST /api/users/{id}/credits/grant`, which records a human decision AS a human decision
 *    instead of rewriting the money history to assert a sale.
 * 4. **`operatorSettlements` is a named term in the reconciliation identity**, precisely so
 *    hand-settlements are not mistaken for defects. Making it one click would turn the number
 *    that EXPLAINS mismatches into the number that hides them.
 * 5. **It is the one transition in the whole state machine that drops the mutex.** Every other
 *    move is a conditional UPDATE whose rowcount is the lock — `hold_intent` matches on
 *    `state='pending'`, `claim_intent` and `release_intent` both match on
 *    `active_transaction_id`. `claim_intent_for_operator` matches `pending OR awaiting` and
 *    NAMES NO HOLDER, by explicit decision, because an operator reading Payme's cabinet has no
 *    transaction id of ours to match on. An action whose defining property is that it bypasses
 *    the concurrency guard should not be one click from a browser tab that polls every fifteen
 *    seconds. A terminal is the correct blast door.
 *
 * ## What is deliberately NOT here
 *
 * A pre-flight verdict ("this command would refuse: the payment is already paid") was cut. It
 * is computed at time T and acted on at T+minutes, during which the five-minute sweep or a
 * real inbound `PerformTransaction` can move the payment underneath it — and a stale verdict
 * an operator has learned to trust is worse than no verdict. The dossier already shows the
 * payment's current state, its transactions and its receipt in full, which is the same
 * information without the false currency.
 *
 * The command itself is built on the SERVER (`schemas/billing.py::settle_command`) so the flag
 * spelling lives in one place, and it is interpolated with the public reference twice on
 * purpose: the string an operator copies then contains nothing but that reference — no
 * Telegram id, no idempotency key, no amount — which is what makes it safe to paste into a
 * ticket.
 */

import { useEffect, useState, type JSX } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/** How long the "Copied" acknowledgement stands before the button says its verb again. */
const COPIED_MS = 2_000;

export interface SettleByHandCardProps {
  /** `IntentDossierView.settleCommand`, verbatim. Never composed here. */
  readonly command: string;
  /** The rail's own reference on the receipt — what to search the Payme cabinet for. */
  readonly cabinetReference?: string | null | undefined;
  readonly className?: string | undefined;
}

export function SettleByHandCard({
  command,
  cabinetReference,
  className,
}: SettleByHandCardProps): JSX.Element {
  const { t } = useI18n();
  const [hasCopied, setHasCopied] = useState(false);

  useEffect(() => {
    if (!hasCopied) return;
    const timer = setTimeout(() => {
      setHasCopied(false);
    }, COPIED_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [hasCopied]);

  return (
    <section
      data-testid="settle-by-hand"
      aria-label={t("billing.dossier.settleByHand")}
      className={cn("rounded-card border border-stroke bg-bg p-4", className)}
    >
      <h2 className="m-0 text-[16px] font-semibold leading-[21.856px] tracking-[-0.32px] text-ink-900">
        {t("billing.dossier.settleByHand")}
      </h2>

      <p className="m-0 mt-2 max-w-[80ch] text-[12px] leading-[16.392px] text-ink-500">
        {t("billing.dossier.settleByHandCaveat")}
      </p>

      {/* Selectable text, not an input: an input invites typing into it, and there is nothing
          here to submit. `user-select: all` so one click takes the whole invocation. */}
      <pre className="m-0 mt-3 overflow-x-auto rounded-field border border-stroke bg-card p-3">
        <code
          data-testid="settle-command"
          className="select-all whitespace-pre font-mono text-[12px] leading-4 text-ink-900"
        >
          {command}
        </code>
      </pre>

      {cabinetReference === undefined || cabinetReference === null ? null : (
        <p className="m-0 mt-2 text-[11px] leading-[1.45] text-ink-400">
          <span>{t("billing.dossier.fields.cabinetReference")}: </span>
          <span className="select-all font-mono text-ink-800">{cabinetReference}</span>
        </p>
      )}

      <button
        type="button"
        data-testid="settle-copy"
        onClick={() => {
          /* Best effort, and its failure is not an error worth showing: the command is
             already on screen and selectable, which is the affordance that always works. A
             sandboxed frame, an insecure origin or a denied permission simply leaves the
             label unchanged. The `in` guard is not decoration — `navigator.clipboard` is
             typed non-optional but is genuinely undefined outside a secure context and in
             jsdom, where reading `.writeText` off it would throw inside an event handler. */
          if (!("clipboard" in navigator)) return;
          void navigator.clipboard
            .writeText(command)
            .then(() => {
              setHasCopied(true);
            })
            .catch(() => undefined);
        }}
        className="mt-3 cursor-pointer rounded-button border border-stroke bg-card px-3 py-1 text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800 transition-colors hover:bg-row-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep"
      >
        {hasCopied ? t("billing.dossier.copied") : t("billing.dossier.copyCommand")}
      </button>
    </section>
  );
}
