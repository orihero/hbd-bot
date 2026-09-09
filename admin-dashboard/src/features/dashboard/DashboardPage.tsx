/**
 * The dashboard, against the live API.
 *
 * Eight reads land INDEPENDENTLY and are drawn independently: audience on 60s, finance on 30s,
 * performance on 10s, the series behind the charts on 15s, vendor on 30s, the plan book on 60s,
 * the deployment pulse on 5s, and the two identified lists on no interval at all. Nothing here
 * waits for the slowest of them — a band renders its own skeletons while its neighbours already
 * hold numbers, and a read that fails says so in the band its cards would have occupied while
 * the rest of the page keeps ticking. Gating the whole page on one query would mean a forbidden
 * `finance` (a viewer role) blanking cards that the operator is allowed to see.
 *
 * Nothing on this page is a literal. The header's clock and FX line are functions of the
 * response; every card's number comes from `adapt.ts`, which turns a null into a hatched pill
 * instead of a zero. The chart captions and badges come from `chartSpecs.tsx`, which has
 * already retired the mock's "68% priced" and "last 30d" — one a fixture's measurement, the
 * other a window a picker can contradict — and they are passed through here unedited rather
 * than second-guessed.
 *
 * ## THE PERIOD IS NOT GLOBAL, AND THAT IS STILL THE WHOLE SHAPE OF THIS FILE
 *
 * The mockup put one `today | week | month | year` picker in the header and wired every card's
 * mini selector to it, so reading "new users this year" dragged all eighteen cards and six
 * charts along. That makes the one comparison an operator actually wants — this week's spend
 * against this month's — impossible to hold on screen at once.
 *
 * There are THREE independent scopes and no page-wide one. The tabs did not change that:
 *
 *  - **A card with `sel` owns its own period.** `cardPeriods` holds one per card key, and it
 *    lives HERE rather than in a section so that a card keeps its window when the operator
 *    walks to another tab and back.
 *  - **Every other card is pinned to `BASE_PERIOD`.** Those cards are population and
 *    point-in-time figures — totals, balances, system state — where a window is close to
 *    meaningless, which is why the mockup gave them no selector either.
 *  - **The FIGURES share ONE picker**, on their group label. It was "the six charts" before;
 *    it is now every drawn figure, because the tabs put the audience and vendor figures beside
 *    the series charts and a window per panel is a window per panel to put two figures on
 *    different months without noticing. No stat card obeys it, and the two figures the plan
 *    book feeds obey nothing at all — that route takes no window and they print their own
 *    `asOf`.
 *
 * The cost of that is reads, and it is bounded: a section is fetched once per DISTINCT period
 * its cards are showing, never once per card. All the selectors on `today` is one audience
 * read, one finance read, one performance read — exactly what the global picker cost.
 *
 * ## What the tabs changed
 *
 * A section that is not open is UNMOUNTED and its reads are not enabled, so the four tabs gate
 * the API as well as the page. `finance` at `BASE_PERIOD` is enabled on every tab, because the
 * header's FX line reads it and the header is drawn everywhere.
 *
 * NO read is exempt from that gating. The audience band — stat cards, churn, top generators,
 * recent subscribers — briefly drew on all four tabs while its two reads stayed gated to
 * Audience, which is the worst of both arrangements: the other three tabs drew the band with
 * nothing behind it. It is back inside the Audience branch, and `/dashboard/audience` and
 * `/dashboard/audience-lists` are enabled there and nowhere else.
 *
 * That the LISTS follow the tab is the load-bearing half. `/dashboard/audience-lists` is
 * `RECORDS_READ` and writes an audit disclosure row per call, so a band on every tab meant that
 * opening the Finances tab also read customer identities. Only the tab that actually shows
 * those two lists asks for them. Moving the figure picker still buys a row, and should: a
 * different window is a different list, and the row records that an admin read customer
 * identities over it.
 *
 * ## What the header lost
 *
 * The period picker, the `to 07 Sep` chip and the `LIVE · 4s AGO` pill are all gone. The chip
 * named a page-global window that no longer exists, so it could only ever have described some
 * of the cards under it. The pill was honest — it reported what `useLiveness` observed — but
 * it answered a question ("is this page still talking to the API") that a failing read already
 * answers in the band where it failed, and it did it with a number that changed every second.
 * `useLiveness` is kept in `useDashboardData.ts`; nothing renders it.
 *
 * The VENDOR BALANCES briefly stood in their place and have moved on again, to `TopBar` — a
 * balance is a property of the deployment rather than of this page, and an operator reading
 * `/generations` needs it as much as one reading `/`. The identity chip is gone too;
 * `NavRail`'s footer owns the session, so a second screen cannot duplicate it or silently drop
 * the only way out.
 *
 * What the header GAINED is the tab strip, which is a set of links rather than buttons because
 * the open tab is in the query string — see `sections/SectionTabs.tsx`.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";

import {
  DEFAULT_AUDIENCE_LIST_LIMIT,
  type AudienceListsResponse,
  type AudienceResponse,
} from "@/api/dashboard";
import { ErrorNote } from "@/components/ErrorNote";
import { Segmented, type SegmentedOption } from "@/components/Segmented";
import { Skeleton } from "@/components/Skeleton";
import { ChurnCard } from "@/features/dashboard/ChurnCard";
import { RecentSubscribers } from "@/features/dashboard/RecentSubscribers";
import { TopGenerators } from "@/features/dashboard/TopGenerators";
import {
  CHURN_CARD_PENDING,
  adaptAudience,
  adaptChurnCard,
  adaptFinance,
  adaptPerformance,
  adaptSparks,
  audienceListsNote,
  mergeSparks,
  recentSubscribersOf,
  topGeneratorsOf,
  type CardValue,
  type CardValues,
  type SparkKey,
} from "@/features/dashboard/adapt";
import {
  cardRowsFor,
  selectableKeysIn,
  type CardKey,
  type SectionKey,
} from "@/features/dashboard/cardSpecs";
import { CHART_SPECS } from "@/features/dashboard/chartSpecs";
import {
  PERIODS,
  PERIOD_LABEL_KEY,
  UNAVAILABLE,
  granFor,
  headerMeta,
  type FxState,
  type Gran,
  type Period,
} from "@/features/dashboard/data";
import { AudienceSection } from "@/features/dashboard/sections/AudienceSection";
import { FinancesSection } from "@/features/dashboard/sections/FinancesSection";
import { PerformanceSection } from "@/features/dashboard/sections/PerformanceSection";
import {
  BASE_PERIOD,
  CardBand,
  FigureGrid,
  GroupLabel,
  LIST_MIN_PX,
  granOr,
  noteFor,
  type AnyQuery,
  type CardPeriods,
  type GranMap,
  type Query,
  type SectionProps,
  type SectionState,
} from "@/features/dashboard/sections/SectionChrome";
import { SectionTabs, readTab } from "@/features/dashboard/sections/SectionTabs";
import { VendorSection } from "@/features/dashboard/sections/VendorSection";
import {
  useAudience,
  useAudienceLists,
  useFinance,
  usePerformance,
  usePlans,
  usePulse,
  useSeries,
  useVendor,
  type DashboardQueryError,
} from "@/features/dashboard/useDashboardData";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/state/auth";

/* -------------------------------------------------------------------------- */
/* Which read each card comes from — NOT which tab draws it                    */
/* -------------------------------------------------------------------------- */

/**
 * The three reads that serve stat cards. `vendor` is a TAB and not one of these — it now draws
 * no stat card at all: the four it used to open with were a coarser second printing of what
 * `VendorCards` gives per supplier, and they went with the row.
 */
type ReadKey = "audience" | "finance" | "performance";

/** The cards each tab draws that own a period selector, derived so it cannot drift. */
const SEL_IN: Readonly<Record<SectionKey, readonly CardKey[]>> = {
  audience: selectableKeysIn("audience"),
  finance: selectableKeysIn("finance"),
  /* Empty, and derived rather than written as `[]` so that a row put back on this tab is picked
     up here without anyone remembering to. */
  vendor: selectableKeysIn("vendor"),
  performance: selectableKeysIn("performance"),
};

/**
 * The selector-bearing cards each READ serves.
 *
 * Finance keeps the Vendor tab's list appended even though it is empty today: that pairing is
 * the one place where "where a card is drawn" and "where its number comes from" ever came
 * apart, and one array is what `override` needs because it walks the keys of ONE response.
 */
const SEL_BY_READ: Readonly<Record<ReadKey, readonly CardKey[]>> = {
  audience: SEL_IN.audience,
  finance: [...SEL_IN.finance, ...SEL_IN.vendor],
  performance: SEL_IN.performance,
};

/** The four sparkline wells. `adapt.ts` owns the union; this is the membership test for it. */
const SPARK_KEYS: readonly SparkKey[] = [
  "newUsers",
  "totalRevenue",
  "vendorSpend",
  "songsDelivered",
];

function isSparkKey(key: CardKey): key is SparkKey {
  return (SPARK_KEYS as readonly CardKey[]).includes(key);
}

/**
 * The spark wells one tab draws, read off `cardSpecs.ts` rather than listed here.
 *
 * A well is a card's own series, so a tab that draws no such card needs no series read for one.
 * Deriving it means moving a card between tabs moves its well's read with it.
 */
function sparkKeysIn(section: SectionKey): readonly SparkKey[] {
  return cardRowsFor(section)
    .flatMap((row) => row.cards)
    .filter((card) => card.spark === true)
    .map((card) => card.key)
    .filter(isSparkKey);
}

/**
 * Which periods a set of cards is currently showing, `BASE_PERIOD` always included.
 *
 * This is the function that keeps the read count honest: it is a SET, so ten cards on `week`
 * ask for `week` once. `BASE_PERIOD` is unconditional because the pinned cards in the same
 * band need it even when every selector has been moved off it — and because the header's FX
 * line reads the base finance response.
 */
function periodsFor(keys: readonly CardKey[], periods: CardPeriods): ReadonlySet<Period> {
  const out = new Set<Period>([BASE_PERIOD]);
  for (const key of keys) out.add(periods[key] ?? BASE_PERIOD);
  return out;
}

/** A read no visible card wants. Frozen at module scope so the memo below stays stable. */
const NO_PERIODS: ReadonlySet<Period> = new Set<Period>();

/** The bucket each toggle-bearing chart lands on for a window — the mockup's set(). */
function gransFor(period: Period): GranMap {
  const out: Record<string, Gran> = {};
  for (const spec of CHART_SPECS) {
    const g = granFor(spec.grans, period);
    if (g !== null) out[spec.key] = g;
  }
  return out;
}

/** The card sparklines' own series. Matches `signups`' default grain, so the read is shared. */
const SPARK_GRANS: readonly Gran[] = ["hourly", "daily", "weekly", "monthly"];

/* -------------------------------------------------------------------------- */
/* One read, four windows                                                      */
/* -------------------------------------------------------------------------- */

/** A value held once per period. Every windowed card read is one of these. */
type PeriodMap<T> = Readonly<Record<Period, T>>;

/** The mutable form of `CardValues`, for the one place that assembles rather than reads it. */
type Draft = Partial<Record<CardKey, CardValue>>;

/**
 * The four responses, as ONE object with a stable identity.
 *
 * Without this every render builds a fresh `{today, week, month, year}` wrapper, and the big
 * `values` memo — which takes that wrapper as a dependency — would recompute every card on
 * every render forever. TanStack already keeps each `data` referentially stable through
 * structural sharing, so memoising on the four of them is exact: the object changes when, and
 * only when, one of the responses does.
 */
function useDataMap<T>(
  queries: PeriodMap<{ readonly data: T | undefined }>,
): PeriodMap<T | undefined> {
  const today = queries.today.data;
  const week = queries.week.data;
  const month = queries.month.data;
  const year = queries.year.data;
  return useMemo(() => ({ today, week, month, year }), [today, week, month, year]);
}

/**
 * Every non-base window's response, run through its adapter.
 *
 * `BASE_PERIOD` is skipped: it is already spread into the draft by the caller, and adapting it
 * twice is the same arithmetic for a result nothing reads — `override` never asks for it.
 */
function adaptByPeriod<T>(
  data: PeriodMap<T | undefined>,
  adapt: (value: T, period: Period) => CardValues,
): PeriodMap<CardValues | undefined> {
  const one = (p: Period): CardValues | undefined => {
    if (p === BASE_PERIOD) return undefined;
    const value = data[p];
    return value === undefined ? undefined : adapt(value, p);
  };
  return { today: one("today"), week: one("week"), month: one("month"), year: one("year") };
}

/** Replaces each moved card's figure with the one from its own window, in place. */
function override(
  out: Draft,
  keys: readonly CardKey[],
  periods: CardPeriods,
  byPeriod: PeriodMap<CardValues | undefined>,
): void {
  for (const key of keys) {
    const p = periods[key] ?? BASE_PERIOD;
    if (p === BASE_PERIOD) continue;
    const value = byPeriod[p]?.[key];
    /* `undefined` means that window has not answered yet. Leaving the base figure standing is
       the point: the card dims through `isPlaceholder` instead of emptying on every click. */
    if (value !== undefined) out[key] = value;
  }
}

/**
 * One band's state, across however many windows its cards are currently showing.
 *
 * `isLoading` and `hasData` are the BASE read's alone — it is what the pinned cards in the band
 * are waiting on, and what decides whether the band can be drawn at all. The other three
 * aggregate, so a second window that is failing or in flight is visible in the band rather than
 * silent on one card.
 *
 * `extra` is for a read that serves the same band from outside the period map — the audience
 * figures, which are the same route at the FIGURE period. Folding it in here is what keeps the
 * Audience tab to one note when the picker happens to sit on the base window and the two are
 * literally the same cache entry.
 */
function sectionState(
  queries: PeriodMap<AnyQuery>,
  needed: ReadonlySet<Period>,
  extra: readonly AnyQuery[] = [],
): SectionState {
  const windowed = PERIODS.filter((p) => needed.has(p)).map((p) => queries[p]);
  const active = [...windowed, ...extra];
  const base = queries[BASE_PERIOD];
  const hasData = base.data !== undefined;
  return {
    isLoading: base.data === undefined && base.error === null,
    /* Two ways the band can be showing something other than what its selectors claim, and both
       have to dim it. The first is `keepPreviousData` handing back the last window's numbers.
       The second has no flag of its own: a window that has NEVER answered — a card just moved
       to `year`, or a tab just opened and enabled the read behind it — leaves `override` with
       nothing to substitute, so the base figure stands under a selector that says `Y`. That is
       the same defect wearing different clothes, so it dims the same way.

       Only the WINDOWED reads count for the second test. `extra` is the figure read, which
       draws its own skeletons in its own group and says nothing about these cards. */
    isPlaceholder:
      active.some((q) => q.isPlaceholderData) ||
      (hasData && windowed.some((q) => q.data === undefined && q.error === null)),
    /* `PERIODS` is ordered and `BASE_PERIOD` leads it, so a base failure wins the one note. */
    error: active.find((q) => q.error !== null)?.error ?? null,
    hasData,
    isFetching: active.some((q) => q.isFetching),
    retry: () => {
      for (const q of active) void q.refetch();
    },
  };
}

/* -------------------------------------------------------------------------- */
/* The page                                                                    */
/* -------------------------------------------------------------------------- */

export function DashboardPage(): JSX.Element {
  const { t } = useI18n();
  const periodOptions = useMemo<readonly SegmentedOption<Period>[]>(
    () => PERIODS.map((p) => ({ value: p, label: t(PERIOD_LABEL_KEY[p]) })),
    [t],
  );

  /* The open tab, from `?tab=`. Not state: the URL is the state, so a refresh, the Back button
     and a pasted link all land on the same section. */
  const [searchParams] = useSearchParams();
  const tab = readTab(searchParams);

  /* One period per card key. An absent entry IS `BASE_PERIOD`; only `sel` cards ever get one.
     Held by the page and not by a section so a card keeps its window across a tab change. */
  const [cardPeriods, setCardPeriods] = useState<CardPeriods>({});
  /* Every FIGURE moves together, under the picker on its own group label. */
  const [figurePeriod, setFigurePeriod] = useState<Period>(BASE_PERIOD);
  const [grans, setGrans] = useState<GranMap>(() => gransFor(BASE_PERIOD));

  const setCardPeriod = useCallback((key: CardKey, p: Period) => {
    setCardPeriods((prev) => ({ ...prev, [key]: p }));
  }, []);

  /* The figures' window also re-derives their buckets: an hourly grain is illegal over a year. */
  const selectFigurePeriod = useCallback((p: Period) => {
    setFigurePeriod(p);
    setGrans(gransFor(p));
  }, []);

  const setGran = useCallback((key: string, g: Gran) => {
    setGrans((prev) => ({ ...prev, [key]: g }));
  }, []);

  /* Which windows each read is wanted at THIS render. A period no VISIBLE card is showing is
     fetched by nobody: the hook is still called (order is fixed) but disabled.

     Finance is the one read with no tab test on it. Its base window feeds the header's FX line,
     which is drawn above every tab; the two tabs whose cards it serves add their own windows on
     top. */
  const audienceNeed = useMemo(
    () => (tab === "audience" ? periodsFor(SEL_IN.audience, cardPeriods) : NO_PERIODS),
    [tab, cardPeriods],
  );
  /* Never `NO_PERIODS`: even on a tab with no finance card, the BASE window is wanted for the
     header's FX line and for the published price the charts are drawn against. */
  const financeNeed = useMemo(
    () => periodsFor(tab === "finance" ? SEL_IN.finance : [], cardPeriods),
    [tab, cardPeriods],
  );
  const perfNeed = useMemo(
    () => (tab === "performance" ? periodsFor(SEL_IN.performance, cardPeriods) : NO_PERIODS),
    [tab, cardPeriods],
  );
  /* Only the open tab's wells: a card that is not mounted has no well to fill. */
  const sparkNeed = useMemo(() => periodsFor(sparkKeysIn(tab), cardPeriods), [tab, cardPeriods]);

  const audience: PeriodMap<ReturnType<typeof useAudience>> = {
    today: useAudience("today", { enabled: audienceNeed.has("today") }),
    week: useAudience("week", { enabled: audienceNeed.has("week") }),
    month: useAudience("month", { enabled: audienceNeed.has("month") }),
    year: useAudience("year", { enabled: audienceNeed.has("year") }),
  };
  const finance: PeriodMap<ReturnType<typeof useFinance>> = {
    today: useFinance("today", { enabled: financeNeed.has("today") }),
    week: useFinance("week", { enabled: financeNeed.has("week") }),
    month: useFinance("month", { enabled: financeNeed.has("month") }),
    year: useFinance("year", { enabled: financeNeed.has("year") }),
  };
  const performance: PeriodMap<ReturnType<typeof usePerformance>> = {
    today: usePerformance("today", { enabled: perfNeed.has("today") }),
    week: usePerformance("week", { enabled: perfNeed.has("week") }),
    month: usePerformance("month", { enabled: perfNeed.has("month") }),
    year: usePerformance("year", { enabled: perfNeed.has("year") }),
  };
  const pulse = usePulse();
  /* The sparkline wells are series data, so they cannot come from the card responses — and each
     well follows ITS OWN card's period, which is why this is four reads and not one. */
  const sparkSeries: PeriodMap<ReturnType<typeof useSeries>> = {
    today: useSeries("today", granOr(SPARK_GRANS, "today", "daily"), {
      enabled: sparkNeed.has("today"),
    }),
    week: useSeries("week", granOr(SPARK_GRANS, "week", "daily"), {
      enabled: sparkNeed.has("week"),
    }),
    month: useSeries("month", granOr(SPARK_GRANS, "month", "daily"), {
      enabled: sparkNeed.has("month"),
    }),
    year: useSeries("year", granOr(SPARK_GRANS, "year", "daily"), {
      enabled: sparkNeed.has("year"),
    }),
  };

  /* The four reads that serve FIGURES rather than cards. One window each — the figure picker's
     — so one hook each, which is also what gives them `keepPreviousData` across a period
     change: the previous drawing stays on screen, dimmed, instead of blanking for a round trip.

     `audienceFigures` is the same route and often the same query KEY as `audience.today`; when
     the picker sits on the base window the two share one cache entry and one request. */
  /* The churn card and the audience cards are drawn from this one response, both on the
     Audience tab only. Whenever the figure picker sits on the base window it is literally the
     same query key as the card band's, so the tab costs one request. */
  const audienceFigures = useAudience(figurePeriod, { enabled: tab === "audience" });
  const vendor = useVendor(figurePeriod, { enabled: tab === "vendor" });
  const plans = usePlans({ enabled: tab === "finance" });
  /* `RECORDS_READ`, audited per call, no poll, and read on the Audience tab only: every
     distinct window written here buys an audit disclosure row saying an admin read customer
     identities, so the other three tabs must not ask for it. */
  const lists = useAudienceLists(figurePeriod, DEFAULT_AUDIENCE_LIST_LIMIT, {
    enabled: tab === "audience",
  });

  useSessionGuard([
    ...PERIODS.map((p) => audience[p].error),
    ...PERIODS.map((p) => finance[p].error),
    ...PERIODS.map((p) => performance[p].error),
    ...PERIODS.map((p) => sparkSeries[p].error),
    audienceFigures.error,
    vendor.error,
    plans.error,
    lists.error,
    pulse.error,
  ]);

  const audienceData = useDataMap(audience);
  const financeData = useDataMap(finance);
  const performanceData = useDataMap(performance);
  const sparkData = useDataMap(sparkSeries);

  const values: CardValues = useMemo(() => {
    /* The BASE response fills every card first, including ones whose selector has been moved.
       That ordering is deliberate: a card overwritten below keeps showing its previous figure
       while its own window is still in flight, instead of blanking on every click. */
    const out: Draft = {
      ...(audienceData.today === undefined ? {} : adaptAudience(audienceData.today, BASE_PERIOD)),
      ...(financeData.today === undefined ? {} : adaptFinance(financeData.today)),
      ...(performanceData.today === undefined
        ? {}
        : adaptPerformance(performanceData.today, pulse.data ?? null)),
    };

    const audienceByPeriod = adaptByPeriod(audienceData, adaptAudience);
    const financeByPeriod = adaptByPeriod(financeData, (d) => adaptFinance(d));
    const perfByPeriod = adaptByPeriod(performanceData, (d) =>
      adaptPerformance(d, pulse.data ?? null),
    );

    override(out, SEL_BY_READ.audience, cardPeriods, audienceByPeriod);
    override(out, SEL_BY_READ.finance, cardPeriods, financeByPeriod);
    override(out, SEL_BY_READ.performance, cardPeriods, perfByPeriod);

    /* Each well takes its points from the series at ITS card's window. Merging one period at a
       time — rather than one `adaptSparks` for the page — is what stops a card on `week` from
       being handed the `today` curve, which would draw a shape that contradicts its number. */
    let merged: CardValues = out;
    for (const p of PERIODS) {
      const response = sparkData[p];
      if (response === undefined) continue;
      const all = adaptSparks(response);
      const mine: Partial<Record<SparkKey, readonly number[]>> = {};
      for (const key of SPARK_KEYS) {
        if ((cardPeriods[key] ?? BASE_PERIOD) !== p) continue;
        const points = all[key];
        if (points !== undefined) mine[key] = points;
      }
      merged = mergeSparks(merged, mine);
    }
    return merged;
  }, [audienceData, financeData, performanceData, sparkData, pulse.data, cardPeriods]);

  const audienceState = sectionState(audience, audienceNeed, [audienceFigures]);
  const financeState = sectionState(finance, financeNeed);
  const performanceState = sectionState(performance, perfNeed);

  /* The header's FX line reads the BASE finance response: the published rate is a fact about
     the deployment, not about the window, so asking for it at four windows would be four
     identical answers. */
  const baseFinance = financeData.today;

  /* Everything a section is handed except its own band's state and its own figure reads. Built
     once so the four branches below cannot pass four slightly different sets. */
  const common: Omit<SectionProps, "state"> = {
    values,
    cardPeriods,
    onCardPeriodChange: setCardPeriod,
    figurePeriod,
    picker: (
      <Segmented
        options={periodOptions}
        value={figurePeriod}
        onChange={selectFigurePeriod}
        ariaLabel={t("dashboard.figureWindowAria")}
      />
    ),
    grans,
    onGranChange: setGran,
    finance: baseFinance ?? null,
  };

  return (
    <main className="py-6">
      {/* A TRUE 1392px content box, which is what every stat row is composed against
          (5 x 270.4 + 4 x 10, or 4 x 340.5 + 3 x 10). `max-w-[1392px] px-4` is 1360 under
          border-box, and the rows wrap at every width. The page ground and the min-height
          belong to `AppShell`; drawing them again here would paint a second background over
          the rail's own and stop the shell's row from stretching. */}
      <div className="mx-auto w-[min(1392px,100%-2rem)]">
        <header className="flex min-h-12 flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="m-0 text-[22px] font-bold leading-[1.1] tracking-[-.9px] text-ink-800">
              {t("dashboard.title")}
            </h1>
            {/* Three answers and a fourth silence: the published rate, `null` for a
                deployment that publishes none, `UNAVAILABLE` for a read that failed and so
                never heard either, and `undefined` while it is still in flight. */}
            <MetaLine
              fx={
                baseFinance?.fx ?? (finance[BASE_PERIOD].error === null ? undefined : UNAVAILABLE)
              }
            />
          </div>
          <SectionTabs tab={tab} />
        </header>

        {/* THE TOP OF THE AUDIENCE TAB, in this order: the audience stat cards, the churn
            card, the two identified-customer lists, then that tab's figures. Audience first
            because churn is a fraction of the population the cards count, and the lists last
            because they are the same people named. Still drawn by the page rather than by the
            section, because the band's two reads fail independently and that wiring is the
            page's — which is why the section itself stayed figures only. */}
        {tab === "audience" && (
          <>
            <AudienceBand
              state={audienceState}
              values={values}
              cardPeriods={cardPeriods}
              onCardPeriodChange={setCardPeriod}
              figures={audienceFigures}
              lists={lists}
            />
            <AudienceSection {...common} state={audienceState} figures={audienceFigures} />
          </>
        )}
        {tab === "finance" && <FinancesSection {...common} state={financeState} plans={plans} />}
        {tab === "vendor" && <VendorSection {...common} vendor={vendor} />}
        {tab === "performance" && <PerformanceSection {...common} state={performanceState} />}
      </div>
    </main>
  );
}

/* -------------------------------------------------------------------------- */
/* The band that opens the Audience tab                                        */
/* -------------------------------------------------------------------------- */

/**
 * The audience cards, then churn, then top generators and recent subscribers.
 *
 * Who is here, then who is leaving, then which of them by name. Churn under the cards rather
 * than over them is the point of the ordering — a churn rate is read against the population it
 * is a fraction of. This band drew on all four tabs for a while; it draws on Audience only,
 * because the two reads under it are enabled on Audience only and one of them is audited per
 * call.
 *
 * Two reads meet here and they fail INDEPENDENTLY, which is why one component draws all three:
 *
 *  - `/dashboard/audience` (`DASHBOARD_READ`) serves the stat cards AND the churn card. One
 *    route, so one note, drawn by `CardBand` above the cards; the churn card blocks quietly
 *    under it rather than repeating the same sentence.
 *  - `/dashboard/audience-lists` is **`RECORDS_READ`, not `DASHBOARD_READ`** — a narrower
 *    permission a role can legitimately lack. Its refusal renders INSIDE the two list cards,
 *    naming the role, and touches nothing else on the page.
 *
 * ## No reveal, no mask, anywhere near the lists
 *
 * `topGenerators` and `recentSubscribers` are the only payload on this screen that carries real
 * customer identity unmasked, and the owner's decision was audit logging INSTEAD OF a reveal
 * gate. A `null` name there is ABSENT, never withheld: there is no masked variant to reveal, so
 * a reveal control would be a button that cannot do anything, sitting beside data that is
 * already shown. Recipient names — the person a song is ABOUT — are a different quantity on a
 * different route and stay reveal-gated there.
 */
function AudienceBand({
  state,
  values,
  cardPeriods,
  onCardPeriodChange,
  figures,
  lists,
}: {
  readonly state: SectionState;
  readonly values: CardValues;
  readonly cardPeriods: CardPeriods;
  readonly onCardPeriodChange: (key: CardKey, period: Period) => void;
  readonly figures: Query<AudienceResponse>;
  readonly lists: Query<AudienceListsResponse>;
}): JSX.Element {
  const { t } = useI18n();
  const audience = figures.data;
  const blocked = audience === undefined && figures.error !== null;
  const dim = figures.isPlaceholderData;
  const notice = listsNotice(lists, t);
  const listsLoading = lists.data === undefined && lists.error === null;

  return (
    <>
      {/* WHO IS HERE, first. These are the `/dashboard/audience` cards, with the churn card and
          then the two lists under them — the order the tab has always had, and the order churn
          needs: a rate is read against the population it is a fraction of. */}
      <CardBand
        section="audience"
        subjectKey="dashboard.subjects.audience"
        state={state}
        values={values}
        cardPeriods={cardPeriods}
        onCardPeriodChange={onCardPeriodChange}
      />

      {/* Two churns in one card and never in one number: bot-block PASSAGES in the window on
          the left, a RATE over plans that ENDED on the right. Its own full-width slot because
          it splits itself into two columns at `sm` and would be four columns of nothing in a
          chart track. */}
      {!blocked && (
        <div className={cn("mb-[10px] transition-opacity", dim && "opacity-50")}>
          {audience === undefined ? (
            <ChurnCard {...CHURN_CARD_PENDING} />
          ) : (
            <ChurnCard {...adaptChurnCard(audience)} />
          )}
        </div>
      )}

      {/* A different permission, so a different heading and a different boundary. A 403 here
          leaves the churn card above it standing. */}
      <GroupLabel>{t("dashboard.figures.identifiedCustomers")}</GroupLabel>
      <FigureGrid minPx={LIST_MIN_PX}>
        <TopGenerators
          data={topGeneratorsOf(lists.data)}
          isLoading={listsLoading}
          notice={notice}
        />
        <RecentSubscribers
          data={recentSubscribersOf(lists.data)}
          isLoading={listsLoading}
          notice={notice}
        />
      </FigureGrid>
    </>
  );
}

/**
 * The denial, in the two cards' own `notice` slot.
 *
 * `noteFor` supplies the tone, the title and the correlation id — a 403 is `denied`, not
 * `error`, and is not offered a retry, because asking again buys another audit row and the same
 * refusal. The MESSAGE is `audienceListsNote`'s, which words the 403 as the permission fact it
 * is ("your role can read the aggregates but not customer records") rather than as a fault.
 */
function listsNotice(
  lists: Query<AudienceListsResponse>,
  t: (path: TranslationPath, params?: Record<string, string | number>) => string,
): ReactNode {
  const error: DashboardQueryError | null = lists.error;
  if (error === null) return undefined;
  const copy = noteFor(error, t("dashboard.subjects.customerLists"), false, t);
  return (
    <ErrorNote
      tone={copy.tone}
      title={copy.title}
      message={audienceListsNote(error.status)}
      hint={copy.hint}
      onRetry={
        copy.canRetry
          ? () => {
              void lists.refetch();
            }
          : undefined
      }
      isRetrying={lists.isFetching}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Header chrome                                                               */
/* -------------------------------------------------------------------------- */

/** The clock in the meta line only shows minutes; checking twice a minute is enough. */
const CLOCK_TICK_MS = 30_000;

function useTick(intervalMs: number): number {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => {
      setTick(Date.now());
    }, intervalMs);
    return () => {
      window.clearInterval(id);
    };
  }, [intervalMs]);
  return tick;
}

/**
 * `08:04 · UTC+5 · 1 USD = 12 800 soʻm (05 Sep)`, or the same line saying there is no rate.
 *
 * Its own component so the per-minute clock re-renders one paragraph rather than a band of
 * cards and a page of SVGs. FOUR states, and the last two are not the same statement:
 * `undefined` is "finance has not answered yet", `UNAVAILABLE` is "the read failed, so this
 * page never heard", and `null` is the deployment saying it publishes no rate at all.
 */
function MetaLine({ fx }: { readonly fx: FxState | undefined }): JSX.Element {
  const { t, locale } = useI18n();
  const tick = useTick(CLOCK_TICK_MS);
  return (
    <p className="mb-0 mt-[2px] flex h-[14px] items-center text-xs font-normal leading-[1.2] text-ink-400">
      {fx === undefined ? (
        <Skeleton className="h-[9px] w-[228px]" />
      ) : (
        headerMeta(new Date(tick), fx, t, locale)
      )}
    </p>
  );
}

/* -------------------------------------------------------------------------- */
/* The session                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * A 401 on any read ends the session HERE.
 *
 * `state/auth.ts` says the app learns about an expired session on the next `me()` — which,
 * before this screen called the API, meant the next page load. A panel that keeps polling
 * routes with a dead cookie shows an operator a page of frozen numbers and no reason for it,
 * so the first 401 clears the tab through `signOut()` and `RequireAuth` takes it to `/login`.
 * `signOut()` posts a logout the server will refuse — the store drops this tab whatever the API
 * answers, which is exactly the behaviour wanted here.
 *
 * The per-chart series queries are deliberately absent from the list, as they always were: a
 * chart renders its own failure in its own card, and it is mounted or not depending on the tab.
 * Every read that survives a tab change is watched.
 */
function useSessionGuard(errors: readonly (DashboardQueryError | null)[]): void {
  const signOut = useAuthStore((state) => state.signOut);
  const done = useRef(false);
  const expired = errors.some((error) => error !== null && error.status === 401);

  useEffect(() => {
    if (!expired || done.current) return;
    // Once: several queries reach 401 within a tick of each other, and several logouts is a
    // pile of audit rows saying nothing new.
    done.current = true;
    void signOut();
  }, [expired, signOut]);
}
