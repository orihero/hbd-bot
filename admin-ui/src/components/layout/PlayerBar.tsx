/**
 * The home of the one `<audio>` element in the application.
 *
 * §11.1: it lives at the shell, **outside the `<Outlet />`**, so playback survives a route
 * change. For a console whose job is checking that a delivered song is actually correct, an
 * `<audio>` per `AssetCard` would cut the song off mid-bar on every navigation — which is
 * precisely the moment an operator wants to look at the order it belongs to.
 *
 * The split with `AudioPlayer` is deliberate and thin. **This file is the strip**: it
 * decides whether the bar is on screen at all, and it is the landmark a screen reader finds.
 * `AudioPlayer` is everything inside it — the element, the transport, the authorisation
 * request and the six ways a stream can refuse. Keeping the strip here is what makes the
 * §11.1 placement rule checkable from `AppShell` without reading a 400-line component.
 *
 * `<AudioPlayer>` is rendered WITHOUT a `key`. That is load-bearing: a key derived from the
 * track would remount it — and therefore replace the `<audio>` node — every time the
 * operator picks a different take, which is the same defect as putting the element inside a
 * screen, one level down. One element, for the life of the shell.
 *
 * The store (`usePlayerStore`) holds state and never the element, which is what stops two
 * components racing over `.play()`.
 *
 * The `src` is always a same-origin path. The `__Host-` session cookie travels with the
 * media request as a subresource and no token ever appears in a URL (§11.1) — do not accept
 * a signed URL here, and do not build a blob.
 */

import { AudioPlayer } from "@/components/domain/AudioPlayer";
import { usePlayerStore } from "@/lib/stores";
import { cn } from "@/lib/utils";

export function PlayerBar() {
  const track = usePlayerStore((state) => state.track);

  // No track, no strip. An empty 56px band on every screen would be the cost of a control
  // nobody has asked for yet.
  if (track === null) return null;

  return (
    /*
     * The strip floats: a card on the page ground with space around it, rather than a slab
     * ruled off from the screen by a 1px line. That is the reskin's rule everywhere — where
     * the old console drew a border, this design uses space and a shadow — and the bar is
     * the one place it also buys something, because a docked element needs to look like it
     * is ON TOP of the scrolling content rather than the last row of it.
     *
     * The landmark stays on the card itself: `AppShell` asserts that `<main>` does not
     * contain it, and `role`/`aria-label` are what a screen reader finds it by.
     */
    <div className="shrink-0 px-gutter pb-4 pt-2">
      <div
        role="region"
        aria-label="Audio player"
        className={cn(
          "flex min-h-14 flex-wrap items-center gap-3 rounded-card bg-surface-card px-4 py-2",
          "shadow-lg",
        )}
      >
        <AudioPlayer track={track} />
      </div>
    </div>
  );
}
