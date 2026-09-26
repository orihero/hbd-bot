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
 * ## The strip is two sums of money, two counts, and a fifth figure it refuses to print
 *
 * Above the filters sit four tiles. The first two are MONEY — what was opened in the window and
 * what settled — with the row count as a caption under each; the other two are counts because
 * faults and stuck payments are things to go and look at rather than money. They were four
 * counts until an operator pointed out that a payment rail was answering "how much did we take"
 * with a number of rows, which reads identically for one 15 000 soʻm song and for a hundred.
 *
 * A Day / Week / Month / Year picker sits above them and scopes the WHOLE screen — it writes
 * `from`/`to` into the URL, which the tiles, the table and the range label all already read. They come from two aggregates the panel already
 * serves and cost no backend work. What they do NOT include is a settlement rate — the
 * denominator here is dominated by stub-rail traffic, so the percentage would be a number about
 * the sandbox wearing the name of the business. {@link buildRailStats} argues it in full, and
 * that comment is the reason nobody should add it back.
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
  type Attention,
  type AttentionPopulation,
  type IntentPage,
  type IntentProduct,
  type IntentState,
  type RailFunnel,
  type SettleSource,
  type StateCount,
} from "@/api/billing";
import { DEFAULT_PAGE_LIMIT, nextCursorOf, type CountedPageRequest } from "@/api/pagination";
import { CursorPager } from "@/components/CursorPager";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { PageStats, type PageStat } from "@/components/PageStats";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { PATH, intentDetailPath } from "@/app/paths";
import { formatCount, money } from "@/features/dashboard/adapt";
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
import type { AdminQueryError } from "@/lib/adminQuery";
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
  BILLING_PERIODS,
  periodRange,
  readIntentUrlState,
  toIntentQuery,
  type BillingPeriod,
  writeIntentUrlState,
  type IntentUrlState,
} from "./intentsFilters";
import { useAttention, useIntents, useRailFunnel, useRailStatus } from "./useRail";

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

/**
 * Just enough of a query result for the tile builder to read.
 *
 * Structural on purpose. The builder needs the answer and the failure and nothing else, and
 * typing the parameters as `UseQueryResult` would drag twenty fields of refetch machinery into
 * a function that is otherwise pure and readable end to end.
 */
interface AggregateRead<T> {
  readonly data: T | undefined;
  readonly error: AdminQueryError | null;
}

/** The translator, as `intentColumns.tsx` types it: a builder takes `t`, never a hook. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

/**
 * Which rail-side transaction state is MONEY THAT ARRIVED.
 *
 * `performed`, and only `performed`. The other three are `created` (a form the customer has
 * opened and not paid), `cancelled` (a decline, often three in a row off one failing card) and
 * `cancelled_after_perform` — which this deployment never writes at all, because a cancel of a
 * performed charge is refused with `-31007` rather than burning a fungible credit balance that
 * has no lot structure. Totalling the funnel's `transactions` list instead would put every
 * declined attempt under a tile labelled "Settled", which is the one word on this strip that an
 * operator reads as "the money is in".
 */
const SETTLED_TRANSACTION_STATE = "performed";

/**
 * A sparse `{state, count}` list, totalled.
 *
 * The wire omits a state with no rows rather than sending it at zero, so there is no fixed set
 * of members to index and a total is a sum over whatever arrived. For `intents` the sum is
 * exactly "payments opened in this window", because an intent is in precisely one state.
 */
function totalOf(counts: readonly StateCount[]): number {
  return counts.reduce((sum, entry) => sum + entry.count, 0);
}

/**
 * One state's count out of a sparse list.
 *
 * Absent means no rows in that state — which is a real zero, not an unmeasured figure, because
 * the query ran over the whole window and simply found none. The probe beside it (see
 * {@link buildRailStats}) is what separates that from "this rail has never run here", and it is
 * the reason a `0` is allowed to print at all.
 */
function countOf(counts: readonly StateCount[], state: string): number {
  return counts.find((entry) => entry.state === state)?.count ?? 0;
}

/**
 * The money in a sparse `{state, count, amountMinor}` list, totalled.
 *
 * Minor units throughout — tiyin, never soʻm — because `money()` is the only place that
 * divides and rounding twice is how a strip and a dossier come to disagree by a tiyin about
 * the same window.
 */
function amountOf(counts: readonly StateCount[]): number {
  return counts.reduce((sum, entry) => sum + entry.amountMinor, 0);
}

/** One state's money out of a sparse list. Absent is a real zero — see {@link countOf}. */
function amountOfState(counts: readonly StateCount[], state: string): number {
  return counts.find((entry) => entry.state === state)?.amountMinor ?? 0;
}

/**
 * The currency to label this funnel's sums with.
 *
 * Read off the INTENT rows and never off the transactions, which carry no currency at all —
 * Payme denominates in soʻm and the column does not exist. `UZS` is the fallback for a window
 * with no intents in it, and it is a label rather than a claim: there is no money to mislabel
 * when there is no money, and a tile with no figure prints no unit anyway.
 *
 * A window holding two currencies is not summable and this does not pretend otherwise — it
 * returns the first, and the sum above is then wrong. That is a deliberate deferral, not an
 * oversight: `payment_intents.currency` has held exactly one value since the rail was built,
 * the server groups by it so the day a second appears the rows arrive separated, and the honest
 * fix at that point is a tile PER currency rather than a smarter label on one.
 */
function currencyOf(counts: readonly StateCount[]): string {
  return counts.find((entry) => entry.currency !== null)?.currency ?? "UZS";
}

/**
 * The four tiles above the table.
 *
 * ## Why every tile has three arms and not two
 *
 * A count here is measured, absent because the read failed, or absent because the rail has
 * never done the thing being counted — and those are three different sentences. The funnel
 * carries a window-BLIND probe beside each figure for exactly this purpose (`hasOpenedAnyIntent`,
 * `hasRecordedTransaction`, `hasRecordedInboundCall`), so `0` never has to mean two things: with
 * the probe false the tile prints a dash and says `notInstrumented`, which is the same
 * distinction this screen's three empty states already draw between "nothing matches" and "no
 * payment has ever been opened here". Zero-filling a rail that was never switched on would read
 * as an outage on a deployment where the stub provider is still the default.
 *
 * ## The tile that is deliberately missing
 *
 * **There is no settlement-rate tile, and one must not be added back.** `transactions ÷ intents`
 * is arithmetic this function could do in one line, and the number it produced would be a
 * number about the SANDBOX: the denominator on this deployment is dominated by stub-rail
 * traffic — checkouts the stub provider opens and settles without money ever moving — so the
 * percentage would carry the business's name over the test harness's behaviour. An operator
 * would then watch it "fall" whenever real Payme volume grew as a share of a mixed population.
 * The honest version of that figure needs a denominator that excludes sandbox intents, which is
 * a server-side question (`?sandbox=false` is a LIST filter; `/metrics/rail/funnel` has no such
 * parameter), not a division to do in the browser. `/metrics/rail/settlement` is not the way
 * round it either: it 422s without an explicit `from`, so a strip that wanted it would have to
 * invent a window, and an invented window is an invented figure.
 */
function buildRailStats(
  funnel: AggregateRead<RailFunnel>,
  attention: AggregateRead<Attention>,
  t: Translate,
): readonly PageStat[] {
  /* Two captions, and they are not interchangeable. "The read failed" is a thing to retry;
     "this has never run here" is a fact about the deployment and retrying changes nothing. */
  const unreadable = t("errors.query.failedTitle", { subject: t("billing.subjectPayments") });
  const neverRan = t("common.stats.unavailable.notInstrumented");

  /**
   * One funnel tile: the figure, the probe that says whether the figure means anything, and the
   * tone. Written once because the three funnel tiles differ only in which field they read —
   * three transcriptions of this reasoning would eventually disagree about which arm wins.
   */
  const funnelTile = (
    key: string,
    label: string,
    read: (data: RailFunnel) => number,
    hasEverRun: (data: RailFunnel) => boolean,
    isWarnWhenNonZero = false,
  ): PageStat => {
    const data = funnel.data;
    /* The error arm comes FIRST, and it has to: `LIST_READ` keeps the previous window's answer
       as placeholder data, so a failed read can arrive with `data` still populated from the
       range the operator was looking at a moment ago. Reading it here would print last week's
       counts as this week's — the table's `isPlaceholderData` dimming exists for the same
       hazard, and a tile cannot dim. A figure whose read failed is absent, and says so. */
    if (funnel.error !== null || data === undefined) {
      /* `data === undefined` also covers the first flight, but the strip is rendered with
         `isLoading` then and `PageStats` prints skeletons over whatever this returned. */
      return { key, label, value: null, reason: unreadable };
    }
    if (!hasEverRun(data)) return { key, label, value: null, reason: neverRan };
    const count = read(data);
    return {
      key,
      label,
      value: formatCount(count),
      ...(isWarnWhenNonZero && count > 0 ? { tone: "warn" as const } : {}),
    };
  };

  /**
   * A funnel tile that leads with MONEY, with the row count as its caption.
   *
   * The same three arms as {@link funnelTile} and for the same reasons — a failed read, a rail
   * that has never run, and a measured figure are three different sentences — but the figure
   * is a sum of `amountMinor` rather than a count of rows.
   *
   * **Why the count survives at all.** It is the only thing that separates one 15 000 soʻm
   * payment from a hundred of them, and `amount ÷ count` is the average payment, which is how
   * a pricing change shows up on this screen. It is rendered dimmer and smaller than the
   * money, because the money is the answer and the count is what the answer is made of.
   */
  const moneyTile = (
    key: string,
    label: string,
    readAmount: (data: RailFunnel) => number,
    readCount: (data: RailFunnel) => number,
    hasEverRun: (data: RailFunnel) => boolean,
  ): PageStat => {
    const data = funnel.data;
    /* Error arm first, for the reason `funnelTile` writes out: a failed read can still carry
       the PREVIOUS window's data as placeholder, and last week's takings printed as this
       week's is the one mistake a money tile must never make. */
    if (funnel.error !== null || data === undefined) {
      return { key, label, value: null, reason: unreadable };
    }
    if (!hasEverRun(data)) return { key, label, value: null, reason: neverRan };
    const count = readCount(data);
    const { value, unit } = money(readAmount(data), currencyOf(data.intents));
    return {
      key,
      label,
      value,
      unit,
      caption: t("billing.stats.ofPayments", { count: formatCount(count) }),
    };
  };

  const attentionData = attention.data;
  /* The three populations are summed because they are one queue as far as this strip is
     concerned: each is a payment somebody has to go and look at, and which of the three it is
     belongs to the filter panel below, where picking one narrows the table to those rows. */
  const needsAttention =
    attention.error !== null || attentionData === undefined
      ? null
      : attentionData.awaitingHeldPastTimeout +
        attentionData.paidNeverAnnounced +
        attentionData.paidWithNoReceipt;

  return [
    /* The two money tiles. They were counts until an operator pointed out that a payment rail
       read to answer "how much did we take" was printing how many ROWS it had — which is the
       same number for one 15 000 soʻm song and for a hundred of them. */
    moneyTile(
      "intents",
      t("billing.stats.intents"),
      (data) => amountOf(data.intents),
      (data) => totalOf(data.intents),
      (data) => data.hasOpenedAnyIntent,
    ),
    moneyTile(
      "settled",
      t("billing.stats.settled"),
      (data) => amountOfState(data.transactions, SETTLED_TRANSACTION_STATE),
      (data) => countOf(data.transactions, SETTLED_TRANSACTION_STATE),
      (data) => data.hasRecordedTransaction,
    ),
    funnelTile(
      "faults",
      t("billing.stats.faults"),
      (data) => data.rpcFaults,
      /* The probe is about INBOUND CALLS, not about faults: "no fault in this window" is only
         good news if the gateway has ever called us at all. On a deployment the rail has never
         reached, an unremarkable `0` beside Faults is the most misleading figure this strip
         could print — it is silence rendered as health. */
      (data) => data.hasRecordedInboundCall,
      true,
    ),
    {
      key: "attention",
      label: t("billing.stats.attention"),
      value: needsAttention === null ? null : formatCount(needsAttention),
      /* No probe on this route, and none is needed: the three counters are computed from the
         payments table as of now, with no window, so a genuine `0` means "nothing is stuck"
         whatever this rail has or has not done. That is the one figure on the strip a zero is
         unambiguously good news for. */
      ...(needsAttention === null ? { reason: unreadable } : {}),
      ...(needsAttention !== null && needsAttention > 0 ? { tone: "warn" as const } : {}),
    },
  ];
}

/**
 * Day / Week / Month / Year — the one control that scopes this whole screen.
 *
 * A `radiogroup` and not four buttons: exactly one is in force at a time and an assistive
 * technology should be told that, so arrow keys move between them and only the selected one is
 * in the tab order. `aria-checked` carries the state rather than colour alone.
 *
 * Nothing is selected when the range came from the date boxes, and that is the honest reading —
 * a custom window is not one of these four, and highlighting the nearest would be a label on
 * somebody else's range. See `BILLING_PERIODS` for why the label is stored at all.
 */
function PeriodPicker({
  period,
  onPick,
  t,
}: {
  readonly period: BillingPeriod | null;
  readonly onPick: (next: BillingPeriod) => void;
  readonly t: Translate;
}): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label={t("billing.stats.period.label")}
      className="flex flex-wrap items-center gap-2"
    >
      {BILLING_PERIODS.map((value) => {
        const isActive = period === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={isActive}
            /* Only the active one is tabbable; the arrows walk the rest. That is the radiogroup
               contract, and without it a four-button group costs four tab stops on a screen
               that already has a filter panel below it. */
            tabIndex={isActive ? 0 : -1}
            onClick={() => {
              onPick(value);
            }}
            onKeyDown={(event) => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
              event.preventDefault();
              const at = BILLING_PERIODS.indexOf(value);
              const step = event.key === "ArrowRight" ? 1 : -1;
              /* Wraps, so the group has no dead end at either edge. */
              const next =
                BILLING_PERIODS[(at + step + BILLING_PERIODS.length) % BILLING_PERIODS.length];
              if (next !== undefined) onPick(next);
            }}
            className={cn(
              "h-9 cursor-pointer rounded-pill border px-4",
              "text-[13px] font-medium leading-none tracking-[-0.1px]",
              "transition-[color,background-color] focus-visible:outline focus-visible:outline-2",
              "focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
              isActive
                ? "border-accent bg-accent text-on-accent"
                : "border-stroke bg-card text-ink-500 hover:text-label",
            )}
          >
            {t(`billing.stats.period.${value}`)}
          </button>
        );
      })}
    </div>
  );
}

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

  /*
   * The strip's two reads.
   *
   * The funnel takes the screen's DATE RANGE and nothing else: the tile says "intents opened in
   * the window", and a strip that ignored the picker would print a different population's total
   * directly above a table that had been narrowed to a week. The other five filters are
   * deliberately not carried — `/metrics/rail/funnel` has no `state`, `product` or `sandbox`
   * parameter, and a strip that silently answered a wider question than its chips suggested
   * would be worse than one that plainly answers the window's.
   *
   * The attention counters take no window at all, because the wire has none. See `useAttention`.
   */
  const railWindow = useMemo(() => ({ from: state.from, to: state.to }), [state.from, state.to]);
  const funnel = useRailFunnel(railWindow);
  const attention = useAttention();

  useSessionGuard([payments.error, railStatus.error, funnel.error, attention.error]);

  const stats = useMemo(() => buildRailStats(funnel, attention, t), [attention, funnel, t]);
  /* `isPlaceholderData` and not just `isPending`: `LIST_READ` keeps the previous window's
     figures across a date change, and a tile has no way to dim itself the way the table does.
     Skeletons for that moment say "asking" where four confident numbers would say "this is the
     answer for the range you just typed". A read that has FAILED is not loading, however —
     without that guard a failed window would hold the skeletons on screen for ever, which is a
     spinner standing in for an error message. */
  const isStripLoading =
    (funnel.error === null && (funnel.isPending || funnel.isPlaceholderData)) ||
    (attention.error === null && (attention.isPending || attention.isPlaceholderData));

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

        {/* Above the filter panel, inside the same 1392 band as the toolbar and the table, so
            the strip reads as the header of the question rather than as a widget beside it. It
            renders unconditionally: a funnel or attention failure is four dashes with a caption
            HERE, and the payments table below is a separate read that must still render — the
            aggregates are the context, the ledger is the work. */}
        {/* The scope, above the money it scopes. One click writes `from`/`to` for the WHOLE
            screen — the tiles, the table and the range label below them — because a payments
            page showing takings for one window over a list for another is a screen that invites
            an operator to do arithmetic across two questions. */}
        <PeriodPicker
          period={state.period}
          onPick={(next) => {
            const { from, to } = periodRange(next, new Date());
            patchFilters({ from, to, period: next });
          }}
          t={t}
        />

        <PageStats stats={stats} isLoading={isStripLoading} />

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
                    /* `period: null` rides along: the moment an operator types a date the
                       range is theirs, and a button left highlighted would be a label on a
                       window it did not produce. */
                    patchFilters({ from: localInputToIso(event.target.value), period: null });
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
                    patchFilters({ to: localInputToIso(event.target.value), period: null });
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
