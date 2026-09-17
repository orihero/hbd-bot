import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type JSX } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { EMPTY_SEGMENT, type Segment, type SegmentNode } from "@/lib/segmentCodec";

import { SegmentBuilder } from "./SegmentBuilder";
import { SEGMENT_FIELDS_FIXTURE } from "./fixtures";
import { monthRangeIso } from "./instants";

/**
 * The builder, driven the way an operator drives it, against the REAL field registry.
 *
 * `fixtures.ts` is `GET /api/segments/fields` verbatim — forty fields, their real operator
 * sets, their real `doc` prose, on a deployment without `chat_messages`. Every audience
 * composed below is therefore composed out of operators the server actually offers, and the
 * documents asserted on are byte-for-byte the ones `BROADCAST_SPEC §1.5` writes out by hand.
 * A registry change that withdrew `plan_status in`, or made `last_activity_at` sortable, or
 * dropped `not_within_last_days`, fails here rather than in a 422 an operator has to read.
 *
 * The four audiences the operator asked for by name each get a test, and each one is asserted
 * as the DOCUMENT rather than as pixels: the document is what the wizard freezes, what the URL
 * carries and what the compiler sees, and it is the only thing two screens have to agree on.
 */

const FIELDS = SEGMENT_FIELDS_FIXTURE.fields;
const LIMITS = SEGMENT_FIELDS_FIXTURE.limits;

let latest: Segment = EMPTY_SEGMENT;

function Harness({
  initial = EMPTY_SEGMENT,
  showSort = false,
}: {
  readonly initial?: Segment;
  readonly showSort?: boolean;
}): JSX.Element {
  const [segment, setSegment] = useState<Segment>(initial);
  latest = segment;
  return (
    <SegmentBuilder
      value={segment}
      onChange={setSegment}
      fields={FIELDS}
      limits={LIMITS}
      version={SEGMENT_FIELDS_FIXTURE.version}
      showSort={showSort}
    />
  );
}

/** The one rule row on screen, scoped so its three controls can be addressed by their labels. */
function rule(index = 1): HTMLElement {
  return screen.getByRole("group", { name: `Rule ${String(index)}` });
}

function fieldSelect(index = 1): HTMLSelectElement {
  return within(rule(index)).getByLabelText("Field");
}

function conditionSelect(index = 1): HTMLSelectElement {
  return within(rule(index)).getByLabelText("Condition");
}

/** `rules` alone: every assertion below is about what was selected, not about the ordering. */
function rulesOf(segment: Segment): readonly SegmentNode[] {
  return segment.rules;
}

beforeEach(() => {
  latest = EMPTY_SEGMENT;
});

describe("SegmentBuilder — the four audiences asked for by name", () => {
  it("composes “people who did not renew their subscription” as plan_status in [lapsed]", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await user.selectOptions(fieldSelect(), "plan_status");

    // The registry offers `in` and `not_in` on this field and the builder opens on `in`, so
    // the only thing left is which case — and "lapsed" is the ONLY truthful spelling of "did
    // not renew": this product has no renewal, so the label says "expired, not bought again".
    expect(conditionSelect()).toHaveValue("in");
    await user.click(screen.getByRole("button", { name: "Plan expired, not bought again" }));

    expect(rulesOf(latest)).toEqual([{ field: "plan_status", op: "in", value: ["lapsed"] }]);
  });

  it("composes “people who joined in June” as a half-open month on joined_at", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await user.selectOptions(fieldSelect(), "joined_at");

    // An instant field opens on `between`, which is the half-open `[a, b)` the dashboard's own
    // windows use — so a June segment and a June tile count the same accounts.
    expect(conditionSelect()).toHaveValue("between");

    const month = within(rule()).getByLabelText("Rule 1: Whole month");
    fireEvent.change(month, { target: { value: "2026-06" } });

    const range = monthRangeIso("2026-06");
    expect(range).not.toBeNull();
    expect(rulesOf(latest)).toEqual([
      { field: "joined_at", op: "between", value: [range?.[0], range?.[1]] },
    ]);
  });

  it("composes “the people who generated the most” as a threshold plus a sort", async () => {
    const user = userEvent.setup();
    render(<Harness showSort />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await user.selectOptions(fieldSelect(), "delivered_order_count");
    expect(conditionSelect()).toHaveValue("gte");

    await user.type(within(rule()).getByLabelText("Rule 1: Number"), "3{Enter}");

    await user.selectOptions(screen.getByLabelText("Sort by"), "delivered_order_count");
    await user.selectOptions(screen.getByLabelText("Direction"), "desc");

    // A sort alone narrows nothing, which is why the threshold is half the audience.
    expect(latest).toEqual({
      v: 1,
      match: "all",
      rules: [{ field: "delivered_order_count", op: "gte", value: 3 }],
      sort: { key: "delivered_order_count", dir: "desc" },
    });
  });

  it("composes “people inactive for months” as not_within_last_days on last_activity_at", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await user.selectOptions(fieldSelect(), "last_activity_at");
    await user.selectOptions(conditionSelect(), "not_within_last_days");
    await user.click(within(rule()).getByRole("button", { name: "90 days" }));

    expect(rulesOf(latest)).toEqual([
      { field: "last_activity_at", op: "not_within_last_days", value: 90 },
    ]);
  });
});

describe("SegmentBuilder — what the registry is allowed to decide", () => {
  it("offers only sortable keys in the sort control", async () => {
    const user = userEvent.setup();
    render(<Harness showSort />);

    const sort = screen.getByLabelText("Sort by");
    // Filterable and deliberately NOT sortable: a sort publishes a total order over identified
    // accounts, which is the surveillance the withheld projection exists to prevent.
    expect(within(sort).queryByRole("option", { name: "Last activity" })).toBeNull();
    expect(within(sort).getByRole("option", { name: "Songs delivered" })).toBeInTheDocument();

    await user.selectOptions(sort, "delivered_order_count");
    expect(latest.sort).toEqual({ key: "delivered_order_count", dir: "desc" });
  });

  it("swaps the value editor with the kind, so a date field never offers a number box", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));

    await user.selectOptions(fieldSelect(), "order_count");
    expect(within(rule()).getByLabelText("Rule 1: Number")).toHaveAttribute("type", "number");

    await user.selectOptions(fieldSelect(), "joined_at");
    expect(within(rule()).queryByLabelText("Rule 1: Number")).toBeNull();
    expect(within(rule()).getByLabelText("Rule 1: From")).toHaveAttribute("type", "date");
  });

  it("lists a capability-gated field this deployment lacks, disabled rather than hidden", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    const option = within(fieldSelect()).getByRole("option", {
      name: "Wizard step — unavailable here",
    });
    // "The table is not installed here" and "nobody matched" must not look the same.
    expect(option).toBeDisabled();
  });

  it("renders the field's own doc verbatim rather than a paraphrase", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await user.selectOptions(fieldSelect(), "plan_status");

    const published = FIELDS.find((field) => field.key === "plan_status");
    expect(published).toBeDefined();
    expect(within(rule()).getByText(published?.doc ?? "")).toBeInTheDocument();
  });
});

describe("SegmentBuilder — the limits, named before the round trip", () => {
  function repeatedRules(count: number, field: string): readonly SegmentNode[] {
    return Array.from({ length: count }, () => ({ field, op: "gte" as const, value: 1 }));
  }

  it("names maxRules with both numbers, and stops offering another rule", () => {
    const overfull: Segment = {
      ...EMPTY_SEGMENT,
      rules: repeatedRules(LIMITS.maxRules + 1, "telegram_user_id"),
    };
    render(<Harness initial={overfull} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(String(LIMITS.maxRules + 1));
    expect(alert).toHaveTextContent(String(LIMITS.maxRules));
    expect(screen.getAllByRole("button", { name: "Add rule" })[0]).toBeDisabled();
  });

  it("names maxDepth on a document nested one level too far", () => {
    const tooDeep: Segment = {
      ...EMPTY_SEGMENT,
      rules: [
        {
          match: "any",
          rules: [
            {
              match: "all",
              rules: [
                { match: "any", rules: [{ field: "order_count", op: "gte", value: 1 }] },
              ],
            },
          ],
        },
      ],
    };
    render(<Harness initial={tooDeep} />);

    expect(screen.getByRole("alert")).toHaveTextContent(String(LIMITS.maxDepth));
  });

  it("names maxAggregateRules — the only limit that is about cost", () => {
    const expensive: Segment = {
      ...EMPTY_SEGMENT,
      rules: repeatedRules(LIMITS.maxAggregateRules + 1, "order_count"),
    };
    render(<Harness initial={expensive} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      String(LIMITS.maxAggregateRules + 1),
    );
  });

  it("names maxValueMembers on the rule that carries too many", () => {
    const members = Array.from({ length: LIMITS.maxValueMembers + 1 }, (_, index) => index);
    const wide: Segment = {
      ...EMPTY_SEGMENT,
      rules: [{ field: "telegram_user_id", op: "in", value: members }],
    };
    render(<Harness initial={wide} />);

    // The rule that broke it says so, with both numbers — the server's 422 can name only the
    // bound, and by the time it lands the operator is looking at a list of forty fields.
    expect(
      within(rule()).getByText(
        `Telegram id names ${String(members.length)} values, and the server accepts at most ${String(LIMITS.maxValueMembers)}.`,
      ),
    ).toBeInTheDocument();
  });

  it("says out loud that a segment with no rules is everyone", () => {
    render(<Harness />);
    expect(screen.getByRole("status")).toHaveTextContent(/everyone/iu);
  });

  it("refuses to leave a nested group empty when its last rule is removed", async () => {
    const user = userEvent.setup();
    const nested: Segment = {
      ...EMPTY_SEGMENT,
      rules: [
        { field: "is_reachable", op: "is_true" },
        { match: "any", rules: [{ field: "order_count", op: "gte", value: 2 }] },
      ],
    };
    render(<Harness initial={nested} />);

    // The rule inside the nested group is "Rule 1" of that group.
    const groups = screen.getAllByRole("group", { name: "Rule 1" });
    const inner = groups[groups.length - 1];
    expect(inner).toBeDefined();
    await user.click(
      within(inner as HTMLElement).getByRole("button", { name: /Remove this rule/u }),
    );

    // The group went with it: an empty NESTED group is a 422, never a document to send.
    expect(rulesOf(latest)).toEqual([{ field: "is_reachable", op: "is_true" }]);
  });
});

describe("SegmentBuilder — keyboard", () => {
  it("adds a rule from the keyboard and puts the focus in it", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const add = screen.getByRole("button", { name: "Add rule" });
    add.focus();
    await user.keyboard("{Enter}");

    expect(fieldSelect()).toHaveFocus();
  });

  it("returns the focus to Add rule when a rule is deleted, rather than to the document", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ ...EMPTY_SEGMENT, rules: [{ field: "is_reachable", op: "is_true" }] }} />);

    await user.click(screen.getByRole("button", { name: "Remove this rule: Rule 1" }));

    expect(screen.getByRole("button", { name: "Add rule" })).toHaveFocus();
  });

  it("reaches every control of a rule by tabbing, in reading order", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ ...EMPTY_SEGMENT, rules: [{ field: "order_count", op: "gte", value: 2 }] }} />);

    fieldSelect().focus();
    await user.tab();
    expect(conditionSelect()).toHaveFocus();
    await user.tab();
    expect(within(rule()).getByLabelText("Rule 1: Number")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Remove this rule: Rule 1" })).toHaveFocus();
  });

  it("changes a group's connective from the keyboard", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ ...EMPTY_SEGMENT, rules: [{ field: "is_reachable", op: "is_true" }] }} />);

    const any = screen.getByRole("button", { name: "Any" });
    any.focus();
    await user.keyboard("{Enter}");

    expect(latest.match).toBe("any");
  });
});
