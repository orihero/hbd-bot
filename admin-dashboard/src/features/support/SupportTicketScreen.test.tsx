import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiFailure } from "@/api/client";
import type { TicketStatusRequest } from "@/api/support";
import {
  makeDetail,
  makeEvent,
  makeTicket,
  makeUndescribedTicket,
} from "@/features/support/fixtures";
import { SupportTicketScreen } from "@/features/support/SupportTicketScreen";
import { useAuthStore } from "@/state/auth";

/**
 * One ticket, and the five things this screen must never get wrong.
 *
 * 1. **The complaint is rendered, and a missing one is not a redaction.** The body is the only
 *    customer free text that crosses to this console in full, and `null` means somebody tapped
 *    ⚠️ and never typed — a row that is kept on purpose. A screen that said "hidden" would
 *    describe a privacy control that does not exist here.
 * 2. **A composed reply is not a delivered reply.** `relayedAt` is stamped after the message
 *    reaches the customer's chat. Reading a timeline as "we answered them" when nothing landed
 *    is the single worst mistake available on this screen.
 * 3. **An operator and a staffer in the Telegram group stay visibly apart.** One has an audit
 *    row behind them and the other has membership of a chat; a timeline that blurred the two
 *    would lend an unaudited act an audited actor's accountability.
 * 4. **Only legal moves are offered, and every move names the status the screen was drawn in.**
 *    Four drop targets of which three are guaranteed refusals is how a console teaches an
 *    operator to ignore its own errors — and `expectedStatus` is the lock that turns a staffer
 *    pressing ✅ Resolve in the group into one move and one refusal.
 * 5. **A note and a reply cannot be confused.** They differ in the one way that matters, so
 *    they are proved here by what each one POSTS as well as by what each one says.
 *
 * `MemoryRouter`, never `createMemoryRouter`/`RouterProvider`: a data router builds a `Request`
 * per navigation and jsdom's `AbortSignal` is not the instance undici's `Request` accepts, so
 * the URL silently never moves. `BroadcastsScreen.test.tsx` writes that out in full.
 */

const {
  getSupportTicket,
  moveSupportTicket,
  addSupportTicketNote,
  replyToSupportTicket,
  assignSupportTicket,
} = vi.hoisted(() => ({
  getSupportTicket: vi.fn(),
  moveSupportTicket: vi.fn(),
  addSupportTicketNote: vi.fn(),
  replyToSupportTicket: vi.fn(),
  assignSupportTicket: vi.fn(),
}));

/* The schemas, the predicates and the bounds stay REAL — only the seven calls are replaced, so
   a fixture that could not have come off the wire still fails here. */
vi.mock("@/api/support", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getSupportTicket,
    moveSupportTicket,
    addSupportTicketNote,
    replyToSupportTicket,
    assignSupportTicket,
  };
});

const TICKET_ID = "aaaaaaaa-1111-4111-8111-111111111111";

/** The refusal this namespace invents: the row moved first, and the server says what it found. */
const MOVED_FIRST: ApiFailure = {
  ok: false,
  code: "CONFLICT",
  message: "the ticket is no longer in that status",
  status: 409,
  endpoint: "POST /api/support/tickets/{ticket_id}/status",
  correlationId: "cid-conflict",
  issues: null,
  details: { status: "resolved" },
  retryAfterS: null,
};

function renderScreen(): void {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/support/${TICKET_ID}`]}>
        <Routes>
          <Route path="/support/:ticketId" element={<SupportTicketScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The body of the most recent `POST /api/support/tickets/{id}/status`. */
async function lastMove(): Promise<TicketStatusRequest> {
  await waitFor(() => {
    expect(moveSupportTicket).toHaveBeenCalled();
  });
  const calls = moveSupportTicket.mock.calls;
  return calls[calls.length - 1]?.[1] as TicketStatusRequest;
}

function signIn(role: "viewer" | "support" | "admin" | "owner"): void {
  useAuthStore.setState({
    account: {
      id: "00000000-0000-4000-8000-000000000001",
      username: "operator",
      role,
      lastLoginAt: null,
      mustChangePassword: false,
    },
  });
}

beforeEach(() => {
  getSupportTicket.mockResolvedValue({ ok: true, data: makeDetail() });
  moveSupportTicket.mockResolvedValue({ ok: true, data: makeDetail() });
  addSupportTicketNote.mockResolvedValue({ ok: true, data: makeDetail() });
  replyToSupportTicket.mockResolvedValue({ ok: true, data: makeDetail() });
  assignSupportTicket.mockResolvedValue({ ok: true, data: makeDetail() });
  signIn("admin");
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("SupportTicketScreen — the complaint itself", () => {
  it("renders the customer's own words, and the reference verbatim", async () => {
    renderScreen();

    // The reference is the heading: it is what the customer quotes back down a phone line,
    // reproduced by READING the id rather than by computing an encoding.
    expect(
      await screen.findByRole("heading", { name: "aaaaaaaa" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Ismni notoʻgʻri aytdi — Dilnoza emas, Dilnora"),
    ).toBeInTheDocument();
    // Masked on screen; the raw id is only ever the href of the route that is keyed by it.
    expect(screen.getByRole("link", { name: "•••••219" })).toHaveAttribute(
      "href",
      "/users/48219",
    );
  });

  it("says nothing was described — never 'hidden' and never 'redacted'", async () => {
    getSupportTicket.mockResolvedValue({
      ok: true,
      data: makeDetail(makeUndescribedTicket()),
    });
    renderScreen();

    expect(
      await screen.findByText("Nothing was described"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /never typed. The row is kept because it is the only measure/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/hidden|redacted/i)).not.toBeInTheDocument();
  });
});

describe("SupportTicketScreen — the timeline", () => {
  it("renders a composed reply as undelivered, and says why", async () => {
    getSupportTicket.mockResolvedValue({
      ok: true,
      data: makeDetail(makeTicket(), [
        makeEvent({ id: "10000000-0000-4000-8000-000000000001" }),
        makeEvent({
          id: "10000000-0000-4000-8000-000000000002",
          kind: "reply",
          authorKind: "operator",
          authorAdminUsername: "dilnoza",
          authorTelegramUserIdMasked: null,
          body: "We are re-rendering the song with the right name.",
          relayedAt: null,
        }),
      ]),
    });
    renderScreen();

    /* Scoped to the timeline itself: the header's source badge reads "Delivered song", which
       is a different fact about a different thing and would satisfy a loose matcher. */
    const timeline = await screen.findByRole("list");
    expect(within(timeline).getByText("Not delivered")).toBeInTheDocument();
    expect(
      within(timeline).getByText(/has not reached the customer/),
    ).toBeInTheDocument();
    expect(within(timeline).queryByText(/^Delivered/)).not.toBeInTheDocument();
  });

  it("renders a relayed reply as delivered", async () => {
    getSupportTicket.mockResolvedValue({
      ok: true,
      data: makeDetail(makeTicket(), [
        makeEvent({
          id: "10000000-0000-4000-8000-000000000003",
          kind: "reply",
          authorKind: "operator",
          authorAdminUsername: "dilnoza",
          authorTelegramUserIdMasked: null,
          body: "We are re-rendering the song with the right name.",
          relayedAt: "2026-09-15T14:31:00Z",
        }),
      ]),
    });
    renderScreen();

    const timeline = await screen.findByRole("list");
    expect(within(timeline).getByText(/^Delivered/)).toBeInTheDocument();
    expect(
      within(timeline).queryByText("Not delivered"),
    ).not.toBeInTheDocument();
  });

  it("keeps an operator and a staffer in the Telegram group visibly apart", async () => {
    getSupportTicket.mockResolvedValue({
      ok: true,
      data: makeDetail(makeTicket(), [
        makeEvent({
          id: "10000000-0000-4000-8000-000000000004",
          kind: "note",
          authorKind: "operator",
          authorAdminUsername: "dilnoza",
          authorTelegramUserIdMasked: null,
          body: "Order re-queued.",
        }),
        makeEvent({
          id: "10000000-0000-4000-8000-000000000005",
          kind: "reply",
          authorKind: "staff_group",
          authorDisplayName: "@aziz",
          body: "Sorry about that — the new version is on its way.",
          relayedAt: "2026-09-15T14:40:00Z",
        }),
      ]),
    });
    renderScreen();

    // Two different words for two different kinds of accountability — one has an audit row
    // behind it, the other has membership of a chat.
    expect(await screen.findByText("Operator")).toBeInTheDocument();
    expect(
      screen.getByText("Staff, in the Telegram group"),
    ).toBeInTheDocument();
    expect(screen.getByText("dilnoza")).toBeInTheDocument();
    expect(screen.getByText("@aziz")).toBeInTheDocument();
  });

  it("names both ends of a status change, so a reopen is legible as one", async () => {
    getSupportTicket.mockResolvedValue({
      ok: true,
      data: makeDetail(makeTicket({ status: "in_progress" }), [
        makeEvent({
          id: "10000000-0000-4000-8000-000000000006",
          kind: "status_change",
          authorKind: "operator",
          authorAdminUsername: "dilnoza",
          authorTelegramUserIdMasked: null,
          fromStatus: "resolved",
          toStatus: "in_progress",
        }),
      ]),
    });
    renderScreen();

    expect(
      await screen.findByText("Resolved → In progress"),
    ).toBeInTheDocument();
    // `resolvedAt` is never cleared by a reopen, so the move itself says it came back.
    expect(screen.getAllByText("Reopened").length).toBeGreaterThan(0);
  });
});

describe("SupportTicketScreen — the moves on offer", () => {
  it("offers the three exits from new, and never a move to itself", async () => {
    renderScreen();

    expect(
      await screen.findByRole("button", { name: "Move to In progress" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Move to Waiting on customer" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move to New" }),
    ).not.toBeInTheDocument();
  });

  it("offers a resolved ticket exactly one exit, and calls it a reopen", async () => {
    getSupportTicket.mockResolvedValue({
      ok: true,
      data: makeDetail(
        makeTicket({ status: "resolved", resolvedAt: "2026-09-15T15:00:00Z" }),
      ),
    });
    renderScreen();

    expect(
      await screen.findByRole("button", { name: "Reopen" }),
    ).toBeInTheDocument();
    // `resolved -> waiting` is not in the grammar, and this screen must not invent it.
    expect(
      screen.queryByRole("button", { name: "Move to Waiting on customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Resolve" }),
    ).not.toBeInTheDocument();
  });

  it("sends the status the screen was drawn in as expectedStatus", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(
      await screen.findByRole("button", { name: "Move to In progress" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Move" }));

    const body = await lastMove();
    expect(body).toEqual({ expectedStatus: "new", toStatus: "in_progress" });
    expect(moveSupportTicket.mock.calls[0]?.[0]).toBe(TICKET_ID);
  });

  it("reports a 409 as the status the server found, and does not retry it", async () => {
    const user = userEvent.setup();
    moveSupportTicket.mockResolvedValue(MOVED_FIRST);
    renderScreen();

    await user.click(
      await screen.findByRole("button", { name: "Move to In progress" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Move" }));

    expect(
      await within(dialog).findByText("This ticket moved first"),
    ).toBeInTheDocument();
    // The status read a moment before the conditional UPDATE refused — usually a staffer
    // pressing ✅ Resolve on the card in the Telegram group.
    expect(within(dialog).getByText("Resolved")).toBeInTheDocument();
    // The same bytes lose the same race: the press is withdrawn rather than re-armed.
    expect(within(dialog).getByRole("button", { name: "Move" })).toBeDisabled();
    expect(moveSupportTicket).toHaveBeenCalledTimes(1);
  });
});

describe("SupportTicketScreen — a note and a reply cannot be confused", () => {
  it("warns that a reply cannot be unsent, and posts it to the reply route", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(
      await screen.findByRole("button", { name: "Reply to the customer" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(
        "These words go into somebody's phone. There is no way to unsend them.",
      ),
    ).toBeInTheDocument();
    // The language is the one the ticket was OPENED in, not the account's language today.
    expect(within(dialog).getByText(/Uzbek/)).toBeInTheDocument();

    const send = within(dialog).getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();

    await user.type(
      within(dialog).getByLabelText("Your answer"),
      "Kechirasiz, tuzatamiz.",
    );
    expect(send).toBeEnabled();
    await user.click(send);

    await waitFor(() => {
      expect(replyToSupportTicket).toHaveBeenCalledWith(TICKET_ID, {
        body: "Kechirasiz, tuzatamiz.",
      });
    });
    expect(addSupportTicketNote).not.toHaveBeenCalled();
  });

  it("says a note reaches nobody, and posts it to the notes route", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(
      await screen.findByRole("button", { name: "Add an internal note" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(
        /The customer never sees this — and neither do the staff working from the card/,
      ),
    ).toBeInTheDocument();

    await user.type(
      within(dialog).getByLabelText("Note"),
      "Order re-queued by hand.",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save the note" }),
    );

    await waitFor(() => {
      expect(addSupportTicketNote).toHaveBeenCalledWith(TICKET_ID, {
        body: "Order re-queued by hand.",
      });
    });
    expect(replyToSupportTicket).not.toHaveBeenCalled();
  });

  it("refuses a whitespace-only reply before the round trip", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(
      await screen.findByRole("button", { name: "Reply to the customer" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Your answer"), "   ");

    // A single space reaches the customer as an empty bubble, or as a Telegram refusal nobody
    // sees. `isSendableTicketBody` is the shared rule and it never trims what is stored.
    expect(within(dialog).getByRole("button", { name: "Send" })).toBeDisabled();
    expect(replyToSupportTicket).not.toHaveBeenCalled();
  });
});

describe("SupportTicketScreen — what a read-only role is shown", () => {
  it("states the refusal instead of drawing buttons that would 403", async () => {
    signIn("viewer");
    renderScreen();

    // This section's OWN sentence, not the shared `errors.detail.roleCannotTitle`. The
    // assertion is on the copy rather than on a test id because the whole value of the
    // sentence is that it names the permission a reader is missing — a generic "cannot do
    // this" would satisfy a looser assertion while telling the operator nothing.
    expect(
      await screen.findByText(
        "Your role can read tickets but not answer them.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reply to the customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add an internal note" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move to In progress" }),
    ).not.toBeInTheDocument();
  });

  it("hands a ticket over through the one write path, prefilled for a claim", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(await screen.findByRole("button", { name: "Take it" }));
    const dialog = await screen.findByRole("dialog");
    // Prefilled with the signed-in operator, and SHOWN before it is recorded: the column is
    // denormalised with no foreign key, so what is written is what the history says for ever.
    expect(within(dialog).getByLabelText("Operator username")).toHaveValue(
      "operator",
    );

    await user.click(within(dialog).getByRole("button", { name: "Hand over" }));
    await waitFor(() => {
      expect(assignSupportTicket).toHaveBeenCalledWith(TICKET_ID, {
        adminUsername: "operator",
      });
    });
  });
});
