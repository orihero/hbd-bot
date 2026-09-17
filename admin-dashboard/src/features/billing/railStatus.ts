/**
 * Payme's own reply codes, named at the presentation edge.
 *
 * A pure module — no clock, no fetch, no React — so the journal's vocabulary is testable
 * against a fixture and every word on a call row is traceable to one line here.
 */

/**
 * JSON-RPC reply codes Payme is known to use, named AT THE PRESENTATION EDGE ONLY.
 *
 * The raw integer is always rendered beside the name, and a code that is not here renders as
 * itself. That is not a fallback, it is the design: this is the rail's vocabulary and they
 * extend it without asking us, so a closed mapping that blanked an unknown code would hide
 * exactly the row an incident is about. There is no VARCHAR mirror and no database enum for
 * this, and there must not be one.
 *
 * Success and fault are told apart BY SIGN — `0` is success, every protocol fault is negative
 * — and there is no second column anywhere in the system that says so.
 */
const REPLY_CODE_NAMES: Readonly<Record<number, string>> = {
  0: "ok",
  [-32300]: "transport",
  [-32700]: "parse",
  [-32600]: "invalid request",
  [-32601]: "method not found",
  [-32602]: "invalid params",
  [-32504]: "not authorised",
  [-31001]: "wrong amount",
  [-31003]: "transaction not found",
  [-31007]: "cannot cancel",
  [-31008]: "cannot perform",
  [-31050]: "unknown account",
  [-31051]: "unknown account",
  [-31052]: "unknown account",
  [-31053]: "unknown account",
  [-31054]: "unknown account",
  [-31055]: "unknown account",
  [-31099]: "unknown account",
};

/** The protocol's own name for a reply code, or `null` when we have never seen it named. */
export function replyCodeName(code: number): string | null {
  return REPLY_CODE_NAMES[code] ?? null;
}

/** `0` is success and every fault is negative. One predicate, so no screen invents a second. */
export function isFaultReply(code: number): boolean {
  return code !== 0;
}
