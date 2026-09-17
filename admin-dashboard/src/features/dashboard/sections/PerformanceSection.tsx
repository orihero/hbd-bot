/**
 * Performance: how fast, how reliably, where orders stand, and what is up.
 *
 * The one tab the split left alone. Five stat cards off `/dashboard/performance` (with the
 * system strip fed by `/ops/pulse`), and the two series figures that were always theirs —
 * songs delivered, and where orders drop off. Nothing moved in or out, so this file is the
 * layout the page had before the tabs, lifted out unchanged.
 */

import type { JSX } from "react";

import { chartSpecsFor } from "@/features/dashboard/chartSpecs";
import { useI18n } from "@/i18n";

import {
  CardBand,
  ChartPanels,
  FigureGrid,
  FigureHeading,
  type SectionProps,
} from "./SectionChrome";

export function PerformanceSection({
  state,
  values,
  cardPeriods,
  onCardPeriodChange,
  figurePeriod,
  picker,
  grans,
  onGranChange,
  finance,
}: SectionProps): JSX.Element {
  const { t } = useI18n();

  return (
    <>
      <CardBand
        section="performance"
        subjectKey="dashboard.subjects.performance"
        state={state}
        values={values}
        cardPeriods={cardPeriods}
        onCardPeriodChange={onCardPeriodChange}
      />

      <FigureHeading label={t("dashboard.figures.heading")}>{picker}</FigureHeading>
      <FigureGrid>
        <ChartPanels
          specs={chartSpecsFor("performance")}
          period={figurePeriod}
          grans={grans}
          onGranChange={onGranChange}
          finance={finance}
        />
      </FigureGrid>
    </>
  );
}
