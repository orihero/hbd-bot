/**
 * Vendor: what is left at each supplier, whether the pollers are still asking, what a song
 * consumes, and how every dollar on this page was arrived at.
 *
 * ## One read, after the stat band came off
 *
 * This tab used to open with four stat cards off `/dashboard/finance` — vendor balance, songs
 * remaining, spend, cost per song — above the same accounts drawn per supplier. All four were
 * a second, coarser printing of numbers `VendorCards` gives per supplier and in that
 * supplier's own unit, so the row is gone and with it the second read, the second note and the
 * second failure mode. Everything on this tab is now `/dashboard/vendor` at the figure period,
 * except the two charts, which carry their own reads inside their own cards.
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
import { useI18n } from "@/i18n";

import {
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

/*
 * The balance card's caption used to interpolate `THRESHOLD_BAD_BELOW` / `THRESHOLD_WARN_BELOW`
 * so the boundaries were never a second copy of the owner's decision. The caption is gone, and
 * with it the interpolation and the two imports: the gates live in `thresholdOf`, the meter
 * paints them, and each lane prints its own state word beside its own figure.
 */
export interface VendorSectionProps
  extends Omit<SectionProps, "state" | "values" | "cardPeriods" | "onCardPeriodChange"> {
  /** `/dashboard/vendor` at the figure period. Its own read, its own failure. */
  readonly vendor: Query<VendorResponse>;
}

export function VendorSection({
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
      <FigureHeading label={t("dashboard.figures.heading")}>{picker}</FigureHeading>
      <SectionNote state={vendorState} subjectKey="dashboard.subjects.vendorDetail" />

      {/* One card per supplier, before the figures: the five numbers the owner reads first —
          what is left, what we consumed, what a song consumes, what a song costs, and how much
          consumption the balance still buys. The figures below are the same accounts drawn;
          the cards are the same accounts NUMBERED, and neither is a substitute for the other. */}
      {!blocked && (
        /* `mb-[14px]`: the same gap `FigureHeading` puts between a group and what precedes it.
           `FigureStack` below carries only its own 10px BOTTOM margin, so without this the last
           supplier card and the balance meters were two cards touching — which read as one
           group of five figures and one drawing, rather than as the cards and then the
           figures. */
        <div className="mb-[14px] mt-3">
          {data === undefined ? <VendorCardsSkeleton /> : <VendorCards {...adaptVendorCards(data)} />}
        </div>
      )}

      {!blocked && (
        <FigureStack>
          <FigureCard
            title={t("dashboard.figures.vendorBalances.title")}
            isPlaceholder={dim}
          >
            {health === null ? <FigureSkeleton /> : <VendorBalanceMeters {...health} />}
          </FigureCard>
          <FigureCard
            title={t("dashboard.figures.pollerFreshness.title")}
            isPlaceholder={dim}
          >
            {/* The SAME object the meters were given — see `health` above. */}
            {health === null ? <FigureSkeleton /> : <PollerFreshness {...health} />}
          </FigureCard>
          <FigureCard
            title={t("dashboard.figures.songConsumption.title")}
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
