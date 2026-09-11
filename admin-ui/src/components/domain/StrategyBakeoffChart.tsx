/**
 * `<StrategyBakeoffChart>` — the bars behind "what should `BAYRAM_NAME_CANDIDATE_ORDER` be?"
 *
 * §11.2 gives `/generations/names` exactly that question, and §8.3 says why it matters:
 * `name_candidate_order` is the flagship live-editable field, and the README and
 * `config.py` both say a bake-off result is applied by REORDERING it, never by editing
 * code. This chart is the evidence for that reorder.
 *
 * Design decisions, each one load-bearing:
 *
 * - **Horizontal bars, in `NAME_STRATEGY_VALUES` order.** The declaration order is the
 *   render order, so the chart does not re-rank itself between polls; an operator comparing
 *   two screenshots must be looking at the same rows in the same places. Sorting by rate
 *   would make the *position* of a bar carry meaning that changes under them. The server
 *   sends the rows best-first; that ordering is what the suggested candidate order is built
 *   from, and it is deliberately not what the chart draws.
 * - **One series, one hue, no legend.** dataviz's rule: a single series needs no legend box
 *   — the title names it — and colour here encodes nothing, because the LENGTH is the datum.
 *   The categorical ramp's first slot (`--c-1`) is used rather than a status colour, because
 *   a verification rate is not a delivery outcome and green must keep meaning one thing
 *   (§11.3).
 * - **Zero attempts is not zero percent.** A strategy nothing ran renders "no attempts" and
 *   no bar. `verificationRate` is `0` there arithmetically, and drawing that bar would put
 *   a strategy at the bottom of a bake-off it never entered — the same class of wrong
 *   number as a 0% success rate on a quiet morning. The windowed endpoint OMITS such a
 *   strategy from its array entirely, so the "no attempts" row is rendered from the gap.
 * - **Every bar is directly labelled** with its rate and its denominator. A rate without a
 *   denominator is how "100%" turns out to mean one attempt.
 * - **The near-threshold count rides on the row that owns it.** A strategy whose wins are
 *   all decided inside the band is not the same evidence as one that clears the threshold
 *   outright, and the whole-screen figure cannot say which strategy the cliff belongs to.
 *   It is a second glyph and a second number, never a second colour: the bar keeps meaning
 *   one thing.
 */

import type { ReactElement } from "react";

import { NAME_STRATEGY_VALUES, type StrategyOutcomeView } from "@/api";
// The module, not the barrel — see the note in `SimilarityHistogram.tsx`.
import { chartToneVar } from "@/components/data/chartTokens";
import { cn, formatInteger, formatRate, humaniseEnum } from "@/lib";

/**
 * What a row needs to be drawn.
 *
 * `StrategyOutcomeView` (from `/metrics/name-strategies`) satisfies it, and
 * `StrategyAnalysisView` (from `/metrics/name-analytics`) is a structural superset that
 * satisfies it too and carries the two optional extras. One chart, both endpoints, no
 * adapter — which is what keeps `/generations` and `/generations/names` drawing the same
 * bars from different reads.
 */
export interface BakeoffRow {
  readonly strategy: StrategyOutcomeView["strategy"];
  readonly attempts: number;
  readonly verified: number;
  readonly verificationRate: number;
  /** Scored attempts — present only on the analytics read. */
  readonly scored?: number | undefined;
  /** Within the band of the threshold. `null` when the deployment publishes no threshold. */
  readonly nearThreshold?: number | null | undefined;
}

export interface StrategyBakeoffChartProps {
  rows: readonly BakeoffRow[];
  className?: string | undefined;
}

/** The glyph that marks the cliff count, so it is not read as another rate. */
export const NEAR_THRESHOLD_GLYPH = "◎";

export function StrategyBakeoffChart({
  rows,
  className,
}: StrategyBakeoffChartProps): ReactElement {
  const byStrategy = new Map(rows.map((row) => [row.strategy, row]));

  return (
    <section
      data-testid="strategy-bakeoff-chart"
      aria-label="name verification rate by strategy"
      className={cn("flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card", className)}
    >
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="type-h2 text-ink">verification rate by strategy</h2>
        <span className="type-caption text-ink-muted">candidate order</span>
      </header>

      <ol className="flex flex-col gap-2">
        {NAME_STRATEGY_VALUES.map((strategy) => {
          const row = byStrategy.get(strategy);
          const hasAttempts = row !== undefined && row.attempts > 0;
          const near = row?.nearThreshold ?? null;
          return (
            <li
              key={strategy}
              data-testid="bakeoff-row"
              data-strategy={strategy}
              data-attempts={String(row?.attempts ?? 0)}
              className="flex flex-col gap-1"
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="type-body-sm text-ink">{humaniseEnum(strategy)}</span>
                <span className="type-body-sm num text-ink-muted">
                  {hasAttempts
                    ? `${formatRate(row.verificationRate)} · ${formatInteger(row.verified)}/${formatInteger(row.attempts)}`
                    : NO_ATTEMPTS_LABEL}
                </span>
              </span>
              <span className="block h-2 rounded-full bg-surface-control-hover">
                {hasAttempts ? (
                  <span
                    data-testid="bakeoff-bar"
                    className="block h-2 rounded-full"
                    style={{
                      width: `${String(Math.max(0, Math.min(100, row.verificationRate * 100)))}%`,
                      backgroundColor: chartToneVar("c-1"),
                    }}
                  />
                ) : null}
              </span>
              {hasAttempts && near !== null && near > 0 ? (
                <span
                  data-testid="bakeoff-near-threshold"
                  className="type-caption num text-ink-muted"
                  title={nearThresholdTitle(near)}
                >
                  <span aria-hidden="true">{NEAR_THRESHOLD_GLYPH}</span>{" "}
                  {`${formatInteger(near)} decided inside the band`}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function nearThresholdTitle(near: number): string {
  return `${formatInteger(near)} of this strategy's scored attempts sit close enough to the threshold that moving it would change their verdict`;
}

/**
 * A strategy with no attempts has no rate. Not "0%" — nothing ran, and the two readings
 * lead to opposite decisions about the candidate order.
 */
export const NO_ATTEMPTS_LABEL = "no attempts";
