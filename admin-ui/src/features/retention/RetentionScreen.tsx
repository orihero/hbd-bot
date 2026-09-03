/**
 * `/retention` — the clocks, and the last sweep.
 *
 * Slice 1b is the first time in this project's life that the retention sweep executes, so
 * the screen's job is evidence rather than reassurance. Four facts are load-bearing and each
 * one is a distinct rendering, because collapsing any pair of them produces a badge that
 * lies:
 *
 *  - **`hasEverRun: false`** — a scheduler that never fired must not light a clean badge.
 *    "Nothing is past expiry" and "nothing has ever been swept" are different answers.
 *  - **`storageReconciliation: null`** is NOT `"nothing_to_reconcile"`: it means no run has
 *    happened at all. `"keys_unrecorded"` — today's normal answer — means *unknown*, not
 *    clean: the rows carried no storage key, so the objects outlived their own deletion.
 *  - **`isBatchFull`** — the sweep came back full, so the backlog below it is not what one
 *    more run will clear. It is a prompt to run again, not an error.
 *  - **`rowsPastExpiry` is counted live**, not read off any run, which is why it can be
 *    non-zero seconds after a clean sweep.
 *
 * There is deliberately no `isOverdue` on the wire and none is computed here: the schedule
 * lives in the deployment's cron, not in this response, so an "overdue" badge would be this
 * screen inventing a fact.
 *
 * Polling: none (§11.5's "everything else"). An hourly sweep does not need a 5s poll.
 *
 * ## Why the eleven clocks are CARDS and the sweeps are still a table
 *
 * They answer different questions and the shapes now say so. A clock is a standing fact with
 * two numbers and a sentence of policy attached — "what is deleted, on whose clock, how much
 * is waiting, how much the last pass took" — and it is read one at a time, by an operator who
 * came to find out *which* clock is behind. That is a card, and in this design a card is how
 * a thing that is read on its own is drawn. The sweep history is the opposite: eleven columns
 * of the same shape, scanned down, compared row against row. That is a table and stays one.
 *
 * Every clock is still rendered, in `SWEEP_CLOCKS` order, with both of its figures — the
 * information the table carried is all here, in the language's own idiom.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement, type ReactNode } from "react";
import { z } from "zod";

import {
  DEFAULT_RETENTION_LIMIT,
  MAX_RETENTION_LIMIT,
  getRetention,
  unwrapAsync,
  type PurgeRunView,
  type RetentionQuery,
  type SweepCounts,
} from "@/api";
import { DataTable, StatTile, Timestamp, type DataColumn } from "@/components/data";
import { tintVar } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Skeleton, SkeletonTable } from "@/components/util";
import {
  EMPTY_VALUE,
  NO_POLLING,
  cn,
  formatDurationMs,
  formatInteger,
  formatRelative,
  humaniseEnum,
  pollWhileVisible,
  queryKeys,
  useSearchParamsState,
  usePrefsStore,
  zIntParam,
  type SearchParamsSchema,
} from "@/lib";

import { SWEEP_CLOCKS, reconciliationPresentation, type SweepClock } from "./retentionModel";

const retentionFilterCodec = z.object({
  limit: zIntParam({ min: 1, max: MAX_RETENTION_LIMIT }),
});
type RetentionFilters = z.output<typeof retentionFilterCodec>;
/** Annotated, not asserted: `SearchParamsSchema` leaves zod's input side `unknown`. */
const retentionFilterSchema: SearchParamsSchema<RetentionFilters> = retentionFilterCodec;
const RETENTION_FILTERS_EMPTY: RetentionFilters = {};

/** How many runs the history table offers. `/api/retention` defaults to 24, not 50. */
const RUN_HISTORY_CHOICES = [24, 50, 100, MAX_RETENTION_LIMIT] as const;

/** The one control shape this screen needs: a ground instead of a border, 14px corners. */
const SELECT_CLASS =
  "type-body-sm num rounded-control bg-surface-control px-3 py-1.5 text-ink transition-colors duration-fast ease-standard hover:bg-surface-control-hover";

interface ClockRow extends SweepClock {
  readonly pastExpiry: number;
  readonly lastRun: number | null;
}

export function RetentionScreen(): ReactElement {
  const filters = useSearchParamsState(retentionFilterSchema, RETENTION_FILTERS_EMPTY);
  const density = usePrefsStore((state) => state.density);

  const limit = filters.value.limit ?? DEFAULT_RETENTION_LIMIT;
  const wireQuery = useMemo<RetentionQuery>(() => ({ limit }), [limit]);

  const retention = useQuery({
    queryKey: queryKeys.retention.list(wireQuery),
    queryFn: ({ signal }) => unwrapAsync(getRetention(wireQuery, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const data = retention.data ?? null;
  const lastRun: PurgeRunView | null = data?.runs[0] ?? null;

  const clockRows = useMemo<readonly ClockRow[]>(
    () =>
      SWEEP_CLOCKS.map((clock) => ({
        ...clock,
        pastExpiry: countOf(data?.rowsPastExpiry, clock.key),
        lastRun: lastRun === null ? null : countOf(lastRun.counts, clock.key),
      })),
    [data?.rowsPastExpiry, lastRun],
  );

  const runColumns = useMemo<readonly DataColumn<PurgeRunView>[]>(
    () => [
      { id: "ranAt", header: "ran at", isNumeric: false, cell: (run) => <Timestamp at={run.ranAt} seconds /> },
      {
        id: "trigger",
        header: "trigger",
        isNumeric: false,
        cell: (run) => (
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-ink">{humaniseEnum(run.trigger)}</span>
            {run.triggeredByUsername === null ? null : (
              <span className="type-caption text-ink-muted">{run.triggeredByUsername}</span>
            )}
          </span>
        ),
      },
      {
        id: "rows",
        header: "rows affected",
        isNumeric: true,
        width: "8rem",
        cell: (run) => formatInteger(run.totalRowsAffected),
      },
      {
        id: "duration",
        header: "duration",
        isNumeric: true,
        width: "7rem",
        cell: (run) => formatDurationMs(run.durationMs),
      },
      {
        id: "batch",
        header: "batch",
        isNumeric: true,
        width: "8rem",
        // The word `full` is the channel; the hue only repeats it.
        cell: (run) => (
          <span className={run.isBatchFull ? "text-caution" : undefined}>
            {formatInteger(run.batchSize)}
            {run.isBatchFull ? " full" : ""}
          </span>
        ),
      },
      {
        id: "storage",
        header: "storage",
        isNumeric: false,
        cell: (run) => {
          const presentation = reconciliationPresentation(run.storage.reconciliation);
          return (
            <span className="flex flex-col">
              <span className="type-body-sm" style={{ color: presentation.colorVar }}>
                {presentation.label}
              </span>
              <span className="type-caption num text-ink-muted">
                {`${formatInteger(run.storage.keysDeleted)}/${formatInteger(run.storage.keysReturned)} keys · ${formatInteger(run.storage.unreconciledKeys)} unreconciled`}
              </span>
            </span>
          );
        },
      },
      {
        id: "errorCode",
        header: "outcome",
        isNumeric: false,
        cell: (run) =>
          run.errorCode === null ? (
            <span className="text-success">
              <span aria-hidden="true">✓</span> ok
            </span>
          ) : (
            <span className="text-error">
              <span aria-hidden="true">✗</span> <code className="type-mono">{run.errorCode}</code>
            </span>
          ),
      },
    ],
    [],
  );

  const reconciliation = reconciliationPresentation(data?.storageReconciliation ?? null);

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Retention"
        description="What is past its clock, and did the sweep run?"
        signal={
          <AsyncBoundary
            status={retention.status}
            hasData={data !== null}
            error={retention.error}
            onRetry={() => void retention.refetch()}
            {...(retention.isError ? { dataUpdatedAt: retention.dataUpdatedAt } : {})}
            noun="the retention status"
            skeleton={<Skeleton className="h-[7.5rem] w-72" />}
          >
            <div className="flex flex-wrap items-stretch gap-3" data-testid="retention-signal">
              <StatTile
                size="hero"
                label="rows past expiry"
                value={formatInteger(data?.totalRowsPastExpiry ?? null)}
                hint="counted live, right now — not read off a run"
              />
              <StatTile
                label="last sweep"
                value={
                  data?.hasEverRun === true && data.lastRunAt !== null ? (
                    <Timestamp at={data.lastRunAt} seconds />
                  ) : (
                    "never"
                  )
                }
                hint={
                  data?.hasEverRun === true && data.lastRunAt !== null
                    ? formatRelative(data.lastRunAt)
                    : "no sweep has ever run in this deployment"
                }
              />
            </div>
          </AsyncBoundary>
        }
      />

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        <AsyncBoundary
          status={retention.status}
          hasData={data !== null}
          error={retention.error}
          onRetry={() => void retention.refetch()}
          {...(retention.isError ? { dataUpdatedAt: retention.dataUpdatedAt } : {})}
          noun="the retention status"
          skeleton={<Skeleton className="h-24 w-full" />}
        >
          {data === null ? null : (
            <div className="flex flex-col gap-2" data-testid="retention-standing">
              {data.hasEverRun ? null : (
                <Banner tone="var(--caution)" glyph="⚑" data-testid="retention-never-run">
                  No sweep has ever run. Every clock below is a backlog nothing has started
                  working through.
                </Banner>
              )}
              {data.isBatchFull ? (
                <Banner tone="var(--caution)" glyph="↻" data-testid="retention-batch-full">
                  The last sweep came back full, so it stopped at its batch size. Run it again
                  — one more pass will not clear the backlog on its own.
                </Banner>
              ) : null}
              <Banner
                tone={reconciliation.colorVar}
                glyph={reconciliation.tone === "good" ? "✓" : "?"}
                data-testid="retention-reconciliation"
              >
                <span className="font-semibold">{reconciliation.label}</span>
                {" — "}
                {reconciliation.note}
              </Banner>
            </div>
          )}
        </AsyncBoundary>

        <section aria-label="retention clocks" className="flex flex-col gap-3">
          <h2 className="type-h3 text-ink">Clocks</h2>
          <AsyncBoundary
            status={retention.status}
            hasData={data !== null}
            error={retention.error}
            onRetry={() => void retention.refetch()}
            {...(retention.isError ? { dataUpdatedAt: retention.dataUpdatedAt } : {})}
            noun="retention clocks"
            skeleton={
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
                {Array.from({ length: SWEEP_CLOCKS.length }, (_unused, index) => (
                  <Skeleton key={index} className="h-28 w-full" />
                ))}
              </div>
            }
          >
            {/* The section's own `aria-label` names this list; a second identical name on
                the `<ul>` would make a screen reader announce "retention clocks" twice. */}
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {clockRows.map((row) => (
                <ClockCard key={row.key} row={row} />
              ))}
            </ul>
          </AsyncBoundary>
        </section>

        <section aria-label="sweep history" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="type-h3 text-ink">Sweeps</h2>
            <label className="type-body-sm flex items-center gap-2 text-ink-muted">
              history
              <select
                className={SELECT_CLASS}
                value={limit}
                onChange={(event) => {
                  filters.patch({ limit: Number(event.target.value) });
                }}
              >
                {RUN_HISTORY_CHOICES.map((choice) => (
                  <option key={choice} value={choice}>
                    {`${String(choice)} runs`}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <AsyncBoundary
            status={retention.status}
            hasData={data !== null}
            isEmpty={(data?.runs.length ?? 0) === 0}
            error={retention.error}
            onRetry={() => void retention.refetch()}
            {...(retention.isError ? { dataUpdatedAt: retention.dataUpdatedAt } : {})}
            noun="sweeps"
            emptyTitle="No sweep has ever run"
            emptyBody="The hourly job writes a row here on its first pass, even when it deletes nothing."
            skeleton={<SkeletonTable rows={6} columns={7} density={density} />}
          >
            <DataTable<PurgeRunView>
              label="sweeps"
              data={data?.runs ?? []}
              columns={runColumns}
              getRowId={(run) => run.id}
              isRowHighlighted={(run) => run.errorCode !== null}
              isRefetching={retention.isFetching}
            />
          </AsyncBoundary>
        </section>
      </div>
    </div>
  );
}

/**
 * One clock, as a card: a ring, a title, the policy in muted text, and the two numbers.
 *
 * The ring is `--caution-fill` when something is waiting and `--neutral-fill` when nothing
 * is, and it is NOT the only channel that says so — the figure itself is the fact (0 against
 * 40), and the `⚑` beside a non-zero count repeats it as a glyph. Both survive greyscale.
 *
 * `past expiry now` and `last run deleted` keep the table's own headings verbatim, because
 * the distinction they draw — counted live against the database, versus read off the last
 * run — is the whole reason both numbers are on the screen.
 */
function ClockCard({ row }: { readonly row: ClockRow }): ReactElement {
  const isWaiting = row.pastExpiry > 0;
  return (
    <li
      data-clock={row.key}
      data-waiting={String(isWaiting)}
      className={cn(
        "flex items-start gap-3 rounded-card bg-surface-card p-card shadow-card",
        "transition-shadow duration-base ease-standard hover:shadow-card-hover",
      )}
    >
      <span
        aria-hidden="true"
        className="mt-1.5 size-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: isWaiting ? "var(--caution-fill)" : "var(--neutral-fill)" }}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="type-body font-semibold text-ink">{row.label}</p>
        <p className="type-body-sm text-ink-muted">{row.clock}</p>
      </div>
      <dl className="flex shrink-0 items-start gap-5 text-right">
        <div className="flex flex-col">
          <dt className="type-caption text-ink-muted" title="counted live against the database, not read off a run">
            past expiry now
          </dt>
          <dd className={cn("type-h2 num", isWaiting ? "text-caution" : "text-ink")}>
            {isWaiting ? <span aria-hidden="true">⚑ </span> : null}
            {formatInteger(row.pastExpiry)}
          </dd>
        </div>
        <div className="flex flex-col">
          <dt className="type-caption text-ink-muted">last run deleted</dt>
          <dd className="type-h2 num text-ink-muted">
            {row.lastRun === null ? EMPTY_VALUE : formatInteger(row.lastRun)}
          </dd>
        </div>
      </dl>
    </li>
  );
}

/** A `SweepCounts` field, read by key without an index-signature cast. */
function countOf(counts: SweepCounts | undefined, key: keyof SweepCounts): number {
  return counts === undefined ? 0 : counts[key];
}

/**
 * A standing note about the sweep.
 *
 * It used to hang a 2px coloured rule down its left edge. This design draws no rules, so the
 * hue is the GROUND — `tintVar` derives the family's own `-tint` from the same `var()` the
 * glyph is painted with, which is what stops the ground and the mark ever naming two
 * different states — and the words are `--ink` on top of it at 6.6:1.
 */
function Banner({
  tone,
  glyph,
  children,
  ...rest
}: {
  readonly tone: string;
  readonly glyph: string;
  readonly children: ReactNode;
  readonly "data-testid"?: string;
}): ReactElement {
  return (
    <p
      {...rest}
      className="type-body-sm flex items-baseline gap-2 rounded-2xl px-4 py-3"
      style={{ backgroundColor: tintVar(tone) }}
    >
      <span aria-hidden="true" style={{ color: tone }}>
        {glyph}
      </span>
      <span className="text-ink">{children}</span>
    </p>
  );
}

export const Component = RetentionScreen;
