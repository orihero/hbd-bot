/**
 * Reading a `StagePlanView` the way §11.2 and the schema require.
 *
 * Three facts drive everything here, and every one of them is a way to get the timeline
 * wrong:
 *
 * 1. **`stages` always carries all ELEVEN `PipelineStage` members**, in `STAGE_ORDER`.
 *    `scheduledStageCount` is how many this deployment actually plans — **9 by default,
 *    because `greetings_per_kit=0` is shipped**. The unplanned remainder is GHOSTED, not
 *    dropped: an operator must be able to see that two stages exist and were never going to
 *    run. Read `scheduledStageCount`, never `stages.length`.
 * 2. **`"not_observed"` means NO RECORD, never "did not run".** Seven of the eleven stages
 *    write no attempt row at all, so `not_observed` is the normal, healthy answer for most
 *    of the plan. Rendering it as a failure or as a gap is the single most misleading thing
 *    this component could do.
 * 3. **`isInferred` is always `true`.** The plan is reconstructed from attempt rows. That
 *    belongs on screen as a caption, not hidden as a debug flag.
 */

import type { PipelineStage, StageOutcome } from "@/api";
import type { StagePlanView, StageStatusView } from "@/api";

/** One stage as the timeline draws it. */
export interface StageEntry {
  readonly status: StageStatusView;
  readonly stage: PipelineStage;
  readonly outcome: StageOutcome;
  /**
   * Whether this deployment planned to run the stage at all. `false` renders ghosted —
   * present, dimmed, and captioned, never omitted.
   */
  readonly isPlanned: boolean;
}

/**
 * Which stages this deployment planned.
 *
 * The wire gives a COUNT, not a set, so the unplanned members have to be identified. They
 * are the greeting stages: `scheduledStageCount` drops below `stages.length` exactly when
 * `greetings_per_kit=0`, and `isGreetingStage` is the flag the serializer sets for that
 * reason. When more stages are scheduled than there are greeting stages to unschedule, the
 * count wins and the remainder stays planned — a future deployment that unschedules
 * something else must not silently ghost the wrong row.
 */
export function planEntries(plan: StagePlanView): readonly StageEntry[] {
  const unplannedCount = Math.max(0, plan.stages.length - plan.scheduledStageCount);
  let remaining = unplannedCount;
  // Ghost from the END of the list, so a plan that unschedules one of two greeting stages
  // ghosts the later one rather than an arbitrary one.
  const ghosted = new Set<number>();
  for (let index = plan.stages.length - 1; index >= 0 && remaining > 0; index -= 1) {
    if (plan.stages[index]?.isGreetingStage === true) {
      ghosted.add(index);
      remaining -= 1;
    }
  }
  return plan.stages.map((status, index) => ({
    status,
    stage: status.stage,
    outcome: status.outcome,
    isPlanned: !ghosted.has(index),
  }));
}

/** The first stage that failed, or `null`. This is the one the timeline highlights. */
export function failedStage(plan: StagePlanView): StageStatusView | null {
  return plan.stages.find((status) => status.outcome === "failed") ?? null;
}

/**
 * The colour for a stage node.
 *
 * A ghosted stage is drawn in the muted colour, not in a status colour: it has no status.
 * `not_observed` is drawn in `--ink-muted` for the same reason — there is no record, and a
 * status colour would be a claim.
 *
 * The muted colour is `--ink-muted`, not the policed `--ink-rule`, because
 * `<PipelineTimeline>` paints the stage's outcome LABEL with whatever this returns.
 * `--ink-muted` clears 1.4.3's 4.5:1 on every ground of every cell (4.88:1 at its worst in
 * light, 4.73:1 in dark); `--ink-rule` is 2.94:1 at its ceiling and clears no bar at all.
 * See `tokenContrast.test.ts`, which measures every `--ink-rule` in `src/` as text unless a
 * waiver there says why it is not.
 */
export function stageOutcomeColorVar(outcome: StageOutcome, isPlanned = true): string {
  if (!isPlanned) return "var(--ink-muted)";
  switch (outcome) {
    case "succeeded":
      return "var(--pg-succeeded)";
    case "failed":
      return "var(--pg-failed)";
    case "skipped":
      return "var(--pg-skipped)";
    case "not_observed":
      return "var(--ink-muted)";
  }
}

/**
 * Glyph + colour, never colour alone (§11.3) — a stage node has to survive greyscale.
 *
 * `·` for `not_observed` reads as "nothing was written here", which is exactly what it
 * means; `✓`, `✗` and `⊘` match the status pill's vocabulary so the two never disagree.
 */
export function stageOutcomeGlyph(outcome: StageOutcome, isPlanned = true): string {
  if (!isPlanned) return "◌";
  switch (outcome) {
    case "succeeded":
      return "✓";
    case "failed":
      return "✗";
    case "skipped":
      return "⊘";
    case "not_observed":
      return "·";
  }
}

/**
 * The words for an outcome. `not_observed` must never read as "did not run" (see the
 * module docstring) — "no record" is the honest phrasing and the one used everywhere.
 */
export function stageOutcomeLabel(outcome: StageOutcome, isPlanned = true): string {
  if (!isPlanned) return NOT_PLANNED_LABEL;
  switch (outcome) {
    case "succeeded":
      return "succeeded";
    case "failed":
      return "failed";
    case "skipped":
      return "skipped";
    case "not_observed":
      return NO_RECORD_LABEL;
  }
}

/**
 * §11.2 pins "not enabled in this deployment" for an absent timeline SOURCE and is silent
 * on the wording for an unplanned STAGE. These two are deliberately close to it: the
 * operator's question is the same one — is this missing because nothing happened, or
 * because it was never going to happen — and the answer should read the same way.
 */
export const NOT_PLANNED_LABEL = "not planned in this deployment";

/** `"not_observed"` is an absent RECORD, not an absent RUN. */
export const NO_RECORD_LABEL = "no record";

/** The caption under an inferred plan. `isInferred` is always `true` on this build. */
export const INFERRED_PLAN_LABEL = "inferred from attempt rows";

/**
 * `isConclusive: false` means the evidence does not settle whether the greeting stages ran.
 * It is a caption, not a warning badge — the plan is still the best available reading.
 */
export const INCONCLUSIVE_PLAN_LABEL = "greeting evidence is inconclusive";
