/**
 * `<AssetCard>`, `<RetentionClocks>` and `<StageMiniBar>` — the three components whose
 * correctness is mostly about what they REFUSE to say.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { AdminRole, AssetWireView } from "@/api";
import { meFixture, renderWithProviders } from "@/components/util/testRender";
import { usePlayerStore } from "@/lib/stores";

import { AssetCard, UNRECORDED_STORAGE_KEY_LABEL } from "./AssetCard";
import { makeAsset, makeStagePlan } from "./fixtures";
import { PLAYER_COPY } from "./playback";
import { RetentionClocks } from "./RetentionClocks";
import { StageMiniBar } from "./StageMiniBar";

const NOW = Date.parse("2026-05-01T00:00:00Z");

/**
 * `AssetCard` reads the session now — §12.2's reveal row is `—` for VIEWER, and §11.4 says
 * that means the play button is ABSENT rather than disabled. A role therefore has to be in
 * the cache for the card to decide anything, which is why these render through the harness.
 */
function renderCard(asset: AssetWireView, role: AdminRole = "support") {
  return renderWithProviders(<AssetCard asset={asset} now={NOW} />, { me: meFixture(role) });
}

beforeEach(() => {
  usePlayerStore.getState().stop();
});
afterEach(() => {
  usePlayerStore.getState().stop();
});

describe("AssetCard", () => {
  it("never shows a size — sizeBytes is always 0 and '0 B' would be a lie", () => {
    renderCard(makeAsset());
    const card = screen.getByTestId("asset-card");
    expect(card).not.toHaveTextContent("0 B");
    expect(card).not.toHaveTextContent("size");
    // The only mention of bytes on the card is the durable-orphan warning, which is
    // about the object store outliving the row, not about how large it is.
    expect(card.textContent).not.toContain("0 bytes");
  });

  it("warns that unrecorded storage keys mean the bytes outlive the row", () => {
    renderCard(makeAsset({ isStorageKeyRecorded: false }));
    expect(screen.getByTestId("asset-unrecorded-key")).toHaveTextContent(
      UNRECORDED_STORAGE_KEY_LABEL,
    );
  });

  it("drops that warning when the key IS recorded", () => {
    renderCard(makeAsset({ isStorageKeyRecorded: true }));
    expect(screen.queryByTestId("asset-unrecorded-key")).toBeNull();
  });

  it("offers no <audio> of its own: one element lives at the shell and survives routes", () => {
    const { container } = renderCard(makeAsset({ kind: "greeting" }));
    expect(container.querySelector("audio")).toBeNull();
    expect(screen.getByTestId("asset-playback-note")).toBeInTheDocument();
  });

  it("says nothing about playback for a lyric sheet, which is not audio", () => {
    renderCard(makeAsset({ kind: "lyric_sheet" }));
    expect(screen.queryByTestId("asset-playback-note")).toBeNull();
  });
});

describe("AssetCard playback", () => {
  it("hands the track to the store rather than mounting an element of its own", async () => {
    const user = userEvent.setup();
    renderCard(makeAsset({ kind: "greeting" }));

    await user.click(screen.getByTestId("asset-play"));

    const state = usePlayerStore.getState();
    // `authorising`, never `playable`: playing is a reveal and the reveal has not happened.
    expect(state.phase).toBe("authorising");
    expect(state.isPlaying).toBe(false);
    expect(state.track?.assetId).toBe("a1b2c3d4-1111-2222-3333-444455556666");
    expect(state.track?.src).toBe("/api/assets/a1b2c3d4-1111-2222-3333-444455556666/stream");
  });

  it("never puts a recipient name in the label — the bar outlives the screen", async () => {
    const user = userEvent.setup();
    renderCard(makeAsset({ kind: "greeting" }));
    await user.click(screen.getByTestId("asset-play"));
    expect(usePlayerStore.getState().track?.label).toBe("order 6f1b6c2e · greeting #0");
  });

  it("hides the button from a VIEWER and keeps the sentence that explains why", () => {
    renderCard(makeAsset({ kind: "song" }), "viewer");
    expect(screen.queryByTestId("asset-play")).toBeNull();
    expect(screen.getByTestId("asset-playback-note")).toHaveTextContent(
      PLAYER_COPY.playbackNotPermitted,
    );
  });

  it("warns a role that CAN play what the click costs", () => {
    renderCard(makeAsset({ kind: "song" }), "support");
    expect(screen.getByTestId("asset-playback-note")).toHaveTextContent(
      PLAYER_COPY.playbackIsAReveal,
    );
  });

  it("offers no button for a mime the stream route answers 415 for", () => {
    // `kind` says song; the stored bytes are a format the route will not serve. The mime
    // decides, exactly as it does server-side — a button here would be a guaranteed 415.
    renderCard(makeAsset({ kind: "song", mime: "audio/wav" }));
    expect(screen.queryByTestId("asset-play")).toBeNull();
    expect(screen.getByTestId("asset-playback-note")).toHaveTextContent(PLAYER_COPY.unsupported);
  });

  it("becomes a transport control for the track it already loaded, not a second reveal", async () => {
    const user = userEvent.setup();
    const asset = makeAsset({ kind: "song" });
    renderCard(asset);

    await user.click(screen.getByTestId("asset-play"));
    // Pretend the probe came back: the reveal is done and the stream is authorised.
    act(() => {
      usePlayerStore.getState().authorise({ isSeekable: true, totalBytes: 1024, contentType: null });
    });
    expect(usePlayerStore.getState().isPlaying).toBe(true);

    await user.click(screen.getByRole("button", { name: /^Pause / }));
    const state = usePlayerStore.getState();
    expect(state.isPlaying).toBe(false);
    // Still `playable`. A second `requestPlay` would open a second authorisation for a
    // stream the operator is in the middle of listening to.
    expect(state.phase).toBe("playable");
  });
});

describe("RetentionClocks", () => {
  it("pairs an absolute instant with the time left — never one without the other", () => {
    render(
      <RetentionClocks
        clocks={[{ label: "note", expiresAt: "2026-05-05T00:00:00Z", purgedAt: null }]}
        now={NOW}
      />,
    );
    const row = screen.getByTestId("retention-clock");
    expect(row).toHaveTextContent("2026-05-05 00:00Z");
    expect(row).toHaveTextContent("in 4d");
  });

  it("colours the last seven days amber and a passed expiry red", () => {
    render(
      <RetentionClocks
        clocks={[
          { label: "soon", expiresAt: "2026-05-05T00:00:00Z", purgedAt: null },
          { label: "gone by", expiresAt: "2026-04-20T00:00:00Z", purgedAt: null },
          { label: "later", expiresAt: "2027-05-05T00:00:00Z", purgedAt: null },
        ]}
        now={NOW}
      />,
    );
    const urgencies = screen
      .getAllByTestId("retention-clock")
      .map((node) => node.getAttribute("data-urgency"));
    expect(urgencies).toEqual(["soon", "expired", "later"]);
  });

  it("renders a fired clock as a purge stamp, not as a blank", () => {
    render(
      <RetentionClocks
        clocks={[
          {
            label: "recipient identity",
            expiresAt: "2026-04-01T00:00:00Z",
            purgedAt: "2026-04-02T02:00:00Z",
          },
        ]}
        now={NOW}
      />,
    );
    expect(screen.getByTestId("purged-value").textContent).toBe("🔒 purged 2026-04-02");
  });
});

describe("StageMiniBar", () => {
  it("draws all eleven segments, ghosting the unplanned two", () => {
    render(<StageMiniBar plan={makeStagePlan()} />);
    const segments = screen.getAllByTestId("stage-mini-segment");
    expect(segments).toHaveLength(11);
    expect(segments.filter((node) => node.getAttribute("data-planned") === "false")).toHaveLength(
      2,
    );
  });

  it("names every stage's outcome in its label, because 6px carries no words", () => {
    render(<StageMiniBar plan={makeStagePlan()} />);
    const label = screen.getByTestId("stage-mini-bar").getAttribute("aria-label") ?? "";
    expect(label).toContain("validating: no record");
    expect(label).toContain("rendering greetings: not planned in this deployment");
  });
});
