/**
 * The pause / resume confirmation.
 *
 * Three properties, and each is one this section would be wrong without:
 *
 * 1. **A reason code is required before the write is allowed.** A body the server refuses as
 *    invalid writes NO audit row, which is the one failure mode of a privileged action that
 *    leaves no trace of the attempt — so the form withholds the confirm rather than letting an
 *    operator discover it as a 422.
 * 2. **The toolbar control re-renders from the RESPONSE, not from what was requested.** The
 *    handler writes the Redis key and reads it back; the two differ exactly when something
 *    went wrong, which is the case worth showing. The mutation seeds `isPaused` from that
 *    read-back, and the verb on the button is the only thing the list shows about the switch.
 * 3. **A 403 renders as a plain refusal and never as a password box.** This cell carries no
 *    step-up by explicit decision, so a `STEP_UP_REQUIRED` here would be a server bug and a
 *    credential prompt would offer a loop nobody can win.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RailStatus, RailSwitch } from "@/api/billing";
import { en } from "@/i18n/locales/en";

import { RailPauseDialog } from "./RailPauseDialog";
import { makeRailStatus } from "./fixtures";

const { postRailPause, postRailResume } = vi.hoisted(() => ({
  postRailPause: vi.fn(),
  postRailResume: vi.fn(),
}));

vi.mock("@/api/billing", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, postRailPause, postRailResume };
});

/**
 * The toolbar control and the dialog together, which is the pairing under test: what the
 * operator sees after a successful flip has to come from the server's read-back.
 *
 * The control is spelled out here rather than imported because it is three lines of
 * `IntentsScreen`'s toolbar — the verb, chosen by `isPaused`. Importing the whole list screen
 * would drag a router, a query and fifty rows in to assert one word.
 */
function Harness({ initial }: { readonly initial: RailStatus }): JSX.Element {
  const [status, setStatus] = useState(initial);
  const [isOpen, setIsOpen] = useState(true);
  return (
    <>
      <span data-testid="rail-pause-state">
        {status.isPaused ? en.billing.pause.resumeAction : en.billing.pause.pauseAction}
      </span>
      <RailPauseDialog
        isOpen={isOpen}
        willPause={!status.isPaused}
        onClose={() => {
          setIsOpen(false);
        }}
        onDone={(result: RailSwitch) => {
          setStatus({ ...status, isPaused: result.isPaused });
        }}
      />
    </>
  );
}

function renderDialog(initial: RailStatus = makeRailStatus()): void {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness initial={initial} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  postRailPause.mockResolvedValue({
    ok: true,
    data: { isPaused: true, pauseKey: "bayram:payme:paused", changedAt: "2026-09-10T09:05:00Z" },
  });
  postRailResume.mockResolvedValue({
    ok: true,
    data: { isPaused: false, pauseKey: "bayram:payme:paused", changedAt: "2026-09-10T09:06:00Z" },
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("RailPauseDialog", () => {
  it("withholds the confirm until a reason code is chosen", async () => {
    const user = userEvent.setup();
    renderDialog();

    const confirm = screen.getByRole("button", { name: en.billing.pause.pauseLabel });
    expect(confirm).toBeDisabled();

    await user.selectOptions(screen.getByTestId("reason-code"), "incident");
    expect(confirm).toBeEnabled();
  });

  it("sends nothing while the reason code is missing", async () => {
    const user = userEvent.setup();
    renderDialog();
    // The button is disabled, so this is a no-op — which is the point: a request that got out
    // without a reason would be a 422 that wrote no audit row.
    await user.click(screen.getByRole("button", { name: en.billing.pause.pauseLabel }));
    expect(postRailPause).not.toHaveBeenCalled();
  });

  it("repaints the control from the switch as STORED, not as requested", async () => {
    const user = userEvent.setup();
    // The server answers `isPaused: false` — as if the key were evicted between the write and
    // the read-back. The control must offer what the BOT would now need, not what was asked for.
    postRailPause.mockResolvedValue({
      ok: true,
      data: {
        isPaused: false,
        pauseKey: "bayram:payme:paused",
        changedAt: "2026-09-10T09:05:00Z",
      },
    });
    renderDialog();

    await user.selectOptions(screen.getByTestId("reason-code"), "incident");
    await user.click(screen.getByRole("button", { name: en.billing.pause.pauseLabel }));

    await waitFor(() => {
      expect(screen.getByTestId("rail-pause-state")).toHaveTextContent(
        en.billing.pause.pauseAction,
      );
    });
    expect(screen.getByTestId("rail-pause-state")).not.toHaveTextContent(
      en.billing.pause.resumeAction,
    );
  });

  it("shows the switch as paused when the server confirms it", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.selectOptions(screen.getByTestId("reason-code"), "incident");
    await user.click(screen.getByRole("button", { name: en.billing.pause.pauseLabel }));

    await waitFor(() => {
      expect(screen.getByTestId("rail-pause-state")).toHaveTextContent(
        en.billing.pause.resumeAction,
      );
    });
    expect(postRailPause).toHaveBeenCalledTimes(1);
    const body = postRailPause.mock.calls[0]?.[0] as { reasonCode: string };
    expect(body.reasonCode).toBe("incident");
  });

  it("renders a 403 with no details as a plain refusal, never as a password box", async () => {
    const user = userEvent.setup();
    postRailPause.mockResolvedValue({
      ok: false,
      code: "FORBIDDEN",
      message: "your role does not allow this",
      status: 403,
      endpoint: "POST /api/ops/rail/pause",
      correlationId: "corr-1",
      issues: null,
      // No `details`: a router-guard refusal with no remedy. This cell carries no step-up.
      details: null,
      retryAfterS: null,
    });
    renderDialog();

    await user.selectOptions(screen.getByTestId("reason-code"), "incident");
    await user.click(screen.getByRole("button", { name: en.billing.pause.pauseLabel }));

    await waitFor(() => {
      expect(screen.getByText("your role does not allow this")).toBeInTheDocument();
    });
    // No credential prompt anywhere: re-authenticating cannot clear a role refusal.
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(document.querySelector("input[type='password']")).toBeNull();
    // And the control is untouched — nothing moved, so nothing repaints.
    expect(screen.getByTestId("rail-pause-state")).toHaveTextContent(
      en.billing.pause.pauseAction,
    );
  });

  it("resumes from a paused rail with the resume verb on the button", async () => {
    const user = userEvent.setup();
    renderDialog(makeRailStatus({ isPaused: true }));

    await user.selectOptions(screen.getByTestId("reason-code"), "routine_ops");
    await user.click(screen.getByRole("button", { name: en.billing.pause.resumeLabel }));

    await waitFor(() => {
      expect(screen.getByTestId("rail-pause-state")).toHaveTextContent(
        en.billing.pause.pauseAction,
      );
    });
    expect(postRailResume).toHaveBeenCalledTimes(1);
    expect(postRailPause).not.toHaveBeenCalled();
  });
});
