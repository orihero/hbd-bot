/**
 * `/retention` — the four states that must not be collapsed into each other.
 *
 * Every assertion here is about a badge that would otherwise lie: a scheduler that never
 * fired reading as clean, `keys_unrecorded` reading as reconciled, a full batch reading as a
 * finished sweep, and a live backlog reading as something a past run already handled.
 */

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { PurgeRunView, RetentionResponse, SweepCounts } from "@/api";
import {
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { RetentionScreen } from "./RetentionScreen";

const ZERO_COUNTS: SweepCounts = {
  assetsDeleted: 0,
  briefNotesPurged: 0,
  briefIdentitiesPurged: 0,
  attemptIdentitiesPurged: 0,
  attemptTranscriptsPurged: 0,
  nameRecordsDeleted: 0,
  abandonedOrdersDeleted: 0,
  auditReasonsPurged: 0,
  auditRowsDeleted: 0,
  adminSessionsDeleted: 0,
  purgeRunsDeleted: 0,
};

function run(overrides: Partial<PurgeRunView> = {}): PurgeRunView {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    ranAt: "2026-09-02T11:00:00Z",
    trigger: "cron",
    triggeredByUsername: null,
    durationMs: 1_240,
    counts: { ...ZERO_COUNTS, assetsDeleted: 12 },
    totalRowsAffected: 12,
    storage: {
      keysReturned: 12,
      keysDeleted: 0,
      deleteFailures: 0,
      unreconciledKeys: 12,
      reconciliation: "keys_unrecorded",
    },
    batchSize: 500,
    isBatchFull: false,
    errorCode: null,
    ...overrides,
  };
}

function response(overrides: Partial<RetentionResponse> = {}): RetentionResponse {
  return {
    runs: [run()],
    rowsPastExpiry: { ...ZERO_COUNTS, assetsDeleted: 40 },
    totalRowsPastExpiry: 40,
    lastRunAt: "2026-09-02T11:00:00Z",
    hasEverRun: true,
    isBatchFull: false,
    storageReconciliation: "keys_unrecorded",
    ...overrides,
  };
}

function renderScreen(data: RetentionResponse = response()) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.retention.list({ limit: 24 }), data);
  return renderWithProviders(<RetentionScreen />, { client, route: "/retention" });
}

beforeEach(() => {
  resetPrefs();
});

describe("RetentionScreen", () => {
  it("leads with the live backlog and says it is counted live", () => {
    renderScreen();
    const signal = screen.getByTestId("retention-signal");
    expect(within(signal).getByText("rows past expiry")).toBeInTheDocument();
    expect(within(signal).getByText("40")).toBeInTheDocument();
    expect(within(signal).getByText(/counted live/)).toBeInTheDocument();
  });

  it("says a scheduler that never fired never fired", () => {
    renderScreen(
      response({
        runs: [],
        hasEverRun: false,
        lastRunAt: null,
        storageReconciliation: null,
      }),
    );
    expect(screen.getByTestId("retention-never-run")).toHaveTextContent(
      /No sweep has ever run/,
    );
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("does not read a null reconciliation as 'nothing to reconcile'", () => {
    renderScreen(response({ runs: [], hasEverRun: false, storageReconciliation: null }));
    const banner = screen.getByTestId("retention-reconciliation");
    expect(banner).toHaveTextContent("no run has ever happened");
    expect(banner).not.toHaveTextContent("nothing to reconcile");
  });

  it("reads keys_unrecorded as unknown, never as clean", () => {
    renderScreen();
    expect(screen.getByTestId("retention-reconciliation")).toHaveTextContent(
      /unknown, not clean/,
    );
  });

  it("asks for another run when the sweep came back full", () => {
    renderScreen(response({ isBatchFull: true }));
    expect(screen.getByTestId("retention-batch-full")).toHaveTextContent(/Run it again/);
  });

  it("says nothing about a full batch when the sweep finished", () => {
    renderScreen();
    expect(screen.queryByTestId("retention-batch-full")).not.toBeInTheDocument();
  });

  it("lists every clock with what is past it now and what the last run deleted", () => {
    renderScreen();
    // The reskin renders the clocks as cards rather than as table rows. What is under test
    // is unchanged: all eleven clocks are present, and each one still carries BOTH figures —
    // the live count against the database and what the last run actually deleted. Collapsing
    // those two into one number is the misreading this screen exists to prevent.
    const clocks = screen.getByRole("region", { name: "retention clocks" });
    const cards = within(clocks).getAllByRole("listitem");
    expect(cards).toHaveLength(11);
    const assets = within(clocks).getByText("assets").closest("li");
    expect(assets).not.toBeNull();
    expect(assets?.textContent).toContain("40");
    expect(assets?.textContent).toContain("12");
    // Both headings survive the change of shape, because the distinction between them is
    // the point: one is counted live, the other is read off the last run.
    expect(within(clocks).getAllByText("past expiry now").length).toBe(11);
    expect(within(clocks).getAllByText("last run deleted").length).toBe(11);
  });

  it("shows the sweep history with its storage tally", () => {
    renderScreen();
    const sweeps = screen.getByRole("table", { name: "sweeps" });
    expect(within(sweeps).getByText("keys unrecorded")).toBeInTheDocument();
    expect(within(sweeps).getByText(/0\/12 keys · 12 unreconciled/)).toBeInTheDocument();
  });

  it("does not claim a sweep exists when none has run", () => {
    renderScreen(response({ runs: [], hasEverRun: false, lastRunAt: null }));
    expect(screen.getByText("No sweep has ever run")).toBeInTheDocument();
  });
});
