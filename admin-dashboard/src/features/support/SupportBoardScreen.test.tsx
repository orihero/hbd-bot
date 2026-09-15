import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiFailure } from "@/api/client";
import type { SupportTicketsFilters, SupportTicketsPage } from "@/api/support";
import { SupportBoardScreen } from "@/features/support/SupportBoardScreen";
import { makeBoard, makeDetail, makeTicket } from "@/features/support/fixtures";
import { useAuthStore } from "@/state/auth";

/**
 * The Kanban board.
 *
 * Five properties make this a board rather than a table with colours, and each one is a thing an
 * operator would be misled by if it broke:
 *
 * 1. **The counts and the cards come from two different reads and describe ONE population.** A
 *    column's number is an exact `GROUP BY` bucket over everything that matches the filters; the
 *    cards under it are one keyset page. The list is therefore asked for `onlyDescribed: true` —
 *    the same exclusion the board endpoint forces on — or the board would draw cards its own
 *    numbers do not count.
 * 2. **A card offers only the moves the grammar allows.** A `resolved` ticket has exactly one
 *    exit and `waiting` is not it, so that column takes no drop and sends no request.
 * 3. **The keyboard path is the whole feature, not an extra.** Native HTML5 drag-and-drop is
 *    invisible to a keyboard and to a screen reader; Space picks up, the arrows choose, Space
 *    drops, Escape cancels, and every one of those says so out loud.
 * 4. **Every move names the column the card was drawn in.** `expectedStatus` is the lock the
 *    handler's `UPDATE` holds, and a 409 means a staffer moved the ticket from the Telegram
 *    group first — the card goes where the SERVER says it is, and nothing retries.
 * 5. **A role without `support.write` gets no move affordance at all.** Absent, not disabled: a
 *    press would be a 403 and a `permission.denied` audit row against somebody who did nothing.
 *
 * Only the three FETCHERS are replaced; every schema, enum, hook, transition table and format
 * helper the screen reads is the real one.
 */

const { getSupportBoard, listSupportTickets, moveSupportTicket } = vi.hoisted(() => ({
  getSupportBoard: vi.fn(),
  listSupportTickets: vi.fn(),
  moveSupportTicket: vi.fn(),
}));

vi.mock("@/api/support", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getSupportBoard, listSupportTickets, moveSupportTicket };
});

const EMPTY_PAGE: SupportTicketsPage = {
  items: [],
  meta: { nextCursor: null, total: 0, isTotalExact: true },
};

function pageOf(items: SupportTicketsPage["items"]): SupportTicketsPage {
  return { items, meta: { nextCursor: null, total: items.length, isTotalExact: true } };
}

/** A 409 from `POST /{id}/status`: the ticket moved under us, and the server says where to. */
function conflictOf(status: string): ApiFailure {
  return {
    ok: false,
    code: "CONFLICT",
    message: "The ticket is not in the expected state.",
    status: 409,
    endpoint: "POST /api/support/tickets/{ticketId}/status",
    correlationId: "c-1",
    issues: null,
    details: { status },
    retryAfterS: null,
  };
}

/**
 * jsdom implements no `DataTransfer`, and `@testing-library/dom` knows it — passing one in the
 * event init is defined onto the event verbatim. A plain object is enough: the screen writes
 * `effectAllowed`/`dropEffect` and calls `setData`, and nothing reads any of it back.
 */
function dataTransfer(): Record<string, unknown> {
  return { effectAllowed: "none", dropEffect: "none", setData: vi.fn(), getData: () => "" };
}

/** Where the ticket screen would be. It never renders one; it reports the URL it was handed. */
function TicketProbe(): JSX.Element {
  const location = useLocation();
  return <p data-testid="ticket-url">{location.pathname}</p>;
}

/*
 * `MemoryRouter`, deliberately NOT `createMemoryRouter`: a data router builds a `Request` for
 * every navigation and jsdom's `AbortSignal` is not the instance undici's `Request` accepts, so
 * `setSearchParams` rejects and the URL silently never moves. Written out in
 * `BroadcastsScreen.test.tsx`, and this screen writes four filters and a cursor to the URL.
 */
function renderScreen(url = "/support"): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/support" element={<SupportBoardScreen />} />
          <Route path="/support/:ticketId" element={<TicketProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** One column's list, by the heading it carries. */
async function columnList(name: RegExp): Promise<HTMLElement> {
  return screen.findByRole("list", { name });
}

/** The `<section>` around a column — the element that takes the drag. */
async function column(name: RegExp): Promise<HTMLElement> {
  const list = await columnList(name);
  const section = list.closest("section");
  if (section === null) throw new Error("a column list must sit inside its section");
  return section;
}

async function cardFor(reference: string): Promise<HTMLElement> {
  return screen.findByRole("listitem", { name: new RegExp(reference) });
}

async function lastListRequest(): Promise<SupportTicketsFilters> {
  await waitFor(() => {
    expect(listSupportTickets).toHaveBeenCalled();
  });
  const calls = listSupportTickets.mock.calls;
  return calls[calls.length - 1]?.[0] as SupportTicketsFilters;
}

beforeEach(() => {
  getSupportBoard.mockResolvedValue({ ok: true, data: makeBoard() });
  listSupportTickets.mockResolvedValue({ ok: true, data: EMPTY_PAGE });
  moveSupportTicket.mockResolvedValue({ ok: true, data: makeDetail() });
  useAuthStore.setState({
    account: {
      id: "00000000-0000-4000-8000-000000000001",
      username: "operator",
      role: "admin",
      lastLoginAt: null,
      mustChangePassword: false,
    },
  });
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("SupportBoardScreen — four columns over one population", () => {
  it("draws the four columns in board order with the board endpoint's exact counts", async () => {
    getSupportBoard.mockResolvedValue({
      ok: true,
      data: makeBoard({ new: 4, in_progress: 2, waiting: 1, resolved: 40 }),
    });
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "aaaa1111" })]),
    });
    renderScreen();

    await cardFor("aaaa1111");
    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent?.replace(/^\P{L}+/u, ""))).toEqual([
      "New",
      "In progress",
      "Waiting on customer",
      "Resolved",
    ]);
    // Exact GROUP BY buckets, so a plain number — never `formatTotal`'s "at least 40".
    expect(await screen.findByText("40 in this column")).toBeInTheDocument();
    expect(screen.queryByText(/at least 40/)).not.toBeInTheDocument();
    /* A parameter named wrongly at the call site renders its brace verbatim, in all three
       locales, and nothing else on the screen looks wrong — so the board is swept for one. */
    expect(document.body.textContent ?? "").not.toMatch(/\{[a-z]+\}/u);
  });

  it("asks the queue for the same population the columns count", async () => {
    renderScreen();

    const filters = await lastListRequest();
    // The board forces `onlyDescribed` on; a board drawing cards its counts exclude is the one
    // way these two reads can disagree.
    expect(filters.onlyDescribed).toBe(true);
    expect(filters.withTotal).toBe(true);
  });

  it("puts each ticket in its own column", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([
        makeTicket({ id: "a0000000-0000-4000-8000-000000000001", publicRef: "aaaa1111" }),
        makeTicket({
          id: "b0000000-0000-4000-8000-000000000002",
          publicRef: "bbbb2222",
          status: "waiting",
        }),
      ]),
    });
    renderScreen();

    await cardFor("aaaa1111");
    expect(within(await columnList(/^New/)).getByText("aaaa1111")).toBeInTheDocument();
    expect(within(await columnList(/^Waiting/)).getByText("bbbb2222")).toBeInTheDocument();
    expect(within(await columnList(/^New/)).queryByText("bbbb2222")).not.toBeInTheDocument();
  });

  it("opens the ticket, not a dialog, when its reference is pressed", async () => {
    const user = userEvent.setup();
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ id: "c0000000-0000-4000-8000-000000000003" })]),
    });
    renderScreen();

    await user.click(await screen.findByRole("button", { name: /Open ticket/ }));
    expect(screen.getByTestId("ticket-url")).toHaveTextContent(
      "/support/c0000000-0000-4000-8000-000000000003",
    );
  });
});

describe("SupportBoardScreen — only the moves the grammar allows", () => {
  it("refuses a drop the transition table forbids and sends nothing", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "rrrr9999", status: "resolved" })]),
    });
    renderScreen();

    const card = await cardFor("rrrr9999");
    const waiting = await column(/^Waiting/);
    const transfer = dataTransfer();

    fireEvent.dragStart(card, { dataTransfer: transfer });
    fireEvent.dragOver(waiting, { dataTransfer: transfer });
    // `resolved` has exactly one exit and it is `in_progress`. The column says why rather than
    // letting the operator find out through a 422.
    expect(
      within(waiting).getByText("A ticket in Resolved cannot be moved to Waiting on customer"),
    ).toBeInTheDocument();

    fireEvent.drop(waiting, { dataTransfer: transfer });
    await waitFor(() => {
      expect(screen.getByText(/cannot be moved to/)).toBeInTheDocument();
    });
    expect(moveSupportTicket).not.toHaveBeenCalled();
  });

  it("moves a card on a legal drop, naming the column it was drawn in", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([
        makeTicket({ id: "d0000000-0000-4000-8000-000000000004", publicRef: "dddd4444" }),
      ]),
    });
    renderScreen();

    const card = await cardFor("dddd4444");
    const inProgress = await column(/^In progress/);
    const transfer = dataTransfer();

    fireEvent.dragStart(card, { dataTransfer: transfer });
    fireEvent.dragOver(inProgress, { dataTransfer: transfer });
    fireEvent.drop(inProgress, { dataTransfer: transfer });

    await waitFor(() => {
      expect(moveSupportTicket).toHaveBeenCalledWith("d0000000-0000-4000-8000-000000000004", {
        expectedStatus: "new",
        toStatus: "in_progress",
      });
    });
  });
});

describe("SupportBoardScreen — a card moves without a mouse", () => {
  it("picks up, walks to a column and drops, announcing every step", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([
        makeTicket({ id: "e0000000-0000-4000-8000-000000000005", publicRef: "eeee5555" }),
      ]),
    });
    renderScreen();

    const card = await cardFor("eeee5555");
    card.focus();

    fireEvent.keyDown(card, { key: " " });
    expect(screen.getByText(/Ticket eeee5555 picked up from New/)).toBeInTheDocument();

    fireEvent.keyDown(card, { key: "ArrowRight" });
    expect(screen.getByText("Move to In progress")).toBeInTheDocument();

    fireEvent.keyDown(card, { key: " " });
    await waitFor(() => {
      expect(moveSupportTicket).toHaveBeenCalledWith("e0000000-0000-4000-8000-000000000005", {
        expectedStatus: "new",
        toStatus: "in_progress",
      });
    });
    expect(
      await screen.findByText("Ticket eeee5555 moved from New to In progress."),
    ).toBeInTheDocument();
  });

  it("puts the card back on Escape and sends nothing", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "ffff6666" })]),
    });
    renderScreen();

    const card = await cardFor("ffff6666");
    card.focus();
    fireEvent.keyDown(card, { key: " " });
    fireEvent.keyDown(card, { key: "ArrowRight" });
    fireEvent.keyDown(card, { key: "Escape" });

    expect(screen.getByText(/Move cancelled. Ticket ffff6666 is still in New/)).toBeInTheDocument();
    expect(moveSupportTicket).not.toHaveBeenCalled();
  });

  it("puts the card down where it was when the cursor walked back, without a write", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "jjjj0000" })]),
    });
    renderScreen();

    const card = await cardFor("jjjj0000");
    card.focus();
    fireEvent.keyDown(card, { key: " " });
    fireEvent.keyDown(card, { key: "ArrowRight" });
    fireEvent.keyDown(card, { key: "ArrowLeft" });
    fireEvent.keyDown(card, { key: " " });

    // A drop in the column it came from is a DROP and not a cancellation, and it is never a
    // move: `X -> X` is absent from every row of the grammar on purpose.
    expect(screen.getByText("Ticket jjjj0000 put back in New.")).toBeInTheDocument();
    expect(moveSupportTicket).not.toHaveBeenCalled();
  });

  it("never walks the cursor into a column the grammar refuses", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "gggg7777", status: "resolved" })]),
    });
    renderScreen();

    const card = await cardFor("gggg7777");
    card.focus();
    fireEvent.keyDown(card, { key: " " });
    // The lane is [In progress, Resolved]: one step left is the only exit `resolved` has, and a
    // second step is clamped rather than wrapped onto `New`, which nothing ever returns to.
    fireEvent.keyDown(card, { key: "ArrowLeft" });
    expect(screen.getByText("Move to In progress")).toBeInTheDocument();
    fireEvent.keyDown(card, { key: "ArrowLeft" });
    expect(screen.getByText("Move to In progress")).toBeInTheDocument();

    fireEvent.keyDown(card, { key: " " });
    await waitFor(() => {
      expect(moveSupportTicket).toHaveBeenCalledWith(expect.any(String), {
        expectedStatus: "resolved",
        toStatus: "in_progress",
      });
    });
  });
});

describe("SupportBoardScreen — the ticket that moved first", () => {
  it("rolls the card into the status the server found and offers no retry", async () => {
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "hhhh8888" })]),
    });
    moveSupportTicket.mockResolvedValue(conflictOf("resolved"));
    renderScreen();

    const card = await cardFor("hhhh8888");
    card.focus();
    fireEvent.keyDown(card, { key: " " });
    fireEvent.keyDown(card, { key: "ArrowRight" });
    fireEvent.keyDown(card, { key: " " });

    expect(await screen.findByText("This ticket moved first")).toBeInTheDocument();
    // Not back in New and not in the column the operator aimed at: where the SERVER says it is.
    await waitFor(async () => {
      expect(within(await columnList(/^Resolved/)).getByText("hhhh8888")).toBeInTheDocument();
    });
    // The same bytes lose the same race, so the note carries no Retry.
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
  });
});

describe("SupportBoardScreen — a role that cannot write", () => {
  it("withholds the drag handle, the pick-up and the instructions from a viewer", async () => {
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000002",
        username: "watcher",
        role: "viewer",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    listSupportTickets.mockResolvedValue({
      ok: true,
      data: pageOf([makeTicket({ publicRef: "iiii9999" })]),
    });
    renderScreen();

    const card = await cardFor("iiii9999");
    expect(card).not.toHaveAttribute("draggable", "true");
    expect(screen.queryByText(/Press Space to pick a ticket up/)).not.toBeInTheDocument();

    card.focus();
    fireEvent.keyDown(card, { key: " " });
    expect(screen.queryByText(/picked up/)).not.toBeInTheDocument();
    expect(moveSupportTicket).not.toHaveBeenCalled();
  });
});
