/**
 * Wire-shaped fixtures for the domain component tests.
 *
 * Test-only: nothing in `src/` imports this, so it never reaches a bundle. It exists so the
 * tests assert against the FULL response shape — every key present, `null` where the server
 * sends `null` — rather than against a hand-trimmed object that would keep passing after a
 * field the component needs stopped arriving.
 *
 * The names are the real ones the product exists for: `Oʻktam` and `Gʻulom` carry U+02BB
 * MODIFIER LETTER TURNED COMMA, `sanʼat` carries U+02BC MODIFIER LETTER APOSTROPHE, and
 * `Дилноза` is Cyrillic. If an editor or a formatter ever rewrites one of these to an ASCII
 * apostrophe, the NameText tests fail — which is the point.
 */

import type {
  AssetWireView,
  OrderView,
  StagePlanView,
  StageStatusView,
  StrategyOutcomeView,
} from "@/api";
import { PIPELINE_STAGE_VALUES } from "@/api";

/** U+004F U+02BB U+006B U+0074 U+0061 U+006D. */
export const NAME_OKTAM = "Oʻktam";
/** U+0047 U+02BB U+0075 U+006C U+006F U+006D. */
export const NAME_GULOM = "Gʻulom";
/** Cyrillic, no modifier letters at all. */
export const NAME_DILNOZA = "Дилноза";
/** U+02BC MODIFIER LETTER APOSTROPHE — a different codepoint from `Oʻktam`'s. */
export const WORD_SANAT = "sanʼat";

export function makeOrder(overrides: Partial<OrderView> = {}): OrderView {
  return {
    id: "6f1b6c2e-1f3a-4a2b-8c9d-0e1f2a3b4c5d",
    telegramUserId: 123456789,
    telegramUserIdMasked: "•••••789",
    state: "delivered",
    isPaid: true,
    correlationId: "0123456789abcdef0123456789abcdef",
    createdAt: "2026-05-01T09:00:00Z",
    updatedAt: "2026-05-01T09:30:00Z",
    deliveredAt: "2026-05-01T09:30:00Z",
    failedReason: null,
    isFailedReasonRetryable: null,
    isBriefPresent: true,
    recipientName: NAME_OKTAM,
    isIdentityPurged: false,
    identityPurgedAt: null,
    notePurgedAt: null,
    occasion: "birthday",
    genre: "pop",
    outputLanguage: "uz_latn",
    assetCount: 2,
    hasAssets: true,
    // The financials the server has always sent and `orderViewSchema` now declares. A
    // delivered order that was charged and settled is the ordinary case; `retryCount: 0` is
    // the honest default, because today every countable attempt row is a name-verification
    // verdict and a vendor-rendered order records none.
    creditCost: 1,
    ledgerStatus: "settled",
    paymentRail: "credits",
    retryCount: 0,
    ...overrides,
  };
}

/**
 * A stage plan in the SHIPPED shape: eleven stages, nine scheduled, both greeting stages
 * unplanned because `greetings_per_kit=0`.
 */
export function makeStagePlan(overrides: Partial<StagePlanView> = {}): StagePlanView {
  const stages: StageStatusView[] = PIPELINE_STAGE_VALUES.map((stage) => ({
    stage,
    outcome: "not_observed",
    attemptCount: 0,
    failedAttemptCount: 0,
    errorCode: null,
    isRetryable: null,
    isGreetingStage: stage === "rendering_greetings" || stage === "writing_scripts",
  }));
  return {
    stages,
    greetingEvidence: "absent",
    isConclusive: true,
    scheduledStageCount: 9,
    isInferred: true,
    ...overrides,
  };
}

/** The same plan with one stage failed, carrying a code and a retryability. */
export function makeFailedStagePlan(): StagePlanView {
  const plan = makeStagePlan();
  return {
    ...plan,
    stages: plan.stages.map((status) =>
      status.stage === "composing_song"
        ? {
            ...status,
            outcome: "failed",
            attemptCount: 3,
            failedAttemptCount: 3,
            errorCode: "MUSIC_PROVIDER_TIMEOUT",
            isRetryable: true,
          }
        : status,
    ),
  };
}

export function makeAsset(overrides: Partial<AssetWireView> = {}): AssetWireView {
  return {
    id: "a1b2c3d4-1111-2222-3333-444455556666",
    orderId: "6f1b6c2e-1f3a-4a2b-8c9d-0e1f2a3b4c5d",
    kind: "song",
    variantIndex: 0,
    mime: "audio/mpeg",
    // Always 0 on this build — the reason §11.2 does not show storage size.
    sizeBytes: 0,
    durationS: 92.5,
    sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    loudnessLufs: -14.2,
    personaId: null,
    isStorageKeyRecorded: false,
    hasTelegramFileId: true,
    nameCandidateStrategy: "canonical",
    nameCandidateRank: 1,
    retentionClass: "paid_audio",
    expiresAt: "2027-05-01T09:00:00Z",
    createdAt: "2026-05-01T09:29:00Z",
    ...overrides,
  };
}

export function makeStrategyOutcome(
  overrides: Partial<StrategyOutcomeView> = {},
): StrategyOutcomeView {
  return {
    strategy: "canonical",
    attempts: 120,
    verified: 114,
    verificationRate: 0.95,
    ...overrides,
  };
}
