/**
 * The re-authentication form on its own, because four later phases will mount it without a
 * reveal anywhere in sight.
 *
 * What is pinned here is the contract those phases depend on: the scope goes out as the BARE
 * action with the subject id untouched, a refusal is rendered as the server worded it (with
 * the one code that has a remedy calling that remedy out), and the grace note tells the truth
 * about a window that is zero for `user.purge` and `config.write` and non-zero for everything
 * else.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";

import { StepUpPrompt } from "./StepUpPrompt";

const SUBJECT = "3f2a9c10-8b44-4d21-9f0e-6a7c5b3e1d02";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function stub(response: () => Response): ReturnType<typeof vi.fn> {
  const calls = vi.fn((input: unknown) => {
    const url = String(input);
    if (url.includes("/api/auth/step-up")) return Promise.resolve(response());
    return Promise.reject(new Error(`unexpected request: ${url}`));
  });
  vi.stubGlobal("fetch", calls);
  return calls;
}

const GRANT = {
  scope: `reveal:${SUBJECT}`,
  grantedAt: "2026-09-02T10:30:00Z",
  expiresAt: "2026-09-02T10:35:00Z",
};

function renderPrompt(props: Partial<Parameters<typeof StepUpPrompt>[0]> = {}) {
  const onGranted = vi.fn();
  const result = renderWithProviders(
    <StepUpPrompt
      action="reveal"
      subjectId={SUBJECT}
      graceS={300}
      onGranted={onGranted}
      {...props}
    />,
    { client: makeTestQueryClient() },
  );
  return { ...result, onGranted };
}

function submit(password = "hunter2hunter2"): void {
  fireEvent.change(screen.getByLabelText("Your password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Re-authenticate" }));
}

beforeEach(() => {
  resetPrefs();
});

describe("StepUpPrompt", () => {
  it("sends the BARE action and the subject id byte-for-byte", async () => {
    const calls = stub(() => jsonResponse(200, GRANT));
    const { onGranted } = renderPrompt();
    submit();

    await waitFor(() => {
      expect(onGranted).toHaveBeenCalledWith(GRANT);
    });
    const init = calls.mock.calls[0]?.[1] as RequestInit | undefined;
    const raw = init?.body;
    if (typeof raw !== "string") throw new Error("the step-up carried no JSON body");
    const body = JSON.parse(raw) as Record<string, unknown>;
    expect(body["scope"]).toBe("reveal");
    expect(body["subjectId"]).toBe(SUBJECT);
    expect(body["password"]).toBe("hunter2hunter2");
  });

  it("will not submit an empty password — that is a 403 nobody needed to spend", () => {
    stub(() => jsonResponse(200, GRANT));
    renderPrompt();
    expect(screen.getByRole("button", { name: "Re-authenticate" })).toBeDisabled();
  });

  it("renders a wrong password as the server worded it", async () => {
    stub(() =>
      jsonResponse(403, {
        error: {
          code: "FORBIDDEN",
          message: "that is not your current password",
          correlationId: "c0ffee",
        },
      }),
    );
    const { onGranted } = renderPrompt();
    submit("wrong");

    const error = await screen.findByTestId("step-up-error");
    expect(error.textContent).toContain("that is not your current password");
    expect(onGranted).not.toHaveBeenCalled();
  });

  it("adds the remedy to REAUTH_RATE_LIMITED, which is why it is its own code", async () => {
    stub(() =>
      jsonResponse(429, {
        error: {
          code: "REAUTH_RATE_LIMITED",
          message: "too many re-authentication attempts",
          correlationId: "c0ffee",
        },
      }),
    );
    renderPrompt();
    submit();

    const error = await screen.findByTestId("step-up-error");
    expect(error.textContent).toContain("Signing in again starts a fresh window");
  });

  it("tells the truth about the grace window for each action", () => {
    stub(() => jsonResponse(200, GRANT));
    const { unmount } = renderPrompt();
    expect(screen.getByTestId("step-up-prompt").textContent).toContain("5 min");
    unmount();

    renderPrompt({ action: "user.purge", graceS: 300 });
    expect(screen.getByTestId("step-up-prompt").textContent).toContain(
      "expires the instant it is issued",
    );
  });
});
