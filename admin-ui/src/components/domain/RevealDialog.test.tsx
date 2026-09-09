/**
 * The reveal dialog, from an operator's side and from the datum's.
 *
 * Two families of assertion, and the second is the one this product exists for:
 *
 * **The controls.** A VIEWER sees no affordance at all (§11.4: hiding, not disabling). The
 * cost is on screen BEFORE the confirm, against the remaining budget. Without a `reasonCode`
 * there is no confirm — the 422 is not allowed to be how the operator finds out. A 403
 * `STEP_UP_REQUIRED` routes into a password box and the SAME request goes again afterwards. A
 * 429 names which of the two budgets refused and when it resets.
 *
 * **The plaintext.** `Oʻktam`, `Gʻulom`, `Дилноза` and `sanʼat` come back out of the DOM with
 * their codepoints intact — U+02BB MODIFIER LETTER TURNED COMMA and U+02BC MODIFIER LETTER
 * APOSTROPHE, not the U+0027 that an autocorrect, a "smart quotes" pass or a hand-written
 * ASCII-fold would leave behind. (Not `NFKD`, whatever the older comments here said: all
 * four normalisation forms leave U+02BB and U+02BC alone. What really breaks these names is
 * case folding, `localeCompare`, and `text-transform`.) The assertions are on
 * `String.prototype.codePointAt` rather than on string equality, because two strings that
 * differ only in which apostrophe they carry look identical in a test failure and identical on
 * a 14px screen — which is the whole reason `<NameText>` exists.
 */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminRole, RevealSubjectType } from "@/api";
import {
  makeTestQueryClient,
  configFixture,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import {
  ATTEMPT_REVEAL_FIELDS,
  BRIEF_REVEAL_FIELDS,
  USER_PROFILE_REVEAL_FIELDS,
} from "./revealFields";
import { NO_RETENTION_CLOCK_NOTE, RevealButton } from "./RevealDialog";

const ORDER = "3f2a9c10-8b44-4d21-9f0e-6a7c5b3e1d02";
/* `users.id`, never the Telegram integer: the step-up scope is `reveal:<uuid>`, compared whole. */
const USER = "b41d0f8e-2c77-4a63-9c15-8e0d2f3a6b91";
const RECORD = "9b8d7c6e-5a4f-4312-8e7d-1c2b3a495867";

/* The datum. Written with explicit escapes so this file's own encoding cannot be the bug. */
const OKTAM = "Oʻktam";
const GULOM = "Gʻulom";
const DILNOZA = "Дилноза";
const SANAT = "sanʼat";

/**
 * A stubbed `Response`. Header lookup is EXACT rather than case-folded, and deliberately so:
 * `toLowerCase` is banned inside `components/domain/` (it is one of the calls that destroys
 * U+02BB), and a test helper is not a reason to reach around the fence. The client asks for
 * exactly `X-Correlation-ID` and `Retry-After`, so exact keys are enough.
 */
function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => headers[name] ?? null },
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function revealBody(
  overrides: {
    fields?: Record<string, unknown>;
    nextCursor?: string | null;
    recordCount?: number;
    revealedFields?: readonly string[];
    records?: unknown[];
    budget?: Record<string, unknown>;
    subjectType?: RevealSubjectType;
    subjectId?: string;
  } = {},
) {
  const record = {
    recordId: RECORD,
    createdAt: "2026-09-01T09:15:00Z",
    fields: overrides.fields ?? {
      "briefs.recipient_name_display": OKTAM,
      "briefs.recipient_name_raw": GULOM,
      "briefs.note": `${DILNOZA} — ${SANAT}`,
    },
    identityPurgedAt: null,
    textPurgedAt: null,
  };
  return {
    subjectType: overrides.subjectType ?? "order",
    subjectId: overrides.subjectId ?? ORDER,
    revealedAt: "2026-09-02T10:30:00Z",
    reasonCode: "support_investigation",
    recordCount: overrides.recordCount ?? 1,
    revealedFields: overrides.revealedFields ?? [
      "briefs.recipient_name_display",
      "briefs.recipient_name_raw",
      "briefs.note",
    ],
    records: overrides.records ?? [record],
    nextCursor: overrides.nextCursor ?? null,
    budget: overrides.budget ?? {
      recordsCharged: 1,
      recordsRemaining: 143,
      conversationsCharged: 0,
      conversationsRemaining: null,
    },
  };
}

interface Stub {
  readonly reveal: () => Response;
  readonly stepUp?: () => Response;
}

/** Every request this dialog can make, and nothing else. An unexpected URL fails loudly. */
function stubFetch(stub: Stub): ReturnType<typeof vi.fn> {
  const calls = vi.fn((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/reveal")) return Promise.resolve(stub.reveal());
    if (url.includes("/api/auth/step-up")) {
      const answer = stub.stepUp;
      if (answer === undefined) return Promise.reject(new Error("no step-up expected"));
      return Promise.resolve(answer());
    }
    return Promise.reject(new Error(`unexpected request: ${url} ${String(init?.method)}`));
  });
  vi.stubGlobal("fetch", calls);
  return calls;
}

function renderButton(
  role: AdminRole = "support",
  fields: readonly (typeof BRIEF_REVEAL_FIELDS)[number][] = BRIEF_REVEAL_FIELDS,
  subject: { readonly type: RevealSubjectType; readonly id: string } = { type: "order", id: ORDER },
) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.config.detail(), configFixture());
  return renderWithProviders(
    <RevealButton
      subjectType={subject.type}
      subjectId={subject.id}
      subjectLabel="3f2a9c10…"
      fields={fields}
    />,
    { client, me: meFixture(role) },
  );
}

function open(): void {
  fireEvent.click(screen.getByTestId("reveal-button"));
}

function chooseReason(code = "support_investigation"): void {
  fireEvent.change(screen.getByTestId("reveal-reason-code"), { target: { value: code } });
}

/**
 * The codepoints of a rendered value, read the way the datum is actually at risk.
 *
 * Walked by index with `codePointAt` rather than spread: spreading a string is banned by
 * `no-misused-spread` (it decomposes some graphemes), and `codePointAt` is the thing this
 * assertion is actually about — two strings differing only in WHICH apostrophe they carry
 * compare unequal here and look identical anywhere else.
 */
function codepointsOf(text: string): number[] {
  const points: number[] = [];
  for (let index = 0; index < text.length; ) {
    const point = text.codePointAt(index);
    if (point === undefined) break;
    points.push(point);
    index += point > 0xffff ? 2 : 1;
  }
  return points;
}

function revealedText(field: string): string {
  const block = screen
    .getAllByTestId("revealed-field")
    .find((element) => element.dataset["field"] === field);
  if (block === undefined) throw new Error(`no revealed field ${field}`);
  return within(block).getByTestId("name-text").textContent ?? "";
}

function bodyOf(calls: ReturnType<typeof vi.fn>, index: number): Record<string, unknown> {
  const call = calls.mock.calls[index];
  if (call === undefined) throw new Error(`no call ${String(index)}`);
  const init = call[1] as RequestInit | undefined;
  const raw = init?.body;
  if (typeof raw !== "string") throw new Error(`call ${String(index)} carried no JSON body`);
  return JSON.parse(raw) as Record<string, unknown>;
}

beforeEach(() => {
  resetPrefs();
});

describe("who sees the affordance at all", () => {
  it("is invisible to a VIEWER — §11.4 is hiding, not disabling", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton("viewer");
    expect(screen.queryByTestId("reveal-button")).not.toBeInTheDocument();
  });

  it("is there for SUPPORT and above, which is §12.2's reveal row", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton("support");
    expect(screen.getByTestId("reveal-button")).toBeInTheDocument();
  });
});

describe("before the confirm", () => {
  it("shows the record cost against the remaining budget", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    expect(screen.getByTestId("reveal-cost").textContent).toContain("charged 1 record");
    expect(screen.getByTestId("reveal-budget-meter")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-budget-meter").textContent).toContain(
      "this reveal costs 1 record",
    );
  });

  it("prices a paged reveal at the whole page and one conversation, before it is sent", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton("support", [...ATTEMPT_REVEAL_FIELDS] as never);
    open();
    expect(screen.getByTestId("reveal-cost").textContent).toContain(
      "charged 50 records and 1 conversation",
    );
    expect(screen.getAllByTestId("reveal-budget-row")).toHaveLength(2);
  });

  it("lets the operator buy a smaller page, because the page size IS the charge", async () => {
    const calls = stubFetch({ reveal: () => jsonResponse(200, revealBody({ recordCount: 10 })) });
    renderButton("support", [...ATTEMPT_REVEAL_FIELDS] as never);
    open();

    fireEvent.change(screen.getByTestId("reveal-limit"), { target: { value: "10" } });
    expect(screen.getByTestId("reveal-cost").textContent).toContain(
      "charged 10 records and 1 conversation",
    );

    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");
    expect(bodyOf(calls, 0)["limit"]).toBe(10);
  });

  it("sends no page control at all on a single-record reveal — the server refuses one", async () => {
    const calls = stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    expect(screen.queryByTestId("reveal-limit")).not.toBeInTheDocument();

    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");
    expect(bodyOf(calls, 0)).not.toHaveProperty("limit");
  });

  it("withholds the confirm until a reason code is chosen, and says why", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    expect(screen.getByTestId("reveal-confirm")).toBeDisabled();
    expect(screen.getByTestId("reveal-reason-required")).toBeInTheDocument();

    chooseReason();
    expect(screen.getByTestId("reveal-confirm")).toBeEnabled();
    expect(screen.queryByTestId("reveal-reason-required")).not.toBeInTheDocument();
  });

  it("refuses a selection that mixes the two record shapes", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton("support", [
      "briefs.note",
      "generation_attempts.stt_transcript",
    ] as never);
    open();
    chooseReason();
    expect(screen.getByTestId("reveal-confirm")).toBeDisabled();
    expect(screen.getByTestId("reveal-cost").textContent).toContain("one record shape");
  });

  it("warns about a ticket reference the audit boundary will read as a credential", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    fireEvent.change(screen.getByTestId("reveal-reason-ref"), {
      target: { value: "a".repeat(44) },
    });
    expect(screen.getByTestId("reveal-ref-credential-warning")).toBeInTheDocument();
  });

  it("sends the reason code and the chosen columns, and nothing it was not given", async () => {
    const calls = stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    // Untick everything but the note, so the request is not just "all of them".
    for (const field of BRIEF_REVEAL_FIELDS) {
      if (field === "briefs.note") continue;
      fireEvent.click(screen.getByRole("checkbox", { name: new RegExp(field, "u") }));
    }
    chooseReason("abuse_report");
    fireEvent.click(screen.getByTestId("reveal-confirm"));

    await screen.findByTestId("reveal-result");
    const body = bodyOf(calls, 0);
    expect(body["subjectType"]).toBe("order");
    expect(body["subjectId"]).toBe(ORDER);
    expect(body["fields"]).toEqual(["briefs.note"]);
    expect(body["reasonCode"]).toBe("abuse_report");
    expect(body).not.toHaveProperty("reasonRef");
    expect(body).not.toHaveProperty("reasonText");
    expect(body).not.toHaveProperty("cursor");
  });
});

describe("the revealed plaintext", () => {
  it("carries U+02BB and U+02BC out of the DOM unfolded", async () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    expect(codepointsOf(revealedText("briefs.recipient_name_display"))).toEqual([
      0x4f, 0x02bb, 0x6b, 0x74, 0x61, 0x6d,
    ]);
    expect(codepointsOf(revealedText("briefs.recipient_name_raw"))).toEqual([
      0x47, 0x02bb, 0x75, 0x6c, 0x6f, 0x6d,
    ]);

    const note = revealedText("briefs.note");
    expect(codepointsOf(note.slice(0, 7))).toEqual([
      0x414, 0x438, 0x43b, 0x43d, 0x43e, 0x437, 0x430,
    ]);
    // `sanʼat` uses U+02BC, a DIFFERENT modifier letter from the name's U+02BB.
    expect(note.codePointAt(note.length - 3)).toBe(0x02bc);
    expect(note).not.toContain("'");
    expect(note).not.toContain("’");
  });

  it("tags every revealed value as Uzbek Latin, left to right", async () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    for (const span of screen.getAllByTestId("name-text")) {
      expect(span).toHaveAttribute("lang", "uz-Latn");
      expect(span).toHaveAttribute("dir", "ltr");
    }
  });

  it("renders a NULL column as the fact it is, never as an em dash or a blank", async () => {
    stubFetch({
      reveal: () =>
        jsonResponse(
          200,
          revealBody({
            fields: { "briefs.note": null },
            revealedFields: ["briefs.note"],
          }),
        ),
    });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    expect(screen.getByTestId("revealed-null").textContent).toContain("the column holds nothing");
    expect(screen.queryByTestId("name-text")).not.toBeInTheDocument();
  });

  it("offers the next page as a fresh reveal, priced again", async () => {
    stubFetch({
      reveal: () =>
        jsonResponse(200, revealBody({ nextCursor: "opaque-cursor", recordCount: 50 })),
    });
    renderButton("support", [...ATTEMPT_REVEAL_FIELDS] as never);
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    expect(screen.getByTestId("reveal-next-page").textContent).toContain(
      "a fresh reveal, 50 records and 1 conversation again",
    );
  });

  it("records the budget the response reported, for the next dialog to show", async () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    const { client } = renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    await waitFor(() => {
      expect(screen.getByTestId("reveal-budget-meter").textContent).toContain(
        "143 of 200 left this hour",
      );
    });
    expect(client.getQueryData(queryKeys.reveal.budget())).toBeDefined();
  });
});

describe("a 403 STEP_UP_REQUIRED", () => {
  const refusal = () =>
    jsonResponse(403, {
      error: {
        code: "STEP_UP_REQUIRED",
        message: "re-authenticate for this action and this subject",
        correlationId: "c0ffee",
        details: { stepUpAction: "reveal", subjectId: ORDER },
      },
    });

  it("routes the operator into the step-up flow, not into a dead error", async () => {
    stubFetch({ reveal: refusal });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));

    const prompt = await screen.findByTestId("step-up-prompt");
    expect(prompt.dataset["stepUpAction"]).toBe("reveal");
    // Byte-identical: a re-formatted subject id is a scope mismatch nobody can debug.
    expect(prompt.dataset["stepUpSubject"]).toBe(ORDER);
    expect(screen.queryByTestId("reveal-failure")).not.toBeInTheDocument();
  });

  it("re-sends the SAME request once the grant lands, and shows the plaintext", async () => {
    let attempts = 0;
    const calls = stubFetch({
      reveal: () => {
        attempts += 1;
        return attempts === 1 ? refusal() : jsonResponse(200, revealBody());
      },
      stepUp: () =>
        jsonResponse(200, {
          scope: `reveal:${ORDER}`,
          grantedAt: "2026-09-02T10:30:00Z",
          expiresAt: "2026-09-02T10:35:00Z",
        }),
    });

    renderButton();
    open();
    chooseReason("incident");
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("step-up-prompt");

    fireEvent.change(screen.getByLabelText("Your password"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Re-authenticate" }));

    await screen.findByTestId("reveal-result");
    expect(codepointsOf(revealedText("briefs.recipient_name_display"))[1]).toBe(0x02bb);

    // The step-up carried the bare action and the canonical subject id …
    const grant = bodyOf(calls, 1);
    expect(grant["scope"]).toBe("reveal");
    expect(grant["subjectId"]).toBe(ORDER);
    // … and the retry was the original body, unchanged. A grant authorises an action on a
    // subject, not a request; the server remembers nothing about what we were trying to do.
    expect(bodyOf(calls, 2)).toEqual(bodyOf(calls, 0));
  });

  it("does NOT offer a password box for a router-level refusal no password can fix", async () => {
    stubFetch({
      reveal: () =>
        jsonResponse(403, {
          error: {
            code: "STEP_UP_REQUIRED",
            message: "this action needs a step-up",
            correlationId: "c0ffee",
          },
        }),
    });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));

    const notice = await screen.findByTestId("reveal-failure");
    expect(notice.dataset["code"]).toBe("STEP_UP_REQUIRED");
    expect(screen.queryByTestId("step-up-prompt")).not.toBeInTheDocument();
  });
});

describe("a 429 REVEAL_BUDGET_EXHAUSTED", () => {
  it("says WHICH budget, what is left and when it resets", async () => {
    stubFetch({
      reveal: () =>
        jsonResponse(
          429,
          {
            error: {
              code: "REVEAL_BUDGET_EXHAUSTED",
              message: "this operator's reveal budget for the window is spent",
              correlationId: "c0ffee",
              details: {
                budget: "conversations",
                recordsRequested: 50,
                recordsRemaining: null,
                conversationsRemaining: 0,
              },
            },
          },
          { "Retry-After": "600" },
        ),
    });
    renderButton("support", [...ATTEMPT_REVEAL_FIELDS] as never);
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));

    const notice = await screen.findByTestId("reveal-budget-exhausted");
    expect(notice.dataset["budgetScope"]).toBe("conversations");
    expect(notice.textContent).toContain("conversations a day");
    expect(notice.textContent).toContain("10 min from now");
    expect(notice.textContent).toContain("Nothing was charged");
  });

  it("never renders a bare 'you have run out' with no number and no clock", async () => {
    stubFetch({
      reveal: () =>
        jsonResponse(429, {
          error: {
            code: "REVEAL_BUDGET_EXHAUSTED",
            message: "spent",
            correlationId: "c0ffee",
            details: { budget: "records", recordsRequested: 1, recordsRemaining: 0 },
          },
        }),
    });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));

    const notice = await screen.findByTestId("reveal-budget-exhausted");
    expect(notice.textContent).toContain("records an hour");
    expect(notice.textContent).toMatch(/resets at/u);
  });
});

describe("closing", () => {
  it("drops the plaintext and the reason when the dialog is reopened", async () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.queryByTestId("reveal-result")).not.toBeInTheDocument();
    });

    open();
    expect(screen.queryByTestId("reveal-result")).not.toBeInTheDocument();
    expect(screen.getByTestId("reveal-confirm")).toBeDisabled();
    expect(screen.getByTestId("reveal-reason-code")).toHaveValue("");
  });
});

/*
 * §12.3 shows the purge stamps BECAUSE they are different facts from "no value": "no name" and
 * "name purged on schedule on 2026-05-14" are different answers to a data-subject request. That
 * argument is about an order. A `user_profiles` row is on no clock at all — PD-2 gives it no
 * `*_expires_at` and no sweep, and `/forget` DELETEs it — so printing "identity clock: not
 * purged" beside a customer's phone number would name a schedule that does not exist and imply
 * the number ages out on its own. Same rule, opposite direction, and both are tested here so a
 * reword of one cannot quietly take the other with it.
 */
describe("the retention line on a revealed record", () => {
  it("prints both clocks for an order subject", async () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody()) });
    renderButton();
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    const clocks = screen.getByTestId("reveal-record-clocks");
    expect(clocks.textContent).toContain("identity clock");
    expect(clocks.textContent).toContain("free-text clock");
    expect(clocks.textContent).not.toContain(NO_RETENTION_CLOCK_NOTE);
  });

  it("names no clock at all for a user subject, and says what erases the row instead", async () => {
    stubFetch({
      reveal: () =>
        jsonResponse(
          200,
          revealBody({
            subjectType: "user",
            subjectId: USER,
            fields: { "user_profiles.phone_e164": "+998901234542" },
            revealedFields: ["user_profiles.phone_e164"],
          }),
        ),
    });
    renderButton("support", [...USER_PROFILE_REVEAL_FIELDS] as never, {
      type: "user",
      id: USER,
    });
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    const clocks = screen.getByTestId("reveal-record-clocks");
    expect(clocks.textContent).toBe(NO_RETENTION_CLOCK_NOTE);
    // Asserted on the whole result, not just the line: a stray "not purged" anywhere in this
    // panel is the same claim made in a different place.
    const result = screen.getByTestId("reveal-result").textContent ?? "";
    expect(result).not.toContain("identity clock");
    expect(result).not.toContain("free-text clock");
    expect(result).not.toContain("not purged");
  });

  it("sends the users.id UUID as the subject, never the Telegram integer", async () => {
    const calls = stubFetch({
      reveal: () =>
        jsonResponse(
          200,
          revealBody({
            subjectType: "user",
            subjectId: USER,
            fields: { "user_profiles.phone_e164": "+998901234542" },
            revealedFields: ["user_profiles.phone_e164"],
          }),
        ),
    });
    renderButton("support", [...USER_PROFILE_REVEAL_FIELDS] as never, {
      type: "user",
      id: USER,
    });
    open();
    chooseReason();
    fireEvent.click(screen.getByTestId("reveal-confirm"));
    await screen.findByTestId("reveal-result");

    // The server composes the step-up scope as `reveal:<subjectId>` and compares it WHOLE. An
    // integer here would be a scope no grant can ever match: a permanent, undebuggable 403.
    const body = bodyOf(calls, 0);
    expect(body["subjectType"]).toBe("user");
    expect(body["subjectId"]).toBe(USER);
    expect(body["fields"]).toEqual([...USER_PROFILE_REVEAL_FIELDS]);
  });

  it("prices all four profile columns as ONE record, before the confirm", () => {
    stubFetch({ reveal: () => jsonResponse(200, revealBody({ subjectType: "user" })) });
    renderButton("support", [...USER_PROFILE_REVEAL_FIELDS] as never, {
      type: "user",
      id: USER,
    });
    open();

    // One `user_profiles` row is one record however many of its columns are named. An operator
    // who is shown four would tick one, come back for the next, and pay four times over.
    expect(screen.getByTestId("reveal-cost").textContent).toContain("charged 1 record");
  });
});
