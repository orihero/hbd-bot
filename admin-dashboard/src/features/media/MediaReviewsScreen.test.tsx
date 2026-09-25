/**
 * The media review queue (IMAGE_VIDEO_SPEC §6.6, §10 M3.2), the screen half.
 *
 * 1. **The queue shows codes and timings** — and the decision buttons only to a role holding
 *    `media.moderate`.
 * 2. **A refund's `STEP_UP_REQUIRED` opens the password prompt**, the grant is asked for the
 *    REVIEW the refusal named, and the identical body goes again.
 * 3. **A release needs no step-up** and is sent once.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiFailure } from "@/api/client";
import type { MediaReviewView } from "@/api/media";
import { en } from "@/i18n/locales/en";
import { useAuthStore } from "@/state/auth";

import { MediaReviewsScreen } from "./MediaReviewsScreen";

const { getMediaReviews, postMediaReviewRefund, postMediaReviewRelease, stepUp } = vi.hoisted(
  () => ({
    getMediaReviews: vi.fn(),
    postMediaReviewRefund: vi.fn(),
    postMediaReviewRelease: vi.fn(),
    stepUp: vi.fn(),
  }),
);

vi.mock("@/api/media", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getMediaReviews, postMediaReviewRefund, postMediaReviewRelease };
});

vi.mock("@/api/reveal", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, stepUp };
});

const REVIEW: MediaReviewView = {
  id: "0b8f6c1e-2d3a-4c5b-9e7f-1a2b3c4d5e6f",
  jobId: "7a1c2e3f-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
  kind: "image",
  sku: "image",
  jobState: "held",
  paidVia: "payme",
  source: "output_review",
  subject: "output_image",
  categories: ["violence"],
  outputsRequested: 2,
  createdAt: "2026-09-25T09:00:00Z",
  dueAt: "2026-09-26T09:00:00Z",
  decision: null,
  decidedAt: null,
  actor: null,
  reasonCode: null,
  appliedAt: null,
  isRefundable: true,
};

const STEP_UP_REFUSAL: ApiFailure = {
  ok: false,
  code: "STEP_UP_REQUIRED",
  message: "re-authenticate for this action and this subject",
  status: 403,
  endpoint: "POST /api/media/reviews/{reviewId}/refund",
  correlationId: "c0ffee",
  issues: null,
  details: { stepUpAction: "moderation.decide", subjectId: REVIEW.id },
  retryAfterS: null,
};

const DECIDED = {
  ok: true,
  data: { review: { ...REVIEW, decision: "blocked", actor: "admin" }, isQueued: true },
};

function renderScreen(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/media/reviews"]}>
        <MediaReviewsScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function signedInAs(role: "admin" | "support"): void {
  useAuthStore.setState({
    account: {
      id: "00000000-0000-4000-8000-00000000000a",
      username: role,
      role,
      lastLoginAt: null,
      mustChangePassword: false,
    },
  });
}

beforeEach(() => {
  getMediaReviews.mockResolvedValue({ ok: true, data: { items: [REVIEW] } });
  postMediaReviewRelease.mockResolvedValue(DECIDED);
  stepUp.mockResolvedValue({
    ok: true,
    data: {
      scope: `moderation.decide:${REVIEW.id}`,
      grantedAt: "2026-09-25T09:00:00Z",
      expiresAt: "2026-09-25T09:05:00Z",
    },
  });
  signedInAs("admin");
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("MediaReviewsScreen", () => {
  it("lists a held job by its codes, never by anything the customer wrote", async () => {
    renderScreen();

    expect(await screen.findByText("violence")).toBeInTheDocument();
    expect(screen.getByText(REVIEW.jobId.slice(0, 8))).toBeInTheDocument();
    expect(screen.getByText(en.media.reviews.source.output_review)).toBeInTheDocument();
    expect(getMediaReviews).toHaveBeenCalledWith("pending", expect.anything());
  });

  it("draws no decision buttons for a role without media.moderate", async () => {
    signedInAs("support");
    renderScreen();

    await screen.findByText("violence");
    expect(
      screen.queryByRole("button", { name: en.media.reviews.release.action }),
    ).not.toBeInTheDocument();
  });

  it("answers a refund's step-up refusal with the prompt, then replays the identical body", async () => {
    const user = userEvent.setup();
    postMediaReviewRefund.mockResolvedValueOnce(STEP_UP_REFUSAL).mockResolvedValueOnce(DECIDED);
    renderScreen();

    await user.click(await screen.findByRole("button", { name: en.media.reviews.refund.action }));
    await user.selectOptions(screen.getByTestId("reason-code"), "abuse_report");
    await user.click(screen.getByRole("button", { name: /^Block 7a1c2e3f$/ }));

    const password = await screen.findByLabelText(/password/i);
    await user.type(password, "the-reviewers-own-password");
    await user.click(screen.getByRole("button", { name: /Re-authenticate|Confirm|Continue/i }));

    await waitFor(() => {
      expect(postMediaReviewRefund).toHaveBeenCalledTimes(2);
    });
    expect(postMediaReviewRefund.mock.calls[1]).toEqual(postMediaReviewRefund.mock.calls[0]);
    expect(postMediaReviewRefund.mock.calls[0]?.[0]).toBe(REVIEW.id);
    expect(stepUp.mock.calls[0]?.[0]).toMatchObject({
      scope: "moderation.decide",
      subjectId: REVIEW.id,
    });
  });

  it("releases with no step-up, once", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(await screen.findByRole("button", { name: en.media.reviews.release.action }));
    await user.selectOptions(screen.getByTestId("reason-code"), "routine_ops");
    await user.click(screen.getByRole("button", { name: /^Release 7a1c2e3f$/ }));

    await waitFor(() => {
      expect(postMediaReviewRelease).toHaveBeenCalledTimes(1);
    });
    expect(postMediaReviewRelease.mock.calls[0]?.[1]).toMatchObject({ reasonCode: "routine_ops" });
    expect(stepUp).not.toHaveBeenCalled();
  });
});
