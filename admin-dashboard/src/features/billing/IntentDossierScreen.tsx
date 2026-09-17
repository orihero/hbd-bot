/**
 * `/billing/intents/:intentId` — everything an operator needs to answer "did this customer's
 * money turn into a song?".
 *
 * **One request.** The server takes all six reads inside ONE transaction, and that is the whole
 * reason this screen does not assemble itself from six queries: an operator has to trust that
 * the receipt and the transaction were true at the same instant, and six separate reads during
 * a live settlement would show a performed transaction with no receipt beside it.
 *
 * The panels are in `bayram.payme.cli._render_dossier`'s order, because that order is the
 * question being asked: what was opened, what the rail did about it, what was sold, what was
 * granted, what Payme said, and then where the chain stops.
 *
 * ## Three things this screen renders that a naive one gets wrong
 *
 * **Zero calls has two meanings and the payment's own age decides.** `payme_rpc_log` is swept
 * at 90 days while a paid payment is never purged, and there are no foreign keys anywhere on
 * the rail's three tables — so an old payment with no calls beside it is ORDINARY. It renders
 * as PURGED, not as "Payme never called us", which on a live rail is the sentence that means
 * the payment was settled by hand.
 *
 * **The chain-stop panel is ALWAYS rendered.** For a single song the honest answer is that
 * whether the purchased credit became a song is unanswerable by construction:
 * `credit_accounts.balance` is a fungible scalar with no lot structure, so a later
 * `DEBIT`/`ORDER_RENDER` row cannot be attributed to the grant that funded it. Stating that
 * beats hiding the panel — a missing panel reads as a screen that failed to load.
 *
 * **The idempotency key is nowhere on this page**, because it is nowhere on the wire. It is
 * shaped `topup:{tg}:{scope}:{seq}` and embeds the customer's Telegram id, which is precisely
 * why `public_ref` exists; a tooltip warning would not stop it reaching a DOM node, a
 * screenshot and a support ticket. `IntentDossierScreen.test.tsx` asserts no rendered text
 * contains `topup:` or `plan:starter:`.
 */

import { useMemo, useState, type JSX, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import type { IntentDossier, NotifyEnqueued } from "@/api/billing";
import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { Skeleton } from "@/components/Skeleton";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { PATH } from "@/app/paths";
import { money } from "@/features/dashboard/adapt";
import { useI18n } from "@/i18n";
import { useCanNotifyPayment } from "@/lib/rbac";
import { useSessionGuard } from "@/state/useSessionGuard";

import { Lifeline } from "./Lifeline";
import { NOTIFY_REFUSAL_KEYS, NotifyDialog } from "./NotifyDialog";
import { SettleByHandCard } from "./SettleByHandCard";
import { Instant, formatMs, isBeyondRpcRetention } from "./instants";
import { replyCodeName } from "./railStatus";
import { useIntentDossier } from "./useRail";

/** A titled card. Every panel on this page is one, so they read as one document. */
function Panel({
  title,
  children,
  testId,
}: {
  readonly title: string;
  readonly children: ReactNode;
  readonly testId?: string | undefined;
}): JSX.Element {
  return (
    <section
      data-testid={testId}
      aria-label={title}
      className="rounded-card border border-stroke bg-card p-4"
    >
      <h2 className="m-0 text-[16px] font-semibold leading-[21.856px] tracking-[-0.32px] text-ink-900">
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** One labelled value in a definition list. `null` prints an em dash, never a blank. */
function Field({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <div className="flex min-w-0 flex-col gap-[2px]">
      <dt className="m-0 text-[11px] font-normal leading-[1.35] text-ink-400">{label}</dt>
      <dd className="m-0 min-w-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-900">
        {children}
      </dd>
    </div>
  );
}

const EM_DASH = "—";

export function IntentDossierScreen(): JSX.Element {
  const { t } = useI18n();
  const params = useParams<{ intentId: string }>();
  const intentId = params.intentId ?? null;
  const canNotify = useCanNotifyPayment();
  const [isNotifyOpen, setIsNotifyOpen] = useState(false);
  const [enqueued, setEnqueued] = useState<NotifyEnqueued | null>(null);

  const dossier = useIntentDossier(intentId);
  useSessionGuard([dossier.error]);

  /**
   * The instant the purged-versus-never decision is taken against.
   *
   * Frozen for the life of this screen rather than read per render: the two are indistinguishable
   * in practice, and a memo makes the rule a pure function of `(openedAt, now)` that the panel
   * and any caption below it cannot disagree about across a midnight.
   */
  const now = useMemo(() => new Date(), []);

  const error = dossier.error;
  const data: IntentDossier | undefined = dossier.data;

  const transactionColumns: readonly Column<IntentDossier["transactions"][number]>[] = [
    {
      key: "id",
      header: t("billing.dossier.fields.reference"),
      width: "24%",
      render: (row) => <span className="font-mono">{row.paymeTransactionId}</span>,
    },
    {
      key: "state",
      header: t("billing.dossier.fields.state"),
      width: "16%",
      render: (row) => <Badge tone={row.state === "performed" ? "accent" : "muted"}>{row.state}</Badge>,
    },
    {
      key: "paymeTime",
      header: t("billing.dossier.fields.paymeTime"),
      width: "16%",
      render: (row) => <Instant at={row.paymeTime} />,
    },
    {
      key: "performTime",
      header: t("billing.dossier.fields.performTime"),
      width: "16%",
      render: (row) => (row.performTime === null ? EM_DASH : <Instant at={row.performTime} />),
    },
    {
      key: "cancelTime",
      header: t("billing.dossier.fields.cancelTime"),
      width: "16%",
      render: (row) => (row.cancelTime === null ? EM_DASH : <Instant at={row.cancelTime} />),
    },
    {
      key: "cancelReason",
      header: t("billing.dossier.fields.cancelReason"),
      width: "12%",
      align: "right",
      /* A BARE INTEGER, by argued decision on the server: these codes are Payme's vocabulary
         and they extend it without asking us, so there is no enum mirror and no VARCHAR copy.
         Rendered as the number it is. */
      render: (row) => (
        <span className="tabular-nums">{row.cancelReason === null ? EM_DASH : row.cancelReason}</span>
      ),
    },
  ];

  const callColumns: readonly Column<IntentDossier["calls"][number]>[] = [
    {
      key: "at",
      header: t("billing.calls.columns.at"),
      width: "24%",
      render: (row) => <Instant at={row.at} />,
    },
    {
      key: "method",
      header: t("billing.calls.columns.method"),
      width: "26%",
      render: (row) => <span className="font-mono">{row.method}</span>,
    },
    {
      key: "replyCode",
      header: t("billing.calls.columns.replyCode"),
      width: "26%",
      render: (row) => {
        const name = replyCodeName(row.replyCode);
        return (
          <span className="inline-flex flex-wrap items-baseline gap-1">
            <span className="font-mono tabular-nums">{row.replyCode}</span>
            {name === null ? null : <span className="text-ink-400">{name}</span>}
          </span>
        );
      },
    },
    {
      key: "durationMs",
      header: t("billing.calls.columns.duration"),
      width: "24%",
      align: "right",
      render: (row) => <span className="tabular-nums">{formatMs(row.durationMs)}</span>,
    },
  ];

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={
            data === undefined
              ? t("billing.subjectPayment")
              : t("billing.dossier.title", { reference: data.intent.publicRef })
          }
          subtitle={
            <Link
              to={PATH.railIntents}
              className="text-[12px] leading-4 text-ink-500 underline underline-offset-2"
            >
              {t("billing.dossier.back")}
            </Link>
          }
          actions={
            /* Hidden for a role without `payment.notify`, never disabled — a press would be a
               403 and a `permission.denied` audit row against somebody who did nothing wrong.
               For a role that HOLDS it, the button is present and disabled with its reason
               showing, because the reason is a fact about the payment rather than about them. */
            canNotify && data !== undefined ? (
              <div className="flex min-w-0 flex-col items-end gap-1">
                <ToolbarButton
                  disabled={!data.notify.canNotify}
                  onClick={() => {
                    setIsNotifyOpen(true);
                  }}
                >
                  {t("billing.notify.action")}
                </ToolbarButton>
                {data.notify.refusalCode === null ? null : (
                  <span
                    data-testid="notify-refusal"
                    className="max-w-[46ch] text-right text-[11px] leading-[1.45] text-ink-400"
                  >
                    {t(NOTIFY_REFUSAL_KEYS[data.notify.refusalCode])}
                  </span>
                )}
              </div>
            ) : undefined
          }
        />

        {enqueued === null ? null : (
          <p
            data-testid="notify-result"
            className="m-0 rounded-card border border-stroke bg-bg px-4 py-3 text-[12px] leading-[16.392px] text-ink-800"
          >
            {enqueued.isReplay ? t("billing.notify.replayed") : t("billing.notify.sent")}
          </p>
        )}

        {error === null ? null : error.status === 404 ? (
          <EmptyState
            title={t("billing.dossier.notFound")}
            message={t("billing.dossier.notFoundMessage")}
          />
        ) : (
          <ErrorNote
            tone={error.status === 403 ? "denied" : error.status === 0 ? "offline" : "error"}
            title={t("errors.query.failedTitle", { subject: t("billing.subjectPayment") })}
            message={error.message}
            hint={error.correlationId === null ? undefined : `${error.endpoint} · ${error.correlationId}`}
            retryable={error.status !== 403}
            isRetrying={dossier.isFetching}
            onRetry={() => {
              void dossier.refetch();
            }}
          />
        )}

        {data === undefined ? (
          error === null ? (
            <Skeleton className="h-96 w-full" />
          ) : null
        ) : (
          <>
            {/* First and dominant: the six-step answer to the question this page exists for. */}
            <Lifeline lifeline={data.lifeline} />

            <Panel title={t("billing.dossier.intentPanel")} testId="dossier-intent">
              <dl className="m-0 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                <Field label={t("billing.dossier.fields.reference")}>
                  <span className="select-all font-mono">{data.intent.publicRef}</span>
                </Field>
                <Field label={t("billing.dossier.fields.state")}>
                  <span className="inline-flex flex-wrap items-center gap-1">
                    <Badge tone={data.intent.state === "paid" ? "accent" : "neutral"}>
                      {data.intent.state}
                    </Badge>
                    {data.intent.isSandbox ? (
                      <Badge tone="warning">{t("billing.intents.sandboxBadge")}</Badge>
                    ) : null}
                  </span>
                </Field>
                <Field label={t("billing.dossier.fields.product")}>
                  {data.intent.planSongs === null || data.intent.planDays === null
                    ? data.intent.product
                    : `${data.intent.product} · ${t("billing.intents.planShape", {
                        songs: data.intent.planSongs,
                        days: data.intent.planDays,
                      })}`}
                </Field>
                <Field label={t("billing.dossier.fields.amount")}>
                  {(() => {
                    const amount = money(data.intent.amountMinor, data.intent.currency);
                    return `${amount.value} ${amount.unit}`;
                  })()}
                </Field>
                <Field label={t("billing.dossier.fields.buyer")}>
                  {/* Erased and masked are two different facts. Never a blank, never an error,
                      and never a fraud badge: the money columns survive `/forget` by design and
                      the buyer does not. */}
                  {data.intent.isBuyerErased ? (
                    <Badge tone="muted">
                      <span data-testid="dossier-buyer-erased">
                        {t("billing.intents.buyerErased")}
                      </span>
                    </Badge>
                  ) : (
                    <span className="font-mono">{data.intent.telegramUserIdMasked ?? EM_DASH}</span>
                  )}
                </Field>
                <Field label={t("billing.dossier.fields.merchant")}>
                  <span className="font-mono">{data.intent.merchantId}</span>
                </Field>
                <Field label={t("billing.dossier.fields.opened")}>
                  <Instant at={data.intent.createdAt} />
                </Field>
                <Field label={t("billing.dossier.fields.validUntil")}>
                  <Instant at={data.intent.validUntil} />
                </Field>
                <Field label={t("billing.dossier.fields.settled")}>
                  {data.intent.settledAt === null ? (
                    t("billing.intents.notSettled")
                  ) : (
                    <Instant at={data.intent.settledAt} />
                  )}
                </Field>
                <Field label={t("billing.dossier.fields.settleNote")}>
                  {data.intent.settleSource === null
                    ? EM_DASH
                    : data.intent.settleSource === "operator"
                      ? t("billing.intents.settledByOperator")
                      : t("billing.intents.settledByRail")}
                </Field>
                <Field label={t("billing.dossier.fields.notified")}>
                  {data.intent.notifiedAt === null ? (
                    EM_DASH
                  ) : (
                    <Instant at={data.intent.notifiedAt} />
                  )}
                </Field>
              </dl>
            </Panel>

            <Panel title={t("billing.dossier.transactionsPanel")} testId="dossier-transactions">
              <DataTable
                caption={t("billing.dossier.transactionsPanel")}
                columns={transactionColumns}
                rows={data.transactions}
                getRowKey={(row) => row.paymeTransactionId}
                skeletonRows={1}
                emptyMessage={<EmptyState title={t("billing.dossier.transactionsNone")} />}
              />
            </Panel>

            <Panel title={t("billing.dossier.receiptPanel")} testId="dossier-receipt">
              {data.receipt === null ? (
                <EmptyState title={t("billing.dossier.receiptNone")} />
              ) : (
                <dl className="m-0 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                  <Field label={t("billing.dossier.fields.source")}>
                    <span className="font-mono">{data.receipt.source}</span>
                  </Field>
                  <Field label={t("billing.dossier.fields.amount")}>
                    {(() => {
                      const amount = money(data.receipt.amountMinor, data.receipt.currency);
                      return `${amount.value} ${amount.unit}`;
                    })()}
                  </Field>
                  <Field label={t("billing.dossier.fields.provider")}>{data.receipt.provider}</Field>
                  <Field label={t("billing.dossier.fields.cabinetReference")}>
                    <span className="select-all font-mono">{data.receipt.reference ?? EM_DASH}</span>
                  </Field>
                  <Field label={t("billing.dossier.fields.creditsGranted")}>
                    {data.receipt.creditsGranted ?? EM_DASH}
                  </Field>
                  <Field label={t("billing.dossier.fields.songsIncluded")}>
                    {data.receipt.songsIncluded ?? EM_DASH}
                  </Field>
                  <Field label={t("billing.dossier.fields.songsUsed")}>
                    {data.receipt.songsUsed ?? EM_DASH}
                  </Field>
                  <Field label={t("billing.dossier.fields.planEndsAt")}>
                    {data.receipt.planEndsAt === null ? (
                      EM_DASH
                    ) : (
                      <Instant at={data.receipt.planEndsAt} />
                    )}
                  </Field>
                </dl>
              )}
            </Panel>

            <Panel title={t("billing.dossier.ledgerPanel")} testId="dossier-ledger">
              {data.ledger.length === 0 ? (
                <EmptyState title={t("billing.dossier.ledgerNone")} />
              ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {data.ledger.map((entry) => (
                    <li
                      key={`${entry.kind}:${entry.createdAt}`}
                      className="flex flex-wrap items-baseline gap-2 text-[12px] leading-[16.392px] text-ink-800"
                    >
                      <Badge tone="neutral">{entry.kind}</Badge>
                      {/* Signed, always: the ledger is append-only and a magnitude with no sign
                          would make a debit indistinguishable from the grant that funded it. */}
                      <span className="tabular-nums">
                        {entry.delta > 0 ? `+${String(entry.delta)}` : String(entry.delta)}
                      </span>
                      <span className="text-ink-500">{entry.reason}</span>
                      <span className="text-ink-400">{entry.actor ?? EM_DASH}</span>
                      <Instant at={entry.createdAt} className="text-ink-400" />
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title={t("billing.dossier.callsPanel")} testId="dossier-calls">
              <DataTable
                caption={t("billing.dossier.callsPanel")}
                columns={callColumns}
                rows={data.calls}
                getRowKey={(row) => row.id}
                skeletonRows={1}
                emptyMessage={
                  /* Purged, not absent. The 90-day journal ages out under a paid payment that
                     is never purged, and there are no foreign keys between the two tables — so
                     an old payment with no calls is ORDINARY and must not read as "Payme never
                     called us", which on a live rail means "settled by hand". */
                  isBeyondRpcRetention(data.intent.createdAt, now) ? (
                    <EmptyState title={t("billing.dossier.callsPurged")} />
                  ) : (
                    <EmptyState title={t("billing.dossier.callsNever")} />
                  )
                }
              />
              <p className="m-0 mt-2 text-[11px] leading-[1.45] text-ink-400">
                {t("billing.calls.peerIpNote")}
              </p>
            </Panel>

            {/* Always rendered — see the module header. A hidden panel reads as a failed load. */}
            <Panel title={t("billing.dossier.chainStopPanel")} testId="dossier-chain-stop">
              {data.chainStop.kind === "single_song" ? (
                <p className="m-0 max-w-[80ch] text-[12px] leading-[16.392px] text-ink-500">
                  {t("billing.dossier.chainStopSingle")}
                </p>
              ) : data.chainStop.songsUsed === null || data.chainStop.songsIncluded === null ? (
                <p className="m-0 max-w-[80ch] text-[12px] leading-[16.392px] text-ink-500">
                  {t("billing.dossier.chainStopPlanUnknown")}
                </p>
              ) : (
                <p className="m-0 max-w-[80ch] text-[12px] leading-[16.392px] text-ink-800">
                  {t("billing.dossier.chainStopPlan", {
                    used: data.chainStop.songsUsed,
                    included: data.chainStop.songsIncluded,
                  })}
                </p>
              )}
            </Panel>

            <SettleByHandCard
              command={data.settleCommand}
              cabinetReference={data.receipt?.reference ?? null}
            />

            <NotifyDialog
              isOpen={isNotifyOpen}
              intentId={data.intent.intentId}
              onClose={() => {
                setIsNotifyOpen(false);
              }}
              onDone={(result) => {
                setEnqueued(result);
              }}
            />
          </>
        )}
      </div>
    </main>
  );
}
