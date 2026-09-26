/**
 * The payments table's columns, outside the Screen file so that file stays a pure component
 * module and Fast Refresh keeps working.
 *
 * ## The buyer column is the one that has to be right
 *
 * A payment carries a MASKED buyer and there is no plaintext behind it on this surface — a
 * payer identity is a `POST /api/reveal` question, and adding a second door to plaintext would
 * be a second audit shape and a second budget for one disclosure. So no reveal affordance is
 * drawn here: a button that can only ever fail is worse than no button.
 *
 * `telegramUserIdMasked: null` and `isBuyerErased: true` are **two different facts** and the
 * cell renders them as two different things. Erased means `/forget` ran: the money moved, the
 * receipt and the amount survive by design, and there is nobody left to grant to or tell. It
 * is a STATE, never a discrepancy, never a blank, and never a fraud badge. A blank cell would
 * read as a rendering fault and send support hunting for a value the system deliberately
 * destroyed on request.
 *
 * ## `settleSource` is the first question of every reconciliation
 *
 * "Did the rail move this money, or did one of us?" A payment settled by hand has no performed
 * transaction and is a named term in the settlement identity precisely so it is not mistaken
 * for a defect. The badge says which, and the full `settleNote` is in its title.
 *
 * ## No sort control
 *
 * No `?sort=` parameter exists anywhere on this API; every list is `ORDER BY created_at DESC,
 * id DESC`, fixed. A header that sent one would be silently ignored, which is worse than a
 * 422 — so no column declares `sort`, and the caption says the ordering out loud.
 */

import type { JSX } from "react";

import type { IntentListItem } from "@/api/billing";
import { Badge } from "@/components/Badge";
import { CELL_SECONDARY_CLASS, type Column } from "@/components/DataTable";
import { money } from "@/features/dashboard/adapt";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";

import { Instant } from "./instants";

/** A `t` bound to the current locale. Passed in rather than hooked: this module is not a hook. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

/**
 * State tones. `paid` is the only accent; `expired` and `cancelled` are muted rather than red.
 *
 * An abandoned checkout is the single most common thing that will ever be in this table and it
 * is not a failure — somebody opened a payment link and did not pay. Painting it in the alarm
 * colour would make the ordinary case look like an incident and teach an operator to ignore
 * the colour before anything real ever happens.
 */
const STATE_TONE: Readonly<Record<string, "neutral" | "accent" | "warning" | "muted">> = {
  pending: "neutral",
  awaiting: "warning",
  paid: "accent",
  cancelled: "muted",
  expired: "muted",
};

/** One of the three chain ticks — receipt, credit, told. Present or absent, never a guess. */
function ChainMark({
  isDone,
  label,
}: {
  readonly isDone: boolean;
  readonly label: string;
}): JSX.Element {
  return (
    <span
      className={cn(
        "text-[11px] leading-[1.35]",
        isDone ? "font-semibold text-ink-800" : "text-ink-300 line-through",
      )}
    >
      {label}
    </span>
  );
}

export function buildIntentColumns(t: Translate): readonly Column<IntentListItem>[] {
  return [
    {
      key: "opened",
      header: t("billing.intents.columns.opened"),
      width: "15%",
      render: (row) => <Instant at={row.createdAt} />,
    },
    {
      key: "reference",
      header: t("billing.intents.columns.reference"),
      width: "16%",
      render: (row) => (
        /* Monospace and whole: this is what a customer reads out over the phone and what an
           operator compares character by character. Truncating it would be truncating the
           only identifier this row can be found by. */
        <span className="font-mono text-[12px] leading-4 text-ink-900">{row.publicRef}</span>
      ),
    },
    {
      key: "state",
      header: t("billing.intents.columns.state"),
      width: "10%",
      render: (row) => (
        <span className="inline-flex flex-wrap items-center gap-1">
          <Badge tone={STATE_TONE[row.state] ?? "neutral"}>{row.state}</Badge>
          {row.isSandbox ? (
            <Badge tone="warning">{t("billing.intents.sandboxBadge")}</Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "product",
      header: t("billing.intents.columns.product"),
      width: "12%",
      render: (row) => (
        <div className="flex flex-col gap-[2px]">
          <span>{row.product}</span>
          {row.planSongs === null || row.planDays === null ? null : (
            <span className={CELL_SECONDARY_CLASS}>
              {t("billing.intents.planShape", { songs: row.planSongs, days: row.planDays })}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "amount",
      header: t("billing.intents.columns.amount"),
      width: "11%",
      align: "right",
      render: (row) => {
        /* `money()` from the dashboard's adapter, never a second minor-unit table: Payme
           amounts are tiyin, and a duplicated exponent table is how a receipt comes to be
           quoted at a hundredth or a hundred times what the customer actually paid. */
        const amount = money(row.amountMinor, row.currency);
        return (
          <span className="whitespace-nowrap tabular-nums">
            {amount.value} <span className="text-ink-400">{amount.unit}</span>
          </span>
        );
      },
    },
    {
      key: "buyer",
      header: t("billing.intents.columns.buyer"),
      width: "12%",
      render: (row) =>
        row.isBuyerErased ? (
          <Badge tone="muted">
            <span data-testid="buyer-erased">{t("billing.intents.buyerErased")}</span>
          </Badge>
        ) : (
          /* The server's mask, verbatim. No reveal button: there is no plaintext behind it on
             this surface, by design (see the module header). */
          <span data-testid="buyer-masked" className="font-mono text-[12px] leading-4">
            {row.telegramUserIdMasked ?? "—"}
          </span>
        ),
    },
    {
      key: "rail",
      header: t("billing.intents.columns.rail"),
      width: "12%",
      render: (row) =>
        row.transactionCount === 0 ? (
          <span className={CELL_SECONDARY_CLASS}>{t("billing.intents.railNever")}</span>
        ) : (
          <span>
            {t("billing.intents.railTransactions", {
              count: row.transactionCount,
              state: row.latestTransactionState ?? "—",
            })}
          </span>
        ),
    },
    {
      key: "settled",
      header: t("billing.intents.columns.settled"),
      width: "13%",
      render: (row) =>
        row.settledAt === null ? (
          <span className={CELL_SECONDARY_CLASS}>{t("billing.intents.notSettled")}</span>
        ) : (
          <div className="flex flex-col gap-[2px]">
            <Instant at={row.settledAt} />
            <Badge tone={row.settleSource === "operator" ? "warning" : "neutral"} title={row.settleNote ?? undefined}>
              {row.settleSource === "operator"
                ? t("billing.intents.settledByOperator")
                : t("billing.intents.settledByRail")}
            </Badge>
          </div>
        ),
    },
    {
      key: "chain",
      header: t("billing.intents.columns.chain"),
      width: "13%",
      render: (row) =>
        !row.hasReceipt && !row.hasGrant && row.notifiedAt === null ? (
          <span className={CELL_SECONDARY_CLASS}>{t("billing.intents.chainNone")}</span>
        ) : (
          /* Three marks, and a struck one is not an alarm: a PLAN sale legitimately has a
             receipt and no credit, because a plan mints songs as they are used. The dossier's
             lifeline is where that distinction is spelled out; here it is three facts. */
          <span className="inline-flex flex-wrap items-center gap-2">
            <ChainMark isDone={row.hasReceipt} label={t("billing.intents.chainReceipt")} />
            <ChainMark isDone={row.hasGrant} label={t("billing.intents.chainGrant")} />
            <ChainMark
              isDone={row.notifiedAt !== null}
              label={t("billing.intents.chainNotified")}
            />
          </span>
        ),
    },
  ];
}
