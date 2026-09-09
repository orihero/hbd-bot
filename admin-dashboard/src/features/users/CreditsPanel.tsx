/**
 * Credits — "can this person order again, and have we already comped them?"
 *
 * The panel's whole job is to keep apart numbers that a single "credits" field would merge, and
 * every one of the distinctions below is a support ticket that has actually been argued:
 *
 *  - **`creditBalance: null` is not a balance of zero.** It means there is no `credit_accounts`
 *    row at all — a third value — and the grant button is exactly what opens one. Drawn as `0`
 *    it becomes the opposite claim: "we metered this account and it has nothing".
 *  - **`creditsProjected` is what the BOT would tell the customer right now**: the stored
 *    balance plus a rolling allowance that is due and has not been minted. An operator handed
 *    only the stored figure cannot answer "they say they have three songs and your panel says
 *    zero", which is the ticket this pair exists for.
 *  - **`inFlightRenderCount` is the only number here that explains a refusal.** A render whose
 *    worker died holds a credit that neither the balance nor the ledger shows as spent.
 *  - **`account: null` on the ledger response** is the same "no row" as a null balance, and it
 *    is not an empty page: an empty `items` array under an existing account means "nothing has
 *    moved on this page", which is a different sentence.
 *
 * Nothing in here is masked or reveal-gated, and that is a property of the tables rather than a
 * relaxation: `credit_accounts` and `credit_ledger` hold a Telegram id, two closed enums and
 * integers, with no free text for `POST /api/reveal` to gate.
 */

import { useEffect, useMemo, useRef, type JSX } from "react";

import { nextCursorOf } from "@/api/pagination";
import type { CreditEntryKind, CreditLedgerEntryView } from "@/api/users";
import { Badge, type BadgeTone } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import {
  Fact,
  FactGrid,
  MONO_CLASS,
  PANEL_NOTE_CLASS,
  Panel,
  QueryErrorNote,
  SectionHeading,
  rangeLabelOf,
  useCursorStack,
} from "./detailKit";
import {
  formatDelta,
  formatInteger,
  formatTimestamp,
  humaniseEnum,
  shortId,
} from "./detailFormat";
import { useUserCredits } from "./useUsers";

/**
 * The ledger's page size, deliberately smaller than the orders table's fifty.
 *
 * It is the explanation beside a balance rather than a working list: the question it answers —
 * "was this account comped, and by whom?" — is nearly always answered by the newest few rows.
 */
const LEDGER_PAGE_LIMIT = 10;

/** No account row at all. Said in words, because the alternative spelling is `0`. */
export const NO_ACCOUNT_LABEL = "no account row";
/** A counter that has never been metered. Also not `0`. */
export const NEVER_METERED_LABEL = "never metered";

const KIND_TONE: Readonly<Record<CreditEntryKind, BadgeTone>> = {
  grant: "accent",
  refund: "neutral",
  debit: "warning",
  consume: "muted",
};

/* The five figures' hints are `users.credits.*Hint`. */

export interface CreditsPanelProps {
  readonly telegramUserId: number | null;
  /** From the user record; `undefined` while it loads or after it failed. */
  readonly creditBalance?: number | null | undefined;
  readonly lifetimeCreditsGranted?: number | null | undefined;
  readonly allowancePeriod?: number | null | undefined;
  readonly creditsProjected?: number | undefined;
  readonly inFlightRenderCount?: number | undefined;
  /** Whether the user record itself failed, so the facts say so instead of shimmering. */
  readonly isRecordUnavailable?: boolean | undefined;
  /**
   * When the last grant on this screen landed, or `null`. A grant INSERTS AT THE TOP of the
   * ledger, so the page an operator was reading is now a page late and its keyset cursor was
   * computed against the pre-grant ordering — the new `admin_grant` row is on page one and
   * page three silently repeats a row. The signal is the write's timestamp rather than a
   * boolean so a second grant is a second reset.
   */
  readonly grantedAt?: number | null | undefined;
}

export function CreditsPanel({
  telegramUserId,
  creditBalance,
  lifetimeCreditsGranted,
  allowancePeriod,
  creditsProjected,
  inFlightRenderCount,
  isRecordUnavailable = false,
  grantedAt = null,
}: CreditsPanelProps): JSX.Element {
  const { t } = useI18n();
  const page = useCursorStack();
  const { toFirst } = page;
  const resetFor = useRef<number | null>(grantedAt);

  useEffect(() => {
    if (grantedAt === null || resetFor.current === grantedAt) return;
    resetFor.current = grantedAt;
    toFirst();
  }, [grantedAt, toFirst]);

  const credits = useUserCredits(telegramUserId, {
    limit: LEDGER_PAGE_LIMIT,
    cursor: page.cursor,
    withTotal: true,
  });

  const items = credits.data?.items ?? [];
  const account = credits.data?.account ?? null;
  const nextCursor = credits.data === undefined ? null : nextCursorOf(credits.data);

  const columns = useMemo<readonly Column<CreditLedgerEntryView>[]>(
    () => [
      {
        key: "delta",
        header: t("users.creditsPanel.movement"),
        width: "6rem",
        align: "right",
        render: (row) => (
          <span className={row.delta < 0 ? "text-ink-800" : "text-accent-deep"}>
            {formatDelta(row.delta)}
          </span>
        ),
      },
      {
        key: "kind",
        header: t("users.creditsPanel.kind"),
        width: "7rem",
        render: (row) => <Badge tone={KIND_TONE[row.kind]}>{humaniseEnum(row.kind)}</Badge>,
      },
      {
        key: "reason",
        header: t("users.creditsPanel.reason"),
        width: "11rem",
        render: (row) => humaniseEnum(row.reason),
      },
      {
        key: "order",
        header: t("users.creditsPanel.order"),
        width: "9rem",
        render: (row) =>
          row.orderId === null ? (
            <span className="text-ink-400">—</span>
          ) : (
            <span className={MONO_CLASS} title={row.orderId}>
              {shortId(row.orderId)}
            </span>
          ),
      },
      {
        key: "actor",
        header: t("users.creditsPanel.actor"),
        width: "10rem",
        render: (row) =>
          row.actor === null ? (
            /* No actor is the system moving credits — an allowance minted, a render settled —
               which is a different fact from an operator whose name we failed to record. */
            <span className="text-ink-400">the system</span>
          ) : (
            <span className="break-words">{row.actor}</span>
          ),
      },
      {
        key: "createdAt",
        header: t("users.creditsPanel.when"),
        width: "11rem",
        render: (row) => (
          <span className="flex flex-col gap-0.5">
            <span>{formatTimestamp(row.createdAt)}</span>
            <span className={cn(CELL_SECONDARY_CLASS, MONO_CLASS)} title={t("users.creditsPanel.idempotencyKey")}>
              {row.idempotencyKey}
            </span>
          </span>
        ),
      },
    ],
    [t],
  );

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-label="credits">
      <SectionHeading>{t("users.credits.title")}</SectionHeading>

      <Panel ariaLabel="credit balances">
        {isRecordUnavailable ? (
          <p className={PANEL_NOTE_CLASS}>
            The balance and the projection are part of the user record, which did not load. The
            ledger below is a separate request and may still be readable.
          </p>
        ) : (
          <>
            <FactGrid>
              <Fact label={t("users.credits.balance")} hint={t("users.credits.balanceHint")}>
                {creditBalance === undefined ? (
                  "…"
                ) : creditBalance === null ? (
                  <span className="text-ink-400">{NO_ACCOUNT_LABEL}</span>
                ) : (
                  formatInteger(creditBalance)
                )}
              </Fact>

              <Fact label={t("users.credits.projected")} hint={t("users.credits.projectedHint")}>
                {creditsProjected === undefined ? "…" : formatInteger(creditsProjected)}
              </Fact>

              <Fact
                label={t("users.credits.rendersInFlight")}
                hint={t("users.credits.inFlightHint")}
              >
                {inFlightRenderCount === undefined ? "…" : formatInteger(inFlightRenderCount)}
              </Fact>

              <Fact
                label={t("users.credits.lifetimeGranted")}
                hint={t("users.credits.lifetimeHint")}
              >
                {lifetimeCreditsGranted === undefined ? (
                  "…"
                ) : lifetimeCreditsGranted === null ? (
                  <span className="text-ink-400">{NEVER_METERED_LABEL}</span>
                ) : (
                  formatInteger(lifetimeCreditsGranted)
                )}
              </Fact>

              <Fact
                label={t("users.credits.allowancePeriod")}
                hint={t("users.credits.allowanceHint")}
              >
                {allowancePeriod === undefined ? (
                  "…"
                ) : allowancePeriod === null ? (
                  <span className="text-ink-400">—</span>
                ) : (
                  formatInteger(allowancePeriod)
                )}
              </Fact>
            </FactGrid>

            <ProjectionNote
              balance={creditBalance}
              projected={creditsProjected}
              inFlightRenderCount={inFlightRenderCount}
            />
          </>
        )}
      </Panel>

      {credits.error === null ? null : (
        <QueryErrorNote
          error={credits.error}
          noun={t("users.creditsPanel.noun")}
          onRetry={() => {
            void credits.refetch();
          }}
          isRetrying={credits.isFetching}
        />
      )}

      {credits.data !== undefined && account === null ? (
        <p className={PANEL_NOTE_CLASS}>
          There is no credit_accounts row for this Telegram id, so there is nothing for the
          ledger to explain. Granting credits opens one.
        </p>
      ) : null}

      <DataTable
        caption={t("users.creditsPanel.caption")}
        columns={columns}
        rows={items}
        getRowKey={(row) => row.id}
        isLoading={credits.isLoading}
        skeletonRows={LEDGER_PAGE_LIMIT}
        className={credits.isPlaceholderData ? "opacity-60 transition-opacity" : undefined}
        emptyMessage={
          <EmptyState
            title={
              account === null
                ? t("users.credits.noAccountTitle")
                : t("users.credits.nothingMovedTitle")
            }
            message={
              account === null
                ? t("users.credits.noAccountMessage")
                : t("users.credits.nothingMovedMessage")
            }
          />
        }
      />

      <CursorPager
        hasPrev={page.hasPrev}
        hasNext={nextCursor !== null}
        isFetching={credits.isFetching}
        onPrev={page.toPrev}
        onNext={
          nextCursor === null
            ? undefined
            : () => {
                page.toNext(nextCursor);
              }
        }
        rangeLabel={rangeLabelOf(
          page.pageIndex,
          LEDGER_PAGE_LIMIT,
          items.length,
          credits.data?.meta,
        )}
      />
    </section>
  );
}

/**
 * The sentence that stops the two credit numbers reading as a contradiction.
 *
 * A `null` balance beside a projection of 3 is the NORMAL reading for a brand-new customer:
 * `credit_accounts` has no row yet and the whole rolling allowance is still ahead of them.
 * Silent when the two agree, because then there is nothing to reconcile — the in-flight line is
 * separate and appears on its own terms, since it explains a refusal rather than a difference.
 */
function ProjectionNote({
  balance,
  projected,
  inFlightRenderCount,
}: {
  readonly balance: number | null | undefined;
  readonly projected: number | undefined;
  readonly inFlightRenderCount: number | undefined;
}): JSX.Element | null {
  // The pair comes from one response, so one of them missing means the record is not here yet.
  if (projected === undefined || balance === undefined) return null;
  const isDifferent = projected !== (balance ?? 0);
  const inFlight = inFlightRenderCount ?? 0;
  if (!isDifferent && inFlight === 0) return null;

  return (
    <div className={cn("flex flex-col gap-1", PANEL_NOTE_CLASS)}>
      {isDifferent ? (
        <p className="m-0">
          {balance === null
            ? `There is no credit_accounts row, so nothing is stored — the ${formatInteger(projected)} above is a rolling allowance this account has never drawn on. That is the normal reading for a customer who has not ordered yet, not a contradiction.`
            : `The customer would be told ${formatInteger(projected)} and the ledger can prove ${formatInteger(balance)}. The difference is a rolling allowance that is due and has not been minted; it becomes a ledger row the moment they order.`}
        </p>
      ) : null}
      {inFlight > 0 ? (
        <p className="m-0">
          {`${formatInteger(inFlight)} ${inFlight === 1 ? "render is" : "renders are"} debited and not settled yet. Those credits are spent as far as the gate is concerned, which is why this account can be refused while the numbers above still look healthy.`}
        </p>
      ) : null}
    </div>
  );
}
