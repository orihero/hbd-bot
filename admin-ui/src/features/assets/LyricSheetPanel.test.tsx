/**
 * The lyric-sheet reveal, and the four ways it refuses.
 *
 * §12.3 puts a lyric sheet in the same class as a greeting's audio: it names the recipient,
 * so reading it IS a reveal. Every test here is about that being true of the CONTROL and
 * not only of the server:
 *
 *  - nothing is fetched until the operator asks, because a mount that revealed would spend
 *    a budget unit and write an audit row for a click nobody made;
 *  - the sheet reaches the DOM as a text node, language-tagged, with U+02BB intact — the
 *    codepoint this whole product exists to get right;
 *  - **Hide** really removes the plaintext, it does not collapse it;
 *  - a `STEP_UP_REQUIRED` refusal becomes a password prompt scoped to THIS asset id, and
 *    confirming it re-runs the reveal that was refused — the refusal is the prompt, because
 *    nothing on this side can know whether a grant exists;
 *  - a role with no media-reveal cell sees no control at all (§11.4: hiding, not disabling).
 *
 * The audio half is not tested here because it is not here: `AssetCard` owns the play
 * button, so `/assets`, order detail and user detail all offer playback identically.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ApiErrorCode,
  ApiFailure,
  ApiResult,
  AssetTextView,
  StepUpRequest,
  StepUpResponse,
} from "@/api";
import type * as ApiModule from "@/api";
import { makeAsset } from "@/components/domain/fixtures";
import { meFixture, renderWithProviders, resetPrefs } from "@/components/util/testRender";

const { getAssetTextMock, postStepUpMock } = vi.hoisted(() => ({
  getAssetTextMock: vi.fn(),
  postStepUpMock: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiModule>()),
  getAssetText: getAssetTextMock,
  postStepUp: postStepUpMock,
}));

const { LyricSheetPanel, NO_REVEAL_CELL_LABEL } = await import("./LyricSheetPanel");

const LYRIC_MIME = "text/plain; charset=utf-8";
/** U+02BB MODIFIER LETTER TURNED COMMA survives the whole round trip — that is the product. */
const SHEET = "Oʻktam, bugun tugʻilgan kuning\nbaxtli boʻlsin";

const lyricAsset = makeAsset({ kind: "lyric_sheet", mime: LYRIC_MIME });

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data };
}

/** The failure arm is FLAT — `{ok: false, code, …}`, not `{ok: false, failure: {…}}`. */
function refusal(code: ApiErrorCode, message: string): ApiFailure {
  return {
    ok: false,
    code,
    message,
    status: code === "STEP_UP_REQUIRED" ? 403 : 429,
    endpoint: "GET /api/assets/{asset_id}/text",
    correlationId: "0123456789abcdef0123456789abcdef",
    details: null,
    issues: null,
    retryAfterS: null,
  };
}

beforeEach(() => {
  resetPrefs();
  getAssetTextMock.mockReset();
  postStepUpMock.mockReset();
});

describe("LyricSheetPanel", () => {
  it("fetches nothing until the operator asks", () => {
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />);
    expect(getAssetTextMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId("lyric-sheet-text")).toBeNull();
  });

  it("renders the sheet unmodified and language-tagged once revealed", async () => {
    const user = userEvent.setup();
    getAssetTextMock.mockResolvedValue(ok<AssetTextView>({ assetId: lyricAsset.id, text: SHEET }));
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />);

    await user.click(screen.getByTestId("lyric-sheet-reveal"));

    const sheet = await screen.findByTestId("lyric-sheet-text");
    expect(sheet.textContent).toBe(SHEET);
    expect(sheet).toHaveAttribute("lang", "uz-Latn");
    expect(sheet).toHaveAttribute("dir", "ltr");
  });

  it("Hide removes the plaintext from the DOM, it does not merely collapse it", async () => {
    const user = userEvent.setup();
    getAssetTextMock.mockResolvedValue(ok<AssetTextView>({ assetId: lyricAsset.id, text: SHEET }));
    const { container } = renderWithProviders(<LyricSheetPanel asset={lyricAsset} />);

    await user.click(screen.getByTestId("lyric-sheet-reveal"));
    await screen.findByTestId("lyric-sheet-text");
    await user.click(screen.getByTestId("lyric-sheet-hide"));

    expect(screen.queryByTestId("lyric-sheet-text")).toBeNull();
    expect(container.textContent ?? "").not.toContain("Oʻktam");
  });

  it("turns a STEP_UP_REQUIRED refusal into a password prompt scoped to this asset", async () => {
    const user = userEvent.setup();
    getAssetTextMock
      .mockResolvedValueOnce(refusal("STEP_UP_REQUIRED", "this reveal needs a confirmation"))
      .mockResolvedValueOnce(ok<AssetTextView>({ assetId: lyricAsset.id, text: SHEET }));
    postStepUpMock.mockResolvedValue(
      ok<StepUpResponse>({
        scope: `reveal:${lyricAsset.id}`,
        grantedAt: "2026-09-02T12:00:00Z",
        expiresAt: "2026-09-02T12:05:00Z",
      }),
    );
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />);

    await user.click(screen.getByTestId("lyric-sheet-reveal"));
    const prompt = await screen.findByTestId("lyric-sheet-step-up");

    await user.type(screen.getByLabelText(/confirm your password/i), "hunter2");
    await user.click(buttonNamed(prompt, "Confirm"));

    await waitFor(() => {
      expect(postStepUpMock).toHaveBeenCalledTimes(1);
    });
    const body = postStepUpMock.mock.calls[0]?.[0] as StepUpRequest | undefined;
    // The ACTION alone, and the asset id as the subject — never a composed pair.
    expect(body?.scope).toBe("reveal");
    expect(body?.subjectId).toBe(lyricAsset.id);

    expect(await screen.findByTestId("lyric-sheet-text")).toHaveTextContent("Oʻktam");
    expect(getAssetTextMock).toHaveBeenCalledTimes(2);
  });

  it("shows an exhausted budget as a refusal with a retry, not as an empty sheet", async () => {
    const user = userEvent.setup();
    getAssetTextMock.mockResolvedValue(
      refusal("REVEAL_BUDGET_EXHAUSTED", "the reveal budget for this hour is spent"),
    );
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />);

    await user.click(screen.getByTestId("lyric-sheet-reveal"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/lyric sheet/i);
    expect(screen.queryByTestId("lyric-sheet-text")).toBeNull();
    expect(screen.queryByTestId("lyric-sheet-step-up")).toBeNull();
  });

  it("says every read is charged, since there is no window here the way there is on playback", () => {
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />);
    expect(screen.getByTestId("lyric-sheet-panel")).toHaveTextContent(
      /charged and audited — there is no ten-minute window/,
    );
  });

  it("renders nothing at all for a row the text route would refuse", () => {
    const { container } = renderWithProviders(
      <LyricSheetPanel asset={makeAsset({ mime: "audio/mpeg" })} />,
    );
    expect(container.querySelector("[data-testid='lyric-sheet-panel']")).toBeNull();
  });

  it("renders nothing for a bare text/plain, which the route matches whole and refuses", () => {
    const { container } = renderWithProviders(
      <LyricSheetPanel asset={makeAsset({ kind: "lyric_sheet", mime: "text/plain" })} />,
    );
    expect(container.querySelector("[data-testid='lyric-sheet-panel']")).toBeNull();
  });

  it("hides the control from a role with no media-reveal cell — hiding, not disabling", () => {
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />, { me: meFixture("viewer") });
    expect(screen.queryByTestId("lyric-sheet-reveal")).toBeNull();
    expect(screen.getByTestId("lyric-sheet-no-cell")).toHaveTextContent(NO_REVEAL_CELL_LABEL);
  });

  it("shows the control to SUPPORT, which does hold the cell", () => {
    renderWithProviders(<LyricSheetPanel asset={lyricAsset} />, { me: meFixture("support") });
    expect(screen.getByTestId("lyric-sheet-reveal")).toBeInTheDocument();
  });
});

/** A button inside one subtree, by its visible label. */
function buttonNamed(root: HTMLElement, name: string): HTMLElement {
  const button = Array.from(root.querySelectorAll("button")).find(
    (node) => (node.textContent ?? "").trim() === name,
  );
  if (button === undefined) throw new Error(`no button named ${name}`);
  return button;
}
