/**
 * `/vendors` — **what did we ask each vendor to do, and what did it cost?**
 *
 * The screen `generations` stops short of. `/generations` says what the pipeline attempted;
 * this says what those attempts asked of a third party — how many calls, how many tokens,
 * how many characters, how long they took, and what, if anything, they were priced at.
 *
 * ## The rule this screen exists to obey
 *
 * Every quantity on `vendor_usage` is a nullable column with no default, so every sum here
 * arrives as `number | null` and **a null is never a zero**. That is not a formatting
 * preference; it is the difference between three facts an operator would otherwise read as
 * one:
 *
 *  1. **not instrumented** (`isInstrumented === false`) — no worker in this deployment
 *     writes a `vendor_usage` row. Nothing is measured. Widening the window cannot help, so
 *     this is Empty-VIRGIN and the copy offers no remedy it does not have.
 *  2. **instrumented, nothing in this window** (`!hasRowsInWindow`) — Empty-FILTERED, whose
 *     remedy is the time picker, and which therefore passes a filter count of at least one
 *     so the Clear affordance appears (the `NameStrategiesScreen` discrimination).
 *  3. **instrumented, nothing priced** (`isCostPriced === false`) — calls are recorded and
 *     not one of them carries a cost. The volume figures are real; every money cell says
 *     "not priced" and the cost chart shows a worded well. There is no `$0.00` anywhere on
 *     this screen, ever — a zero there would say a vendor worked free.
 *
 * Out of the box that third state covers MOST of the screen but not all of it, and the
 * difference matters to the copy: `bayram/config.py` ships `music_usd_per_minute` at `0.15`, so
 * the music leg is priced from a placeholder rate and reports `costSource: "estimated"`,
 * while `BAYRAM_ELEVENLABS_USD_PER_CHARACTER` and all four token rates ship at `0.0`, leaving
 * speech, transcription and every LLM group unpriced until an operator sets a rate. So the
 * common shipped page is a MIXTURE — an estimated music row beside unpriced speech rows —
 * and never a screen on which the word "priced" is meaningless.
 *
 * A fourth absence rides along inside the rollup: a group's `costSource` says how its money
 * was arrived at, and `"estimated"` — our rate against a duration WE requested, which is
 * exactly what the shipped music rate produces — is a much weaker claim than
 * `"vendor_reported"`. The word is printed beside every figure THAT EXISTS. It is omitted
 * for an unpriced group rather than printed as "not priced" a second time beside the value
 * that already says so; see the cost column.
 *
 * ## The shape of the page
 *
 * Header (title, the question, the spend hero, the filter bar) → "Volume" → "Over time" →
 * "Breakdown" → "Failures". `StatTile`, `FilterBar`, `DataTable` and `ChartFrame` each bring
 * their own 28px card and `--shadow-card`, so this file supplies the gutter, the rhythm and
 * the plain section labels on the page ground — wrapping any of them in a panel would render
 * a card inside a card.
 *
 * **Two charts, not one.** `ChartFrame` has exactly one y-axis by design (§11.1), and
 * dollars and call counts share no magnitude; a dual axis would invent a correlation that is
 * not in the data.
 *
 * **One time picker.** It scopes every panel below it, so the table and the chart beside it
 * can never describe different windows. A picker per chart is how that happens.
 *
 * ## Polling
 *
 * None — `NO_POLLING` plus `refetchOnWindowFocus`. Spend is not live ops; see
 * `useVendorUsage.ts`.
 */

import { useMemo, type ReactElement } from "react";

import { VENDOR_VALUES, type VendorErrorView, type VendorUsageRollupView } from "@/api";
import {
  ChartFrame,
  DataTable,
  FilterBar,
  StatTile,
  TimeRangePicker,
  buildFilterChips,
  type DataColumn,
  type TimeRange,
} from "@/components/data";
import { ErrorCodeBadge } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Skeleton, SkeletonTable } from "@/components/util";
import {
  EMPTY_VALUE,
  cn,
  costSourceLabel,
  formatDurationMs,
  formatInteger,
  formatRate,
  formatSpendUsd,
  formatTimestamp,
  humaniseEnum,
  rateBand,
  useSearchParamsState,
  usePrefsStore,
} from "@/lib";

import { VendorToggles } from "./filterControls";
import { dominantCostSource, toVendorDaySeries, useVendorUsage } from "./useVendorUsage";
import { VENDORS_FILTER_FALLBACK, toVendorUsageQuery, vendorsFilterSchema } from "./vendorsFilters";

/** Empty-VIRGIN copy. Two sentences, and the second is the one that matters. */
export const NOT_INSTRUMENTED_TITLE = "Vendor usage is not recorded here";
export const NOT_INSTRUMENTED_BODY =
  "No worker in this deployment has written a vendor_usage row. Calls, tokens and spend are unmeasured — not zero.";

/**
 * What the cost chart says when nothing in the whole record carries a cost. A sentence, not
 * a grid.
 *
 * It says "no configured rate covers these calls" rather than "no rate is configured": this
 * deployment ships a music rate, so the honest claim is about the legs these calls actually
 * used, not about the settings file.
 */
export const UNPRICED_CHART_LABEL =
  "nothing recorded here carries a cost — no configured rate covers these calls";

/** What a panel here holds, in the operator's words. */
const NOUN = "vendor calls";

/**
 * The hero tile's caption: how much of the window's money is money, and how it was arrived
 * at.
 *
 * **The provenance clause is dropped when nothing in the window was priced.**
 * `dominantCostSource` returns `null` there and `costSourceLabel` renders that as "not
 * priced" — which is already the whole of the figure above the caption, so appending it
 * printed the absence twice, the same doubling the Breakdown table's chip had. The coverage
 * count survives either way: "0 of 120 calls priced" is a measured count of priced calls and
 * not a money zero, and it is the sentence that tells an operator the window HAD calls.
 */
function spendHintText(
  costedCalls: number | null,
  calls: number | null,
  dominantSource: string | null,
): string {
  const coverage = `${formatInteger(costedCalls)} of ${formatInteger(calls)} calls priced`;
  return dominantSource === null ? coverage : `${coverage} · ${costSourceLabel(dominantSource)}`;
}

/**
 * What the cost chart's dollars actually cover, as a sentence under the plot.
 *
 * `costUsd` sums only the rows that carry a cost, so a stack drawn over a window of nine
 * hundred calls of which nine were priced is a total for the nine — and nothing in the plot
 * says so. The count belongs beside the money, and `ChartFrame`'s tooltip cannot hold it:
 * `formatValue` is handed `(value, seriesKey)` and never the datum row, so a second quantity
 * per (day, vendor) has nowhere to go, and §11.1 forbids reaching past the frame into
 * Recharts to make one. A window-level caption is the honest thing this screen CAN say, and
 * it is drawn from the by-day series itself rather than from `totals`, so it always
 * describes the points that were actually plotted.
 *
 * `null` when the window holds no calls at all — the chart's own empty well is the sentence
 * there, and a caption counting to zero beneath it would be the second copy of one absence.
 */
function pricedCoverageCaption(costedCalls: number, calls: number): string | null {
  if (calls <= 0) return null;
  if (costedCalls <= 0) {
    return `None of this window's ${formatInteger(calls)} calls carried a cost.`;
  }
  if (costedCalls >= calls) {
    return `Every one of this window's ${formatInteger(calls)} calls carried a cost.`;
  }
  return `The bars above total the ${formatInteger(costedCalls)} of this window's ${formatInteger(
    calls,
  )} calls that carried a cost.`;
}

/**
 * The tint behind a provenance chip — the WORD in `--ink`, the hue in the ground, which is
 * this design's idiom for a categorical label and the reason none of these is a coloured
 * word. `estimated` takes the CAUTION tint deliberately: it is the weakest claim on the
 * screen and the one an operator is most likely to mistake for a bill.
 *
 * Never called with `null` from the table any more: a row with no provenance renders no
 * chip at all, so the neutral tint is the fallback for a source a newer server invented
 * rather than the shipped look of an unpriced row.
 */
function costSourceTint(source: string | null): string {
  if (source === "vendor_reported") return "bg-success-tint";
  if (source === "derived") return "bg-info-tint";
  if (source === "estimated") return "bg-caution-tint";
  return "bg-neutral-tint";
}

export function VendorsScreen(): ReactElement {
  const density = usePrefsStore((state) => state.density);
  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);
  const filters = useSearchParamsState(vendorsFilterSchema, VENDORS_FILTER_FALLBACK);
  const { value, patch } = filters;

  const query = useMemo(() => toVendorUsageQuery(value), [value]);
  const { usage, byDay, errors } = useVendorUsage(query);

  const view = usage.data ?? null;
  const totals = view?.totals ?? null;
  const rollup = useMemo(() => view?.rows ?? [], [view]);
  const failures = useMemo(() => errors.data ?? [], [errors.data]);

  const isInstrumented = view?.isInstrumented ?? false;
  const isCostPriced = view?.isCostPriced ?? false;

  const callSeries = useMemo(() => toVendorDaySeries(byDay.data ?? [], "calls"), [byDay.data]);
  const costSeries = useMemo(() => toVendorDaySeries(byDay.data ?? [], "costUsd"), [byDay.data]);
  const dominantSource = useMemo(() => dominantCostSource(rollup), [rollup]);
  const costCoverage = useMemo(
    () => pricedCoverageCaption(costSeries.costedCalls, costSeries.calls),
    [costSeries],
  );

  const chips = useMemo(
    () =>
      buildFilterChips(filters, [
        { key: "vendor", label: "vendor" },
        { key: "from", label: "from" },
        { key: "to", label: "to" },
      ]),
    [filters],
  );

  /** An empty window is not a measured zero — and it is not an absent writer either. */
  const isEmptyWindow = view !== null && !view.hasRowsInWindow;
  /*
   * WHICH empty, decided by the writer probe rather than by the URL. A deployment that
   * records nothing is Empty-virgin even with a window applied (widening it would not help);
   * a deployment that records plenty is Empty-filtered even when the operator arrived by a
   * pasted link with no filters of their own, because the window IS the filter and Clear is
   * the remedy. `resolveAsyncState` branches on the count, so this is the count it is told.
   */
  const emptinessFilterCount = isInstrumented ? Math.max(filters.activeCount, 1) : 0;

  const windowLabel =
    view === null || view.window === null
      ? "the whole record"
      : `${formatTimestamp(view.window.from, timeZoneMode)} → ${formatTimestamp(view.window.to, timeZoneMode)}`;

  /** The empty/error/stale copy every panel shares. Each panel still gets its OWN boundary:
   *  a stalled failure query must not blank the rollup beside it. */
  const emptiness = {
    activeFilterCount: emptinessFilterCount,
    onClearFilters: filters.clear,
    noun: NOUN,
    emptyTitle: NOT_INSTRUMENTED_TITLE,
    emptyBody: NOT_INSTRUMENTED_BODY,
    emptyFilteredTitle: "No vendor calls in this window",
    emptyFilteredBody: (
      <>
        Nothing was recorded in <span className="num">{windowLabel}</span>. Widen the range or
        clear the filters — this is an empty window, not a measured zero.
      </>
    ),
  } as const;

  const columns = useMemo<readonly DataColumn<VendorUsageRollupView>[]>(
    () => [
      {
        id: "vendor",
        header: "vendor",
        isNumeric: false,
        width: "10rem",
        cell: (row) => <span className="text-ink">{humaniseEnum(row.vendor)}</span>,
      },
      {
        id: "operation",
        header: "operation",
        isNumeric: false,
        width: "11rem",
        cell: (row) => <span className="text-ink-muted">{humaniseEnum(row.operation)}</span>,
      },
      {
        /* A vendor's model id is NOT one of our enums — `google/gemma-4-31b-it:free` has a
           slash, a colon and hyphens that mean something to the vendor. It is rendered
           verbatim; `humaniseEnum` would rewrite a name we do not own. */
        id: "modelId",
        header: "model",
        isNumeric: false,
        width: "13rem",
        cell: (row) => (
          <span className="type-mono text-ink-muted">{row.modelId ?? EMPTY_VALUE}</span>
        ),
      },
      {
        id: "calls",
        header: "calls",
        isNumeric: true,
        width: "6rem",
        cell: (row) => formatInteger(row.calls),
      },
      {
        id: "successRate",
        header: "success",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatRate(row.successRate),
      },
      {
        id: "promptTokens",
        header: "prompt",
        headerTitle: "prompt tokens",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatInteger(row.promptTokens),
      },
      {
        id: "completionTokens",
        header: "completion",
        headerTitle: "completion tokens",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatInteger(row.completionTokens),
      },
      {
        id: "billedCharacters",
        header: "characters",
        headerTitle: "billed characters",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatInteger(row.billedCharacters),
      },
      {
        id: "audioMs",
        header: "audio",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatDurationMs(row.audioMs),
      },
      {
        id: "avgLatencyMs",
        header: "avg latency",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatDurationMs(row.avgLatencyMs),
      },
      {
        id: "maxLatencyMs",
        header: "max latency",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatDurationMs(row.maxLatencyMs),
      },
      {
        /*
         * The money and its provenance — and for a PRICED group, never one without the
         * other. `costSource === null` IS the unpriced signal for this group (the database
         * will not let a cost exist without a source), so the value says "not priced" rather
         * than inventing a zero, and the chip says how the figure that IS there was arrived
         * at.
         *
         * The chip is OMITTED entirely when there is no provenance to report. It used to
         * render `costSourceLabel(null)`, which is the same "not priced" the value beside it
         * already says — so an unpriced group read "not priced not priced", and on the
         * shipped default every speech and LLM group is unpriced, which made that the common
         * row rather than an edge case. One absence, stated once, in the cell that carries
         * the figure; a chip that only ever appears next to money also stops the tint from
         * meaning anything for a row that has none.
         */
        id: "costUsd",
        header: "cost",
        isNumeric: true,
        width: "11rem",
        cell: (row) => (
          <span className="inline-flex items-baseline justify-end gap-2">
            <span>{formatSpendUsd(row.costUsd, row.costSource !== null)}</span>
            {row.costSource !== null && (
              <span
                data-testid="cost-source-chip"
                data-cost-source={row.costSource}
                className={cn(
                  "type-body-sm rounded-pill px-2 py-0.5 text-ink",
                  costSourceTint(row.costSource),
                )}
              >
                {costSourceLabel(row.costSource)}
              </span>
            )}
          </span>
        ),
      },
    ],
    [],
  );

  const failureColumns = useMemo<readonly DataColumn<VendorErrorView>[]>(
    () => [
      {
        id: "vendor",
        header: "vendor",
        isNumeric: false,
        width: "10rem",
        cell: (row) => <span className="text-ink">{humaniseEnum(row.vendor)}</span>,
      },
      {
        /* `errorCode: null` groups failures whose writer recorded no code. Still a badge,
           never a blank — and `isRetryable` is unknown here, which the badge renders as "?"
           rather than as "terminal". */
        id: "errorCode",
        header: "error code",
        isNumeric: false,
        width: "18rem",
        cell: (row) => <ErrorCodeBadge code={row.errorCode} isRetryable={null} />,
      },
      {
        id: "count",
        header: "count",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatInteger(row.count),
      },
      {
        id: "share",
        header: "share",
        headerTitle: "share of this vendor's failures in the window",
        isNumeric: true,
        width: "7rem",
        cell: (row) => formatRate(row.share),
      },
    ],
    [],
  );

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        title="Vendors"
        description="What each vendor was asked to do, and what it cost."
        signal={
          <AsyncBoundary
            status={usage.status}
            hasData={usage.data !== undefined}
            error={usage.error}
            onRetry={() => {
              void usage.refetch();
            }}
            {...(usage.isError ? { dataUpdatedAt: usage.dataUpdatedAt } : {})}
            noun="vendor spend"
            skeleton={<Skeleton width="19rem" height="10.5rem" />}
          >
            <StatTile
              size="hero"
              label="spend in this window"
              value={
                <span className="num">
                  {formatSpendUsd(totals?.costUsd ?? null, isCostPriced)}
                </span>
              }
              hint={
                isInstrumented ? (
                  <span className="num">
                    {spendHintText(
                      totals?.costedCalls ?? null,
                      totals?.calls ?? null,
                      dominantSource,
                    )}
                  </span>
                ) : (
                  NOT_INSTRUMENTED_BODY
                )
              }
            />
          </AsyncBoundary>
        }
      >
        <FilterBar
          label="vendor filters"
          chips={chips}
          onClear={filters.clear}
          activeCount={filters.activeCount}
        >
          {/* ONE picker for the whole screen. Every panel below reads the same window, so
              the table and the chart beside it cannot describe different populations. */}
          <TimeRangePicker
            value={{ from: value.from, to: value.to }}
            onChange={(next: TimeRange) => {
              /*
               * A preset emits `to` undefined meaning "now". Close it at the click instant
               * and PIN it, so the filter does not widen underneath the three queries that
               * share it.
               *
               * NOT because half a window is refused — `resolve_window` accepts "since X"
               * on every windowed route now, and `windowParams` sends a lone bound rather
               * than dropping it. The reason is that these are THREE separate requests: an
               * open `to` is resolved to each request's own `now`, so the rollup, the daily
               * series and the failure mix would each close their window at a different
               * instant and the table would disagree with the chart beside it. A `from` the
               * operator typed with no `to` arrives from the URL and is sent as-is; only the
               * PICKER pins, because only the picker is choosing on their behalf.
               */
              patch({
                from: next.from,
                to: next.from === undefined ? undefined : (next.to ?? new Date().toISOString()),
              });
            }}
          />
          <VendorToggles
            values={VENDOR_VALUES}
            selected={value.vendor}
            onChange={(next) => {
              patch({ vendor: next === undefined ? undefined : [...next] });
            }}
          />
        </FilterBar>
      </PageHeader>

      <div className="flex min-h-0 flex-col gap-8 px-gutter pb-gutter">
        <Group label="Volume">
          <AsyncBoundary
            status={usage.status}
            hasData={usage.data !== undefined}
            isEmpty={isEmptyWindow}
            error={usage.error}
            onRetry={() => {
              void usage.refetch();
            }}
            dataUpdatedAt={usage.dataUpdatedAt}
            skeleton={
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[0, 1, 2, 3].map((slot) => (
                  <Skeleton key={slot} height="8rem" />
                ))}
              </div>
            }
            {...emptiness}
          >
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatTile
                label="calls"
                value={<span className="num">{formatInteger(totals?.calls ?? null)}</span>}
                hint="every recorded vendor call in the window, health probes included"
              />
              <StatTile
                label="failures"
                /* The band is the SUCCESS rate's, so the word beside the figure ("good" /
                   "at risk" / "bad") describes the system rather than the count — and a
                   null rate bands as "unknown" rather than as good news. */
                band={rateBand(totals?.successRate ?? null)}
                value={<span className="num">{formatInteger(totals?.failures ?? null)}</span>}
                hint={
                  <span className="num">
                    {`${formatRate(totals?.successRate ?? null)} succeeded`}
                  </span>
                }
              />
              <StatTile
                label="tokens"
                value={<span className="num">{formatInteger(totals?.totalTokens ?? null)}</span>}
                hint="null where no call in the window reported a token count"
              />
              <StatTile
                label="characters"
                value={
                  <span className="num">{formatInteger(totals?.billedCharacters ?? null)}</span>
                }
                hint="billed characters, as counted by the vendor where it said so"
              />
            </div>
          </AsyncBoundary>
        </Group>

        <Group label="Over time">
          <div className="grid gap-4 xl:grid-cols-2">
            <AsyncBoundary
              status={byDay.status}
              hasData={byDay.data !== undefined}
              isEmpty={isEmptyWindow}
              error={byDay.error}
              onRetry={() => {
                void byDay.refetch();
              }}
              dataUpdatedAt={byDay.dataUpdatedAt}
              skeleton={<Skeleton height="18rem" />}
              {...emptiness}
            >
              <div className="flex flex-col gap-2">
                <ChartFrame
                  title="Cost per day by vendor"
                  subtitle="stacked; a day nobody was billed for is a gap, not a zero"
                  kind="stacked-bar"
                  xKey="day"
                  data={costSeries.data}
                  series={costSeries.series}
                  isRefetching={byDay.isFetching}
                  formatY={(cost) => formatSpendUsd(cost, true)}
                  formatValue={(cost) => formatSpendUsd(cost, true)}
                  /* An unpriced deployment gets a SENTENCE rather than an empty grid: the
                     absence has a cause and a remedy, and neither is visible in a blank
                     plot. */
                  emptyLabel={isCostPriced ? "no priced call in this window" : UNPRICED_CHART_LABEL}
                />
                {/* The denominator, under the money and not inside it. A stack summed over
                    the priced rows alone is a partial bill, and the plot has no room to say
                    so — see `pricedCoverageCaption`. Only the COST chart gets this; on the
                    calls chart beside it, "how many were priced" answers no question the
                    reader asked. */}
                {costCoverage !== null && (
                  <p data-testid="cost-coverage-caption" className="type-body-sm text-ink-muted">
                    <span className="num">{costCoverage}</span>
                  </p>
                )}
              </div>
            </AsyncBoundary>

            <AsyncBoundary
              status={byDay.status}
              hasData={byDay.data !== undefined}
              isEmpty={isEmptyWindow}
              error={byDay.error}
              onRetry={() => {
                void byDay.refetch();
              }}
              dataUpdatedAt={byDay.dataUpdatedAt}
              skeleton={<Skeleton height="18rem" />}
              {...emptiness}
            >
              <ChartFrame
                title="Calls per day by vendor"
                subtitle="stacked; a (day, vendor) pair with no calls is absent, not zero"
                kind="stacked-bar"
                xKey="day"
                data={callSeries.data}
                series={callSeries.series}
                isRefetching={byDay.isFetching}
              />
            </AsyncBoundary>
          </div>
        </Group>

        <Group label="Breakdown">
          <AsyncBoundary
            status={usage.status}
            hasData={usage.data !== undefined}
            isEmpty={isEmptyWindow || rollup.length === 0}
            error={usage.error}
            onRetry={() => {
              void usage.refetch();
            }}
            dataUpdatedAt={usage.dataUpdatedAt}
            skeleton={<SkeletonTable rows={8} columns={columns.length} density={density} />}
            {...emptiness}
          >
            <DataTable
              label="vendor usage by operation"
              data={rollup}
              columns={columns}
              getRowId={(row) => `${row.vendor}:${row.operation}:${row.modelId ?? "-"}`}
              isRefetching={usage.isFetching}
            />
          </AsyncBoundary>
        </Group>

        <Group label="Failures">
          <AsyncBoundary
            status={errors.status}
            hasData={errors.data !== undefined}
            isEmpty={failures.length === 0}
            /* Zero failures is a RESULT, not a missing filter — so this panel never offers
               Clear, and its empty copy says the good news rather than blaming the window. */
            activeFilterCount={0}
            error={errors.error}
            onRetry={() => {
              void errors.refetch();
            }}
            dataUpdatedAt={errors.dataUpdatedAt}
            noun="vendor failures"
            emptyTitle={isInstrumented ? "No failed vendor calls" : NOT_INSTRUMENTED_TITLE}
            emptyBody={
              isInstrumented
                ? "Every recorded call in this window succeeded. A vendor with no failures is absent from this table rather than present at zero."
                : NOT_INSTRUMENTED_BODY
            }
            skeleton={
              <SkeletonTable rows={4} columns={failureColumns.length} density={density} />
            }
          >
            <DataTable
              label="vendor failures by error code"
              data={failures}
              columns={failureColumns}
              getRowId={(row) => `${row.vendor}:${row.errorCode ?? "-"}`}
              isRefetching={errors.isFetching}
              isDensityToggle={false}
            />
          </AsyncBoundary>
        </Group>
      </div>
    </div>
  );
}

/**
 * A plain section label with the cards it gathers.
 *
 * Deliberately NOT a heading and NOT a landmark, for the reason `LiveScreen` states it: the
 * cards inside already carry their own headings and accessible names, and a second level
 * above them would leave a screen reader with two competing outlines for one group. `<h1>`
 * stays singular, in `PageHeader`.
 */
function Group({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactElement;
}): ReactElement {
  return (
    <div className="flex flex-col gap-3">
      <p className="type-h3 text-ink">{label}</p>
      {children}
    </div>
  );
}

export const Component = VendorsScreen;
