/**
 * `<AudioPlayer>` — the reveal, the six refusals, and the transport.
 *
 * The suite is organised around the one claim that matters: **a silent dead player is the
 * worst outcome.** Every HTTP answer the stream route can give is exercised here, and every
 * one of them has to produce a different sentence and a different next move. If a future
 * change collapses two of them into "cannot play", one of these fails.
 *
 * The player is rendered through `PlayerBar`, not directly, because the strip is what
 * decides whether there is a player at all and the two are only meaningful together.
 */

import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configFixture, renderWithProviders } from "@/components/util/testRender";
import { PlayerBar } from "@/components/layout";
import { usePlayerStore, type PlayerTrack } from "@/lib/stores";

import { PLAYER_COPY, toPlayerFailure } from "./playback";

const ASSET_ID = "a1b2c3d4-1111-2222-3333-444455556666";

const TRACK: PlayerTrack = {
  assetId: ASSET_ID,
  orderId: "0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30",
  src: `/api/assets/${ASSET_ID}/stream`,
  kind: "greeting",
  label: "order 0c4f2a1e · greeting #0",
  durationS: 61,
};

/* -------------------------------------------------------------------------- */
/* Canned server answers                                                       */
/* -------------------------------------------------------------------------- */

function audioResponse(status = 206, headers: Record<string, string> = {}): Response {
  return new Response("x", {
    status,
    headers: {
      "content-type": "audio/mpeg",
      ...(status === 206 ? { "content-range": "bytes 0-0/4194304" } : {}),
      ...headers,
    },
  });
}

function envelope(
  status: number,
  code: string,
  message: string,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify({ error: { code, message, correlationId: "corr-7" } }), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

/** What `POST /api/auth/step-up` will answer, when a test gets that far. */
let stepUpAnswer: Response | null = null;

/**
 * A tiny server, routed by URL rather than by call order.
 *
 * By URL on purpose: the shared `<StepUpPrompt>` reads `adminStepUpGraceSeconds` from
 * `GET /api/config` when it mounts, so a queue keyed on call ORDER would hand the config
 * request the step-up's answer and fail in a way that reads like a bug in the player.
 *
 * `/stream` answers `first`, then each of `rest`, then repeats the last one.
 */
function serve(first: Response, ...rest: Response[]): ReturnType<typeof vi.fn> {
  const queue = [first, ...rest];
  const fetchMock = vi.fn((url: string) => {
    if (url.startsWith("/api/auth/step-up")) {
      return Promise.resolve(stepUpAnswer ?? envelope(500, "INTERNAL_ERROR", "no canned step-up"));
    }
    if (url.startsWith("/api/config")) return Promise.resolve(json(configFixture()));
    return Promise.resolve(queue.length > 1 ? queue.shift()! : queue[0]!);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Every request the player made for BYTES — the ones §12.3 counts. */
function streamCalls(fetchMock: ReturnType<typeof vi.fn>): unknown[][] {
  return fetchMock.mock.calls.filter((call) => String(call[0]).includes("/stream"));
}

function callTo(fetchMock: ReturnType<typeof vi.fn>, path: string): unknown[] | undefined {
  return fetchMock.mock.calls.find((call) => String(call[0]) === path);
}

/** Mount the bar with `TRACK` chosen and the reveal in flight, then let the probe land. */
async function playAndSettle(): Promise<void> {
  act(() => {
    usePlayerStore.getState().requestPlay(TRACK);
  });
  renderWithProviders(<PlayerBar />);
  await waitFor(() => {
    expect(usePlayerStore.getState().phase).not.toBe("authorising");
  });
}

beforeEach(() => {
  stepUpAnswer = null;
  usePlayerStore.getState().stop();
});
afterEach(() => {
  usePlayerStore.getState().stop();
});

/* -------------------------------------------------------------------------- */

describe("the reveal that has to happen before a byte moves", () => {
  it("does not give the element a src until the stream is authorised", () => {
    // A never-resolving probe: this is the state an operator sees for one round trip.
    vi.stubGlobal(
      "fetch",
      vi.fn((): Promise<Response> => new Promise<Response>(() => undefined)),
    );
    act(() => {
      usePlayerStore.getState().requestPlay(TRACK);
    });
    const { container } = renderWithProviders(<PlayerBar />);

    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    // An element pointed at the route before the step-up lands would fire the 403 at itself
    // and report it as an unsupported source — losing the only useful fact.
    expect(audio?.hasAttribute("src")).toBe(false);
    expect(screen.getByTestId("player-status")).toHaveTextContent(PLAYER_COPY.authorising);
    // And no transport: a play button during authorisation invites a second reveal.
    expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
  });

  it("hands the element the same-origin URL once the route says yes, and starts", async () => {
    serve(audioResponse());
    await playAndSettle();

    const audio = document.querySelector("audio");
    expect(audio?.getAttribute("src")).toBe(`/api/assets/${ASSET_ID}/stream`);
    // No token, no signed URL: the `__Host-` cookie travels as a subresource (§11.1).
    expect(audio?.getAttribute("src")).not.toContain("?");
    expect(usePlayerStore.getState().isPlaying).toBe(true);
  });

  it("sends ONE request per click, because that request is the audit row", async () => {
    const fetchMock = serve(audioResponse());
    await playAndSettle();

    // §12.3's audio caveat: the route audits the FIRST request per (actor, asset) per
    // ten-minute window. The probe is that request. A second probe for one click would be a
    // second budget unit the window happens to absorb — which is not a reason to send it.
    expect(streamCalls(fetchMock)).toHaveLength(1);
  });

  it("cancels an in-flight reveal when the operator picks another take", () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit): Promise<Response> => {
        if (init.signal) signals.push(init.signal);
        return new Promise<Response>(() => undefined);
      }),
    );
    act(() => {
      usePlayerStore.getState().requestPlay(TRACK);
    });
    renderWithProviders(<PlayerBar />);

    act(() => {
      usePlayerStore.getState().requestPlay({ ...TRACK, assetId: "b2", src: "/api/assets/b2/stream" });
    });

    // The first probe would otherwise land after the second and refuse a track nobody is
    // looking at.
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);
  });
});

describe("the six refusals, each with its own sentence", () => {
  it("turns STEP_UP_REQUIRED into a prompt rather than an error", async () => {
    serve(envelope(403, "STEP_UP_REQUIRED", "this action needs a fresh step-up"));
    await playAndSettle();

    expect(usePlayerStore.getState().phase).toBe("step_up");
    expect(screen.getByTestId("player-status")).toHaveTextContent(PLAYER_COPY.stepUpLine);
    // The reason, in §12.3's terms, sits in the prompt rather than being said twice.
    expect(screen.getByTestId("step-up-prompt")).toHaveTextContent(PLAYER_COPY.stepUpPrompt);
    // The console's ONE re-authentication form, not a second one grown in the player.
    const prompt = screen.getByTestId("step-up-prompt");
    expect(prompt).toHaveAttribute("data-step-up-action", "reveal");
    expect(prompt).toHaveAttribute("data-step-up-subject", ASSET_ID);
    expect(screen.getByLabelText("Your password")).toBeInTheDocument();
    // Not an error: nothing has gone wrong and there is nothing to retry.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("turns a plain FORBIDDEN into a wall, with no retry to click", async () => {
    serve(envelope(403, "FORBIDDEN", "your role has no cell for that"));
    await playAndSettle();

    const status = screen.getByTestId("player-status");
    expect(status).toHaveAttribute("data-failure-kind", "forbidden");
    expect(status).toHaveTextContent(PLAYER_COPY.forbidden);
    // A role does not change while a bar is open, and a retry would write a second
    // `permission.denied` row saying the same thing.
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
  });

  it("says the object is missing on a 404, and never a filesystem path", async () => {
    serve(envelope(404, "NOT_FOUND", "no asset with id 1234"));
    await playAndSettle();

    const status = screen.getByTestId("player-status");
    expect(status).toHaveAttribute("data-failure-kind", "not_found");
    expect(status).toHaveTextContent(PLAYER_COPY.notFound);
    expect(status.textContent).toContain("corr-7");
  });

  it("says the FORMAT is wrong on a 415, which is not the same as missing", async () => {
    serve(envelope(415, "UNSUPPORTED_MEDIA_TYPE", "this asset is audio/wav; this route serves audio only"));
    await playAndSettle();

    const status = screen.getByTestId("player-status");
    expect(status).toHaveAttribute("data-failure-kind", "unsupported");
    expect(status).toHaveTextContent(PLAYER_COPY.unsupported);
    // An operator told "not found" here would go looking for a retention bug.
    expect(status.textContent).not.toContain(PLAYER_COPY.notFound);
  });

  it("reads a 416 to a probe of byte zero as an EMPTY object", async () => {
    serve(
      envelope(416, "RANGE_NOT_SATISFIABLE", "that byte range is past the end of this object", {
        "content-range": "bytes */0",
      }),
    );
    await playAndSettle();

    const status = screen.getByTestId("player-status");
    expect(status).toHaveAttribute("data-failure-kind", "empty");
    expect(status).toHaveTextContent(PLAYER_COPY.empty);
  });

  it("says how long to wait on a 429 and offers the retry", async () => {
    serve(
      envelope(429, "REVEAL_BUDGET_EXHAUSTED", "the reveal budget is spent", {
        "retry-after": "300",
      }),
    );
    await playAndSettle();

    const status = screen.getByTestId("player-status");
    expect(status).toHaveAttribute("data-failure-kind", "budget");
    expect(status).toHaveTextContent(PLAYER_COPY.budget);
    expect(status).toHaveTextContent("try again in 5m 00s");
    expect(screen.getByRole("button", { name: /Try again/ })).toBeInTheDocument();
  });

  it("says the stream is unreachable when there is no network, and offers the retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    await playAndSettle();

    const status = screen.getByTestId("player-status");
    expect(status).toHaveAttribute("data-failure-kind", "unavailable");
    expect(screen.getByRole("button", { name: /Try again/ })).toBeInTheDocument();
  });

  it("distinguishes a decode failure from a refusal — the bytes WERE released", async () => {
    serve(audioResponse());
    await playAndSettle();

    const audio = document.querySelector("audio");
    expect(audio).not.toBeNull();
    if (audio !== null) fireEvent.error(audio);

    expect(screen.getByRole("alert")).toHaveTextContent(PLAYER_COPY.decode);
    // The transport survives: the operator can still press play again, or close.
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(usePlayerStore.getState().failure?.kind).toBe("decode");
  });

  it("maps nothing it does not recognise onto a guess", () => {
    const guessed = toPlayerFailure({
      ok: false,
      code: "INTERNAL_ERROR",
      message: "something broke",
      status: 500,
      correlationId: null,
      endpoint: "GET /api/assets/{asset_id}/stream",
      details: null,
      issues: null,
      retryAfterS: null,
    });
    expect(guessed.kind).toBe("unavailable");
    expect(guessed.detail).toBe("something broke");
  });
});

describe("the step-up, inline in the bar", () => {
  it("asks for a grant scoped to THIS asset and replays the reveal on success", async () => {
    const user = userEvent.setup();
    stepUpAnswer = json({
      scope: `reveal:${ASSET_ID}`,
      grantedAt: "2026-09-01T10:00:00Z",
      expiresAt: "2026-09-01T10:05:00Z",
    });
    const fetchMock = serve(
      envelope(403, "STEP_UP_REQUIRED", "this action needs a fresh step-up"),
      audioResponse(),
    );
    await playAndSettle();

    await user.type(screen.getByLabelText("Your password"), "hunter2hunter2");
    await user.click(screen.getByRole("button", { name: "Re-authenticate" }));

    await waitFor(() => {
      expect(usePlayerStore.getState().phase).toBe("playable");
    });

    const stepUpCall = callTo(fetchMock, "/api/auth/step-up");
    expect(stepUpCall).toBeDefined();
    const sent: unknown = (stepUpCall?.[1] as RequestInit | undefined)?.body;
    const body = JSON.parse(typeof sent === "string" ? sent : "{}") as Record<string, unknown>;
    // The bare ACTION and the asset id as `str(uuid)` — byte for byte what
    // `authorise_media_reveal` composes its scope from. A grant for another asset is no use.
    expect(body["scope"]).toBe("reveal");
    expect(body["subjectId"]).toBe(ASSET_ID);
    // Two reveals: the one that was refused, and the one the grant let through. Not three —
    // a grant authorises the action, it does not replay the request by itself.
    expect(streamCalls(fetchMock)).toHaveLength(2);
  });

  it("shows the server's own words when the password is wrong, and stays on the prompt", async () => {
    const user = userEvent.setup();
    stepUpAnswer = envelope(403, "FORBIDDEN", "that password does not match");
    serve(envelope(403, "STEP_UP_REQUIRED", "this action needs a fresh step-up"));
    await playAndSettle();

    await user.type(screen.getByLabelText("Your password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Re-authenticate" }));

    await waitFor(() => {
      expect(screen.getByTestId("step-up-error")).toHaveTextContent("that password does not match");
    });
    // A wrong password, a spent re-auth budget and an ended session are three different
    // remedies, and the server distinguishes all three. We do not paraphrase them into one.
    expect(usePlayerStore.getState().phase).toBe("step_up");
  });

  it("will not submit an empty password, so a stray Enter costs no re-auth budget", async () => {
    serve(envelope(403, "STEP_UP_REQUIRED", "this action needs a fresh step-up"));
    await playAndSettle();
    expect(screen.getByRole("button", { name: "Re-authenticate" })).toBeDisabled();
  });
});

describe("the transport", () => {
  it("shows current and total position as TEXT, not only as a bar position", async () => {
    serve(audioResponse());
    await playAndSettle();
    act(() => {
      usePlayerStore.getState().setPosition(65);
    });

    expect(screen.getByTestId("player-position")).toHaveTextContent("1m 05s");
    expect(screen.getByTestId("player-duration")).toHaveTextContent("1m 01s");
    expect(screen.getByRole("slider", { name: "Seek" })).toHaveAttribute(
      "aria-valuetext",
      "1m 05s of 1m 01s",
    );
  });

  it("gives every control an accessible name and reaches them all from the keyboard", async () => {
    serve(audioResponse());
    await playAndSettle();

    for (const name of [
      "Back 10 seconds",
      "Pause",
      "Forward 10 seconds",
      "Mute",
      "Close the player",
    ]) {
      const control = screen.getByRole("button", { name });
      expect(control).toBeInTheDocument();
      // A native <button> is in the tab order; an ARIA-labelled <div> would not be, and
      // that is the mistake this asserts against.
      expect(control.tagName).toBe("BUTTON");
    }
    expect(screen.getByRole("slider", { name: "Seek" })).toBeInTheDocument();
  });

  it("nudges through the store, so the one element stays the only owner", async () => {
    const user = userEvent.setup();
    serve(audioResponse());
    await playAndSettle();
    act(() => {
      usePlayerStore.getState().setPosition(30);
    });

    await user.click(screen.getByRole("button", { name: "Forward 10 seconds" }));
    expect(usePlayerStore.getState().positionS).toBe(40);

    await user.click(screen.getByRole("button", { name: "Back 10 seconds" }));
    expect(usePlayerStore.getState().positionS).toBe(30);
  });

  it("clamps a nudge to the track rather than seeking past either end", async () => {
    const user = userEvent.setup();
    serve(audioResponse());
    await playAndSettle();

    await user.click(screen.getByRole("button", { name: "Back 10 seconds" }));
    expect(usePlayerStore.getState().positionS).toBe(0);

    act(() => {
      usePlayerStore.getState().setPosition(58);
    });
    await user.click(screen.getByRole("button", { name: "Forward 10 seconds" }));
    expect(usePlayerStore.getState().positionS).toBe(61);
  });

  it("disables the scrubber and SAYS WHY when the server sent the whole object", async () => {
    serve(audioResponse(200));
    await playAndSettle();

    const slider = screen.getByRole("slider", { name: "Seek" });
    expect(slider).toBeDisabled();
    // The one place in this console where a disabled control beats an absent one: the
    // control is the position display as well. So it has to explain itself.
    expect(slider).toHaveAttribute("aria-describedby", "player-seek-note");
    expect(screen.getByTestId("player-seek-note")).toHaveTextContent(PLAYER_COPY.notSeekable);
    expect(screen.getByRole("button", { name: "Back 10 seconds" })).toBeDisabled();
  });

  it("leaves the scrubber live on a 206 and draws no note", async () => {
    serve(audioResponse(206));
    await playAndSettle();

    expect(screen.getByRole("slider", { name: "Seek" })).toBeEnabled();
    expect(screen.queryByTestId("player-seek-note")).toBeNull();
  });

  it("closing unloads the track, hides the bar and abandons the stream", async () => {
    const user = userEvent.setup();
    serve(audioResponse());
    const { container } = (() => {
      act(() => {
        usePlayerStore.getState().requestPlay(TRACK);
      });
      return renderWithProviders(<PlayerBar />);
    })();
    await waitFor(() => {
      expect(usePlayerStore.getState().phase).toBe("playable");
    });

    await user.click(screen.getByRole("button", { name: "Close the player" }));

    expect(usePlayerStore.getState().track).toBeNull();
    expect(usePlayerStore.getState().phase).toBe("idle");
    expect(container).toBeEmptyDOMElement();
  });
});
