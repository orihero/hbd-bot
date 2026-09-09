/**
 * Campaign fixtures for the two Broadcasts screens' tests.
 *
 * Built through the REAL schemas' types rather than as loose object literals, so a field the
 * server adds or renames breaks these here — at `npm run typecheck` — rather than as a screen
 * quietly rendering `undefined` under a test that still passes.
 *
 * The numbers are internally consistent on purpose: `settledCount` really is the five terminal
 * counters summed and `unsettledCount` really is `recipientCount - settledCount`, because the
 * delivery panel's whole claim is that these add up the way the server says they do.
 */

import type {
  BroadcastDetailView,
  BroadcastProgressView,
  BroadcastRecipientView,
  BroadcastView,
} from "@/api/broadcasts";

/** A campaign that has gone out to all forty thousand of its frozen audience. */
export const COMPLETED_PROGRESS: BroadcastProgressView = {
  audienceSize: 40_000,
  recipientCount: 40_000,
  isAudienceComplete: true,
  sentCount: 39_500,
  failedCount: 300,
  skippedCount: 150,
  undeliverableCount: 40,
  unknownCount: 10,
  settledCount: 40_000,
  unsettledCount: 0,
};

/** Ready: the ledger is written and not one message has left. */
export const READY_PROGRESS: BroadcastProgressView = {
  audienceSize: 1_284,
  recipientCount: 1_284,
  isAudienceComplete: true,
  sentCount: 0,
  failedCount: 0,
  skippedCount: 0,
  undeliverableCount: 0,
  unknownCount: 0,
  settledCount: 0,
  unsettledCount: 1_284,
};

/** Mid-send, and deliberately mid-chunk: the rollup is what a poll would show. */
export const SENDING_PROGRESS: BroadcastProgressView = {
  audienceSize: 40_000,
  recipientCount: 40_000,
  isAudienceComplete: true,
  sentCount: 12_000,
  failedCount: 4,
  skippedCount: 6,
  undeliverableCount: 0,
  unknownCount: 0,
  settledCount: 12_010,
  unsettledCount: 27_990,
};

export function makeBroadcast(overrides: Partial<BroadcastView> = {}): BroadcastView {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    title: "August outage notice",
    kind: "service",
    state: "completed",
    isTerminal: true,
    segmentHash: "9f2c4a".padEnd(64, "0"),
    audienceEvaluatedAt: "2026-08-01T09:00:00Z",
    scheduledFor: null,
    startedAt: "2026-08-01T09:05:00Z",
    finishedAt: "2026-08-01T10:12:00Z",
    createdAt: "2026-08-01T08:59:00Z",
    updatedAt: "2026-08-01T10:12:00Z",
    createdByAdminId: "22222222-2222-4222-8222-222222222222",
    createdByUsername: "operator",
    scheduledByAdminId: null,
    scheduledByUsername: null,
    reasonCode: "incident",
    reasonRef: null,
    errorCode: null,
    progress: COMPLETED_PROGRESS,
    ...overrides,
  };
}

export function makeDetail(
  broadcast: BroadcastView = makeBroadcast(),
  overrides: Partial<BroadcastDetailView> = {},
): BroadcastDetailView {
  return {
    broadcast,
    bodies: [
      {
        language: "ru",
        text: "Мы уже чиним.",
        renderedText: "Мы уже чиним.",
        renderedLength: 13,
        hasMedia: false,
        mediaStorageKey: null,
        isMediaCached: false,
        buttonLabel: null,
        buttonUrl: null,
      },
    ],
    segment: {
      v: 1,
      match: "all",
      rules: [{ field: "delivered_order_count", op: "gte", value: 3 }],
    },
    isSegmentReadable: true,
    countedProgress: broadcast.progress,
    ...overrides,
  };
}

export function makeRecipient(
  overrides: Partial<BroadcastRecipientView> = {},
): BroadcastRecipientView {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    telegramUserIdMasked: "•••••789",
    isErased: false,
    language: "ru",
    state: "sent",
    attempts: 1,
    errorCode: null,
    settledAt: "2026-08-01T09:06:00Z",
    createdAt: "2026-08-01T09:00:10Z",
    ...overrides,
  };
}
