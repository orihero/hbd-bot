import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BroadcastSendRequest, BroadcastRecipientsPage } from "@/api/broadcasts";
import { SEGMENT_FIELDS_FIXTURE } from "@/components/SegmentBuilder/fixtures";
import { BroadcastDetailScreen } from "@/features/broadcasts/BroadcastDetailScreen";
import {
  READY_PROGRESS,
  SENDING_PROGRESS,
  makeBroadcast,
  makeDetail,
  makeRecipient,
} from "@/features/broadcasts/fixtures";
import { useAuthStore } from "@/state/auth";

/**
 * One campaign.
 *
 * What has to hold, and what each failure would cost:
 *
 * 1. **The actions match the state.** Send appears only from `ready`; Pause only while
 *    `sending`; Resume only while `paused`; Cancel until the campaign is terminal. A Send button
 *    on a sending campaign is a 409 an operator would read as the console being broken.
 * 2. **The send names the real recipient count, twice.** In the warning and on the confirm
 *    button, which is the last thing read before forty thousand people are messaged.
 * 3. **Both counts of the funnel are rendered**, and `unknown` is its own number — never folded
 *    into `failed`, because those rows may well have arrived.
 * 4. **The frozen audience is chips with no remove button.** Changing who hears a message is a
 *    new campaign, so there is nothing an edit here could mean.
 * 5. **The ledger carries no Telegram id at any role**, and an erased row says so rather than
 *    rendering an empty cell.
 *
 * The registry behind the audience chips is the REAL `GET /api/segments/fields`.
 */

const { getBroadcast, listBroadcastRecipients, sendBroadcast, getSegmentFields } = vi.hoisted(
  () => ({
    getBroadcast: vi.fn(),
    listBroadcastRecipients: vi.fn(),
    sendBroadcast: vi.fn(),
    getSegmentFields: vi.fn(),
  }),
);

vi.mock("@/api/broadcasts", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getBroadcast, listBroadcastRecipients, sendBroadcast };
});

vi.mock("@/api/segments", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getSegmentFields };
});

const BROADCAST_ID = "11111111-1111-4111-8111-111111111111";

/*
 * The Send button's accessible name, which is its `aria-label` and not its visible word.
 * `/Send/` alone would also match the ledger's "Sending" outcome chip — a real ambiguity on
 * this screen, and the reason the action carries a name that says what pressing it does.
 */
const SEND_ACTION = /Send — authorise this campaign/;

const EMPTY_LEDGER: BroadcastRecipientsPage = {
  items: [],
  meta: { nextCursor: null, total: 0, isTotalExact: true },
};

function renderScreen(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/broadcasts/${BROADCAST_ID}`]}>
        <Routes>
          <Route path="/broadcasts/:broadcastId" element={<BroadcastDetailScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The body of the most recent `POST /api/broadcasts/{id}/send`, once one has been made. */
async function lastSend(): Promise<BroadcastSendRequest> {
  await waitFor(() => {
    expect(sendBroadcast).toHaveBeenCalled();
  });
  const calls = sendBroadcast.mock.calls;
  return calls[calls.length - 1]?.[1] as BroadcastSendRequest;
}

beforeEach(() => {
  getBroadcast.mockResolvedValue({ ok: true, data: makeDetail() });
  listBroadcastRecipients.mockResolvedValue({ ok: true, data: EMPTY_LEDGER });
  getSegmentFields.mockResolvedValue({ ok: true, data: SEGMENT_FIELDS_FIXTURE });
  sendBroadcast.mockResolvedValue({ ok: true, data: makeDetail() });
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

describe("BroadcastDetailScreen — the actions the state permits", () => {
  it("offers Send and Cancel on a ready campaign, and neither Pause nor Resume", async () => {
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(
        makeBroadcast({ state: "ready", isTerminal: false, progress: READY_PROGRESS }),
      ),
    });
    renderScreen();

    expect(await screen.findByRole("button", { name: SEND_ACTION })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel campaign" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("offers Pause and Cancel while sending, and never a second Send", async () => {
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(
        makeBroadcast({ state: "sending", isTerminal: false, progress: SENDING_PROGRESS }),
      ),
    });
    renderScreen();

    expect(await screen.findByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel campaign" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: SEND_ACTION })).not.toBeInTheDocument();
  });

  it("offers Resume, and not Pause, on a paused campaign", async () => {
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(
        makeBroadcast({ state: "paused", isTerminal: false, progress: SENDING_PROGRESS }),
      ),
    });
    renderScreen();

    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("offers no lifecycle action at all on a terminal campaign", async () => {
    renderScreen(); // the default fixture is `completed`, which `isTerminal` says is over

    await screen.findByText("August outage notice");
    expect(screen.queryByRole("button", { name: SEND_ACTION })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel campaign" })).not.toBeInTheDocument();
  });

  it("shows a read-only role the reason rather than a button that would 403", async () => {
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000002",
        username: "watcher",
        role: "support",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(
        makeBroadcast({ state: "ready", isTerminal: false, progress: READY_PROGRESS }),
      ),
    });
    renderScreen();

    expect(
      await screen.findByText(/Your role can read campaigns but not send them/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: SEND_ACTION })).not.toBeInTheDocument();
  });
});

describe("BroadcastDetailScreen — the send confirmation", () => {
  async function openSendDialog(): Promise<ReturnType<typeof userEvent.setup>> {
    const user = userEvent.setup();
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(
        makeBroadcast({ state: "ready", isTerminal: false, progress: READY_PROGRESS }),
      ),
    });
    renderScreen();
    await user.click(await screen.findByRole("button", { name: SEND_ACTION }));
    return user;
  }

  it("names the exact recipient count in the warning and on the confirm button", async () => {
    await openSendDialog();

    const dialog = await screen.findByRole("dialog");
    // 1,284 rows are what will actually be attempted — `recipientCount`, not a rounded audience.
    expect(within(dialog).getByText(/1,284 people will receive this message/)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Send to 1,284 people now" }),
    ).toBeInTheDocument();
  });

  it("says when the audience was frozen, beside the number", async () => {
    await openSendDialog();

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/That audience was frozen .* and is not recounted now/),
    ).toBeInTheDocument();
  });

  it("withholds the send until a reason code is chosen, then sends without scheduledFor", async () => {
    const user = await openSendDialog();

    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Send to 1,284 people now" });
    // A body with no `reasonCode` is a 422 that writes NO audit row — the wrong way to fail a
    // privileged action, so the press is withheld rather than the refusal discovered.
    expect(confirm).toBeDisabled();

    await user.selectOptions(within(dialog).getByTestId("reason-code"), "incident");
    expect(confirm).toBeEnabled();

    await user.click(confirm);
    const body = await lastSend();
    expect(body.reasonCode).toBe("incident");
    // "Now" OMITS the field: its absence is what makes the server enqueue the job at once.
    expect("scheduledFor" in body).toBe(false);
    expect(sendBroadcast.mock.calls[0]?.[0]).toBe(BROADCAST_ID);
  });

  it("refuses a scheduled instant in the past before the round trip", async () => {
    const user = await openSendDialog();

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Schedule for later" }));
    await user.selectOptions(within(dialog).getByTestId("reason-code"), "incident");

    const at = within(dialog).getByLabelText("Send at");
    await user.type(at, "2020-01-01T09:00");

    expect(
      within(dialog).getByText(/That instant has already passed/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /Schedule for 1,284 people/ }),
    ).toBeDisabled();
    expect(sendBroadcast).not.toHaveBeenCalled();
  });
});

describe("BroadcastDetailScreen — what the numbers and the audience may claim", () => {
  it("renders both counts of the funnel, with unknown as its own number", async () => {
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(makeBroadcast(), {
        // The rollup lags the ledger mid-send; both are true and both are shown.
        countedProgress: { ...SENDING_PROGRESS, unknownCount: 7 },
      }),
    });
    renderScreen();

    expect(await screen.findByText("Worker rollup")).toBeInTheDocument();
    expect(screen.getByText("Recounted from rows")).toBeInTheDocument();

    const unknownRow = screen.getByRole("rowheader", { name: "Unknown" }).closest("tr");
    expect(unknownRow).not.toBeNull();
    // 10 in the rollup, 7 in the recount — and neither is added to the 300 failures.
    expect(within(unknownRow as HTMLElement).getByText("10")).toBeInTheDocument();
    expect(within(unknownRow as HTMLElement).getByText("7")).toBeInTheDocument();
  });

  it("draws the frozen audience as chips with no remove control on any of them", async () => {
    renderScreen();

    const chips = await screen.findByRole("group", { name: "The frozen audience" });
    expect(within(chips).getByText(/Songs delivered/)).toBeInTheDocument();
    expect(within(chips).queryByRole("button")).not.toBeInTheDocument();
  });

  it("says EVERYONE when the stored document carries no rules at all", async () => {
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(makeBroadcast(), { segment: { v: 1, match: "all", rules: [] } }),
    });
    renderScreen();

    expect(await screen.findByText(/it is EVERY account, not an empty selection/)).toBeInTheDocument();
  });

  it("reports an unreadable stored filter as a state, never as 'no filter'", async () => {
    getBroadcast.mockResolvedValue({
      ok: true,
      data: makeDetail(makeBroadcast(), { segment: null, isSegmentReadable: false }),
    });
    renderScreen();

    expect(await screen.findByText(/cannot read the stored filter/)).toBeInTheDocument();
  });
});

describe("BroadcastDetailScreen — the recipient ledger", () => {
  it("renders masked recipients and no Telegram id column", async () => {
    listBroadcastRecipients.mockResolvedValue({
      ok: true,
      data: {
        items: [makeRecipient(), makeRecipient({
          id: "44444444-4444-4444-8444-444444444444",
          telegramUserIdMasked: "•••••321",
          state: "failed",
          errorCode: "TELEGRAM_FORBIDDEN",
          attempts: 2,
        })],
        meta: { nextCursor: null, total: 2, isTotalExact: true },
      },
    });
    renderScreen();

    expect(await screen.findByText("•••••789")).toBeInTheDocument();
    expect(screen.getByText("TELEGRAM_FORBIDDEN")).toBeInTheDocument();
    expect(
      screen.getByText(/There is no Telegram id column here at any role/),
    ).toBeInTheDocument();
  });

  it("renders an erased recipient as erased rather than as an empty cell", async () => {
    listBroadcastRecipients.mockResolvedValue({
      ok: true,
      data: {
        items: [makeRecipient({ telegramUserIdMasked: null, isErased: true })],
        meta: { nextCursor: null, total: 1, isTotalExact: true },
      },
    });
    renderScreen();

    expect(await screen.findByText("erased on request")).toBeInTheDocument();
  });
});
