import { describe, expect, it, vi } from "vitest";

import { segmentFieldIndex } from "@/api/segments";
import { useI18n } from "@/i18n";
import { EMPTY_SEGMENT, encodeSegment, type Segment } from "@/lib/segmentCodec";

import { SEGMENT_FIELDS_FIXTURE } from "./fixtures";
import { monthRangeIso } from "./instants";
import { buildSegmentChips, segmentFilterCount } from "./segmentChips";
import { removeAt } from "./segmentTree";

/**
 * The chips are the only place a nine-clause audience is legible without opening the builder,
 * so what they say has to be true in three specific ways: the COUNT is leaf rules rather than
 * the one URL key, a NESTED rule says which group it is in, and removing one removes exactly
 * that rule and nothing else.
 */

const FIELDS = segmentFieldIndex(SEGMENT_FIELDS_FIXTURE);
const t = useI18n.getState().t;

function chipsOf(segment: Segment, onChange = vi.fn()): ReturnType<typeof buildSegmentChips> {
  return buildSegmentChips({ segment, fields: FIELDS, t, locale: "en", onChange });
}

describe("segmentChips", () => {
  it("folds the operator into the value and leaves the field as the field", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [{ field: "delivered_order_count", op: "gte", value: 3 }],
    };

    expect(chipsOf(segment)).toEqual([
      expect.objectContaining({ field: "Songs delivered", value: "is at least 3" }),
    ]);
  });

  it("names an enum member rather than echoing the wire spelling", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [{ field: "plan_status", op: "in", value: ["lapsed"] }],
    };

    const chip = chipsOf(segment)[0];
    expect(chip?.field).toBe("Plan status");
    expect(chip?.value).toBe("is any of Plan expired, not bought again");
  });

  it("reads a date range as two days in the operator's own zone, not as an instant", () => {
    const june = monthRangeIso("2026-06");
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [{ field: "joined_at", op: "between", value: [june?.[0] ?? "", june?.[1] ?? ""] }],
    };

    const chip = chipsOf(segment)[0];
    expect(chip?.field).toBe("First contact");
    // Half-open, so the second bound is the first instant of July — printed as the day it is.
    expect(chip?.value).toMatch(/^is between .*Jun.*2026 – .*Jul.*2026$/u);
  });

  it("carries no value at all for a no-operand operator", () => {
    const segment: Segment = { ...EMPTY_SEGMENT, rules: [{ field: "is_reachable", op: "is_true" }] };
    expect(chipsOf(segment)[0]?.value).toBe("yes");
  });

  it("says which group a nested rule belongs to", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [
        { field: "is_reachable", op: "is_true" },
        {
          match: "any",
          rules: [
            { field: "topup_count", op: "gte", value: 1 },
            { field: "credit_balance", op: "gt", value: 0 },
          ],
        },
      ],
    };

    const chips = chipsOf(segment);
    expect(chips.map((chip) => chip.field)).toEqual([
      "Reachable",
      "Any · Top-ups",
      "Any · Credit balance",
    ]);
  });

  it("counts LEAF rules at every depth, never the one segment parameter", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [
        { field: "is_reachable", op: "is_true" },
        {
          match: "any",
          rules: [
            { field: "topup_count", op: "gte", value: 1 },
            { field: "credit_balance", op: "gt", value: 0 },
          ],
        },
      ],
    };

    expect(segmentFilterCount(segment)).toBe(3);
    expect(chipsOf(segment)).toHaveLength(3);
  });

  it("removes exactly the rule it names, and prunes the group that emptied", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [
        { field: "is_reachable", op: "is_true" },
        { match: "any", rules: [{ field: "topup_count", op: "gte", value: 1 }] },
      ],
    };
    const onChange = vi.fn<(next: Segment) => void>();

    const chips = chipsOf(segment, onChange);
    chips[1]?.onRemove();

    expect(onChange).toHaveBeenCalledWith({
      ...EMPTY_SEGMENT,
      rules: [{ field: "is_reachable", op: "is_true" }],
    });
  });

  it("still describes a rule whose field the registry no longer publishes", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [{ field: "withdrawn_field", op: "eq", value: 1 }],
    };

    // Under its raw key, so the operator can see it and delete it — a rule that vanishes from
    // the chips is a narrowing nobody made.
    expect(chipsOf(segment)[0]?.field).toBe("withdrawn_field");
  });

  it("leaves the document a chip removal produced encodable as the same bytes the server reads", () => {
    const segment: Segment = {
      ...EMPTY_SEGMENT,
      rules: [
        { field: "plan_status", op: "in", value: ["lapsed"] },
        { field: "delivered_order_count", op: "gte", value: 2 },
      ],
    };

    expect(encodeSegment(removeAt(segment, [1]))).toBe(
      encodeSegment({
        ...EMPTY_SEGMENT,
        rules: [{ field: "plan_status", op: "in", value: ["lapsed"] }],
      }),
    );
  });
});
