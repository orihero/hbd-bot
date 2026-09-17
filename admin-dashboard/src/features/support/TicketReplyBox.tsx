/**
 * The two things an operator can WRITE on a ticket, in one file so that nobody can write a
 * third that blurs them.
 *
 * A note stays in this panel. A reply is put into a real person's phone, in the language they
 * complained in, and cannot be recalled. They are one keystroke apart in the API — two routes
 * whose request bodies are the same single field — which is exactly why
 * `schemas/tickets.py` gives them two models and says so: "one model behind two routes is one
 * refactor away from one route behind one model". This module takes the same position one layer
 * up. There is no `mode` prop, no shared `TicketComposer` that branches on a string, and no
 * table of copy keyed by an action name. {@link TicketReplyDialog} and {@link TicketNoteDialog}
 * are two components that happen to share a text field, and the ONLY thing they share is
 * {@link BodyField} — the textarea itself, which knows nothing about who reads what is typed
 * into it.
 *
 * ## The difference is visible while the words are being typed, not only in the heading
 *
 * A label an operator has read four hundred times is not a control. So the two differ in the
 * band immediately above the box — an alarm ground saying the words cannot be unsent, against a
 * quiet ground saying nobody outside this panel will ever see them — in the field's own edge,
 * in the confirm button's tone (`danger` against the default accent), and in the verb on that
 * button. The reply also names its recipient and their language in the description, because
 * "which of these people am I about to message" is the question a mistaken send answers wrongly.
 *
 * ## Both go through `ConfirmDialog`, and the reply is the reason
 *
 * The broadcasts feature gates every irreversible send behind that dialog: focus is moved in
 * and trapped, Escape and the scrim rest while a request is in flight, and the confirm button
 * carries the verb rather than the word "OK". A reply is this namespace's irreversible send —
 * one message, one person, no recall — so it is gated the same way. The note is gated too, for
 * a smaller reason that still holds: a note is append-only and there is no route that deletes
 * one, so an accidental line stays on the timeline for as long as the ticket does.
 *
 * ## No step-up, and no reason code, on either
 *
 * `support.write` is a plain `W` cell — `api/support.ts` carries the argument — so there is no
 * `STEP_UP_REQUIRED` to catch, no `subjectId` to echo back verbatim and no body to replay. And
 * neither request inherits `ReasonedRequest`: §12.4's rule is about destructive acts, and
 * answering somebody who wrote to us is the ordinary work of the queue. That is why
 * `ConfirmDialog`'s built-in `reason` field is deliberately unused below and the composer lives
 * in `children` instead — that field exists to collect a `reasonCode`'s free text, and pouring a
 * customer-facing answer into a control named "reason" is how the next reader comes to believe
 * this route takes one.
 *
 * ## A closed dialog holds nothing
 *
 * Both are mounted only while open (`SupportTicketScreen` owns that), so the draft is discarded
 * structurally rather than by an effect that has to remember to run. This matters more here than
 * on a campaign: the ticket screen is navigated between tickets, and a half-written answer to
 * one customer surviving into another customer's dialog is the failure this shape makes
 * unreachable.
 */

import { useId, useState, type JSX, type ReactNode } from "react";

import {
  MAX_TICKET_BODY_CHARS,
  isSendableTicketBody,
  type SupportTicketView,
} from "@/api/support";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import { formatCount, noteFor } from "@/features/support/ticketFormat";
import {
  useAddSupportTicketNote,
  useReplyToSupportTicket,
} from "@/features/support/useSupportTickets";
import { useI18n } from "@/i18n";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import type { AdminQueryError } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";

export interface TicketComposerProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** The ticket being written on. Its language decides what the reply must be written in. */
  readonly ticket: SupportTicketView;
}

/* -------------------------------------------------------------------------- */
/* The reply — the one action on this surface that leaves the building         */
/* -------------------------------------------------------------------------- */

/**
 * Answer the customer.
 *
 * Three things are load-bearing rather than decorative:
 *
 * 1. **The language is named, from the ticket and not from the account.** `ticket.language` is
 *    the locale the complaint was OPENED in, which is the language the answer has to be written
 *    in — not whatever the customer's record says today. It is on the screen while the operator
 *    types, because a correct answer in the wrong language is an answer nobody reads.
 * 2. **The button is disabled while the mutation is pending.** The relay job is keyed on the
 *    event id, so a double-clicked Send collapses onto the job already queued rather than
 *    putting the same paragraph in somebody's phone twice — but a second press still writes a
 *    second `reply` EVENT, and the timeline would then show the same answer twice with one of
 *    them undelivered. The idempotency is the server's; this is the screen's half.
 * 3. **A 503 is not a failed send.** The reply and its relay enqueue commit together, so a dead
 *    worker rolls the whole action back: nothing was written, nothing was sent, and the operator
 *    presses again once the worker is up. `noteFor` says exactly that rather than leaving them
 *    to guess whether the customer got half of it.
 */
export function TicketReplyDialog({ isOpen, onClose, ticket }: TicketComposerProps): JSX.Element {
  const { t } = useI18n();
  const [body, setBody] = useState("");
  const reply = useReplyToSupportTicket();
  const canSend = isSendableTicketBody(body);

  function confirm(): void {
    if (!canSend) return;
    reply.mutate(
      { ticketId: ticket.id, body: { body } },
      {
        /* The response IS the ticket, re-read inside the transaction it was written in, and the
           hook has already seeded the detail cache with it — so closing here reveals the new
           `reply` event rather than the timeline as it was a moment ago. */
        onSuccess: () => {
          onClose();
        },
      },
    );
  }

  return (
    <ConfirmDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t("support.dialogs.reply.title")}
      tone="danger"
      description={
        <>
          <span className="block">{t("support.dialogs.reply.hint")}</span>
          <span className="mt-2 block text-ink-900">
            {t("support.card.customer")}: {ticket.telegramUserIdMasked} ·{" "}
            {t("support.card.language")}: {t(LANGUAGE_LABEL_KEY[ticket.language])}
          </span>
        </>
      }
      confirmLabel={t("support.dialogs.reply.submit")}
      pendingLabel={t("support.dialogs.reply.pending")}
      isPending={reply.isPending}
      isConfirmDisabled={!canSend}
      onConfirm={confirm}
      error={
        reply.error === null ? undefined : (
          <ComposerFailure error={reply.error} subject={t("support.dialogs.reply.title")} />
        )
      }
    >
      <div className="flex flex-col gap-3">
        {/* The band, not a footnote: it sits between the heading and the box, so it is read on
            the way to the keyboard rather than after the answer has been typed. */}
        <p
          role="note"
          className="m-0 rounded-card bg-required-24 px-3 py-2 text-[12px] font-semibold leading-4 text-required-deep"
        >
          {t("support.dialogs.reply.warning")}
        </p>
        <BodyField
          label={t("support.dialogs.reply.label")}
          placeholder={t("support.dialogs.reply.placeholder")}
          value={body}
          onChange={setBody}
          isDisabled={reply.isPending}
          isAlarming
          /* Only the reply counts down. Its ceiling is Telegram's own single-message limit as
             well as the column's, so a body over it is a message that could not be carried —
             which is a different and worse thing than a row that would not fit. */
          counter={t("support.dialogs.reply.remaining", {
            count: formatCount(MAX_TICKET_BODY_CHARS - body.length),
          })}
        />
      </div>
    </ConfirmDialog>
  );
}

/* -------------------------------------------------------------------------- */
/* The note — the one that reaches nobody                                      */
/* -------------------------------------------------------------------------- */

/**
 * Append an internal line to the timeline.
 *
 * The copy is blunt about the second half of "internal", which is the half operators get wrong:
 * a note is invisible to the customer AND to the staffers working the card in the Telegram
 * group. That is what an internal note IS, and a screen that let somebody believe they had left
 * a message for the group would be routing a handover into a place nobody reads.
 *
 * It is also the only write in this namespace that enqueues nothing — it reaches no chat and
 * changes no rendered surface — and therefore the only one that cannot answer `503`. The failure
 * copy goes through the same {@link ComposerFailure} anyway, because a branch that exists only
 * to omit an unreachable case is a branch that goes stale the day a note grows a side effect.
 */
export function TicketNoteDialog({ isOpen, onClose, ticket }: TicketComposerProps): JSX.Element {
  const { t } = useI18n();
  const [body, setBody] = useState("");
  const note = useAddSupportTicketNote();
  const canSave = isSendableTicketBody(body);

  function confirm(): void {
    if (!canSave) return;
    note.mutate(
      { ticketId: ticket.id, body: { body } },
      {
        onSuccess: () => {
          onClose();
        },
      },
    );
  }

  return (
    <ConfirmDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t("support.dialogs.note.title")}
      description={t("support.dialogs.note.hint")}
      confirmLabel={t("support.dialogs.note.submit")}
      pendingLabel={t("support.dialogs.note.pending")}
      isPending={note.isPending}
      isConfirmDisabled={!canSave}
      onConfirm={confirm}
      error={
        note.error === null ? undefined : (
          <ComposerFailure error={note.error} subject={t("support.dialogs.note.title")} />
        )
      }
    >
      <div className="flex flex-col gap-3">
        <p
          role="note"
          className="m-0 rounded-card bg-bg px-3 py-2 text-[12px] leading-4 text-ink-500 ring-1 ring-inset ring-stroke"
        >
          {t("support.dialogs.note.warning")}
        </p>
        <BodyField
          label={t("support.dialogs.note.label")}
          placeholder={t("support.dialogs.note.placeholder")}
          value={body}
          onChange={setBody}
          isDisabled={note.isPending}
        />
      </div>
    </ConfirmDialog>
  );
}

/* -------------------------------------------------------------------------- */
/* What the two share, and it is only the box                                  */
/* -------------------------------------------------------------------------- */

interface BodyFieldProps {
  readonly label: string;
  readonly placeholder: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly isDisabled: boolean;
  /**
   * The alarm edge. `true` exactly when what is typed here leaves the building — which today is
   * the reply and nothing else. Deliberately NOT named `isReply`: this component must not know
   * which of its two callers it is serving, or it becomes the shared branch this file exists to
   * refuse.
   */
  readonly isAlarming?: boolean;
  /** A live character count, where one is worth reading. Absent on the note — see the reply. */
  readonly counter?: ReactNode;
}

/**
 * The textarea, and nothing else.
 *
 * `maxLength` caps the INPUT at the server's own bound rather than letting an over-long body
 * become a 422 the operator cannot see the shape of — `ConfirmDialog`'s reason field takes the
 * same position. Nothing is trimmed on the way out: `_checked_body` refuses whitespace-only
 * text and stores exactly what was typed, so a composer that quietly trimmed would be storing
 * something other than the artefact.
 *
 * `data-autofocus` puts the cursor in the box on open. `ConfirmDialog` otherwise focuses
 * Cancel, and it never focuses the confirm button — a stray Enter on a focused Send is the
 * accident this whole file is shaped against.
 */
function BodyField({
  label,
  placeholder,
  value,
  onChange,
  isDisabled,
  isAlarming = false,
  counter,
}: BodyFieldProps): JSX.Element {
  const id = useId();

  return (
    <div className="flex flex-col gap-2">
      <label
        htmlFor={id}
        className="block text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-label"
      >
        {label}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        placeholder={placeholder}
        maxLength={MAX_TICKET_BODY_CHARS}
        disabled={isDisabled}
        rows={5}
        data-autofocus
        className={cn(
          "block w-full resize-y rounded-field border bg-card px-3 py-2",
          "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-900",
          "placeholder:text-ink-300",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
          "disabled:cursor-not-allowed disabled:bg-bg",
          isAlarming ? "border-required" : "border-stroke",
        )}
      />
      {counter === undefined ? null : (
        <p className="m-0 text-[11px] leading-[1.35] text-ink-400">{counter}</p>
      )}
    </div>
  );
}

/**
 * A refused write, in the words a failed read gets.
 *
 * The subject is the ACTION and not the ticket — "Reply to the customer failed" is a fact about
 * the press, which is what the operator is holding. Never retryable from in here: `noteFor`
 * decides that for a READ, and a write is re-attempted by pressing the button again with the
 * body still on screen, not by a Retry link that would resend what may already have landed.
 */
function ComposerFailure({
  error,
  subject,
}: {
  readonly error: AdminQueryError;
  readonly subject: string;
}): JSX.Element {
  const { t } = useI18n();
  const note = noteFor(error, false, t, subject);
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
