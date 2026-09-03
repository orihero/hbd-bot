import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import {
  SOURCE_UNAVAILABLE_LABEL,
  type AttemptsPage,
  type BriefWireView,
  type OrderDetailView,
  type TimelineView,
} from "@/api";
import { makeFailedStagePlan, makeOrder, makeStagePlan } from "@/components/domain/fixtures";
import {
  configFixture,
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { OrderDetailScreen } from "./OrderDetailScreen";

const ORDER_ID = "6f1b6c2e-1f3a-4a2b-8c9d-0e1f2a3b4c5d";

function briefFixture(): BriefWireView {
  return {
    id: "7a2c3d4e-5555-4666-8777-888899990000",
    occasion: "birthday",
    genre: "pop",
    vocalGender: "female",
    uiLanguage: "uz_latn",
    outputLanguage: "uz_latn",
    eventDay: 14,
    eventMonth: 5,
    recipientName: "Oʻktam",
    recipientScript: "latin",
    recipientLanguage: "uz_latn",
    candidateCount: 3,
    identityExpiresAt: "2026-06-01T00:00:00Z",
    identityPurgedAt: null,
    isIdentityPurged: false,
    noteChars: 180,
    hasApprovedLyrics: true,
    noteExpiresAt: "2026-06-01T00:00:00Z",
    notePurgedAt: null,
    isNotePurged: false,
  };
}

function timelineFixture(): TimelineView {
  return {
    events: [
      {
        at: "2026-05-01T09:00:00Z",
        kind: "order_created",
        source: "order",
        isInferred: false,
        label: null,
        referenceId: null,
      },
      {
        at: "2026-05-01T09:20:00Z",
        kind: "attempt_failed",
        source: "attempts",
        isInferred: true,
        label: "composing_song",
        referenceId: null,
      },
    ],
    availableSources: ["order", "attempts", "assets", "audit"],
    unavailableSources: ["chat", "payments"],
  };
}

function detailFixture(overrides: Partial<OrderDetailView> = {}): OrderDetailView {
  return {
    order: makeOrder({
      id: ORDER_ID,
      state: "failed",
      failedReason: "MUSIC_PROVIDER_TIMEOUT",
      isFailedReasonRetryable: true,
      deliveredAt: null,
    }),
    brief: briefFixture(),
    assets: [],
    attempts: [],
    stagePlan: makeFailedStagePlan(),
    timeline: timelineFixture(),
    ...overrides,
  };
}

function renderDetail(
  detail: OrderDetailView = detailFixture(),
  extra: (client: ReturnType<typeof makeTestQueryClient>) => void = () => undefined,
) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.orders.detail(ORDER_ID), detail);
  client.setQueryData(queryKeys.orders.timeline(ORDER_ID), timelineFixture());
  extra(client);
  return renderWithProviders(
    <Routes>
      <Route path="/orders/:orderId" element={<OrderDetailScreen />} />
    </Routes>,
    { client, route: `/orders/${ORDER_ID}` },
  );
}

describe("OrderDetailScreen", () => {
  beforeEach(() => {
    resetPrefs();
  });

  /* §14, Slice 1d acceptance. */
  it("shows a 9-stage plan, not 11, with the two greeting stages ghosted", () => {
    renderDetail();

    expect(screen.getByTestId("scheduled-stage-count")).toHaveTextContent("9");
    expect(screen.getAllByTestId("pipeline-stage")).toHaveLength(11);

    for (const stage of ["writing_scripts", "rendering_greetings"]) {
      const node = document.querySelector(`[data-stage="${stage}"]`);
      expect(node).toHaveAttribute("data-planned", "false");
    }
  });

  it("highlights the failed stage with its error code and retryability", () => {
    renderDetail();

    const failed = document.querySelector('[data-stage="composing_song"]');
    expect(failed).toHaveAttribute("data-outcome", "failed");
    expect(failed).toHaveTextContent("MUSIC_PROVIDER_TIMEOUT");
    // `↻` retryable vs `■` terminal — the operator's real decision, one glyph away.
    expect(failed).toHaveTextContent("↻");
  });

  it("renders unknown retryability as unknown, never as terminal", () => {
    const plan = makeStagePlan();
    renderDetail(
      detailFixture({
        stagePlan: {
          ...plan,
          stages: plan.stages.map((status) =>
            status.stage === "composing_song"
              ? {
                  ...status,
                  outcome: "failed" as const,
                  attemptCount: 1,
                  failedAttemptCount: 1,
                  errorCode: "SOMETHING_NEW",
                  isRetryable: null,
                }
              : status,
          ),
        },
      }),
    );
    const failed = document.querySelector('[data-stage="composing_song"]');
    expect(failed).toHaveTextContent("unknown");
    expect(failed).not.toHaveTextContent("terminal");
  });

  /* §14: chat and payments read "not enabled in this deployment"; stateTransitions is
     labelled "inferred". */
  it("renders the sources legend so an absent section is not read as silence", () => {
    renderDetail();

    for (const source of ["chat", "payments"]) {
      const row = document.querySelector(`[data-source="${source}"]`);
      expect(row).toHaveAttribute("data-standing", "unavailable");
      expect(row).toHaveTextContent(SOURCE_UNAVAILABLE_LABEL);
    }

    const transitions = document.querySelector('[data-source="state_transitions"]');
    expect(transitions).toHaveAttribute("data-standing", "inferred");
    expect(transitions).toHaveTextContent("inferred");
  });

  it("keeps the legend beside the pipeline, not behind a tab", () => {
    renderDetail();
    // Visible on arrival, with the timeline tab merely the default panel.
    expect(screen.getByTestId("timeline-source-legend")).toBeInTheDocument();
    expect(screen.getAllByTestId("timeline-event")).toHaveLength(2);
  });

  it("marks a derived timeline row as inferred", () => {
    renderDetail();
    const rows = screen.getAllByTestId("timeline-event");
    expect(rows[1]).toHaveTextContent("inferred");
  });

  it("renders a purged recipient as a lock, never as a blank", () => {
    renderDetail(
      detailFixture({
        order: makeOrder({
          id: ORDER_ID,
          recipientName: null,
          isIdentityPurged: true,
          identityPurgedAt: "2026-05-14T03:00:00Z",
        }),
      }),
    );
    expect(screen.getAllByTestId("purged-value")[0]).toHaveTextContent("🔒 purged 2026-05-14");
  });

  it("reads attempts off the sub-collection endpoint when that tab is opened", () => {
    const attemptsPage: AttemptsPage = {
      items: [
        {
          id: "9a9a9a9a-1111-4111-8111-999999999999",
          orderId: ORDER_ID,
          kind: "song",
          sequence: 1,
          attempt: 2,
          provider: "suno",
          providerRemoteId: null,
          language: "uz_latn",
          isSuccess: false,
          isOrphaned: false,
          nameCandidateStrategy: null,
          nameCandidateRank: null,
          isNameVerified: null,
          matchConfidence: null,
          nameCandidate: null,
          identityPurgedAt: null,
          sttTranscriptChars: null,
          textPurgedAt: null,
          errorCode: "MUSIC_PROVIDER_TIMEOUT",
          errorMessage: "provider did not answer",
          isRetryable: true,
          costUsd: null,
          costSource: null,
          latencyMs: null,
          isInstrumented: false,
          createdAt: "2026-05-01T09:20:00Z",
        },
      ],
      meta: { nextCursor: null, total: null, isTotalExact: null },
    };

    renderDetail(detailFixture(), (client) => {
      client.setQueryData(
        queryKeys.orders.attempts(ORDER_ID, { limit: 50, cursor: undefined }),
        attemptsPage,
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: "attempts" }));

    const table = screen.getByRole("table", { name: "generation attempts" });
    expect(table).toHaveTextContent("MUSIC_PROVIDER_TIMEOUT");
    // `null` cost and latency are "not instrumented", never $0.00 / 0 ms.
    expect(table).toHaveTextContent("not instrumented");
    expect(table).not.toHaveTextContent("$0.00");
  });

  it("does not fetch a tab nobody opened", () => {
    const { client } = renderDetail();
    // The observer exists (the hook is mounted) but `enabled` kept it from ever fetching.
    const state = client.getQueryState(
      queryKeys.orders.assets(ORDER_ID, { limit: 50, cursor: undefined }),
    );
    expect(state?.fetchStatus).toBe("idle");
    expect(state?.data).toBeUndefined();
    expect(state?.dataUpdatedAt).toBe(0);
  });
});

/**
 * The reveal affordance, Phase 2.
 *
 * §12.3 masks the recipient name and hides the note at every role, including OWNER, and
 * `POST /api/reveal` is the one path out of that. What is asserted here is the WIRING —
 * that both record shapes are offered as two separate controls, that they carry this order's
 * id as the subject, and that a VIEWER sees neither. The dialog's own behaviour is pinned in
 * `components/domain/RevealDialog.test.tsx`.
 */
describe("OrderDetailScreen — the reveal", () => {
  beforeEach(() => {
    resetPrefs();
  });

  function renderAs(role: Parameters<typeof meFixture>[0]) {
    const client = makeTestQueryClient();
    client.setQueryData(queryKeys.orders.detail(ORDER_ID), detailFixture());
    client.setQueryData(queryKeys.orders.timeline(ORDER_ID), timelineFixture());
    return renderWithProviders(
      <Routes>
        <Route path="/orders/:orderId" element={<OrderDetailScreen />} />
      </Routes>,
      // The ceilings come from `/api/config`, which the top bar has already cached in a live
      // session. Seeded here so opening the dialog is not a network call.
      { client, route: `/orders/${ORDER_ID}`, me: meFixture(role), config: configFixture() },
    );
  }

  it("offers the brief and the attempt free text SEPARATELY — the shapes cannot be mixed", () => {
    renderAs("support");
    expect(screen.getByRole("button", { name: /Reveal the brief/u })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Reveal attempt free text/u }),
    ).toBeInTheDocument();
  });

  it("opens on this order, and prices the brief at one record before anything is sent", () => {
    renderAs("support");
    fireEvent.click(screen.getByRole("button", { name: /Reveal the brief/u }));

    expect(screen.getByTestId("reveal-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-cost").textContent).toContain("charged 1 record");
    // The dialog's subject is the order, and its label is OUR reference — never the name it
    // exists to unmask.
    expect(screen.getByTestId("reveal-dialog").textContent).toContain(ORDER_ID.slice(0, 8));
    expect(screen.getByTestId("reveal-dialog").textContent).not.toContain("Oʻktam");
  });

  it("is invisible to a VIEWER — §11.4 hides, it does not grey out", () => {
    renderAs("viewer");
    expect(screen.queryByTestId("reveal-button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reveal/u })).not.toBeInTheDocument();
  });
});
