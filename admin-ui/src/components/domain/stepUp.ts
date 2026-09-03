/**
 * The step-up seam — how a `403 STEP_UP_REQUIRED` becomes a re-authentication and back again.
 *
 * ## This is the first place in the app where a grant is worth anything
 *
 * Through Phase 1, `POST /api/auth/step-up` worked end to end — it re-verified the password,
 * metered, refunded, wrote `STEP_UP_SUCCESS` and persisted `admin_sessions.step_up_scope` —
 * and **no route ever read that column back**. The only `STEP_UP_REQUIRED` a Phase 1 screen
 * could provoke came from a router guard (`check_role`), which holds no subject and therefore
 * never consults a grant: re-authenticating would not have changed the answer. That is why no
 * Phase 1 screen called it, and why this file did not exist.
 *
 * `POST /api/reveal` is the first handler that calls `deps.enforce_step_up`, so its 403 is the
 * first one in the product with a remedy behind it. Phases 3–7 add more — `order.retry`,
 * `order.force_deliver`, `user.block`, `moderation.decide`, `user.purge`, `config.write`,
 * `order.evidence_export`, `audit.export`, `admin.manage` — and every one of them refuses the
 * same way and recovers the same way. **Reuse this and `<StepUpPrompt>` rather than writing a
 * second re-auth form**: two of them will disagree about the scope spelling, and a scope
 * mismatch is a permanent, silent 403 that only a test driving the real route catches.
 *
 * ## The contract, in three facts
 *
 * 1. The refusal names its own remedy. `deps.enforce_step_up` raises with
 *    `details.stepUpAction` (a bare `StepUpAction`, e.g. `"reveal"`) and `details.subjectId`
 *    (the canonical `str(uuid)`). `stepUpTargetOf` reads exactly those two keys.
 * 2. **The subject id must be byte-identical** on both sides. `check_step_up` compares the
 *    composed `"<action>:<subjectId>"` scope WHOLE, so a braced or upper-case spelling on one
 *    side is a mismatch nobody can debug from the 403. Take the id from the failure's details
 *    when they carry one, never from a re-formatting of your own.
 * 3. A grant is **not single-use**. Nothing clears `step_up_scope`, so within
 *    `adminStepUpGraceSeconds` (default 300, max 900) the same grant admits the next request
 *    for the same action and subject — including page two of a paged reveal. The budget, not
 *    the step-up, is what bounds volume; do not build a UI that promises otherwise.
 */

import { ZERO_GRACE_STEP_UP_ACTIONS, type ApiFailure, type StepUpAction } from "@/api";

/** The two halves of a grant: what to re-authenticate for, and on what. */
export interface StepUpTarget {
  readonly action: StepUpAction;
  /** Byte-identical to the id the refusing handler compared against. */
  readonly subjectId: string;
}

const STEP_UP_ACTIONS: readonly string[] = [
  "reveal",
  "order.force_deliver",
  "user.block",
  "moderation.decide",
  "user.purge",
  "config.write",
  "order.evidence_export",
  "audit.export",
  "admin.manage",
];

function asStepUpAction(value: unknown): StepUpAction | null {
  return typeof value === "string" && STEP_UP_ACTIONS.includes(value)
    ? (value as StepUpAction)
    : null;
}

/** Whether this failure is the one a re-authentication can fix. */
export function isStepUpRequired(failure: ApiFailure | null): boolean {
  return failure !== null && failure.code === "STEP_UP_REQUIRED";
}

/**
 * The grant to ask for, read off the refusal itself.
 *
 * `null` for any 403 that is not a step-up, and — deliberately — for a `STEP_UP_REQUIRED`
 * that carries no `details`. That second case is the ROUTER-level refusal, which reports a
 * cell's step-up requirement without ever consulting a grant: re-authenticating cannot change
 * its answer, so offering the operator a password box would be a loop they cannot win. Render
 * it as the refusal it is.
 */
export function stepUpTargetOf(failure: ApiFailure | null): StepUpTarget | null {
  if (!isStepUpRequired(failure) || failure === null) return null;
  const action = asStepUpAction(failure.details?.["stepUpAction"]);
  const subjectId = failure.details?.["subjectId"];
  if (action === null || typeof subjectId !== "string" || subjectId === "") return null;
  return { action, subjectId };
}

/** Whether two targets name the same grant, so a retry knows it has the one it needed. */
export function isSameTarget(a: StepUpTarget, b: StepUpTarget): boolean {
  return a.action === b.action && a.subjectId === b.subjectId;
}

/**
 * How long a fresh grant will last, in seconds, or `0` for the two zero-grace actions.
 *
 * §12.1 T2 gives `user.purge` and `config.write` a window of zero — `expiresAt === grantedAt`
 * — so a UI must not promise a window it does not have. `reveal` uses the configured grace.
 */
export function grantWindowS(action: StepUpAction, graceS: number): number {
  return ZERO_GRACE_STEP_UP_ACTIONS.includes(action) ? 0 : graceS;
}

/** The sentence under the password box, in the operator's terms rather than the matrix's. */
export const STEP_UP_EXPLANATION =
  "§12.2 marks this action A+S: holding the permission is not enough, and the panel needs your password again for this subject specifically.";

/** Said when the grant will not outlive the request it authorises. */
export const ZERO_GRACE_NOTE =
  "This action's grant expires the instant it is issued — it authorises exactly this one request.";

/** Said when it will. Not a promise of unlimited use; a statement of what the server does. */
export function graceNote(windowS: number): string {
  if (windowS <= 0) return ZERO_GRACE_NOTE;
  const minutes = Math.round(windowS / 60);
  const window = minutes >= 1 ? `${String(minutes)} min` : `${String(windowS)}s`;
  return `The grant covers this action on this subject for ${window}. It is not single-use — the reveal budget, not the grant, is what bounds how much is disclosed.`;
}
