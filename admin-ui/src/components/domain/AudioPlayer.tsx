/**
 * `<AudioPlayer>` — the one `<audio>` element in the console, and the only thing that talks
 * to it.
 *
 * `PlayerBar` gives it a home at the shell, **outside the `<Outlet />`**, so playback
 * survives a route change (§11.1). This component owns the DOM node and the authorisation
 * request; `usePlayerStore` owns the state and does no I/O. That division is what stops two
 * components racing over `.play()`, and what lets an in-flight probe be cancelled when the
 * operator picks a different take.
 *
 * ## Playing is a reveal, so there is a phase before "playing"
 *
 * §12.3: "no player until revealed — a greeting says the name aloud, so playing *is* a
 * reveal". `GET /api/assets/{id}/stream` is an `A+S` cell: `REVEAL_MEDIA_READ` at the
 * router, a step-up scoped to **this asset id** in the handler, one unit of the reveal
 * budget, and an audit row — all decided before a byte moves. So pressing play does not
 * start audio. It starts `probeAssetStream`, and that request is where the reveal happens.
 *
 * §12.3's audio caveat then does the rest of the work: the route audits the FIRST request
 * per `(actor, asset)` per ten-minute window, not every range request, because an `<audio>`
 * element issues many. **The probe is that first request.** Everything the element then
 * fetches falls inside the window the probe opened. Nothing here tries to compensate for
 * that accounting, deduplicate it, or keep a play count of its own — the server's window is
 * the record, and a second counter on the client would disagree with it within a day.
 *
 * ## Six refusals, six sentences
 *
 * An `<audio>` element collapses every HTTP failure into one opaque `error` event carrying
 * `MEDIA_ERR_SRC_NOT_SUPPORTED`. A player built on that is a dead control with no
 * explanation, which is the outcome §11.4 forbids on every other surface in this console.
 * So the probe asks the question in a form that can be answered, and each answer gets its
 * own sentence and its own next move: confirm your password (403 `STEP_UP_REQUIRED`), your
 * role has no cell (403 `FORBIDDEN`), nothing to play (404), wrong format (415), the object
 * is empty (416 to a probe of byte zero), wait (429 `REVEAL_BUDGET_EXHAUSTED`). A seventh
 * state, `decode`, is the element failing AFTER a successful authorisation — the bytes were
 * released and something downstream of that broke, which is a different bug report from all
 * six.
 *
 * The password form is `<StepUpPrompt>` and not one grown here. It is the console's ONE
 * re-authentication path, it already knows that `subjectId` is compared byte-for-byte (a
 * re-formatted id is a permanent silent 403 that looks exactly like a wrong password), and
 * it already distinguishes a wrong password from a spent re-auth budget. A second credential
 * form in a player bar is how those distinctions get lost.
 *
 * ## Seeking, and why the scrubber can be dead on purpose
 *
 * A 206 to the range probe means seeking is real. A 200 means the server sent the whole
 * object and a drag would re-download it from zero, so the scrubber is disabled and says
 * why — the one case in this console where a disabled control beats an absent one, because
 * the control is the position display as well.
 *
 * Position and duration are rendered as TEXT beside the bar, not only as a bar position:
 * "1m 05s of 3m 12s" is the whole answer to "did it say the name at forty seconds", and a
 * slider thumb is not.
 */

import {
  KeyRound,
  Loader2,
  Lock,
  Pause,
  Play,
  RefreshCw,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useEffect, useRef, type ReactElement } from "react";

import { probeAssetStream } from "@/api";
import { buttonVariants } from "@/components/util";
import { formatDurationS } from "@/lib/format";
import {
  usePlayerStore,
  type PlayerFailure,
  type PlayerPhase,
  type PlayerTrack,
} from "@/lib/stores";
import { cn } from "@/lib/utils";

import { isRetryableFailure, NUDGE_SECONDS, PLAYER_COPY, toPlayerFailure } from "./playback";
import { StepUpPrompt } from "./StepUpPrompt";
import { useRevealCeilings } from "./useReveal";

/*
 * The transport's icon buttons and its one labelled action, both from the shared definition.
 *
 * The transport is `quiet`: a circular target with no ground until hover — the top-bar idiom,
 * and the same variant an unselected segment wears. The "try again" chip is `secondary`; it
 * used to be `--surface-control` under `--ink`, a filled grey capsule, which is the shape the
 * brand language rules out. `disabled:opacity-50` is gone with the rest of them: a dead
 * control loses its ground and keeps a readable `--ink-muted` label instead of being dimmed
 * to roughly 2:1.
 */
const BUTTON_CLASS = cn(
  buttonVariants({ variant: "quiet", size: "icon", shape: "pill" }),
  "h-9 w-9 focus-visible:outline-none focus-visible:ring-1",
);

const CHIP_CLASS = cn(
  buttonVariants({ variant: "secondary" }),
  "focus-visible:outline-none focus-visible:ring-1",
);

const SEEK_NOTE_ID = "player-seek-note";

export interface AudioPlayerProps {
  readonly track: PlayerTrack;
}

export function AudioPlayer({ track }: AudioPlayerProps): ReactElement {
  const phase = usePlayerStore((state) => state.phase);
  const isPlaying = usePlayerStore((state) => state.isPlaying);
  const positionS = usePlayerStore((state) => state.positionS);
  const durationS = usePlayerStore((state) => state.durationS);
  const volume = usePlayerStore((state) => state.volume);
  const isMuted = usePlayerStore((state) => state.isMuted);
  const failure = usePlayerStore((state) => state.failure);
  const capabilities = usePlayerStore((state) => state.capabilities);
  const pendingSeekS = usePlayerStore((state) => state.pendingSeekS);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  // `GET /api/config`, shared with the top bar through one key, and asked for ONLY while the
  // prompt is up: the grace window is a number nobody is looking at until then.
  const { stepUpGraceS } = useRevealCeilings(phase === "step_up");

  /*
   * The reveal. One request per authorisation, cancelled on unmount and on a track change so
   * an operator who clicks two songs quickly does not leave a probe in flight against the
   * first — it would land after the second and refuse a track nobody is looking at.
   *
   * The dependency is `assetId` and not `track`: the object identity changes on every
   * `requestPlay`, and re-running this for the same asset would open a second reveal for one
   * click. The ten-minute window would absorb it, but "the window absorbed it" is not a
   * reason to send it.
   */
  const assetId = track.assetId;
  useEffect(() => {
    if (phase !== "authorising") return;
    const controller = new AbortController();
    void (async () => {
      const result = await probeAssetStream(assetId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (result.ok) {
        usePlayerStore.getState().authorise(result.data);
        return;
      }
      if (result.code === "STEP_UP_REQUIRED") {
        usePlayerStore.getState().requireStepUp();
        return;
      }
      // An abort is this component's own doing, never news for the operator.
      if (result.code === "REQUEST_ABORTED") return;
      usePlayerStore.getState().refuse(toPlayerFailure(result));
    })();
    return () => {
      controller.abort();
    };
  }, [phase, assetId]);

  // Follow the store's play/pause into the element. `play()` rejects when the browser blocks
  // autoplay or the media fails to load; that rejection is the operator's error message, not
  // a console warning.
  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null || phase !== "playable") return;
    const fail = (reason: unknown): void => {
      usePlayerStore
        .getState()
        .setError(reason instanceof Error ? reason.message : "playback was refused");
    };
    // `play()` and `pause()` are unimplemented in jsdom and can throw synchronously in a
    // browser too (a detached element, a blocked autoplay). Neither may take the shell down.
    try {
      if (isPlaying) {
        const started: unknown = audio.play();
        if (started instanceof Promise) started.catch(fail);
        return;
      }
      audio.pause();
    } catch {
      /* A media element that refuses to start is the operator's problem, not a crash. */
    }
  }, [isPlaying, phase, assetId]);

  // Seeks are requested through the store so a scrubber anywhere can drive the one element.
  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null || pendingSeekS === null) return;
    try {
      audio.currentTime = pendingSeekS;
    } catch {
      /* Same reasoning as `play()`: a media element that will not seek is not a crash. */
    }
    usePlayerStore.getState().clearPendingSeek();
  }, [pendingSeekS]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null) return;
    try {
      audio.volume = volume;
      audio.muted = isMuted;
    } catch {
      /* Same reasoning. */
    }
  }, [volume, isMuted]);

  const total = durationS === null || durationS <= 0 ? 0 : durationS;
  const isPlayable = phase === "playable";
  // A seek is real only when the server honoured the range probe, and only when there is a
  // length to seek within. `capabilities` is null on the narrow `play()` entry point, whose
  // caller has vouched for the authorisation already — unknown is not "no".
  const canSeek = isPlayable && total > 0 && (capabilities?.isSeekable ?? true);
  // Why the scrubber is dead, when it is. `null` never coincides with a disabled scrubber:
  // the two reasons below are exhaustive, which is what makes `aria-describedby` honest.
  const seekNote =
    capabilities !== null && !capabilities.isSeekable
      ? PLAYER_COPY.notSeekable
      : total === 0
        ? PLAYER_COPY.noLength
        : null;

  const nudge = (deltaS: number): void => {
    usePlayerStore.getState().requestSeek(Math.min(total, Math.max(0, positionS + deltaS)));
  };

  return (
    <>
      <audio
        ref={audioRef}
        data-testid="audio-element"
        // The URL is handed over ONLY once the reveal is authorised. An element pointed at
        // this route before the step-up lands would fire the 403 at itself and report it as
        // an unsupported source, losing the one thing the operator needs to know.
        {...(isPlayable ? { src: track.src } : {})}
        preload="metadata"
        onTimeUpdate={(event) => {
          usePlayerStore.getState().setPosition(event.currentTarget.currentTime);
        }}
        onLoadedMetadata={(event) => {
          const seconds = event.currentTarget.duration;
          usePlayerStore.getState().setDuration(Number.isFinite(seconds) ? seconds : null);
        }}
        onEnded={() => {
          usePlayerStore.getState().pause();
        }}
        onError={() => {
          usePlayerStore.getState().setError(PLAYER_COPY.decode);
        }}
      />

      {isPlayable ? (
        <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Transport">
          <button
            type="button"
            onClick={() => {
              nudge(-NUDGE_SECONDS);
            }}
            disabled={!canSeek}
            aria-label={`Back ${String(NUDGE_SECONDS)} seconds`}
            className={BUTTON_CLASS}
          >
            <SkipBack aria-hidden="true" className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => {
              usePlayerStore.getState().toggle();
            }}
            aria-label={isPlaying ? "Pause" : "Play"}
            className={BUTTON_CLASS}
          >
            {isPlaying ? (
              <Pause aria-hidden="true" className="h-4 w-4" />
            ) : (
              <Play aria-hidden="true" className="h-4 w-4" />
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              nudge(NUDGE_SECONDS);
            }}
            disabled={!canSeek}
            aria-label={`Forward ${String(NUDGE_SECONDS)} seconds`}
            className={BUTTON_CLASS}
          >
            <SkipForward aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <PhaseGlyph phase={phase} />
      )}

      <div className="min-w-0 flex-1">
        {/* `track.label` is OUR text — an order reference, a kind, a variant index. Never a
            recipient name: the bar outlives the screen the operator opened to see it. */}
        <p className="type-body-sm truncate text-ink">{track.label}</p>

        {isPlayable ? (
          <div className="flex items-center gap-2">
            <span className="type-caption num shrink-0 text-ink-muted" data-testid="player-position">
              {formatDurationS(positionS)}
            </span>
            <input
              type="range"
              min={0}
              max={total}
              step={0.5}
              value={Math.min(positionS, total)}
              disabled={!canSeek}
              onChange={(event) => {
                usePlayerStore.getState().requestSeek(Number(event.target.value));
              }}
              aria-label="Seek"
              // A slider that announces "37" tells a screen-reader operator nothing about a
              // song. The same words the sighted operator reads, in the same order.
              aria-valuetext={`${formatDurationS(positionS)} of ${formatDurationS(durationS)}`}
              aria-describedby={seekNote === null ? undefined : SEEK_NOTE_ID}
              // `accent-brand-fill` paints the native range thumb/track with the brand
              // magenta; `--brand-fill` is the graphic member (4.02:1 light, 3.06:1 dark).
              className="h-1 min-w-0 flex-1 accent-brand-fill"
            />
            <span className="type-caption num shrink-0 text-ink-muted" data-testid="player-duration">
              {formatDurationS(durationS)}
            </span>
          </div>
        ) : (
          <PhaseLine phase={phase} failure={failure} />
        )}

        {isPlayable && seekNote !== null ? (
          <p id={SEEK_NOTE_ID} className="type-caption text-ink-muted" data-testid="player-seek-note">
            {seekNote}
          </p>
        ) : null}
      </div>

      {/* The element can fail AFTER a good authorisation — a decode error, a stalled body.
          That is a different report from a refusal, and it belongs BESIDE the transport
          rather than replacing it: the operator can still close, or press play again. */}
      {isPlayable && failure !== null ? (
        <span role="alert" className="type-body-sm shrink-0" style={{ color: "var(--error)" }}>
          {failure.message}
        </span>
      ) : null}

      {phase === "step_up" ? (
        <StepUpPrompt
          action="reveal"
          // Byte for byte what `authorise_media_reveal` composes its scope from. Reformatting
          // it — braced, upper-cased, trimmed — is a permanent silent 403 that looks exactly
          // like a wrong password.
          subjectId={assetId}
          subjectLabel={track.label}
          graceS={stepUpGraceS}
          note={PLAYER_COPY.stepUpPrompt}
          onGranted={() => {
            // A grant clears the step-up and nothing else: the budget, the mime and the
            // object are all still ahead of it, so the probe runs again rather than the
            // player assuming it may start.
            usePlayerStore.getState().retryAuthorisation();
          }}
          onCancel={() => {
            usePlayerStore.getState().stop();
          }}
          className="w-full"
        />
      ) : null}

      {phase === "refused" && failure !== null && isRetryableFailure(failure) ? (
        <button
          type="button"
          onClick={() => {
            usePlayerStore.getState().retryAuthorisation();
          }}
          className={CHIP_CLASS}
        >
          <RefreshCw aria-hidden="true" className="mr-1 inline h-3 w-3" />
          {PLAYER_COPY.retry}
        </button>
      ) : null}

      {isPlayable ? (
        <button
          type="button"
          onClick={() => {
            usePlayerStore.getState().setMuted(!isMuted);
          }}
          aria-label={isMuted ? "Unmute" : "Mute"}
          className={BUTTON_CLASS}
        >
          {isMuted ? (
            <VolumeX aria-hidden="true" className="h-4 w-4" />
          ) : (
            <Volume2 aria-hidden="true" className="h-4 w-4" />
          )}
        </button>
      ) : null}

      <button
        type="button"
        onClick={() => {
          usePlayerStore.getState().stop();
        }}
        aria-label="Close the player"
        className={BUTTON_CLASS}
      >
        <X aria-hidden="true" className="h-4 w-4" />
      </button>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* What sits where the transport would be                                      */
/* -------------------------------------------------------------------------- */

/**
 * A mark, not a control. The words next to it carry every bit of the meaning, which is what
 * makes `aria-hidden` correct here rather than lazy.
 */
function PhaseGlyph({ phase }: { readonly phase: PlayerPhase }): ReactElement {
  return (
    <span
      className={cn(BUTTON_CLASS, "hover:bg-transparent hover:text-ink-muted")}
      aria-hidden="true"
      data-testid="player-phase-glyph"
      data-phase={phase}
    >
      {phase === "authorising" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {phase === "step_up" ? <KeyRound className="h-4 w-4" /> : null}
      {phase === "refused" || phase === "idle" ? <Lock className="h-4 w-4" /> : null}
    </span>
  );
}

/**
 * The line under the label, when there is no scrubber to draw.
 *
 * `aria-live="polite"` on the two progress states because the operator's focus is on the
 * play button they just pressed and the answer arrives a round trip later; `role="alert"` on
 * a refusal, because a refusal is not progress. The correlation id rides along on anything
 * the server refused, so an operator reporting "it will not play" hands over the string that
 * finds the log line.
 */
function PhaseLine({
  phase,
  failure,
}: {
  readonly phase: PlayerPhase;
  readonly failure: PlayerFailure | null;
}): ReactElement | null {
  if (phase === "authorising" || phase === "step_up") {
    return (
      <p className="type-caption text-ink-muted" aria-live="polite" data-testid="player-status">
        {phase === "authorising" ? PLAYER_COPY.authorising : PLAYER_COPY.stepUpLine}
      </p>
    );
  }
  if (failure === null) return null;
  return (
    <p
      role="alert"
      data-testid="player-status"
      data-failure-kind={failure.kind}
      className="type-caption"
      style={{ color: "var(--error)" }}
    >
      {failure.message}
      {failure.retryAfterS === null
        ? null
        : ` — try again in ${formatDurationS(failure.retryAfterS)}`}
      {failure.detail === null ? null : ` (${failure.detail})`}
      {failure.correlationId === null ? null : ` · ${failure.correlationId}`}
    </p>
  );
}
