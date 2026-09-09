/**
 * The reveal's arithmetic, held against the server's.
 *
 * `plan_reveal` is the authority: a `single`-shaped reveal is `records_authorised = 1`
 * whatever it names, and a `paged` one is `page.limit` — defaulting to the fifty-record cap —
 * plus one conversation. Every assertion here is that rule, because it is what lets
 * `RevealDialog` show a cost BEFORE the confirm instead of after the 429.
 */

import { describe, expect, it } from "vitest";

import { MAX_RECORDS_PER_REVEAL, REVEAL_FIELD_VALUES, type RevealField } from "@/api";

import {
  ATTEMPT_REVEAL_FIELDS,
  BRIEF_REVEAL_FIELDS,
  USER_PROFILE_REVEAL_FIELDS,
  canSubmitReveal,
  describeRevealCost,
  orderFields,
  REVEAL_FIELD_HINTS,
  REVEAL_FIELD_LABELS,
  revealCost,
  revealShapeOf,
} from "./revealFields";

describe("the offered field groups", () => {
  it("cover every RevealField exactly once between them", () => {
    const covered = [
      ...BRIEF_REVEAL_FIELDS,
      ...ATTEMPT_REVEAL_FIELDS,
      ...USER_PROFILE_REVEAL_FIELDS,
    ];
    expect([...covered].sort()).toEqual([...REVEAL_FIELD_VALUES].sort());
    expect(new Set(covered).size).toBe(covered.length);
  });

  it("each group is one shape, because the server refuses a mixed request", () => {
    expect(revealShapeOf(BRIEF_REVEAL_FIELDS)).toBe("single");
    expect(revealShapeOf(ATTEMPT_REVEAL_FIELDS)).toBe("paged");
    expect(revealShapeOf(USER_PROFILE_REVEAL_FIELDS)).toBe("single");
  });

  it("every field has a label and a hint — a bare column name is not an affordance", () => {
    for (const field of REVEAL_FIELD_VALUES) {
      expect(REVEAL_FIELD_LABELS[field].length).toBeGreaterThan(0);
      expect(REVEAL_FIELD_HINTS[field].length).toBeGreaterThan(0);
    }
  });
});

describe("revealShapeOf", () => {
  it("is null for a mixed selection — one recordCount cannot describe two shapes", () => {
    expect(revealShapeOf(["briefs.note", "generation_attempts.stt_transcript"])).toBeNull();
  });

  it("is null for an empty selection: nothing to charge is not a request", () => {
    expect(revealShapeOf([])).toBeNull();
  });
});

describe("revealCost", () => {
  it("charges ONE record for all six brief columns together", () => {
    expect(revealCost(BRIEF_REVEAL_FIELDS)).toEqual({ records: 1, conversations: 0 });
    expect(revealCost(["briefs.note"])).toEqual({ records: 1, conversations: 0 });
  });

  it("never touches the daily conversation ceiling for a single-record reveal", () => {
    expect(revealCost(BRIEF_REVEAL_FIELDS).conversations).toBe(0);
  });

  it("charges ONE record for the whole profile — the reason the four are offered together", () => {
    // A `user_profiles` row is 1:1 with the account, so the phone, the two name parts and the
    // handle are one record between them. If this ever became four, an operator would be paying
    // four times over for one screen and the group would be the thing charging them.
    expect(revealCost(USER_PROFILE_REVEAL_FIELDS)).toEqual({ records: 1, conversations: 0 });
    expect(revealCost(["user_profiles.phone_e164"])).toEqual({ records: 1, conversations: 0 });
  });

  it("charges the whole page for the attempts' free text, plus one conversation", () => {
    expect(revealCost(ATTEMPT_REVEAL_FIELDS)).toEqual({
      records: MAX_RECORDS_PER_REVEAL,
      conversations: 1,
    });
  });

  it("charges the requested page size when one is given, not what it finds", () => {
    expect(revealCost(ATTEMPT_REVEAL_FIELDS, 10)).toEqual({ records: 10, conversations: 1 });
  });

  it("costs nothing for a selection that could not be sent", () => {
    expect(revealCost([])).toEqual({ records: 0, conversations: 0 });
    expect(revealCost(["briefs.note", "generation_attempts.stt_transcript"])).toEqual({
      records: 0,
      conversations: 0,
    });
  });
});

describe("describeRevealCost", () => {
  it("spells the unit out — a bare 1 beside a budget of 200 has to be decoded", () => {
    expect(describeRevealCost({ records: 1, conversations: 0 })).toBe("1 record");
    expect(describeRevealCost({ records: 50, conversations: 1 })).toBe(
      "50 records and 1 conversation",
    );
  });
});

describe("canSubmitReveal", () => {
  const fields: readonly RevealField[] = ["briefs.note"];

  it("refuses without a reason code, which is the whole of §12.3's requirement", () => {
    expect(canSubmitReveal({ fields, reasonCode: null })).toBe(false);
    expect(canSubmitReveal({ fields, reasonCode: "support_investigation" })).toBe(true);
  });

  it("refuses an empty selection and a mixed one", () => {
    expect(canSubmitReveal({ fields: [], reasonCode: "incident" })).toBe(false);
    expect(
      canSubmitReveal({
        fields: ["briefs.note", "generation_attempts.stt_transcript"],
        reasonCode: "incident",
      }),
    ).toBe(false);
  });
});

describe("orderFields", () => {
  it("keeps the offered order, not the set's iteration order", () => {
    const chosen = new Set<RevealField>(["briefs.note", "briefs.recipient_name_display"]);
    expect(orderFields(BRIEF_REVEAL_FIELDS, chosen)).toEqual([
      "briefs.recipient_name_display",
      "briefs.note",
    ]);
  });

  it("emits each field once, so no reveal is audited twice for one read", () => {
    const chosen = new Set<RevealField>(BRIEF_REVEAL_FIELDS);
    const ordered = orderFields(BRIEF_REVEAL_FIELDS, chosen);
    expect(new Set(ordered).size).toBe(ordered.length);
  });
});
