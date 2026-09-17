/**
 * `/support/:ticketId` — one complaint: who wrote it, what they said, where it is, and every
 * thing that has happened to it since.
 *
 * ## This screen renders a person waiting for an answer, not a record
 *
 * Every other detail screen in this console describes something that happened to the business —
 * an order, a payment, a campaign — and is read after the fact. A ticket is somebody who is
 * still waiting, and the whole layout follows from that: their own words come before the
 * clocks, the timeline is a conversation read forwards rather than a table sorted newest-first,
 * and the four controls are the four things an operator can do ABOUT them rather than a
 * lifecycle taxonomy.
 *
 * ## Only legal moves are offered, and the server's list wins
 *
 * `allowedMovesFor` prefers `ticket.allowedTransitions` — computed per ticket from
 * `bayram.support.LEGAL_STATUS_MOVES` and already in the board's left-to-right order — and falls
 * back to `ticketFormat`'s copy of the same table. Rendering all four columns and discovering
 * which three are guaranteed refusals is how a console teaches an operator to ignore its own
 * errors. Three of the grammar's refusals look arbitrary until they are argued and this screen
 * must not work around any of them: nothing moves to itself, nothing returns to `new`, and
 * `resolved -> waiting` is not a move. The one exit from `resolved` is a REOPEN, and it is
 * labelled as one, because `resolvedAt` survives it and the ticket stays visibly a complaint
 * that came back.
 *
 * ## Every move names the status the screen was drawn in
 *
 * `expectedStatus` is captured when the move dialog opens and never recomputed, because the
 * handler's `UPDATE` names it in its `WHERE` clause and the rowcount is the lock. A `409` means
 * somebody moved the ticket first — almost always a staffer pressing `✋ Claim` or `✅ Resolve`
 * on the card in the Telegram support group, which is a different process — and it is rendered
 * as the status the server actually found, with the confirm button withdrawn. There is no
 * retry: the same bytes lose the same race, and the detail is re-read instead.
 *
 * ## A note and a reply are two dialogs, never one with a switch
 *
 * `TicketReplyBox.tsx` holds both and argues the separation at length. What this screen owes
 * them is that the two buttons are never adjacent look-alikes: the reply carries the primary
 * slot and the customer's language, the note sits beside it in the secondary tone.
 *
 * ## No step-up, and no polling
 *
 * `support.write` is a plain `W` cell, so there is no re-authentication dialog to drive and no
 * body to replay. And nothing here polls: a support screen is read for minutes at a time while
 * an answer is being written, and a header that re-ordered itself under a half-typed reply would
 * cost more than the freshness buys. The freshness signal is window focus plus the invalidation
 * every write performs — and, after a `409`, one explicit re-read.
 */

import { ArrowLeft } from "lucide-react";
import { useId, useMemo, useState, type JSX } from "react";
import { Link, useParams } from "react-router-dom";

import { CLIENT_ERROR_CODES } from "@/api/client";
import {
  MAX_TICKET_ASSIGNEE_CHARS,
  isAssignableUsername,
  ticketStatusConflictOf,
  type SupportTicketStatus,
  type SupportTicketView,
} from "@/api/support";
import { PATH, userDetailPath } from "@/app/paths";
import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import { Skeleton } from "@/components/Skeleton";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import {
  TICKET_SOURCE_HINT_KEY,
  TICKET_SOURCE_LABEL_KEY,
  TICKET_STATUS_EMOJI,
  TICKET_STATUS_HINT_KEY,
  TICKET_STATUS_LABEL_KEY,
  TICKET_STATUS_TONE,
  allowedMovesFor,
  formatAbsolute,
  formatCount,
  formatRelative,
  isGroupPostOwed,
  isReopenMove,
  isReopenedTicket,
  isUndescribedTicket,
  noteFor,
  type Translate,
} from "@/features/support/ticketFormat";
import {
  TicketNoteDialog,
  TicketReplyDialog,
} from "@/features/support/TicketReplyBox";
import { TicketTimeline } from "@/features/support/TicketTimeline";
import {
  useAssignSupportTicket,
  useMoveSupportTicket,
  useSupportTicket,
} from "@/features/support/useSupportTickets";
import { Fact, FactGrid, MONO_CLASS, Panel } from "@/features/users/detailKit";
import { useI18n } from "@/i18n";
import { failureOf, type AdminQueryError } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import { useCanWriteSupport } from "@/lib/rbac";
import { useAuthStore } from "@/state/auth";
import { useSessionGuard } from "@/state/useSessionGuard";

/**
 * Which dialog is open, and what it was opened ABOUT.
 *
 * A discriminated union rather than four booleans: only one is ever open, and the move and the
 * hand-over each carry a value chosen at the moment of the press — the column being moved to,
 * and the name to prefill. Keeping that value here is what lets both dialogs be unmounted on
 * close, so a draft cannot survive into the next ticket.
 */
type OpenDialog =
  | { readonly kind: "move"; readonly to: SupportTicketStatus }
  | { readonly kind: "assign"; readonly username: string }
  | { readonly kind: "reply" }
  | { readonly kind: "note" }
  | null;

const PROSE_CLASS =
  "m-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-400";

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

export function SupportTicketScreen(): JSX.Element {
  const { t } = useI18n();
  const params = useParams<{ readonly ticketId: string }>();
  const ticketId = params.ticketId ?? null;
  const canWrite = useCanWriteSupport();
  /* The signed-in operator's own name, for the one-press claim. It is a PREFILL and not a
     shortcut around the dialog: `assigned_admin_username` is denormalised with no foreign key,
     so whatever is written is what the queue's history will say for ever — and the operator
     should read it before it is recorded. */
  const username = useAuthStore((state) => state.account?.username ?? null);
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null);

  const detail = useSupportTicket(ticketId);
  const failure =
    detail.error !== null && detail.error.code !== CLIENT_ERROR_CODES.aborted
      ? detail.error
      : null;
  /* The first 401 on this read ends the tab. The shared guard, never a second copy: a screen
     that kept reading with a dead cookie would leave Reply and Move drawn and pressable. */
  useSessionGuard([failure]);

  const view = detail.data ?? null;
  const ticket = view?.ticket ?? null;
  const note =
    failure === null
      ? null
      : noteFor(failure, view !== null, t, t("support.subjectOne"));

  /**
   * The columns this ticket may be moved to, already labelled.
   *
   * `t` is a NEW CLOSURE per locale and is in the dependency array for that reason — omit it and
   * these buttons freeze in whichever language the screen first rendered in, which is the one
   * failure that survives a language switch and looks like a caching bug.
   */
  const moves = useMemo(() => {
    if (ticket === null) return [];
    return allowedMovesFor(ticket).map((to) => ({
      to,
      label: isReopenMove(ticket.status, to)
        ? t("support.actions.reopen")
        : to === "resolved"
          ? t("support.actions.resolve")
          : t("support.actions.moveTo", {
              status: t(TICKET_STATUS_LABEL_KEY[to]),
            }),
    }));
  }, [ticket, t]);

  const canClaim =
    username !== null &&
    isAssignableUsername(username) &&
    ticket?.assignedAdminUsername !== username;

  function close(): void {
    setOpenDialog(null);
  }

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Link
          to={PATH.support}
          className={cn(
            "inline-flex w-fit items-center gap-1 rounded text-[12px] font-semibold text-ink-500",
            "transition-colors hover:text-ink-900",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
          )}
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
          {t("support.backToBoard")}
        </Link>

        <Toolbar
          /* The public reference IS the title: it is the string the customer was given and
             quotes back down a phone line, and it is rendered verbatim — never case-folded,
             never prettified — because it is reproduced by READING the ticket id, not by
             computing an encoding. */
          title={ticket?.publicRef ?? t("common.loading")}
          subtitle={
            ticket === null ? undefined : (
              <span className="flex flex-wrap items-center gap-2">
                <Badge
                  tone={TICKET_STATUS_TONE[ticket.status]}
                  icon={TICKET_STATUS_EMOJI[ticket.status]}
                  title={t(TICKET_STATUS_HINT_KEY[ticket.status])}
                >
                  {t(TICKET_STATUS_LABEL_KEY[ticket.status])}
                </Badge>
                <Badge
                  tone="muted"
                  title={t(TICKET_SOURCE_HINT_KEY[ticket.source])}
                >
                  {t(TICKET_SOURCE_LABEL_KEY[ticket.source])}
                </Badge>
                {isReopenedTicket(ticket) ? (
                  /* Closed once, open again. `resolvedAt` is never cleared by a reopen, and the
                     pair is the whole signal — there is no notification surface anywhere in this
                     panel, so this badge is the only place it can be said. */
                  <Badge tone="warning" title={t("support.card.reopenedHint")}>
                    {t("support.card.reopened")}
                  </Badge>
                ) : null}
              </span>
            )
          }
          actions={
            ticket === null ? undefined : canWrite ? (
              <>
                <ToolbarButton
                  variant="primary"
                  onClick={() => {
                    setOpenDialog({ kind: "reply" });
                  }}
                >
                  {t("support.actions.reply")}
                </ToolbarButton>
                <ToolbarButton
                  variant="secondary"
                  onClick={() => {
                    setOpenDialog({ kind: "note" });
                  }}
                >
                  {t("support.actions.note")}
                </ToolbarButton>
                {/* `canClaim` is a const over `username !== null`, so the compiler carries that
                    narrowing in here and into the closure below — no second null check. */}
                {canClaim ? (
                  <ToolbarButton
                    variant="secondary"
                    onClick={() => {
                      setOpenDialog({ kind: "assign", username });
                    }}
                  >
                    {t("support.actions.claim")}
                  </ToolbarButton>
                ) : null}
                <ToolbarButton
                  variant="secondary"
                  onClick={() => {
                    setOpenDialog({ kind: "assign", username: "" });
                  }}
                >
                  {t("support.actions.assign")}
                </ToolbarButton>
              </>
            ) : (
              /* Not a row of disabled buttons: a press would be a 403 and a `permission.denied`
                 audit row against somebody who did nothing wrong. The reason is stated instead.
                 The sentence is this section's own rather than the shared
                 `errors.detail.roleCannotTitle`, which names no permission — a reader learns
                 from it that something is refused but not which of the four actions they are
                 missing, and naming it is the only reason to print a sentence here at all.
                 `broadcasts.actions.readOnly` is the model it is transcribed from. */
              <p className={cn("max-w-[36ch]", PROSE_CLASS)}>
                {t("support.actions.readOnly")}
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

        {view === null || ticket === null ? (
          failure === null ? (
            <LoadingPanels />
          ) : null
        ) : (
          <>
            <FactsPanel
              ticket={ticket}
              t={t}
              moves={canWrite ? moves : []}
              onMove={(to) => {
                setOpenDialog({ kind: "move", to });
              }}
            />
            <ComplaintPanel ticket={ticket} t={t} />
            <Panel
              title={t("support.timeline.title")}
              /* The rendered count, not `eventCount`: the timeline is unpaged, so the two are the
                 same number — and where they ever disagree, the honest one is what is on screen. */
              caption={t("support.card.events", {
                count: formatCount(view.events.length),
              })}
            >
              <TicketTimeline events={view.events} t={t} />
            </Panel>
          </>
        )}
      </div>

      {ticket === null || openDialog === null ? null : openDialog.kind ===
        "move" ? (
        <MoveTicketDialog
          ticket={ticket}
          to={openDialog.to}
          onClose={close}
          onConflict={() => {
            void detail.refetch();
          }}
        />
      ) : openDialog.kind === "assign" ? (
        <AssignTicketDialog
          ticket={ticket}
          initialUsername={openDialog.username}
          onClose={close}
        />
      ) : openDialog.kind === "reply" ? (
        <TicketReplyDialog isOpen onClose={close} ticket={ticket} />
      ) : (
        <TicketNoteDialog isOpen onClose={close} ticket={ticket} />
      )}
    </main>
  );
}

/** The panel shapes at their real heights, so nothing jumps when the ticket lands. */
function LoadingPanels(): JSX.Element {
  return (
    <div aria-busy className="flex flex-col gap-4">
      <Skeleton className="h-40 w-full rounded-panel" />
      <Skeleton className="h-32 w-full rounded-panel" />
      <Skeleton className="h-56 w-full rounded-panel" />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The facts, and the moves                                                    */
/* -------------------------------------------------------------------------- */

interface MoveOption {
  readonly to: SupportTicketStatus;
  readonly label: string;
}

/**
 * Who this is, where it is, and where it may go.
 *
 * Untitled on purpose: the toolbar above it already names the ticket, and a card headed
 * "Ticket" under a heading that is the reference would be the same word twice.
 */
function FactsPanel({
  ticket,
  t,
  moves,
  onMove,
}: {
  readonly ticket: SupportTicketView;
  readonly t: Translate;
  readonly moves: readonly MoveOption[];
  readonly onMove: (to: SupportTicketStatus) => void;
}): JSX.Element {
  return (
    <Panel>
      <FactGrid>
        <Fact label={t("support.card.reference")}>
          <span className={MONO_CLASS}>{ticket.publicRef}</span>
        </Fact>
        <Fact label={t("support.card.customer")}>
          {/* The MASK is what is printed; the raw id rides in the href, which is the route
              `/api/users/{id}` is addressed by. A ticket holds no name column at all, so this
              link is the only way from a complaint to the person who made it. */}
          <Link
            to={userDetailPath(ticket.telegramUserId)}
            className={cn(
              "rounded font-medium text-ink-900 underline decoration-stroke underline-offset-2",
              "transition-colors hover:decoration-ink-500",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
            )}
          >
            {ticket.telegramUserIdMasked}
          </Link>
        </Fact>
        <Fact label={t("support.card.order")}>
          {ticket.orderId === null ? (
            /* `null` on every `/support` ticket — roughly half of them — and not a defect: the
               command is typed from anywhere and carries no order. It is printed rather than
               linked because this console has no per-order route to link to. */
            <span className="text-ink-400">{t("support.card.noOrder")}</span>
          ) : (
            <span className={MONO_CLASS}>{ticket.orderId}</span>
          )}
        </Fact>
        <Fact
          label={t("support.card.language")}
          hint={t("support.filter.languageHint")}
        >
          {t(LANGUAGE_LABEL_KEY[ticket.language])}
        </Fact>
        <Fact label={t("support.card.opened")}>
          <Instant iso={ticket.createdAt} t={t} />
        </Fact>
        <Fact label={t("support.card.updated")}>
          <Instant iso={ticket.updatedAt} t={t} />
        </Fact>
        <Fact label={t("support.card.assignee")}>
          {ticket.assignedAdminUsername === null ? (
            <span className="text-ink-400">{t("support.card.unassigned")}</span>
          ) : (
            ticket.assignedAdminUsername
          )}
        </Fact>
        {ticket.resolvedAt === null ? null : (
          <Fact
            label={t("support.card.resolvedAt")}
            hint={t("support.card.reopenedHint")}
          >
            <Instant iso={ticket.resolvedAt} t={t} />
          </Fact>
        )}
      </FactGrid>

      <div className="flex flex-col gap-2">
        {ticket.isPostedToGroup ? (
          <p className={PROSE_CLASS}>{t("support.card.inGroup")}</p>
        ) : isGroupPostOwed(ticket) ? (
          <>
            {/* Still OWED, never lost. The customer has their reference either way, and this
                deployment may simply have no support group configured. */}
            <Badge tone="warning" title={t("support.card.notInGroupHint")}>
              {t("support.card.notInGroup")}
            </Badge>
            <p className={cn("max-w-[80ch]", PROSE_CLASS)}>
              {t("support.card.notInGroupHint")}
            </p>
          </>
        ) : null}
      </div>

      {moves.length === 0 ? null : (
        <div
          role="group"
          aria-label={t("support.actions.move")}
          className="flex flex-wrap items-center gap-2"
        >
          {moves.map((move) => (
            <ToolbarButton
              key={move.to}
              variant="secondary"
              onClick={() => {
                onMove(move.to);
              }}
            >
              {move.label}
            </ToolbarButton>
          ))}
        </div>
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* The complaint                                                               */
/* -------------------------------------------------------------------------- */

/**
 * The customer's own words, in full, as TEXT.
 *
 * This is the one wire in the panel that carries a customer's free prose unredacted, and it is
 * an argued exception rather than an oversight — they wrote it TO support, in answer to a prompt
 * asking them to describe a problem, and an operator who cannot read the complaint cannot answer
 * it. `api/support.ts` carries the argument in full.
 *
 * **A `null` body is never "hidden" and never "redacted".** It is a customer who tapped ⚠️ and
 * never typed, which `describedAt` says as a clock, and those rows are kept deliberately: they
 * are the only measure of how many people tried to tell us something and gave up.
 */
function ComplaintPanel({
  ticket,
  t,
}: {
  readonly ticket: SupportTicketView;
  readonly t: Translate;
}): JSX.Element {
  return (
    <Panel title={t("support.card.body")}>
      {ticket.body === null ? (
        <>
          <p className="m-0 text-[12px] font-semibold leading-4 text-ink-900">
            {t("support.card.noBody")}
          </p>
          {/* The two facts travel together in every real row; the hint is tied to the CLOCK
              rather than to the empty column, so a body that somehow arrived without one still
              renders its words above. */}
          {isUndescribedTicket(ticket) ? (
            <p className={cn("max-w-[80ch]", PROSE_CLASS)}>
              {t("support.card.noBodyHint")}
            </p>
          ) : null}
        </>
      ) : (
        /* `whitespace-pre-wrap` because the line breaks are part of what they wrote, and
           `break-words` because a pasted link must not widen the page. Never parsed as markup. */
        <p className="m-0 whitespace-pre-wrap break-words text-[12px] leading-[1.5] text-ink-900">
          {ticket.body}
        </p>
      )}
    </Panel>
  );
}

/** "3 minutes ago", with the exact instant in the title. The pair, never one of them. */
function Instant({
  iso,
  t,
}: {
  readonly iso: string;
  readonly t: Translate;
}): JSX.Element {
  return (
    <span title={formatAbsolute(iso)}>
      {formatRelative(iso, t) ?? formatAbsolute(iso)}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Moving the ticket                                                           */
/* -------------------------------------------------------------------------- */

/**
 * One move, confirmed — and the only place in this namespace that reads a `409`.
 *
 * `expectedStatus` is taken ONCE, when the dialog mounts, and is the status the screen was drawn
 * in at the moment of the press. Recomputing it from the ticket on every render would defeat the
 * whole mechanism: the re-read that follows a conflict would hand the retry the status the
 * server just reported, turning a refused lost-update into an accepted one.
 *
 * After a conflict the confirm is withdrawn rather than re-armed. The same bytes lose the same
 * race, and the honest next act is to read what the ticket now says — which is why the screen is
 * re-read behind this dialog and the operator chooses a move again from what is actually there.
 */
function MoveTicketDialog({
  ticket,
  to,
  onClose,
  onConflict,
}: {
  readonly ticket: SupportTicketView;
  readonly to: SupportTicketStatus;
  readonly onClose: () => void;
  readonly onConflict: () => void;
}): JSX.Element {
  const { t } = useI18n();
  const [expectedStatus] = useState<SupportTicketStatus>(ticket.status);
  const move = useMoveSupportTicket();
  const conflictStatus = ticketStatusConflictOf(failureOf(move.error));
  const isReopen = isReopenMove(expectedStatus, to);

  function confirm(): void {
    move.mutate(
      { ticketId: ticket.id, body: { expectedStatus, toStatus: to } },
      {
        onSuccess: () => {
          onClose();
        },
        onError: (error) => {
          /* A 409 is not a failure of this console: somebody moved the ticket first, almost
             always a staffer pressing a button on the card in the Telegram group. Re-read, so
             the header behind this dialog stops claiming a status the row no longer holds. */
          if (ticketStatusConflictOf(failureOf(error)) !== null) onConflict();
        },
      },
    );
  }

  return (
    <ConfirmDialog
      isOpen
      onClose={onClose}
      title={t("support.dialogs.move.title")}
      description={
        isReopen
          ? t("support.dialogs.move.reopenBody", {
              status: t(TICKET_STATUS_LABEL_KEY[to]),
            })
          : t("support.dialogs.move.body", {
              status: t(TICKET_STATUS_LABEL_KEY[to]),
            })
      }
      confirmLabel={t("support.dialogs.move.submit")}
      pendingLabel={t("support.dialogs.move.pending")}
      isPending={move.isPending}
      isConfirmDisabled={conflictStatus !== null}
      onConfirm={confirm}
      error={
        move.error === null ? undefined : conflictStatus !== null ? (
          <div className="flex flex-col gap-2">
            <ErrorNote
              tone="stale"
              title={t("support.notes.conflictTitle")}
              message={t("support.notes.conflictMessage")}
              retryable={false}
            />
            {/* The status the server actually found, in the board's own vocabulary. It is read
                a moment BEFORE the conditional UPDATE that refused, which is the honest thing to
                report rather than pretending to have raced it. */}
            <p className="m-0 flex flex-wrap items-center gap-2 text-[12px] leading-4 text-ink-500">
              {t("support.filter.status")}
              <Badge
                tone={TICKET_STATUS_TONE[conflictStatus]}
                icon={TICKET_STATUS_EMOJI[conflictStatus]}
                title={t(TICKET_STATUS_HINT_KEY[conflictStatus])}
              >
                {t(TICKET_STATUS_LABEL_KEY[conflictStatus])}
              </Badge>
            </p>
          </div>
        ) : (
          <MoveFailure error={move.error} />
        )
      }
    />
  );
}

/** Everything that is not the 409, in the words a failed read gets. Never retryable from here. */
function MoveFailure({
  error,
}: {
  readonly error: AdminQueryError;
}): JSX.Element {
  const { t } = useI18n();
  const note = noteFor(error, false, t, t("support.dialogs.move.title"));
  return (
    <ErrorNote
      tone={note.tone}
      title={note.title}
      message={note.message === "" ? error.message : note.message}
      hint={`${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`}
      retryable={false}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Handing it over                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Give the ticket to an operator — possibly oneself, which is what `Take it` prefills.
 *
 * **One write path for both**, rather than a silent one-press claim beside a dialog for everyone
 * else. The column is denormalised with no foreign key precisely so a renamed or deactivated
 * operator does not rewrite who worked a queue, which means whatever is typed here is what the
 * history will say for ever — and a name that could never have been an operator is a row that
 * quietly means nothing. So the name is shown before it is recorded, in both directions.
 *
 * The API does **not** check the value against the roster and neither does this: what is checked
 * is the SHAPE — the column's width and the same pattern `POST /api/admins` accepts — so an
 * impossible name is refused here instead of becoming a 422 after the press.
 *
 * Assigning does **not** move the ticket. In the Telegram group `✋ Claim` is both acts because a
 * staffer has one button; here the operator has the column controls in front of them, and an
 * implicit move would write a `status_change` nobody asked for.
 */
function AssignTicketDialog({
  ticket,
  initialUsername,
  onClose,
}: {
  readonly ticket: SupportTicketView;
  readonly initialUsername: string;
  readonly onClose: () => void;
}): JSX.Element {
  const { t } = useI18n();
  const id = useId();
  const [username, setUsername] = useState(initialUsername);
  const assign = useAssignSupportTicket();
  const isShaped = isAssignableUsername(username);

  function confirm(): void {
    if (!isShaped) return;
    assign.mutate(
      { ticketId: ticket.id, body: { adminUsername: username } },
      {
        onSuccess: () => {
          onClose();
        },
      },
    );
  }

  return (
    <ConfirmDialog
      isOpen
      onClose={onClose}
      title={t("support.dialogs.assign.title")}
      description={t("support.dialogs.assign.hint")}
      confirmLabel={t("support.dialogs.assign.submit")}
      pendingLabel={t("support.dialogs.assign.pending")}
      isPending={assign.isPending}
      isConfirmDisabled={!isShaped}
      onConfirm={confirm}
      error={
        assign.error === null ? undefined : (
          <AssignFailure error={assign.error} />
        )
      }
    >
      <div className="flex flex-col gap-2">
        <label
          htmlFor={id}
          className="block text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-label"
        >
          {t("support.dialogs.assign.label")}
        </label>
        <input
          id={id}
          type="text"
          value={username}
          onChange={(event) => {
            setUsername(event.target.value);
          }}
          placeholder={t("support.dialogs.assign.placeholder")}
          maxLength={MAX_TICKET_ASSIGNEE_CHARS}
          disabled={assign.isPending}
          aria-invalid={username !== "" && !isShaped}
          data-autofocus
          className={cn(
            "block w-full rounded-field border bg-card px-3 py-2",
            "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-900",
            "placeholder:text-ink-300",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
            "disabled:cursor-not-allowed disabled:bg-bg",
            username !== "" && !isShaped ? "border-required" : "border-stroke",
          )}
        />
        {username !== "" && !isShaped ? (
          <p className="m-0 text-[11px] font-semibold leading-[1.35] text-required-deep">
            {t("support.dialogs.assign.invalid")}
          </p>
        ) : null}
      </div>
    </ConfirmDialog>
  );
}

function AssignFailure({
  error,
}: {
  readonly error: AdminQueryError;
}): JSX.Element {
  const { t } = useI18n();
  const note = noteFor(error, false, t, t("support.dialogs.assign.title"));
  return (
    <ErrorNote
      tone={note.tone}
      title={note.title}
      message={note.message === "" ? error.message : note.message}
      hint={`${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`}
      retryable={false}
    />
  );
}
