/**
 * `RevealBudgetMeter` — what is left of §12.3's two ceilings, and what this reveal will spend.
 *
 * §11.4 puts the requirement on `RevealDialog` and this is the component that discharges it:
 * the cost of a reveal is shown **against the remaining budget before the operator confirms**.
 * A dialog that reveals first and reports cost after has missed the point — the 429 arrives
 * halfway through a support call, on the third of five records somebody is reading out.
 *
 * ## Three things it must never do
 *
 * **Never render `null` as zero.** A counter the last response did not touch, or one no
 * response has reported in this window, is "not measured yet" — with the ceiling beside it so
 * the number is still useful. "0 left" for "not asked" stops an operator doing legitimate
 * work, which is the one failure mode a budget meter can cause on its own.
 *
 * **Never colour alone** (§11.3). Every band carries a glyph and a word as well as a hue, and
 * the word is in the accessible name, so the meter survives greyscale, a projector and the
 * operators who cannot separate the amber from the green. The bar is `aria-hidden`; it
 * duplicates the number, it does not carry it.
 *
 * **Never invent a figure.** There is no endpoint that answers "what is left" (§12.3 promises
 * `/metrics/reveals` and no phase mounts it), so everything here comes from the last
 * `POST /api/reveal` answer this tab received. It is not decremented locally: the counter is a
 * Redis key shared with every other tab and session on the same account, and a locally-guessed
 * figure would be wrong in precisely the case the budget exists to detect.
 */

import type { ReactElement } from "react";

import type { RevealBudgetScope } from "@/api";
import { useNow } from "@/components/util/hooks";
import { cn, formatInteger } from "@/lib";

import {
  budgetBand,
  budgetBandColorVar,
  BUDGET_BAND_GLYPH,
  BUDGET_BAND_LABEL,
  currentReading,
  formatResetIn,
  remainingAfter,
  REVEAL_BUDGET_LABELS,
  REVEAL_BUDGET_UNITS,
  REVEAL_BUDGET_WINDOW_LABELS,
  REVEAL_BUDGET_WINDOW_S,
  secondsToReset,
  type BudgetBand,
  type RevealBudgetSnapshot,
} from "./revealBudget";
import { FREE, type RevealCost } from "./revealFields";

/** The ceilings half of the meter. `null` on either while `/api/config` has not answered. */
export interface RevealCeilingsInput {
  readonly records: number | null;
  readonly conversations: number | null;
}

export interface RevealBudgetMeterProps {
  readonly budget: RevealBudgetSnapshot;
  readonly ceilings: RevealCeilingsInput;
  /** What the pending reveal would charge. `FREE` when nothing is selected yet. */
  readonly cost?: RevealCost | undefined;
  /** Pin the clock. Tests pass it; production lets the component tick its own reset counter. */
  readonly now?: number | undefined;
  readonly className?: string | undefined;
}

/** Re-read the clock every half minute: a reset countdown is useful to the minute, not the ms. */
const TICK_MS = 30_000;

export function RevealBudgetMeter({
  budget,
  ceilings,
  cost = FREE,
  now,
  className,
}: RevealBudgetMeterProps): ReactElement {
  const ticked = useNow(TICK_MS, now === undefined);
  const nowMs = now ?? ticked;

  // The conversation ceiling is only drawn when it is in play — a name reveal never reads it,
  // and a row saying "20 a day, untouched" beside a reveal that cannot touch it is noise on
  // the one screen where every line has to earn its place.
  const showConversations =
    cost.conversations > 0 || budget.conversations.remaining !== null;

  return (
    <div
      data-testid="reveal-budget-meter"
      aria-label="Reveal budget"
      className={cn("flex flex-col gap-3 rounded-2xl bg-surface-control p-4", className)}
    >
      <BudgetRow
        scope="records"
        reading={currentReading(budget.records, "records", nowMs)}
        ceiling={ceilings.records}
        cost={cost.records}
        nowMs={nowMs}
      />
      {showConversations ? (
        <BudgetRow
          scope="conversations"
          reading={currentReading(budget.conversations, "conversations", nowMs)}
          ceiling={ceilings.conversations}
          cost={cost.conversations}
          nowMs={nowMs}
        />
      ) : null}
    </div>
  );
}

function BudgetRow({
  scope,
  reading,
  ceiling,
  cost,
  nowMs,
}: {
  readonly scope: RevealBudgetScope;
  readonly reading: {
    readonly remaining: number | null;
    readonly measuredAt: number | null;
  };
  readonly ceiling: number | null;
  readonly cost: number;
  readonly nowMs: number;
}): ReactElement {
  const band: BudgetBand = budgetBand(reading, { cost, ceiling });
  const after = remainingAfter(reading, cost);
  const resetsInS = secondsToReset(nowMs, REVEAL_BUDGET_WINDOW_S[scope]);
  const color = budgetBandColorVar(band);

  return (
    <div
      data-testid="reveal-budget-row"
      data-scope={scope}
      data-band={band}
      className="flex flex-col gap-1"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        {/* Glyph, word, colour — three channels for one fact (§11.3). */}
        <span aria-hidden="true" className="type-body-sm" style={{ color }}>
          {BUDGET_BAND_GLYPH[band]}
        </span>
        <span className="type-body-sm text-ink">{REVEAL_BUDGET_LABELS[scope]}</span>
        <span className="type-body-sm" style={{ color }}>
          {BUDGET_BAND_LABEL[band]}
        </span>
        <span className="type-body-sm num ml-auto text-ink">
          {remainingLabel(reading.remaining, ceiling, scope)}
        </span>
      </div>

      <Bar remaining={reading.remaining} ceiling={ceiling} cost={cost} color={color} />

      <p className="type-caption text-ink-muted">
        {costSentence(cost, scope, after)}
        {cost > 0 ? " · " : ""}
        {`resets ${formatResetIn(resetsInS)} (${REVEAL_BUDGET_WINDOW_LABELS[scope]}'s window)`}
      </p>
    </div>
  );
}

/**
 * The bar is decoration and says so.
 *
 * It is drawn only when both numbers are real; a track with no fill would read as "empty
 * budget" rather than as "unknown budget", which is the confusion this whole file is about.
 */
function Bar({
  remaining,
  ceiling,
  cost,
  color,
}: {
  readonly remaining: number | null;
  readonly ceiling: number | null;
  readonly cost: number;
  readonly color: string;
}): ReactElement | null {
  if (remaining === null || ceiling === null || ceiling <= 0) return null;
  const left = Math.max(0, Math.min(1, remaining / ceiling));
  const spend = Math.max(0, Math.min(left, cost / ceiling));
  return (
    <div aria-hidden="true" className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-control-hover">
      {/* What survives this reveal, then what this reveal takes — read left to right. */}
      <div style={{ width: `${String((left - spend) * 100)}%`, backgroundColor: color }} />
      <div
        data-testid="reveal-budget-spend"
        className="opacity-50"
        style={{ width: `${String(spend * 100)}%`, backgroundColor: color }}
      />
    </div>
  );
}

/** `143 of 200 left this hour`, or the honest absence of a figure. */
function remainingLabel(
  remaining: number | null,
  ceiling: number | null,
  scope: RevealBudgetScope,
): string {
  const window = REVEAL_BUDGET_WINDOW_LABELS[scope];
  if (remaining === null) {
    return ceiling === null
      ? "not measured yet"
      : `not measured yet · ceiling ${formatInteger(ceiling)} ${window}`;
  }
  return ceiling === null
    ? `${formatInteger(remaining)} left ${window}`
    : `${formatInteger(remaining)} of ${formatInteger(ceiling)} left ${window}`;
}

/** `this reveal costs 1 record · 198 would remain`. Silent when this budget is not charged. */
function costSentence(
  cost: number,
  scope: RevealBudgetScope,
  after: number | null,
): string {
  if (cost === 0) return `this reveal charges nothing against ${REVEAL_BUDGET_LABELS[scope]}`;
  const unit = REVEAL_BUDGET_UNITS[scope];
  const charge = `this reveal costs ${formatInteger(cost)} ${cost === 1 ? unit : `${unit}s`}`;
  return after === null ? charge : `${charge} · ${formatInteger(after)} would remain`;
}
