/**
 * The journal's reply-code vocabulary.
 *
 * Two rules and nothing else: success and fault are told apart by SIGN, and a code Payme adds
 * tomorrow renders as its own integer rather than as a blank.
 */

import { describe, expect, it } from "vitest";

import { isFaultReply, replyCodeName } from "./railStatus";

describe("reply codes", () => {
  it("tells success from fault by SIGN and by nothing else", () => {
    expect(isFaultReply(0)).toBe(false);
    expect(isFaultReply(-31050)).toBe(true);
    expect(isFaultReply(-32504)).toBe(true);
  });

  it("names the codes it knows and returns null for one Payme adds tomorrow", () => {
    expect(replyCodeName(0)).toBe("ok");
    expect(replyCodeName(-31003)).toBe("transaction not found");
    // The raw integer is always rendered beside the name, so an unnamed code still shows.
    expect(replyCodeName(-31234)).toBeNull();
  });
});
