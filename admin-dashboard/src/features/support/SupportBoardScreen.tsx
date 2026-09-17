/**
 * `/support` — the queue as four columns, and the only screen in this console you can drag on.
 *
 * ## Two reads, one population
 *
 * The board endpoint answers with FOUR NUMBERS and nothing else (`SupportBoardView` is
 * `{status, count}[]`), so the cards on this screen come from the list — one keyset page of
 * tickets, bucketed into columns here. That split is the server's and it is the right one: a
 * column length is a `GROUP BY` bucket over the whole filtered population and a card is a row
 * on a page, and an endpoint that tried to be both would either page four columns
 * independently (four cursors, four ends of four walks) or cap the count at whatever it had
 * fetched.
 *
 * What the split costs is the thing to be clear-eyed about: **a column's count is the truth and
 * the cards under it are a page.** A column can say `40` with nine cards beneath it, because the
 * other thirty-one are further along the same walk. The count carries `board.columnCount` —
 * "{count} in this column" — rather than a bare number for exactly that reason, and the pager
 * at the foot moves all four columns together because there is one cursor over one ordering.
 *
 * Both reads take the SAME filter object, which is what makes "a board summing to more than its
 * own queue" impossible to ship: `boardQuery` and `supportBoardFilterKey` drop the two fields
 * the board does not honour, so one object is two correct requests.
 *
 * **The list is asked for `onlyDescribed: true`**, which the board endpoint forces on regardless.
 * Without it this screen would draw cards the counts do not count — a customer who tapped ⚠️ and
 * never typed has nothing on the card for an operator to act on, and a column length that
 * included them would be a backlog number that lies (`SUPPORT_TICKETS_SPEC §4.3`). Those rows
 * are real and are kept; the queue list is where they are reachable, and `board.undescribedHidden`
 * says so under the board rather than leaving the absence to be discovered.
 *
 * `withTotal: true` on the LIST is what the toolbar's subtitle states, through `formatTotal`,
 * which says "at least" — `bounded_total` saturates at 10 000. The four column counts are exact
 * and go through `formatCount`. Mixing the two is the one number mistake available on this
 * screen: "at least 40" over a column that is simply 40 understates the queue somebody is
 * planning a shift around.
 *
 * ## Moving a card
 *
 * Hand-rolled native HTML5 drag-and-drop — `draggable`, `onDragStart`, `onDragOver`, `onDrop` —
 * because **no drag-and-drop library is installed in either SPA** and this codebase hand-rolls
 * rather than take a dependency for one behaviour (`ConfirmDialog.tsx` argues the same about
 * Radix). Native DnD is invisible to a keyboard and to a screen reader, so the keyboard path
 * below is not a courtesy: without it this board is unusable by a whole class of operator, and
 * the support queue is not an optional corner of the console.
 *
 * Three rules hold on both paths:
 *
 *  1. **Only legal columns are offered.** `canMoveTicketTo` prefers the server's own
 *     `allowedTransitions` and falls back to `LEGAL_TICKET_MOVES`. A card picked up lights only
 *     the columns it can reach, and the keyboard cursor walks only those plus the one it came
 *     from. Four drop targets of which three are guaranteed refusals is how a board teaches an
 *     operator to ignore its own errors (`SUPPORT_TICKETS_SPEC §6.2`).
 *  2. **Every move names the column the card was DRAWN in.** `expectedStatus` is
 *     {@link Placement}'s column, not `ticket.status`, because during an optimistic move and
 *     after a corrected one those two differ — and the handler's `UPDATE` names `expectedStatus`
 *     in its `WHERE` clause, so it is the lock. A `409` means a staffer moved the ticket from
 *     the Telegram group first, which is another process entirely.
 *  3. **A 409 is not retried.** The optimistic move is rolled forward to the status the server
 *     actually found (`ticketStatusConflictOf`), both reads are asked again, and the note says
 *     the ticket moved first. The same bytes lose the same race, so there is no Retry.
 *
 * ## Why there is no status filter and no "only described" switch
 *
 * The catalogue carries `support.filter.status` and `support.filter.onlyDescribed`, and this
 * screen deliberately renders neither. A status filter over a board is a control that empties
 * columns — the columns ARE the statuses, and the question it answers ("show me only waiting")
 * is answered better by reading the Waiting column. `onlyDescribed` is forced on by the board
 * endpoint, so a switch for it would be a control that changes the cards and not the counts.
 * Both belong to a flat queue list, which is a screen this section does not yet have; the keys
 * are left in place rather than removed, because deleting a key costs three catalogues and
 * `types.ts` and buys nothing.
 *
 * ## The Support group control
 *
 * The third toolbar button opens {@link SupportGroupDialog} — which Telegram group ticket cards
 * are posted into, and whether the bot has been PROVED able to post there. It is on THIS toolbar
 * and not in the sidebar because the question it answers is asked from this screen: a card that
 * renders `notInGroup` sends an operator looking for where the group post was supposed to go.
 *
 * The button itself is not gated. Reading which group is selected is `support.read`, which every
 * role holds, and the dialog withholds its own controls from a role without
 * `support.group.write` — hiding the button as well would leave a VIEWER unable to answer "where
 * do my tickets go?" at all, which is the question the read cell exists for.
 */

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useState,
  type DragEvent,
  type JSX,
  type KeyboardEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { CLIENT_ERROR_CODES } from "@/api/client";
import {
  DEFAULT_PAGE_LIMIT,
  nextCursorOf,
  type PageRequest,
} from "@/api/pagination";
import {
  LANGUAGE_VALUES,
  MAX_TICKET_ASSIGNEE_CHARS,
  MAX_TICKET_SEARCH_CHARS,
  SUPPORT_TICKET_SOURCE_VALUES,
  ticketStatusConflictOf,
  type Language,
  type SupportTicketSource,
  type SupportTicketStatus,
  type SupportTicketView,
  type SupportTicketsFilters,
} from "@/api/support";
import { supportTicketPath } from "@/app/paths";
import { CursorPager } from "@/components/CursorPager";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { SupportGroupDialog } from "@/features/support/SupportGroupDialog";
import { TicketCard } from "@/features/support/TicketCard";
import {
  BOARD_COLUMNS,
  TICKET_SOURCE_LABEL_KEY,
  TICKET_STATUS_EMOJI,
  TICKET_STATUS_HINT_KEY,
  TICKET_STATUS_LABEL_KEY,
  allowedMovesFor,
  canMoveTicketTo,
  formatCount,
  formatTotal,
  noteFor,
} from "@/features/support/ticketFormat";
import {
  useMoveSupportTicket,
  useSupportBoard,
  useSupportTickets,
} from "@/features/support/useSupportTickets";
import { EnumToggleGroup, SearchField } from "@/features/users/filterControls";
import { useI18n } from "@/i18n";
import { failureOf, type AdminQueryError } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import { useCanWriteSupport } from "@/lib/rbac";
import { useSessionGuard } from "@/state/useSessionGuard";

/* -------------------------------------------------------------------------- */
/* URL state                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Every filter this board honours, in the address bar.
 *
 * In the URL and not in component state, for the reason every list in this console puts them
 * there: a queue an operator is working is a thing they send to somebody else — "the Russian
 * tickets nobody has claimed" is a link, not a sequence of clicks to describe in a chat.
 */
interface BoardUrlState {
  readonly source: readonly SupportTicketSource[];
  readonly language: readonly Language[];
  readonly assignedTo: string | null;
  readonly q: string | null;
  readonly cursor: string | null;
}

function readText(params: URLSearchParams, name: string): string | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * A repeated parameter, read back as the members this build knows.
 *
 * `BroadcastsScreen`'s function, duplicated rather than imported across features for
 * `broadcastFormat.ts`'s own reason — a feature does not reach into a sibling feature, and the
 * shared answer is a module under `src/lib/` that would mean editing two shipped screens.
 *
 * An unknown member is DROPPED rather than sent on: the server would answer 422 naming the
 * parameter, which empties the board and blames a filter the operator cannot see.
 */
function readMembers<T extends string>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
): readonly T[] {
  const seen: T[] = [];
  for (const raw of params.getAll(name)) {
    const member = allowed.find((value) => value === raw.trim());
    if (member !== undefined && !seen.includes(member)) seen.push(member);
  }
  return seen;
}

function parseUrlState(params: URLSearchParams): BoardUrlState {
  return {
    source: readMembers(params, "source", SUPPORT_TICKET_SOURCE_VALUES),
    language: readMembers(params, "language", LANGUAGE_VALUES),
    assignedTo: readText(params, "assignedTo"),
    q: readText(params, "q"),
    cursor: readText(params, "cursor"),
  };
}

function writeUrlState(state: BoardUrlState): URLSearchParams {
  const params = new URLSearchParams();
  for (const member of state.source) params.append("source", member);
  for (const member of state.language) params.append("language", member);
  if (state.assignedTo !== null) params.set("assignedTo", state.assignedTo);
  if (state.q !== null) params.set("q", state.q);
  if (state.cursor !== null) params.set("cursor", state.cursor);
  return params;
}

/** The cursor is a position, not a filter. Each vocabulary counts once, however many members. */
function activeFilterCount(state: BoardUrlState): number {
  return (
    (state.source.length === 0 ? 0 : 1) +
    (state.language.length === 0 ? 0 : 1) +
    (state.assignedTo === null ? 0 : 1) +
    (state.q === null ? 0 : 1)
  );
}

/* -------------------------------------------------------------------------- */
/* The walk                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Where the keyset walk has been, so Previous exists.
 *
 * The API mints a forward cursor only, and this board deliberately does NOT number its pages:
 * `support.range` offers "{count} on this page" and "{count} of {total}" and no numbered range,
 * because a card's position in a walk is meaningless once it has been bucketed into a column —
 * "51–100" over four columns names nothing an operator can see.
 */
interface Walk {
  readonly cursor: string | null;
  readonly trail: readonly (string | null)[];
}

const FIRST_STOP: Walk = { cursor: null, trail: [] };

/* -------------------------------------------------------------------------- */
/* Moving a card                                                               */
/* -------------------------------------------------------------------------- */

/**
 * The one card whose column is not `ticket.status`.
 *
 * Held here rather than written into the query cache, because only this screen knows which
 * column the card was drawn in and only this screen can put it back — `useSupportTickets.ts`
 * says the same thing from the other side and keeps the mutation plain.
 *
 * `isPending` distinguishes the two states that look alike and are not: a move in flight (the
 * card is dimmed and cannot be picked up again) from a settled one (the write landed, or the
 * server corrected us, and we are holding the card in place until the refetched page agrees —
 * without which the card would snap back to the stale cached column and jump again a moment
 * later).
 *
 * ONE slot, so this board writes one move at a time. A second drag while a POST is in flight is
 * ignored rather than queued: the shared mutation and the single rollback can describe one move,
 * and an operator dragging two cards inside the half-second a write takes is not a case worth
 * making the rollback ambiguous for.
 */
interface Placement {
  readonly ticketId: string;
  readonly to: SupportTicketStatus;
  readonly isPending: boolean;
}

/** A card picked up by the KEYBOARD, and where its cursor currently rests. */
interface Grab {
  readonly ticketId: string;
  readonly reference: string;
  /** The column it was drawn in. The `expectedStatus` of the move, and where Escape returns it. */
  readonly from: SupportTicketStatus;
  /** The column under the cursor. Never a column the grammar refuses. */
  readonly target: SupportTicketStatus;
}

/** A card picked up by the MOUSE. The reference rides along for the refusal announcement. */
interface Drag {
  readonly ticketId: string;
  readonly reference: string;
  readonly from: SupportTicketStatus;
}

/**
 * The columns a grabbed card may rest in: the one it came from, plus every legal move, in board
 * order.
 *
 * The origin is in the lane so Escape is not the only way out of a pick-up — an operator who
 * has walked to `waiting` and changed their mind walks back and presses Space, which is a drop
 * and not a cancellation. It is never a MOVE, because nothing moves to itself.
 */
function laneFor(
  ticket: SupportTicketView,
  from: SupportTicketStatus,
): readonly SupportTicketStatus[] {
  return BOARD_COLUMNS.filter(
    (status) => status === from || canMoveTicketTo(ticket, status),
  );
}

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

export function SupportBoardScreen(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  /* Local state and not a URL parameter, deliberately. Every other piece of this screen's state
     is in the query string because a filtered board is worth sending to a colleague; a
     configuration dialog is not, and a `?groups=1` that survived a reload would reopen a modal
     over the board every time somebody pressed refresh on a link they were sent. */
  const [isGroupDialogOpen, setIsGroupDialogOpen] = useState(false);
  const [walk, setWalk] = useState<Walk>(FIRST_STOP);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [grab, setGrab] = useState<Grab | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hover, setHover] = useState<SupportTicketStatus | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [focusTicketId, setFocusTicketId] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<AdminQueryError | null>(null);
  const canWrite = useCanWriteSupport();
  const instructionsId = useId();

  const url = useMemo(() => parseUrlState(searchParams), [searchParams]);
  const filterCount = activeFilterCount(url);

  /** A filter change starts the walk again: a cursor is a position in ONE filtered set. */
  const patch = useCallback(
    (change: Partial<Omit<BoardUrlState, "cursor">>) => {
      setWalk(FIRST_STOP);
      setSearchParams(writeUrlState({ ...url, ...change, cursor: null }), {
        replace: true,
      });
    },
    [setSearchParams, url],
  );

  const goToStop = useCallback(
    (stop: Walk) => {
      setWalk(stop);
      setSearchParams(writeUrlState({ ...url, cursor: stop.cursor }), {
        replace: true,
      });
    },
    [setSearchParams, url],
  );

  const clearAll = useCallback(() => {
    setWalk(FIRST_STOP);
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  /*
   * ONE filter object for both reads. `boardQuery`/`supportBoardFilterKey` drop `withTotal` and
   * `onlyDescribed` themselves — the board honours neither — so passing the same object is what
   * guarantees the counts and the cards describe one population rather than two that agree by
   * accident.
   */
  const filters = useMemo<SupportTicketsFilters>(
    () => ({
      withTotal: true,
      onlyDescribed: true,
      source: url.source,
      language: url.language,
      assignedTo: url.assignedTo,
      q: url.q,
    }),
    [url.assignedTo, url.language, url.q, url.source],
  );

  const page = useMemo<PageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: url.cursor }),
    [url.cursor],
  );

  const board = useSupportBoard(filters);
  const tickets = useSupportTickets(filters, page);
  const move = useMoveSupportTicket();

  /* An abort is a superseded request — a filter change, an unmount — and renders as nothing. */
  const listFailure =
    tickets.error !== null && tickets.error.code !== CLIENT_ERROR_CODES.aborted
      ? tickets.error
      : null;
  const boardFailure =
    board.error !== null && board.error.code !== CLIENT_ERROR_CODES.aborted
      ? board.error
      : null;
  useSessionGuard([listFailure, boardFailure, writeError]);

  const items = useMemo<readonly SupportTicketView[]>(
    () => tickets.data?.items ?? [],
    [tickets.data],
  );
  const meta = tickets.data?.meta ?? null;

  /** Where a card is DRAWN, which is `ticket.status` unless this screen is holding it elsewhere. */
  const columnOf = useCallback(
    (ticket: SupportTicketView): SupportTicketStatus =>
      placement !== null && placement.ticketId === ticket.id
        ? placement.to
        : ticket.status,
    [placement],
  );

  /*
   * A settled placement is held only until the page agrees with it. Once the refetched row
   * carries the status we are drawing — or the ticket has walked off this page entirely — the
   * override is a second copy of the truth, and a second copy is the thing that goes stale.
   */
  useEffect(() => {
    if (placement === null || placement.isPending) return;
    const row = items.find((ticket) => ticket.id === placement.ticketId);
    if (row === undefined || row.status === placement.to) setPlacement(null);
  }, [items, placement]);

  /*
   * Focus, returned to the card after it was unmounted from one column and remounted in another.
   * Child effects run before parent effects, so the card has already taken focus by the time
   * this clears the request — which it must, or every later remount of that card would steal
   * focus back from wherever the operator has since gone.
   */
  useEffect(() => {
    if (focusTicketId !== null) setFocusTicketId(null);
  }, [focusTicketId]);

  const columnCount = useCallback(
    (status: SupportTicketStatus): number | undefined =>
      board.data?.columns.find((column) => column.status === status)?.count,
    [board.data],
  );

  const statusLabel = useCallback(
    (status: SupportTicketStatus) => t(TICKET_STATUS_LABEL_KEY[status]),
    [t],
  );

  /* ---------------------------------------------------------------------- */
  /* The write                                                               */
  /* ---------------------------------------------------------------------- */

  const submitMove = useCallback(
    (
      ticket: SupportTicketView,
      from: SupportTicketStatus,
      to: SupportTicketStatus,
    ) => {
      if (placement?.isPending === true) return;
      setWriteError(null);
      setPlacement({ ticketId: ticket.id, to, isPending: true });
      move.mutate(
        { ticketId: ticket.id, body: { expectedStatus: from, toStatus: to } },
        {
          onSuccess: () => {
            /* Held, not cleared: the invalidated page has not come back yet, and clearing here
               would drop the card into its stale column for one paint. */
            setPlacement({ ticketId: ticket.id, to, isPending: false });
            setAnnouncement(
              t("support.dnd.moved", {
                reference: ticket.publicRef,
                from: statusLabel(from),
                to: statusLabel(to),
              }),
            );
          },
          onError: (error) => {
            setWriteError(error);
            const actual = ticketStatusConflictOf(failureOf(error));
            if (actual === null) {
              /* Not the lost-update refusal — a 503 with no worker, a 403, a dropped network.
                 Nothing was written, so the card goes back exactly where it was. */
              setPlacement(null);
              return;
            }
            /* Somebody moved it first, almost always a staffer pressing ✋ or ✅ on the card in
               the Telegram group. Roll the card FORWARD to what the server actually found — the
               note says the board is being re-read, and this is that re-read arriving early. */
            setPlacement({ ticketId: ticket.id, to: actual, isPending: false });
            void tickets.refetch();
            void board.refetch();
          },
        },
      );
    },
    [board, move, placement, statusLabel, t, tickets],
  );

  /* ---------------------------------------------------------------------- */
  /* The keyboard path                                                       */
  /* ---------------------------------------------------------------------- */

  const openTicket = useCallback(
    (ticket: SupportTicketView) => {
      navigate(supportTicketPath(ticket.id));
    },
    [navigate],
  );

  const onCardKeyDown = useCallback(
    (ticket: SupportTicketView, drawnIn: SupportTicketStatus) =>
      (event: KeyboardEvent<HTMLLIElement>) => {
        /* A key pressed inside the card's own button is that button's business. */
        if (event.target !== event.currentTarget) return;
        const held = grab !== null && grab.ticketId === ticket.id ? grab : null;

        if (event.key === "Enter") {
          /* Not while a card is held: an operator mid-move who presses Enter means the move. */
          if (grab !== null) return;
          event.preventDefault();
          openTicket(ticket);
          return;
        }

        if (!canWrite) return;

        if (event.key === " " || event.key === "Spacebar") {
          event.preventDefault();
          if (held === null) {
            if (grab !== null) return;
            /* Nothing to pick a card up FOR when the grammar offers it nowhere to go. No
               announcement invented for it: the card simply is not a draggable thing. */
            if (allowedMovesFor(ticket).length === 0) return;
            if (placement?.isPending === true) return;
            setGrab({
              ticketId: ticket.id,
              reference: ticket.publicRef,
              from: drawnIn,
              target: drawnIn,
            });
            setAnnouncement(
              t("support.dnd.grabbed", {
                reference: ticket.publicRef,
                status: statusLabel(drawnIn),
              }),
            );
            return;
          }
          setGrab(null);
          setFocusTicketId(ticket.id);
          if (held.target === held.from) {
            setAnnouncement(
              t("support.dnd.dropped", {
                reference: held.reference,
                status: statusLabel(held.from),
              }),
            );
            return;
          }
          submitMove(ticket, held.from, held.target);
          return;
        }

        if (held === null) return;

        if (event.key === "Escape") {
          event.preventDefault();
          setGrab(null);
          setAnnouncement(
            t("support.dnd.cancelled", {
              reference: held.reference,
              status: statusLabel(held.from),
            }),
          );
          return;
        }

        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const lane = laneFor(ticket, held.from);
        const next =
          lane[
            lane.indexOf(held.target) + (event.key === "ArrowRight" ? 1 : -1)
          ];
        /* Clamped at both ends rather than wrapped: a cursor that reappears at the far side of
           the board is a cursor an operator has to look for. */
        if (next === undefined) return;
        setGrab({ ...held, target: next });
        setAnnouncement(
          next === held.from
            ? /* Back where it started — "Move to New" would be a lie about a card already in
                 New, so the column announces itself instead, length and all. */
              t("support.board.columnAria", {
                status: statusLabel(next),
                count: formatCount(columnCount(next) ?? 0),
              })
            : t("support.board.dropHere", { status: statusLabel(next) }),
        );
      },
    [
      canWrite,
      columnCount,
      grab,
      openTicket,
      placement,
      statusLabel,
      submitMove,
      t,
    ],
  );

  /* ---------------------------------------------------------------------- */
  /* The mouse path                                                          */
  /* ---------------------------------------------------------------------- */

  const onCardDragStart = useCallback(
    (ticket: SupportTicketView, drawnIn: SupportTicketStatus) =>
      (event: DragEvent<HTMLLIElement>) => {
        if (
          !canWrite ||
          allowedMovesFor(ticket).length === 0 ||
          placement?.isPending === true
        ) {
          event.preventDefault();
          return;
        }
        /* A mouse takes over from a keyboard pick-up rather than fighting it. */
        setGrab(null);
        setDrag({
          ticketId: ticket.id,
          reference: ticket.publicRef,
          from: drawnIn,
        });
        event.dataTransfer.effectAllowed = "move";
        /* The public reference and not the id: a drop outside this board lands in a text field,
           and the reference is the string an operator would want pasted there. */
        event.dataTransfer.setData("text/plain", ticket.publicRef);
      },
    [canWrite, placement],
  );

  const onCardDragEnd = useCallback(() => {
    setDrag(null);
    setHover(null);
  }, []);

  const draggedTicket = useMemo<SupportTicketView | null>(
    () =>
      drag === null
        ? null
        : (items.find((ticket) => ticket.id === drag.ticketId) ?? null),
    [drag, items],
  );

  const onColumnDragOver = useCallback(
    (status: SupportTicketStatus) => (event: DragEvent<HTMLElement>) => {
      if (draggedTicket === null) return;
      setHover(status);
      /* `preventDefault` is what MAKES a column a drop target, so withholding it on an illegal
         column is the refusal itself — the cursor says no-drop and the browser fires no drop. */
      if (!canMoveTicketTo(draggedTicket, status)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    },
    [draggedTicket],
  );

  const onColumnDrop = useCallback(
    (status: SupportTicketStatus) => (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      const held = drag;
      setDrag(null);
      setHover(null);
      if (held === null || draggedTicket === null) return;
      if (!canMoveTicketTo(draggedTicket, status)) {
        /* Unreachable through a browser, which never fires a drop on a target that refused the
           dragover. Kept because it is the only place that knows the answer, and because a
           second handler on the page calling `preventDefault` would make it reachable. */
        setAnnouncement(
          t("support.dnd.blocked", {
            from: statusLabel(held.from),
            to: statusLabel(status),
          }),
        );
        return;
      }
      submitMove(draggedTicket, held.from, status);
    },
    [drag, draggedTicket, statusLabel, submitMove, t],
  );

  /* ---------------------------------------------------------------------- */
  /* What the toolbar and the pager may claim                                */
  /* ---------------------------------------------------------------------- */

  const total = meta?.total ?? null;
  const isTotalExact = meta?.isTotalExact ?? null;

  let subtitle: string;
  if (tickets.data === undefined) {
    subtitle =
      listFailure === null
        ? t("support.subtitles.reading")
        : t("support.subtitles.failed");
  } else if (total === null) {
    subtitle = t("support.subtitles.onThisPage", {
      count: formatCount(items.length),
    });
  } else {
    /* `{count}`, not `{total}`: the catalogue names this placeholder for the thing being
       counted, and a mis-named parameter renders the brace verbatim in all three locales. */
    const shown = formatTotal(total, isTotalExact, t);
    subtitle =
      filterCount === 0
        ? t("support.subtitles.tickets", { count: shown })
        : t("support.subtitles.ticketsFiltered", { count: shown });
  }

  let rangeLabel: string;
  if (tickets.data === undefined) {
    rangeLabel = t("support.board.loading");
  } else if (items.length === 0) {
    rangeLabel =
      filterCount === 0
        ? t("support.range.none")
        : t("support.range.noneMatching");
  } else if (total === null) {
    rangeLabel = t("support.range.onPage", {
      count: formatCount(items.length),
    });
  } else {
    rangeLabel = t("support.range.onPageOf", {
      count: formatCount(items.length),
      total: formatTotal(total, isTotalExact, t),
    });
  }

  const chips = useMemo<readonly FilterChip[]>(() => {
    const list: FilterChip[] = [];
    if (url.source.length > 0) {
      list.push({
        id: "source",
        field: t("support.chips.source"),
        /* Words, never the wire spelling: `delivery_button` in a chip is a database column. */
        value: url.source
          .map((member) => t(TICKET_SOURCE_LABEL_KEY[member]))
          .join(t("support.chips.join")),
        onRemove: () => {
          patch({ source: [] });
        },
      });
    }
    if (url.language.length > 0) {
      list.push({
        id: "language",
        field: t("support.chips.language"),
        value: url.language
          .map((member) => t(LANGUAGE_LABEL_KEY[member]))
          .join(t("support.chips.join")),
        onRemove: () => {
          patch({ language: [] });
        },
      });
    }
    if (url.assignedTo !== null) {
      list.push({
        id: "assignedTo",
        field: t("support.chips.assignedTo"),
        value: url.assignedTo,
        onRemove: () => {
          patch({ assignedTo: null });
        },
      });
    }
    if (url.q !== null) {
      list.push({
        id: "q",
        field: t("support.chips.search"),
        value: url.q,
        onRemove: () => {
          patch({ q: null });
        },
      });
    }
    return list;
  }, [patch, t, url.assignedTo, url.language, url.q, url.source]);

  const listNote =
    listFailure === null
      ? null
      : noteFor(
          listFailure,
          tickets.data !== undefined,
          t,
          t("support.subject"),
        );
  const boardNote =
    boardFailure === null
      ? null
      : noteFor(
          boardFailure,
          board.data !== undefined,
          t,
          t("support.subjectBoard"),
        );
  const writeNote =
    writeError === null
      ? null
      : noteFor(writeError, false, t, t("support.subjectOne"));

  const nextCursor =
    tickets.data === undefined ? null : nextCursorOf(tickets.data);
  const isWalkCurrent = walk.cursor === url.cursor;
  const trail = isWalkCurrent ? walk.trail : [];
  const hasPrev = trail.length > 0;

  /*
   * The whole-page empty state replaces the grid only when BOTH reads say there is nothing, and
   * only at the start of a walk.
   *
   * An empty page at the end of a walk is an ordinary last page, and a page that is empty while
   * the columns count twelve is a disagreement between the two reads — in either case "Nobody
   * has written in" would be a sentence contradicting the numbers beside it, and the honest
   * thing is to draw four empty columns under their own counts and let them say so.
   */
  const hasCountedTickets = (board.data?.columns ?? []).some(
    (column) => column.count > 0,
  );
  const isEmptyBoard =
    tickets.data !== undefined &&
    items.length === 0 &&
    url.cursor === null &&
    !hasCountedTickets;

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("support.title")}
          subtitle={subtitle}
          actions={
            <>
              <ToolbarButton
                variant="secondary"
                ariaExpanded={isPanelOpen}
                ariaControls="support-filter-panel"
                onClick={() => {
                  setIsPanelOpen((open) => !open);
                }}
              >
                {filterCount === 0
                  ? t("common.filters")
                  : t("common.filtersCount", { count: filterCount })}
              </ToolbarButton>
              {/* Where the cards go. It lives on this toolbar rather than in the sidebar
                  because the question it answers — "why did this ticket never reach the
                  group?" — is asked while looking at a card that says `notInGroup`, and the
                  answer is two feet away rather than a navigation. Not gated on
                  `support.group.write`: every role may READ which group is selected and whether
                  it last verified, and the dialog withholds the controls on its own. */}
              <ToolbarButton
                variant="secondary"
                ariaExpanded={isGroupDialogOpen}
                onClick={() => {
                  setIsGroupDialogOpen(true);
                }}
              >
                {t("support.groups.open")}
              </ToolbarButton>
              <ToolbarButton
                variant="secondary"
                disabled={tickets.isFetching || board.isFetching}
                onClick={() => {
                  /* The reads do not poll — a board that re-ordered itself under a half-typed
                     reply would cost more than the freshness buys — so this is the one control
                     that asks again. Both halves, because a stale count beside fresh cards is
                     the disagreement this screen exists to avoid. */
                  void tickets.refetch();
                  void board.refetch();
                }}
              >
                {t("support.refresh")}
              </ToolbarButton>
            </>
          }
        />

        <div
          id="support-filter-panel"
          role="group"
          aria-label={t("support.filtersAria")}
          hidden={!isPanelOpen}
          className="rounded-card border border-stroke bg-card px-4 py-4"
        >
          <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
            <EnumToggleGroup<SupportTicketSource>
              label={t("support.filter.source")}
              values={SUPPORT_TICKET_SOURCE_VALUES}
              selected={url.source}
              onChange={(next) => {
                patch({ source: next });
              }}
              format={(member) => t(TICKET_SOURCE_LABEL_KEY[member])}
              hint={t("support.filter.sourceHint")}
            />
            <EnumToggleGroup<Language>
              label={t("support.filter.language")}
              values={LANGUAGE_VALUES}
              selected={url.language}
              onChange={(next) => {
                patch({ language: next });
              }}
              format={(member) => t(LANGUAGE_LABEL_KEY[member])}
              hint={t("support.filter.languageHint")}
            />
            <SearchField
              value={url.assignedTo}
              onChange={(next) => {
                patch({ assignedTo: next });
              }}
              label={t("support.filter.assignedTo")}
              placeholder={t("support.filter.assignedTo")}
              hint={t("support.filter.assignedToHint")}
              maxLength={MAX_TICKET_ASSIGNEE_CHARS}
              /* An operator username is words, not digits — see `SearchFieldProps.inputMode`. */
              inputMode="search"
            />
            <SearchField
              value={url.q}
              onChange={(next) => {
                patch({ q: next });
              }}
              label={t("support.filter.search")}
              placeholder={t("support.filter.search")}
              hint={t("support.filter.searchHint")}
              maxLength={MAX_TICKET_SEARCH_CHARS}
              inputMode="search"
            />
          </div>
        </div>

        <FilterChips
          chips={chips}
          onClearAll={chips.length === 0 ? undefined : clearAll}
        />

        {writeNote === null || writeError === null ? null : (
          <ErrorNote
            tone={writeNote.tone}
            title={writeNote.title}
            message={writeNote.message}
            hint={`${writeError.endpoint} · ${writeError.correlationId ?? t("errors.query.noCorrelationId")}`}
            retryable={false}
          />
        )}

        {boardNote === null || boardFailure === null ? null : (
          <ErrorNote
            tone={boardNote.tone}
            title={boardNote.title}
            message={boardNote.message}
            hint={`${boardFailure.endpoint} · ${boardFailure.correlationId ?? t("errors.query.noCorrelationId")}`}
            onRetry={() => {
              void board.refetch();
            }}
            isRetrying={board.isFetching}
            retryable={boardNote.canRetry}
          />
        )}

        {listNote === null || listFailure === null ? null : (
          <ErrorNote
            tone={listNote.tone}
            title={listNote.title}
            message={listNote.message}
            hint={`${listFailure.endpoint} · ${listFailure.correlationId ?? t("errors.query.noCorrelationId")}`}
            onRetry={() => {
              void tickets.refetch();
            }}
            isRetrying={tickets.isFetching}
            retryable={listNote.canRetry}
          />
        )}

        {/* Read by a screen reader when focus lands on any card, through `aria-describedby`. */}
        {canWrite ? (
          <p
            id={instructionsId}
            className="m-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500"
          >
            {t("support.dnd.instructions")}
          </p>
        ) : null}

        {/*
          Polite and never assertive: an announcement that interrupted would cut across the card
          label a screen reader is in the middle of reading — which is the text an operator
          picked the card up from.
        */}
        <p aria-live="polite" role="status" className="sr-only">
          {announcement}
        </p>

        {/* A failed FIRST read has nothing to draw: the note above is the whole answer. */}
        {tickets.data === undefined &&
        listFailure !== null ? null : isEmptyBoard ? (
          <EmptyState
            title={
              filterCount === 0
                ? t("support.empty.title")
                : t("support.empty.filteredTitle")
            }
            message={
              filterCount === 0
                ? t("support.empty.message")
                : t("support.empty.filteredMessage")
            }
            {...(filterCount === 0
              ? {}
              : {
                  action: (
                    <ToolbarButton onClick={clearAll} variant="secondary">
                      {t("common.clearAllFilters")}
                    </ToolbarButton>
                  ),
                })}
          />
        ) : (
          <div
            role="group"
            aria-label={t("support.board.aria")}
            aria-busy={tickets.isPlaceholderData}
            className={cn(
              "grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4",
              "transition-opacity",
              tickets.isPlaceholderData && "opacity-50",
            )}
          >
            {BOARD_COLUMNS.map((status) => {
              const cards = items.filter(
                (ticket) => columnOf(ticket) === status,
              );
              const count = columnCount(status);
              const isHovered = hover === status;
              const isLegalTarget =
                draggedTicket !== null &&
                canMoveTicketTo(draggedTicket, status);
              const isKeyboardTarget = grab !== null && grab.target === status;

              return (
                <section
                  key={status}
                  onDragOver={onColumnDragOver(status)}
                  onDrop={onColumnDrop(status)}
                  onDragLeave={() => {
                    setHover((current) =>
                      current === status ? null : current,
                    );
                  }}
                  className={cn(
                    "flex min-w-0 flex-col gap-2 rounded-card border border-stroke bg-bg px-2 py-3",
                    /* Only a column that can actually take the card lights up. */
                    (isHovered && isLegalTarget) || isKeyboardTarget
                      ? "border-accent-deep ring-2 ring-accent"
                      : null,
                    isHovered &&
                      draggedTicket !== null &&
                      !isLegalTarget &&
                      "opacity-60",
                  )}
                >
                  <header className="flex min-w-0 flex-col gap-[2px] px-1">
                    <h2
                      className="m-0 text-[14px] font-semibold leading-5 tracking-[-0.084px] text-ink-900"
                      title={t(TICKET_STATUS_HINT_KEY[status])}
                    >
                      <span aria-hidden>{TICKET_STATUS_EMOJI[status]} </span>
                      {statusLabel(status)}
                    </h2>
                    {count === undefined ? null : (
                      /* An EXACT `GROUP BY` bucket, so a plain number — `formatTotal`'s "at
                         least" belongs to the list's bounded total and would understate this. */
                      <span className="text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500">
                        {t("support.board.columnCount", {
                          count: formatCount(count),
                        })}
                      </span>
                    )}
                    {draggedTicket === null || isLegalTarget ? null : (
                      <span className="text-[11px] font-normal leading-[1.35] text-ink-400">
                        {t("support.board.cannotDropHere", {
                          from: statusLabel(drag?.from ?? draggedTicket.status),
                          to: statusLabel(status),
                        })}
                      </span>
                    )}
                    {draggedTicket !== null && isLegalTarget ? (
                      <span className="text-[11px] font-normal leading-[1.35] text-ink-400">
                        {t("support.board.dropHere", {
                          status: statusLabel(status),
                        })}
                      </span>
                    ) : null}
                  </header>

                  <ul
                    role="list"
                    aria-label={
                      count === undefined
                        ? statusLabel(status)
                        : t("support.board.columnAria", {
                            status: statusLabel(status),
                            count: formatCount(count),
                          })
                    }
                    className="m-0 flex list-none flex-col gap-2 p-0"
                  >
                    {cards.map((ticket) => (
                      <TicketCard
                        key={ticket.id}
                        ticket={ticket}
                        t={t}
                        drawnIn={status}
                        isGrabbed={grab !== null && grab.ticketId === ticket.id}
                        isMoving={
                          placement !== null &&
                          placement.isPending &&
                          placement.ticketId === ticket.id
                        }
                        isMovable={
                          canWrite && allowedMovesFor(ticket).length > 0
                        }
                        shouldFocus={focusTicketId === ticket.id}
                        instructionsId={canWrite ? instructionsId : undefined}
                        onOpen={() => {
                          openTicket(ticket);
                        }}
                        onKeyDown={onCardKeyDown(ticket, status)}
                        onDragStart={onCardDragStart(ticket, status)}
                        onDragEnd={onCardDragEnd}
                      />
                    ))}
                  </ul>

                  {cards.length > 0 ? null : (
                    <p className="m-0 px-1 py-2 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-300">
                      {tickets.data === undefined
                        ? t("support.board.loading")
                        : filterCount === 0
                          ? t("support.board.empty")
                          : t("support.board.emptyFiltered")}
                    </p>
                  )}
                </section>
              );
            })}
          </div>
        )}

        {/* Said once, under the board: the absence is a filter, not a gap in the data. */}
        <p className="m-0 max-w-[80ch] text-[11px] font-normal leading-[1.35] text-ink-400">
          {t("support.board.undescribedHidden")}
        </p>

        <CursorPager
          hasPrev={hasPrev}
          hasNext={nextCursor !== null}
          isFetching={tickets.isFetching}
          rangeLabel={rangeLabel}
          onPrev={
            !hasPrev
              ? undefined
              : () => {
                  goToStop({
                    cursor: trail[trail.length - 1] ?? null,
                    trail: trail.slice(0, -1),
                  });
                }
          }
          onNext={
            nextCursor === null
              ? undefined
              : () => {
                  goToStop({
                    cursor: nextCursor,
                    trail: [...trail, url.cursor],
                  });
                }
          }
        />

        {/* Mounted only while open — the dialog owns a query, so an always-rendered one gated on
            a prop would fetch the chat directory on every board load for every operator. It
            portals to `document.body`, so its position in this tree costs nothing, and its
            unmount is what returns focus to the toolbar button above. */}
        {isGroupDialogOpen ? (
          <SupportGroupDialog
            onClose={() => {
              setIsGroupDialogOpen(false);
            }}
          />
        ) : null}
      </div>
    </main>
  );
}
