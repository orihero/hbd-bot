/**
 * The payments list's lookup: "the customer read me a reference over the phone".
 *
 * One input, two accepted identifiers, and **three distinguishable outcomes** — which is why
 * it is a lookup rather than another filter on the list.
 *
 *  - A malformed reference is answered HERE, before any request. The operator mistyped, and
 *    telling them so is a different answer from telling them no such payment exists.
 *  - A well-formed reference that matches nothing is a **200** carrying two nulls.
 *  - A match offers the dossier.
 *
 * Collapsing the first two — which is what firing the request on any input would do, since the
 * server answers a malformed one with a 422 — would tell somebody their customer never paid
 * when in fact a character was dropped in transcription.
 *
 * ## Two identifiers, told apart by shape, and no third
 *
 * A payment reference is 24 LOWERCASE hex (`secrets.token_hex(12)`); a Payme transaction id is
 * 24 hex in whichever case their cabinet renders it. So an uppercase-bearing value can only be
 * theirs, and a lowercase one could be either — which is why a lowercase value is tried as OUR
 * reference first and the response says which index answered.
 *
 * There is deliberately no name search, no phone search and no free-text box. That is a
 * standing refusal in this panel: billing is searched by the two identifiers that are not
 * people. `idempotency_key` is not searchable either — it is shaped `topup:{tg}:{scope}:{seq}`
 * and embeds the customer's Telegram id, which is precisely why `public_ref` exists.
 */

import { useState, type FormEvent, type JSX } from "react";
import { useNavigate } from "react-router-dom";

import { PAYME_TRANSACTION_ID_PATTERN, PUBLIC_REF_PATTERN } from "@/api/constants";
import { intentDetailPath } from "@/app/paths";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import { useIntentLookup } from "./useRail";

/**
 * Which identifier this string is, or `null` when it is neither.
 *
 * Exported for its test: the lowercase-is-ours rule is the one piece of dispatch this file
 * owns, and it decides which query parameter the request carries.
 */
export function classifyReference(raw: string): "ref" | "transactionId" | null {
  const value = raw.trim();
  if (PUBLIC_REF_PATTERN.test(value)) return "ref";
  if (PAYME_TRANSACTION_ID_PATTERN.test(value)) return "transactionId";
  return null;
}

export interface LookupBoxProps {
  readonly className?: string | undefined;
}

/** The kit's 36-high field, sized for the toolbar rather than for a card of its own. */
const INPUT_CLASS = cn(
  "h-9 w-[26ch] max-w-full rounded-field border border-stroke bg-card px-3",
  "font-mono text-[12px] leading-[16.392px] tracking-[-0.36px] text-ink-900",
  "placeholder:text-ink-300",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
);

export function LookupBox({ className }: LookupBoxProps): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  /** What was SUBMITTED, not what is being typed. A keystroke is not a question. */
  const [submitted, setSubmitted] = useState<string | null>(null);

  const typedKind = classifyReference(typed);
  const submittedKind = submitted === null ? null : classifyReference(submitted);
  const isMalformed = typed.trim() !== "" && typedKind === null;

  const lookup = useIntentLookup(
    submittedKind === "ref"
      ? { ref: submitted }
      : submittedKind === "transactionId"
        ? { transactionId: submitted }
        : {},
    submittedKind !== null,
  );

  /* Navigation on a match happens during render-driven effectless flow: the query resolves,
     this component re-renders, and the branch below hands the operator the link rather than
     moving them. An automatic redirect was the alternative and is worse — it takes the URL
     they typed off the screen before they can check it against the one they were read. */
  const match = lookup.data ?? null;
  /* Hoisted rather than read inside the handler: TypeScript does not carry a property's
     narrowing into a closure, and the alternative was a `?? ""` fallback that would have
     navigated to `/billing/intents/` — a path with no id in it — on a branch that cannot
     actually be reached. A local makes the impossibility structural. */
  const matchedId = match === null ? null : match.intentId;

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (typedKind === null) return;
    setSubmitted(typed.trim());
  }

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2">
        <input
          id="rail-lookup"
          type="text"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          value={typed}
          /* Both identifiers are exactly 24 characters, so anything longer is a paste that
             brought punctuation with it. Capped rather than trimmed silently. */
          maxLength={24}
          aria-label={t("billing.lookup.label")}
          placeholder={t("billing.lookup.placeholder")}
          aria-invalid={isMalformed}
          onChange={(event) => {
            setTyped(event.target.value);
            // A new question invalidates the previous answer immediately: leaving the old
            // "no such payment" on screen under a half-typed reference is how somebody
            // reads a verdict about a reference they are no longer asking about.
            setSubmitted(null);
          }}
          className={INPUT_CLASS}
        />
        <button
          type="submit"
          disabled={typedKind === null}
          className={cn(
            "h-9 shrink-0 cursor-pointer rounded-button border border-stroke bg-card px-3",
            "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800",
            "hover:bg-bg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
            "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-card",
          )}
        >
          {t("billing.lookup.submit")}
        </button>
      </form>

      {isMalformed ? (
        <p
          role="alert"
          data-testid="lookup-malformed"
          className="m-0 text-[11px] leading-[1.45] text-required-deep"
        >
          {t("billing.lookup.malformed")}
        </p>
      ) : null}

      {match === null ? null : matchedId === null ? (
        <p data-testid="lookup-no-match" className="m-0 text-[11px] leading-[1.45] text-ink-500">
          {t("billing.lookup.noMatch")}
        </p>
      ) : (
        <p data-testid="lookup-match" className="m-0 flex flex-wrap items-baseline gap-2">
          <button
            type="button"
            onClick={() => {
              navigate(intentDetailPath(matchedId));
            }}
            className="cursor-pointer rounded border-0 bg-transparent p-0 text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep"
          >
            {t("billing.dossier.title", { reference: typed.trim() })}
          </button>
          <span className="text-[11px] leading-[1.45] text-ink-400">
            {match.matchedOn === "payme_transaction_id"
              ? t("billing.lookup.matchedTransaction")
              : t("billing.lookup.matchedRef")}
          </span>
        </p>
      )}
    </div>
  );
}
