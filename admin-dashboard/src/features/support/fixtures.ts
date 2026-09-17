/**
 * Ticket fixtures for the two Support screens' tests — and, at the foot of the file, chat
 * directory fixtures for the Support group dialog.
 *
 * The two sets share this module rather than splitting because they share one rule, stated once
 * below and enforced by construction in both halves: a fixture must be a shape the SERVER can
 * actually produce. A ticket whose `allowedTransitions` contradict its status and a chat row
 * carrying both a `verifiedAt` and a `verificationError` are the same mistake, and both would
 * let a test prove a rendering that cannot happen.
 *
 * Built through the REAL schemas' types rather than as loose object literals, exactly as
 * `features/broadcasts/fixtures.ts` is — so a field the server adds or renames breaks these
 * here, at `npm run typecheck`, rather than as a screen quietly rendering `undefined` under a
 * test that still passes.
 *
 * Two invariants are maintained by construction rather than left to each call site, because
 * both of them are things a board test would otherwise assert against a shape the server can
 * never produce:
 *
 *  - **`allowedTransitions` follows `status`.** The server derives it per ticket from
 *    `bayram.support.LEGAL_STATUS_MOVES`, so a fixture that said `status: "resolved"` and left
 *    the `new` row's three exits behind would let a test pass while dragging a resolved ticket
 *    into `waiting` — a move both the grammar and the handler refuse. {@link makeTicket} reads
 *    the same table `ticketFormat.ts` publishes and fills it in; an override still wins, which
 *    is how the "a stale bundle carries no transitions" case is written.
 *  - **`describedAt` and `body` travel together.** A described ticket has words and an
 *    undescribed one has neither — `null` body beside a `describedAt` clock is a row the bot
 *    cannot write, and a fixture in that shape would prove a board behaviour that cannot
 *    happen. {@link makeUndescribedTicket} is the honest way to ask for the other case.
 *
 * The bodies are the kind of sentence this queue actually carries — a customer complaining
 * about a name in a song — because a fixture whose body is `"test"` hides every wrapping,
 * truncation and escaping question a real complaint asks of a 280px card.
 */

import type {
  SupportBoardView,
  SupportGroupView,
  SupportGroupsResponse,
  SupportTicketDetailView,
  SupportTicketEventView,
  SupportTicketStatus,
  SupportTicketView,
} from "@/api/support";
import { BOARD_COLUMNS, LEGAL_TICKET_MOVES } from "@/features/support/ticketFormat";

/**
 * One described ticket, in `new`, opened from the button under a delivered song.
 *
 * The shape roughly half the queue has: an `orderId`, a body, a `describedAt` clock, and a
 * card already on the support group's wall.
 */
export function makeTicket(overrides: Partial<SupportTicketView> = {}): SupportTicketView {
  const status: SupportTicketStatus = overrides.status ?? "new";
  return {
    id: "aaaaaaaa-1111-4111-8111-111111111111",
    publicRef: "aaaaaaaa",
    telegramUserId: 48_219,
    telegramUserIdMasked: "•••••219",
    language: "uz_latn",
    source: "delivery_button",
    orderId: "bbbbbbbb-2222-4222-8222-222222222222",
    status,
    body: "Ismni notoʻgʻri aytdi — Dilnoza emas, Dilnora",
    describedAt: "2026-09-15T14:04:00Z",
    /* The server's own answer for this status. An explicit override still wins — see the
       header — which is how the empty-array case (an older bundle, a card built from a column)
       gets written without hand-copying the grammar. */
    allowedTransitions: [...LEGAL_TICKET_MOVES[status]],
    assignedAdminUsername: null,
    assignedAt: null,
    isPostedToGroup: true,
    groupPostedAt: "2026-09-15T14:04:02Z",
    resolvedAt: null,
    eventCount: 3,
    createdAt: "2026-09-15T14:02:00Z",
    updatedAt: "2026-09-15T14:04:02Z",
    ...overrides,
  };
}

/**
 * The customer tapped ⚠️ and never typed.
 *
 * **The board must never show one of these** — `ticket_board` forces `onlyDescribed` on and
 * the board screen asks the list for the same population — so this fixture exists to prove the
 * exclusion rather than to be rendered. `body` and `describedAt` are `null` together, which is
 * the only shape the bot can write.
 */
export function makeUndescribedTicket(
  overrides: Partial<SupportTicketView> = {},
): SupportTicketView {
  return makeTicket({
    id: "cccccccc-3333-4333-8333-333333333333",
    publicRef: "cccccccc",
    body: null,
    describedAt: null,
    isPostedToGroup: false,
    groupPostedAt: null,
    eventCount: 1,
    ...overrides,
  });
}

/**
 * A ticket that was closed once and is open again.
 *
 * `resolvedAt` survives a reopen — the server never clears it — so the pair "a resolved clock
 * beside a live status" is the whole signal `isReopenedTicket` reads, and it is the most useful
 * thing a board card can say about a repeat complaint.
 */
export function makeReopenedTicket(
  overrides: Partial<SupportTicketView> = {},
): SupportTicketView {
  return makeTicket({
    id: "dddddddd-4444-4444-8444-444444444444",
    publicRef: "dddddddd",
    status: "in_progress",
    assignedAdminUsername: "dilnoza",
    assignedAt: "2026-09-14T09:10:00Z",
    resolvedAt: "2026-09-13T17:40:00Z",
    eventCount: 9,
    ...overrides,
  });
}

/** One timeline row. `kind` and `authorKind` are the two fields every caller actually sets. */
export function makeEvent(
  overrides: Partial<SupportTicketEventView> = {},
): SupportTicketEventView {
  return {
    id: "eeeeeeee-5555-4555-8555-555555555555",
    ticketId: "aaaaaaaa-1111-4111-8111-111111111111",
    kind: "opened",
    authorKind: "customer",
    authorAdminUsername: null,
    authorTelegramUserIdMasked: "•••••219",
    authorDisplayName: null,
    fromStatus: null,
    toStatus: null,
    body: null,
    relayedAt: null,
    createdAt: "2026-09-15T14:02:00Z",
    ...overrides,
  };
}

/** The response every one of the four writes answers with: the ticket and its whole timeline. */
export function makeDetail(
  ticket: SupportTicketView = makeTicket(),
  events: readonly SupportTicketEventView[] = [makeEvent({ ticketId: ticket.id })],
): SupportTicketDetailView {
  return { ticket, events: [...events] };
}

/**
 * The four column lengths, zero-filled and in board order.
 *
 * Zero-filling here is not a convenience: `ticket_board` returns all four buckets whether or
 * not any row is in them, and a fixture that omitted the empty ones would let a screen pass a
 * test while reading `columns[2]` for a column that is not there — which is the exact shape
 * `noUncheckedIndexedAccess` exists to make visible.
 */
export function makeBoard(
  counts: Partial<Record<SupportTicketStatus, number>> = {},
): SupportBoardView {
  return {
    columns: BOARD_COLUMNS.map((status) => ({ status, count: counts[status] ?? 0 })),
  };
}

/* -------------------------------------------------------------------------- */
/* The chat directory                                                          */
/* -------------------------------------------------------------------------- */

/**
 * One chat the bot knows it is in: a supergroup Telegram itself told us about, verified.
 *
 * The default is the SAFE row on purpose — Telegram's own word for its source, a real title, a
 * clean `verifiedAt` — so that every interesting case in a test is written as an explicit
 * departure from it and reads as one. A default that was already `manual` and unverified would
 * make the tests about the risky path invisible.
 *
 * Two invariants a caller has to keep, because the server keeps them and a fixture that broke
 * one would prove a rendering that cannot happen:
 *
 *  - **`chatId` is NEGATIVE.** A non-negative Telegram id is a private chat, which is a person,
 *    and `BotChatType` has no `private` member precisely so such a row cannot exist.
 *  - **`verifiedAt` and `verificationError` are mutually exclusive.** A verdict writes one and
 *    clears the other; a fixture holding both would be a row whose badge the three-state rule
 *    has no answer for. {@link makeUnverifiedGroup} and {@link makeFailedGroup} are the honest
 *    ways to ask for the other two states.
 */
export function makeGroup(overrides: Partial<SupportGroupView> = {}): SupportGroupView {
  return {
    chatId: -1_001_234_567_890,
    chatType: "supergroup",
    title: "Bayram · qoʻllab-quvvatlash",
    username: null,
    botStatus: "administrator",
    source: "membership_event",
    isSupportGroup: false,
    threadId: null,
    verifiedAt: "2026-09-15T13:00:00Z",
    verificationError: null,
    selectedByUsername: null,
    selectedAt: null,
    firstSeenAt: "2026-09-10T08:00:00Z",
    lastSeenAt: "2026-09-14T19:30:00Z",
    createdAt: "2026-09-10T08:00:01Z",
    updatedAt: "2026-09-15T13:00:00Z",
    ...overrides,
  };
}

/**
 * A chat id somebody typed, which nothing has checked yet — **the row the panel must draw most
 * carefully.**
 *
 * This is the exact shape `select` inserts for an id the directory has never heard of: `manual`,
 * `botStatus: "unknown"`, a `chatType` inferred from the id's shape, no title until `getChat`
 * runs, and both verification fields null. It is also the shape every FRESH selection of a known
 * chat passes through, and the shape a deployment with no worker stays in for ever.
 */
export function makeUnverifiedGroup(
  overrides: Partial<SupportGroupView> = {},
): SupportGroupView {
  return makeGroup({
    chatId: -1_009_876_543_210,
    title: null,
    botStatus: "unknown",
    source: "manual",
    verifiedAt: null,
    verificationError: null,
    ...overrides,
  });
}

/**
 * A chat the worker tried and could not post to.
 *
 * The default message is the MIGRATED one, because it is the case that makes the whole
 * `verificationError` contract matter: it names the group's new chat id as a bare number an
 * operator copies back into the paste field, so a test that renders it proves the recovery path
 * survives the UI.
 */
export function makeFailedGroup(overrides: Partial<SupportGroupView> = {}): SupportGroupView {
  return makeGroup({
    chatId: -487_216_004,
    chatType: "group",
    title: "Bayram support (old)",
    botStatus: "member",
    verifiedAt: null,
    verificationError:
      "This group was upgraded to a supergroup and now has the id -1001987654321. Select that id instead.",
    ...overrides,
  });
}

/** The unpaged directory response, in the order the server returns it: selected first. */
export function makeDirectory(
  groups: readonly SupportGroupView[] = [makeGroup()],
): SupportGroupsResponse {
  return { groups: [...groups] };
}
