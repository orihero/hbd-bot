/**
 * The non-rendering half of playback: the copy, the refusal mapping, and the one place an
 * `AssetWireView` becomes a `PlayerTrack`.
 *
 * It lives beside `AudioPlayer` rather than inside it so a play button, a test and the
 * player itself all agree on what a track is called and what a refusal means, and so
 * `AudioPlayer.tsx` exports components only (the `react-refresh` fence).
 */

import type { ApiFailure, AssetWireView } from "@/api";
import { pathAssetStream } from "@/api";
import { humaniseEnum } from "@/lib/format";
import type { PlayerFailure, PlayerTrack } from "@/lib/stores";

/** How far the two nudge buttons move. Long enough to skip an intro, short enough to land
 *  on the syllable an operator is checking. */
export const NUDGE_SECONDS = 10;

/** The two kinds whose artefact IS audio — what the row is for, not what it is stored as. */
const AUDIO_KINDS: readonly AssetWireView["kind"][] = ["song", "greeting"];

/**
 * `services/assets.STREAMABLE_MIMES`, spelled once on this side.
 *
 * **Matched WHOLE, never `split(";")[0]`.** The server compares the stored string against a
 * `frozenset`, so a client that stripped parameters would offer a play button for
 * `audio/mpeg; codecs=mp3` that the server then refuses with a 415 — a control that cannot
 * work, which §11.4 forbids for a format exactly as it forbids it for a role.
 */
export const STREAMABLE_MIMES: readonly string[] = ["audio/mpeg", "audio/ogg"];

/**
 * Whether this row is an audio ARTEFACT. Decides whether playback is a subject the card
 * should say anything about at all — a lyric sheet has no player and needs no sentence
 * explaining that it has no player.
 */
export function isAudioAsset(asset: AssetWireView): boolean {
  return AUDIO_KINDS.includes(asset.kind);
}

/**
 * Whether the stream route would actually serve this row's bytes.
 *
 * Deliberately separate from `isAudioAsset`: `kind` says what the artefact is FOR and the
 * mime says what the route can serve, and a `song` rendered to `audio/wav` is a 415 whatever
 * its kind claims. The card says so instead of offering a button that answers 415.
 */
export function isStreamableAsset(asset: AssetWireView): boolean {
  return STREAMABLE_MIMES.includes(asset.mime);
}

/**
 * How many characters of an order id identify it on screen. The same prefix `OrderRefChip`
 * uses, so the label in the bar and the chip on the screen behind it read as the same order.
 */
const ORDER_REF_CHARS = 8;

/**
 * One asset row as a track.
 *
 * The label is OUR text and never a recipient name: the bar outlives the screen the operator
 * opened it from, so a name shown there follows them to every other screen — including one
 * they are about to screen-share. An order prefix, a kind and a variant index are enough to
 * say which take is playing, and none of them is personal data.
 */
export function assetTrack(asset: AssetWireView): PlayerTrack {
  return {
    assetId: asset.id,
    orderId: asset.orderId,
    src: pathAssetStream(asset.id),
    kind: asset.kind,
    label: `order ${asset.orderId.slice(0, ORDER_REF_CHARS)} · ${humaniseEnum(asset.kind)} #${String(asset.variantIndex)}`,
    durationS: asset.durationS,
  };
}

/** The operator's words, in one place, so a test asserts what shipped and not a paraphrase. */
export const PLAYER_COPY = {
  authorising: "authorising — playing is an audited reveal",
  /** The line under the label while the prompt is up. Short: the prompt says the rest. */
  stepUpLine: "confirm your password to reveal this take",
  /** Handed to `<StepUpPrompt note>` — what the operator was trying to do, in §12.3's terms. */
  stepUpPrompt: "Playing says the recipient's name aloud. Confirm your password to reveal it.",
  retry: "Try again",
  notSeekable: "this server sent the whole object — seeking would re-download it",
  noLength: "this take has no recorded length, so there is nothing to scrub through",
  forbidden:
    "this account cannot play audio: playback is an audited reveal and your role has no cell for it",
  notFound: "there is nothing to play — the asset row, or the object behind it, is not there",
  unsupported:
    "the player serves audio/mpeg and audio/ogg; this asset is stored in another format",
  empty: "the stored object holds no bytes, even though the row claims a duration",
  budget: "the reveal budget is spent — playback is charged in records, not in clicks",
  unavailable: "the stream could not be reached",
  decode: "this asset could not be loaded",
  /** On the card, for a role that holds no reveal cell. §11.4: hide the control, keep the
   *  explanation — an absent button with no reason is its own support call. */
  playbackNotPermitted: "metadata only — playback is a reveal",
  /** On the card, for a role that does. The warning is the point: it is not a preview. */
  playbackIsAReveal: "playing is an audited reveal — it is charged against the record budget",
} as const;

/**
 * The refusal kinds a retry could plausibly clear.
 *
 * `budget` and `unavailable` are time: the hourly ceiling rolls, the counter store comes
 * back. The other four are facts about the row — a role, a missing object, a stored format,
 * an empty file — and a retry against any of them is one more audit row saying the same
 * thing. `forbidden` is absent for the same reason `RETRYABLE_ERROR_CODES` omits it.
 */
const RETRYABLE_KINDS: readonly PlayerFailure["kind"][] = ["budget", "unavailable"];

export function isRetryableFailure(failure: PlayerFailure): boolean {
  return RETRYABLE_KINDS.includes(failure.kind);
}

/**
 * Map one `ApiFailure` from the stream probe onto the player's own vocabulary.
 *
 * `STEP_UP_REQUIRED` is deliberately absent: it is not a failure, it is a prompt, and
 * `AudioPlayer` turns it into a phase before it ever reaches here. Anything unrecognised
 * becomes `unavailable` rather than a guess — including a 500, which is not the operator's
 * to classify, and `SCHEMA_DRIFT`, which cannot arise on a route that returns bytes.
 *
 * The server's own message is kept as `detail` in every case. It is already redacted and
 * capped server-side and never names a filesystem path (§12.1 T4), so it is safe to render
 * verbatim beside ours — ours says what to do, theirs says what happened.
 */
export function toPlayerFailure(failure: ApiFailure): PlayerFailure {
  const base = {
    detail: failure.message,
    correlationId: failure.correlationId,
    retryAfterS: failure.retryAfterS,
  };
  switch (failure.code) {
    case "FORBIDDEN":
      return { ...base, kind: "forbidden", message: PLAYER_COPY.forbidden };
    case "NOT_FOUND":
      return { ...base, kind: "not_found", message: PLAYER_COPY.notFound };
    case "UNSUPPORTED_MEDIA_TYPE":
      return { ...base, kind: "unsupported", message: PLAYER_COPY.unsupported };
    case "RANGE_NOT_SATISFIABLE":
      // The probe asks for byte zero, so "past the end" can only mean there is no byte
      // zero. Saying "that range is past the end" would be true and useless.
      return { ...base, kind: "empty", message: PLAYER_COPY.empty };
    case "REVEAL_BUDGET_EXHAUSTED":
      return { ...base, kind: "budget", message: PLAYER_COPY.budget };
    default:
      return { ...base, kind: "unavailable", message: PLAYER_COPY.unavailable };
  }
}
