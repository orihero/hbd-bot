import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BroadcastCreateRequest,
  BroadcastSendRequest,
  BroadcastTestSendRequest,
} from "@/api/broadcasts";
import type { SegmentPreviewView } from "@/api/segments";
import { SEGMENT_FIELDS_FIXTURE } from "@/components/SegmentBuilder/fixtures";
import { READY_PROGRESS, makeBroadcast, makeDetail } from "@/features/broadcasts/fixtures";
import { BroadcastWizardScreen } from "@/features/broadcasts/wizard/BroadcastWizardScreen";
import { useAuthStore } from "@/state/auth";

/**
 * The campaign wizard, driven the way an operator drives it.
 *
 * Four properties, and each one is a thing that would cost an audience if it broke:
 *
 * 1. **The happy path freezes ONCE and sends ONCE.** `POST /api/broadcasts` carries the count the
 *    operator was shown (`matched`, which is what the server re-counts) and the whole body set;
 *    `POST /{id}/send` carries the reason and — for "now" — no `scheduledFor` at all.
 * 2. **An audience nobody can be reached in does not advance.** `reachable`, never a sum of the
 *    overlapping skips, and never `matched`: a filter that selects forty thousand blocked
 *    accounts selects nobody to message.
 * 3. **The body ceiling is measured on the string Telegram will receive.** A thousand ampersands
 *    is a thousand characters typed and five thousand sent, and the second number is the one the
 *    server refuses on.
 * 4. **A step-up mid-send resumes without retyping anything, and without creating a second
 *    campaign.** The identical body is replayed against the identical campaign id.
 *
 * Only the FETCHERS are replaced. Every schema, hook, validator and catalogue string below is the
 * real one, and the field registry is `GET /api/segments/fields`'s own response.
 */

const { getSegmentFields, previewSegment, createBroadcast, sendBroadcast, testSendBroadcast, stepUp } =
  vi.hoisted(() => ({
    getSegmentFields: vi.fn(),
    previewSegment: vi.fn(),
    createBroadcast: vi.fn(),
    sendBroadcast: vi.fn(),
    testSendBroadcast: vi.fn(),
    stepUp: vi.fn(),
  }));

vi.mock("@/api/segments", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getSegmentFields, previewSegment };
});

vi.mock("@/api/broadcasts", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, createBroadcast, sendBroadcast, testSendBroadcast };
});

vi.mock("@/api/reveal", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, stepUp };
});

const BROADCAST_ID = "11111111-1111-4111-8111-111111111111";

/** One language, so the happy path is one body: the multi-language gate has its own test. */
const PREVIEW: SegmentPreviewView = {
  matched: 1_284,
  reachable: 1_200,
  skippedBlocked: 40,
  skippedBotBlocked: 44,
  byLanguage: [{ language: "ru", count: 1_200 }],
};

/** Where the campaign screen would be. It never renders one; it reports the URL it was handed. */
function DetailProbe(): JSX.Element {
  const location = useLocation();
  return <p data-testid="detail-url">{location.pathname}</p>;
}

function renderScreen(url = "/broadcasts/new"): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      {/* `MemoryRouter`, deliberately NOT `createMemoryRouter`: a data router builds a `Request`
          for every navigation and jsdom's `AbortSignal` is not the instance undici's `Request`
          accepts, so the URL silently never moves. */}
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/broadcasts/new" element={<BroadcastWizardScreen />} />
          <Route path="/broadcasts/:broadcastId" element={<DetailProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Step 1 → step 2, once the count has landed. */
async function toMessageStep(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await screen.findByText("1,200 people would be messaged");
  await user.click(screen.getByRole("button", { name: "Next: Message" }));
  await screen.findByLabelText("Campaign title");
}

/** Step 2 → step 3, with one valid Russian body. */
async function toReviewStep(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await toMessageStep(user);
  await user.type(screen.getByLabelText("Campaign title"), "August outage notice");
  fireEvent.change(screen.getByLabelText("Message in Russian"), {
    target: { value: "Мы восстановили доставку." },
  });
  await user.click(screen.getByRole("button", { name: "Next: Review and send" }));
  await screen.findByTestId("reason-code");
}

/** Reason, transcription, press. The three gestures that authorise a send. */
async function authorise(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.selectOptions(screen.getByTestId("reason-code"), "incident");
  await user.type(screen.getByLabelText("Type 1,200 to confirm the audience"), "1200");
  await user.click(
    screen.getByRole("button", { name: "Freeze the audience and send to 1,200 people now" }),
  );
}

function createdDetail(): ReturnType<typeof makeDetail> {
  return makeDetail(
    makeBroadcast({
      id: BROADCAST_ID,
      state: "ready",
      isTerminal: false,
      progress: READY_PROGRESS,
    }),
  );
}

beforeEach(() => {
  getSegmentFields.mockResolvedValue({ ok: true, data: SEGMENT_FIELDS_FIXTURE });
  previewSegment.mockResolvedValue({ ok: true, data: PREVIEW });
  createBroadcast.mockResolvedValue({ ok: true, data: createdDetail() });
  sendBroadcast.mockResolvedValue({ ok: true, data: createdDetail() });
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

describe("BroadcastWizardScreen — the whole path from a filter to a send", () => {
  it("freezes the audience once and sends once, carrying the count the operator was shown", async () => {
    const user = userEvent.setup();
    renderScreen();
    await toReviewStep(user);
    await authorise(user);

    await waitFor(() => {
      expect(createBroadcast).toHaveBeenCalledTimes(1);
    });
    const create = createBroadcast.mock.calls[0]?.[0] as BroadcastCreateRequest;
    expect(create.title).toBe("August outage notice");
    expect(create.kind).toBe("service");
    // `matched`, not `reachable`: the server re-counts the SEGMENT and compares against this.
    expect(create.expectedAudienceSize).toBe(1_284);
    // An empty document is everyone, and it travels as the document rather than as an absence.
    expect(create.segment.rules).toEqual([]);
    expect(create.bodies).toHaveLength(1);
    expect(create.bodies[0]?.language).toBe("ru");
    expect(create.bodies[0]?.text).toBe("Мы восстановили доставку.");
    expect(create.bodies[0]?.buttonLabel).toBeNull();

    await waitFor(() => {
      expect(sendBroadcast).toHaveBeenCalledTimes(1);
    });
    expect(sendBroadcast.mock.calls[0]?.[0]).toBe(BROADCAST_ID);
    const send = sendBroadcast.mock.calls[0]?.[1] as BroadcastSendRequest;
    expect(send.reasonCode).toBe("incident");
    // "Now" OMITS the field: its absence is what makes the server enqueue the job at once.
    expect("scheduledFor" in send).toBe(false);

    // The create is not idempotent, so the wizard leaves for the campaign on success.
    expect(await screen.findByTestId("detail-url")).toHaveTextContent(
      `/broadcasts/${BROADCAST_ID}`,
    );
  });

  it("keeps everything typed when the operator walks back through the steps", async () => {
    const user = userEvent.setup();
    renderScreen();
    await toReviewStep(user);

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByLabelText("Campaign title")).toHaveValue("August outage notice");
    await user.click(screen.getByRole("button", { name: "Back" }));
    // The audience is still the one the count was read from, and step 3 is still reachable.
    await screen.findByText("1,200 people would be messaged");
    await user.click(screen.getByRole("button", { name: "Next: Message" }));
    expect(screen.getByLabelText("Message in Russian")).toHaveValue("Мы восстановили доставку.");
  });

  it("refuses to advance from an audience nobody can be reached in", async () => {
    previewSegment.mockResolvedValue({
      ok: true,
      // Forty thousand matched and nobody reachable is an audience of nobody: the two skips
      // overlap, and only `reachable` is the complement.
      data: { ...PREVIEW, matched: 40_000, reachable: 0, byLanguage: [] },
    });
    renderScreen();

    await screen.findByText("0 people would be messaged");
    expect(
      screen.getByText(/Nobody in this audience can be reached/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next: Message" })).toBeDisabled();
    expect(createBroadcast).not.toHaveBeenCalled();
  });

  it("measures the body the way the server does — the rendered string, not the typed one", async () => {
    const user = userEvent.setup();
    renderScreen();
    await toMessageStep(user);

    // 1 000 ampersands: 1 000 characters typed, 5 000 on the wire. The raw bound passes and the
    // rendered one does not, and the server applies both.
    fireEvent.change(screen.getByLabelText("Message in Russian"), {
      target: { value: "&".repeat(1_000) },
    });

    expect(await screen.findByText(/5,000 characters, and Telegram takes 4,096/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Next: Review and send" })).toBeDisabled();
  });

  it("replays the identical send after a step-up, and creates no second campaign", async () => {
    const user = userEvent.setup();
    sendBroadcast.mockResolvedValueOnce({
      ok: false,
      code: "STEP_UP_REQUIRED",
      message: "this action needs your password again",
      status: 403,
      endpoint: "POST /api/broadcasts/{id}/send",
      correlationId: "c-1",
      issues: null,
      // VERBATIM: the server compares `broadcast.send:{id}` whole, so the pair is passed through
      // untouched or the retry is a permanent silent 403 that looks like a wrong password.
      details: { stepUpAction: "broadcast.send", subjectId: BROADCAST_ID },
      retryAfterS: null,
    });
    stepUp.mockResolvedValue({
      ok: true,
      data: {
        scope: `broadcast.send:${BROADCAST_ID}`,
        grantedAt: "2026-09-09T10:00:00Z",
        expiresAt: "2026-09-09T10:05:00Z",
      },
    });

    renderScreen();
    await toReviewStep(user);
    await authorise(user);

    const dialog = await screen.findByTestId("step-up-dialog");
    // The subject reaches the password box exactly as the refusal spelled it.
    expect(within(dialog).getByText(BROADCAST_ID)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/password/i), "correct horse");
    await user.click(within(dialog).getByRole("button", { name: "Re-authenticate" }));

    await waitFor(() => {
      expect(sendBroadcast).toHaveBeenCalledTimes(2);
    });
    // The same body, and the same campaign: re-authenticating authorises the action, it does not
    // compose a second send and it must not freeze a second audience.
    expect(sendBroadcast.mock.calls[1]?.[1]).toEqual(sendBroadcast.mock.calls[0]?.[1]);
    expect(sendBroadcast.mock.calls[1]?.[0]).toBe(BROADCAST_ID);
    expect(createBroadcast).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("detail-url")).toHaveTextContent(
      `/broadcasts/${BROADCAST_ID}`,
    );
  });

  it("surfaces an audience that drifted between the count and the press, and never sends through it", async () => {
    const user = userEvent.setup();
    createBroadcast.mockResolvedValueOnce({
      ok: false,
      code: "CONFLICT",
      message: "the audience has moved since it was counted",
      status: 409,
      endpoint: "POST /api/broadcasts",
      correlationId: "c-2",
      issues: null,
      details: { expectedAudienceSize: 1_284, audienceSize: 1_960 },
      retryAfterS: null,
    });

    renderScreen();
    await toReviewStep(user);
    await authorise(user);

    expect(await screen.findByText(/You were shown 1,284 accounts/)).toBeVisible();
    expect(screen.getByText(/the filter now selects 1,960/)).toBeVisible();
    // Nothing was authorised: the drift is a refusal to freeze, not a send against a new number.
    expect(sendBroadcast).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Go back and read the audience again" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Freeze it as it stands now (1,960)" }),
    ).toBeInTheDocument();
  });

  it("sends a test copy through the campaign, and says that confirming freezes the audience", async () => {
    const user = userEvent.setup();
    testSendBroadcast.mockResolvedValue({
      ok: true,
      data: {
        broadcastId: BROADCAST_ID,
        telegramUserIdMasked: "12•••89",
        jobId: "job-1",
        requestedAt: "2026-09-09T10:00:00Z",
      },
    });

    renderScreen();
    await toMessageStep(user);
    await user.type(screen.getByLabelText("Campaign title"), "August outage notice");
    fireEvent.change(screen.getByLabelText("Message in Russian"), {
      target: { value: "Мы восстановили доставку." },
    });

    await user.click(screen.getByRole("button", { name: /Send a test copy/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/FREEZES the audience now/)).toBeVisible();

    await user.type(
      within(dialog).getByLabelText("Telegram id of the test recipient"),
      "700000001",
    );
    await user.selectOptions(within(dialog).getByTestId("reason-code"), "incident");
    await user.click(within(dialog).getByRole("button", { name: "Send the test copy" }));

    await waitFor(() => {
      expect(testSendBroadcast).toHaveBeenCalledTimes(1);
    });
    // The campaign had to exist first, and it was created exactly once for both.
    expect(createBroadcast).toHaveBeenCalledTimes(1);
    expect(testSendBroadcast.mock.calls[0]?.[0]).toBe(BROADCAST_ID);
    const body = testSendBroadcast.mock.calls[0]?.[1] as BroadcastTestSendRequest;
    expect(body.telegramUserId).toBe(700000001);
    expect(body.reasonCode).toBe("incident");
  });
});
