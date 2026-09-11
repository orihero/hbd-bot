/**
 * `<CreditBalanceChip>` — "does this customer have credits?", in three states and never two.
 *
 * The load-bearing distinction is `null` versus `0`, and it is the router's own (see the
 * docstring on `list_user_credits` in `bayram/admin/routers/credits.py`, and
 * `creditLedgerPageSchema`): `credit_accounts.balance` is `NOT NULL`, so a `null` on this wire
 * cannot mean "zero" — it means there is **no account row**. Two populations land there:
 *
 *  - a customer who has never been metered at all (no allowance, no grant, no render), and
 *  - a customer whose `/forget` deleted the row, whose ledger entries survive with a nulled
 *    Telegram id.
 *
 * A chip that rendered both of those as `0` would be answering "they have spent everything"
 * to a question nobody asked, and the operator's next move — granting a comp, or explaining a
 * missing render — is different in each case. So there are three chips: **never metered**,
 * **0 credits**, and a positive balance.
 *
 * ## Not colour alone (§11.3)
 *
 * Each state carries its own GLYPH (`∅` / `○` / `●`) and its own words as well as its own
 * hue, so the three survive greyscale and a red-green deficiency. The hue paints the glyph
 * over a tint of the same family — the soft-badge idiom `<StatusPill>` established, and the
 * one that measures on both palettes.
 */

import type { ReactElement } from "react";

import { cn, formatInteger } from "@/lib";

import { tintVar } from "./colors";
import {
  CREDIT_BALANCE_COLOR_VAR,
  CREDIT_BALANCE_GLYPH,
  CREDIT_BALANCE_TITLES,
  creditBalanceState,
  NEVER_METERED_LABEL,
} from "./credits";

export interface CreditBalanceChipProps {
  /** `credit_accounts.balance`, or `null` when there is no account row. */
  readonly balance: number | null | undefined;
  /** `sm` for a table cell, `md` for a header or a card. */
  readonly size?: "sm" | "md" | undefined;
  readonly className?: string | undefined;
}

export function CreditBalanceChip({
  balance,
  size = "sm",
  className,
}: CreditBalanceChipProps): ReactElement {
  const state = creditBalanceState(balance);
  const color = CREDIT_BALANCE_COLOR_VAR[state];
  const label =
    state === "never-metered"
      ? NEVER_METERED_LABEL
      : `${formatInteger(balance ?? 0)} credit${balance === 1 ? "" : "s"}`;

  return (
    <span
      data-testid="credit-balance-chip"
      data-state={state}
      title={CREDIT_BALANCE_TITLES[state]}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-pill text-ink",
        size === "sm" ? "type-body-sm px-2.5 py-0.5" : "type-body px-3 py-1",
        className,
      )}
      style={{ backgroundColor: tintVar(color) }}
    >
      {/* The glyph is the non-colour channel; the words beside it already say the state, so
          it is hidden from assistive tech rather than announced as punctuation. */}
      <span aria-hidden="true" className="leading-none" style={{ color }}>
        {CREDIT_BALANCE_GLYPH[state]}
      </span>
      <span className={state === "never-metered" ? undefined : "num"}>{label}</span>
    </span>
  );
}
