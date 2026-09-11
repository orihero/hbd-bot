/**
 * `/billing` — the section's front door: every checkout the bot opened, newest first.
 *
 * One row per PAYMENT, with its whole fulfilment chain answered as three booleans. The columns
 * live in `intentColumns.tsx` and the URL codec in `intentsFilters.ts`, so this file is the
 * wiring: read the URL, ask the question, render the answer.
 *
 * ## The screen is the table, the filters and the lookup
 *
 * It replaced a five-band status board, which measured the rail at length and in prose. Every
 * number that board printed is a filter here or a column on a row, and the one control it
 * carried that nothing else does — the pause switch — is a button in this toolbar.
 *
 * ## Previous is this tab's memory
 *
 * The API mints no previous cursor — there is no page number and no offset — so a screen that
 * offers Back keeps the cursors it has walked on a stack. A cursor arriving from anywhere else
 * (a pasted link, the browser's Back button) is DETECTED rather than assumed to be the next
 * step of this walk: Previous still works, because we know the cursor we came from, but the
 * stack starts again from where we actually are rather than pretending to a history this tab
 * does not have.
 *
 * ## Polling stops while the pause dialog is open
 *
 * The switch is what that dialog is about. A value that changed underneath a confirmation
 * would be a confirmation about something else.
 */

import { SlidersHorizontal } from "lucide-react";
import { useCallback, useMemo, useState, type JSX } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  ATTENTION_POPULATION_VALUES,
  INTENT_PRODUCT_VALUES,
  INTENT_STATE_VALUES,
  SETTLE_SOURCE_VALUES,
  type AttentionPopulation,
  type IntentPage,
  type IntentProduct,
  type IntentState,
  type SettleSource,
} from "@/api/billing";
import { DEFAULT_PAGE_LIMIT, nextCursorOf, type CountedPageRequest } from "@/api/pagination";
import { CursorPager } from "@/components/CursorPager";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { PATH, intentDetailPath } from "@/app/paths";
import { isoToLocalInput, localInputToIso } from "@/features/generations/attemptFormat";
/* The filter kit lives beside the screen that first needed it; `broadcasts` reaches for
   `users`' copy the same way. A fourth transcription of the same seven controls would be four
   places to fix one focus ring. */
import {
  EnumToggleGroup,
  FilterField,
  FilterPanel,
  SingleEnumSelect,
  TriStateSelect,
} from "@/features/generations/filterControls";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { useCanControlRail } from "@/lib/rbac";
import { cn } from "@/lib/cn";
import { useSessionGuard } from "@/state/useSessionGuard";

import { LookupBox } from "./LookupBox";
import { RailPauseDialog } from "./RailPauseDialog";
import { buildIntentColumns } from "./intentColumns";
import {
  EMPTY_INTENT_STATE,
  INTENT_PARAM,
  activeIntentFilterCount,
  readIntentUrlState,
  toIntentQuery,
  writeIntentUrlState,
  type IntentUrlState,
} from "./intentsFilters";
import { useIntents, useRailStatus } from "./useRail";

/**
 * The cursors this tab has walked. See the module header — the API mints no previous cursor.
 *
 * There is no page ORDINAL here, deliberately. A cursor is opaque and carries no position, so a
 * tab that arrived on a pasted link cannot know which page it is on; and the range label this
 * screen shows says how many rows are in front of the operator rather than which page of how
 * many, which is a claim `withTotal` would have to be paid for to make.
 */
interface Walk {
  readonly cursor: string | null;
  readonly stack: readonly (string | null)[];
}

const FIRST_PAGE_WALK: Walk = { cursor: null, stack: [] };

/** Ties the Filters button's `aria-controls` to the panel it discloses. */
const FILTER_PANEL_ID = "intent-filters";

/** The three attention populations, in the order the API declares them. */
const ATTENTION_LABEL_KEY: Readonly<Record<AttentionPopulation, TranslationPath>> = {
  awaiting_stale: "billing.attention.awaitingStale",
  paid_unnotified: "billing.attention.paidUnnotified",
  paid_no_receipt: "billing.attention.paidNoReceipt",
};

/** The kit's 47-high field, so the two date boxes match every other control in the panel. */
const DATE_INPUT_CLASS = cn(
  "h-[47px] w-auto min-w-0 flex-1 rounded-field border border-stroke bg-card py-[10px] pl-[12px] pr-[10px]",
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-label",
  "shadow-field outline-none transition-shadow",
  "focus:border-accent-deep focus:ring-2 focus:ring-accent",
);

export function IntentsScreen(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => readIntentUrlState(searchParams), [searchParams]);
  const filterCount = activeIntentFilterCount(state);

  const [walk, setWalk] = useState<Walk>(() => ({ cursor: state.cursor, stack: [] }));
  /* Open when the URL already carries a question, so a pasted link SHOWS what it is asking. */
  const [isPanelOpen, setIsPanelOpen] = useState(() => filterCount > 0);

  const canControl = useCanControlRail();
  const [pauseTarget, setPauseTarget] = useState<boolean | null>(null);
  const isDialogOpen = pauseTarget !== null;
  const railStatus = useRailStatus(!isDialogOpen);

  const apply = useCallback(
    (next: IntentUrlState) => {
      setSearchParams(writeIntentUrlState(next), { replace: true });
    },
    [setSearchParams],
  );

  /**
   * Any filter edit: back to page one, and the walked cursors go with the old question.
   *
   * `Omit<…, "cursor">` on the patch makes "a filter change that keeps the cursor" a compile
   * error rather than a page of the previous question's rows under the new chips.
   */
  const patchFilters = useCallback(
    (partial: Partial<Omit<IntentUrlState, "cursor">>) => {
      setWalk(FIRST_PAGE_WALK);
      apply({ ...state, ...partial, cursor: null });
    },
    [apply, state],
  );

  const clearFilters = useCallback(() => {
    setWalk(FIRST_PAGE_WALK);
    apply(EMPTY_INTENT_STATE);
  }, [apply]);

  const filters = useMemo(() => toIntentQuery(state), [state]);
  const page = useMemo<CountedPageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: state.cursor }),
    [state.cursor],
  );

  const payments = useIntents(filters, page);
  useSessionGuard([payments.error, railStatus.error]);

  const data: IntentPage | undefined = payments.data;
  const items = data?.items ?? [];
  const nextCursor = data === undefined ? null : nextCursorOf(data);
  const isWalkCurrent = walk.cursor === state.cursor;
  const hasPrev = isWalkCurrent && walk.stack.length > 0;

  const goNext = useCallback(() => {
    if (nextCursor === null) return;
    setWalk((previous) =>
      previous.cursor === state.cursor
        ? { cursor: nextCursor, stack: [...previous.stack, state.cursor] }
        : /* The page we are leaving was not reached through this walk — a pasted link, or the
             browser's Back button — so the stack starts again from where we actually are. */
          { cursor: nextCursor, stack: [state.cursor] },
    );
    apply({ ...state, cursor: nextCursor });
  }, [apply, nextCursor, state]);

  const goPrev = useCallback(() => {
    if (!hasPrev) return;
    const previous = walk.stack[walk.stack.length - 1] ?? null;
    setWalk({ cursor: previous, stack: walk.stack.slice(0, -1) });
    apply({ ...state, cursor: previous });
  }, [apply, hasPrev, state, walk]);

  const columns = useMemo(() => buildIntentColumns(t), [t]);

  const chips = useMemo<readonly FilterChip[]>(() => {
    const out: FilterChip[] = [];
    if (state.state.length > 0) {
      out.push({
        id: INTENT_PARAM.state,
        field: t("billing.intents.chips.state"),
        value: state.state.join(" or "),
        onRemove: () => {
          patchFilters({ state: [] });
        },
      });
    }
    if (state.product.length > 0) {
      out.push({
        id: INTENT_PARAM.product,
        field: t("billing.intents.chips.product"),
        value: state.product.join(" or "),
        onRemove: () => {
          patchFilters({ product: [] });
        },
      });
    }
    if (state.settledBy !== null) {
      out.push({
        id: INTENT_PARAM.settledBy,
        field: t("billing.intents.chips.settledBy"),
        value:
          state.settledBy === "operator"
            ? t("billing.intents.settledByOperator")
            : t("billing.intents.settledByRail"),
        onRemove: () => {
          patchFilters({ settledBy: null });
        },
      });
    }
    if (state.attention !== null) {
      const labels = {
        awaiting_stale: t("billing.attention.awaitingStale"),
        paid_unnotified: t("billing.attention.paidUnnotified"),
        paid_no_receipt: t("billing.attention.paidNoReceipt"),
      } as const;
      out.push({
        id: INTENT_PARAM.attention,
        field: t("billing.intents.chips.attention"),
        value: labels[state.attention],
        onRemove: () => {
          // The cutoff goes with the population it qualified. Left behind it would sit in the
          // URL meaning nothing, and mean something again the next time somebody filtered.
          patchFilters({ attention: null, staleAfterHours: null });
        },
      });
    }
    if (state.sandbox !== null) {
      out.push({
        id: INTENT_PARAM.sandbox,
        field: t("billing.intents.chips.sandbox"),
        value: state.sandbox ? t("common.yes") : t("common.no"),
        onRemove: () => {
          patchFilters({ sandbox: null });
        },
      });
    }
    if (state.from !== null) {
      out.push({
        id: INTENT_PARAM.from,
        field: t("billing.intents.chips.openedFrom"),
        value: state.from,
        onRemove: () => {
          patchFilters({ from: null });
        },
      });
    }
    if (state.to !== null) {
      out.push({
        id: INTENT_PARAM.to,
        field: t("billing.intents.chips.openedThrough"),
        value: state.to,
        onRemove: () => {
          patchFilters({ to: null });
        },
      });
    }
    return out;
  }, [patchFilters, state, t]);

  const error = payments.error;
  /*
   * `withTotal` is off — the count is a second query and `bounded_total` saturates at 10,000,
   * so a bare `10000` would be a ceiling wearing a measurement's clothes. `total` and
   * `isTotalExact` travel as a PAIR or not at all, so the label uses the exact form only when
   * the server actually counted; otherwise it says what it can, which is how many rows are on
   * this page.
   */
  const total = data?.meta.total ?? null;
  const rangeLabel =
    total === null || data?.meta.isTotalExact !== true
      ? t("billing.range.onPage", { count: items.length })
      : t("billing.range.onPageOf", { count: items.length, total });

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("billing.intents.title")}
          filters={<LookupBox />}
          actions={
            <>
              <ToolbarButton
                icon={<SlidersHorizontal className="h-5 w-5" strokeWidth={1.75} />}
                ariaExpanded={isPanelOpen}
                ariaControls={FILTER_PANEL_ID}
                onClick={() => {
                  setIsPanelOpen((open) => !open);
                }}
              >
                {filterCount === 0
                  ? t("common.filters")
                  : t("common.filtersCount", { count: filterCount })}
              </ToolbarButton>
              {/* Hidden, never disabled, for a role without the cell: a press would be a 403
                  and a `permission.denied` audit row against somebody who did nothing wrong.
                  The server is still the authority — this only decides what is drawn. */}
              {canControl && railStatus.data !== undefined ? (
                <ToolbarButton
                  onClick={() => {
                    setPauseTarget(!railStatus.data.isPaused);
                  }}
                >
                  {railStatus.data.isPaused
                    ? t("billing.pause.resumeAction")
                    : t("billing.pause.pauseAction")}
                </ToolbarButton>
              ) : null}
              <ToolbarButton
                onClick={() => {
                  navigate(PATH.railCalls);
                }}
              >
                {t("billing.calls.title")}
              </ToolbarButton>
            </>
          }
        />

        {isPanelOpen ? (
          <FilterPanel id={FILTER_PANEL_ID}>
            <FilterField label={t("billing.intents.columns.opened")} as="div">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="datetime-local"
                  aria-label={t("billing.intents.chips.openedFrom")}
                  value={isoToLocalInput(state.from)}
                  className={DATE_INPUT_CLASS}
                  onChange={(event) => {
                    patchFilters({ from: localInputToIso(event.target.value) });
                  }}
                />
                <span aria-hidden className="text-[12px] text-ink-300">
                  –
                </span>
                <input
                  type="datetime-local"
                  aria-label={t("billing.intents.chips.openedThrough")}
                  value={isoToLocalInput(state.to)}
                  className={DATE_INPUT_CLASS}
                  onChange={(event) => {
                    patchFilters({ to: localInputToIso(event.target.value) });
                  }}
                />
              </div>
            </FilterField>
            {/* The enum members are printed raw, exactly as the State and Product columns
                print them: a filter whose word differs from the cell it selects is a filter
                somebody has to translate before they can trust it. */}
            <EnumToggleGroup<IntentState>
              label={t("billing.intents.chips.state")}
              values={INTENT_STATE_VALUES}
              selected={state.state}
              format={(value) => value}
              onChange={(next) => {
                patchFilters({ state: next });
              }}
            />
            <EnumToggleGroup<IntentProduct>
              label={t("billing.intents.chips.product")}
              values={INTENT_PRODUCT_VALUES}
              selected={state.product}
              format={(value) => value}
              onChange={(next) => {
                patchFilters({ product: next });
              }}
            />
            <SingleEnumSelect<SettleSource>
              label={t("billing.intents.chips.settledBy")}
              values={SETTLE_SOURCE_VALUES}
              value={state.settledBy}
              anyLabel={t("common.any")}
              format={(value) =>
                value === "operator"
                  ? t("billing.intents.settledByOperator")
                  : t("billing.intents.settledByRail")
              }
              onChange={(settledBy) => {
                patchFilters({ settledBy });
              }}
            />
            <SingleEnumSelect<AttentionPopulation>
              label={t("billing.intents.chips.attention")}
              values={ATTENTION_POPULATION_VALUES}
              value={state.attention}
              anyLabel={t("common.any")}
              format={(value) => t(ATTENTION_LABEL_KEY[value])}
              onChange={(attention) => {
                /* The cutoff goes with the population it qualified — see the chip's remove. */
                patchFilters({ attention, staleAfterHours: null });
              }}
            />
            <TriStateSelect
              label={t("billing.intents.chips.sandbox")}
              value={state.sandbox}
              anyLabel={t("common.any")}
              trueLabel={t("common.yes")}
              falseLabel={t("common.no")}
              onChange={(sandbox) => {
                patchFilters({ sandbox });
              }}
            />
          </FilterPanel>
        ) : null}

        {error === null ? null : (
          <ErrorNote
            tone={error.status === 403 ? "denied" : error.status === 0 ? "offline" : "error"}
            title={t("errors.query.failedTitle", { subject: t("billing.subjectPayments") })}
            message={error.message}
            hint={error.correlationId === null ? undefined : `${error.endpoint} · ${error.correlationId}`}
            retryable={error.status !== 403}
            isRetrying={payments.isFetching}
            onRetry={() => {
              void payments.refetch();
            }}
          />
        )}

        <FilterChips chips={chips} onClearAll={filterCount === 0 ? undefined : clearFilters} />

        <section aria-label={t("billing.intents.title")} className="flex min-w-0 flex-col gap-3">
          <div
            aria-busy={payments.isPlaceholderData}
            /* A page still loading under NEW filters is the PREVIOUS answer; dimming it says
               so rather than presenting it under the new chips as this question's. */
            className={cn("transition-opacity", payments.isPlaceholderData && "opacity-60")}
          >
            <DataTable
              caption={t("billing.intents.caption")}
              columns={columns}
              rows={items}
              getRowKey={(row) => row.intentId}
              onRowClick={(row) => {
                navigate(intentDetailPath(row.intentId));
              }}
              isLoading={payments.isPending}
              skeletonRows={DEFAULT_PAGE_LIMIT}
              /* Three empties, three titles, and no paragraph under any of them. "Nothing
                 matches your filters" and "no payment has ever been opened here" have
                 different remedies — one offers Clear all, the other cannot — and a shared
                 "no results" would send an operator to the wrong one. The third is a failed
                 read, whose detail is in the note above the table. */
              emptyMessage={
                error !== null ? (
                  <EmptyState title={t("billing.intents.emptyFailed")} />
                ) : filterCount > 0 ? (
                  <EmptyState
                    title={t("billing.intents.emptyFiltered")}
                    action={
                      <ToolbarButton onClick={clearFilters}>
                        {t("common.clearAllFilters")}
                      </ToolbarButton>
                    }
                  />
                ) : (
                  /* The probe's answer, not the row count's. `data` is undefined only while
                     the first page is in flight, in which case the skeleton is showing and
                     this branch is not rendered. */
                  <EmptyState
                    title={
                      data?.capabilities.hasOpenedAnyIntent === true
                        ? t("billing.intents.emptyFiltered")
                        : t("billing.intents.emptyVirgin")
                    }
                  />
                )
              }
            />
          </div>

          <CursorPager
            rangeLabel={rangeLabel}
            hasPrev={hasPrev}
            hasNext={nextCursor !== null}
            isFetching={payments.isFetching}
            onPrev={goPrev}
            onNext={goNext}
          />
        </section>
      </div>

      <RailPauseDialog
        isOpen={isDialogOpen}
        willPause={pauseTarget ?? false}
        onClose={() => {
          setPauseTarget(null);
        }}
        onDone={() => {
          /* Nothing to do here: `useRailSwitch` has already SET the cached status from the
             response the server re-read, so the toolbar repaints from the switch as STORED
             rather than as requested. A refetch would be a round trip to learn what the
             write already told us, and it would race the operator closing the dialog. */
          setPauseTarget(null);
        }}
      />
    </main>
  );
}
