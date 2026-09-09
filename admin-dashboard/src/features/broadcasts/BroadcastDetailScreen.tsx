/**
 * `/broadcasts/:broadcastId` — one campaign: who it was pointed at, what it says, how far it got.
 *
 * ## The audience is history, and is drawn as history
 *
 * `segment` on this response is a STORED document, not a filter to re-run. It is rendered as the
 * same chips the directory draws — one per leaf rule, each carrying its group's connective — but
 * with no remove button on any of them, because there is nothing here that editing it could do:
 * a campaign's audience was frozen at composition, and changing who hears a message is a new
 * campaign. Three states, never collapsed into one: a readable document, a document this build
 * cannot parse (`isSegmentReadable: false` — history does not re-validate), and a document with
 * no rules at all, which is EVERY account and is said in those words.
 *
 * ## Both counts of the funnel, side by side
 *
 * `broadcast.progress` is the worker's rollup; `countedProgress` is the same nine numbers
 * recounted from the recipient rows. They differ exactly while a send is being watched — the
 * rollup lags the ledger by a chunk — and showing one would mean picking which of two true
 * answers to hide. `unknownCount` gets its own tile at both counts and is never added to
 * `failedCount`: a killed job left those rows claimed, they are never retried, and the message
 * may well have arrived.
 *
 * ## The audience size, the rows written, and the messages sent are three numbers
 *
 * `audienceSize` is what the segment counted at composition. `recipientCount` is how many rows
 * the expansion has written. `sentCount` is how many messages Telegram accepted. A screen that
 * showed one bar against "the audience" would sit at a third while the send was in fact
 * complete, so the bar is settled rows over rows WRITTEN and the other two numbers are stated.
 *
 * ## No Telegram id in the ledger, at any role
 *
 * `BroadcastRecipientView` carries `telegramUserIdMasked` and there is no reveal that would
 * produce more. A `null` there is not masking — `/forget` nulled the column — so the row renders
 * as erased rather than as an empty cell, because the row itself is the evidence that a message
 * was sent to an account this database no longer holds.
 *
 * ## Polling stops on its own
 *
 * `useBroadcast` re-reads at `BROADCAST_POLL_MS` while the campaign is expanding, ready, sending
 * or paused, and stops the moment it is terminal — computed from the query's own data, so this
 * screen neither starts a timer nor has to remember to clear one. The ledger polls on the same
 * clock, told by the campaign's state, because a page of recipients cannot tell "still pending"
 * from "finished, and this is the final answer".
 */

import { ArrowLeft } from "lucide-react";
import { useMemo, useState, type JSX, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import {
  BROADCAST_RECIPIENT_STATE_VALUES,
  broadcastBodyLimit,
  type BroadcastBodyView,
  type BroadcastDetailView,
  type BroadcastProgressView,
  type BroadcastRecipientState,
  type BroadcastRecipientView,
  type BroadcastRecipientsFilters,
} from "@/api/broadcasts";
import { CLIENT_ERROR_CODES } from "@/api/client";
import { DEFAULT_PAGE_LIMIT, nextCursorOf, type PageRequest } from "@/api/pagination";
import { segmentFieldIndex, type SegmentFieldView } from "@/api/segments";
import { PATH } from "@/app/paths";
import { Badge } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { Skeleton } from "@/components/Skeleton";
import { buildSegmentChips, useSegmentFields } from "@/components/SegmentBuilder";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import {
  BROADCAST_KIND_HINT_KEY,
  BROADCAST_KIND_LABEL_KEY,
  BROADCAST_STATE_HINT_KEY,
  BROADCAST_STATE_LABEL_KEY,
  BROADCAST_STATE_TONE,
  RECIPIENT_STATE_LABEL_KEY,
  RECIPIENT_STATE_TONE,
  canCancelCampaign,
  canPauseCampaign,
  canResumeCampaign,
  canSendCampaign,
  formatAbsolute,
  formatCount,
  formatRelative,
  formatTotal,
  noteFor,
  type Translate,
} from "@/features/broadcasts/broadcastFormat";
import {
  CampaignActionDialog,
  type CampaignAction,
} from "@/features/broadcasts/CampaignActionDialog";
import { SendCampaignDialog } from "@/features/broadcasts/SendCampaignDialog";
import {
  isBroadcastInFlight,
  useBroadcast,
  useBroadcastRecipients,
} from "@/features/broadcasts/useBroadcasts";
import { EnumToggleGroup } from "@/features/users/filterControls";
import { Fact, FactGrid, Panel } from "@/features/users/detailKit";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import { useCanWriteBroadcasts } from "@/lib/rbac";
import { useSessionGuard } from "@/state/useSessionGuard";

/** Which modal is open. `null` is the screen itself; only one is ever open at a time. */
type OpenDialog = "send" | CampaignAction | null;

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

export function BroadcastDetailScreen(): JSX.Element {
  const { t, locale } = useI18n();
  const params = useParams<{ readonly broadcastId: string }>();
  const broadcastId = params.broadcastId ?? null;
  const canWrite = useCanWriteBroadcasts();
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null);

  const detail = useBroadcast(broadcastId);
  const failure =
    detail.error !== null && detail.error.code !== CLIENT_ERROR_CODES.aborted ? detail.error : null;
  useSessionGuard([failure]);

  const view = detail.data ?? null;
  const broadcast = view?.broadcast ?? null;
  const note =
    failure === null ? null : noteFor(failure, view !== null, t, t("broadcasts.subjectOne"));

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Link
          to={PATH.broadcasts}
          className={cn(
            "inline-flex w-fit items-center gap-1 rounded text-[12px] font-semibold text-ink-500",
            "transition-colors hover:text-ink-900",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
          )}
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
          {t("broadcasts.detail.backToList")}
        </Link>

        <Toolbar
          title={broadcast?.title ?? t("broadcasts.detail.loading")}
          subtitle={
            broadcast === null ? undefined : (
              <span className="flex flex-wrap items-center gap-2">
                <Badge
                  tone={BROADCAST_STATE_TONE[broadcast.state]}
                  title={t(BROADCAST_STATE_HINT_KEY[broadcast.state])}
                >
                  {t(BROADCAST_STATE_LABEL_KEY[broadcast.state])}
                </Badge>
                <Badge tone="muted" title={t(BROADCAST_KIND_HINT_KEY[broadcast.kind])}>
                  {t(BROADCAST_KIND_LABEL_KEY[broadcast.kind])}
                </Badge>
              </span>
            )
          }
          actions={
            broadcast === null ? undefined : canWrite ? (
              <>
                {canSendCampaign(broadcast) ? (
                  <ToolbarButton
                    variant="primary"
                    ariaLabel={t("broadcasts.actions.sendAria")}
                    onClick={() => {
                      setOpenDialog("send");
                    }}
                  >
                    {t("broadcasts.actions.send")}
                  </ToolbarButton>
                ) : null}
                {canPauseCampaign(broadcast) ? (
                  <ToolbarButton
                    variant="secondary"
                    onClick={() => {
                      setOpenDialog("pause");
                    }}
                  >
                    {t("broadcasts.actions.pause")}
                  </ToolbarButton>
                ) : null}
                {canResumeCampaign(broadcast) ? (
                  <ToolbarButton
                    variant="primary"
                    onClick={() => {
                      setOpenDialog("resume");
                    }}
                  >
                    {t("broadcasts.actions.resume")}
                  </ToolbarButton>
                ) : null}
                {canCancelCampaign(broadcast) ? (
                  <ToolbarButton
                    variant="secondary"
                    onClick={() => {
                      setOpenDialog("cancel");
                    }}
                  >
                    {t("broadcasts.actions.cancel")}
                  </ToolbarButton>
                ) : null}
              </>
            ) : (
              /* Not a disabled button: a press would be a 403 and a `permission.denied` row
                 against somebody who did nothing wrong. The reason is stated instead. */
              <p className="m-0 max-w-[36ch] text-[12px] leading-4 text-ink-400">
                {t("broadcasts.actions.readOnly")}
              </p>
            )
          }
        />

        {note === null || failure === null ? null : (
          <ErrorNote
            tone={note.tone}
            title={note.title}
            message={note.message}
            hint={`${failure.endpoint} · ${failure.correlationId ?? t("errors.query.noCorrelationId")}`}
            onRetry={() => {
              void detail.refetch();
            }}
            isRetrying={detail.isFetching}
            retryable={note.canRetry}
          />
        )}

        {view === null ? (
          failure === null ? (
            <LoadingPanels />
          ) : null
        ) : (
          <>
            <AudiencePanel view={view} t={t} locale={locale} />
            <MessagePanel view={view} t={t} />
            <DeliveryPanel view={view} t={t} />
            <RecordPanel view={view} t={t} />
            <RecipientsPanel
              broadcastId={view.broadcast.id}
              isInFlight={isBroadcastInFlight(view.broadcast)}
              t={t}
            />
          </>
        )}
      </div>

      {broadcast === null ? null : (
        <>
          <SendCampaignDialog
            isOpen={openDialog === "send"}
            onClose={() => {
              setOpenDialog(null);
            }}
            broadcast={broadcast}
          />
          {openDialog === "pause" || openDialog === "resume" || openDialog === "cancel" ? (
            <CampaignActionDialog
              isOpen
              onClose={() => {
                setOpenDialog(null);
              }}
              action={openDialog}
              broadcast={broadcast}
            />
          ) : null}
        </>
      )}
    </main>
  );
}

/** The card shapes, at their real heights, so nothing jumps when the campaign lands. */
function LoadingPanels(): JSX.Element {
  return (
    <div aria-busy className="flex flex-col gap-4">
      <Skeleton className="h-40 w-full rounded-panel" />
      <Skeleton className="h-56 w-full rounded-panel" />
      <Skeleton className="h-40 w-full rounded-panel" />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Audience                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * The frozen audience, as chips with no remove button on any of them.
 *
 * `buildSegmentChips` composes the same phrases the directory's chip row uses — including a
 * nested rule's own group connective, without which a chip lifted out of an `any` group reads as
 * one more thing EVERY account must match — and its `onChange` is never called from here,
 * because there is no edit this screen could apply. That is why they are drawn as badges rather
 * than through `<FilterChips>`: an X on a frozen audience would be a control that either does
 * nothing or lies about what it did.
 */
function AudiencePanel({
  view,
  t,
  locale,
}: {
  readonly view: BroadcastDetailView;
  readonly t: Translate;
  readonly locale: string;
}): JSX.Element {
  const registry = useSegmentFields();
  const fieldIndex = useMemo<ReadonlyMap<string, SegmentFieldView>>(
    () =>
      registry.data === undefined
        ? new Map<string, SegmentFieldView>()
        : segmentFieldIndex(registry.data),
    [registry.data],
  );

  const chips = useMemo(
    () =>
      view.segment === null
        ? []
        : buildSegmentChips({
            segment: view.segment,
            fields: fieldIndex,
            t,
            locale,
            // Never called: nothing on this screen may edit a campaign's audience.
            onChange: () => undefined,
          }),
    [fieldIndex, locale, t, view.segment],
  );

  const { audienceSize, recipientCount, isAudienceComplete } = view.broadcast.progress;

  return (
    <Panel
      title={t("broadcasts.detail.headingAudience")}
      caption={t("broadcasts.detail.captionAudience")}
    >
      <FactGrid>
        <Fact
          label={t("broadcasts.detail.counters.audience")}
          hint={t("broadcasts.detail.countersHint.audience")}
        >
          {t("broadcasts.audience.size", { count: formatCount(audienceSize) })}
        </Fact>
        <Fact
          label={t("broadcasts.detail.counters.written")}
          hint={t("broadcasts.detail.countersHint.written")}
        >
          {formatCount(recipientCount)}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.segmentHash")}>
          <span className="font-mono text-[12px] leading-4 tracking-[-0.2px] break-all">
            {view.broadcast.segmentHash}
          </span>
        </Fact>
      </FactGrid>

      <p className="m-0 max-w-[80ch] text-[12px] leading-[1.4] text-ink-400">
        {t("broadcasts.audience.frozenAt", {
          at: formatAbsolute(view.broadcast.audienceEvaluatedAt),
        })}{" "}
        {t("broadcasts.audience.frozenNote")}
      </p>

      {isAudienceComplete ? null : (
        <p className="m-0 text-[12px] leading-[1.4] text-warn-deep">
          {t("broadcasts.audience.incomplete")}
        </p>
      )}

      {!view.isSegmentReadable ? (
        <p className="m-0 max-w-[80ch] text-[12px] leading-[1.4] text-ink-400">
          {t("broadcasts.audience.unreadable")}
        </p>
      ) : view.segment === null ? (
        <p className="m-0 text-[12px] leading-[1.4] text-ink-400">
          {t("broadcasts.audience.missing")}
        </p>
      ) : chips.length === 0 ? (
        /* An empty document is EVERYONE, and the one reading that must never be "nothing
           selected" — this campaign went to every account the eligibility rule allowed. */
        <p className="m-0 max-w-[80ch] text-[12px] leading-[1.4] text-warn-deep">
          {t("broadcasts.audience.everyone")}
        </p>
      ) : (
        <div role="group" aria-label={t("broadcasts.audience.chipsLabel")} className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <Badge key={chip.id} tone="accent">
              <span className="font-semibold">{chip.field}:</span> {chip.value}
            </Badge>
          ))}
        </div>
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* Message                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * One card per language, showing `renderedText` — the exact argument the sender hands Telegram.
 *
 * As TEXT, never as markup. The string carries the allowlisted tags the operator typed, and a
 * panel that parsed them would be showing a browser's reading of the message rather than the
 * message; it would also be injecting a stored string into this document, which is the one thing
 * a console that renders operator-composed content must never do.
 */
function MessagePanel({
  view,
  t,
}: {
  readonly view: BroadcastDetailView;
  readonly t: Translate;
}): JSX.Element {
  return (
    <Panel
      title={t("broadcasts.detail.headingMessage")}
      caption={t("broadcasts.detail.captionMessage")}
    >
      {view.bodies.length === 0 ? (
        <p className="m-0 text-[12px] leading-[1.4] text-ink-400">{t("broadcasts.detail.body.none")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {view.bodies.map((body) => (
            <BodyCard key={body.language} body={body} t={t} />
          ))}
        </div>
      )}
    </Panel>
  );
}

function BodyCard({
  body,
  t,
}: {
  readonly body: BroadcastBodyView;
  readonly t: Translate;
}): JSX.Element {
  const limit = broadcastBodyLimit(body.hasMedia);
  const isOverLimit = body.renderedLength > limit;

  return (
    <section
      aria-label={`${t("broadcasts.detail.body.language")}: ${t(LANGUAGE_LABEL_KEY[body.language])}`}
      className="flex flex-col gap-2 rounded-card border border-stroke bg-bg p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{t(LANGUAGE_LABEL_KEY[body.language])}</Badge>
        <span className={cn("text-[12px] leading-4", isOverLimit ? "text-required-deep" : "text-ink-400")}>
          {t("broadcasts.detail.body.renderedLength", {
            length: formatCount(body.renderedLength),
            limit: formatCount(limit),
          })}
        </span>
        {isOverLimit ? (
          <span role="alert" className="text-[12px] leading-4 text-required-deep">
            {t("broadcasts.detail.body.overLimit")}
          </span>
        ) : null}
      </div>

      <p className="m-0 text-[12px] font-semibold leading-4 text-ink-400">
        {t("broadcasts.detail.body.asSent")}
      </p>
      {/* `whitespace-pre-wrap` because the line breaks the operator typed are part of the
          message, and `break-words` because a pasted URL must not widen the page. */}
      <p className="m-0 whitespace-pre-wrap break-words text-[12px] leading-[1.5] text-ink-900">
        {body.renderedText}
      </p>

      <div className="flex flex-wrap items-center gap-3 text-[12px] leading-4 text-ink-400">
        <span>
          {body.hasMedia
            ? `${t("broadcasts.detail.body.image")} — ${
                body.isMediaCached
                  ? t("broadcasts.detail.body.imageCached")
                  : t("broadcasts.detail.body.imageNotCached")
              }`
            : t("broadcasts.detail.body.noImage")}
        </span>
        <span className="break-all">
          {body.buttonLabel !== null && body.buttonUrl !== null
            ? t("broadcasts.detail.body.button", {
                label: body.buttonLabel,
                url: body.buttonUrl,
              })
            : t("broadcasts.detail.body.noButton")}
        </span>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Delivery                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Every counter on the funnel is a number; `isAudienceComplete` is the one field that is not,
 * and excluding it by name is what lets these cells be read without a cast.
 */
type CounterKey = Exclude<keyof BroadcastProgressView, "isAudienceComplete">;

/** The numbers, in the order the funnel runs, with the label and the caveat each one needs. */
const COUNTERS: readonly {
  readonly key: CounterKey;
  readonly label: TranslationPath;
  readonly hint: TranslationPath;
}[] = [
  {
    key: "unsettledCount",
    label: "broadcasts.detail.counters.unsettled",
    hint: "broadcasts.detail.countersHint.unsettled",
  },
  {
    key: "sentCount",
    label: "broadcasts.detail.counters.sent",
    hint: "broadcasts.detail.countersHint.sent",
  },
  {
    key: "failedCount",
    label: "broadcasts.detail.counters.failed",
    hint: "broadcasts.detail.countersHint.failed",
  },
  {
    key: "skippedCount",
    label: "broadcasts.detail.counters.skipped",
    hint: "broadcasts.detail.countersHint.skipped",
  },
  {
    key: "undeliverableCount",
    label: "broadcasts.detail.counters.undeliverable",
    hint: "broadcasts.detail.countersHint.undeliverable",
  },
  {
    key: "unknownCount",
    label: "broadcasts.detail.counters.unknown",
    hint: "broadcasts.detail.countersHint.unknown",
  },
  {
    key: "settledCount",
    label: "broadcasts.detail.counters.settled",
    hint: "broadcasts.detail.countersHint.settled",
  },
];

/**
 * Two counts of one funnel, as a table rather than as two rows of tiles.
 *
 * A table is what makes the pair comparable at a glance — the whole reason both are published is
 * that an operator can see the rollup lagging the ledger during a send — and it gives every
 * number a row header, which a grid of tiles cannot.
 */
function DeliveryPanel({
  view,
  t,
}: {
  readonly view: BroadcastDetailView;
  readonly t: Translate;
}): JSX.Element {
  const rolled = view.broadcast.progress;
  const counted = view.countedProgress;

  return (
    <Panel
      title={t("broadcasts.detail.headingDelivery")}
      caption={t("broadcasts.detail.captionDelivery")}
    >
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              <th scope="col" className="px-2 pb-2 text-[12px] font-normal text-ink-300">
                {t("broadcasts.detail.headingDelivery")}
              </th>
              <th scope="col" className="px-2 pb-2 text-right text-[12px] font-normal text-ink-300">
                {t("broadcasts.detail.rolledUp")}
              </th>
              <th scope="col" className="px-2 pb-2 text-right text-[12px] font-normal text-ink-300">
                {t("broadcasts.detail.recounted")}
              </th>
            </tr>
          </thead>
          <tbody>
            {COUNTERS.map((counter) => (
              <tr key={counter.key} className="border-t border-stroke">
                <th
                  scope="row"
                  title={t(counter.hint)}
                  className="px-2 py-2 text-[12px] font-medium text-ink-800"
                >
                  {t(counter.label)}
                </th>
                <td className="px-2 py-2 text-right text-[12px] font-semibold text-ink-900">
                  {formatCount(rolled[counter.key])}
                </td>
                <td className="px-2 py-2 text-right text-[12px] font-semibold text-ink-900">
                  {formatCount(counted[counter.key])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* Record                                                                      */
/* -------------------------------------------------------------------------- */

function RecordPanel({
  view,
  t,
}: {
  readonly view: BroadcastDetailView;
  readonly t: Translate;
}): JSX.Element {
  const b = view.broadcast;

  return (
    <Panel title={t("broadcasts.detail.headingRecord")}>
      <FactGrid>
        <Fact label={t("broadcasts.detail.facts.createdBy")}>
          {b.createdByUsername ?? t("broadcasts.detail.facts.unknownActor")}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.createdAt")}>
          <Instant iso={b.createdAt} t={t} />
        </Fact>
        <Fact label={t("broadcasts.detail.facts.scheduledFor")}>
          {b.scheduledFor === null ? (
            <Absent>{t("broadcasts.detail.facts.notScheduled")}</Absent>
          ) : (
            <Instant iso={b.scheduledFor} t={t} />
          )}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.scheduledBy")}>
          {b.scheduledByUsername ?? <Absent>{t("broadcasts.detail.facts.noReason")}</Absent>}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.startedAt")}>
          {b.startedAt === null ? (
            <Absent>{t("broadcasts.detail.facts.notStarted")}</Absent>
          ) : (
            <Instant iso={b.startedAt} t={t} />
          )}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.finishedAt")}>
          {b.finishedAt === null ? (
            <Absent>{t("broadcasts.detail.facts.notFinished")}</Absent>
          ) : (
            <Instant iso={b.finishedAt} t={t} />
          )}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.reasonCode")}>
          {b.reasonCode ?? <Absent>{t("broadcasts.detail.facts.noReason")}</Absent>}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.reasonRef")}>
          {b.reasonRef ?? <Absent>{t("broadcasts.detail.facts.noReason")}</Absent>}
        </Fact>
        <Fact label={t("broadcasts.detail.facts.errorCode")}>
          {b.errorCode === null ? (
            <Absent>{t("broadcasts.detail.facts.noError")}</Absent>
          ) : (
            <span className="text-required-deep">{b.errorCode}</span>
          )}
        </Fact>
      </FactGrid>
    </Panel>
  );
}

function Absent({ children }: { readonly children: ReactNode }): JSX.Element {
  return <span className="text-[12px] font-normal text-ink-400">{children}</span>;
}

/** Relative for scanning, absolute in the `title` for quoting. */
function Instant({ iso, t }: { readonly iso: string; readonly t: Translate }): JSX.Element {
  return (
    <span className="whitespace-nowrap" title={formatAbsolute(iso)}>
      {formatRelative(iso, t) ?? iso}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Recipients                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The ledger: one masked row per account, filtered by outcome, walked by cursor.
 *
 * The walk is component state rather than the URL, and deliberately: this table sits beside a
 * campaign that is already addressed by its path, and an opaque keyset key in a link somebody
 * pastes into a ticket would be either missing or stale by the time it was opened.
 */
function RecipientsPanel({
  broadcastId,
  isInFlight,
  t,
}: {
  readonly broadcastId: string;
  readonly isInFlight: boolean;
  readonly t: Translate;
}): JSX.Element {
  const [states, setStates] = useState<readonly BroadcastRecipientState[]>([]);
  /* The stops already visited, newest last. Reset whenever the filter changes: a cursor is a
     position in ONE filtered set, and carrying it into another asks for rows nobody counted. */
  const [trail, setTrail] = useState<readonly (string | null)[]>([null]);

  const cursor = trail[trail.length - 1] ?? null;
  const pageIndex = trail.length - 1;

  const filters = useMemo<BroadcastRecipientsFilters>(
    () => ({ withTotal: true, state: states }),
    [states],
  );
  const page = useMemo<PageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor }),
    [cursor],
  );

  const recipients = useBroadcastRecipients(broadcastId, filters, page, isInFlight);
  const failure =
    recipients.error !== null && recipients.error.code !== CLIENT_ERROR_CODES.aborted
      ? recipients.error
      : null;

  const items = recipients.data?.items ?? [];
  const meta = recipients.data?.meta ?? null;
  const nextCursor = recipients.data === undefined ? null : nextCursorOf(recipients.data);

  const columns = useMemo<readonly Column<BroadcastRecipientView>[]>(
    () => [
      {
        key: "recipient",
        header: t("broadcasts.detail.recipients.columnRecipient"),
        width: "14rem",
        render: (row) =>
          row.telegramUserIdMasked === null ? (
            /* Not masking and not a bug: `/forget` nulled the column. The row survives as the
               evidence that a message went to an account this database no longer holds. */
            <span className={CELL_SECONDARY_CLASS}>
              {t("broadcasts.detail.recipients.erased")}
            </span>
          ) : (
            <span className="font-mono">{row.telegramUserIdMasked}</span>
          ),
      },
      {
        key: "language",
        header: t("broadcasts.detail.recipients.columnLanguage"),
        width: "9rem",
        render: (row) => (
          <span className="text-ink-500">{t(LANGUAGE_LABEL_KEY[row.language])}</span>
        ),
      },
      {
        key: "state",
        header: t("broadcasts.detail.recipients.columnState"),
        width: "12rem",
        render: (row) => (
          <Badge tone={RECIPIENT_STATE_TONE[row.state]}>
            {t(RECIPIENT_STATE_LABEL_KEY[row.state])}
          </Badge>
        ),
      },
      {
        key: "attempts",
        header: t("broadcasts.detail.recipients.columnAttempts"),
        width: "6rem",
        align: "right",
        render: (row) => formatCount(row.attempts),
      },
      {
        key: "errorCode",
        header: t("broadcasts.detail.recipients.columnError"),
        width: "12rem",
        render: (row) =>
          row.errorCode === null ? (
            <span className={CELL_SECONDARY_CLASS}>
              {t("broadcasts.detail.recipients.noError")}
            </span>
          ) : (
            <span className="font-mono text-[12px]">{row.errorCode}</span>
          ),
      },
      {
        key: "settledAt",
        header: t("broadcasts.detail.recipients.columnSettled"),
        width: "10rem",
        render: (row) =>
          row.settledAt === null ? (
            <span className={CELL_SECONDARY_CLASS}>
              {t("broadcasts.detail.recipients.notSettled")}
            </span>
          ) : (
            <span className={cn(CELL_SECONDARY_CLASS, "whitespace-nowrap")} title={formatAbsolute(row.settledAt)}>
              {formatRelative(row.settledAt, t) ?? row.settledAt}
            </span>
          ),
      },
    ],
    [t],
  );

  const total = meta?.total ?? null;
  const rangeLabel =
    items.length === 0
      ? states.length === 0
        ? t("broadcasts.range.none")
        : t("broadcasts.range.noneMatching")
      : t("broadcasts.range.numbered", {
          start: formatCount(pageIndex * DEFAULT_PAGE_LIMIT + 1),
          end: formatCount(pageIndex * DEFAULT_PAGE_LIMIT + items.length),
          total:
            total === null
              ? ""
              : t("broadcasts.range.ofTotal", {
                  total: formatTotal(total, meta?.isTotalExact ?? null, t),
                }),
        });

  const note =
    failure === null
      ? null
      : noteFor(failure, recipients.data !== undefined, t, t("broadcasts.subjectRecipients"));

  return (
    <Panel
      title={t("broadcasts.detail.headingRecipients")}
      caption={t("broadcasts.detail.captionRecipients")}
    >
      <EnumToggleGroup<BroadcastRecipientState>
        label={t("broadcasts.detail.recipients.filterState")}
        values={BROADCAST_RECIPIENT_STATE_VALUES}
        selected={states}
        onChange={(next) => {
          setStates(next);
          setTrail([null]);
        }}
        format={(member) => t(RECIPIENT_STATE_LABEL_KEY[member])}
        hint={t("broadcasts.detail.recipients.filterStateHint")}
      />

      {note === null || failure === null ? null : (
        <ErrorNote
          tone={note.tone}
          title={note.title}
          message={note.message}
          hint={`${failure.endpoint} · ${failure.correlationId ?? t("errors.query.noCorrelationId")}`}
          onRetry={() => {
            void recipients.refetch();
          }}
          isRetrying={recipients.isFetching}
          retryable={note.canRetry}
        />
      )}

      {recipients.data === undefined && failure !== null ? null : (
        <DataTable
          columns={columns}
          rows={items}
          getRowKey={(row) => row.id}
          isLoading={recipients.isPending}
          skeletonRows={8}
          caption={t("broadcasts.detail.recipients.tableCaption")}
          emptyMessage={
            <EmptyState
              title={
                states.length === 0
                  ? t("broadcasts.detail.recipients.emptyTitle")
                  : t("broadcasts.detail.recipients.emptyFilteredTitle")
              }
              message={
                states.length === 0
                  ? t("broadcasts.detail.recipients.emptyMessage")
                  : t("broadcasts.detail.recipients.emptyFilteredMessage")
              }
            />
          }
        />
      )}

      <p className="m-0 text-[12px] leading-[1.4] text-ink-400">
        {t("broadcasts.detail.recipients.noIdColumnNote")}
      </p>

      <CursorPager
        hasPrev={trail.length > 1}
        hasNext={nextCursor !== null}
        isFetching={recipients.isFetching}
        rangeLabel={rangeLabel}
        onPrev={
          trail.length > 1
            ? () => {
                setTrail((current) => current.slice(0, -1));
              }
            : undefined
        }
        onNext={
          nextCursor === null
            ? undefined
            : () => {
                setTrail((current) => [...current, nextCursor]);
              }
        }
      />
    </Panel>
  );
}
