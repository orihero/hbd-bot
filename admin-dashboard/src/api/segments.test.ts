import { afterEach, describe, expect, it, vi } from "vitest";

import { SEGMENT_SCHEMA_VERSION } from "@/api/constants";
import {
  audienceLanguages,
  getSegmentFields,
  previewSegment,
  segmentFieldIndex,
  supportsOp,
  type SegmentFieldsView,
} from "@/api/segments";
import { encodeSegment, type Segment } from "@/lib/segmentCodec";

/**
 * The two reads the rule builder is generated from, checked against the bodies the server
 * actually produces — `FIELDS_BODY` below is `to_segment_fields_view(capabilities=frozenset())`
 * verbatim, trimmed to three entries that between them exercise every branch the builder has:
 * an aggregate int, a plain enum, and a capability-gated token this deployment does not hold.
 *
 * The preview assertions are about the QUERY STRING more than the body: the wizard's audience
 * number and the Users page's rows have to be the same population, and the only thing that
 * makes them so is that both send the same bytes in `?segment=`.
 */

const FIELDS_BODY = {
  version: 1,
  defaultSort: { key: "joined_at", dir: "desc" },
  limits: { maxRules: 25, maxDepth: 3, maxValueMembers: 50, maxAggregateRules: 6 },
  fields: [
    {
      key: "order_count",
      kind: "int",
      ops: ["between", "eq", "gt", "gte", "in", "lt", "lte", "neq", "not_in"],
      sortable: true,
      isAggregate: true,
      capability: null,
      isAvailable: true,
      doc: "How many orders this account has placed, in any state.",
    },
    {
      key: "ui_language",
      kind: "enum",
      ops: ["eq", "in", "neq", "not_in"],
      sortable: false,
      isAggregate: false,
      capability: null,
      isAvailable: true,
      doc: "The language the bot speaks to this account in.",
    },
    {
      key: "wizard_step",
      kind: "token",
      ops: ["in", "not_in"],
      sortable: false,
      isAggregate: true,
      capability: "chat_messages",
      isAvailable: false,
      doc: "Which step of OUR wizard they have reached.",
    },
  ],
};

const PREVIEW_BODY = {
  matched: 1_204,
  reachable: 1_100,
  skippedBlocked: 12,
  skippedBotBlocked: 96,
  byLanguage: [
    { language: "ru", count: 700 },
    { language: "uz_latn", count: 504 },
  ],
};

const SEGMENT: Segment = {
  v: SEGMENT_SCHEMA_VERSION,
  match: "all",
  rules: [{ field: "order_count", op: "gte", value: 3 }],
};

/** The three fields of a `Response` `api/client.ts` reads, and nothing it does not. */
function answerWith(body: unknown, status = 200): unknown {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: () => Promise.resolve(body),
  };
}

function stubAnswer(body: unknown, status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() => Promise.resolve(answerWith(body, status)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getSegmentFields", () => {
  it("parses the registry the server publishes", async () => {
    stubAnswer(FIELDS_BODY);

    const result = await getSegmentFields();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.version).toBe(SEGMENT_SCHEMA_VERSION);
    expect(result.data.limits.maxRules).toBe(25);
    expect(result.data.defaultSort).toStrictEqual({ key: "joined_at", dir: "desc" });
    expect(result.data.fields).toHaveLength(3);
  });

  it("keeps a field this deployment cannot serve, marked unavailable", async () => {
    stubAnswer(FIELDS_BODY);

    const result = await getSegmentFields();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const gated = segmentFieldIndex(result.data).get("wizard_step");
    // Listed, not omitted: "the table is not installed here" and "nobody matched" must not
    // look the same on a screen a campaign is about to be sent from.
    expect(gated?.isAvailable).toBe(false);
    expect(gated?.capability).toBe("chat_messages");
  });

  it("refuses a registry this build does not understand, loudly", async () => {
    stubAnswer({
      ...FIELDS_BODY,
      fields: [{ ...FIELDS_BODY.fields[0], kind: "geo" }],
    });

    const result = await getSegmentFields();

    // A kind with no value editor is not a field the builder can draw. SCHEMA_DRIFT names the
    // path; silently dropping it would offer an audience the compiler refuses.
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("SCHEMA_DRIFT");
  });
});

describe("previewSegment", () => {
  it("sends the same bytes the Users list walks", async () => {
    const fetchMock = stubAnswer(PREVIEW_BODY);

    await previewSegment(SEGMENT);

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/segments/preview?segment=${encodeURIComponent(encodeSegment(SEGMENT))}`,
      expect.anything(),
    );
  });

  it("omits the parameter entirely when there is no document", async () => {
    const fetchMock = stubAnswer(PREVIEW_BODY);

    await previewSegment(null);

    // Not a bare `?`: two spellings of one request are two cache keys and two log lines.
    expect(fetchMock).toHaveBeenCalledWith("/api/segments/preview", expect.anything());
  });

  it("parses the counts and the per-language split", async () => {
    stubAnswer(PREVIEW_BODY);

    const result = await previewSegment(SEGMENT);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.matched).toBe(1_204);
    expect(result.data.reachable).toBe(1_100);
    expect(audienceLanguages(result.data)).toStrictEqual(["ru", "uz_latn"]);
  });

  it("surfaces a refusal rather than a count", async () => {
    stubAnswer(
      {
        error: {
          code: "INVALID_INPUT",
          message: "unknown field",
          correlationId: "c-1",
        },
      },
      422,
    );

    const result = await previewSegment(SEGMENT);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("INVALID_INPUT");
    expect(result.endpoint).toBe("GET /api/segments/preview");
  });
});

describe("reading the registry", () => {
  it("resolves a rule's field to its operator set, and misses to undefined", () => {
    const view = FIELDS_BODY as unknown as SegmentFieldsView;
    const index = segmentFieldIndex(view);
    const language = index.get("ui_language");

    expect(language).toBeDefined();
    if (language === undefined) return;
    expect(supportsOp(language, "in")).toBe(true);
    // The registry's own set, never a per-kind guess: an enum takes no range operator.
    expect(supportsOp(language, "gte")).toBe(false);
    expect(index.get("phone_e164")).toBeUndefined();
  });
});
