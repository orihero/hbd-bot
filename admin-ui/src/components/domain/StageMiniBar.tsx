/**
 * `<StageMiniBar>` — the whole stage plan as one row-height strip.
 *
 * `<PipelineTimeline>` is the top third of a detail screen; this is the same eleven facts
 * inside a 40px table row, so an operator scanning `/orders` can see *where* things are
 * dying without opening each one.
 *
 * It obeys the same three rules as the timeline: eleven segments always, the unplanned ones
 * ghosted rather than dropped, and `not_observed` drawn as an absent record rather than as
 * a failure. It carries a `title` naming each stage's outcome, because a 6px segment cannot
 * carry a word — the strip is a scanning aid, and the timeline is the answer.
 */

import type { ReactElement } from "react";

import type { StagePlanView } from "@/api";
import { cn, humaniseEnum } from "@/lib";

import {
  planEntries,
  stageOutcomeColorVar,
  stageOutcomeLabel,
} from "./stagePlan";

export interface StageMiniBarProps {
  plan: StagePlanView;
  className?: string | undefined;
}

export function StageMiniBar({ plan, className }: StageMiniBarProps): ReactElement {
  const entries = planEntries(plan);
  const summary = entries
    .map(
      (entry) =>
        `${humaniseEnum(entry.stage)}: ${stageOutcomeLabel(entry.outcome, entry.isPlanned)}`,
    )
    .join("\n");

  return (
    <span
      data-testid="stage-mini-bar"
      role="img"
      aria-label={summary}
      title={summary}
      className={cn("inline-flex h-2 items-stretch gap-[2px]", className)}
    >
      {entries.map((entry) => (
        <span
          key={entry.stage}
          data-testid="stage-mini-segment"
          data-stage={entry.stage}
          data-outcome={entry.outcome}
          data-planned={entry.isPlanned ? "true" : "false"}
          className={cn("w-2 rounded-4xs", entry.isPlanned ? "" : "opacity-70")}
          style={{
            backgroundColor: entry.isPlanned
              ? stageOutcomeColorVar(entry.outcome, true)
              : "transparent",
            // A ghosted segment is an outline, not a fill: it must read as "there is a
            // stage here that was never scheduled", not as a stage in some pale state.
            //
            // The outline is `--edge`, the one border in this design that carries meaning,
            // and it is deliberately NOT the policed `--ink-rule` the old `--fg-3` mapped
            // to. Measured: `--edge` is 3.08:1 on `--surface` and 3.22:1 on `--surface-card`
            // in light, 3.35:1 and 3.62:1 in dark — so on the two grounds a table row
            // normally sits on it CLEARS 1.4.11's 3:1 outright, rather than needing a waiver
            // to be excused from it. On a HOVERED row (`--surface-control-hover`) it falls to
            // 2.61:1 light / 2.79:1 dark and does not; that case rests on the same 1.4.11
            // decoration exemption the old `--fg-3` outline always did, because the strip is
            // `role="img"` with an `aria-label` naming every stage and its outcome in words
            // and `<PipelineTimeline>` says the same thing at full size. Nothing here is
            // carried by the outline alone. The point of the swap is that the exemption is
            // now a fallback for one ground instead of the whole justification, and that at
            // 8px wide `--ink-rule`'s 1.75:1 was genuinely invisible.
            boxShadow: entry.isPlanned ? undefined : "inset 0 0 0 1px var(--edge)",
          }}
        />
      ))}
    </span>
  );
}
