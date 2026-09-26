/**
 * The six SERIES figures, as presentation metadata plus one `render` per chart.
 *
 * Six, still — the new figures on this page are drawn from the audience, vendor and plan
 * responses rather than from `/series`, and a spec here is by definition a slice of
 * `ChartData`. They are placed by their own sections instead.
 *
 * A spec no longer hands a chart a GRANULARITY. It hands it the slice of `ChartData` the
 * adapter built for it, because the granularity is a property of the REQUEST — it picks the
 * series bucket — and by the time a chart is drawing, the bucket is already baked into the
 * numbers. `grans` survives only to say which options that chart's toggle offers.
 *
 * Two captions from the mockup are functions rather than constants, and one number is gone:
 * see `sub` and `cov` below. The rest is the mock's copy, unchanged.
 */

import type { JSX } from "react";

import type { SegmentedOption } from "@/components/Segmented";
import { formatCount, formatUsd, type ChartData } from "@/features/dashboard/adapt";
import {
  CostPerSong,
  CostSplit,
  Delivered,
  Funnel,
  RevCost,
  Signups,
} from "@/features/dashboard/charts";
import type { SectionKey } from "@/features/dashboard/cardSpecs";
import { isGranLegal, type Gran, type Period, type Translate } from "@/features/dashboard/data";
import type { TranslationPath } from "@/i18n/types";

export type ChartKey = "signups" | "revcost" | "delivered" | "cps" | "costsplit" | "funnel";

export interface ChartSpec {
  readonly key: ChartKey;
  /**
   * The tab this chart is drawn in. Sign-ups is an audience question, the two cost figures
   * are vendor questions, and the money-in-against-money-out figure is the finance one; the
   * page was one scroll when they all sat together and the grouping is the owner's.
   */
  readonly section: SectionKey;
  readonly titleKey: TranslationPath;
  /**
   * The sub-caption, as a function of the data because one of the six states a unit the
   * DATA chooses — and of `t`, because it is a sentence and this console has three. `null`
   * data is "not loaded yet": every caption still reads, and the one that quotes a unit says
   * which unit it is waiting on rather than naming the mockup's.
   */
  readonly sub: (data: ChartData | null, t: Translate) => string;
  /** Small uppercase caveat riding on the title. */
  /**
   * The uppercase badge beside the title. No dashboard spec sets one any more — `priced spend
   * only`, `this window` — but the prop stays: it is how a chart that genuinely cannot be read
   * without a caveat would carry it, and the three that were removed were removed for being
   * true of every chart on the page rather than for being wrong.
   */
  readonly covKey?: TranslationPath;
  /** Granularities the toggle offers. Empty = this figure has no toggle in the mockup. */
  readonly grans: readonly Gran[];
  readonly render: (data: ChartData) => JSX.Element;
}

const GRAN_LABEL_KEY: Record<Gran, TranslationPath> = {
  hourly: "dashboard.charts.grans.hourly",
  daily: "dashboard.charts.grans.daily",
  weekly: "dashboard.charts.grans.weekly",
  monthly: "dashboard.charts.grans.monthly",
};

/**
 * The grains a chart may OFFER for the period on screen, which is not the same list it can
 * draw. `?bucket=hour` over a window longer than eight days is a 422 the operator cannot
 * recover from — the retry re-runs a byte-identical refusal — and a grain whose bucket is as
 * long as the window draws one column, which is not a choice either. Both are filtered here
 * rather than left for the server to refuse.
 */
export function granOptions(
  grans: readonly Gran[],
  period: Period,
  t: Translate,
): readonly SegmentedOption<Gran>[] {
  return grans
    .filter((g) => isGranLegal(g, period))
    .map((g) => ({ value: g, label: t(GRAN_LABEL_KEY[g]) }));
}

const FINE: readonly Gran[] = ["hourly", "daily", "weekly", "monthly"];
const COARSE: readonly Gran[] = ["daily", "weekly", "monthly"];

/** A caption that says the same thing whatever the data is. */
function fixed(key: TranslationPath): (data: ChartData | null, t: Translate) => string {
  return (_data, t) => t(key);
}

/**
 * `one rung = 25 orders · dashed drops` was true of the fixture and of nothing else: the
 * funnel's unit is chosen per window off the tallest column, so the mock's 25 is a number
 * about a demo. The shape of the sentence is the mock's; the figure in it is this window's.
 */
function funnelSub(data: ChartData | null, t: Translate): string {
  if (data === null) return t("dashboard.charts.funnel.subPending");
  if (data.funnel.unit === 1) return t("dashboard.charts.funnel.subOne");
  return t("dashboard.charts.funnel.sub", { count: formatCount(data.funnel.unit) });
}

/** Mockup order, titles and captions. */
export const CHART_SPECS: readonly ChartSpec[] = [
  {
    key: "signups",
    section: "audience",
    titleKey: "dashboard.charts.signups.title",
    /* "hollow = weekend" is only claimable on a daily series, where the adapter carries a
       real weekday per bucket. On any other grain the hollow dot is the tip, and saying
       otherwise would be an unbacked claim about which days were weekends. */
    sub: (data, t) =>
      data !== null && data.signups.weekend.length > 0
        ? t("dashboard.charts.signups.subWeekend")
        : t("dashboard.charts.signups.sub"),
    grans: FINE,
    render: (data) => (
      <Signups
        points={data.signups.points}
        ticks={data.signups.ticks}
        weekend={data.signups.weekend}
      />
    ),
  },
  {
    key: "revcost",
    section: "finance",
    titleKey: "dashboard.charts.revcost.title",
    sub: fixed("dashboard.charts.revcost.sub"),
    grans: COARSE,
    render: (data) => (
      <RevCost
        revenue={data.revCost.revenue}
        cost={data.revCost.cost}
        ticks={data.revCost.ticks}
        revenueNote={data.revCost.revenueNote}
        costNote={data.revCost.costNote}
      />
    ),
  },
  {
    key: "delivered",
    section: "performance",
    titleKey: "dashboard.charts.delivered.title",
    sub: fixed("dashboard.charts.delivered.sub"),
    grans: FINE,
    render: (data) => <Delivered points={data.delivered.points} ticks={data.delivered.ticks} />,
  },
  {
    key: "cps",
    section: "vendor",
    titleKey: "dashboard.charts.cps.title",
    /* Named for what it actually divides. The chart's numerator is spend BILLED in the
       bucket less unattributed work — which still carries the balance poller's quota probes
       and calls against orders that never delivered — while the card beside it divides the
       spend attributed to orders DELIVERED in the window. Two measures, so two captions. */
    sub: fixed("dashboard.charts.cps.sub"),
    /* The mock's badge read "68% priced". That is a MEASUREMENT, and it was a fixture's — the
       real coverage is `costedCalls / calls` on the finance response, which no chart carries.
       Rather than reprint a demo's percentage against live columns, the badge now states the
       one thing this figure is always true about: unpriced vendor calls are left out of it. */
    grans: COARSE,
    render: (data) => (
      <CostPerSong
        values={data.costPerSong.values}
        ticks={data.costPerSong.ticks}
        priceLine={data.costPerSong.priceLine}
      />
    ),
  },
  {
    key: "costsplit",
    section: "vendor",
    titleKey: "dashboard.charts.costsplit.title",
    sub: (data, t) =>
      data === null
        ? t("dashboard.charts.costsplit.subPending")
        : t("dashboard.charts.costsplit.sub", { amount: formatUsd(data.costSplit.tickUsd) }),
    /* "last 30d" in the mock. Both this and the funnel are computed over the REQUEST window,
       so the span is whatever the period picker says and a fixed 30 days would misdate them. */
    grans: [],
    render: (data) => <CostSplit rows={data.costSplit.rows} tickUsd={data.costSplit.tickUsd} />,
  },
  {
    key: "funnel",
    section: "performance",
    titleKey: "dashboard.charts.funnel.title",
    sub: funnelSub,
    grans: [],
    render: (data) => <Funnel unit={data.funnel.unit} steps={data.funnel.steps} />,
  },
];

/**
 * The series charts one tab draws, in the mockup's order.
 *
 * A filter rather than four hand-written lists: `CHART_SPECS` stays the one place a chart is
 * declared, so a chart can never be in two sections at once or — worse — in none, which is
 * how a figure disappears from a page without anybody deleting it.
 */
export function chartSpecsFor(section: SectionKey): readonly ChartSpec[] {
  return CHART_SPECS.filter((spec) => spec.section === section);
}
