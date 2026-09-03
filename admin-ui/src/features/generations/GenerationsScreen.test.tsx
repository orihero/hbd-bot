/**
 * §11.2's dominant signal for `/generations`: "Overall verification rate."
 *
 * The tests that matter here are the two ways the number could be wrong: computed from the
 * page in hand rather than from the whole population, and rendered as `0%` when nothing has
 * been verified at all.
 */

import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ApiResult,
  AttemptWireView,
  AttemptsPage,
  StrategyOutcomeView,
} from "@/api";
import type * as ApiModule from "@/api";
import { renderWithProviders, resetPrefs } from "@/components/util/testRender";

const { getGenerationsMock, getNameStrategiesMock, getAttemptMock } = vi.hoisted(() => ({
  getGenerationsMock: vi.fn(),
  getNameStrategiesMock: vi.fn(),
  getAttemptMock: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getGenerations: getGenerationsMock,
  getNameStrategies: getNameStrategiesMock,
  getAttempt: getAttemptMock,
}));

const { GenerationsScreen } = await import("./GenerationsScreen");

const ATTEMPT_ID = "44444444-4444-4444-8444-444444444444";

function makeAttempt(overrides: Partial<AttemptWireView> = {}): AttemptWireView {
  return {
    id: ATTEMPT_ID,
    orderId: "22222222-2222-4222-8222-222222222222",
    kind: "name_verification",
    sequence: 0,
    attempt: 1,
    provider: "verifier",
    providerRemoteId: null,
    language: "uz_latn",
    isSuccess: true,
    isOrphaned: false,
    nameCandidateStrategy: "canonical",
    nameCandidateRank: 0,
    isNameVerified: true,
    matchConfidence: 0.91,
    nameCandidate: "G•••",
    identityPurgedAt: null,
    sttTranscriptChars: 12,
    textPurgedAt: null,
    errorCode: null,
    errorMessage: null,
    isRetryable: null,
    costUsd: null,
    costSource: null,
    latencyMs: null,
    isInstrumented: false,
    createdAt: "2026-09-01T09:00:00Z",
    ...overrides,
  };
}

function attemptsPage(items: readonly AttemptWireView[]): AttemptsPage {
  return { items: [...items], meta: { nextCursor: null, total: items.length, isTotalExact: true } };
}

function outcome(
  strategy: StrategyOutcomeView["strategy"],
  attempts: number,
  verified: number,
): StrategyOutcomeView {
  return { strategy, attempts, verified, verificationRate: attempts === 0 ? 0 : verified / attempts };
}

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data };
}

beforeEach(() => {
  resetPrefs();
  getGenerationsMock.mockReset();
  getNameStrategiesMock.mockReset();
  getAttemptMock.mockReset();
  getGenerationsMock.mockResolvedValue(ok(attemptsPage([makeAttempt()])));
  getNameStrategiesMock.mockResolvedValue(ok([outcome("canonical", 100, 92)]));
  getAttemptMock.mockResolvedValue(ok(makeAttempt()));
});

describe("GenerationsScreen", () => {
  it("takes the verification rate from the metric, not from the page on screen", async () => {
    // One row on screen, all of it verified; the metric says 92%. The metric wins.
    renderWithProviders(<GenerationsScreen />, { route: "/generations" });

    expect(await screen.findByText("92.0%")).toBeInTheDocument();
    expect(screen.getByText("92/100 candidates verified")).toBeInTheDocument();
  });

  it("renders an em dash, never 0%, when no verification has run", async () => {
    getNameStrategiesMock.mockResolvedValue(ok([]));
    renderWithProviders(<GenerationsScreen />, { route: "/generations" });

    expect(await screen.findByText("no verification has run in this window")).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("keeps `isNameVerified: null` distinct from a failure", async () => {
    getGenerationsMock.mockResolvedValue(
      ok(attemptsPage([makeAttempt({ isNameVerified: null, matchConfidence: null })])),
    );
    renderWithProviders(<GenerationsScreen />, { route: "/generations" });

    expect(await screen.findByText("did not run")).toBeInTheDocument();
    expect(screen.queryByText("no match")).not.toBeInTheDocument();
  });

  /*
   * The reskin turned both outcome columns into tinted pills — the word in `--ink`, the hue
   * in the ground and the glyph. That is a readability win and it is only safe while the
   * glyph survives: ✓ / ✗ / "did not run" are three facts, and none of them may be carried
   * by colour alone (§11.3). jsdom cannot see a colour, so the glyph is the half of the rule
   * a test CAN hold, and this is the test that holds it.
   */
  it("keeps a glyph beside a succeeded outcome and a verified name", async () => {
    renderWithProviders(<GenerationsScreen />, { route: "/generations" });

    // Scoped to the table on purpose: the outcome FILTER offers an option reading
    // "succeeded", it is in the DOM before the query resolves, and an unscoped
    // `findByText` would settle on it and assert nothing about the column.
    const table = await screen.findByRole("table");
    expect((await within(table).findByText("succeeded")).textContent).toContain("✓");
    expect(within(table).getByText("verified").textContent).toContain("✓");
  });

  it("keeps a glyph beside a name that did not match", async () => {
    getGenerationsMock.mockResolvedValue(
      ok(attemptsPage([makeAttempt({ isNameVerified: false, matchConfidence: 0.41 })])),
    );
    renderWithProviders(<GenerationsScreen />, { route: "/generations" });

    const table = await screen.findByRole("table");
    expect((await within(table).findByText("no match")).textContent).toContain("✗");
  });

  it("renders the masked candidate through NameText", async () => {
    renderWithProviders(<GenerationsScreen />, { route: "/generations" });

    const name = await screen.findByTestId("name-text");
    expect(name).toHaveAttribute("lang", "uz-Latn");
    expect(name.textContent).toBe("G•••");
  });

  it("opens the attempt detail from ?attempt= and does not count it as a filter", async () => {
    renderWithProviders(<GenerationsScreen />, {
      route: `/generations?attempt=${ATTEMPT_ID}`,
    });

    const panel = await screen.findByTestId("attempt-detail");
    expect(panel).toHaveAttribute("data-attempt-id", ATTEMPT_ID);
    expect(getAttemptMock).toHaveBeenCalledWith(ATTEMPT_ID, expect.anything());
    // Selection is not a filter: the bar must not claim one.
    await waitFor(() => {
      expect(screen.getByLabelText("filters")).toHaveAttribute("data-active-count", "0");
    });
  });

  it("sends `strategy` as a scalar even though the URL codec parses a list", async () => {
    renderWithProviders(<GenerationsScreen />, { route: "/generations?strategy=ascii" });

    await waitFor(() => {
      expect(getGenerationsMock).toHaveBeenCalled();
    });
    const query = getGenerationsMock.mock.calls
      .map((call) => call[0] as { strategy?: unknown })
      .find((candidate) => candidate.strategy !== undefined);
    expect(query?.strategy).toBe("ascii");
  });

  it("renders cost and latency as “not instrumented”, never as zero", async () => {
    renderWithProviders(<GenerationsScreen />, {
      route: `/generations?attempt=${ATTEMPT_ID}`,
    });

    await screen.findByTestId("attempt-detail");
    expect(screen.getAllByText("not instrumented")).toHaveLength(2);
    expect(screen.queryByText("$0.0000")).not.toBeInTheDocument();
  });
});
