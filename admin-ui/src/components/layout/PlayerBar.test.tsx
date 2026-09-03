/**
 * The strip, and the property the strip exists for.
 *
 * Two things are asserted here and nowhere else. The bar is INVISIBLE with no track — an
 * empty 56px band on every screen is the cost of a control nobody has asked for. And the
 * `<audio>` node SURVIVES A ROUTE CHANGE: §11.1 puts the bar outside the `<Outlet />` for
 * exactly that reason, and node identity across a navigation is the only assertion that
 * actually proves it. Everything else about the player — the reveal, the six refusals, the
 * step-up — is `AudioPlayer.test.tsx`.
 */

import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { renderWithProviders } from "@/components/util/testRender";
import { usePlayerStore, type PlayerTrack } from "@/lib/stores";

import { PlayerBar } from "./PlayerBar";

const TRACK: PlayerTrack = {
  assetId: "a1",
  orderId: "0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30",
  src: "/api/assets/a1/stream",
  kind: "song",
  label: "order 0c4f2a1e · song v1",
  durationS: 61,
};

beforeEach(() => {
  usePlayerStore.getState().stop();
});
afterEach(() => {
  usePlayerStore.getState().stop();
});

describe("PlayerBar", () => {
  it("renders nothing with no track — which is every screen until an operator plays one", () => {
    const { container } = renderWithProviders(<PlayerBar />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the track's label, which is OUR text and never a recipient name", () => {
    usePlayerStore.getState().play(TRACK);
    renderWithProviders(<PlayerBar />);
    expect(screen.getByText("order 0c4f2a1e · song v1")).toBeInTheDocument();
  });

  it("streams from a same-origin path, never a signed URL", () => {
    usePlayerStore.getState().play(TRACK);
    const { container } = renderWithProviders(<PlayerBar />);
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    // The `__Host-` session cookie travels as a subresource; no token in the URL (§11.1).
    expect(audio?.getAttribute("src")).toBe("/api/assets/a1/stream");
  });

  it("drives pause and mute through the store, so one element is the only owner", () => {
    usePlayerStore.getState().play(TRACK);
    renderWithProviders(<PlayerBar />);

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(usePlayerStore.getState().isPlaying).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Mute" }));
    expect(usePlayerStore.getState().isMuted).toBe(true);
  });

  it("closing unloads the track and hides the bar", () => {
    usePlayerStore.getState().play(TRACK);
    const { container } = renderWithProviders(<PlayerBar />);
    fireEvent.click(screen.getByRole("button", { name: "Close the player" }));
    expect(usePlayerStore.getState().track).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("requests a seek through the store rather than touching the element directly", () => {
    usePlayerStore.getState().play(TRACK);
    renderWithProviders(<PlayerBar />);
    fireEvent.change(screen.getByRole("slider", { name: "Seek" }), { target: { value: "30" } });
    expect(usePlayerStore.getState().positionS).toBe(30);
  });

  it("surfaces a load failure as operator prose instead of swallowing it", () => {
    usePlayerStore.getState().play(TRACK);
    const { container } = renderWithProviders(<PlayerBar />);
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    if (audio !== null) fireEvent.error(audio);
    expect(screen.getByRole("alert")).toHaveTextContent("this asset could not be loaded");
  });
});

/**
 * §11.1's placement rule, asserted as a property rather than as a DOM position.
 *
 * `AppShell.test.tsx` checks that the bar is not inside `<main>`; that is necessary and it
 * is not sufficient. What an operator actually needs is that navigating away from the screen
 * they pressed play on does not restart the song — and the only way to show that is to keep
 * a reference to the element, navigate, and find the SAME node still there with its state
 * intact. A remount would produce an equal-looking node with `currentTime` back at zero, and
 * every assertion short of identity would pass.
 */
describe("surviving a route change", () => {
  function Harness() {
    return (
      <>
        <Link to="/orders/0c4f2a1e">Open the order</Link>
        <Routes>
          <Route path="/" element={<p>the assets screen</p>} />
          <Route path="/orders/:orderId" element={<p>the order screen</p>} />
        </Routes>
        {/* Outside the routes, exactly as `AppShell` puts it outside the `<Outlet />`. */}
        <PlayerBar />
      </>
    );
  }

  it("keeps the very same <audio> node, still playing, across a navigation", async () => {
    const user = userEvent.setup();
    usePlayerStore.getState().play(TRACK);

    const { container } = renderWithProviders(<Harness />, { route: "/" });
    expect(screen.getByText("the assets screen")).toBeInTheDocument();

    const before = container.querySelector("audio");
    expect(before).not.toBeNull();
    act(() => {
      usePlayerStore.getState().setPosition(37);
    });

    await user.click(screen.getByRole("link", { name: "Open the order" }));
    await waitFor(() => {
      expect(screen.getByText("the order screen")).toBeInTheDocument();
    });

    const after = container.querySelector("audio");
    // Identity, not equality. A remounted element would look identical and would have
    // dropped the song on the floor.
    expect(after).toBe(before);
    expect(usePlayerStore.getState().isPlaying).toBe(true);
    expect(usePlayerStore.getState().positionS).toBe(37);
    expect(screen.getByText("order 0c4f2a1e · song v1")).toBeInTheDocument();
  });

  it("does not remount the element when the operator switches to another take", () => {
    usePlayerStore.getState().play(TRACK);
    const { container } = renderWithProviders(<Harness />, { route: "/" });
    const before = container.querySelector("audio");

    act(() => {
      usePlayerStore.getState().play({ ...TRACK, assetId: "a2", src: "/api/assets/a2/stream" });
    });

    // `PlayerBar` renders `<AudioPlayer>` with no `key`, so a new track REPLACES the source
    // on the one element rather than replacing the element. A key derived from the track
    // would be the same defect as putting the player inside a screen, one level down.
    expect(container.querySelector("audio")).toBe(before);
    expect(before?.getAttribute("src")).toBe("/api/assets/a2/stream");
  });
});
