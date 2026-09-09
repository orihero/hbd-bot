/**
 * `<CreditLedgerTable>` — the append-only movements behind a balance.
 *
 * This is the screen that answers "was this account comped, and by whom?", which is why three
 * of its details are not negotiable:
 *
 * 1. **`account === null` is not an empty ledger.** It means `credit_accounts` holds no row.
 *    That is rendered as "never metered" — a stated fact with its own explanation — and never
 *    as a bare empty grid, which reads as "nothing has happened yet" for a customer whose row
 *    was erased by `/forget`. Those rows survive erasure with a nulled Telegram id, so a null
 *    account can sit above a table with movements in it; the notice says so rather than the
 *    two contradicting each other.
 * 2. **`consume` is not a zero-value grant.** The four kinds carry three different signs,
 *    pinned at the database by `ck_credit_ledger_delta_matches_kind`: `grant` and `refund` are
 *    positive, `debit` is negative, and `consume` is exactly `0` — it moves nothing and marks
 *    a debit *settled*, which is what frees the in-flight slot. So it gets its own treatment
 *    rather than being coloured, or hidden, as a no-op.
 * 3. **`actor` is verbatim, `admin:{username}` included.** It is our own operator identity,
 *    not customer content, and masking it would send the operator to the audit log for every
 *    grant — the one question this table is open for. `null` is the pipeline's own movements.
 *
 * ## Colour is never the only channel (§11.3)
 *
 * The signed delta is coloured, and it also carries its SIGN in the text (`+3`, `−1`, `±0`)
 * and a glyph in the movement column. A greyscale print, a projector and a red-green
 * deficiency all leave the direction of every row readable.
 */

import type { ReactElement } from "react";

import type { CreditEntryKind, CreditLedgerPage } from "@/api";
import { CursorPager, DataTable, Timestamp, type DataColumn } from "@/components/data";
import { EmptyState } from "@/components/util";
import { cn, EMPTY_VALUE, formatInteger, humaniseEnum } from "@/lib";

import { CreditBalanceChip } from "./CreditBalanceChip";
import {
  CREDIT_KIND_COLOR_VAR,
  CREDIT_KIND_GLYPH,
  NEVER_METERED_BODY,
  NEVER_METERED_TITLE,
} from "./credits";
import { OrderRefChip } from "./OrderRefChip";

export interface CreditLedgerTableProps {
  /** The page exactly as `GET /users/{id}/credits` returned it; `undefined` while loading. */
  readonly page: CreditLedgerPage | undefined;
  /** The cursor that produced this page; `null` on page one. */
  readonly cursor: string | null;
  readonly onCursorChange: (cursor: string | null) => void;
  readonly limit: number;
  readonly onLimitChange?: ((limit: number) => void) | undefined;
  readonly isFetching?: boolean | undefined;
  /** Hide the balance line when the host already shows the chip beside its own heading. */
  readonly isSummaryHidden?: boolean | undefined;
  readonly className?: string | undefined;
}

export function CreditLedgerTable({
  page,
  cursor,
  onCursorChange,
  limit,
  onLimitChange,
  isFetching = false,
  isSummaryHidden = false,
  className,
}: CreditLedgerTableProps): ReactElement {
  const items = page?.items ?? [];
  const account = page?.account ?? null;
  // `undefined` is "still loading" and must not claim anything; only a page that ARRIVED
  // with a null account is evidence of an unmetered customer.
  const isNeverMetered = page !== undefined && account === null;

  const columns: readonly DataColumn<(typeof items)[number]>[] = [
    {
      id: "createdAt",
      header: "when",
      isNumeric: false,
      width: "11rem",
      cell: (row) => <Timestamp at={row.createdAt} seconds />,
    },
    {
      id: "kind",
      header: "movement",
      isNumeric: false,
      width: "9rem",
      cell: (row) => (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-ink">
          <span aria-hidden="true" className="leading-none" style={{ color: CREDIT_KIND_COLOR_VAR[row.kind] }}>
            {CREDIT_KIND_GLYPH[row.kind]}
          </span>
          {humaniseEnum(row.kind)}
        </span>
      ),
    },
    {
      id: "delta",
      header: "delta",
      isNumeric: true,
      width: "6rem",
      cell: (row) => <SignedDelta delta={row.delta} kind={row.kind} />,
    },
    {
      id: "reason",
      header: "reason",
      isNumeric: false,
      cell: (row) => <span className="text-ink">{humaniseEnum(row.reason)}</span>,
    },
    {
      id: "actor",
      header: "actor",
      isNumeric: false,
      width: "12rem",
      cell: (row) =>
        row.actor === null ? (
          // Not an operator: the pipeline wrote it. Said in words rather than as a dash,
          // because "nobody" and "we do not know who" are different answers.
          <span className="type-body-sm text-ink-muted">the pipeline</span>
        ) : (
          // Verbatim, `admin:` prefix included — see rule 3 in the file docstring.
          <span className="type-mono text-ink">{row.actor}</span>
        ),
    },
    {
      id: "orderId",
      header: "order",
      isNumeric: false,
      width: "10rem",
      cell: (row) =>
        row.orderId === null ? (
          <span className="text-ink-muted">{EMPTY_VALUE}</span>
        ) : (
          <OrderRefChip orderId={row.orderId} />
        ),
    },
    {
      id: "generation",
      header: "gen",
      headerTitle: "charge generation — bumped by each refund, which is what makes a refunded order chargeable again",
      isNumeric: true,
      width: "4.5rem",
      cell: (row) => <span className="text-ink">{formatInteger(row.generation)}</span>,
    },
  ];

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {isSummaryHidden ? null : (
        <div
          data-testid="credit-ledger-summary"
          className="flex flex-wrap items-center gap-3 type-body-sm text-ink-muted"
        >
          <CreditBalanceChip balance={account?.balance ?? null} size="md" />
          {account === null ? null : (
            <>
              <span>
                {"lifetime granted "}
                <span className="num text-ink">{formatInteger(account.lifetimeGranted)}</span>
              </span>
              <span>
                {"allowance period "}
                <span className="num text-ink">
                  {account.allowancePeriod === null
                    ? EMPTY_VALUE
                    : formatInteger(account.allowancePeriod)}
                </span>
              </span>
            </>
          )}
        </div>
      )}

      {isNeverMetered && items.length > 0 ? (
        <p role="status" data-testid="credit-ledger-orphan-note" className="type-body-sm text-ink-muted">
          {`These ${formatInteger(items.length)} movements have no account row above them. Erasure keeps the ledger and nulls its Telegram id, so this is what a forgotten customer's history looks like.`}
        </p>
      ) : null}

      <DataTable
        label="credit ledger"
        data={items}
        columns={columns}
        getRowId={(row) => row.id}
        isRefetching={isFetching}
        emptyState={
          isNeverMetered ? (
            <EmptyState glyph="∅" title={NEVER_METERED_TITLE} body={NEVER_METERED_BODY} />
          ) : (
            <EmptyState
              title="No movements"
              body="This account exists and its ledger is empty on this page — nothing has been granted, charged or refunded here."
            />
          )
        }
        footer={
          <CursorPager
            label="movements"
            meta={page?.meta}
            itemCount={items.length}
            cursor={cursor}
            onCursorChange={onCursorChange}
            limit={limit}
            // Spread rather than passed: `CursorPagerProps` declares `onLimitChange` as a
            // plain optional, and under `exactOptionalPropertyTypes` an explicit `undefined`
            // is not the same thing as an absent prop.
            {...(onLimitChange === undefined ? {} : { onLimitChange })}
            isFetching={isFetching}
          />
        }
      />
    </div>
  );
}

/**
 * One row's arithmetic, with its sign in the text as well as in the colour.
 *
 * `±0` for a `consume` rather than `+0`: it is not a grant of nothing, it is the row that
 * explains why a customer who "used" a credit was never refunded it.
 */
function SignedDelta({
  delta,
  kind,
}: {
  readonly delta: number;
  readonly kind: CreditEntryKind;
}): ReactElement {
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  return (
    <span
      data-testid="credit-delta"
      data-kind={kind}
      data-sign={delta > 0 ? "positive" : delta < 0 ? "negative" : "zero"}
      className="num"
      style={{ color: CREDIT_KIND_COLOR_VAR[kind] }}
    >
      {`${sign}${formatInteger(Math.abs(delta))}`}
    </span>
  );
}
