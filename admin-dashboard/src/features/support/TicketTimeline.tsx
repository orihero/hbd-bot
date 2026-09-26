/**
 * One ticket's append-only history, read forwards — the only place in this console where a
 * conversation is rendered rather than a record.
 *
 * ## The order is the server's, and it is not re-sorted here
 *
 * `SupportTicketDetailView.events` arrives unpaged and OLDEST FIRST, which is two departures
 * from this API's defaults and both are deliberate: a ticket is a conversation between one
 * customer and a handful of staff, so its event count is tens at the very worst, and a
 * conversation is read forwards. Re-sorting by `createdAt` here would be a second ordering of
 * a promise that already has one — and a worse one, because two events written inside one
 * transaction share an instant exactly and only the server's `(ticket_id, created_at, id)` read
 * breaks that tie the same way twice.
 *
 * ## A composed reply and a delivered reply are two different rows
 *
 * `relayedAt` is stamped by the worker AFTER the message reaches the customer's chat, so a
 * `reply` with a null clock is a sentence that was written and never arrived — the customer
 * blocked the bot, or the deployment had no worker running. `isUnrelayedReply` is the shared
 * predicate and this component MUST branch on it: rendering every reply the same way tells an
 * operator "we answered them" when nothing landed, which is the single worst mistake available
 * on this screen. It is also why the undelivered state is a warning band with the reason
 * spelled out and not a small grey clock nobody reads.
 *
 * ## `operator` and `staff_group` are kept visibly apart, at the cost of a tone
 *
 * An `operator` signed in to this panel has an `admin_users` row, a role, a session and an
 * `admin_audit_log` entry written beside the event. A `staff_group` author is somebody in a
 * Telegram group whose only credential is membership of that chat and whose actions write NO
 * audit row at all. Both get a badge, in different tones, and the badge is never omitted even
 * when the name below it would be enough — because a timeline that rendered both as "staff"
 * would let an unaudited act borrow an audited actor's accountability. The customer and the
 * system carry the same badge for consistency of reading, not because anything hangs on it.
 *
 * ## Every body is TEXT, never markup
 *
 * A ticket body, a note and a reply all cross the wire as the artefact somebody typed. They are
 * rendered with `whitespace-pre-wrap` — the line breaks are part of what was written — and
 * never parsed: injecting stored prose into this document is the one thing a console that
 * renders operator- and customer-composed content must not do. `BroadcastDetailScreen`'s
 * message panel takes the same position for the same reason.
 */

import type { JSX } from "react";

import type { SupportAuthorKind, SupportTicketEventView } from "@/api/support";
import { Badge, type BadgeTone } from "@/components/Badge";
import {
  AUTHOR_KIND_LABEL_KEY,
  EVENT_KIND_LABEL_KEY,
  TICKET_STATUS_LABEL_KEY,
  formatAbsolute,
  formatRelative,
  isReopenMove,
  isUnrelayedReply,
  type Translate,
} from "@/features/support/ticketFormat";
import { cn } from "@/lib/cn";

/**
 * Who wrote the line, as colour — the second reading of the badge, after its word.
 *
 * `operator` takes the accent because that is this console's own voice; `staff_group` is
 * `muted` so the two can never be mistaken for each other at a glance, which is the whole point
 * of the split. Nothing here is `danger`: a timeline is a record, and an alarm colour on a row
 * that merely happened is an alarm colour nobody sees when one is warranted.
 */
const AUTHOR_KIND_TONE: Readonly<Record<SupportAuthorKind, BadgeTone>> = {
  customer: "neutral",
  operator: "accent",
  staff_group: "muted",
  system: "muted",
};

const ROW_CLASS = "flex flex-col gap-2 rounded-card border border-stroke bg-bg p-3";
const META_CLASS = "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-400";
const PROSE_CLASS =
  "m-0 whitespace-pre-wrap break-words text-[12px] leading-[1.5] text-ink-900";

export interface TicketTimelineProps {
  /** The server's order, kept. Oldest first. */
  readonly events: readonly SupportTicketEventView[];
  /**
   * The operator's language, threaded in rather than read from the store here.
   *
   * `t` is a NEW CLOSURE per locale, so a component that took it from `useI18n()` itself would
   * be correct too — it is passed because the screen already holds one and a second
   * subscription to the i18n store buys nothing. Whichever way it arrives, it belongs in the
   * dependency array of any `useMemo` built from it; there is none here on purpose, because
   * every label below is derived per row at render and nothing is cached across locales.
   */
  readonly t: Translate;
}

export function TicketTimeline({ events, t }: TicketTimelineProps): JSX.Element {
  if (events.length === 0) {
    /* Unreachable in practice — a ticket is born with an `opened` event — and rendered anyway,
       because "no rows" must read as a state rather than as a panel that failed to load. */
    return <p className={cn("m-0", META_CLASS)}>{t("support.timeline.empty")}</p>;
  }

  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      {events.map((event) => (
        <li key={event.id} className={ROW_CLASS}>
          <TicketEventHeader event={event} t={t} />
          <TicketEventDetail event={event} t={t} />
        </li>
      ))}
    </ol>
  );
}

/** What happened, who did it, and when — the one line every kind of event has. */
function TicketEventHeader({
  event,
  t,
}: {
  readonly event: SupportTicketEventView;
  readonly t: Translate;
}): JSX.Element {
  const author = authorNameOf(event, t);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={AUTHOR_KIND_TONE[event.authorKind]}>
        {t(AUTHOR_KIND_LABEL_KEY[event.authorKind])}
      </Badge>
      <span className="text-[12px] font-semibold leading-4 text-ink-900">
        {t(EVENT_KIND_LABEL_KEY[event.kind])}
      </span>
      {author === null ? null : <span className={META_CLASS}>{author}</span>}
      {/* The relative form is what an operator reads; the exact instant rides in the title,
          because "2 days ago" is not a thing anybody can quote back down a phone line. */}
      <span className={cn("ml-auto", META_CLASS)} title={formatAbsolute(event.createdAt)}>
        {whenOf(event.createdAt, t)}
      </span>
    </div>
  );
}

/** Everything below the header: the move, the hand-over, the prose, the relay clock. */
function TicketEventDetail({
  event,
  t,
}: {
  readonly event: SupportTicketEventView;
  readonly t: Translate;
}): JSX.Element {
  const { fromStatus, toStatus } = event;

  return (
    <>
      {fromStatus === null || toStatus === null ? null : (
        <p className="m-0 flex flex-wrap items-center gap-2 text-[12px] leading-4 text-ink-900">
          {/* BOTH ends, always. "It went to waiting" and "it went to waiting FROM resolved"
              are different events, and the second one is a complaint that came back. */}
          <span>
            {t("support.timeline.statusMove", {
              from: t(TICKET_STATUS_LABEL_KEY[fromStatus]),
              to: t(TICKET_STATUS_LABEL_KEY[toStatus]),
            })}
          </span>
          {isReopenMove(fromStatus, toStatus) ? (
            <Badge tone="warning" title={t("support.card.reopenedHint")}>
              {t("support.card.reopened")}
            </Badge>
          ) : null}
        </p>
      )}

      {event.kind === "assigned" ? (
        <p className={cn("m-0", META_CLASS)}>
          {t("support.timeline.assignedTo", {
            username: event.authorAdminUsername ?? t("support.timeline.unknownAuthor"),
          })}
        </p>
      ) : null}

      {event.body === null ? null : <p className={PROSE_CLASS}>{event.body}</p>}

      {event.kind === "reply" ? <ReplyDelivery event={event} t={t} /> : null}
    </>
  );
}

/**
 * Whether this answer reached the person it was written to.
 *
 * The undelivered branch says WHY as well as WHAT, because the two causes an operator can act
 * on are different actions: a blocked bot means the customer must be reached another way, and a
 * stopped worker means the reply is still queued and nothing has to be rewritten.
 */
function ReplyDelivery({
  event,
  t,
}: {
  readonly event: SupportTicketEventView;
  readonly t: Translate;
}): JSX.Element {
  const { relayedAt } = event;

  /* `isUnrelayedReply` is the shared rule and the authority. The second half of this condition
     is TypeScript's rather than the rule's: it is what narrows the clock to a string for the
     delivered branch below, and it can never be the half that decides. */
  if (isUnrelayedReply(event) || relayedAt === null) {
    return (
      <p className="m-0 flex flex-col gap-1 rounded-card bg-warn-18 px-3 py-2 text-[12px] leading-4 text-warn-deep">
        <span className="font-semibold">{t("support.timeline.notRelayed")}</span>
        <span>{t("support.timeline.notRelayedHint")}</span>
      </p>
    );
  }

  return (
    <p className={cn("m-0", META_CLASS)} title={formatAbsolute(relayedAt)}>
      {t("support.timeline.relayed", { when: whenOf(relayedAt, t) })}
    </p>
  );
}

/**
 * The name to print beside the badge, or `null` when the badge has already said it.
 *
 * An `operator` is named by their `admin_users` username, denormalised on the row so a rename
 * never rewrites history. A `staff_group` author is named by the `@handle` or first name the
 * bot captured, falling back to their MASKED Telegram id — the raw id is not on this wire and
 * must not be reconstructed, because the author of a timeline line is not a record this panel
 * can route to. `system` gets nothing: its badge is its whole identity, and a second line
 * saying "The system" twice is noise.
 */
function authorNameOf(event: SupportTicketEventView, t: Translate): string | null {
  if (event.authorKind === "system") return null;
  if (event.authorKind === "operator") {
    return event.authorAdminUsername ?? t("support.timeline.unknownAuthor");
  }
  return (
    event.authorDisplayName ??
    event.authorTelegramUserIdMasked ??
    t("support.timeline.unknownAuthor")
  );
}

/** "3 minutes ago", with the absolute instant left to the caller's `title`. */
function whenOf(iso: string, t: Translate): string {
  return formatRelative(iso, t) ?? formatAbsolute(iso);
}
