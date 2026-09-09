/**
 * The credits vocabulary: the three balance states, the four movement kinds, and the words
 * and marks each one is drawn with.
 *
 * A sibling module rather than exports hanging off the components, for the reason
 * `revealFields.ts`, `stagePlan.ts` and `playback.ts` are: a screen, a chip and a table all
 * need to agree about what `null` means, and a rule that lives inside one component is a rule
 * the next surface re-invents slightly differently.
 *
 * The one decision worth stating plainly, because everything else here follows from it:
 * **`balance === null` is not `0`.** `credit_accounts.balance` is `NOT NULL`, so a null on
 * the wire can only mean there is no account row — a customer never metered, or one whose
 * `/forget` deleted the row while keeping their ledger entries. "Spent everything" is the
 * opposite claim.
 */

import type { CreditEntryKind } from "@/api";

/** Which of the three facts a balance is stating. */
export type CreditBalanceState = "never-metered" | "spent" | "held";

/** `null` is not zero, decided once so a column, a chip and a drawer cannot disagree. */
export function creditBalanceState(balance: number | null | undefined): CreditBalanceState {
  if (balance === null || balance === undefined) return "never-metered";
  return balance > 0 ? "held" : "spent";
}

/** Said instead of a number, because there is no account to hold one. */
export const NEVER_METERED_LABEL = "never metered";

/** The heading on the ledger's empty state. */
export const NEVER_METERED_TITLE = "Never metered";

export const NEVER_METERED_BODY =
  "There is no credit_accounts row for this account — it has never been granted or charged anything, or its row was erased by /forget. That is a different fact from a balance of 0, and it is why this is not an empty table.";

/** The fact behind each chip, for an operator who hovers it. */
export const CREDIT_BALANCE_TITLES: Readonly<Record<CreditBalanceState, string>> = {
  "never-metered":
    "No credit_accounts row at all — never granted, never charged, or erased by /forget. This is not a balance of 0.",
  spent: "Metered, and the balance is 0: everything this account was given has been spent.",
  held: "Credits the ledger can prove. The number the customer is told is creditsProjected, which can differ.",
};

/** §11.3: the non-colour channel. Three states, three marks. */
export const CREDIT_BALANCE_GLYPH: Readonly<Record<CreditBalanceState, string>> = {
  "never-metered": "∅",
  spent: "○",
  held: "●",
};

/**
 * `--neutral` for the absent account, `--caution` for the spent one, `--success` for a
 * balance. Three families rather than three shades of one, so the states differ at a glance
 * as well as in the words. All three are the text-safe member of their family.
 */
export const CREDIT_BALANCE_COLOR_VAR: Readonly<Record<CreditBalanceState, string>> = {
  "never-metered": "var(--neutral)",
  spent: "var(--caution)",
  held: "var(--success)",
};

/**
 * The mark beside each movement: direction without colour.
 *
 * `consume` gets a third shape rather than a second arrow. It moves nothing — its delta is
 * exactly `0`, pinned by `ck_credit_ledger_delta_matches_kind` — and marks a debit settled,
 * which is what frees the in-flight slot. Drawing it as an increase or a decrease would be a
 * lie about arithmetic the database itself constrains.
 */
export const CREDIT_KIND_GLYPH: Readonly<Record<CreditEntryKind, string>> = {
  grant: "▲",
  refund: "▲",
  debit: "▼",
  consume: "◇",
};

export const CREDIT_KIND_COLOR_VAR: Readonly<Record<CreditEntryKind, string>> = {
  grant: "var(--success)",
  refund: "var(--info)",
  debit: "var(--caution)",
  consume: "var(--neutral)",
};
