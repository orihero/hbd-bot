/**
 * `usePlayerStore` — one of the THREE client stores §11.1 allows.
 *
 * The store exists for one reason: **one `<audio>` element surviving route changes.**
 * `PlayerBar` mounts that element once, at the shell, and every play button anywhere in the
 * app calls `requestPlay()` here. If each `AssetCard` owned its own `<audio>`, navigating
 * from `/orders/:id` to `/users/:id` would cut the song off mid-bar — which, for a console
 * whose job is checking that a delivered song is actually correct, is the one thing it must
 * not do.
 *
 * The store holds STATE, never the element, and it performs no I/O. The element lives in
 * `AudioPlayer` and drives the store through `setPosition` / `setDuration` / `setError`;
 * the authorisation request lives there too, and drives the store through `requireStepUp` /
 * `authorise` / `refuse`. Keeping a DOM node in a Zustand store would make it
 * unserialisable and would let two components fight over `.play()`; keeping the fetch here
 * would put a request in a module that has no way to cancel it on unmount.
 *
 * The `src` is a same-origin path (`/api/assets/{id}/stream`), so the `__Host-` session
 * cookie travels with the media request as a subresource and no token ever appears in a URL
 * (§11.1). Do not put a signed URL here.
 *
 * ## Playing is a reveal, so there is a phase before "playing"
 *
 * §12.3: audio assets are metadata only, "no player until revealed — a greeting says the
 * name aloud, so playing *is* a reveal". The stream route is an `A+S` cell: it wants a
 * step-up scoped to this asset id, it spends a unit of the reveal budget, and it writes an
 * audit row. So a track does not go from "chosen" to "playing"; it goes through
 * `authorising`, and possibly through `step_up`, and can end at `refused` with a reason the
 * operator can act on. `phase` is that progression and `failure` is the reason — see
 * `PlayerPhase` below.
 */

import { create } from "zustand";

import type { AssetKind } from "@/api";

export interface PlayerTrack {
  readonly assetId: string;
  readonly orderId: string | null;
  /** Same-origin path. Never an absolute URL, never a blob, never a signed URL. */
  readonly src: string;
  readonly kind: AssetKind;
  /**
   * What to show in the bar. Our own text — an order reference, a kind, a variant index —
   * and NEVER a recipient name: the player bar persists across routes, so a name shown there
   * outlives the screen the operator opened to see it.
   */
  readonly label: string;
  /** From `AssetWireView.durationS`, so the scrubber has a length before metadata loads. */
  readonly durationS: number | null;
}

/**
 * Where a track is between "an operator pressed play" and "audio is coming out".
 *
 * The two middle states are the whole point. `authorising` is a real request in flight —
 * the one that spends the budget unit and writes the audit row — and showing a play button
 * during it would invite a second one. `step_up` is the server saying "confirm your
 * password for THIS asset", which is a prompt and not an error: nothing has gone wrong, the
 * operator simply has not proved it is still them.
 *
 * `refused` is terminal for this attempt and always carries a `failure`. There is no state
 * that renders a control which does nothing.
 */
export type PlayerPhase =
  /** Nothing loaded. The bar is not on screen. */
  | "idle"
  /** Probing the stream route: step-up, budget and the audit row are being decided. */
  | "authorising"
  /** The route wants a password confirmation scoped to this asset id. */
  | "step_up"
  /** Authorised. The element may load the URL, and only now does it get a `src`. */
  | "playable"
  /** Refused, with a reason in `failure`. */
  | "refused";

/**
 * Why playback is not happening, in a form the UI can turn into one honest sentence.
 *
 * The kinds are the refusals the stream route actually produces, kept separate because the
 * operator's next move differs for every one of them: a `budget` refusal means wait, a
 * `not_found` means the retention sweep or the archive-orphan bug got there first, an
 * `unsupported` means the file is fine and this route will not serve that format, and a
 * `decode` means the bytes arrived and the browser could not play them — which is a
 * different bug report from all four.
 */
export type PlayerFailureKind =
  | "forbidden"
  | "not_found"
  | "unsupported"
  | "empty"
  | "budget"
  | "unavailable"
  | "decode";

export interface PlayerFailure {
  readonly kind: PlayerFailureKind;
  /** One sentence, ours. Safe to render; never a filesystem path and never a name. */
  readonly message: string;
  /** The server's own words, when it had any. Already redacted and capped server-side. */
  readonly detail: string | null;
  /** `X-Correlation-ID`. The string that ties this refusal to a log line. */
  readonly correlationId: string | null;
  /** From `Retry-After`, on a 429 or the limiter's 503. Seconds. */
  readonly retryAfterS: number | null;
}

/**
 * What the probe learned about the stream itself, once it was authorised.
 *
 * `isSeekable` is `false` when the route answered the range probe with a whole-object 200.
 * A scrubber over a non-seekable stream re-downloads from zero on every drag, so the player
 * disables it and says why rather than offering a control that quietly costs four megabytes
 * a nudge.
 */
export interface StreamCapabilities {
  readonly isSeekable: boolean;
  readonly totalBytes: number | null;
  readonly contentType: string | null;
}

export interface PlayerState {
  track: PlayerTrack | null;
  phase: PlayerPhase;
  isPlaying: boolean;
  /** Seconds. Written by the element's `timeupdate`. */
  positionS: number;
  /** Seconds. `null` until the element reports metadata. */
  durationS: number | null;
  /** 0–1. Persisted nowhere: a volume that follows you between browsers is a surprise. */
  volume: number;
  isMuted: boolean;
  /** Why playback is not happening. `null` whenever it is, or whenever it is being decided. */
  failure: PlayerFailure | null;
  /** `null` until the probe answers; `null` again for every new track. */
  capabilities: StreamCapabilities | null;
  /** Set when something wants the element to seek; cleared once it has. */
  pendingSeekS: number | null;

  /**
   * Choose a track and begin authorising it. THE entry point for a play button.
   *
   * It does not start playback: it loads the track, clears every per-track field and moves
   * to `authorising`. `AudioPlayer` owns what happens next.
   */
  requestPlay: (track: PlayerTrack) => void;
  /**
   * Load a track that is ALREADY authorised and start it.
   *
   * The narrow entry point: it skips the probe, so it is right only where the reveal has
   * just happened by other means. Tests use it to reach a playing bar without a fetch.
   */
  play: (track: PlayerTrack) => void;
  /** Re-run the authorisation for the loaded track — after a step-up, or on a retry. */
  retryAuthorisation: () => void;
  /** The route asked for a password confirmation scoped to this asset. */
  requireStepUp: () => void;
  /** The probe succeeded. Playback may begin. */
  authorise: (capabilities: StreamCapabilities) => void;
  /** The route refused, terminally for this attempt. */
  refuse: (failure: PlayerFailure) => void;

  pause: () => void;
  resume: () => void;
  /** Toggle. A no-op unless the loaded track is `playable`. */
  toggle: () => void;
  /** Stop and unload. The bar hides itself when `track` is null. */
  stop: () => void;
  requestSeek: (positionS: number) => void;
  clearPendingSeek: () => void;
  setPosition: (positionS: number) => void;
  setDuration: (durationS: number | null) => void;
  setVolume: (volume: number) => void;
  setMuted: (isMuted: boolean) => void;
  /**
   * The element failed after a successful authorisation — a decode error, a stalled body, a
   * range the browser asked for and did not get. Distinct from every `refuse` reason,
   * because the bytes were authorised and something downstream of that broke.
   */
  setError: (message: string) => void;
}

/** The fields that belong to ONE track and must not leak into the next one. */
const PER_TRACK_RESET = {
  isPlaying: false,
  positionS: 0,
  failure: null,
  capabilities: null,
  pendingSeekS: null,
} as const;

export const usePlayerStore = create<PlayerState>()((set, get) => ({
  track: null,
  phase: "idle",
  isPlaying: false,
  positionS: 0,
  durationS: null,
  volume: 1,
  isMuted: false,
  failure: null,
  capabilities: null,
  pendingSeekS: null,

  requestPlay: (track) =>
    set({ ...PER_TRACK_RESET, track, phase: "authorising", durationS: track.durationS }),

  play: (track) =>
    set({
      ...PER_TRACK_RESET,
      track,
      phase: "playable",
      isPlaying: true,
      durationS: track.durationS,
    }),

  retryAuthorisation: () =>
    set((state) =>
      state.track === null
        ? state
        : { phase: "authorising", failure: null, capabilities: null, isPlaying: false },
    ),

  requireStepUp: () =>
    set((state) =>
      state.track === null ? state : { phase: "step_up", isPlaying: false, failure: null },
    ),

  authorise: (capabilities) =>
    set((state) =>
      state.track === null
        ? state
        : { phase: "playable", isPlaying: true, failure: null, capabilities },
    ),

  refuse: (failure) =>
    set((state) =>
      state.track === null ? state : { phase: "refused", isPlaying: false, failure },
    ),

  pause: () => set({ isPlaying: false }),
  resume: () => set((state) => (state.phase === "playable" ? { isPlaying: true } : state)),
  toggle: () => {
    const { phase, isPlaying } = get();
    if (phase !== "playable") return;
    set({ isPlaying: !isPlaying });
  },
  stop: () =>
    set({
      ...PER_TRACK_RESET,
      track: null,
      phase: "idle",
      durationS: null,
    }),
  requestSeek: (positionS) => set({ pendingSeekS: positionS, positionS }),
  clearPendingSeek: () => set({ pendingSeekS: null }),
  setPosition: (positionS) => set({ positionS }),
  setDuration: (durationS) => set({ durationS }),
  setVolume: (volume) => set({ volume: Math.min(1, Math.max(0, volume)), isMuted: false }),
  setMuted: (isMuted) => set({ isMuted }),
  setError: (message) =>
    set({
      isPlaying: false,
      failure: { kind: "decode", message, detail: null, correlationId: null, retryAfterS: null },
    }),
}));

/** Whether a given asset is the one currently loaded — for a per-row play/pause button. */
export function useIsCurrentTrack(assetId: string): boolean {
  return usePlayerStore((state) => state.track?.assetId === assetId);
}
