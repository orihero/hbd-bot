/**
 * `/generations` — "Is name verification working?" (§11.2)
 *
 * ## The dominant signal
 *
 * §11.2 says "overall verification rate", and it comes from `GET /api/metrics/name-strategies`
 * rather than from the attempts on screen. That endpoint is one `GROUP BY` over rows where
 * `name_candidate_strategy IS NOT NULL AND is_name_verified IS NOT NULL` — verification that
 * actually ran — so summing its groups gives the whole population's rate. Deriving it from
 * the current page would give the rate of fifty rows out of ten thousand and present it as
 * the system's, which is the same class of wrong number as a client-side sort on a keyset
 * page. The metric follows the screen's time window and nothing else.
 *
 * `rate === null` when nothing ran. Never `0` — see `verification.ts`.
 *
 * ## The detail is a panel, not a route
 *
 * `routes.tsx` has no `/generations/:id`, so the attempt detail opens from `?attempt=<uuid>`
 * and still pastes into Slack as a link. It is excluded from the filter count by hand,
 * because `activeFilterCount`'s default exclusion list covers paging and not selection — a
 * selected row is not a filter, and counting it would make the Empty-filtered copy claim a
 * filter the operator cannot see.
 *
 * ## Polling
 *
 * None. §11.5's table gives an interval to the pulse, order detail, moderation and the
 * orders list; the render ledger is "everything else: on demand + `refetchOnWindowFocus`".
 *
 * ## The shape of the page
 *
 * Header (title, breadcrumb, the question, the verification-rate tile) → the filter card →
 * "Attempts" → the table card, with the detail panel as a second column beside it. The tile
 * stays in `PageHeader`'s `signal` slot: §11.2 wants it read before the table, and a stats
 * row under seven filter controls is a row the filters push off the fold.
 *
 * `StatTile`, `FilterBar` and `DataTable` each bring their own 28px card and
 * `--shadow-card`, so this file supplies only the gutter, the rhythm and the section label.
 * Wrapping any of them in a panel would render a card inside a card.
 *
 * ## The two outcome columns are tinted pills, not coloured words
 *
 * `outcome` and `name verified` used to paint `var(--green)`/`var(--red)` straight onto the
 * text. In the light-first palette that is a hue sitting at its 4.5:1 floor; the design's own
 * idiom — the WORD in `--ink`, the hue in the ground and the glyph — reads at 6.6:1 and puts
 * the colour where the eye catches it. The glyph stays: ✓ / ✗ / a muted "did not run" are
 * three different facts and none of them may be conveyed by colour alone.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";
import { z } from "zod";

import {
  DEFAULT_PAGE_LIMIT,
  GENERATION_KIND_VALUES,
  MAX_ERROR_CODE_CHARS,
  MAX_PAGE_LIMIT,
  MAX_PROVIDER_CHARS,
  MIN_PAGE_LIMIT,
  NAME_STRATEGY_VALUES,
  getAttempt,
  getGenerations,
  getNameStrategies,
  unwrapAsync,
  type AttemptWireView,
  type GenerationKind,
  type GenerationsQuery,
  type NameStrategy,
  type WindowQuery,
} from "@/api";
import {
  CursorPager,
  DataTable,
  FilterBar,
  StatTile,
  TimeRangePicker,
  TimeZoneCaption,
  Timestamp,
  buildFilterChips,
  type DataColumn,
  type TimeRange,
} from "@/components/data";
import {
  ErrorCodeBadge,
  NameText,
  OrderRefChip,
  PurgedValue,
  formatSimilarity,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Skeleton, SkeletonTable } from "@/components/util";
import {
  EMPTY_VALUE,
  activeFilterCount,
  cn,
  formatRate,
  humaniseEnum,
  queryKeys,
  rateBand,
  useSearchParamsState,
  usePrefsStore,
  zBoolParam,
  zEnumList,
  zInstantParam,
  zIntParam,
  zStringParam,
  type SearchParamsSchema,
} from "@/lib";

import { AttemptDetailPanel, VERIFICATION_NOT_RUN_LABEL } from "./AttemptDetailPanel";
import {
  EnumToggleGroup,
  SingleEnumSelect,
  TextFilter,
  TriStateSelect,
} from "./filterControls";
import { overallVerification } from "./verification";

const generationsFilterSchema = z.object({
  kind: zEnumList(GENERATION_KIND_VALUES),
  provider: zStringParam,
  isSuccess: zBoolParam,
  errorCode: zStringParam,
  strategy: zEnumList(NAME_STRATEGY_VALUES),
  isOrphaned: zBoolParam,
  from: zInstantParam,
  to: zInstantParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
  cursor: zStringParam,
  attempt: zStringParam,
}) satisfies SearchParamsSchema<GenerationsFilters>;

/**
 * The codecs' OUTPUT, written out rather than inferred — `useSearchParamsState` takes a
 * `z.ZodType<T>` whose input and output are the same `T`, and every codec is a transform.
 * See the longer note in `features/users/UsersScreen.tsx`.
 *
 * `strategy` is parsed as a LIST and sent as a scalar: the URL codec has to tolerate a
 * repeated parameter an operator may have hand-edited, while `AttemptFilters.strategy` is
 * scalar server-side and a repeated one is a 422.
 */
type GenerationsFilters = {
  kind?: GenerationKind[] | undefined;
  provider?: string | undefined;
  isSuccess?: boolean | undefined;
  errorCode?: string | undefined;
  strategy?: NameStrategy[] | undefined;
  isOrphaned?: boolean | undefined;
  from?: string | undefined;
  to?: string | undefined;
  limit?: number | undefined;
  cursor?: string | undefined;
  /** The open detail panel. Selection, not a filter — see the header note. */
  attempt?: string | undefined;
};

const GENERATIONS_FILTER_FALLBACK: GenerationsFilters = {};

/** Paging and selection are not filters. `attempt` is this screen's addition. */
const NON_FILTER_KEYS = ["limit", "cursor", "withTotal", "attempt"] as const;

export function GenerationsScreen(): ReactElement {
  const density = usePrefsStore((state) => state.density);
  const filters = useSearchParamsState(generationsFilterSchema, GENERATIONS_FILTER_FALLBACK);
  const { value, patch } = filters;

  const listQuery = useMemo<GenerationsQuery>(
    () => ({
      kind: value.kind,
      provider: value.provider,
      isSuccess: value.isSuccess,
      errorCode: value.errorCode,
      strategy: value.strategy?.[0],
      isOrphaned: value.isOrphaned,
      from: value.from,
      to: value.to,
      limit: value.limit ?? DEFAULT_PAGE_LIMIT,
      cursor: value.cursor,
      withTotal: true,
    }),
    [value],
  );

  /** The signal follows the screen's window and no other filter. */
  const metricsWindow = useMemo<WindowQuery>(
    () => ({ from: value.from, to: value.to }),
    [value.from, value.to],
  );

  const filterCount = activeFilterCount(value, [...NON_FILTER_KEYS]);

  const attempts = useQuery({
    queryKey: queryKeys.generations.list(listQuery),
    queryFn: ({ signal }) => unwrapAsync(getGenerations(listQuery, { signal })),
  });

  const strategies = useQuery({
    queryKey: queryKeys.metrics.nameStrategies(metricsWindow),
    queryFn: ({ signal }) => unwrapAsync(getNameStrategies(metricsWindow, { signal })),
  });

  const selectedId = value.attempt ?? null;
  const selected = useQuery({
    queryKey: queryKeys.generations.detail(selectedId ?? ""),
    queryFn: ({ signal }) => unwrapAsync(getAttempt(selectedId ?? "", { signal })),
    enabled: selectedId !== null,
  });

  const items = attempts.data?.items ?? [];
  const totals = useMemo(
    () => overallVerification(strategies.data ?? []),
    [strategies.data],
  );

  const chips = useMemo(
    () =>
      buildFilterChips(filters, [
        { key: "kind", label: "kind" },
        { key: "provider", label: "provider", format: (member) => String(member) },
        { key: "isSuccess", label: "succeeded" },
        { key: "errorCode", label: "error code", format: (member) => String(member) },
        { key: "strategy", label: "strategy" },
        { key: "isOrphaned", label: "orphaned" },
        { key: "from", label: "from" },
        { key: "to", label: "to" },
      ]),
    [filters],
  );

  const columns = useMemo<readonly DataColumn<AttemptWireView>[]>(
    () => [
      {
        id: "createdAt",
        header: (
          <span>
            created <TimeZoneCaption />
          </span>
        ),
        isNumeric: false,
        width: "12rem",
        cell: (row) => <Timestamp at={row.createdAt} seconds />,
      },
      {
        id: "kind",
        header: "kind",
        isNumeric: false,
        width: "9rem",
        cell: (row) => <span className="text-ink-muted">{humaniseEnum(row.kind)}</span>,
      },
      {
        id: "order",
        header: "order",
        isNumeric: false,
        width: "12rem",
        cell: (row) =>
          row.orderId === null ? (
            <span className="type-body-sm text-ink-muted">orphaned</span>
          ) : (
            <OrderRefChip orderId={row.orderId} />
          ),
      },
      {
        id: "provider",
        header: "provider",
        isNumeric: false,
        width: "9rem",
        cell: (row) => <span className="type-mono text-ink-muted">{row.provider ?? EMPTY_VALUE}</span>,
      },
      {
        id: "outcome",
        header: "outcome",
        isNumeric: false,
        width: "16rem",
        cell: (row) =>
          row.isSuccess ? (
            <span className="type-body-sm inline-flex items-center gap-1.5 rounded-pill bg-success-tint px-2.5 py-1 text-ink">
              <span aria-hidden="true" className="text-success">
                ✓
              </span>{" "}
              succeeded
            </span>
          ) : (
            <ErrorCodeBadge code={row.errorCode} isRetryable={row.isRetryable} />
          ),
      },
      {
        /* Tri-state: `null` means the verifier never ran on this row, which is neither a
           pass nor a fail and must not be drawn as one. */
        id: "verified",
        header: "name verified",
        isNumeric: false,
        width: "11rem",
        cell: (row) =>
          row.isNameVerified === null ? (
            <span className="type-body-sm text-ink-muted">{VERIFICATION_NOT_RUN_LABEL}</span>
          ) : (
            <span
              className={cn(
                "type-body-sm inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-ink",
                row.isNameVerified ? "bg-success-tint" : "bg-error-tint",
              )}
            >
              <span
                aria-hidden="true"
                className={row.isNameVerified ? "text-success" : "text-error"}
              >
                {row.isNameVerified ? "✓" : "✗"}
              </span>{" "}
              {row.isNameVerified ? "verified" : "no match"}
            </span>
          ),
      },
      {
        id: "matchConfidence",
        header: "confidence",
        isNumeric: true,
        width: "7rem",
        cell: (row) =>
          row.matchConfidence === null ? EMPTY_VALUE : formatSimilarity(row.matchConfidence),
      },
      {
        id: "candidate",
        header: "candidate",
        isNumeric: false,
        width: "11rem",
        cell: (row) => (
          <PurgedValue purgedAt={row.identityPurgedAt} clock="identity retention">
            <NameText value={row.nameCandidate} />
          </PurgedValue>
        ),
      },
      {
        id: "strategy",
        header: "strategy",
        isNumeric: false,
        width: "9rem",
        cell: (row) => (
          <span className="text-ink-muted">
            {row.nameCandidateStrategy === null
              ? EMPTY_VALUE
              : humaniseEnum(row.nameCandidateStrategy)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        title="generations"
        description="Is name verification working?"
        signal={
          <StatTile
            label="verification rate"
            size="hero"
            band={rateBand(totals.rate)}
            value={<span className="num">{formatRate(totals.rate)}</span>}
            hint={
              totals.attempts === 0
                ? "no verification has run in this window"
                : `${String(totals.verified)}/${String(totals.attempts)} candidates verified`
            }
          />
        }
      >
        <FilterBar chips={chips} onClear={filters.clear} activeCount={filterCount}>
          <TimeRangePicker
            value={{ from: value.from, to: value.to }}
            onChange={(next: TimeRange) => {
              /* `/api/generations` refuses a half window ("from and to are a pair"), and the
                 picker emits presets with `to` undefined. Close it, and PIN it in the URL —
                 a `to` meaning "now" would widen the filter between keyset pages. */
              patch({
                from: next.from,
                to: next.from === undefined ? undefined : (next.to ?? new Date().toISOString()),
              });
            }}
          />
          <EnumToggleGroup<GenerationKind>
            label="kind"
            values={GENERATION_KIND_VALUES}
            selected={value.kind}
            onChange={(next) => {
              patch({ kind: next === undefined ? undefined : [...next] });
            }}
            format={humaniseEnum}
          />
          <SingleEnumSelect<NameStrategy>
            label="strategy"
            values={NAME_STRATEGY_VALUES}
            value={value.strategy?.[0]}
            onChange={(next) => {
              patch({ strategy: next === undefined ? undefined : [next] });
            }}
            format={humaniseEnum}
          />
          <TriStateSelect
            label="outcome"
            value={value.isSuccess}
            onChange={(next) => {
              patch({ isSuccess: next });
            }}
            trueLabel="succeeded"
            falseLabel="failed"
          />
          <TriStateSelect
            label="orphaned"
            value={value.isOrphaned}
            onChange={(next) => {
              patch({ isOrphaned: next });
            }}
            trueLabel="orphaned"
            falseLabel="has an order"
          />
          <TextFilter
            label="provider"
            value={value.provider}
            onChange={(next) => {
              patch({ provider: next });
            }}
            maxLength={MAX_PROVIDER_CHARS}
            placeholder="suno"
          />
          <TextFilter
            label="error code"
            value={value.errorCode}
            onChange={(next) => {
              patch({ errorCode: next });
            }}
            maxLength={MAX_ERROR_CODE_CHARS}
            placeholder="SUNO_TIMEOUT"
          />
        </FilterBar>
      </PageHeader>

      <div className="grid min-h-0 grid-cols-1 gap-gutter px-gutter pb-gutter xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="flex min-w-0 flex-col gap-3" aria-label="generation attempts">
          {/* A plain section label ABOVE the card, not a heading inside it. */}
          <h2 className="type-h3 text-ink">Attempts</h2>
          <AsyncBoundary
            status={attempts.status}
            hasData={attempts.data !== undefined}
            isEmpty={items.length === 0}
            activeFilterCount={filterCount}
            onClearFilters={filters.clear}
            error={attempts.error}
            onRetry={() => {
              void attempts.refetch();
            }}
            dataUpdatedAt={attempts.dataUpdatedAt}
            noun="attempts"
            emptyTitle="No generation attempts yet"
            emptyBody="Every vendor call the pipeline makes writes a row here, successful or not."
            skeleton={<SkeletonTable rows={10} columns={columns.length} density={density} />}
          >
            <DataTable
              label="generation attempts"
              data={items}
              columns={columns}
              getRowId={(row) => row.id}
              isRefetching={attempts.isFetching}
              isRowHighlighted={(row) => row.id === selectedId}
              onRowActivate={(row) => {
                patch({ attempt: row.id }, { keepCursor: true });
              }}
              footer={
                <CursorPager
                  label="attempts"
                  meta={attempts.data?.meta}
                  itemCount={items.length}
                  cursor={value.cursor ?? null}
                  onCursorChange={(cursor) => {
                    patch({ cursor: cursor ?? undefined }, { keepCursor: true });
                  }}
                  limit={value.limit ?? DEFAULT_PAGE_LIMIT}
                  onLimitChange={(limit) => {
                    patch({ limit });
                  }}
                  isFetching={attempts.isFetching}
                />
              }
            />
          </AsyncBoundary>
        </section>

        {selectedId === null ? null : (
          <AsyncBoundary
            status={selected.status}
            hasData={selected.data !== undefined}
            error={selected.error}
            onRetry={() => {
              void selected.refetch();
            }}
            dataUpdatedAt={selected.dataUpdatedAt}
            noun="the attempt"
            skeleton={<Skeleton height="24rem" className="w-full rounded-card" />}
          >
            {selected.data === undefined ? null : (
              <AttemptDetailPanel
                attempt={selected.data}
                onClose={() => {
                  patch({ attempt: undefined }, { keepCursor: true });
                }}
              />
            )}
          </AsyncBoundary>
        )}
      </div>
    </div>
  );
}

export const Component = GenerationsScreen;
