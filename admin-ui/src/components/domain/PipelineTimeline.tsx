/**
 * `<PipelineTimeline>` — §11.2's answer to "where is it, or exactly where did it die?"
 *
 * It sits across the top third of `/orders/:id` and is driven by `stagePlan`. Four things
 * it must get right, each of which is a way an operator ends up with a wrong belief:
 *
 * 1. **Nine stages by default, not eleven.** `greetings_per_kit=0` is shipped, so the two
 *    greeting stages are unplanned. They are GHOSTED — dimmed, dashed, captioned "not
 *    planned in this deployment" — never dropped. Dropping them makes an operator hunt for
 *    a greeting stage that was never scheduled; showing them as ordinary gaps makes them
 *    look like a failure.
 * 2. **The failed stage is highlighted with its error code and retryability.** That is the
 *    whole point of the screen: not "it failed" but "it failed HERE, with THIS code, and
 *    retrying is/is not worth anything".
 * 3. **`not_observed` means no record, not "did not run".** Seven of the eleven stages
 *    write no attempt row, so most of a perfectly healthy plan is `not_observed`.
 * 4. **The plan is inferred.** `isInferred` is always `true`; it belongs on screen as a
 *    caption. An operator who reads this as a log will believe an absence is evidence.
 */

import type { ReactElement } from "react";

import type { StagePlanView } from "@/api";
import { cn, formatInteger, humaniseEnum } from "@/lib";

import { ErrorCodeBadge } from "./ErrorCodeBadge";
import {
  INCONCLUSIVE_PLAN_LABEL,
  INFERRED_PLAN_LABEL,
  NOT_PLANNED_LABEL,
  planEntries,
  stageOutcomeColorVar,
  stageOutcomeGlyph,
  stageOutcomeLabel,
} from "./stagePlan";

export interface PipelineTimelineProps {
  plan: StagePlanView;
  className?: string | undefined;
}

export function PipelineTimeline({ plan, className }: PipelineTimelineProps): ReactElement {
  const entries = planEntries(plan);
  const plannedCount = entries.filter((entry) => entry.isPlanned).length;

  return (
    <section
      data-testid="pipeline-timeline"
      aria-label="pipeline stages"
      // A card in this language is `--surface-card` + `--shadow-card` at a 28px radius and
      // nothing else. The border it used to carry is gone; the separation is the shadow.
      className={cn("rounded-card bg-surface-card p-card shadow-card", className)}
    >
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="type-h2 text-ink">pipeline</h2>
        <p className="type-body-sm text-ink-muted">
          <span className="num" data-testid="scheduled-stage-count">
            {formatInteger(plannedCount)}
          </span>
          {" of "}
          <span className="num">{formatInteger(entries.length)}</span>
          {" stages scheduled · "}
          {plan.isInferred ? INFERRED_PLAN_LABEL : "recorded"}
          {` · greeting evidence ${plan.greetingEvidence}`}
          {plan.isConclusive ? "" : ` · ${INCONCLUSIVE_PLAN_LABEL}`}
        </p>
      </header>

      <ol className="flex flex-wrap items-stretch gap-2">
        {entries.map((entry) => {
          const color = stageOutcomeColorVar(entry.outcome, entry.isPlanned);
          const isFailed = entry.isPlanned && entry.outcome === "failed";
          return (
            <li
              key={entry.stage}
              data-testid="pipeline-stage"
              data-stage={entry.stage}
              data-outcome={entry.outcome}
              data-planned={entry.isPlanned ? "true" : "false"}
              className={cn(
                "flex min-w-[7.5rem] flex-1 flex-col gap-1 rounded-2xl px-3 py-2.5",
                // A planned stage carries a control ground instead of a 1px box. A ghosted
                // one keeps its dashed outline: "there is a stage here and it was never
                // scheduled" is a different statement from "this stage is pale", and a
                // filled-but-faint tile says the second thing.
                entry.isPlanned
                  ? "bg-surface-control"
                  : "border border-dashed border-hairline-strong bg-transparent opacity-60",
                isFailed && "shadow-ring-error",
              )}
            >
              <span className="flex items-baseline gap-1.5">
                <span aria-hidden="true" style={{ color }} className="leading-none">
                  {stageOutcomeGlyph(entry.outcome, entry.isPlanned)}
                </span>
                <span className="type-body-sm text-ink">{humaniseEnum(entry.stage)}</span>
              </span>
              <span className="type-caption" style={{ color }}>
                {stageOutcomeLabel(entry.outcome, entry.isPlanned)}
              </span>
              {entry.isPlanned && entry.status.attemptCount > 0 ? (
                <span className="type-body-sm num text-ink-muted">
                  {formatInteger(entry.status.attemptCount)}
                  {entry.status.attemptCount === 1 ? " attempt" : " attempts"}
                  {entry.status.failedAttemptCount > 0
                    ? `, ${formatInteger(entry.status.failedAttemptCount)} failed`
                    : ""}
                </span>
              ) : null}
              {isFailed ? (
                <ErrorCodeBadge
                  code={entry.status.errorCode}
                  isRetryable={entry.status.isRetryable}
                  className="mt-1"
                />
              ) : null}
            </li>
          );
        })}
      </ol>

      {plannedCount < entries.length ? (
        <p className="type-body-sm mt-4 text-ink-muted">
          {`Ghosted stages are ${NOT_PLANNED_LABEL} — they were never scheduled, so their absence is not a gap.`}
        </p>
      ) : null}
    </section>
  );
}
