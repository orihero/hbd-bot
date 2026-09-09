/**
 * `/generations/names` — "What should `HBD_NAME_CANDIDATE_ORDER` be?" (§11.2)
 *
 * §11.2's dominant signal is "per-strategy bake-off bars + a similarity histogram with the
 * threshold marked, **linking straight to `/config`**". Both are above the fold and side by
 * side, because the decision needs both halves: the bars say which orthography wins, the
 * histogram says whether the threshold that decided those wins is in the right place.
 *
 * ## One endpoint, one window, one population
 *
 * The whole screen reads `GET /api/metrics/name-analytics`. That is deliberate and it is
 * the fix for the thing this screen used to get wrong: the bars came from a `GROUP BY` over
 * the window and the histogram came from ONE KEYSET PAGE of `/api/generations`, so the two
 * halves of a single argument were counted over different samples, and the screen said so
 * in small type ("most recent 200 scored attempts — the window holds more"). A distribution
 * capped at two hundred rows cannot argue about a threshold that decided ten thousand.
 *
 * The server now counts every scored attempt in the window, in the database, over the same
 * population as the bars: `name_candidate_strategy IS NOT NULL AND is_name_verified IS NOT
 * NULL`. Rows where verification did not run are in neither.
 *
 * ## The number this screen exists for
 *
 * `nearThreshold` — how many scored attempts sit within `thresholdBand` of
 * `name_match_min_similarity` — is the dominant figure, not a footnote. It is the only
 * number that answers "is moving the threshold safe": a bake-off can say `stripped` wins,
 * and it is worth nothing if a nudge of 0.05 would flip a third of the verdicts. It is
 * `null` exactly when `threshold` is, and null means **this deployment publishes no
 * threshold** — never zero. In that state the tile says so and points at the setting.
 *
 * ## An empty window is not a measured zero
 *
 * `hasRecordedAttempts` is a window-IGNORING probe, and it is what lets an empty result say
 * which kind of empty it is: "nothing in the range you chose" (§11.4 Empty-FILTERED, whose
 * remedy is to widen the window, and which names the window it found nothing in) versus
 * "verification has never run here" (Empty-VIRGIN, which has no remedy). A chart of twenty
 * empty bars says neither, and reads as a measured result.
 *
 * ## The shape of the page
 *
 * Header (title, breadcrumb, and the near-threshold tile as the dominant signal) →
 * "Evidence", the two argument halves side by side → "Recommendation", the line to paste.
 *
 * The section labels sit ABOVE the cards, as plain text on the page ground, and the cards
 * carry no border at all: `--surface-card` at 28px plus `--shadow-card` is the whole
 * separation. `StrategyBakeoffChart` and `SimilarityHistogram` are each already a card and
 * title themselves, so "Evidence" names the GROUP rather than repeating either — wrapping
 * one of them in a panel here would render a card inside a card.
 *
 * The two footnotes under the charts (the denominator and the sample size) stay OUTSIDE the
 * cards, on the ground, because they qualify the whole claim rather than one mark in it.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";
import { Link } from "react-router-dom";
import { z } from "zod";

import { getNameAnalytics, unwrapAsync, type NameAnalyticsView, type WindowQuery } from "@/api";
import { StatTile, TimeRangePicker, type TimeRange } from "@/components/data";
import { SimilarityHistogram, StrategyBakeoffChart } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, CopyButton, Skeleton } from "@/components/util";
import {
  EMPTY_VALUE,
  formatInteger,
  formatRate,
  formatTimestamp,
  humaniseEnum,
  queryKeys,
  useSearchParamsState,
  usePrefsStore,
  zInstantParam,
  type SearchParamsSchema,
  type TimeZoneMode,
} from "@/lib";
import { href } from "@/routes";

import {
  CANDIDATE_ORDER_ENV,
  candidateOrderValue,
  hasBakeoffEvidence,
  overallVerification,
  suggestedCandidateOrder,
} from "./verification";

const nameStrategiesFilterSchema = z.object({
  from: zInstantParam,
  to: zInstantParam,
}) satisfies SearchParamsSchema<NameStrategiesFilters>;

/** The codecs' OUTPUT. See the note in `features/users/UsersScreen.tsx`. */
type NameStrategiesFilters = {
  from?: string | undefined;
  to?: string | undefined;
};

const NAME_STRATEGIES_FALLBACK: NameStrategiesFilters = {};

/** §11.2's link target, spelled once. */
export const THRESHOLD_CONFIG_LINK_LABEL = "name_match_min_similarity in config →";

/** What the cliff tile says when the deployment never published the worker's threshold. */
export const THRESHOLD_UNPUBLISHED_HINT =
  "This deployment publishes no threshold, so there is no band to count inside. Set HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY to the worker's value.";

/** The window, as an operator would say it. `null` is the whole record. */
function windowLabel(
  analytics: Pick<NameAnalyticsView, "window">,
  mode: TimeZoneMode,
): string {
  if (analytics.window === null) return "the whole record";
  return `${formatTimestamp(analytics.window.from, mode)} → ${formatTimestamp(analytics.window.to, mode)}`;
}

export function NameStrategiesScreen(): ReactElement {
  const filters = useSearchParamsState(nameStrategiesFilterSchema, NAME_STRATEGIES_FALLBACK);
  const { value, patch } = filters;
  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);

  const metricsWindow = useMemo<WindowQuery>(
    () => ({ from: value.from, to: value.to }),
    [value.from, value.to],
  );

  const analytics = useQuery({
    queryKey: queryKeys.metrics.nameAnalytics(metricsWindow),
    queryFn: ({ signal }) => unwrapAsync(getNameAnalytics(metricsWindow, { signal })),
  });

  const view = analytics.data ?? null;
  const rows = useMemo(() => view?.strategies ?? [], [view]);
  const totals = useMemo(() => overallVerification(rows), [rows]);
  const order = useMemo(() => suggestedCandidateOrder(rows), [rows]);

  const isEmptyWindow = view !== null && view.attempts === 0;
  /*
   * `hasRecordedAttempts` decides WHICH empty, not the URL. A window that excludes
   * everything is Empty-filtered even when the operator arrived by a pasted link; a
   * deployment where verification has never run is Empty-virgin even with a window applied,
   * because widening it would not help. `resolveAsyncState` branches on the filter count,
   * so this is the count it is told.
   */
  const emptinessFilterCount =
    view !== null && view.hasRecordedAttempts ? Math.max(filters.activeCount, 1) : 0;

  const boundary = {
    status: analytics.status,
    hasData: analytics.data !== undefined,
    isEmpty: isEmptyWindow,
    activeFilterCount: emptinessFilterCount,
    onClearFilters: filters.clear,
    error: analytics.error,
    onRetry: () => {
      void analytics.refetch();
    },
    dataUpdatedAt: analytics.dataUpdatedAt,
    emptyFilteredTitle: "No verification ran in this window",
    emptyFilteredBody: (
      <>
        Nothing was scored between{" "}
        <span className="num">{view === null ? EMPTY_VALUE : windowLabel(view, timeZoneMode)}</span>
        . Widen the range — this is an empty window, not a measured zero.
      </>
    ),
    emptyTitle: "No verification has ever run here",
    emptyBody:
      "A row appears once the verifier scores a candidate. Rows where verification did not run are excluded from both counts, so a disabled verifier shows as nothing rather than as zero.",
  } as const;

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        title="name strategies"
        description={`What should ${CANDIDATE_ORDER_ENV} be?`}
        signal={
          <AsyncBoundary
            status={analytics.status}
            hasData={analytics.data !== undefined}
            error={analytics.error}
            onRetry={() => {
              void analytics.refetch();
            }}
            {...(analytics.isError ? { dataUpdatedAt: analytics.dataUpdatedAt } : {})}
            noun="the near-threshold count"
            skeleton={<Skeleton className="h-[10rem] w-72 rounded-card" />}
          >
            <div data-testid="near-threshold-signal">
              <NearThresholdTile view={view} />
            </div>
          </AsyncBoundary>
        }
      >
        <TimeRangePicker
          value={{ from: value.from, to: value.to }}
          /* The picker emits both bounds or neither by construction. Not a requirement any
             more — every windowed route accepts a lone bound now, and `windowParams` sends
             one — but a preset pinned to two fixed instants is what makes this screen's URL
             mean the same population to whoever it is pasted to. */
          onChange={(next: TimeRange) => {
            patch({ from: next.from, to: next.to });
          }}
        />
      </PageHeader>

      <div className="flex min-h-0 flex-col gap-8 px-gutter pb-gutter">
        <section className="flex flex-col gap-3" aria-label="evidence">
          {/* One plain label over the GROUP; each card below already titles itself. */}
          <h2 className="type-h3 text-ink">Evidence</h2>

          <div className="grid grid-cols-1 gap-gutter xl:grid-cols-2">
            <section aria-label="bake-off">
              <AsyncBoundary
                {...boundary}
                isEmpty={isEmptyWindow || !hasBakeoffEvidence(rows)}
                noun="strategy outcomes"
                skeleton={<Skeleton height="17rem" className="w-full rounded-card" />}
              >
                <div className="flex flex-col gap-2">
                  <StrategyBakeoffChart rows={rows} />
                  {/*
                    The denominator qualifies the whole card, so it sits UNDER it on the page
                    ground rather than inside the card's own footer — but INSIDE the boundary,
                    which is load-bearing: outside it, a pending query renders
                    "— overall · 0/0 verified in —" as though it had been measured. The whole
                    screen exists to refuse numbers of exactly that kind.
                  */}
                  <p className="type-body-sm flex flex-wrap items-baseline justify-between gap-2 px-1 text-ink-muted">
                    <span className="num" data-testid="bakeoff-denominator">
                      {`${formatRate(totals.rate)} overall · ${formatInteger(totals.verified)}/${formatInteger(totals.attempts)} verified in ${view === null ? EMPTY_VALUE : windowLabel(view, timeZoneMode)}`}
                    </span>
                  </p>
                </div>
              </AsyncBoundary>
            </section>

            <section aria-label="match confidence">
              <AsyncBoundary
                {...boundary}
                noun="scored attempts"
                skeleton={<Skeleton height="17rem" className="w-full rounded-card" />}
              >
                <div className="flex flex-col gap-2">
                  <SimilarityHistogram
                    buckets={view?.buckets ?? []}
                    threshold={view?.threshold ?? null}
                    {...(view === null ? {} : { band: view.thresholdBand })}
                    {...(view === null ? {} : { nearThreshold: view.nearThreshold })}
                  />
                  {/* Inside the boundary for the same reason as the denominator above: a
                      pending query must not print "0 scored attempts in this window". */}
                  <p className="type-body-sm flex flex-wrap items-baseline justify-between gap-2 px-1 text-ink-muted">
                    <span className="num" data-testid="similarity-sample-note">
                      {`${formatInteger(view?.scored ?? 0)} scored attempts in this window`}
                    </span>
                    {/* §11.2: "linking straight to /config". */}
                    <Link
                      to={href.config()}
                      data-testid="threshold-config-link"
                      className="text-brand underline-offset-4 hover:underline"
                    >
                      {THRESHOLD_CONFIG_LINK_LABEL}
                    </Link>
                  </p>
                </div>
              </AsyncBoundary>
            </section>
          </div>
        </section>

        <section className="flex flex-col gap-3" aria-label="suggested candidate order">
          <h2 className="type-h3 text-ink">Recommendation</h2>

          <div className="flex flex-col gap-4 rounded-card bg-surface-card p-card shadow-card">
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="type-h2 text-ink">suggested candidate order</h3>
              <span className="type-body-sm text-ink-muted">
                apply by reordering the environment variable — never by editing code
              </span>
            </header>

            {hasBakeoffEvidence(rows) ? (
              <>
                <ol
                  className="flex flex-wrap items-center gap-2"
                  data-testid="suggested-order"
                >
                  {order.map((strategy, index) => (
                    <li
                      key={strategy}
                      data-strategy={strategy}
                      /* The rank is the second channel: position in the list is the claim,
                         and the number says it again for anyone reading the row out of
                         order or wrapped onto a second line. */
                      className="type-body-sm inline-flex items-baseline gap-2 rounded-pill bg-surface-control px-3 py-1 text-ink"
                    >
                      <span className="num text-ink-muted">{formatInteger(index + 1)}</span>
                      <span>{humaniseEnum(strategy)}</span>
                    </li>
                  ))}
                </ol>

                <p className="type-mono flex flex-wrap items-center gap-2 rounded-control bg-surface-sunken px-4 py-3 text-ink">
                  <span data-testid="candidate-order-value">
                    {`${CANDIDATE_ORDER_ENV}=${candidateOrderValue(order)}`}
                  </span>
                  <CopyButton
                    value={`${CANDIDATE_ORDER_ENV}=${candidateOrderValue(order)}`}
                    label="candidate order"
                  />
                </p>

                <p className="type-body-sm max-w-prose text-ink-muted">
                  Ranked by verification rate, ties broken by volume. Strategies that ran
                  nothing keep their declared position and go last — a rate of zero over zero
                  attempts is not evidence against an orthography.
                </p>
              </>
            ) : (
              <p className="type-body-sm text-ink-muted">
                Nothing has been verified in this window, so there is no bake-off to apply. The
                current order stands.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

/**
 * The dominant signal: how many verdicts a nudge of the threshold would change.
 *
 * Three states, and only one of them is a number. `null` is not zero — an unpublished
 * threshold has no band, so there is nothing to count inside it, and the tile says which
 * setting would give it one rather than showing a confident `0`.
 */
function NearThresholdTile({ view }: { readonly view: NameAnalyticsView | null }): ReactElement {
  if (view === null || view.nearThreshold === null || view.threshold === null) {
    return (
      <StatTile
        size="hero"
        band="unknown"
        label="near the threshold"
        value={EMPTY_VALUE}
        hint={THRESHOLD_UNPUBLISHED_HINT}
      />
    );
  }
  return (
    <StatTile
      size="hero"
      label={`within ±${view.thresholdBand.toFixed(2)} of ${view.threshold.toFixed(2)}`}
      value={<span className="num">{formatInteger(view.nearThreshold)}</span>}
      hint={
        <span className="num">
          {`of ${formatInteger(view.scored)} scored attempts would change verdict if the threshold moved that far`}
        </span>
      }
    />
  );
}

export const Component = NameStrategiesScreen;
