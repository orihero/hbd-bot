/**
 * Which reveal an asset row can be asked for — decided from its `mime`, exactly the way the
 * server decides it.
 *
 * `GET /api/assets/{id}/stream` serves `audio/mpeg` and `audio/ogg` and answers 415 for
 * everything else. `GET /api/assets/{id}/text` serves `text/plain; charset=utf-8` — the
 * lyric sheet rendered out of `assets.payload` — and answers 415 for everything else. There
 * is no third media route, so a row that is neither gets no reveal control at all rather
 * than a button that produces a 415 (§11.4: a control nobody can explain is worse than an
 * absent one).
 *
 * **The mime is matched WHOLE**, never `split(";")[0]`. `services/assets.py` compares the
 * stored string against a `frozenset` and against `LYRIC_TEXT_MIME` verbatim; a client that
 * strips parameters would offer a Play button for `audio/mpeg; codecs=mp3` that the server
 * then refuses, and would offer a lyric button for a bare `text/plain` it also refuses. The
 * two sides must disagree about nothing.
 *
 * `kind` is deliberately NOT what decides this. `AssetKind` is `song`/`greeting`/`cover`/
 * `lyric_sheet` and describes what the artefact is FOR; the mime is what the route can
 * actually serve, and a `song` row whose mime is `audio/wav` is a 415 whatever its kind
 * says. (`components/domain/playback.ts` branches on the KIND for the play button; the two
 * agree on every row this pipeline writes, and disagree only for a stored format the stream
 * route would refuse — where the player's own 415 handling takes over.)
 */

/** Matched whole. The server's `STREAMABLE_MIMES`, spelled once on this side. */
export const STREAMABLE_MIMES: readonly string[] = ["audio/mpeg", "audio/ogg"];

/** Matched whole, parameter included. The server's `LYRIC_TEXT_MIME`. */
export const LYRIC_TEXT_MIME = "text/plain; charset=utf-8";

/** What, if anything, this row can be revealed as. */
export type AssetMediaKind = "audio" | "lyrics" | "none";

export function assetMediaKind(mime: string): AssetMediaKind {
  if (STREAMABLE_MIMES.includes(mime)) return "audio";
  if (mime === LYRIC_TEXT_MIME) return "lyrics";
  return "none";
}
