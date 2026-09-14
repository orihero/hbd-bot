/**
 * The parts every tab draws with: a group heading, a failed read as something an operator can
 * act on, the stat band, the figure grid, and one series chart with its own bucket.
 *
 * All of it came out of `DashboardPage.tsx` unchanged when the page became four tabs. It lives
 * here rather than in the page because a section is now a FILE — `AudienceSection` and
 * `VendorSection` both draw a stat band and both need the same failure copy, and a second copy
 * of `noteFor` is how two tabs start wording a 403 differently.
 *
 * Nothing in this module fetches except `ChartPanel`, which has to: each chart's granularity
 * toggle picks a different `?bucket=` and a hook cannot be called in a loop, so the query lives
 * in the per-chart component exactly as it always did.
 */

import { useMemo, type CSSProperties, type JSX, type ReactNode } from "react";

import { CLIENT_ERROR_CODES } from "@/api/client";
import type { FinanceResponse } from "@/api/dashboard";
import { ErrorNote, type NoteTone } from "@/components/ErrorNote";
import { Skeleton } from "@/components/Skeleton";
import { ChartCard } from "@/features/dashboard/ChartCard";
import { StatCard } from "@/features/dashboard/StatCard";
import { adaptSeries, type CardValues } from "@/features/dashboard/adapt";
import { cardRowsFor, type CardKey, type SectionKey } from "@/features/dashboard/cardSpecs";
import { granOptions, type ChartSpec } from "@/features/dashboard/chartSpecs";
import { granFor, type Gran, type Period, type Translate } from "@/features/dashboard/data";
import { useSeries, type DashboardQueryError } from "@/features/dashboard/useDashboardData";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";

/**
 * The window every card without a selector of its own is pinned to, and the one a card with a
 * selector starts on. Also the FIGURE picker's starting value.
 *
 * `today` because it is what the mockup opened on, and because the pinned cards are the ones a
 * window barely applies to: `totalUsers` and `vendorBalance` are the same number whichever of
 * the four is asked for.
 */
export const BASE_PERIOD: Period = "today";

/** One period per card key. An absent entry IS `BASE_PERIOD`; only `sel` cards ever get one. */
export type CardPeriods = Readonly<Partial<Record<CardKey, Period>>>;

/** Which bucket each toggle-bearing chart is currently drawn at, keyed by `ChartSpec.key`. */
export type GranMap = Readonly<Record<string, Gran>>;

/* -------------------------------------------------------------------------- */
/* What every tab is handed                                                    */
/* -------------------------------------------------------------------------- */

/**
 * The state and callbacks every section needs, whichever figures it happens to draw.
 *
 * A section is PRESENTATION: it fetches nothing except through `ChartPanel` (whose query is
 * per-chart by necessity) and it holds no state of its own. Everything below is owned by
 * `DashboardPage`, which is where the read count and the three period scopes are argued —
 * a section that kept its own period would be a fourth scope nobody declared.
 */
export interface SectionProps {
  /** The read behind THIS tab's stat cards. Vendor's cards come off the finance read. */
  readonly state: SectionState;
  readonly values: CardValues;
  readonly cardPeriods: CardPeriods;
  readonly onCardPeriodChange: (key: CardKey, period: Period) => void;
  /** The window every FIGURE in this tab is drawn over. No stat card obeys it. */
  readonly figurePeriod: Period;
  /** The picker for the above, built once by the page so all four tabs move one value. */
  readonly picker: ReactNode;
  readonly grans: GranMap;
  readonly onGranChange: (key: string, gran: Gran) => void;
  /** The BASE finance response — the FX rate and the published price, neither windowed. */
  readonly finance: FinanceResponse | null;
}

/* -------------------------------------------------------------------------- */
/* What a section knows about the read behind it                               */
/* -------------------------------------------------------------------------- */

export interface SectionState {
  /** True only before the FIRST answer. A failing refresh over good numbers is not loading. */
  readonly isLoading: boolean;
  /**
   * True while the numbers on screen belong to the PREVIOUS window.
   *
   * `keepPreviousData` is what stops the page blanking on every re-key, and the cost of it is
   * that a period change relabels last year's figures as today's for the length of a round
   * trip — the one failure mode a dashboard cannot recover from, because nothing on screen
   * looks wrong. Consuming the flag is what makes it look wrong.
   */
  readonly isPlaceholder: boolean;
  readonly error: DashboardQueryError | null;
  readonly hasData: boolean;
  readonly isFetching: boolean;
  readonly retry: () => void;
}

/** Only what a section reads off a query, so any `UseQueryResult` satisfies it. */
export interface Query<T> {
  readonly data: T | undefined;
  readonly error: DashboardQueryError | null;
  readonly isPlaceholderData: boolean;
  readonly isFetching: boolean;
  readonly refetch: () => unknown;
}

export type AnyQuery = Query<unknown>;

/** One query's state, in the shape a band or a figure group renders from. */
export function stateOf(query: AnyQuery): SectionState {
  return {
    isLoading: query.data === undefined && query.error === null,
    isPlaceholder: query.isPlaceholderData,
    error: query.error,
    hasData: query.data !== undefined,
    isFetching: query.isFetching,
    retry: () => {
      void query.refetch();
    },
  };
}

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

interface NoteCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly hint: string | undefined;
  /** False when asking again cannot change the answer. */
  readonly canRetry: boolean;
}

/**
 * A failed read, as something an operator can act on.
 *
 * The status is the fact that matters, not the message: 403 is a permission statement and not
 * an error at all, `status: 0` never reached the process, and a schema drift means this bundle
 * and the server disagree about the contract — retrying any of the three re-runs a decision,
 * not a request. The server's own message is always carried verbatim underneath, because that
 * is the string an operator greps the logs for.
 */
export function noteFor(
  error: DashboardQueryError,
  subject: string,
  isStale: boolean,
  t: Translate,
): NoteCopy {
  const hint = `${error.endpoint} · ${error.correlationId ?? t("dashboard.note.noCorrelationId")}`;

  if (error.status === 403) {
    return {
      tone: "denied",
      title: t("dashboard.note.deniedTitle", { subject }),
      message: t("dashboard.note.deniedMessage"),
      hint,
      canRetry: false,
    };
  }

  if (error.code === CLIENT_ERROR_CODES.schemaDrift) {
    const paths = (error.issues ?? []).map((issue) => issue.path).join(", ");
    return {
      tone: "error",
      title: t("dashboard.note.driftTitle", { subject }),
      message: paths === "" ? error.message : `${error.message} (${paths})`,
      hint,
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("dashboard.note.refusedTitle", { subject }),
      message: t("dashboard.note.refusedMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (isStale) {
    return {
      tone: "stale",
      title: t("dashboard.note.staleTitle", { subject }),
      message: t("dashboard.note.staleMessage", { message: error.message }),
      hint,
      canRetry: true,
    };
  }

  if (error.status === 0) {
    return {
      tone: "offline",
      title: t("dashboard.note.offlineTitle", { subject }),
      message: error.message,
      hint,
      canRetry: true,
    };
  }

  return {
    tone: "error",
    title: t("dashboard.note.failedTitle", { subject }),
    message: error.message,
    hint,
    canRetry: true,
  };
}

export function SectionNote({
  state,
  subjectKey,
}: {
  readonly state: SectionState;
  readonly subjectKey: TranslationPath;
}): JSX.Element | null {
  const { t } = useI18n();
  if (state.error === null) return null;
  const copy = noteFor(state.error, t(subjectKey), state.hasData, t);
  return (
    <div className="mb-[10px]">
      <ErrorNote
        tone={copy.tone}
        title={copy.title}
        message={copy.message}
        hint={copy.hint}
        onRetry={copy.canRetry ? state.retry : undefined}
        isRetrying={state.isFetching}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Headings                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * A heading, not a styled div: as a `<div>` the group labels were invisible to heading
 * navigation, so the document outline went straight from the `<h1>` to the chart titles and a
 * screen-reader user passed a whole band of cards without learning they were grouped.
 */
export function GroupLabel({
  children,
  className,
}: {
  readonly children: string;
  /** Only for a label that sits in a flex row with a picker and owns no margin. */
  readonly className?: string;
}): JSX.Element {
  return (
    <h2
      className={cn(
        "m-0 mb-1 mt-[14px] h-[14px] text-[11px] font-bold uppercase leading-[14px] tracking-[.12em] text-ink-300",
        className,
      )}
    >
      {children}
    </h2>
  );
}

/* -------------------------------------------------------------------------- */
/* The stat band                                                               */
/* -------------------------------------------------------------------------- */

/**
 * A stat row's tracks.
 *
 * The mockup is a fixed 1440px stage and simply states each row's card width (270.4 for the
 * five-card rows, 340.5 for the four-card ones). Reproducing that as a wrapping flex row with
 * `grow` is what it looks like at first, and it is wrong: the instant the band is a few pixels
 * narrower than the row's exact composition the last card wraps ALONE and stretches to the full
 * 1392, which the mockup never does. `auto-fit` keeps every card in a track of equal width and
 * drops a whole column at a time instead.
 *
 * The floor is the design width less 60px, not the design width: `auto-fit` collapses the empty
 * tracks and shares the band equally, so at the design's 1392 band each row still lands on its
 * exact card width (1392 - 40 gaps over 5 tracks IS 270.4). The slack only buys the row a lower
 * breakpoint — five across and four across survive down to ~1170px, which is the viewport this
 * console is actually read at.
 */
function trackStyle(width: number): CSSProperties {
  const floor = Math.round(width) - 60;
  return {
    gridTemplateColumns: `repeat(auto-fit, minmax(min(${String(floor)}px, 100%), 1fr))`,
  };
}

/**
 * Every stat card one tab draws, with the note for the read behind them.
 *
 * `subject` is passed rather than derived because a tab's cards and the read that serves them
 * are two different things: Vendor's four cards come off the FINANCE response, and a note
 * headed "Finances" under a tab called Vendor names a section the operator is not looking at.
 */
export function CardBand({
  section,
  subjectKey,
  state,
  values,
  cardPeriods,
  onCardPeriodChange,
}: {
  readonly section: SectionKey;
  readonly subjectKey: TranslationPath;
  readonly state: SectionState;
  readonly values: CardValues;
  readonly cardPeriods: CardPeriods;
  readonly onCardPeriodChange: (key: CardKey, period: Period) => void;
}): JSX.Element {
  const { t } = useI18n();
  const rows = cardRowsFor(section);
  /* A read that failed with nothing to show draws the note and no cards; a read that failed
     over good numbers draws both, and the note says the figures are the last good answer. */
  const blocked = state.error !== null && !state.hasData;

  return (
    <>
      {rows.map((row, i) => (
        <section key={row.labelKey ?? `row-${String(i)}`}>
          {row.labelKey !== null && <GroupLabel>{t(row.labelKey)}</GroupLabel>}
          {/* The note is a statement about the READ, so it is drawn once, above the first of
              however many rows that read serves. */}
          {i === 0 && <SectionNote state={state} subjectKey={subjectKey} />}
          {!blocked && (
            <div
              aria-busy={state.isPlaceholder}
              className={cn(
                "mb-[10px] grid gap-[10px] transition-opacity",
                state.isPlaceholder && "opacity-50",
              )}
              style={trackStyle(row.w)}
            >
              {row.cards.map((card) => (
                <StatCard
                  key={card.key}
                  spec={card}
                  value={values[card.key]}
                  isLoading={state.isLoading}
                  /* This card's own window. A card with no selector never leaves the base
                     one, so passing it is the same as pinning it. */
                  period={cardPeriods[card.key] ?? BASE_PERIOD}
                  onPeriodChange={(p) => {
                    onCardPeriodChange(card.key, p);
                  }}
                />
              ))}
            </div>
          )}
        </section>
      ))}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* The figure grid                                                             */
/* -------------------------------------------------------------------------- */

/**
 * The narrowest a figure column may get before the drawing stops being a drawing.
 *
 * 610 was the width at which an 8px axis label is still drawn at its natural size, and holding
 * it meant two columns needed a 1230px band — which the rail expanded (264px) never leaves on a
 * 1440px screen, so every figure on the page was drawn ALONE across the whole band, at roughly
 * 380px tall. One chart per row is not a comparison; the owner reads revenue against cost and
 * sign-ups against active accounts side by side.
 *
 * 470 puts two across from a ~950px band, which the rail expanded does leave, and it CANNOT
 * give three: the content box is capped at 1392px and three tracks would need 1430. So the
 * figure grid is one column or two, never a thin third. The 651-unit viewBox scales with the
 * column, so at 470 the 8px labels are drawn at about 0.67 — smaller than the drawing was laid
 * out for, and the trade the owner asked for.
 *
 * A VIEWPORT media query cannot express any of this: the rail is 264px expanded and 72px
 * collapsed, so the same window width yields two very different bands. `auto-fit` measures the
 * grid's own width and therefore follows the rail.
 */
export const FIGURE_MIN_PX = 470;

/** A list row is HTML, not a 651-unit drawing, and stays readable in a much narrower column. */
export const LIST_MIN_PX = 420;

/**
 * One row of figures, as many across as fit.
 *
 * A PAIR that must be a pair gets its own `FigureGrid` rather than sharing one with its
 * neighbours: inside its own grid the two are either both across (above `2 x minPx + gap`) or
 * both stacked, and there is no width at which one of them is orphaned onto a second row by a
 * chart that happens to precede it.
 */
export function FigureGrid({
  children,
  minPx = FIGURE_MIN_PX,
}: {
  readonly children: ReactNode;
  readonly minPx?: number;
}): JSX.Element {
  return (
    <div
      className="mb-[10px] grid gap-[10px]"
      style={{
        gridTemplateColumns: `repeat(auto-fit, minmax(min(${String(minPx)}px, 100%), 1fr))`,
      }}
    >
      {children}
    </div>
  );
}

/**
 * Figures that each need the WHOLE band, one under another.
 *
 * `minmax(0, 1fr)` rather than an `auto-fit` track wide enough to never double up, because
 * "always one column" is the statement being made: a vendor lane already carries two or three
 * lines of type at the 8px floor, and there is no viewport wide enough to make two of them
 * across a good idea.
 */
export function FigureStack({ children }: { readonly children: ReactNode }): JSX.Element {
  return (
    <div className="mb-[10px] grid gap-[10px]" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
      {children}
    </div>
  );
}

/**
 * A figure that is NOT one of the six series charts: same card chrome, no granularity toggle,
 * no query of its own.
 *
 * `ratio` is the figure's own viewBox ratio. Every drawing in `charts/` uses
 * `preserveAspectRatio="xMidYMid meet"`, so a box of the wrong ratio pads rather than crops —
 * but a 651x352 table in a 651x176 box would be padded down to half the height it was drawn
 * for, and house rule 3 forbids buying room back by shrinking the type.
 */
export function FigureCard({
  title,
  sub,
  cov,
  ratio,
  isPlaceholder,
  children,
}: {
  readonly title: string;
  /** Optional, and on the dashboard's own figures now always absent — see `TranslationTree`. */
  readonly sub?: string | undefined;
  readonly cov?: string | undefined;
  readonly ratio?: string | undefined;
  readonly isPlaceholder: boolean;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <ChartCard title={title} sub={sub} cov={cov} ratio={ratio}>
      {/* Same rule as the card bands: figures from the previous window are dimmed rather than
          passed off as this one's. */}
      <div
        aria-busy={isPlaceholder}
        className={cn(
          "h-full w-full transition-opacity [&>svg]:h-full [&>svg]:w-full",
          isPlaceholder && "opacity-50",
        )}
      >
        {children}
      </div>
    </ChartCard>
  );
}

/* -------------------------------------------------------------------------- */
/* Series charts                                                               */
/* -------------------------------------------------------------------------- */

/**
 * The grain a chart with no toggle is fetched at.
 *
 * `costSplit` and `orderFunnel` are window aggregates that ride along on the series response
 * and do not vary with the bucket at all — but the request still has to name one. Naming the
 * coarse charts' default means the query key matches theirs and the page fetches one series
 * rather than two identical ones.
 */
const UNTOGGLED_GRANS: readonly Gran[] = ["daily", "weekly", "monthly"];

export function granOr(grans: readonly Gran[], period: Period, fallback: Gran): Gran {
  return granFor(grans, period) ?? fallback;
}

/**
 * One chart, with its own bucket and therefore its own read.
 *
 * A component per chart rather than a loop in the page, because each toggle picks a different
 * `?bucket=` and a hook cannot be called in a loop. Charts left on their default grain share
 * one query key and so one request; only a chart the operator has actually toggled costs a
 * second read.
 *
 * A chart in a tab nobody is looking at is UNMOUNTED, and its query goes inactive with it —
 * which is the whole reason the per-chart hook survived the split unchanged: the tabs gate the
 * series reads for free, with no `enabled` flag to keep in step with the layout.
 */
export function ChartPanel({
  spec,
  period,
  gran,
  onGranChange,
  finance,
}: {
  readonly spec: ChartSpec;
  readonly period: Period;
  readonly gran: Gran | undefined;
  readonly onGranChange: (g: Gran) => void;
  readonly finance: FinanceResponse | null;
}): JSX.Element {
  const { t } = useI18n();
  const effective = gran ?? granOr(UNTOGGLED_GRANS, period, "daily");
  const query = useSeries(period, effective);
  const data = query.data ?? null;
  /* The toggle offers only grains this window can legally be served at: `?bucket=hour` over
     more than eight days is a 422, and a grain as long as the window draws one column. */
  const options = granOptions(spec.grans, period, t);

  /* `finance` is read for exactly two things the series response does not carry: the FX rate
     the cost line is converted at, and the published price the cost-per-song ceiling is drawn
     from. Without it those two degrade to an empty cost line and no price line — never a guess. */
  const charts = useMemo(() => (data === null ? null : adaptSeries(data, finance)), [data, finance]);

  // One option is not a choice; the chart is drawn at it either way.
  const hasToggle = options.length > 1;

  return (
    <ChartCard
      title={t(spec.titleKey)}
      /* The caption is a function of the data: one of the six states a unit the window chose,
         and until the window has answered it says which unit it is waiting on. */
      sub={spec.sub(charts, t)}
      cov={spec.covKey === undefined ? undefined : t(spec.covKey)}
      options={hasToggle ? options : undefined}
      gran={hasToggle ? effective : undefined}
      onGranChange={hasToggle ? onGranChange : undefined}
    >
      <div
        aria-busy={query.isPlaceholderData}
        /* Carries the figure's sizing rules with it: `ChartCard`'s box styles its own child,
           and this wrapper is now that child. */
        className={cn(
          "h-full w-full transition-opacity [&>svg]:h-full [&>svg]:w-full",
          query.isPlaceholderData && "opacity-50",
        )}
      >
        {charts === null ? (
          query.error === null ? (
            <Skeleton className="h-full w-full rounded-card" />
          ) : (
            <div className="flex h-full items-center">
              <ChartNote
                error={query.error}
                title={t(spec.titleKey)}
                isFetching={query.isFetching}
                onRetry={() => {
                  void query.refetch();
                }}
              />
            </div>
          )
        ) : (
          /* The figure itself draws its own empty state; a window with no sign-ups is a fact
             about the window, not a failure of this panel. */
          spec.render(charts)
        )}
      </div>
    </ChartCard>
  );
}

function ChartNote({
  error,
  title,
  isFetching,
  onRetry,
}: {
  readonly error: DashboardQueryError;
  readonly title: string;
  readonly isFetching: boolean;
  readonly onRetry: () => void;
}): JSX.Element {
  const { t } = useI18n();
  const copy = noteFor(error, title, false, t);
  return (
    <div className="w-full">
      <ErrorNote
        tone={copy.tone}
        title={copy.title}
        message={copy.message}
        hint={copy.hint}
        onRetry={copy.canRetry ? onRetry : undefined}
        isRetrying={isFetching}
      />
    </div>
  );
}

/**
 * Every series chart one tab draws, in `chartSpecs.tsx`'s order — as grid CHILDREN, not as a
 * grid.
 *
 * A fragment rather than a row because a tab's series charts and its route-fed figures belong
 * in ONE grid: Sign-ups beside Active accounts is a pair the operator reads together, and two
 * adjacent grids would break the pair apart at exactly the widths where both would have fitted.
 */
export function ChartPanels({
  specs,
  period,
  grans,
  onGranChange,
  finance,
}: {
  readonly specs: readonly ChartSpec[];
  readonly period: Period;
  readonly grans: GranMap;
  readonly onGranChange: (key: string, gran: Gran) => void;
  readonly finance: FinanceResponse | null;
}): JSX.Element {
  return (
    <>
      {specs.map((spec) => (
        <ChartPanel
          key={spec.key}
          spec={spec}
          period={period}
          gran={grans[spec.key]}
          onGranChange={(g) => {
            onGranChange(spec.key, g);
          }}
          /* The BASE response, not one at the figure period: the two things a chart reads from
             finance are the FX rate and the published unit price, and neither is a function of
             the window. Asking again at the figure period would be a second request for the
             same two constants. */
          finance={finance}
        />
      ))}
    </>
  );
}

/** A figure that has not answered yet, in the card's own box. */
export function FigureSkeleton(): JSX.Element {
  return <Skeleton className="h-full w-full rounded-card" />;
}

/**
 * The picker that moves every FIGURE in a tab, on the group label they sit under.
 *
 * On the label rather than on each panel: the figures in one tab are read against each other
 * constantly — revenue against cost, sign-ups against active accounts, spend against the units
 * it bought — and a window per panel is a window per panel to put two of them on different
 * months without noticing. The per-chart toggle stays what it always was, the GRAIN, which is
 * a question about one chart's resolution rather than about which window it covers.
 *
 * It is NOT a page period: no stat card obeys it, and the cards keep their own selectors.
 */
export function FigureHeading({
  label,
  children,
}: {
  readonly label: string;
  /** The period picker. Omitted by a group whose figures take no window at all. */
  readonly children?: ReactNode;
}): JSX.Element {
  return (
    /* `mb-[14px]`, and it is not decoration: the picker is a control that sits directly on top
       of the figures it moves, and with no gap under it the segmented switch read as chrome
       attached to the first chart's header rather than as a heading for the group. The margin
       is the same 14px that separates the heading from what precedes it. */
    <div className="mb-[14px] mt-[14px] flex flex-wrap items-center justify-between gap-2">
      <GroupLabel className="m-0">{label}</GroupLabel>
      {children}
    </div>
  );
}
