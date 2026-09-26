/**
 * The `/api/support/tickets/**` contract, transcribed from `bayram/admin/routers/support.py`
 * over `bayram/admin/schemas/tickets.py` — **and, in the second half of this file,
 * `/api/support/groups/**` from `routers/support_groups.py` over `schemas/groups.py`.**
 *
 * The two live in one module because they are one prefix and one screen's worth of knowledge:
 * `isPostedToGroup` on a ticket and `verifiedAt` on a chat are the same question asked from
 * either end, and a reader who has just learned that the card is owed needs to be one scroll
 * from the surface that says which room it is owed to. Server-side they are separate routers
 * for a reason this file does not share — §12.1 T3 declares a permission on a router, and the
 * group writes stand on a third cell — and that split is stated where it matters, on each
 * builder below. Everything from the `/api/support/groups` banner down is that namespace.
 *
 * **The tickets, then.** Seven routes across two routers: three reads on `support.read` (**M**
 * at all four roles,
 * because the queue is what the panel exists to show) and four writes on `support.write` (**W**
 * at SUPPORT, ADMIN and OWNER — the only write cell in the matrix that starts at SUPPORT).
 * **Neither permission carries a step-up**, which is the one thing a caller here does not have
 * to plan for: there is no `STEP_UP_REQUIRED` to catch, no `subjectId` to echo back, and no
 * body to replay. `SUPPORT_WRITE` argues that at length server-side — a support operator's
 * whole job is answering customers, so withholding the reply behind a password box would leave
 * the role unable to do the thing it is named for and would push the work back into the
 * Telegram group, where there is no audit row at all.
 *
 * ## The body is the customer's own words, and it crosses in full
 *
 * **This is the one wire in the panel that carries a customer's free text unredacted, and it is
 * an argued exception rather than an oversight.** Everywhere else — `briefs.note`,
 * `briefs.approved_lyrics`, `generation_attempts.stt_transcript` — a customer's prose reaches
 * this console as a `*_chars` count and a `has_*` flag, with the plaintext routed through the
 * audited, budgeted, step-up-gated `POST /api/reveal`. Those columns hold words a customer
 * wrote *about a real third party* in order to have a song made, and an operator reading them
 * is reading something they were not addressed with.
 *
 * A ticket body is neither. The customer wrote it **to support**, deliberately, in answer to a
 * prompt that asked them to describe a problem; it is not metadata about the work item, it *is*
 * the work item; and an operator who cannot read the complaint cannot answer it. Gating it
 * would protect nobody — the same sentence is already on a card in the support group being read
 * off staff phones — and would only add an audited click to every ticket, which is the habit
 * that makes the reveal gate meaningless where it matters. `db/admin/views.py`'s
 * `SupportTicketListItem` writes that argument out in full and is the authority; this module
 * must not quietly widen it. **Nothing else on a ticket is free text**, and the two event
 * bodies that also cross whole are an operator's own note and a sentence we already sent the
 * customer.
 *
 * `body: null` is therefore never a redaction. It is a customer who tapped ⚠️ and never typed —
 * `describedAt` is the same fact as a clock, and those rows are kept, excluded from the board
 * and visible in the list.
 *
 * ## No raw Telegram id is on this wire — except the reporter's, deliberately
 *
 * {@link SupportTicketView} publishes `telegramUserId` beside its mask, exactly as `UserView`
 * does and pointedly unlike `BroadcastRecipientView`, which carries the mask alone. The
 * distinction those two draw is whether the list is a *membership decision about people* paged
 * through in bulk, or a set of records each keyed by that id. The queue is the second, twice
 * over: every `/users/**` route keys on the raw id, and the first thing an operator does with a
 * complaint is open the customer's record to answer it — a mask this SPA could not dereference
 * would make the ticket a dead end at exactly that moment.
 *
 * {@link SupportTicketEventView} is the other way round: `authorTelegramUserIdMasked` and no
 * raw value, because a timeline's author is a staffer in a Telegram group or the customer
 * already named on the ticket, and neither is a record this API can route to. The customer's
 * NAME is on neither shape and cannot be — a ticket holds no name column at all.
 *
 * ## The grammar is the server's, and it travels on every ticket
 *
 * `allowedTransitions` is computed from `bayram.support.LEGAL_STATUS_MOVES` per ticket and
 * ordered in the board's own left-to-right order. A screen renders exactly those moves and no
 * others: offering four drop targets and discovering which three are guaranteed refusals is how
 * a board teaches an operator to ignore its own errors. `features/support/ticketFormat.ts`
 * holds the client-side copy of the same table for the drag path, which needs to know what is
 * legal before a card is picked up; the two read one grammar and the server is the authority.
 *
 * ## Every move names both ends
 *
 * {@link TicketStatusRequest} carries `expectedStatus` AND `toStatus`, and the first is not a
 * convenience. The handler's `UPDATE` names it in its `WHERE` clause, so the rowcount is the
 * lock: two operators dragging one card — or an operator dragging while a staffer presses
 * ✅ Resolve on the card in the group — produce one move and one `409`, never two moves and a
 * timeline that contradicts itself. Read that refusal through {@link ticketStatusConflictOf},
 * which unpacks the status the server actually found.
 *
 * ## What each write costs, and what it does not
 *
 * Three of the four enqueue an ARQ job — the admin process holds no bot token and is
 * structurally forbidden from talking to Telegram (`ADMIN_PANEL_PLAN D10 / §4.2`) — and the
 * enqueue is unwrapped server-side, so a dead worker rolls the whole action back as a `503`
 * rather than leaving the board saying `resolved` while the group card still says `🆕 New`. A
 * NOTE enqueues nothing: it reaches nobody and changes no rendered surface. A REPLY enqueues
 * the relay and NOT a card sync, because answering a customer changes neither the ticket's
 * status nor its claim row.
 *
 * **A panel reply does not move the ticket.** In the group a reply to the card moves a `new`
 * ticket to `in_progress` — "the reply is the claim", because a staffer in a chat has no other
 * control to press. An operator here has the column controls in front of them, so an implicit
 * move would write a `status_change` nobody asked for and race the explicit one they are about
 * to make. The two surfaces differ because one of them has buttons.
 *
 * ## No reason code, on any of the four
 *
 * Every other operator action in this API takes a `ReasonedRequest`. These four deliberately do
 * not: §12.4's rule is about *destructive* actions — deleting a record, disclosing a name,
 * barring an account, minting credit — and moving a card, claiming it, writing a note and
 * answering the person who wrote to us are the ordinary work of the queue, done dozens of times
 * a shift by the role the queue exists for. A mandatory code would be answered with the same
 * member every time, which is an accountability control switching itself off while continuing
 * to look enabled. The server stamps `support_investigation` itself, and the audit row plus the
 * append-only timeline carry the accountability instead.
 */

import { z } from "zod";

import { request, type ApiFailure, type ApiResult } from "./client";
import {
  appendEach,
  appendPage,
  appendParam,
  pageMetaSchema,
  queryOf,
  type PageRequest,
} from "./pagination";
import { languageSchema, type Language } from "./users";

/* `Language` is the customer's vocabulary, declared beside `UserView` where it is first
   consumed. Imported rather than retyped: a ticket records the locale it was OPENED in, which
   is the language the reply must be written in, and two spellings of that enum would be two
   answers to "which of these people must be answered in Russian". */
export { LANGUAGE_VALUES, languageSchema, type Language } from "./users";

/* -------------------------------------------------------------------------- */
/* Names and bounds                                                            */
/* -------------------------------------------------------------------------- */

/**
 * `bayram.admin.routers.support.SUPPORT_TICKETS_PATH`. All seven routes hang off it, across
 * BOTH routers: three reads guarded by `support.read` and four writes by `support.write`, one
 * path space and one prefix.
 *
 * Declared here rather than in `api/constants.ts` alongside the other eight prefixes, and the
 * asymmetry is worth a line: this module is its only consumer and will stay so — no screen
 * composes a support URL, because the four builders below are the whole surface — so a constant
 * in the shared file would be a name every other API module has to read past. If a second
 * module ever needs it, it moves there in that change rather than in advance.
 */
export const SUPPORT_TICKETS_PREFIX = "/api/support/tickets";

/**
 * `db.models.support_ticket_event.SUPPORT_BODY_LENGTH` — what an operator may write in a note
 * or a reply.
 *
 * It is the COLUMN's bound and not a number chosen for a form, and it happens to be Telegram's
 * own single-message ceiling as well, which is not a coincidence: the column was sized so that
 * a reply this API accepts is a message Telegram will carry. Unlike a broadcast body there is
 * no second, RENDERED length to check — a campaign body is authored as Telegram HTML, so an
 * ampersand costs one character in the editor and five on the wire, whereas a ticket reply is
 * plain text the worker escapes on the way out. The operator's count and Telegram's are the
 * same count.
 */
export const MAX_TICKET_BODY_CHARS = 4_096;

/**
 * `support_tickets.assigned_admin_username` is `String(ACTOR_USERNAME_LENGTH)` — the same 64
 * that `admin_audit_log.actor_username` and `admin_users.username` use.
 *
 * Wider than {@link ADMIN_USERNAME_PATTERN}'s practical shape on purpose: the column is
 * denormalised with no foreign key, so it holds whatever an operator was called at the time,
 * including a login this panel could never create.
 */
export const MAX_TICKET_ASSIGNEE_CHARS = 64;

/**
 * `schemas.admins.ADMIN_USERNAME_PATTERN`, restated so a form refuses before a round trip.
 *
 * The assignee is **not** checked against the roster — not here and deliberately not at the
 * handler either. The column is denormalised precisely so that a deactivated or renamed
 * operator does not rewrite who worked a queue, and a validity check at write time would be a
 * rule the column does not keep and could not keep tomorrow. What is checked is the SHAPE, so a
 * value that could never name an operator is caught here rather than stored meaning nothing.
 */
export const ADMIN_USERNAME_PATTERN = /^[a-z0-9][a-z0-9._-]*[a-z0-9]$/;

/** `bayram.db.admin.sql.MAX_SEARCH_CHARS`. Over-long `q` is a 422 naming the parameter. */
export const MAX_TICKET_SEARCH_CHARS = 64;

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from `bayram.contracts`; a new member lands here first      */
/* -------------------------------------------------------------------------- */

/**
 * `SupportTicketStatus` — the four Kanban columns, **in board order**.
 *
 * `new -> in_progress -> waiting -> resolved`, and the order of this tuple is the order the
 * columns are drawn in: it is `SupportTicketStatus`' declaration order server-side, which is
 * also the order `ordered_transitions` sorts `allowedTransitions` into. A screen that sorted
 * them itself would be a second copy of that decision.
 *
 * **`waiting` means waiting on the CUSTOMER, never on us.** That is the whole reason it is a
 * column rather than a flag: a queue in which "we asked them a question three days ago" and
 * "nobody has looked at this yet" share one state is a queue whose length means nothing,
 * because the operator cannot tell which half is their backlog.
 *
 * There is no `triaged` — the act that would set it is the same act that claims the ticket —
 * and no `closed` archive, because `resolved` is already terminal and a fifth column nobody
 * drags to is a column that silently collects tickets. A ticket leaves the board by ageing out
 * of the filter, not by changing state. Starting narrow costs a code change and not DDL:
 * `enum_type` renders a plain `VARCHAR(32)` with `create_constraint` off, so a fifth status
 * later needs no migration — and would need a member here, a column entry in
 * `ticketFormat.ts` and three locale strings.
 */
export const SUPPORT_TICKET_STATUS_VALUES = [
  "new",
  "in_progress",
  "waiting",
  "resolved",
] as const;
export const supportTicketStatusSchema = z.enum(SUPPORT_TICKET_STATUS_VALUES);
export type SupportTicketStatus = z.infer<typeof supportTicketStatusSchema>;

/**
 * `SupportTicketSource` — which door the complaint came through.
 *
 * It exists to answer "where do complaints come from?" and to explain why roughly half the rows
 * carry no `orderId`: `/support` is typed from anywhere and has no order in hand, while the ⚠️
 * button under a delivered song always does. **It is never branched on afterwards** — both
 * doors file the same kind of ticket into the same queue, which is the divergence the design
 * exists to prevent, so a screen may render it and must not filter the work by it.
 */
export const SUPPORT_TICKET_SOURCE_VALUES = ["delivery_button", "support_command"] as const;
export const supportTicketSourceSchema = z.enum(SUPPORT_TICKET_SOURCE_VALUES);
export type SupportTicketSource = z.infer<typeof supportTicketSourceSchema>;

/**
 * `SupportTicketEventKind` — what one row of the append-only timeline records.
 *
 * `opened` and `described` are two kinds and not one: a customer who tapped ⚠️ and never typed
 * has an opened ticket with no description, and collapsing them would make that row
 * indistinguishable from one that never existed. `note` and `reply` are likewise kept apart by
 * the one difference that matters — whether the words reached a person — which is the same
 * split the audit taxonomy takes with `ticket.note` and `ticket.reply`.
 */
export const SUPPORT_EVENT_KIND_VALUES = [
  "opened",
  "described",
  "status_change",
  "note",
  "reply",
  "assigned",
  "group_posted",
] as const;
export const supportEventKindSchema = z.enum(SUPPORT_EVENT_KIND_VALUES);
export type SupportTicketEventKind = z.infer<typeof supportEventKindSchema>;

/**
 * `SupportAuthorKind` — who did the thing, and how accountable they are for it.
 *
 * `operator` is signed in to this panel: they have an `admin_users` row, a session, a role, an
 * IP and an `admin_audit_log` entry beside the event. `staff_group` is a person in the Telegram
 * support group, identified only by a Telegram id and a display name, whose only credential is
 * membership of a chat — their actions write an event row and NO audit row, because
 * `admin_audit_log` must not carry an actor it cannot name. The split exists so a timeline
 * cannot attribute an unaudited action to the audit log, and a screen must keep the two visibly
 * apart for the same reason.
 */
export const SUPPORT_AUTHOR_KIND_VALUES = [
  "customer",
  "operator",
  "staff_group",
  "system",
] as const;
export const supportAuthorKindSchema = z.enum(SUPPORT_AUTHOR_KIND_VALUES);
export type SupportAuthorKind = z.infer<typeof supportAuthorKindSchema>;

/* -------------------------------------------------------------------------- */
/* Responses                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One ticket — a queue row and a board card in one shape.
 *
 * Two projections were the alternative, a thin card and a fat row, and the server rejected it
 * for the reason the board and the list already share one filter set: they describe ONE
 * population, and two shapes over it is two places for "what does a card show?" to be answered
 * differently. The card renders a subset of these fields; nothing here is expensive enough to
 * justify a second query shape to avoid sending it.
 */
export const supportTicketViewSchema = z.object({
  id: z.string().uuid(),
  /**
   * The short reference the customer was given and quotes back down a phone line — the leading
   * eight characters of the ticket's own id, lowercase, and UNIQUE. It is reproducible by
   * READING the id in a log or an error context, never by computing an encoding, which is why
   * it must be rendered verbatim and never case-folded or prettified.
   */
  publicRef: z.string(),
  /** Raw AND masked, the way `UserView` publishes them — see this module's header for why. */
  telegramUserId: z.number().int(),
  telegramUserIdMasked: z.string(),
  /** The locale the ticket was OPENED in. The language a reply must be written in. */
  language: languageSchema,
  source: supportTicketSourceSchema,
  /** `null` for every `/support` ticket — roughly half of them, and not a defect. */
  orderId: z.string().uuid().nullable(),
  status: supportTicketStatusSchema,
  /**
   * **The customer's own words, in full.** `null` is not a redaction: it is a customer who
   * tapped ⚠️ and never typed, which `describedAt` says as a clock.
   */
  body: z.string().nullable(),
  describedAt: timestampSchema.nullable(),
  /**
   * Where this ticket may go next, from the SERVER's grammar rather than from a copy in
   * TypeScript, and already in the board's left-to-right order. Empty for a status with
   * nowhere to go — render that as a card with no actions, never as an error.
   */
  allowedTransitions: z.array(supportTicketStatusSchema),
  /** Denormalised, no foreign key. `null` is unclaimed. */
  assignedAdminUsername: z.string().nullable(),
  assignedAt: timestampSchema.nullable(),
  /**
   * Whether the card reached the support group. The chat and message ids are deliberately
   * absent — the admin process cannot talk to Telegram, so they are a routing detail this API
   * has no use for and publishing them would invite a future screen to try. `false` beside a
   * described body means the post is still OWED, never that the ticket was lost.
   */
  isPostedToGroup: z.boolean(),
  groupPostedAt: timestampSchema.nullable(),
  /**
   * Stamped on the way into `resolved` and **never cleared by a reopen**. A `resolvedAt` beside
   * a non-resolved status is a ticket that came back, which is the most useful thing this row
   * can say; a screen that hid it would make repeat complaints invisible.
   */
  resolvedAt: timestampSchema.nullable(),
  /** How many timeline rows exist — which tickets have been talked about, at a glance. */
  eventCount: z.number().int(),
  createdAt: timestampSchema,
  /** Last move of any kind. What a "nothing has happened here for four days" filter reads. */
  updatedAt: timestampSchema,
});
export type SupportTicketView = z.infer<typeof supportTicketViewSchema>;

export const supportTicketsPageSchema = z.object({
  items: z.array(supportTicketViewSchema),
  meta: pageMetaSchema,
});
export type SupportTicketsPage = z.infer<typeof supportTicketsPageSchema>;

/**
 * One row of the append-only timeline.
 *
 * The three author columns travel separately rather than flattened into an `author` string,
 * exactly as the table stores them — see {@link SUPPORT_AUTHOR_KIND_VALUES}. The five fields
 * the server declares with defaults are `.default(null)` here for the same reason `pageMeta`
 * does it: a build branching on `undefined` in one deployment and `null` in the next is a bug
 * waiting for a framework upgrade.
 */
export const supportTicketEventViewSchema = z.object({
  id: z.string().uuid(),
  ticketId: z.string().uuid(),
  kind: supportEventKindSchema,
  authorKind: supportAuthorKindSchema,
  /** Set for `operator`. Denormalised; a rename must not rewrite history. */
  authorAdminUsername: z.string().nullable(),
  /** Set for `customer` and `staff_group`. **Masked and never raw** — see the header. */
  authorTelegramUserIdMasked: z.string().nullable(),
  /** The staffer's `@handle` or first name, so the timeline reads as prose. */
  authorDisplayName: z.string().nullable().default(null),
  /**
   * Both ends of a move, set only on `status_change`. Two fields and not one: "it went to
   * waiting" and "it went to waiting FROM resolved" are different events, and the second is a
   * reopened ticket — the shape anybody goes looking for.
   */
  fromStatus: supportTicketStatusSchema.nullable().default(null),
  toStatus: supportTicketStatusSchema.nullable().default(null),
  /** A note or a reply; `null` on the kinds that carry no prose. */
  body: z.string().nullable().default(null),
  /**
   * **Published because its absence is the point.** A `reply` row with no relay clock is a
   * sentence that was composed and never reached anybody — the customer blocked the bot, or the
   * relay was refused by a deployment with no worker. An operator who cannot see the difference
   * reads the timeline as "we answered them" when nothing landed, which is the single worst
   * mistake available on this screen. Never render a reply without this distinction.
   */
  relayedAt: timestampSchema.nullable().default(null),
  createdAt: timestampSchema,
});
export type SupportTicketEventView = z.infer<typeof supportTicketEventViewSchema>;

/**
 * One ticket and its whole timeline — the response **every** mutation here answers with.
 *
 * **Unpaged, and oldest first.** Both are departures from this API's defaults and both are
 * deliberate: a ticket is a conversation between one customer and a handful of staff, so its
 * event count is tens at the very worst, and a conversation is read forwards.
 */
export const supportTicketDetailViewSchema = z.object({
  ticket: supportTicketViewSchema,
  events: z.array(supportTicketEventViewSchema),
});
export type SupportTicketDetailView = z.infer<typeof supportTicketDetailViewSchema>;

/** One Kanban column and how many DESCRIBED tickets are in it. */
export const supportBoardColumnViewSchema = z.object({
  status: supportTicketStatusSchema,
  count: z.number().int(),
});
export type SupportBoardColumnView = z.infer<typeof supportBoardColumnViewSchema>;

/**
 * The board's four column lengths — always four, always in {@link SUPPORT_TICKET_STATUS_VALUES}
 * order, zero-filled.
 *
 * **These counts are exact and are not `meta.total`.** A page's total is `bounded_total`, which
 * saturates at 10 000 and would make a busy column read as a ceiling; and a distribution cannot
 * be sampled, because an arbitrary ten thousand rows have an arbitrary distribution. These are
 * four `GROUP BY` buckets, so render them as plain numbers — `formatTotal`'s "at least" wording
 * belongs to the LIST's total and would understate a real count here.
 *
 * **The board excludes tickets nobody described** (`describedAt === null`), whatever the filter
 * asks: there is nothing on such a row for an operator to act on, and a column length that
 * counted them would be a backlog number that lies. Those rows are real data — they measure how
 * many people tried to complain and gave up — and the LIST is where they are reachable.
 *
 * A wrapper object rather than a bare array, because a top-level array is a shape nothing can be
 * added to later, and the board is the screen most likely to want a second number beside its
 * columns. It carries no `meta` because it is not paged and must never be.
 */
export const supportBoardViewSchema = z.object({
  columns: z.array(supportBoardColumnViewSchema),
});
export type SupportBoardView = z.infer<typeof supportBoardViewSchema>;

/* -------------------------------------------------------------------------- */
/* Requests                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Move one ticket between columns. **Carries BOTH ends of the move, which is the point.**
 *
 * `expectedStatus` is the status the board DREW the card in. The handler names it in its
 * `UPDATE`'s `WHERE` clause, so a stale board produces a `409` naming the status actually
 * found — {@link ticketStatusConflictOf} — instead of silently overwriting somebody else's
 * move. A request without it would mean "set this ticket to resolved whatever it says now",
 * which is the lost update every conditional write in this namespace exists to refuse.
 *
 * An ILLEGAL move never reaches the database: the server refuses it as a `422` before a session
 * opens, naming both ends. The two shapes a client sends by accident are a move to the status
 * the ticket is already in — nothing moves to itself, so a second Claim is a refusal rather
 * than a duplicate event — and a return to `new`, which the grammar forbids from everywhere
 * because a ticket somebody has touched is not new. Send only what `allowedTransitions` offers
 * and neither can happen.
 */
export const ticketStatusRequestSchema = z.object({
  expectedStatus: supportTicketStatusSchema,
  toStatus: supportTicketStatusSchema,
});
export type TicketStatusRequest = z.infer<typeof ticketStatusRequestSchema>;

/**
 * An internal line on the timeline. **The customer never sees this.**
 *
 * Its own model rather than a shared body with {@link TicketReplyRequest}, whose single field is
 * identical, and the duplication is deliberate: the two differ in the one way that matters —
 * whether the words reach a person — and one model behind two routes is one refactor away from
 * one route behind one model.
 *
 * The consequence to be clear-eyed about on a screen: a note is invisible to the staffers
 * working from the card in the Telegram group. That is what an internal note IS, and the place
 * to say something to them is the group.
 */
export const ticketNoteRequestSchema = z.object({
  body: z.string().min(1).max(MAX_TICKET_BODY_CHARS),
});
export type TicketNoteRequest = z.infer<typeof ticketNoteRequestSchema>;

/**
 * What to say to the customer. **These words are put in somebody's phone.**
 *
 * Nothing is escaped, trimmed or canonicalised on the way in: the worker escapes on the way
 * out, where the escaping belongs, and the reply is stored as the artefact the operator wrote.
 * Whitespace-only is refused ({@link isSendableTicketBody}) because `min(1)` alone accepts a
 * single space, which reaches the customer as an empty bubble or as a Telegram refusal nobody
 * sees.
 *
 * The reply is written first and delivered second, and the two are not the same fact: the event
 * lands with `relayedAt` null and the worker stamps it when the message actually arrives. The
 * relay job is keyed on the EVENT id, so a double-clicked Send collapses onto the job already
 * queued rather than putting the same paragraph in somebody's phone twice — but disable the
 * button while the mutation is pending anyway, because a second press is still a second event.
 */
export const ticketReplyRequestSchema = z.object({
  body: z.string().min(1).max(MAX_TICKET_BODY_CHARS),
});
export type TicketReplyRequest = z.infer<typeof ticketReplyRequestSchema>;

/**
 * Hand the ticket to an operator — possibly oneself, possibly somebody else.
 *
 * `adminUsername` is a field and not "whoever is calling", because handing a ticket over is the
 * normal case and a route that could only claim would need a second route to assign. The write
 * is **unconditional on the current holder** for the same reason: a reassignment must not be
 * refused because somebody claimed it first, and the append-only `assigned` event is what keeps
 * the history of who has had it.
 *
 * **Assigning does not move the ticket.** In the group `✋ Claim` is both acts because a staffer
 * has one button; here the operator has the column controls in front of them.
 */
export const ticketAssignRequestSchema = z.object({
  adminUsername: z
    .string()
    .min(1)
    .max(MAX_TICKET_ASSIGNEE_CHARS)
    .regex(ADMIN_USERNAME_PATTERN),
});
export type TicketAssignRequest = z.infer<typeof ticketAssignRequestSchema>;

/**
 * `_checked_body`'s rule, one layer up: a note or a reply may not be blank.
 *
 * Never trims — what is stored is what was typed — so this is a predicate for enabling a Send
 * button and never a transform to apply before sending.
 */
export function isSendableTicketBody(body: string): boolean {
  return body.trim() !== "" && body.length <= MAX_TICKET_BODY_CHARS;
}

/**
 * `ADMIN_USERNAME_PATTERN` and the column's width, as a form can apply them.
 *
 * Says only that the value COULD name an operator, never that it does: the column is
 * denormalised with no foreign key and this API does not check the roster — see
 * {@link ADMIN_USERNAME_PATTERN}.
 */
export function isAssignableUsername(username: string): boolean {
  return username.length <= MAX_TICKET_ASSIGNEE_CHARS && ADMIN_USERNAME_PATTERN.test(username);
}

/* -------------------------------------------------------------------------- */
/* Reading the refusal this namespace invents                                  */
/* -------------------------------------------------------------------------- */

/**
 * The status a move was refused against, off the `409` from `POST /{id}/status`.
 *
 * The status IS published — unlike the id in this namespace's 404s — and the difference is what
 * the caller can do with it: an operator whose drag lost a race to a staffer pressing
 * ✅ Resolve in the group needs to know it was resolved. It is the status read a moment BEFORE
 * the conditional `UPDATE` that actually refused, which is the honest thing to report rather
 * than pretending to have raced it.
 *
 * `null` for any other conflict, so a caller tells them apart by which reader answers rather
 * than by matching a message. Roll the optimistic move back and re-read; never retry — the same
 * bytes lose the same race.
 */
export function ticketStatusConflictOf(failure: ApiFailure | null): SupportTicketStatus | null {
  if (failure === null || failure.code !== "CONFLICT" || failure.details === null) return null;
  const parsed = supportTicketStatusSchema.safeParse(failure.details["status"]);
  return parsed.success ? parsed.data : null;
}

/* -------------------------------------------------------------------------- */
/* Filters                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The queue's filters. Repeats are OR within a field and AND across fields; an omitted field is
 * not sent, because absent and empty are different questions.
 *
 * **The board takes the SAME set**, so the two describe one population: a board summing to more
 * than its own queue is a real bug, and sharing the filter object is what makes it impossible.
 * The one thing the board does not honour is {@link onlyDescribed} — it forces it on.
 *
 * There is no name filter, no phone filter and no sort key, at any role. `publicRef` is matched
 * by exact lookup through `q` rather than by substring over an identifier, so a reference is
 * either known or it is not.
 */
export interface SupportTicketsFilters {
  /**
   * Ask for the bounded count as well. Off by default because it is a second query, and it
   * arrives as the `total`/`isTotalExact` pair — render both halves or neither.
   */
  readonly withTotal?: boolean;
  /** REPEATED on the wire. Empty = do not filter. */
  readonly status?: readonly SupportTicketStatus[];
  /** REPEATED. Which door the complaint came through — a fact, never a queue of its own. */
  readonly source?: readonly SupportTicketSource[];
  /**
   * REPEATED. The language the ticket was OPENED in, not the account's language today — this is
   * how an operator who speaks Russian finds the tickets they can actually answer.
   */
  readonly language?: readonly Language[];
  /**
   * EXACT `assigned_admin_username`, and deliberately not folded into {@link q}. "Show me
   * Dilnoza's tickets" and "find the ticket mentioning Dilnoza" are two questions, and a
   * substring search answering both would put every ticket whose body names an operator into
   * that operator's queue.
   */
  readonly assignedTo?: string | null;
  /** EXACT. "This customer says they wrote to you" — the first question of any escalation. */
  readonly telegramUserId?: number | null;
  /**
   * `support_tickets.created_at` — when the customer TAPPED — half-open `[from, to)`, RFC 3339.
   * Deliberately not `describedAt`: a window on a nullable column silently drops every
   * tapped-and-never-typed ticket from a range the operator believes covers everything, which
   * is precisely the population a date filter is opened to measure.
   */
  readonly from?: string | null;
  readonly to?: string | null;
  /**
   * Substring over the public reference AND the body — the one search in this API that reaches
   * a customer's own words, and it is allowed to only because the same rows publish those words
   * in full on the response it returns. Cap the INPUT at {@link MAX_TICKET_SEARCH_CHARS}; an
   * over-long value is a 422 naming the parameter, and truncating it here would hide that
   * behind a page nobody asked for.
   */
  readonly q?: string | null;
  /**
   * Drop the tickets nobody described. **`false` by default**, so the queue shows everything —
   * those rows are the only place abandonment is visible, and the board already hides them.
   */
  readonly onlyDescribed?: boolean;
}

/**
 * The filter set as a query string.
 *
 * `withTotal` and `onlyDescribed` are sent only when `true`, because the server's default for
 * both is `false`: sending `false` would be a second spelling of the same request — two
 * react-query keys and two lines in the request log for one question. Every other filter goes
 * through `appendParam`/`appendEach`, which omit absent, null and empty values.
 */
function ticketsQuery(filters: SupportTicketsFilters, page: PageRequest): string {
  const params = new URLSearchParams();
  if (filters.withTotal === true) params.append("withTotal", "true");
  if (filters.onlyDescribed === true) params.append("onlyDescribed", "true");
  appendEach(params, "status", filters.status);
  appendEach(params, "source", filters.source);
  appendEach(params, "language", filters.language);
  appendParam(params, "assignedTo", filters.assignedTo);
  appendParam(params, "telegramUserId", filters.telegramUserId);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendParam(params, "q", filters.q);
  appendPage(params, page);
  return queryOf(params);
}

/** The board takes the filters and no paging — it is a distribution, not a page. */
function boardQuery(filters: SupportTicketsFilters): string {
  const params = new URLSearchParams();
  appendEach(params, "status", filters.status);
  appendEach(params, "source", filters.source);
  appendEach(params, "language", filters.language);
  appendParam(params, "assignedTo", filters.assignedTo);
  appendParam(params, "telegramUserId", filters.telegramUserId);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendParam(params, "q", filters.q);
  return queryOf(params);
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The route templates, as a failure names them.
 *
 * `board` is registered BEFORE `detail` server-side, and the ordering is load-bearing rather
 * than tidy: both are a single segment under `/support/tickets`, so a literal registered second
 * gives the caller FastAPI's 422 about a malformed UUID instead of their board.
 */
export const SUPPORT_ENDPOINT = {
  board: "GET /api/support/tickets/board",
  list: "GET /api/support/tickets",
  detail: "GET /api/support/tickets/{ticketId}",
  status: "POST /api/support/tickets/{ticketId}/status",
  notes: "POST /api/support/tickets/{ticketId}/notes",
  reply: "POST /api/support/tickets/{ticketId}/reply",
  assign: "POST /api/support/tickets/{ticketId}/assign",
} as const;

/**
 * A ticket is addressed by its UUID, and the id is passed through untouched.
 *
 * Every path parameter on this API is asserted to be a `UUID` or an `int`, so `publicRef` — the
 * string a customer reads down the phone — is a LOOKUP value (`?q=`) and never an address.
 */
function ticketPath(ticketId: string): string {
  return `${SUPPORT_TICKETS_PREFIX}/${encodeURIComponent(ticketId)}`;
}

/**
 * The four column lengths. Exact counts, described tickets only, never paged.
 *
 * **This read writes nothing and must never start to.** It is the one route a "mark the queue as
 * seen" feature would naturally attach itself to, and `test_no_get_route_changes_domain_state`
 * snapshots every domain table around it — correctly, because a screen that polls would write a
 * row every few seconds.
 */
export function getSupportBoard(
  filters: SupportTicketsFilters,
  signal?: AbortSignal,
): Promise<ApiResult<SupportBoardView>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.board,
    path: `${SUPPORT_TICKETS_PREFIX}/board${boardQuery(filters)}`,
    schema: supportBoardViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * One keyset page of tickets, newest first, **with the complaint on each row**.
 *
 * The body travels on the list and not only on the detail, which is a departure from how every
 * other free-text column in this API is handled and is argued in this module's header. The
 * operational half: a queue whose rows say only "a ticket, 14:02, uz" cannot be triaged without
 * opening fifty of them, which is fifty audited round trips to do the one thing the screen is
 * for.
 *
 * Keyset only — there is no page number and no offset, and `limit` outside `[1, 200]` is a 422
 * rather than a clamp.
 */
export function listSupportTickets(
  filters: SupportTicketsFilters,
  page: PageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SupportTicketsPage>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.list,
    path: `${SUPPORT_TICKETS_PREFIX}${ticketsQuery(filters, page)}`,
    schema: supportTicketsPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * One ticket and its whole timeline, oldest first. 404 for an id we hold nothing on, and the
 * refusal does not echo the id back — an identifier is not a hint worth confirming.
 */
export function getSupportTicket(
  ticketId: string,
  signal?: AbortSignal,
): Promise<ApiResult<SupportTicketDetailView>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.detail,
    path: ticketPath(ticketId),
    schema: supportTicketDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Move a ticket between columns. Answers with the ticket and its new timeline row.
 *
 * `409 CONFLICT` when the row has moved since the board drew it — read it through
 * {@link ticketStatusConflictOf}, roll the optimistic move back, and show the operator what the
 * ticket actually says. `422` for a move the grammar forbids, which
 * `allowedTransitions` exists to make unreachable.
 *
 * `503` when the worker is unreachable: the enqueue is unwrapped server-side, so the whole
 * action rolls back rather than leaving this board and the group card permanently disagreeing
 * about whether the ticket is finished. That is a retry an operator makes, not one to automate.
 */
export function moveSupportTicket(
  ticketId: string,
  body: TicketStatusRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SupportTicketDetailView>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.status,
    path: `${ticketPath(ticketId)}/status`,
    method: "POST",
    body,
    schema: supportTicketDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Append an internal line to the timeline. **Reaches nobody, and enqueues nothing.**
 *
 * The only one of the four writes that changes no state outside the event table, which is why
 * it is also the only one that cannot fail with a `503` for want of a worker.
 */
export function addSupportTicketNote(
  ticketId: string,
  body: TicketNoteRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SupportTicketDetailView>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.notes,
    path: `${ticketPath(ticketId)}/notes`,
    method: "POST",
    body,
    schema: supportTicketDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Answer the customer. **The one call on this surface that leaves the building.**
 *
 * The response's new `reply` event carries `relayedAt: null` — the worker stamps it when the
 * message actually reaches the customer's chat. A screen must render that difference and must
 * not report a composed reply as a delivered one.
 *
 * Does not move the ticket: see this module's header on why the panel and the group differ.
 */
export function replyToSupportTicket(
  ticketId: string,
  body: TicketReplyRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SupportTicketDetailView>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.reply,
    path: `${ticketPath(ticketId)}/reply`,
    method: "POST",
    body,
    schema: supportTicketDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Record who has this ticket. Unconditional on the current holder, and it moves nothing.
 *
 * The card in the group is re-rendered because it carries the claim row — the staffer reading
 * it needs to know somebody has picked this up, which is most of what the card is for.
 */
export function assignSupportTicket(
  ticketId: string,
  body: TicketAssignRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SupportTicketDetailView>> {
  return request({
    endpoint: SUPPORT_ENDPOINT.assign,
    path: `${ticketPath(ticketId)}/assign`,
    method: "POST",
    body,
    schema: supportTicketDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* ========================================================================== */
/* The support GROUP — `/api/support/groups`, three routes across two routers  */
/* ========================================================================== */

/**
 * ## Why this namespace exists at all, and why its shapes look unlike everything above
 *
 * **Telegram has no "list my groups" API.** A bot cannot enumerate the chats it belongs to; the
 * only way it ever learns a group exists is a `my_chat_member` update, delivered when its OWN
 * membership changes. A group the bot was already sitting in on the day this shipped produces
 * no such event, appears in no list, and cannot be backfilled from anything.
 * `routers/support_groups.py` is bent around that fact rather than around REST tidiness, and so
 * is everything below it: the list is **unpaged**, a pasted chat id is a first-class route
 * rather than a debugging convenience, and "Telegram says the bot is a member" and "the bot has
 * been PROVED able to post" are two different fields on every row.
 *
 * This replaces `BAYRAM_SUPPORT_GROUP_CHAT_ID`, an environment variable that needed a redeploy
 * to change. The database selection is now the only authority — there is no seed, no pin and no
 * precedence rule to reason about.
 *
 * ## Read is `support.read`; the two writes are `support.group.write`
 *
 * Every role holds the read, VIEWER included: "where do my tickets go?" is a question an
 * operator must be able to answer without being able to change the answer, and the rows it is
 * answered from hold no customer at all. The writes are a THIRD permission — not `support.write`
 * — because the blast radius is different in kind: a support operator answering a complaint
 * affects one customer, and repointing the inbox publishes every future complaint into whatever
 * room was chosen, invisibly, until somebody notices. ADMIN and OWNER, **no step-up**, so there
 * is no `STEP_UP_REQUIRED` to catch and no body to replay — the audit row carries the
 * accountability, exactly as `broadcast.write` argues.
 *
 * ## Four things a screen over this contract must get right
 *
 * 1. **The badge comes from `verifiedAt`/`verificationError`, NEVER from `botStatus`.**
 *    `botStatus` is what Telegram last said, at the instant it said it — evidence, never
 *    permission. An administrator can have `can_post_messages` taken away with no membership
 *    transition sent at all, and a `manual` row has never had a transition in the first place.
 *    There is deliberately no `isVerified` boolean on the wire because the screen needs THREE
 *    states, not two — see {@link verificationStateOf}.
 * 2. **A `200` from `/select` does not mean it works.** The admin process holds no bot token
 *    (`ADMIN_PANEL_PLAN D10 / §4.2`), so a selection is a database write plus an ARQ job; the
 *    worker is what finds out. The row goes to "checking…", never straight to verified.
 * 3. **`source` must be rendered.** `membership_event` is Telegram's own word that the bot is in
 *    the room; `manual` is a number somebody typed. Drawing them identically presents a typo
 *    with the confidence of a fact, and the two values exist only because of the constraint at
 *    the top of this comment.
 * 4. **`threadId` travels WITH the selection.** `select_support_group` sets it from the request
 *    on every call, so re-selecting a group without it CLEARS the topic. A form that drops the
 *    field on an edit meaning "leave it alone" moves the inbox out of the topic it was in.
 */

/**
 * `bayram.admin.routers.support_groups.SUPPORT_GROUPS_PATH`. All three routes hang off it.
 *
 * Declared here beside {@link SUPPORT_TICKETS_PREFIX} rather than in `api/constants.ts`, for the
 * same reason: this module is its only consumer, because the three builders below are the whole
 * surface and no screen composes one of these URLs.
 */
export const SUPPORT_GROUPS_PREFIX = "/api/support/groups";

/**
 * The floor for a chat id **on this side of the wire**, and it is not the server's.
 *
 * `bot_chats.chat_id` is `BIGINT`, so `schemas/groups.py` bounds it at `-(2**63)`. A JavaScript
 * number cannot hold that value exactly, and that is the whole point of restating the bound
 * rather than transcribing it: every integer below `Number.MIN_SAFE_INTEGER` has ALREADY been
 * rounded by the time this code could compare it, whether it came from `JSON.parse` or from a
 * digit somebody typed. So the client's floor is the tighter one — a value outside it is an id
 * this bundle cannot name, and naming a chat that does not exist is exactly the failure a
 * support inbox must not have.
 *
 * There is no ceiling constant: a chat id is bounded above by `< 0`, which is the stronger rule
 * and the one {@link parseChatIdInput} refuses on.
 */
export const MIN_CHAT_ID = Number.MIN_SAFE_INTEGER;

/**
 * A forum topic id is a Telegram MESSAGE id — the id of the message that opened the topic — so
 * it is positive, and the same rounding argument caps it at the safe-integer ceiling here.
 *
 * `0` is refused rather than read as "no topic": `null` is how this API says *the group itself*,
 * and a zero in `thread_id` would be a topic id Telegram has never issued, posted into by a
 * worker with no way to tell it from a real one.
 */
export const MAX_THREAD_ID = Number.MAX_SAFE_INTEGER;

/** `db.models.bot_chat.BOT_CHAT_TITLE_LENGTH` — Telegram's own cap on a chat title. */
export const MAX_GROUP_TITLE_CHARS = 128;

/** `db.models.bot_chat.BOT_CHAT_USERNAME_LENGTH` — a public supergroup's `@handle`. */
export const MAX_GROUP_USERNAME_CHARS = 32;

/**
 * `db.models.bot_chat.VERIFICATION_ERROR_LENGTH`.
 *
 * Restated because of what these 200 characters CONTAIN. The migrated-group message names the
 * group's NEW chat id as a bare number an operator copies back into the paste field, and that is
 * the entire recovery path for a group Telegram upgraded under us. **Never truncate this string
 * in a UI**; if it does not fit, wrap it.
 */
export const MAX_VERIFICATION_ERROR_CHARS = 200;

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from `bayram.contracts`                                    */
/* -------------------------------------------------------------------------- */

/**
 * `BotChatType` — three members, and `private` is absent on purpose.
 *
 * Telegram's `chat.type` has four values and this enum carries three. A private chat is a
 * conversation with a PERSON, recorded against `users` by a different `my_chat_member`
 * registration, and a private chat reaching `bot_chats` would mean the two registrations had
 * stopped being disjoint. Leaving it out is what makes that unrepresentable rather than merely
 * unwritten — and it is also why a non-negative chat id can be refused by this client before a
 * round trip.
 *
 * `channel` is included even though nobody would deliberately pick one as the support inbox: the
 * bot can be added to a channel as an administrator and Telegram sends the same update, so a
 * type this enum could not spell would be a row the recorder had to drop.
 */
export const BOT_CHAT_TYPE_VALUES = ["group", "supergroup", "channel"] as const;
export const botChatTypeSchema = z.enum(BOT_CHAT_TYPE_VALUES);
export type BotChatType = z.infer<typeof botChatTypeSchema>;

/**
 * `BotChatStatus` — the bot's standing, in Telegram's vocabulary, **which is not a closed set**.
 *
 * Five are what Telegram sends today; `unknown` is the sixth and is the reason the column is
 * safe to persist. The recorder turns a status it does not recognise into an `unknown` row plus
 * a warning naming it, rather than dropping the update — a filter that matched only the five we
 * know about is how we would never learn the vocabulary had moved.
 *
 * **Evidence, never permission.** See this section's header: the answer to "can the bot post
 * here" is `verifiedAt` and nothing else.
 */
export const BOT_CHAT_STATUS_VALUES = [
  "member",
  "administrator",
  "restricted",
  "left",
  "kicked",
  "unknown",
] as const;
export const botChatStatusSchema = z.enum(BOT_CHAT_STATUS_VALUES);
export type BotChatStatus = z.infer<typeof botChatStatusSchema>;

/**
 * `BotChatSource` — Telegram's own word that the bot is in this room, or an operator's claim.
 *
 * These two values exist ONLY because Telegram has no "list my groups" API. A `membership_event`
 * row was written from an update Telegram sent; a `manual` row is a number somebody typed, with
 * an inferred `chatType`, `botStatus: "unknown"` and nothing in `verifiedAt` until a job has
 * been and tried. **A screen must draw them differently.**
 */
export const BOT_CHAT_SOURCE_VALUES = ["membership_event", "manual"] as const;
export const botChatSourceSchema = z.enum(BOT_CHAT_SOURCE_VALUES);
export type BotChatSource = z.infer<typeof botChatSourceSchema>;

/* -------------------------------------------------------------------------- */
/* Responses                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * A 64-bit chat or topic id, checked for the one thing JSON cannot promise.
 *
 * `bot_chats.chat_id` and `thread_id` are `BIGINT`, and JSON has no integer width: a value wider
 * than 2^53 is parsed into the nearest double and silently becomes a DIFFERENT number. Any such
 * value is outside the safe range by construction, so `.safe()` catches exactly the rows this
 * bundle would otherwise render — and post to — under an id Telegram never issued. The failure
 * is a `SCHEMA_DRIFT` naming the field, which is the honest outcome: a chat we cannot name is
 * not a chat we can offer as the support inbox.
 *
 * Real Telegram ids are around thirteen digits, so this never fires in practice. It is here for
 * the case where it would matter most and be least visible.
 */
const chatIdSchema = z.number().int().safe();

/**
 * One chat the bot knows it is in.
 *
 * **Every column of the table crosses, and this is the only view in this API that can say that.**
 * It is not an exception to the redaction rule, it is a record the rule has nothing to say
 * about: there is no customer anywhere on this row. The one field that would have been a person
 * — `my_chat_member.from_user`, who added the bot — is the field `bot_chats` deliberately does
 * not store, which is what keeps every column here about a ROOM. So there is no id to mask and
 * no `*Chars` count standing in for a string.
 *
 * The only human name on the row is `selectedByUsername`, and it is a colleague's.
 */
export const supportGroupViewSchema = z.object({
  /** Telegram's own id and the table's primary key. **Negative for every row.** */
  chatId: chatIdSchema,
  chatType: botChatTypeSchema,
  /**
   * What the group calls itself, or `null` until something learns it — which for a pasted id
   * means until the verification job's `getChat` runs. The title is the only way an operator
   * tells four negative numbers apart, so a missing one is a fact to render rather than a hole
   * to fill with the id again.
   */
  title: z.string().max(MAX_GROUP_TITLE_CHARS).nullable().default(null),
  /** The public `@handle`. `null` for every private group, which is most of them. */
  username: z.string().max(MAX_GROUP_USERNAME_CHARS).nullable().default(null),
  /** **Evidence, never permission.** Never the source of a green badge. */
  botStatus: botChatStatusSchema,
  /** Telegram's word, or an operator's claim. **Render it.** */
  source: botChatSourceSchema,
  /**
   * The selection. At most one row in a response holds `true`, enforced by a partial unique
   * index rather than by whoever wrote the last endpoint — which is also why there is no
   * separate `selected` field beside the list: a second answer to "which one is it?" is a second
   * thing to disagree with the first.
   */
  isSupportGroup: z.boolean(),
  /** The forum topic cards go into, or `null` for the group itself. */
  threadId: chatIdSchema.nullable().default(null),
  /**
   * When the bot was last PROVED able to post here, by a job that actually tried. `null` means
   * nobody has checked since this row last changed — where every fresh selection sits, and where
   * a selection stays for ever on a deployment with no worker.
   */
  verifiedAt: timestampSchema.nullable().default(null),
  /**
   * Why the last check failed, in **English operator prose written by the worker**.
   *
   * Render it verbatim. It is staff copy and not a catalogue key: there is nothing to map it to,
   * translating it would mean the panel inventing a verdict Telegram did not give, and the
   * migrated-group message carries the group's NEW id as a bare number that is the whole
   * recovery path. Mutually exclusive with {@link verifiedAt}.
   */
  verificationError: z.string().max(MAX_VERIFICATION_ERROR_CHARS).nullable().default(null),
  /**
   * The operator's login, denormalised with no foreign key: a rename must not rewrite who
   * repointed the support inbox.
   */
  selectedByUsername: z.string().max(MAX_TICKET_ASSIGNEE_CHARS).nullable().default(null),
  /**
   * **NOT cleared when a chat is unselected.** "This was once the support group, chosen by this
   * person, on that day" is the most useful thing to know about a chat somebody is looking at
   * while wondering where last month's tickets went.
   */
  selectedAt: timestampSchema.nullable().default(null),
  /**
   * TELEGRAM's clocks — `ChatMemberUpdated.date` from the first and most recent membership
   * updates — and never this system's. For a `manual` row both are the instant the id was
   * pasted, which is the only instant such a row has.
   */
  firstSeenAt: timestampSchema,
  lastSeenAt: timestampSchema,
  /**
   * OURS: when this process wrote the row and when it last changed it. Published beside the two
   * above rather than instead of them, because the gap is real —
   * `delete_webhook(drop_pending_updates=True)` throws away updates that arrived while the bot
   * was down, so a row can be written long after the event it describes.
   */
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
});
export type SupportGroupView = z.infer<typeof supportGroupViewSchema>;

/**
 * Every chat in the directory, **selected one first. Unpaged, and it always will be.**
 *
 * No `meta`, no cursor, no `withTotal`. `list_bot_chats` returns the whole table by
 * construction: the population is a handful of rows in every deployment this product will have,
 * because it fills one row at a time from `my_chat_member` updates and from ids an operator
 * typed. A keyset cursor over four rows would answer the screen's one question on page two.
 *
 * A wrapper object rather than a bare array, because a top-level array is a shape nothing can be
 * added to later without breaking every client that indexed it.
 */
export const supportGroupsResponseSchema = z.object({
  groups: z.array(supportGroupViewSchema),
});
export type SupportGroupsResponse = z.infer<typeof supportGroupsResponseSchema>;

/**
 * What one press of Select actually did — the half a client cannot work out for itself.
 *
 * `previousChatId` is the chat the tickets were taken away from. By the time the response is
 * built the selection has been cleared and set inside one transaction, so it is unreadable from
 * the directory and is carried out of the writer instead.
 *
 * **Nothing here says the selection WORKS.** The admin process cannot talk to Telegram; it
 * reports what it recorded and enqueues the job that will find out.
 */
export const supportGroupSelectionViewSchema = z.object({
  chatId: chatIdSchema,
  /**
   * `null` when nothing was selected before, and it **may equal `chatId`** — re-selecting the
   * same group to change its topic is an ordinary act, not a no-op. Which is why {@link moved}
   * is published rather than inferred by comparing the two.
   */
  previousChatId: chatIdSchema.nullable().default(null),
  threadId: chatIdSchema.nullable().default(null),
  /** `true` when this call inserted a `manual` row for an id the directory did not hold. */
  created: z.boolean(),
  /**
   * `true` when future cards will arrive somewhere they were not arriving before. Derived
   * server-side from the pair above so the panel's sentence and the audit row's cannot disagree
   * about whether the inbox actually moved.
   */
  moved: z.boolean(),
});
export type SupportGroupSelectionView = z.infer<typeof supportGroupSelectionViewSchema>;

/** The directory as it now stands, plus what the press did to it. */
export const supportGroupSelectResponseSchema = z.object({
  groups: z.array(supportGroupViewSchema),
  selection: supportGroupSelectionViewSchema,
});
export type SupportGroupSelectResponse = z.infer<typeof supportGroupSelectResponseSchema>;

/**
 * The directory with nothing selected, and which chat that used to be.
 *
 * `clearedChatId` is `null` when there was nothing to clear, and that case is a **200 rather
 * than a 404**: "no group is selected" is the state the caller asked for, it is supported rather
 * than broken — tickets keep working, only the group post stops — and answering a second press
 * with an error would report a failure for arriving at exactly the requested outcome.
 */
export const supportGroupClearResponseSchema = z.object({
  groups: z.array(supportGroupViewSchema),
  clearedChatId: chatIdSchema.nullable().default(null),
});
export type SupportGroupClearResponse = z.infer<typeof supportGroupClearResponseSchema>;

/* -------------------------------------------------------------------------- */
/* Requests                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Point the support inbox at this chat, and optionally at one topic inside it.
 *
 * **One endpoint takes this body whether or not the chat is already known**, which is the shape
 * of the feature rather than a convenience. A group the bot was already sitting in can never be
 * discovered, so a pasted id is the only route to it; a separate "add a chat" call would invent
 * a state — added, unselected, unverified, unowned — that means nothing here. An id the
 * directory has never heard of is recorded as `source: "manual"` by the same call that selects
 * it, and the verification job is what tells the truth about the claim.
 *
 * There is no `reasonCode`, on either write. §12.4's rule is about DESTRUCTIVE actions;
 * repointing the inbox destroys nothing, discloses nothing, and is undone by selecting the
 * previous group again. The audit row — which names the actor, their role, their IP, the chat
 * selected AND the chat the tickets were taken away from — carries the accountability.
 */
export const supportGroupSelectRequestSchema = z.object({
  /** NEGATIVE, always. {@link parseChatIdInput} refuses the rest before a round trip. */
  chatId: z.number().int().safe().negative().gte(MIN_CHAT_ID),
  /**
   * The forum topic, or absent for the group itself — the ordinary case, because most groups
   * are not forums.
   *
   * **Sending it is how it is kept.** Omitting it on a re-select clears the topic, by design:
   * the topic travels with the selection and "the group, no topic" has to be expressible.
   */
  threadId: z.number().int().safe().positive().lte(MAX_THREAD_ID).optional(),
});
export type SupportGroupSelectRequest = z.infer<typeof supportGroupSelectRequestSchema>;

/* -------------------------------------------------------------------------- */
/* Reading a row, and reading what an operator typed                           */
/* -------------------------------------------------------------------------- */

/**
 * The three states a row's verification can be in. **Not two.**
 *
 * There is deliberately no `isVerified` boolean on the wire, because a boolean collapses the two
 * states that are not "proved" into one and loses the only one an operator can act on:
 *
 *  - `verified`  — a job posted a message into this chat and it landed. A clock says when.
 *  - `failed`    — a job tried and could not. {@link SupportGroupView.verificationError} says
 *                  why, in words, and it is the sentence an operator acts on.
 *  - `checking`  — **both null.** Nobody has checked since this row last changed. Every fresh
 *                  selection is here for as long as the worker takes, every pasted id is here
 *                  until a job runs, and a deployment with no worker at all stays here for ever.
 *
 * The server keeps the first two mutually exclusive — a verdict writes one and clears the other
 * — so `checking` is exactly "neither". This function is the only place that rule is spelled in
 * TypeScript; a screen that re-derived it would eventually render a row that is both.
 *
 * **`botStatus` is not consulted and must never be.** It is what Telegram last said, at the
 * instant it said it: an administrator can lose `can_post_messages` with no membership
 * transition sent, and a `manual` row has never had one. A green badge drawn from it is a chat
 * the panel claims works and the bot cannot write a word into.
 */
export type SupportGroupVerification = "verified" | "failed" | "checking";

export function verificationStateOf(group: SupportGroupView): SupportGroupVerification {
  if (group.verificationError !== null) return "failed";
  return group.verifiedAt === null ? "checking" : "verified";
}

/**
 * A chat id as an operator typed it, or `null` if it is not one.
 *
 * Every refusal here is a refusal the server would also make, taken before a round trip — and
 * one of them is the reason the whole check exists. **A non-negative Telegram id is a PRIVATE
 * chat**, which is to say a person: an operator who pastes their own user id must be told they
 * pasted a person, rather than have the support inbox quietly pointed at a direct-message thread
 * where every ticket card is visible to exactly one human being and to nobody else.
 * `BotChatType` has no `private` member precisely so that cannot be recorded, and this is the
 * same rule said early enough to be a sentence under a field instead of a 422.
 *
 * Deliberately strict about the TEXT as well: a chat id is pasted, and `Number("-100 123")`,
 * `Number("")` and `Number("-1e14")` all produce numbers that are not what was on the clipboard.
 * Leading and trailing whitespace is forgiven because a paste carries it; nothing else is.
 */
export function parseChatIdInput(text: string): number | null {
  const trimmed = text.trim();
  if (!/^-\d{1,19}$/.test(trimmed)) return null;
  const value = Number(trimmed);
  if (!Number.isSafeInteger(value) || value >= 0 || value < MIN_CHAT_ID) return null;
  return value;
}

/**
 * A forum topic id as an operator typed it, or `null` if it is not one.
 *
 * Positive, because a topic id is the id of the message that opened the topic. `0` is refused
 * rather than read as "no topic" — an empty field is how this form says *the group itself*, and
 * a zero stored in `thread_id` would be a topic id Telegram has never issued.
 */
export function parseThreadIdInput(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d{1,19}$/.test(trimmed)) return null;
  const value = Number(trimmed);
  if (!Number.isSafeInteger(value) || value <= 0 || value > MAX_THREAD_ID) return null;
  return value;
}

/**
 * The index a `409` from `/select` names, off the failure's details.
 *
 * Two operators pressing Select in the same instant each read one selected row, each clear the
 * row they read and each set their own; under READ COMMITTED both are legal right up to the
 * commit, where the partial unique index refuses the second. The loser is told to look again —
 * the WINNING chat is deliberately not published, because the handler lost at the index and
 * would need a second read inside an aborted transaction to know what won.
 *
 * `null` for any other conflict, so a caller tells them apart by which reader answers rather
 * than by matching a message. Re-read the directory; never retry, because the same bytes lose
 * the same race.
 */
export function supportGroupConflictIndexOf(failure: ApiFailure | null): string | null {
  if (failure === null || failure.code !== "CONFLICT" || failure.details === null) return null;
  const index = failure.details["index"];
  return typeof index === "string" ? index : null;
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The three route templates, as a failure names them.
 *
 * `select` and `clear` are literal segments and this namespace takes NO path parameter, so
 * there is no registration-order trap of the kind `board` and `detail` have one route space
 * along. The chat id travels in the BODY, which is a decision rather than an accident of the
 * verb: in a path it would be validated by a converter that knows only "int", so a pasted user
 * id — a person — would reach the handler and be refused inside a transaction that had already
 * cleared the previous selection.
 */
export const SUPPORT_GROUP_ENDPOINT = {
  list: "GET /api/support/groups",
  select: "POST /api/support/groups/select",
  clear: "POST /api/support/groups/clear",
} as const;

/**
 * Every chat the bot knows it is in, the selected one first. `support.read`, so every role.
 *
 * **This read writes nothing and must never start to.** It is the route a "last checked at"
 * stamp would naturally attach itself to, and `test_no_get_route_changes_domain_state` snapshots
 * every domain table around it — correctly, because a screen that polled would write a row every
 * few seconds.
 */
export function listSupportGroups(
  signal?: AbortSignal,
): Promise<ApiResult<SupportGroupsResponse>> {
  return request({
    endpoint: SUPPORT_GROUP_ENDPOINT.list,
    path: SUPPORT_GROUPS_PREFIX,
    schema: supportGroupsResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Point the support inbox at a chat — known or pasted — and enqueue the job that checks it.
 *
 * **A 200 is not a success report.** It says the selection was recorded and a verification job
 * was queued; whether the bot can post there is a question only the worker can answer. Move the
 * row to "checking…" and let `verifiedAt`/`verificationError` say what happened.
 *
 * The refusals, and what each one means for a form:
 *
 *  - `422` naming `chatId` — a non-negative id (a person) or one outside `BIGINT`.
 *    {@link parseChatIdInput} makes this unreachable from a well-built field.
 *  - `422` naming `threadId` — a zero or a negative topic. `null` is how "no topic" is said.
 *  - `422` for any extra field: the server's models are `extra="forbid"`.
 *  - `403 FORBIDDEN` — **never `STEP_UP_REQUIRED`** — for a role without `support.group.write`.
 *    Say which permission is missing, in this section's own words.
 *  - `409 CONFLICT` — a concurrent double press. {@link supportGroupConflictIndexOf}.
 *  - `503` — the deployment has no worker. **The selection still happened and is committed**:
 *    the enqueue follows the commit deliberately, because the race the other way round was a
 *    critical defect in this feature's sibling. Re-read the directory rather than treating it as
 *    a failed write.
 */
export function selectSupportGroup(
  body: SupportGroupSelectRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SupportGroupSelectResponse>> {
  return request({
    endpoint: SUPPORT_GROUP_ENDPOINT.select,
    path: `${SUPPORT_GROUPS_PREFIX}/select`,
    method: "POST",
    body,
    schema: supportGroupSelectResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Unselect the support group. **Tickets keep working; only the group post stops.**
 *
 * Takes NO body, enqueues nothing — there is no room to verify and no card to render — and is
 * idempotent: clearing when nothing is selected is a 200 with `clearedChatId: null`.
 *
 * `selectedAt`, `selectedByUsername` and `threadId` are left standing on the row; only the
 * boolean moves. Re-selecting that chat later keeps the topic it always had.
 */
export function clearSupportGroup(
  signal?: AbortSignal,
): Promise<ApiResult<SupportGroupClearResponse>> {
  return request({
    endpoint: SUPPORT_GROUP_ENDPOINT.clear,
    path: `${SUPPORT_GROUPS_PREFIX}/clear`,
    method: "POST",
    /* An empty object rather than no body at all. The handler declares no body parameter, so
       nothing parses this and no `extra="forbid"` model sees it; what it buys is that every
       POST this client sends carries a JSON body beside the `Content-Type` it always sets —
       a `Content-Type: application/json` with zero bytes after it is the shape proxies and
       WSGI-era middleware disagree about, and this is the one call that would have it. */
    body: {},
    schema: supportGroupClearResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
