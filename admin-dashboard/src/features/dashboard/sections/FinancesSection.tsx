/**
 * Finances: what came in against what went out, and what the plans still owe.
 *
 * The four vendor cards that used to sit here — balance, songs remaining, spend, cost per song
 * — have moved to **Vendor**. They are about what the suppliers cost and what is left at them,
 * and they belong beside the meters that measure the same accounts; they were only ever here
 * because Finances was once the only place money appeared. The read that serves them has not
 * moved: they are still finance figures, drawn on another tab.
 *
 * ## The plan book obeys no picker, and says so
 *
 * `GET /api/metrics/plans` takes NO window. Liability is a STATE — what is owed right now —
 * rather than a flow, so the two figures below carry the response's own `asOf` and sit under
 * their own heading with no period picker on it. Putting them under the "Figures" label, whose
 * picker moves everything beside it, would have made them look like they were obeying a window
 * the server never applied.
 */

import type { JSX } from "react";

import type { PlanLiabilityResponse } from "@/api/dashboard";
import { adaptPlanLiability, adaptPlanUtilisation } from "@/features/dashboard/adapt";
import { PlanLiability, PlanUtilisation } from "@/features/dashboard/charts";
import { chartSpecsFor } from "@/features/dashboard/chartSpecs";
import { useI18n } from "@/i18n";

import {
  CardBand,
  ChartPanels,
  FigureCard,
  FigureGrid,
  FigureHeading,
  FigureSkeleton,
  SectionNote,
  stateOf,
  type Query,
  type SectionProps,
} from "./SectionChrome";

/**
 * The two plan figures are drawn 651x244, not 651x176.
 *
 * They are destined for a two-up row and each carries three axis ticks plus a legend at the
 * 8px type floor, so the box grew rather than the type shrinking — house rule 3. `ChartCard`
 * defaults to the series charts' ratio, so this has to be said.
 */
const PLAN_RATIO = "651 / 244";

export interface FinancesSectionProps extends SectionProps {
  /** The plan book. No window, no period, and one cache entry for the whole deployment. */
  readonly plans: Query<PlanLiabilityResponse>;
}

export function FinancesSection({
  state,
  values,
  cardPeriods,
  onCardPeriodChange,
  figurePeriod,
  picker,
  grans,
  onGranChange,
  finance,
  plans,
}: FinancesSectionProps): JSX.Element {
  const { t } = useI18n();
  const planState = stateOf(plans);
  const book = plans.data;
  const blocked = book === undefined && plans.error !== null;

  return (
    <>
      <CardBand
        section="finance"
        subjectKey="dashboard.subjects.finances"
        state={state}
        values={values}
        cardPeriods={cardPeriods}
        onCardPeriodChange={onCardPeriodChange}
      />

      <FigureHeading label={t("dashboard.figures.heading")}>{picker}</FigureHeading>
      <FigureGrid>
        <ChartPanels
          specs={chartSpecsFor("finance")}
          period={figurePeriod}
          grans={grans}
          onGranChange={onGranChange}
          finance={finance}
        />
      </FigureGrid>

      <FigureHeading label={t("dashboard.figures.planBook")} />
      <SectionNote state={planState} subjectKey="dashboard.subjects.planBook" />
      {!blocked && (
        /* Its OWN grid, and that is the point: side by side is what the owner asked for, and
           inside a grid of their own the two are either both across or both stacked. Sharing
           the grid above would let a wide viewport put Revenue-against-cost beside Plan
           utilisation and orphan Plan liability onto a row by itself.

           The floor is the same 610px every figure column uses, so the pair goes two-across
           only above about 1230px of content band and STACKS below it. It never squashes: a
           651-unit viewBox in a 500px column draws its 8px ticks at about 6px, and the fix for
           a narrow column is fewer columns, never smaller type. */
        <FigureGrid>
          <FigureCard
            title={t("dashboard.figures.planUtilisation.title")}
            ratio={PLAN_RATIO}
            isPlaceholder={plans.isPlaceholderData}
          >
            {book === undefined ? (
              <FigureSkeleton />
            ) : (
              <PlanUtilisation {...adaptPlanUtilisation(book)} />
            )}
          </FigureCard>
          <FigureCard
            title={t("dashboard.figures.planLiability.title")}
            ratio={PLAN_RATIO}
            isPlaceholder={plans.isPlaceholderData}
          >
            {book === undefined ? (
              <FigureSkeleton />
            ) : (
              <PlanLiability {...adaptPlanLiability(book)} />
            )}
          </FigureCard>
        </FigureGrid>
      )}
    </>
  );
}
