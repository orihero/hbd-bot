/**
 * One ticket, as a card on the board.
 *
 * ## The card is the focusable thing, and the link inside it is not
 *
 * Native HTML5 drag-and-drop is invisible to a keyboard and to a screen reader, so this board
 * carries a second, hand-written path: pick up with Space, choose a column with the arrow keys,
 * drop with Space, cancel with Escape (`SUPPORT_TICKETS_SPEC §6.2`). That path needs somewhere
 * to put focus, and the card itself is the only honest place — the thing being moved is the
 * ticket, not a control on it.
 *
 * So the `<li>` takes `tabIndex={0}` and the key handling, and it does **not** take
 * `role="button"`. A card announced as a button promises that Space activates it, and here
 * Space picks it up; the promise this element makes instead is `aria-describedby`, pointing at
 * the board's one visible instructions line, which is read out when focus lands. Opening the
 * ticket is a real `<button>` inside the card — the public reference, which is what an operator
 * reaches for anyway — so the action is reachable by Tab as well as by Enter on the card, and
 * it has an accessible name that says what it does rather than being a bare reference string.
 *
 * ## What a card may claim
 *
 * Four things on this card are refusals rather than decoration, and each has a way of being
 * quietly broken by somebody tidying the layout:
 *
 *  - **A `null` body is "nothing was described", never "hidden".** This is the one wire in the
 *    panel carrying a customer's free text in full, so an empty one is a customer who tapped
 *    and never typed — not a redaction, and never rendered as one. The board should not be
 *    showing such a ticket at all (`onlyDescribed`), and the branch stays because a card built
 *    from a cache written before that filter was forced on is a shape this component can
 *    legitimately be handed.
 *  - **A ticket not in the support group says so.** `isPostedToGroup: false` beside a described
 *    body means the group post is still owed — the ticket is not lost and the customer already
 *    has their reference — or that this deployment has no support group SELECTED, which is the
 *    shipped default (an empty `bot_chats` table; it was `support_group_chat_id = 0` until
 *    2026-09-15, and `SupportGroupDialog` is now where that is fixed). Either way the staff
 *    working from Telegram cannot see this one,
 *    and that is a fact an operator plans around.
 *  - **A resolved clock beside a live status is a reopen.** `resolvedAt` is never cleared, and
 *    the pair is the only notification this console has for "a complaint came back" — there is
 *    no notification surface anywhere in the panel.
 *  - **The customer is a MASK.** The raw Telegram id travels on the wire (the queue keys on it,
 *    and the first thing an operator does with a complaint is open the customer's record), but
 *    a card on a board that is read over somebody's shoulder shows `telegramUserIdMasked`. The
 *    raw id belongs on the ticket screen's identity block, behind a deliberate act.
 *
 * The status itself is NOT drawn on the card: the column is the status, and a chip repeating it
 * would be the one label on the board that goes stale during an optimistic move.
 */

import { useEffect, useRef, type DragEvent, type JSX, type KeyboardEvent } from "react";

import type { SupportTicketStatus, SupportTicketView } from "@/api/support";
import { Badge } from "@/components/Badge";
import {
  TICKET_SOURCE_HINT_KEY,
  TICKET_SOURCE_LABEL_KEY,
  TICKET_STATUS_LABEL_KEY,
  formatAbsolute,
  formatCount,
  formatRelative,
  isReopenedTicket,
  isUndescribedTicket,
  type Translate,
} from "@/features/support/ticketFormat";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";

/** The kit's 12px cell, used for everything on a card that is not the complaint itself. */
const META_CLASS = "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500";

export interface TicketCardProps {
  readonly ticket: SupportTicketView;
  readonly t: Translate;
  /**
   * The column this card is DRAWN in — which is not always `ticket.status`.
   *
   * While a move is in flight the card sits in the column it is going to, and after a lost race
   * it sits in the column the server said it was actually in. Every announcement and every
   * `expectedStatus` reads THIS value, because it is what the operator can see.
   */
  readonly drawnIn: SupportTicketStatus;
  /** Picked up by the keyboard path and waiting for a column. */
  readonly isGrabbed: boolean;
  /** A move for this ticket is in flight. The card is dimmed and cannot be picked up again. */
  readonly isMoving: boolean;
  /** Whether this role may move tickets at all. Withheld, never disabled — see `lib/rbac.ts`. */
  readonly isMovable: boolean;
  /**
   * Focus belongs on this card after the board re-rendered under it.
   *
   * A keyboard move takes the card out of one column's list and into another's, which unmounts
   * and remounts it — and focus lands back on `<body>`, leaving an operator who was mid-triage
   * with nowhere to press the next key. The board names the card that should hold focus and
   * this effect puts it back.
   */
  readonly shouldFocus: boolean;
  /** The board's one instructions line. `undefined` for a role that cannot move anything. */
  readonly instructionsId: string | undefined;
  readonly onOpen: () => void;
  readonly onKeyDown: (event: KeyboardEvent<HTMLLIElement>) => void;
  readonly onDragStart: (event: DragEvent<HTMLLIElement>) => void;
  readonly onDragEnd: () => void;
}

export function TicketCard({
  ticket,
  t,
  drawnIn,
  isGrabbed,
  isMoving,
  isMovable,
  shouldFocus,
  instructionsId,
  onOpen,
  onKeyDown,
  onDragStart,
  onDragEnd,
}: TicketCardProps): JSX.Element {
  const card = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (shouldFocus) card.current?.focus();
  }, [shouldFocus]);

  const statusLabel = t(TICKET_STATUS_LABEL_KEY[drawnIn]);
  const updated = formatRelative(ticket.updatedAt, t) ?? ticket.updatedAt;

  return (
    <li
      ref={card}
      tabIndex={0}
      draggable={isMovable}
      aria-label={t("support.board.cardAria", {
        reference: ticket.publicRef,
        customer: ticket.telegramUserIdMasked,
        status: statusLabel,
      })}
      aria-describedby={instructionsId}
      aria-busy={isMoving}
      onKeyDown={onKeyDown}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={cn(
        "flex list-none flex-col gap-2 rounded-card border border-stroke bg-card px-3 py-3",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
        isMovable && "cursor-grab",
        /* Picked up: a ring rather than a shadow, because the card has not moved yet and a
           lifted card that is still in its column reads as a rendering glitch. */
        isGrabbed && "cursor-grabbing ring-2 ring-accent-deep",
        isMoving && "opacity-50",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={onOpen}
          aria-label={`${t("support.openTicket")} ${ticket.publicRef}`}
          title={t("support.card.reference")}
          className={cn(
            "cursor-pointer rounded border-0 bg-transparent p-0 font-mono text-[12px] font-semibold",
            "leading-[16.392px] text-ink-900 underline underline-offset-2",
            "transition-colors hover:text-accent-deep",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
          )}
        >
          {ticket.publicRef}
        </button>
        <span
          className={cn(META_CLASS, "whitespace-nowrap")}
          title={`${t("support.card.updated")}: ${formatAbsolute(ticket.updatedAt)}`}
        >
          {updated}
        </span>
      </div>

      {isUndescribedTicket(ticket) ? (
        /* Not a redaction and not an error: somebody tapped ⚠️ and never typed. The board
           filters these out, so seeing one here means a cache older than that filter. */
        <p className={cn(META_CLASS, "m-0 italic")} title={t("support.card.noBodyHint")}>
          {t("support.card.noBody")}
        </p>
      ) : (
        <p
          className="m-0 line-clamp-3 text-[12px] font-normal leading-[1.4] text-ink-900"
          title={t("support.card.body")}
        >
          {ticket.body}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={META_CLASS} title={t("support.card.customer")}>
          {ticket.telegramUserIdMasked}
        </span>
        <span className={META_CLASS} title={t("support.card.language")}>
          {t(LANGUAGE_LABEL_KEY[ticket.language])}
        </span>
        <span className={META_CLASS}>
          {t("support.card.events", { count: formatCount(ticket.eventCount) })}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="muted" title={t(TICKET_SOURCE_HINT_KEY[ticket.source])}>
          {t(TICKET_SOURCE_LABEL_KEY[ticket.source])}
        </Badge>
        {ticket.assignedAdminUsername === null ? (
          <span className={META_CLASS}>{t("support.card.unassigned")}</span>
        ) : (
          <span className={META_CLASS} title={t("support.card.assignee")}>
            {ticket.assignedAdminUsername}
          </span>
        )}
        {isReopenedTicket(ticket) ? (
          <Badge tone="warning" title={t("support.card.reopenedHint")}>
            {t("support.card.reopened")}
          </Badge>
        ) : null}
        {ticket.isPostedToGroup ? null : (
          <Badge tone="muted" title={t("support.card.notInGroupHint")}>
            {t("support.card.notInGroup")}
          </Badge>
        )}
      </div>
    </li>
  );
}
