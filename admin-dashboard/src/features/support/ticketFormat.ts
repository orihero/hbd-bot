/**
 * What the two Support screens agree on: the board's columns, the grammar of a move, the
 * timeline's vocabulary, and the refusals.
 *
 * A leaf module imported by the board and by the ticket screen alike. It exists because both of
 * them need the same words for the same wire members and, more importantly, the same answer to
 * **"which moves are allowed?"** — a board that offers a drop target the ticket screen would
 * refuse is two implementations of one rule, and the drift shows up as an operator dragging a
 * card into a column that bounces.
 *
 * Every table here is a `Record` over a wire enum rather than a lookup with a fallback, so a
 * fifth `SupportTicketStatus` or an eighth event kind is a COMPILE error in this file instead of
 * a blank chip on a board somebody is working a backlog from. `enum_type` renders a plain
 * `VARCHAR(32)` server-side, so a fifth status needs no migration — which makes this file, not
 * the database, the thing that would notice.
 *
 * ## The transition table is here AND on every ticket, and that is not a duplication to remove
 *
 * `SupportTicketView.allowedTransitions` is the server's own answer for ONE ticket, ordered,
 * derived from `bayram.support.LEGAL_STATUS_MOVES` at read time. {@link LEGAL_TICKET_MOVES}
 * below is the same table as data, and it is needed for the questions asked before a ticket is
 * in hand: which columns a keyboard move may offer while a card is picked up, whether a drop
 * target should light up at all, what a column header says it accepts. **When a ticket is in
 * hand, prefer its `allowedTransitions`** — {@link allowedMovesFor} does exactly that — because
 * the server's copy cannot be stale relative to the row it came with. Neither copy decides
 * anything: every move is a conditional `UPDATE` that answers `409` with the status it actually
 * found, because a staffer in the Telegram group moves tickets in another process while this
 * screen is being read. A move these tables hide is an affordance withheld; the refusal is
 * still the server's.
 *
 * Three refusals in that grammar look arbitrary until they are argued, and a screen must not
 * "helpfully" work around any of them:
 *
 *  - **A status may not move to itself.** `X -> X` is absent from every row on purpose. It is a
 *    no-op that would still write a `status_change` event with both ends equal — a timeline row
 *    that says nothing — and bump `updatedAt`, making an untouched ticket look worked.
 *  - **Nothing returns to `new`.** `new` means "nobody has looked at this yet", which is a claim
 *    about the past no later move can make true again. A reopened ticket lands in `in_progress`.
 *  - **`resolved -> waiting` is not legal.** `waiting` means we have asked the customer
 *    something, and a resolved ticket has not.
 *
 * `new -> resolved` IS legal and is not a shortcut to close off: spam and duplicates are common
 * enough that routing them through `in_progress` would add a click and a meaningless event.
 *
 * ## The four time helpers are duplicated, not imported
 *
 * They are the ones in `features/broadcasts/broadcastFormat.ts`. Importing across features is
 * the coupling `features/audit/auditFormat.ts` argues against at length when it makes the same
 * choice, and the shared answer — one module under `src/lib/` — means editing two shipped
 * screens, which is not this change. Duplicating four pure functions is the cheaper honesty.
 */

import type {
  SupportAuthorKind,
  SupportTicketEventKind,
  SupportTicketSource,
  SupportTicketStatus,
  SupportTicketView,
} from "@/api/support";
import { CLIENT_ERROR_CODES } from "@/api/client";
import type { BadgeTone } from "@/components/Badge";
import type { NoteTone } from "@/components/ErrorNote";
import type { TranslationPath } from "@/i18n/types";
import type { AdminQueryError } from "@/lib/adminQuery";

/**
 * Every sentence on these screens, bound to the operator's chosen language.
 *
 * Declared here rather than imported from `broadcastFormat.ts` for that module's own reason: a
 * feature does not reach into a sibling feature for a type alias, and this one is two lines.
 * `t` is a NEW CLOSURE per locale, so it belongs in the dependency array of every `useMemo`
 * that builds a column heading or a status chip — omit it and they freeze in the language the
 * screen first rendered in.
 */
export type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

/* -------------------------------------------------------------------------- */
/* The board's four columns                                                    */
/* -------------------------------------------------------------------------- */

/**
 * The columns, left to right. **This order is the server's**, not a layout decision.
 *
 * It is `SupportTicketStatus`' declaration order, which is also the order `ticket_board`
 * zero-fills its four buckets in and the order `ordered_transitions` sorts
 * `allowedTransitions` into — so a button row reads `In progress · Waiting · Resolved` and
 * never `Resolved · In progress · Waiting`. Rendering the board from this constant rather than
 * from the response's array is deliberate: a column that appeared from nowhere as the first
 * ticket arrived would re-lay-out the board under the operator's cursor, and a board whose
 * columns depend on the data is a board whose emptiness cannot be told from a failed request.
 */
export const BOARD_COLUMNS: readonly SupportTicketStatus[] = [
  "new",
  "in_progress",
  "waiting",
  "resolved",
];

/**
 * The glyph on a column heading and on a card's status chip.
 *
 * The same four the group card uses — `🆕` in its header, `✋ Claim` and `✅ Resolve` on its two
 * inline buttons — so a staffer who triages in Telegram and an operator who works the board are
 * looking at one vocabulary. `⏳` is this file's own, for the column Telegram has no button
 * for. Decorative: every one of them sits beside its translated label and none carries meaning
 * alone.
 */
export const TICKET_STATUS_EMOJI: Readonly<Record<SupportTicketStatus, string>> = {
  new: "🆕",
  in_progress: "✋",
  waiting: "⏳",
  resolved: "✅",
};

export const TICKET_STATUS_LABEL_KEY: Readonly<Record<SupportTicketStatus, TranslationPath>> = {
  new: "support.status.new",
  in_progress: "support.status.inProgress",
  waiting: "support.status.waiting",
  resolved: "support.status.resolved",
};

/** The long form, on a chip's `title` and under a column heading: what the column MEANS. */
export const TICKET_STATUS_HINT_KEY: Readonly<Record<SupportTicketStatus, TranslationPath>> = {
  new: "support.statusHint.new",
  in_progress: "support.statusHint.inProgress",
  waiting: "support.statusHint.waiting",
  resolved: "support.statusHint.resolved",
};

/**
 * Colour is the second thing a column says; the word in the chip is the first.
 *
 * **Nothing on this board is `danger`,** and that absence is the decision: a complaint is work,
 * not an incident, and an alarm colour on a queue every operator opens every morning is an
 * alarm colour nobody sees any more. `new` takes `warning` — the tone this console already uses
 * for "something to look at, not something that went wrong" — because unlooked-at work is
 * exactly that. `in_progress` is the accent, where the live work is. `waiting` is `muted`
 * because it is parked on the CUSTOMER: nothing an operator does moves it, and colouring it for
 * attention would point the eye at the one column that cannot be acted on. `resolved` is
 * `neutral` rather than accent so the board's colour weight sits on the two columns that are
 * somebody's backlog.
 */
export const TICKET_STATUS_TONE: Readonly<Record<SupportTicketStatus, BadgeTone>> = {
  new: "warning",
  in_progress: "accent",
  waiting: "muted",
  resolved: "neutral",
};

/* -------------------------------------------------------------------------- */
/* The grammar of a move                                                       */
/* -------------------------------------------------------------------------- */

/**
 * `bayram.support.LEGAL_STATUS_MOVES`, as data, with every row in {@link BOARD_COLUMNS} order.
 *
 * A total `Record` so a fifth status cannot arrive without its row. The values are arrays and
 * not sets because they are RENDERED — a `frozenset`'s iteration order is a hash artefact, and
 * publishing one raw is how a button row reorders itself between two renders of the same
 * ticket.
 *
 * `resolved` keeps exactly one exit, `in_progress`, and it is a reopen: the customer replied, or
 * an operator pulled it back. `resolvedAt` is NOT cleared by that move, so a reopened ticket
 * still says it was once considered finished — the most useful thing to know about a repeat
 * complaint.
 */
export const LEGAL_TICKET_MOVES: Readonly<
  Record<SupportTicketStatus, readonly SupportTicketStatus[]>
> = {
  new: ["in_progress", "waiting", "resolved"],
  in_progress: ["waiting", "resolved"],
  waiting: ["in_progress", "resolved"],
  resolved: ["in_progress"],
};

/** Every column a ticket in this status may move to, in board order. Never includes itself. */
export function legalMovesFrom(status: SupportTicketStatus): readonly SupportTicketStatus[] {
  return LEGAL_TICKET_MOVES[status];
}

/** Whether this exact move is in the grammar. `false` for `X -> X`, always. */
export function isLegalTicketMove(
  from: SupportTicketStatus,
  to: SupportTicketStatus,
): boolean {
  return LEGAL_TICKET_MOVES[from].includes(to);
}

/**
 * The moves to OFFER for a ticket in hand — the server's answer, with this file's as the
 * fallback.
 *
 * `allowedTransitions` is computed per ticket from the same table, so the two agree today; what
 * makes the server's copy the one to prefer is that it travelled WITH the row, and a bundle
 * cached in a browser tab overnight is the copy that can be stale. The fallback exists for the
 * shape a screen can legitimately hold — a card rendered from a cursor page that was parsed
 * before a field was added, or a keyboard menu built from a column rather than from a card.
 */
export function allowedMovesFor(ticket: SupportTicketView): readonly SupportTicketStatus[] {
  return ticket.allowedTransitions.length > 0
    ? ticket.allowedTransitions
    : legalMovesFrom(ticket.status);
}

/**
 * Whether this card may be dropped on this column. The drag path's whole rule.
 *
 * Render a column as a live drop target only when this is `true`: four targets of which three
 * are guaranteed refusals is how a board teaches an operator to ignore its own errors. It is
 * also `false` for the column the card is already in, because nothing moves to itself.
 */
export function canMoveTicketTo(
  ticket: SupportTicketView,
  status: SupportTicketStatus,
): boolean {
  return allowedMovesFor(ticket).includes(status);
}

/**
 * Whether moving into `status` is a REOPEN rather than ordinary progress.
 *
 * Worth naming because the confirmation copy differs: pulling a resolved ticket back is the one
 * move that says "we were wrong to close this", and `resolvedAt` survives it.
 */
export function isReopenMove(
  from: SupportTicketStatus,
  to: SupportTicketStatus,
): boolean {
  return from === "resolved" && to === "in_progress";
}

/* -------------------------------------------------------------------------- */
/* What a ticket is, beyond its column                                         */
/* -------------------------------------------------------------------------- */

/**
 * The customer tapped ⚠️ and never typed.
 *
 * Not an error and not a redaction — those rows are the measure of how many people tried to
 * complain and gave up. The BOARD never shows them (`ticket_board` forces `onlyDescribed` on),
 * so this predicate is the list's, and a row it is true of must read as "nothing was described"
 * rather than as a missing body.
 */
export function isUndescribedTicket(ticket: SupportTicketView): boolean {
  return ticket.describedAt === null;
}

/**
 * This ticket was closed once and is open again.
 *
 * `resolvedAt` is never cleared by a reopen, so the pair — a resolved clock beside a live status
 * — is the whole signal. An operator who resolved fifty tickets on Friday finding six back on
 * Monday has no notification anywhere in this panel (there is no notification surface at all),
 * so the board is the only place that can say so.
 */
export function isReopenedTicket(ticket: SupportTicketView): boolean {
  return ticket.resolvedAt !== null && ticket.status !== "resolved";
}

/**
 * The card is described but has not reached the support group.
 *
 * `false` on an undescribed ticket, because the post is not owed until the customer has typed
 * something to post. When this is true the ticket is not lost and the customer HAS their
 * reference — the group leg is an internal delivery problem, and it is also off entirely on a
 * deployment with no support group SELECTED, which is the shipped default. That was
 * `support_group_chat_id = 0` until 2026-09-15 and is now an empty `bot_chats` table, chosen in
 * `SupportGroupDialog` rather than in a unit file; the observable state here is unchanged.
 */
export function isGroupPostOwed(ticket: SupportTicketView): boolean {
  return !ticket.isPostedToGroup && ticket.describedAt !== null;
}

export const TICKET_SOURCE_LABEL_KEY: Readonly<Record<SupportTicketSource, TranslationPath>> = {
  delivery_button: "support.source.deliveryButton",
  support_command: "support.source.supportCommand",
};

export const TICKET_SOURCE_HINT_KEY: Readonly<Record<SupportTicketSource, TranslationPath>> = {
  delivery_button: "support.sourceHint.deliveryButton",
  support_command: "support.sourceHint.supportCommand",
};

/* -------------------------------------------------------------------------- */
/* The timeline's vocabulary                                                   */
/* -------------------------------------------------------------------------- */

/**
 * What each kind of event says it is.
 *
 * `opened` and `described` stay two rows rather than one line, because a ticket that was opened
 * and never described is a real and common shape. `status_change` is rendered from its two
 * status fields — `support.timeline.statusMove` takes both — so the sentence names where it came
 * from as well as where it went; "it went to waiting" and "it went to waiting FROM resolved"
 * are different events and the second is a reopen.
 */
export const EVENT_KIND_LABEL_KEY: Readonly<
  Record<SupportTicketEventKind, TranslationPath>
> = {
  opened: "support.timeline.kind.opened",
  described: "support.timeline.kind.described",
  status_change: "support.timeline.kind.statusChange",
  note: "support.timeline.kind.note",
  reply: "support.timeline.kind.reply",
  assigned: "support.timeline.kind.assigned",
  group_posted: "support.timeline.kind.groupPosted",
};

/**
 * Who did it — and how accountable they are, which is the distinction the split exists for.
 *
 * An `operator` has an `admin_users` row, a session, a role and an `admin_audit_log` entry
 * beside the event. A `staff_group` author is somebody in a Telegram group whose only credential
 * is membership of that chat, and whose actions write NO audit row. A screen must keep the two
 * visibly apart: rendering both as "staff" would let the timeline claim an audited actor for an
 * act nobody audited.
 */
export const AUTHOR_KIND_LABEL_KEY: Readonly<Record<SupportAuthorKind, TranslationPath>> = {
  customer: "support.timeline.author.customer",
  operator: "support.timeline.author.operator",
  staff_group: "support.timeline.author.staffGroup",
  system: "support.timeline.author.system",
};

/**
 * A `reply` that was composed but has not reached anybody.
 *
 * `relayedAt` is stamped by the worker AFTER the send, so its absence on a reply is the only way
 * to tell "we answered them" from "we wrote an answer the customer never got" — the customer
 * blocked the bot, or a deployment has no worker running. Rendering a reply without this
 * distinction is the single worst mistake available on the ticket screen.
 *
 * `false` for every other kind: nothing else is relayed and an unrelayed `note` is not a thing.
 */
export function isUnrelayedReply(event: {
  readonly kind: SupportTicketEventKind;
  readonly relayedAt: string | null;
}): boolean {
  return event.kind === "reply" && event.relayedAt === null;
}

/* -------------------------------------------------------------------------- */
/* Numbers and instants                                                        */
/* -------------------------------------------------------------------------- */

const NUMBER_FORMAT = new Intl.NumberFormat();
const RELATIVE_FORMAT = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function formatCount(value: number): string {
  return NUMBER_FORMAT.format(value);
}

/**
 * A LIST total, said honestly.
 *
 * `isTotalExact: false` is `bounded_total`'s 10 000 cap talking and `null` is the server
 * declining to say; neither is a promise, so both read as "at least".
 *
 * **Never use this for a board column.** Those four numbers are exact `GROUP BY` buckets and
 * are not `meta.total` — dressing one as "at least 40" would understate a count that is simply
 * 40, on the screen an operator plans a shift around.
 */
export function formatTotal(total: number, isTotalExact: boolean | null, t: Translate): string {
  return isTotalExact === true
    ? formatCount(total)
    : t("support.atLeast", { count: formatCount(total) });
}

const MINUTE_S = 60;
const HOUR_S = 60 * MINUTE_S;
const DAY_S = 24 * HOUR_S;
const MONTH_S = 30 * DAY_S;
const YEAR_S = 365 * DAY_S;

/** "3 minutes ago". The exact instant rides in a `title` beside it — see {@link formatAbsolute}. */
export function formatRelative(iso: string, t: Translate): string | null {
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  const elapsedS = Math.round((at - Date.now()) / 1000);
  const magnitude = Math.abs(elapsedS);
  if (magnitude < MINUTE_S) return t("common.justNow");
  if (magnitude < HOUR_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / MINUTE_S), "minute");
  if (magnitude < DAY_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / HOUR_S), "hour");
  if (magnitude < MONTH_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / DAY_S), "day");
  if (magnitude < YEAR_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / MONTH_S), "month");
  return RELATIVE_FORMAT.format(Math.round(elapsedS / YEAR_S), "year");
}

export function formatAbsolute(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString();
}

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

export interface NoteCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly canRetry: boolean;
}

/**
 * A failed read, as something an operator can act on — the `BroadcastsScreen` rule, restated for
 * this namespace's own subjects and its own refusals.
 *
 * Branching is on the CODE, not the status. None of `FORBIDDEN`, `ORIGIN_REJECTED`,
 * `CSRF_REJECTED`, `SCHEMA_DRIFT`, 404, 422 or 409 is fixed by asking again, so none of them
 * offers a Retry: on a 403 each press writes a `permission.denied` audit row against somebody
 * who did nothing wrong, and a button that always fails is worse than no button.
 *
 * **409 is in this table and the others' is not**, because it is the refusal this namespace
 * invents: the ticket moved under the operator — usually a staffer pressing `✅ Resolve` on the
 * card in the Telegram group, which is another process entirely. The copy says the board is
 * being re-read rather than that something went wrong, and offers no retry, because the same
 * bytes lose the same race.
 */
export function noteFor(
  error: AdminQueryError,
  isStale: boolean,
  t: Translate,
  subject: string,
): NoteCopy {
  if (error.code === "FORBIDDEN") {
    return {
      tone: "denied",
      title: t("errors.query.forbiddenTitle", { subject }),
      message: t("support.notes.forbiddenMessage"),
      canRetry: false,
    };
  }

  if (error.code === "ORIGIN_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.originTitle"),
      message: t("errors.query.originMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.code === "CSRF_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.sessionEndedTitle"),
      message: t("support.notes.sessionEndedMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.code === CLIENT_ERROR_CODES.schemaDrift) {
    const paths = (error.issues ?? []).map((issue) => issue.path).join(", ");
    return {
      tone: "error",
      title: t("errors.query.driftTitle", { subject }),
      message:
        paths === ""
          ? error.message
          : t("errors.query.driftMessage", { message: error.message, paths }),
      canRetry: false,
    };
  }

  if (error.status === 404) {
    return {
      tone: "error",
      title: t("errors.query.notFoundTitle", { subject }),
      message: t("support.notes.notFoundMessage"),
      canRetry: false,
    };
  }

  if (error.status === 409) {
    return {
      tone: "stale",
      title: t("support.notes.conflictTitle"),
      message: t("support.notes.conflictMessage"),
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("errors.query.refusedFiltersTitle", { subject }),
      message: t("support.notes.refusedFiltersMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.status === 503) {
    return {
      tone: "error",
      title: t("support.notes.workerTitle"),
      message: t("support.notes.workerMessage"),
      canRetry: true,
    };
  }

  if (error.status === 429) {
    const wait =
      error.retryAfterS === null
        ? ""
        : t("errors.query.rateLimitedWait", { seconds: error.retryAfterS });
    return {
      tone: "error",
      title: t("errors.query.rateLimitedTitle", { subject }),
      message: `${error.message}${wait}`,
      canRetry: false,
    };
  }

  if (isStale) {
    return {
      tone: "stale",
      title: t("errors.query.staleTitle", { subject }),
      message: t("errors.query.staleMessage", { message: error.message }),
      canRetry: true,
    };
  }

  if (error.status === 0) {
    return {
      tone: "offline",
      title: t("errors.query.offlineTitle", { subject }),
      message: error.message,
      canRetry: true,
    };
  }

  return {
    tone: "error",
    title: t("errors.query.failedTitle", { subject }),
    message: error.message,
    canRetry: true,
  };
}
