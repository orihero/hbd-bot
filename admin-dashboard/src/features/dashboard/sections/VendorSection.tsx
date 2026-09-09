/**
 * Vendor: what is left at each supplier, whether the pollers are still asking, what a song
 * consumes, and how every dollar on this page was arrived at.
 *
 * ## Two reads, and they are not the same read
 *
 * The four stat cards come off `/dashboard/finance` — they moved tabs, not routes. The five
 * figures come off `/dashboard/vendor`. The two republish `vendorSpend` and `vendorBalances`
 * from the same server functions and are asked for windows that agree by contract, but they
 * land independently and fail independently, which is why they get two notes: a finance 403
 * must not blank the balance meters, and a vendor timeout must not blank the cards.
 *
 * ## Why three of the five figures take the whole band
 *
 * A balance lane already carries two or three lines of type at the 8px floor and the unit
 * tables are three headed tables stacked; the rule is that a narrow column gets FEWER columns,
 * never smaller type. `VendorUnits` is drawn 651x352 for the same reason and says so below.
 *
 * The traffic light on the meters is the owner's decision and is not re-litigated here: the
 * health green is deliberately not `ACCENT` (that ink means "this is the mark the figure is
 * about"), and there is a fourth state — unmeasured — for `uncapped`, `never answered`, `not
 * reported` and `stale`, drawn as an achromatic hatched track with the reason in words.
 * Painting an unknown balance green makes an empty account look fine; painting it red sends
 * the operator to top up an account that was never low.
 */

import type { JSX } from "react";

import type { VendorResponse } from "@/api/dashboard";
import {
  adaptCostProvenance,
  adaptVendorCards,
  adaptVendorHealth,
  adaptVendorUnits,
} from "@/features/dashboard/adapt";
import { VendorCards, VendorCardsSkeleton } from "@/features/dashboard/VendorCards";
import {
  CostProvenance,
  PollerFreshness,
  VendorBalanceMeters,
  VendorUnits,
} from "@/features/dashboard/charts";
import { chartSpecsFor } from "@/features/dashboard/chartSpecs";
import { THRESHOLD_BAD_BELOW, THRESHOLD_WARN_BELOW } from "@/features/dashboard/svg";
import { useI18n } from "@/i18n";

import {
  CardBand,
  ChartPanels,
  FigureCard,
  FigureGrid,
  FigureHeading,
  FigureSkeleton,
  FigureStack,
  SectionNote,
  stateOf,
  type Query,
  type SectionProps,
} from "./SectionChrome";

/** Three unit families, one headed table each: the box grew, the 8px type did not shrink. */
const UNITS_RATIO = "651 / 352";

/**
 * The card's caption quotes the traffic light's own boundaries rather than spelling them.
 *
 * A literal `< 30 songs critical` here would be a fourth copy of the owner's decision, sitting
 * one line above a drawing that takes its gates from `thresholdOf` — and the day the boundary
 * moves, the caption is the copy nobody greps for.
 */
export interface VendorSectionProps extends SectionProps {
  /** `/dashboard/vendor` at the figure period. Its own read, its own failure. */
  readonly vendor: Query<VendorResponse>;
}

export function VendorSection({
  state,
  values,
  cardPeriods,
  onCardPeriodChange,
  figurePeriod,
  picker,
  grans,
  onGranChange,
  finance,
  vendor,
}: VendorSectionProps): JSX.Element {
  const { t } = useI18n();
  const vendorState = stateOf(vendor);
  const data = vendor.data;
  const blocked = data === undefined && vendor.error !== null;
  const dim = vendor.isPlaceholderData;

  /* ONE adapter call for the pair. The meters and the freshness figure are one statement about
     one set of accounts, and two calls would be two chances for a future change to filter or
     order them differently — at which point the two stacked drawings would disagree about
     which accounts exist while claiming to be the same list. */
  const health = data === undefined ? null : adaptVendorHealth(data);

  return (
    <>
      {/* The subject is "Vendor", not "Finances": these four cards are served by the finance
          read but they are drawn here, and a note headed with the name of a tab the operator
          is not looking at tells them to go and check the wrong thing. */}
      <CardBand
        section="vendor"
        subjectKey="dashboard.subjects.vendorSpend"
        state={state}
        values={values}
        cardPeriods={cardPeriods}
        onCardPeriodChange={onCardPeriodChange}
      />

      <FigureHeading label={t("dashboard.figures.heading")}>{picker}</FigureHeading>
      <SectionNote state={vendorState} subjectKey="dashboard.subjects.vendorDetail" />

      {/* One card per supplier, before the figures: the five numbers the owner reads first —
          what is left, what we consumed, what a song consumes, what a song costs, and how much
          consumption the balance still buys. The figures below are the same accounts drawn;
          the cards are the same accounts NUMBERED, and neither is a substitute for the other. */}
      {!blocked && (
        <div className="mt-3">
          {data === undefined ? <VendorCardsSkeleton /> : <VendorCards {...adaptVendorCards(data)} />}
        </div>
      )}

      {!blocked && (
        <FigureStack>
          <FigureCard
            title={t("dashboard.figures.vendorBalances.title")}
            sub={t("dashboard.figures.vendorBalances.sub", {
              bad: THRESHOLD_BAD_BELOW,
              warn: THRESHOLD_WARN_BELOW,
            })}
            isPlaceholder={dim}
          >
            {health === null ? <FigureSkeleton /> : <VendorBalanceMeters {...health} />}
          </FigureCard>
          <FigureCard
            title={t("dashboard.figures.pollerFreshness.title")}
            sub={t("dashboard.figures.pollerFreshness.sub")}
            isPlaceholder={dim}
          >
            {/* The SAME object the meters were given — see `health` above. */}
            {health === null ? <FigureSkeleton /> : <PollerFreshness {...health} />}
          </FigureCard>
          <FigureCard
            title={t("dashboard.figures.songConsumption.title")}
            sub={t("dashboard.figures.songConsumption.sub")}
            ratio={UNITS_RATIO}
            isPlaceholder={dim}
          >
            {data === undefined ? <FigureSkeleton /> : <VendorUnits {...adaptVendorUnits(data)} />}
          </FigureCard>
        </FigureStack>
      )}

      <FigureGrid>
        {!blocked && (
          <FigureCard
            title={t("dashboard.figures.costProvenance.title")}
            sub={t("dashboard.figures.costProvenance.sub")}
            cov={t("dashboard.figures.costProvenance.cov")}
            isPlaceholder={dim}
          >
            {data === undefined ? (
              <FigureSkeleton />
            ) : (
              <CostProvenance {...adaptCostProvenance(data)} />
            )}
          </FigureCard>
        )}
        <ChartPanels
          specs={chartSpecsFor("vendor")}
          period={figurePeriod}
          grans={grans}
          onGranChange={onGranChange}
          finance={finance}
        />
      </FigureGrid>
    </>
  );
}
