/**
 * `/billing/calls` — every JSON-RPC call Payme made to this deployment, newest first.
 *
 * The incident tool. Reachable from the board's fault table, from the dossier, and from the
 * nav via the board — it has no rail entry of its own, because it is a drill-down rather than a
 * section, and a rail transcribed from the plan is not extended by inference.
 *
 * ## The empty state is the one sentence this screen must get right
 *
 * "Payme has never called this endpoint" is TRUE on this deployment right now and it is not an
 * outage. On a live rail it is also what a payment settled by hand looks like: nobody called
 * about it because nothing on the rail happened. So the copy says both, and the screen never
 * implies the gateway is down — a claim it is in no position to make, since this process cannot
 * reach the gateway at all.
 *
 * ## What this journal does not contain
 *
 * No Telegram id, no request body, no header. `peerIp` is Payme's data centre. That absence is
 * the design and is why this route sits on the `dashboard.read` router beside the board rather
 * than on `records.read` with the payments list, despite sharing the `/api/billing` prefix.
 */

import { useCallback, useMemo, useState, type JSX } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { DEFAULT_PAGE_LIMIT, nextCursorOf, type CountedPageRequest } from "@/api/pagination";
import { CursorPager } from "@/components/CursorPager";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { Segmented } from "@/components/Segmented";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { PATH } from "@/app/paths";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useSessionGuard } from "@/state/useSessionGuard";

import { buildCallColumns } from "./callColumns";
import {
  CALL_PARAM,
  EMPTY_CALL_STATE,
  activeCallFilterCount,
  readCallUrlState,
  toCallQuery,
  writeCallUrlState,
  type CallUrlState,
} from "./callsFilters";
import { useCalls } from "./useRail";

interface Walk {
  readonly cursor: string | null;
  readonly stack: readonly (string | null)[];
}

const FIRST_PAGE_WALK: Walk = { cursor: null, stack: [] };

export function CallsScreen(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => readCallUrlState(searchParams), [searchParams]);
  const filterCount = activeCallFilterCount(state);
  const [walk, setWalk] = useState<Walk>(() => ({ cursor: state.cursor, stack: [] }));

  const apply = useCallback(
    (next: CallUrlState) => {
      setSearchParams(writeCallUrlState(next), { replace: true });
    },
    [setSearchParams],
  );

  const patchFilters = useCallback(
    (partial: Partial<Omit<CallUrlState, "cursor">>) => {
      setWalk(FIRST_PAGE_WALK);
      apply({ ...state, ...partial, cursor: null });
    },
    [apply, state],
  );

  const clearFilters = useCallback(() => {
    setWalk(FIRST_PAGE_WALK);
    apply(EMPTY_CALL_STATE);
  }, [apply]);

  const filters = useMemo(() => toCallQuery(state), [state]);
  const page = useMemo<CountedPageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: state.cursor }),
    [state.cursor],
  );

  const calls = useCalls(filters, page);
  useSessionGuard([calls.error]);

  const items = calls.data?.items ?? [];
  const nextCursor = calls.data === undefined ? null : nextCursorOf(calls.data);
  const isWalkCurrent = walk.cursor === state.cursor;
  const hasPrev = isWalkCurrent && walk.stack.length > 0;

  const goNext = useCallback(() => {
    if (nextCursor === null) return;
    setWalk((previous) =>
      previous.cursor === state.cursor
        ? { cursor: nextCursor, stack: [...previous.stack, state.cursor] }
        : { cursor: nextCursor, stack: [state.cursor] },
    );
    apply({ ...state, cursor: nextCursor });
  }, [apply, nextCursor, state]);

  const goPrev = useCallback(() => {
    if (!hasPrev) return;
    const previous = walk.stack[walk.stack.length - 1] ?? null;
    setWalk({ cursor: previous, stack: walk.stack.slice(0, -1) });
    apply({ ...state, cursor: previous });
  }, [apply, hasPrev, state, walk]);

  const columns = useMemo(() => buildCallColumns(t), [t]);

  const chips = useMemo<readonly FilterChip[]>(() => {
    const out: FilterChip[] = [];
    if (state.method.length > 0) {
      out.push({
        id: CALL_PARAM.method,
        field: t("billing.calls.chips.method"),
        value: state.method.join(" or "),
        onRemove: () => {
          patchFilters({ method: [] });
        },
      });
    }
    if (state.faultsOnly) {
      out.push({
        id: CALL_PARAM.faultsOnly,
        field: t("billing.calls.chips.faultsOnly"),
        value: t("common.yes"),
        onRemove: () => {
          patchFilters({ faultsOnly: false });
        },
      });
    }
    if (state.ref !== null) {
      out.push({
        id: CALL_PARAM.ref,
        field: t("billing.calls.chips.reference"),
        value: state.ref,
        onRemove: () => {
          patchFilters({ ref: null });
        },
      });
    }
    if (state.transactionId !== null) {
      out.push({
        id: CALL_PARAM.transactionId,
        field: t("billing.calls.chips.transactionId"),
        value: state.transactionId,
        onRemove: () => {
          patchFilters({ transactionId: null });
        },
      });
    }
    if (state.from !== null) {
      out.push({
        id: CALL_PARAM.from,
        field: t("billing.calls.chips.from"),
        value: state.from,
        onRemove: () => {
          patchFilters({ from: null });
        },
      });
    }
    if (state.to !== null) {
      out.push({
        id: CALL_PARAM.to,
        field: t("billing.calls.chips.through"),
        value: state.to,
        onRemove: () => {
          patchFilters({ to: null });
        },
      });
    }
    return out;
  }, [patchFilters, state, t]);

  const error = calls.error;

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("billing.calls.title")}
          subtitle={t("billing.calls.subtitle")}
          filters={
            /* Two arms, not a checkbox: `aria-pressed` carries the state on a non-colour
               channel, and "all calls" is a real choice rather than the absence of one. */
            <Segmented
              ariaLabel={t("billing.calls.chips.faultsOnly")}
              value={state.faultsOnly ? "faults" : "all"}
              options={[
                { value: "all", label: t("billing.calls.allCalls") },
                { value: "faults", label: t("billing.calls.faultsOnly") },
              ]}
              onChange={(value) => {
                patchFilters({ faultsOnly: value === "faults" });
              }}
            />
          }
          actions={
            <ToolbarButton
              onClick={() => {
                navigate(PATH.rail);
              }}
            >
              {t("billing.title")}
            </ToolbarButton>
          }
        />

        {error === null ? null : (
          <ErrorNote
            tone={error.status === 403 ? "denied" : error.status === 0 ? "offline" : "error"}
            title={t("errors.query.failedTitle", { subject: t("billing.subjectCalls") })}
            message={error.message}
            hint={error.correlationId === null ? undefined : `${error.endpoint} · ${error.correlationId}`}
            retryable={error.status !== 403}
            isRetrying={calls.isFetching}
            onRetry={() => {
              void calls.refetch();
            }}
          />
        )}

        <FilterChips chips={chips} onClearAll={filterCount === 0 ? undefined : clearFilters} />

        <section aria-label={t("billing.calls.title")} className="flex min-w-0 flex-col gap-3">
          <div
            aria-busy={calls.isPlaceholderData}
            className={cn("transition-opacity", calls.isPlaceholderData && "opacity-60")}
          >
            <DataTable
              caption={t("billing.calls.caption")}
              columns={columns}
              rows={items}
              getRowKey={(row) => row.id}
              isLoading={calls.isPending}
              skeletonRows={DEFAULT_PAGE_LIMIT}
              emptyMessage={
                error !== null ? (
                  <EmptyState
                    title={t("billing.calls.emptyFailed")}
                    message={t("billing.calls.emptyFailedMessage")}
                  />
                ) : filterCount > 0 ? (
                  <EmptyState
                    title={t("billing.calls.emptyFiltered")}
                    message={t("billing.calls.emptyFilteredMessage")}
                    action={
                      <ToolbarButton onClick={clearFilters}>
                        {t("common.clearAllFilters")}
                      </ToolbarButton>
                    }
                  />
                ) : (
                  <EmptyState
                    title={t("billing.calls.empty")}
                    message={t("billing.calls.emptyMessage")}
                  />
                )
              }
            />
          </div>

          <p className="m-0 text-[11px] leading-[1.45] text-ink-400">
            {t("billing.calls.peerIpNote")}
          </p>

          <CursorPager
            rangeLabel={t("billing.range.onPage", { count: items.length })}
            hasPrev={hasPrev}
            hasNext={nextCursor !== null}
            isFetching={calls.isFetching}
            onPrev={goPrev}
            onNext={goNext}
          />
        </section>
      </div>
    </main>
  );
}
