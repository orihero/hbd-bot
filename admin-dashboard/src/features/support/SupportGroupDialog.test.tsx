import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiFailure } from "@/api/client";
import type { SupportGroupView } from "@/api/support";
import { SupportGroupDialog } from "@/features/support/SupportGroupDialog";
import {
  makeDirectory,
  makeFailedGroup,
  makeGroup,
  makeUnverifiedGroup,
} from "@/features/support/fixtures";
import { useAuthStore } from "@/state/auth";

/**
 * The Support group picker.
 *
 * Six properties make this dialog worth having rather than the environment variable it replaced,
 * and every one of them is a thing an operator would be actively misled by if it broke:
 *
 * 1. **A Select does not mean it works.** The admin process cannot talk to Telegram; it records
 *    the selection and queues a job. The row must move to "checking…" and never to a tick.
 * 2. **The badge comes from `verifiedAt`/`verificationError` and NEVER from `botStatus`.** The
 *    two tests below run the pair in opposite directions on purpose: an `administrator` the
 *    worker has not proved reads as unchecked, and a bot Telegram says has LEFT but that a job
 *    proved it could post in reads as working.
 * 3. **`source` is drawn.** Telegram's own word and an operator's paste look different, because
 *    drawing them identically presents a typo with the confidence of a fact.
 * 4. **`verificationError` crosses verbatim and whole** — it is the worker's English prose, and
 *    the migrated-group case carries the group's NEW chat id, which is the entire recovery path.
 * 5. **`threadId` travels with the selection.** Omitting it clears the topic server-side, so a
 *    re-select of a row that has one must send it back.
 * 6. **A role without `support.group.write` gets no controls at all** — absent, not disabled —
 *    and one sentence naming the permission.
 *
 * Only the three FETCHERS are replaced; every schema, enum, hook, format table and permission
 * check the dialog reads is the real one.
 */

const { listSupportGroups, selectSupportGroup, clearSupportGroup } = vi.hoisted(() => ({
  listSupportGroups: vi.fn(),
  selectSupportGroup: vi.fn(),
  clearSupportGroup: vi.fn(),
}));

vi.mock("@/api/support", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listSupportGroups, selectSupportGroup, clearSupportGroup };
});

/** A refusal, in the shape `api/client.ts` builds one. */
function failureOf(status: number, code: string, details: Record<string, unknown> | null): ApiFailure {
  return {
    ok: false,
    code,
    message: "The request was refused.",
    status,
    endpoint: "POST /api/support/groups/select",
    correlationId: "c-1",
    issues: null,
    details,
    retryAfterS: null,
  };
}

function renderDialog(onClose: () => void = vi.fn()): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/support"]}>
        <SupportGroupDialog onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The `<li>` for one chat, found by the name the dialog draws it under. */
async function row(name: string | RegExp): Promise<HTMLElement> {
  const list = await screen.findByRole("list", { name: /chats the bot knows about/i });
  const items = within(list).getAllByRole("listitem");
  const found = items.find((item) =>
    typeof name === "string" ? item.textContent?.includes(name) : name.test(item.textContent ?? ""),
  );
  if (found === undefined) throw new Error(`no row for ${String(name)}`);
  return found;
}

function asRole(role: "viewer" | "support" | "admin" | "owner"): void {
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
  listSupportGroups.mockResolvedValue({ ok: true, data: makeDirectory() });
  selectSupportGroup.mockResolvedValue({
    ok: true,
    data: {
      groups: makeDirectory().groups,
      selection: {
        chatId: -1_001_234_567_890,
        previousChatId: null,
        threadId: null,
        created: false,
        moved: true,
      },
    },
  });
  clearSupportGroup.mockResolvedValue({ ok: true, data: { groups: [], clearedChatId: null } });
  asRole("admin");
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("SupportGroupDialog — what the directory says", () => {
  it("draws every known chat in the order the server returned, selected one first", async () => {
    const selected = makeGroup({
      chatId: -100_1,
      title: "Support",
      isSupportGroup: true,
      selectedByUsername: "dilnoza",
      selectedAt: "2026-09-15T10:00:00Z",
    });
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([selected, makeGroup({ chatId: -100_2, title: "Marketing" })]),
    });

    renderDialog();

    const list = await screen.findByRole("list", { name: /chats the bot knows about/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]?.textContent).toContain("Support");
    expect(items[1]?.textContent).toContain("Marketing");
  });

  it("names a chat by its title, its handle, or — failing both — its raw id", async () => {
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([
        makeGroup({ chatId: -100_1, title: "Support desk" }),
        makeGroup({ chatId: -100_2, title: null, username: "bayram_support" }),
        makeGroup({ chatId: -100_3, title: null, username: null }),
      ]),
    });

    renderDialog();

    expect(await row("Support desk")).toBeTruthy();
    expect((await row("@bayram_support")).textContent).toContain("@bayram_support");
    /* No invented placeholder: the id is the honest last resort and is what an operator matches
       against Telegram. */
    expect((await row("-1003")).textContent).toContain("-1003");
  });

  it("draws Telegram's own word and an operator's paste as different things", async () => {
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([
        makeGroup({ chatId: -100_1, title: "From Telegram" }),
        makeUnverifiedGroup({ chatId: -100_2, title: "Pasted in" }),
      ]),
    });

    renderDialog();

    expect((await row("From Telegram")).textContent).toContain("Telegram told us");
    expect((await row("Pasted in")).textContent).toContain("Typed in");
  });
});

describe("SupportGroupDialog — the badge is the verification, never the bot's standing", () => {
  it("shows an administrator nobody has checked as checking, not as working", async () => {
    /* The trap this whole feature is built around: Telegram says the bot is an administrator,
       which says nothing about whether it can post — `can_post_messages` can be taken away with
       no membership transition at all. */
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([
        makeGroup({ title: "Admin but unproved", botStatus: "administrator", verifiedAt: null }),
      ]),
    });

    renderDialog();

    const item = await row("Admin but unproved");
    expect(item.textContent).toContain("Administrator");
    expect(item.textContent).toContain("Checking…");
    expect(item.textContent).not.toContain("Posting works");
  });

  it("shows a chat a job proved it could post in as working, whatever Telegram last said", async () => {
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([
        makeGroup({ title: "Proved", botStatus: "left", verifiedAt: "2026-09-15T13:00:00Z" }),
      ]),
    });

    renderDialog();

    const item = await row("Proved");
    expect(item.textContent).toContain("Posting works");
  });

  it("renders the worker's failure verbatim, including the new id after a migration", async () => {
    const migrated = makeFailedGroup({ title: "Old group" });
    listSupportGroups.mockResolvedValue({ ok: true, data: makeDirectory([migrated]) });

    renderDialog();

    const item = await row("Old group");
    expect(item.textContent).toContain("Cannot post");
    /* The WHOLE string, not a truncation: the number in it is what an operator copies into the
       paste field below, and it is the only route back to a group Telegram upgraded. */
    expect(item.textContent).toContain(migrated.verificationError);
    expect(item.textContent).toContain("-1001987654321");
  });
});

describe("SupportGroupDialog — selecting is honest about being asynchronous", () => {
  it("sends the row's own topic back, so a re-select does not clear it", async () => {
    const withTopic = makeGroup({ title: "Forum", threadId: 42, isSupportGroup: true });
    listSupportGroups.mockResolvedValue({ ok: true, data: makeDirectory([withTopic]) });

    renderDialog();

    const item = await row("Forum");
    await userEvent.click(within(item).getByRole("button", { name: /post ticket cards to/i }));

    await waitFor(() => {
      expect(selectSupportGroup).toHaveBeenCalledWith({
        chatId: withTopic.chatId,
        threadId: 42,
      });
    });
  });

  it("omits the topic for a chat that has none, rather than sending a zero", async () => {
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([makeGroup({ title: "Plain", threadId: null })]),
    });

    renderDialog();

    const item = await row("Plain");
    await userEvent.click(within(item).getByRole("button", { name: /post ticket cards to/i }));

    await waitFor(() => {
      expect(selectSupportGroup).toHaveBeenCalledWith({ chatId: -1_001_234_567_890 });
    });
  });

  it("moves a freshly selected chat to checking and never claims it works", async () => {
    const fresh: SupportGroupView = makeGroup({
      title: "Just chosen",
      isSupportGroup: true,
      verifiedAt: null,
      verificationError: null,
    });
    /* The read answers the pre-select state once, then the post-select state — which is what a
       real server does, because the write's own answer is seeded and then re-read. */
    listSupportGroups.mockResolvedValueOnce({
      ok: true,
      data: makeDirectory([makeGroup({ title: "Just chosen", verifiedAt: null })]),
    });
    listSupportGroups.mockResolvedValue({ ok: true, data: makeDirectory([fresh]) });
    selectSupportGroup.mockResolvedValue({
      ok: true,
      data: {
        groups: [fresh],
        selection: {
          chatId: fresh.chatId,
          previousChatId: null,
          threadId: null,
          created: false,
          moved: true,
        },
      },
    });

    renderDialog();

    const item = await row("Just chosen");
    await userEvent.click(within(item).getByRole("button", { name: /post ticket cards to/i }));

    await waitFor(() => {
      expect(screen.getByText(/receives tickets/i)).toBeTruthy();
    });
    expect(screen.getAllByText(/checking…/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/posting works/i)).toBeNull();
  });
});

describe("SupportGroupDialog — the paste field refuses a person", () => {
  it("names the mistake and sends nothing when the id has no minus", async () => {
    renderDialog();

    const field = await screen.findByLabelText("Chat id");
    await userEvent.type(field, "48219");

    expect(screen.getByText(/that is not a group/i)).toBeTruthy();
    const submit = screen.getAllByRole("button", { name: /post tickets here/i })[0];
    expect(submit).toBeDefined();
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect(selectSupportGroup).not.toHaveBeenCalled();
  });

  it("sends a pasted id with its topic when both are given", async () => {
    renderDialog();

    await userEvent.type(await screen.findByLabelText("Chat id"), "-1009876543210");
    await userEvent.type(await screen.findByLabelText("Topic id (optional)"), "77");

    const buttons = screen.getAllByRole("button", { name: /post tickets here/i });
    const submit = buttons[buttons.length - 1];
    expect(submit).toBeDefined();
    await userEvent.click(submit as HTMLElement);

    await waitFor(() => {
      expect(selectSupportGroup).toHaveBeenCalledWith({
        chatId: -1_009_876_543_210,
        threadId: 77,
      });
    });
  });
});

describe("SupportGroupDialog — the refusals", () => {
  it("tells an operator a 503 selection HAPPENED, rather than that nothing was written", async () => {
    selectSupportGroup.mockResolvedValue(failureOf(503, "SERVICE_UNAVAILABLE", null));

    renderDialog();

    const item = await row("Bayram");
    await userEvent.click(within(item).getByRole("button", { name: /post ticket cards to/i }));

    /* The enqueue follows the COMMIT. Telling somebody "nothing was written" here would be the
       one lie this feature exists to remove. */
    expect(await screen.findByText(/selected, and nothing can check it/i)).toBeTruthy();
    expect(screen.getByText(/the change is saved/i)).toBeTruthy();
  });

  it("reports a concurrent double press as somebody else having changed it first", async () => {
    selectSupportGroup.mockResolvedValue(
      failureOf(409, "CONFLICT", { index: "ix_bot_chats_selected_support_group" }),
    );

    renderDialog();

    const item = await row("Bayram");
    await userEvent.click(within(item).getByRole("button", { name: /post ticket cards to/i }));

    expect(await screen.findByText(/somebody else changed it first/i)).toBeTruthy();
  });
});

describe("SupportGroupDialog — reading is every role; writing is not", () => {
  it("shows a support operator the directory and the verification state", async () => {
    asRole("support");
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([makeGroup({ title: "Support", isSupportGroup: true })]),
    });

    renderDialog();

    expect((await row("Support")).textContent).toContain("Posting works");
    expect(screen.getByText(/ticket cards go to/i)).toBeTruthy();
  });

  it("withholds every control from a role without support.group.write, and names it", async () => {
    asRole("support");
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([makeGroup({ title: "Support", isSupportGroup: true })]),
    });

    renderDialog();

    await row("Support");
    /* Absent, not disabled: a press would be a 403 and a `permission.denied` audit row against
       somebody who did nothing wrong. */
    expect(screen.queryByRole("button", { name: /post ticket cards to/i })).toBeNull();
    expect(screen.queryByLabelText("Chat id")).toBeNull();
    expect(screen.queryByRole("button", { name: /stop posting to a group/i })).toBeNull();
    /* This section's own sentence, naming the permission — not the generic role refusal. */
    expect(screen.getByText(/support\.group\.write/i)).toBeTruthy();
  });

  it("offers Clear only while a group is selected, and calls the clear route", async () => {
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([makeGroup({ title: "Support", isSupportGroup: true })]),
    });

    renderDialog();

    const clear = await screen.findByRole("button", { name: /stop posting to a group/i });
    await userEvent.click(clear);

    await waitFor(() => {
      expect(clearSupportGroup).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText(/no group is selected/i)).toBeTruthy();
  });

  it("hides Clear when nothing is selected — there is nothing to stop", async () => {
    listSupportGroups.mockResolvedValue({
      ok: true,
      data: makeDirectory([makeGroup({ title: "Support", isSupportGroup: false })]),
    });

    renderDialog();

    await row("Support");
    expect(screen.queryByRole("button", { name: /stop posting to a group/i })).toBeNull();
    /* And the state is stated as supported rather than drawn as a fault. */
    expect(screen.getByText(/no group is selected/i)).toBeTruthy();
  });
});

describe("SupportGroupDialog — the modal contract", () => {
  it("is a dialog, is labelled by its own heading, and closes on Escape", async () => {
    const onClose = vi.fn();
    renderDialog(onClose);

    const dialog = await screen.findByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(within(dialog).getByRole("heading", { level: 2 }).textContent).toMatch(
      /where ticket cards are posted/i,
    );

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("says out loud why a group the bot is already in may not be listed", async () => {
    renderDialog();
    /* Telegram has no "list my groups" API. An operator who has not been told that reads the
       missing group as a bug in this panel. */
    expect(
      await screen.findByText(/gives a bot no list of its groups/i),
    ).toBeTruthy();
  });
});
