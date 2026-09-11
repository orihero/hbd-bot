/**
 * The two numbers `/generations` and `/generations/names` exist to produce.
 *
 * §11.2 gives `/generations` the dominant signal "overall verification rate" and
 * `/generations/names` the question "what should `BAYRAM_NAME_CANDIDATE_ORDER` be?".
 * `config.py` answers the second's shape: `name_candidate_order` is `NoDecode` with a
 * comma-separated env spelling, and its own docstring says **"a bake-off result is applied
 * by reordering this list in the environment — never by editing code"**. So the screen's
 * output is a candidate order an operator can paste, not prose.
 *
 * Both are computed from `GET /api/metrics/name-strategies`, which is one `GROUP BY` over
 * `generation_attempts` where `name_candidate_strategy IS NOT NULL AND is_name_verified IS
 * NOT NULL` — rows where verification did not run are excluded from BOTH counts, so summing
 * the groups gives the true overall rate and not a rate diluted by a disabled verifier.
 */

import { NAME_STRATEGY_VALUES, type NameStrategy, type StrategyOutcomeView } from "@/api";

export interface VerificationTotals {
  /** Attempts where verification actually ran. */
  readonly attempts: number;
  readonly verified: number;
  /**
   * `verified / attempts`, or `null` when nothing ran.
   *
   * `null`, never `0`: the same rule `deliveryViewSchema` states for `successRate`. A 0%
   * verification rate reads as "the verifier is broken", and "nothing has been verified yet"
   * is a different fact with a different next action.
   */
  readonly rate: number | null;
}

export function overallVerification(
  rows: readonly StrategyOutcomeView[],
): VerificationTotals {
  let attempts = 0;
  let verified = 0;
  for (const row of rows) {
    attempts += row.attempts;
    verified += row.verified;
  }
  return { attempts, verified, rate: attempts === 0 ? null : verified / attempts };
}

/**
 * The candidate order the bake-off argues for.
 *
 * Strategies that ran are ranked by verification rate, ties broken by volume — the same tie
 * break `strategy_outcomes` applies server-side, so one lucky success never outranks four
 * hundred attempts. Strategies that ran NOTHING keep their declared position and go last:
 * their `verificationRate` is arithmetically `0`, and ranking them on it would demote an
 * orthography that was simply never tried, which is the opposite of what the bake-off
 * measures.
 */
export function suggestedCandidateOrder(
  rows: readonly StrategyOutcomeView[],
): readonly NameStrategy[] {
  const byStrategy = new Map(rows.map((row) => [row.strategy, row]));
  const ranked = NAME_STRATEGY_VALUES.filter((strategy) => {
    const row = byStrategy.get(strategy);
    return row !== undefined && row.attempts > 0;
  }).sort((left, right) => {
    const a = byStrategy.get(left);
    const b = byStrategy.get(right);
    if (a === undefined || b === undefined) return 0;
    if (a.verificationRate !== b.verificationRate) return b.verificationRate - a.verificationRate;
    return b.attempts - a.attempts;
  });
  const untried = NAME_STRATEGY_VALUES.filter((strategy) => !ranked.includes(strategy));
  return [...ranked, ...untried];
}

/** The environment variable a bake-off result is applied to. */
export const CANDIDATE_ORDER_ENV = "BAYRAM_NAME_CANDIDATE_ORDER";

/** `canonical,stripped,ascii,…` — `_split_csv` in `config.py` is what reads this back. */
export function candidateOrderValue(order: readonly NameStrategy[]): string {
  return order.join(",");
}

/** True when at least one strategy has attempts — the bake-off has something to say. */
export function hasBakeoffEvidence(rows: readonly StrategyOutcomeView[]): boolean {
  return rows.some((row) => row.attempts > 0);
}
