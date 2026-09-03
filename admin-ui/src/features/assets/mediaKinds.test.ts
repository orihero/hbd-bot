/**
 * The mime decides which reveal exists, and it is matched WHOLE.
 *
 * The server compares the stored string against `frozenset({"audio/mpeg", "audio/ogg"})` and
 * against `LYRIC_TEXT_MIME` verbatim. A client that stripped parameters would offer a Play
 * button for `audio/mpeg; codecs=mp3` that the server then answers 415 to, and a lyric
 * button for a bare `text/plain` it also refuses — a control that cannot work, which is the
 * one thing §11.4 forbids.
 */

import { describe, expect, it } from "vitest";

import { assetMediaKind, LYRIC_TEXT_MIME } from "./mediaKinds";

describe("assetMediaKind", () => {
  it("streams the two audio types the route serves", () => {
    expect(assetMediaKind("audio/mpeg")).toBe("audio");
    expect(assetMediaKind("audio/ogg")).toBe("audio");
  });

  it("reads the lyric sheet only at its full mime, charset included", () => {
    expect(assetMediaKind(LYRIC_TEXT_MIME)).toBe("lyrics");
    expect(assetMediaKind("text/plain")).toBe("none");
  });

  it("matches whole, so a parameterised audio mime gets no control rather than a 415", () => {
    expect(assetMediaKind("audio/mpeg; codecs=mp3")).toBe("none");
  });

  it("answers 'none' for a format neither route serves", () => {
    expect(assetMediaKind("audio/wav")).toBe("none");
    expect(assetMediaKind("application/json")).toBe("none");
  });
});
