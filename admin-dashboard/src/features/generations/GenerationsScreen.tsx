import { SlidersHorizontal } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from "react";
import { useSearchParams } from "react-router-dom";

import { CLIENT_ERROR_CODES } from "@/api/client";
import {
  MAX_ERROR_CODE_CHARS,
  MAX_PROVIDER_CHARS,
} from "@/api/constants";
import type { LedgerWindow } from "@/api/dashboard";
import {
  GENERATION_KIND_VALUES,
  NAME_STRATEGY_VALUES,
  PROVIDER_VALUES,
  type AttemptWireView,
  type GenerationKind,
  type GenerationsFilters,
  type NameStrategy,
} from "@/api/generations";
import {
  DEFAULT_PAGE_LIMIT,
  TOTAL_COUNT_CAP,
  nextCursorOf,
  type PageRequest,
} from "@/api/pagination";
import { Badge } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote, type NoteTone } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { PageStats, type PageStat } from "@/components/PageStats";
import { Skeleton } from "@/components/Skeleton";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { formatCount } from "@/features/dashboard/adapt";
import { EMPTY_VALUE } from "@/features/reveal";
import type { AdminQueryError } from "@/lib/adminQuery";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import { useSessionGuard } from "@/state/useSessionGuard";

/** Every sentence on this screen, bound to the operator's chosen language. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

import { AttemptDetailPanel } from "./AttemptDetailPanel";
import {
  GENERATION_KIND_KEY,
  NAME_STRATEGY_KEY,
  formatCostUsd,
  formatLatencyMs,
  isoToLocalInput,
  localInputToIso,
  localZoneLabel,
  splitTimestamp,
} from "./attemptFormat";
import {
  EnumToggleGroup,
  FilterPanel,
  SingleEnumSelect,
  TextFilter,
  TimeRangeFilter,
  TriStateSelect,
} from "./filterControls";
import { useGeneration, useGenerations, useNameAnalytics } from "./useGenerations";

/**
 * `/generations` — the render ledger: every vendor call the pipeline has made, successful or
 * not, and the one screen an operator uses to answer "is name verification working, and what
 * is it costing us".
 *
 * ## Everything narrowing the list is in the URL
 *
 * Seven filters and the cursor live in the query string, so a filtered view is a link — the
 * thing an operator actually pastes into an incident channel — and survives a reload. What is
 * deliberately NOT in the URL is anything personal: no name, no Telegram id, and above all no
 * revealed plaintext. A URL leaks through history, referrers, screenshots and the address bar
 * over a shoulder, and a disclosure bought with a step-up and an audit row must not end up in
 * any of them. The one id here is the attempt's UUID, which is not personal data and which is
 * how the detail panel is addressable at all.
 *
 * ## Paging is keyset, and Previous is the CLIENT'S memory
 *
 * The API mints an opaque `meta.nextCursor` and takes it back verbatim. There is no page
 * number, no offset, and no previous cursor on the wire — so Previous is a stack this
 * component keeps of the cursors it has already used. Which means two honest consequences,
 * both of which show in the range label: a filter change empties the stack (the old cursors
 * address a different walk), and a link pasted with a `?cursor=` opens on a page whose ordinal
 * this tab does not know. It says "this page" rather than inventing "51–100".
 *
 * ## The count is bounded, and says so
 *
 * `withTotal=true` costs a second query and `bounded_total` stops at `TOTAL_COUNT_CAP`, so a
 * `total` of exactly 10 000 with `isTotalExact: false` is a ceiling wearing a measurement's
 * clothes. It renders "10,000+"; the pair is rendered together or not at all.
 *
 * ## Two numbers on this screen are not measurements
 *
 * `costUsd` and `latencyMs` are `null` with `isInstrumented: false` on every row in production
 * today, and they render the dashboard's "not tracked" rather than `$0.00 / 0 ms`. See
 * `attemptFormat.ts`; the rule matters most here, because this is the table somebody would
 * total up to decide what a song costs.
 *
 * ## The strip answers §11.2's question and refuses the two it cannot
 *
 * ADMIN_PANEL_PLAN §11.2 names this screen's question as "is name verification working", with
 * the overall verification rate as its dominant signal — so the three tiles are the attempts
 * in view, that rate, and the denominator the rate was taken over. There is deliberately **no
 * cost tile and no latency tile**, and their absence is the section above made structural: a
 * strip cannot print "not tracked" in a 22px weight forty times a day and be read as anything
 * other than a number, and the one figure this page must never publish is a made-up cost per
 * song. The two columns keep saying it row by row, where the caveat fits.
 *
 * There is no failure breakdown here either. The Dashboard's Performance tab already publishes
 * `failures` over the same window from the same rows; a second copy would be a second caption
 * to keep honest, and the day the two disagree an operator has no way to tell which one lied.
 *
 * ## The strip mixes two populations on purpose, and prints the denominator that shows it
 *
 * The attempts tile is the ledger's own bounded total and obeys all eight filters. The other
 * two come from `/api/metrics/name-analytics`, which takes `?from=&to=` and NOTHING else —
 * there is no parameter on that route for provider, kind, outcome or error code. So filtering
 * to one adapter moves the first tile and not the other two. That is why `Checked` is on the
 * strip at all: a rate whose sample is three attempts is not a measurement of the system, and
 * the denominator standing beside it is how this codebase already handles that everywhere else
 * (`LatencyView.sampleCount` travels with its percentiles, `SubscriptionChurnView.endedPlans`
 * with its rate). An operator who sees `Attempts 3` next to `Checked 1 204` can see at a glance
 * that the two are not counting the same thing; one without the other hides it.
 *
 * ## There is no name search on this screen, and no invented vendor
 *
 * `/api/generations` takes no `q` at all — the free-text filters are `provider` and
 * `errorCode`, both EXACT matches against machine vocabularies, and both labelled as such. The
 * provider suggestions are the nine adapter names `providers/**` actually writes and nothing
 * else; a vendor recalled from a plan document would answer an empty page for ever.
 */

/* -------------------------------------------------------------------------- */
/* URL state                                                                   */
/* -------------------------------------------------------------------------- */

/** Ties the Filters button's `aria-controls` to the panel it discloses. */
const FILTER_PANEL_ID = "generations-filters";

/**
 * The width at which the attempt panel sits BESIDE the table rather than under it — Tailwind's
 * `xl`, which is the breakpoint the grid below switches on. Below it the panel is the last
 * thing on a very long page, so the screen has to take the operator to it.
 */
const TWO_COLUMN_QUERY = "(min-width: 1280px)";

/**
 * The query parameter the open attempt rides in.
 *
 * Exported because `/generations/:attemptId` is a second spelling of the same place and the
 * router canonicalises one into the other; the two must not disagree about the spelling.
 */
export const ATTEMPT_PARAM = "attempt";

const PARAM = {
  kind: "kind",
  provider: "provider",
  isSuccess: "isSuccess",
  errorCode: "errorCode",
  strategy: "strategy",
  isOrphaned: "isOrphaned",
  from: "from",
  to: "to",
  cursor: "cursor",
  attempt: ATTEMPT_PARAM,
} as const;

interface UrlState {
  readonly kind: readonly GenerationKind[];
  readonly provider: string | null;
  readonly isSuccess: boolean | null;
  readonly errorCode: string | null;
  readonly strategy: NameStrategy | null;
  readonly isOrphaned: boolean | null;
  readonly from: string | null;
  readonly to: string | null;
  /** Paging, not a filter. */
  readonly cursor: string | null;
  /** Selection, not a filter — an open panel narrows nothing. */
  readonly attempt: string | null;
}

const EMPTY_STATE: UrlState = {
  kind: [],
  provider: null,
  isSuccess: null,
  errorCode: null,
  strategy: null,
  isOrphaned: null,
  from: null,
  to: null,
  cursor: null,
  attempt: null,
};

function readString(params: URLSearchParams, name: string): string | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/** `?isSuccess=` and `?isSuccess=yes` are both "not a filter"; only the two literals count. */
function readBool(params: URLSearchParams, name: string): boolean | null {
  const raw = params.get(name);
  if (raw === "true") return true;
  if (raw === "false") return false;
  return null;
}

/**
 * Enum parameters are validated against our own vocabulary and unknown members DROPPED.
 *
 * Not passed through: `kind` and `strategy` are typed enums server-side, so an unknown value
 * is a 422 for the whole request — one hand-edited character in a pasted link would blank the
 * table rather than ignore one chip. Free text and the two instants are NOT validated here for
 * the opposite reason: the server's 422 names the parameter, and that is a better answer than
 * this screen silently widening a filter somebody wrote on purpose.
 */
function readEnums<T extends string>(
  params: URLSearchParams,
  name: string,
  values: readonly T[],
): readonly T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of params.getAll(name)) {
    const member = values.find((value) => value === raw);
    if (member === undefined || seen.has(member)) continue;
    seen.add(member);
    out.push(member);
  }
  return out;
}

function readUrlState(params: URLSearchParams): UrlState {
  return {
    kind: readEnums(params, PARAM.kind, GENERATION_KIND_VALUES),
    provider: readString(params, PARAM.provider),
    isSuccess: readBool(params, PARAM.isSuccess),
    errorCode: readString(params, PARAM.errorCode),
    strategy: readEnums(params, PARAM.strategy, NAME_STRATEGY_VALUES)[0] ?? null,
    isOrphaned: readBool(params, PARAM.isOrphaned),
    from: readString(params, PARAM.from),
    to: readString(params, PARAM.to),
    cursor: readString(params, PARAM.cursor),
    attempt: readString(params, PARAM.attempt),
  };
}

/** An absent filter writes NO parameter — `?provider=` is a filter matching nothing. */
function writeUrlState(state: UrlState): URLSearchParams {
  const params = new URLSearchParams();
  for (const kind of state.kind) params.append(PARAM.kind, kind);
  if (state.provider !== null) params.set(PARAM.provider, state.provider);
  if (state.isSuccess !== null) params.set(PARAM.isSuccess, String(state.isSuccess));
  if (state.errorCode !== null) params.set(PARAM.errorCode, state.errorCode);
  if (state.strategy !== null) params.set(PARAM.strategy, state.strategy);
  if (state.isOrphaned !== null) params.set(PARAM.isOrphaned, String(state.isOrphaned));
  if (state.from !== null) params.set(PARAM.from, state.from);
  if (state.to !== null) params.set(PARAM.to, state.to);
  if (state.cursor !== null) params.set(PARAM.cursor, state.cursor);
  if (state.attempt !== null) params.set(PARAM.attempt, state.attempt);
  return params;
}

/** Paging and selection are not filters, and counting them would misreport an empty page. */
function activeFilterCount(state: UrlState): number {
  return (
    (state.kind.length === 0 ? 0 : 1) +
    (state.provider === null ? 0 : 1) +
    (state.isSuccess === null ? 0 : 1) +
    (state.errorCode === null ? 0 : 1) +
    (state.strategy === null ? 0 : 1) +
    (state.isOrphaned === null ? 0 : 1) +
    (state.from === null ? 0 : 1) +
    (state.to === null ? 0 : 1)
  );
}

/* -------------------------------------------------------------------------- */
/* Keyset paging                                                               */
/* -------------------------------------------------------------------------- */

/**
 * One tab's memory of a keyset walk.
 *
 * `bayram.db.admin.page` hands back an opaque `(created_at, id)` cursor and takes it back
 * verbatim. It mints no previous cursor and it accepts no page index, so both "go back" and
 * "which page is this" have to be remembered on the client or not offered at all — and a
 * "Page 3 of 12" invented from a row count would be a control whose first use is a jump to a
 * page that cannot be addressed.
 */
interface Walk {
  /** The cursor of the page this walk describes. `null` is page one. */
  readonly cursor: string | null;
  /** The cursors of the pages before it, oldest first. Its length is the page ordinal. */
  readonly stack: readonly (string | null)[];
  /** False once a page was reached by a route this walk did not take — a pasted link. */
  readonly isOrdinalKnown: boolean;
}

const FIRST_PAGE_WALK: Walk = { cursor: null, stack: [], isOrdinalKnown: true };

/* -------------------------------------------------------------------------- */
/* The verification rate                                                       */
/* -------------------------------------------------------------------------- */

/**
 * `verified` of `checked`, in whole percentage points — formed HERE from the two integers.
 *
 * The response also carries `verificationRate`, an IEEE double the server divided out, and it
 * is deliberately not read: printing it prints the server's rounding, and a quotient formatted
 * in two places eventually disagrees with itself. The two integers are on the payload so that
 * the SPA can decide how the rate is spelled, which is the same division of labour the rest of
 * this console keeps — the wire measures, the browser writes the sentence.
 *
 * **Neither end is allowed to round into a lie**, and that is the whole reason this is a
 * function rather than an expression. 999 verified of 1 000 is 99.9%, which `Math.round` makes
 * `100%` — "every name verified", on a window that contains a failure somebody is looking for.
 * One of 1 000 rounds the other way into `0%`, "nothing verified", on a window where something
 * did. So a full sweep prints 100 only when `verified === checked`, and 0 only when nothing was
 * verified at all; every other value is held one point short of the boundary it would otherwise
 * cross. The percentage is decoration over a small sample anyway — the tile beside it carries
 * `checked`, which is the measurement.
 *
 * The caller guarantees `checked > 0`; a zero denominator is not a rate of any kind and is
 * rendered as an absent figure with `noDenominator` beside it, never as `0%`.
 */
function passRateLabel(verified: number, checked: number): string {
  const rounded = Math.round((verified / checked) * 100);
  if (rounded >= 100 && verified < checked) return "99%";
  if (rounded <= 0 && verified > 0) return "1%";
  return `${String(rounded)}%`;
}

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

interface NoteCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly hint: string;
  readonly canRetry: boolean;
}

/**
 * A failed read, as something an operator can act on. The CODE decides, not the status: a 403
 * is three different facts (`FORBIDDEN`, `CSRF_REJECTED`, `ORIGIN_REJECTED`) with three
 * different remedies, and only one of them is about this operator's role.
 *
 * `null` for `REQUEST_ABORTED`, which must render as nothing at all — it is a request this
 * screen cancelled on purpose.
 */
function noteFor(error: AdminQueryError, subject: string, t: Translate): NoteCopy | null {
  const hint = `${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`;

  if (error.code === CLIENT_ERROR_CODES.aborted) return null;

  if (error.code === "UNAUTHENTICATED" || error.code === "CSRF_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.sessionEndedTitle"),
      message: t("generations.notes.sessionEndedMessage"),
      hint,
      canRetry: false,
    };
  }

  if (error.code === "ORIGIN_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.originTitle"),
      message: t("errors.query.originMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 403) {
    return {
      tone: "denied",
      title: t("errors.query.forbiddenTitle", { subject }),
      message: t("generations.notes.forbiddenMessage"),
      hint,
      canRetry: false,
    };
  }

  if (error.code === CLIENT_ERROR_CODES.schemaDrift) {
    const paths = (error.issues ?? []).map((issue) => issue.path).join(", ");
    return {
      tone: "error",
      title: t("errors.query.driftTitle", { subject }),
      message:
        paths === ""
          ? error.message
          : t("errors.query.driftMessage", { message: error.message, paths }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 404) {
    return {
      tone: "error",
      title: t("errors.query.notFoundTitle", { subject }),
      message: t("generations.notes.notFoundMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("errors.query.refusedFiltersTitle", { subject }),
      message: t("users.notes.refusedFiltersMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 0) {
    return {
      tone: "offline",
      title: t("errors.query.offlineTitle", { subject }),
      message: error.message,
      hint,
      canRetry: true,
    };
  }

  return {
    tone: "error",
    title: `${subject} failed to load`,
    message: error.message,
    hint,
    canRetry: true,
  };
}

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

export function GenerationsScreen(): JSX.Element {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => readUrlState(searchParams), [searchParams]);
  const filterCount = activeFilterCount(state);

  /**
   * The walk this tab has actually made. The API mints no previous cursor, so Previous is
   * this component's memory and nothing else.
   *
   * `cursor` records which page the walk describes, so a cursor that arrives from anywhere
   * else — a pasted link, the Back button, a hand-edited URL — is detected rather than
   * assumed to be the next step of this walk. When it does not match, the stack is not this
   * page's history and the ordinal is not this page's ordinal, and both say so.
   */
  const [walk, setWalk] = useState<Walk>(() => ({
    cursor: state.cursor,
    stack: [],
    // A load with no cursor is page one. A load WITH one is a page whose ordinal is carried
    // only by the opaque cursor, which this tab cannot decode and will not guess at.
    isOrdinalKnown: state.cursor === null,
  }));
  const [isPanelOpen, setIsPanelOpen] = useState(() => filterCount > 0);

  const apply = useCallback(
    (next: UrlState, options: { readonly push: boolean }) => {
      setSearchParams(writeUrlState(next), { replace: !options.push });
    },
    [setSearchParams],
  );

  /** Any filter edit: back to page one, and the walked cursors go with the old question. */
  const patchFilters = useCallback(
    (partial: Partial<UrlState>) => {
      setWalk(FIRST_PAGE_WALK);
      apply({ ...state, ...partial, cursor: null }, { push: false });
    },
    [apply, state],
  );

  const clearFilters = useCallback(() => {
    setWalk(FIRST_PAGE_WALK);
    apply({ ...EMPTY_STATE, attempt: state.attempt }, { push: false });
  }, [apply, state.attempt]);

  /**
   * The open panel, and the row it was opened from.
   *
   * Below `xl` the panel is not beside the table — it is appended UNDER fifty rows and the
   * pager, roughly three thousand pixels down. So opening one has to take the operator there
   * and closing one has to bring them back to the row they pressed; otherwise the screen
   * looks inert and the natural response is to press the row again.
   */
  const panelRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const focusedFor = useRef<string | null>(null);

  /** Selection is PUSHED, so Back closes the panel instead of leaving the screen. */
  const selectAttempt = useCallback(
    (attempt: string | null) => {
      apply({ ...state, attempt }, { push: true });
    },
    [apply, state],
  );

  /** Close, and put focus back on the row the panel was opened from — it still exists. */
  const closeAttempt = useCallback(() => {
    const openedFrom = state.attempt;
    selectAttempt(null);
    if (openedFrom === null) return;
    const row = listRef.current?.querySelector<HTMLElement>(
      `[data-row-key="${CSS.escape(openedFrom)}"]`,
    );
    row?.focus();
  }, [selectAttempt, state.attempt]);

  useEffect(() => {
    const attempt = state.attempt;
    if (attempt === null) {
      focusedFor.current = null;
      return;
    }
    // Once per selection, and only where the panel is NOT beside the table: on a wide screen
    // it is already in view and pulling focus out of the list would cost a keyboard operator
    // their place in it.
    if (focusedFor.current === attempt) return;
    focusedFor.current = attempt;
    if (window.matchMedia(TWO_COLUMN_QUERY).matches) return;
    const panel = panelRef.current;
    if (panel === null) return;
    panel.focus();
    panel.scrollIntoView({ block: "start" });
  }, [state.attempt]);

  const filters = useMemo<GenerationsFilters>(
    () => ({
      withTotal: true,
      kind: state.kind,
      provider: state.provider,
      isSuccess: state.isSuccess,
      errorCode: state.errorCode,
      strategy: state.strategy,
      isOrphaned: state.isOrphaned,
      from: state.from,
      to: state.to,
    }),
    [state],
  );

  const page = useMemo<PageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: state.cursor }),
    [state.cursor],
  );

  /**
   * The only two filters `/api/metrics/name-analytics` can be asked for.
   *
   * Narrowed to `from`/`to` at the boundary rather than at the fetcher, so the six filters that
   * route cannot honour are not even in scope where the request is formed — a screen that
   * passed `state` wholesale would look like it was filtering the verification figures and
   * would not be. See the header on what the strip owes the reader in exchange.
   */
  const ledgerWindow = useMemo<LedgerWindow>(
    () => ({ from: state.from, to: state.to }),
    [state.from, state.to],
  );

  const attempts = useGenerations(filters, page);
  const selected = useGeneration(state.attempt);
  const verification = useNameAnalytics(ledgerWindow);

  /* The verification read is on a DIFFERENT permission, but a 401 is a 401 on any of the three:
     the session cookie is gone, and the screen must leave rather than render two thirds of
     itself around the hole. Only `useSessionGuard` branches on that; a 403 from this read is a
     role refusal and stays local to the strip. */
  useSessionGuard([attempts.error, selected.error, verification.error]);

  const items = attempts.data?.items ?? [];
  const meta = attempts.data?.meta ?? null;
  const nextCursor = attempts.data === undefined ? null : nextCursorOf(attempts.data);

  /** Whether `walk` still describes the page on screen. See the `Walk` note above. */
  const isWalkCurrent = walk.cursor === state.cursor;
  const hasPrev = isWalkCurrent && walk.stack.length > 0;
  /** How many pages precede this one, or `null` when this tab did not walk here. */
  const pageOrdinal = isWalkCurrent && walk.isOrdinalKnown ? walk.stack.length : null;

  const goNext = useCallback(() => {
    if (nextCursor === null) return;
    setWalk((previous) =>
      previous.cursor === state.cursor
        ? {
            cursor: nextCursor,
            stack: [...previous.stack, state.cursor],
            isOrdinalKnown: previous.isOrdinalKnown,
          }
        : /* The page we are leaving was not reached through this walk, so its ordinal is
             unknown and so is every ordinal after it. Previous still works — we know the
             cursor we came from — but the range label stops counting. */
          { cursor: nextCursor, stack: [state.cursor], isOrdinalKnown: false },
    );
    apply({ ...state, cursor: nextCursor }, { push: false });
  }, [apply, nextCursor, state]);

  const goPrev = useCallback(() => {
    if (!hasPrev) return;
    const previous = walk.stack[walk.stack.length - 1] ?? null;
    setWalk({
      cursor: previous,
      stack: walk.stack.slice(0, -1),
      isOrdinalKnown: walk.isOrdinalKnown,
    });
    apply({ ...state, cursor: previous }, { push: false });
  }, [apply, hasPrev, state, walk]);

  const zoneLabel = useMemo(() => localZoneLabel(), []);

  /* ---------------------------------------------------------------------- */
  /* Chips                                                                   */
  /* ---------------------------------------------------------------------- */

  const chips = useMemo<readonly FilterChip[]>(() => {
    const out: FilterChip[] = [];

    if (state.kind.length > 0) {
      out.push({
        id: PARAM.kind,
        field: t("generations.chips.kind"),
        value: state.kind
          .map((kind) => t(GENERATION_KIND_KEY[kind]))
          .join(t("users.chips.languageJoin")),
        onRemove: () => {
          patchFilters({ kind: [] });
        },
      });
    }
    if (state.strategy !== null) {
      out.push({
        id: PARAM.strategy,
        field: t("generations.chips.nameStrategy"),
        value: t(NAME_STRATEGY_KEY[state.strategy]),
        onRemove: () => {
          patchFilters({ strategy: null });
        },
      });
    }
    if (state.isSuccess !== null) {
      out.push({
        id: PARAM.isSuccess,
        field: t("generations.chips.outcome"),
        value: state.isSuccess
          ? t("generations.chips.succeeded")
          : t("generations.chips.failed"),
        onRemove: () => {
          patchFilters({ isSuccess: null });
        },
      });
    }
    if (state.isOrphaned !== null) {
      out.push({
        id: PARAM.isOrphaned,
        field: t("generations.chips.hasOrder"),
        /* Stated as the question the parameter asks, not as the raw flag. */
        value: state.isOrphaned ? "no — orphaned" : "yes",
        onRemove: () => {
          patchFilters({ isOrphaned: null });
        },
      });
    }
    if (state.provider !== null) {
      out.push({
        id: PARAM.provider,
        field: t("generations.chips.provider"),
        value: state.provider,
        onRemove: () => {
          patchFilters({ provider: null });
        },
      });
    }
    if (state.errorCode !== null) {
      out.push({
        id: PARAM.errorCode,
        field: t("generations.chips.errorCode"),
        value: state.errorCode,
        onRemove: () => {
          patchFilters({ errorCode: null });
        },
      });
    }
    if (state.from !== null) {
      out.push({
        id: PARAM.from,
        field: t("generations.chips.createdFrom"),
        value: `${splitTimestamp(state.from).full} ${zoneLabel}`,
        onRemove: () => {
          patchFilters({ from: null });
        },
      });
    }
    if (state.to !== null) {
      out.push({
        id: PARAM.to,
        field: t("generations.chips.createdBefore"),
        value: `${splitTimestamp(state.to).full} ${zoneLabel}`,
        onRemove: () => {
          patchFilters({ to: null });
        },
      });
    }
    return out;
  }, [patchFilters, state, t, zoneLabel]);

  /* ---------------------------------------------------------------------- */
  /* Columns                                                                 */
  /* ---------------------------------------------------------------------- */

  const columns = useMemo<readonly Column<AttemptWireView>[]>(
    () => [
      {
        key: "created",
        header: t("generations.table.created", { zone: zoneLabel }),
        width: "9.5rem",
        render: (row) => {
          const at = splitTimestamp(row.createdAt);
          return (
            <div className="flex flex-col">
              <span>{at.date}</span>
              <span className={CELL_SECONDARY_CLASS}>{at.time}</span>
            </div>
          );
        },
      },
      {
        key: "kind",
        header: t("generations.table.kind"),
        width: "9rem",
        render: (row) => t(GENERATION_KIND_KEY[row.kind]),
      },
      {
        key: "provider",
        header: t("generations.table.provider"),
        width: "10rem",
        render: (row) => (
          <span className="font-mono text-[12px] leading-4">
            {row.provider ??
              (row.kind === "name_verification" ? t("generations.noVendorCall") : EMPTY_VALUE)}
          </span>
        ),
      },
      {
        key: "sequence",
        header: t("generations.table.sequence"),
        width: "6rem",
        render: (row) => (
          <div className="flex flex-col">
            <span>{`seq ${String(row.sequence)}`}</span>
            <span className={CELL_SECONDARY_CLASS}>{`attempt ${String(row.attempt)}`}</span>
          </div>
        ),
      },
      {
        key: "outcome",
        header: t("generations.table.outcome"),
        width: "15rem",
        render: (row) => (
          <div className="flex flex-wrap items-center gap-1">
            {row.isSuccess ? (
              <Badge tone="accent">{t("generations.outcomes.succeeded")}</Badge>
            ) : (
              /* The code IS the outcome for a failure; "failed" alone sends the operator to
                 the panel to learn the one thing the row already knows. */
              <Badge tone="danger" title={row.errorMessage ?? undefined}>
                {row.errorCode ?? t("generations.outcomes.failed")}
              </Badge>
            )}
            {row.isOrphaned ? (
              <Badge tone="muted" title={t("generations.orphanedExplanation")}>
                {t("generations.orphanedLabel")}
              </Badge>
            ) : null}
          </div>
        ),
      },
      {
        key: "language",
        header: t("generations.table.language"),
        width: "9rem",
        render: (row) =>
          row.language === null ? (
            <span className={CELL_SECONDARY_CLASS}>{EMPTY_VALUE}</span>
          ) : (
            t(LANGUAGE_LABEL_KEY[row.language])
          ),
      },
      {
        key: "latency",
        header: t("generations.table.latency"),
        width: "7rem",
        align: "right",
        render: (row) => (
          <span className={row.isInstrumented ? undefined : CELL_SECONDARY_CLASS}>
            {formatLatencyMs(row.latencyMs, row.isInstrumented)}
          </span>
        ),
      },
      {
        key: "cost",
        header: t("generations.table.cost"),
        width: "8rem",
        align: "right",
        render: (row) => (
          <div className="flex flex-col items-end">
            <span className={row.isInstrumented ? undefined : CELL_SECONDARY_CLASS}>
              {formatCostUsd(row.costUsd, row.isInstrumented)}
            </span>
            {/* `costSource` is only meaningful beside a cost that was actually written. */}
            {row.isInstrumented && row.costSource !== null ? (
              <span className={CELL_SECONDARY_CLASS}>{row.costSource}</span>
            ) : null}
          </div>
        ),
      },
    ],
    [t, zoneLabel],
  );

  /* ---------------------------------------------------------------------- */
  /* Counts and the range label                                              */
  /* ---------------------------------------------------------------------- */

  const totalLabel = useMemo(() => {
    if (meta === null || meta.total === null) return null;
    /* `bounded_total` stops at the cap: 10 000 with `isTotalExact: false` is a floor, not a
       count, and printing it bare would be a ceiling wearing a measurement's clothes. */
    return meta.isTotalExact === false && meta.total >= TOTAL_COUNT_CAP
      ? `${formatCount(meta.total)}+`
      : formatCount(meta.total);
  }, [meta]);

  /**
   * The three tiles, and the Toolbar subtitle they replaced.
   *
   * **The subtitle is gone rather than kept beside them.** It printed exactly this count in
   * exactly this position — "1 234 attempts match these filters", two centimetres above a tile
   * reading `Attempts 1 234` — and two spellings of one number is how they eventually differ:
   * the first reader to see them disagree has no way to know which is the ledger's. What the
   * sentence said and the tile does not is whether the count is filtered, and that fact did not
   * need a sentence: the chips row and the `Filters · N` badge sit between the strip and the
   * table, they name every filter that is set, and unlike the subtitle they can be pressed to
   * change it. The pager's range label keeps its own `of {total}` — that is a position within
   * the count and not a second statement of it.
   *
   * **`value: null` is never a zero here.** Each of the four ways a figure can be missing is a
   * different sentence: the count was not requested, the read has not answered (or was
   * refused), verification has never run on this deployment, and nothing in this window reached
   * a verdict. The first three print an absent figure; the last prints a measured `0` for
   * `checked`, because "nothing was checked in the range you chose" is a fact somebody measured
   * — and an absent rate beside it, because a quotient over no denominator is not a number.
   *
   * No tile is toned `warn`. That tone is for a count an operator must act on, and there is no
   * published figure on this deployment for what a healthy pass rate is; a threshold invented
   * here would paint a colour on an opinion and be read as a measurement.
   */
  const stats = useMemo<readonly PageStat[]>(() => {
    const attemptsTile: PageStat = {
      key: "attempts",
      label: t("generations.stats.attempts"),
      value: totalLabel,
      /* `withTotal` is always sent, so a null total is the server declining to bound one —
         which is its own sentence and not an outage, and the screen already owns the phrase. */
      ...(totalLabel === null ? { reason: t("generations.countNotRequested") } : {}),
    };

    const names = verification.data;
    if (names === undefined) {
      /* In flight, or refused. Two dashes and no caption invented from nothing: the note
         under the strip carries the reason, with the correlation id a refusal is chased by. */
      return [
        attemptsTile,
        { key: "passRate", label: t("generations.stats.passRate"), value: null },
        { key: "checked", label: t("generations.stats.checked"), value: null },
      ];
    }

    if (!names.hasRecordedAttempts) {
      /* `hasRecordedAttempts` is measured with the window IGNORED, so this is the one state in
         which `attempts: 0` means "the verifier has never run here" rather than "not in this
         range". Printing `0 checked` would answer the second question — widen the window —
         about a deployment where widening it cannot help. */
      const notInstrumented = t("common.stats.unavailable.notInstrumented");
      return [
        attemptsTile,
        {
          key: "passRate",
          label: t("generations.stats.passRate"),
          value: null,
          reason: notInstrumented,
        },
        {
          key: "checked",
          label: t("generations.stats.checked"),
          value: null,
          reason: notInstrumented,
        },
      ];
    }

    return [
      attemptsTile,
      {
        key: "passRate",
        label: t("generations.stats.passRate"),
        value: names.attempts === 0 ? null : passRateLabel(names.verified, names.attempts),
        /* The percent sign rides in `value` rather than in `unit`: `unit` is set in a smaller
           weight a gap away from the number, which is right for `soʻm` and wrong for a
           percentage — `97 %` is not how this is written in any of the three locales. */
        ...(names.attempts === 0
          ? { reason: t("common.stats.unavailable.noDenominator") }
          : {}),
      },
      {
        key: "checked",
        label: t("generations.stats.checked"),
        /* Measured, including at zero — the ledger holds verdicts and this window has none. */
        value: formatCount(names.attempts),
      },
    ];
  }, [t, totalLabel, verification.data]);

  const rangeLabel = useMemo(() => {
    if (attempts.isPlaceholderData) {
      /* The rows on screen belong to the PREVIOUS request and the walk has already moved on,
         so any range composed now would number one page's rows with another's positions. */
      return t("generations.range.loadingNext");
    }
    if (attempts.data === undefined) {
      return attempts.error === null
        ? t("generations.range.loading")
        : t("generations.range.noneLoaded");
    }
    if (items.length === 0) return t("generations.range.noneOnPage");
    const suffix =
      totalLabel === null ? "" : t("generations.range.ofTotal", { total: totalLabel });
    if (pageOrdinal === null) {
      /* This tab did not walk here, so it does not know this page's ordinal — and a number
         guessed from a cursor it cannot decode would be an invention. */
      return t("generations.range.onThisPage", {
        count: formatCount(items.length),
        total: suffix,
      });
    }
    const start = pageOrdinal * DEFAULT_PAGE_LIMIT + 1;
    return t("generations.range.numbered", {
      start: formatCount(start),
      end: formatCount(start + items.length - 1),
      total: suffix,
    });
  }, [
    attempts.data,
    attempts.error,
    attempts.isPlaceholderData,
    items.length,
    pageOrdinal,
    t,
    totalLabel,
  ]);

  const listNote =
    attempts.error === null ? null : noteFor(attempts.error, t("generations.subjects.ledger"), t);
  const detailNote =
    selected.error === null ? null : noteFor(selected.error, t("generations.subjects.attempt"), t);
  /**
   * Why the two verification tiles are blank, when they are.
   *
   * The tiles themselves print a bare dash in this state and no caption, because the reason is
   * not one of the six the absence vocabulary covers — those name what the DATA could not say,
   * and this is the read never having happened. `noteFor` is the copy that does say it, and it
   * carries the endpoint and the correlation id, which is the difference between an operator
   * filing a useful report and re-pressing a button.
   *
   * The subject is `name verification` — the attempt KIND, which is exactly the population
   * these two tiles measure, and already translated in all three locales. A 403 here reads
   * "name verification is not visible to this role", which is the true sentence: the route is
   * `DASHBOARD_READ` and the rows under it are `RECORDS_READ`, so the table below keeps every
   * one of its rows while the aggregate over them is refused.
   */
  const statsNote =
    verification.error === null
      ? null
      : noteFor(verification.error, t("generations.kinds.name_verification"), t);

  return (
    <main className="py-6">
      {/* The 1392px content box the shell's screens are composed against. The page ground and
          the min-height belong to `AppShell`; a second one here would paint over the rail's. */}
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("generations.title")}
          /* No subtitle. It printed the same count the Attempts tile does — see `stats`. */
          actions={
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
          }
        />

        {/* Above the filter panel, not below it: the strip is what the page ANSWERS and the
            panel is what narrows it, and an answer that moves down the screen as a disclosure
            opens is one the operator has to go looking for again. `isLoading` is the union of
            the two reads on purpose — one strip, one busy state, filled in one go rather than
            in two stages that shuffle the tiles under whoever is reading them. */}
        <PageStats stats={stats} isLoading={attempts.isLoading || verification.isLoading} />

        {statsNote === null ? null : (
          <ErrorNote
            tone={statsNote.tone}
            title={statsNote.title}
            message={statsNote.message}
            hint={statsNote.hint}
            retryable={statsNote.canRetry}
            isRetrying={verification.isFetching}
            onRetry={() => {
              void verification.refetch();
            }}
          />
        )}

        {isPanelOpen ? (
          <FilterPanel id={FILTER_PANEL_ID}>
            <TimeRangeFilter
              from={state.from}
              to={state.to}
              fromInput={isoToLocalInput(state.from)}
              toInput={isoToLocalInput(state.to)}
              toIso={localInputToIso}
              zoneLabel={zoneLabel}
              onChange={(next) => {
                patchFilters(next);
              }}
            />
            <EnumToggleGroup<GenerationKind>
              label={t("generations.chips.kind")}
              values={GENERATION_KIND_VALUES}
              selected={state.kind}
              format={(kind) => t(GENERATION_KIND_KEY[kind])}
              onChange={(kind) => {
                patchFilters({ kind });
              }}
            />
            <SingleEnumSelect<NameStrategy>
              label={t("generations.chips.nameStrategy")}
              values={NAME_STRATEGY_VALUES}
              value={state.strategy}
              format={(strategy) => t(NAME_STRATEGY_KEY[strategy])}
              hint={t("generations.hints.nameStrategy")}
              onChange={(strategy) => {
                patchFilters({ strategy });
              }}
            />
            <TriStateSelect
              label={t("generations.chips.outcome")}
              value={state.isSuccess}
              trueLabel={t("generations.chips.succeeded")}
              falseLabel={t("generations.chips.failed")}
              onChange={(isSuccess) => {
                patchFilters({ isSuccess });
              }}
            />
            <TriStateSelect
              label={t("generations.chips.hasOrder")}
              value={state.isOrphaned === null ? null : !state.isOrphaned}
              trueLabel="yes"
              falseLabel={t("generations.chips.orphanedNo")}
              hint={t("generations.orphanedExplanation")}
              onChange={(hasOrder) => {
                /* The wire asks the negative; the operator is offered the positive. */
                patchFilters({ isOrphaned: hasOrder === null ? null : !hasOrder });
              }}
            />
            <TextFilter
              label={t("generations.chips.provider")}
              value={state.provider}
              maxLength={MAX_PROVIDER_CHARS}
              placeholder="elevenlabs_music"
              suggestions={PROVIDER_VALUES}
              hint={t("generations.hints.provider")}
              onChange={(provider) => {
                patchFilters({ provider });
              }}
            />
            <TextFilter
              label={t("generations.chips.errorCode")}
              value={state.errorCode}
              maxLength={MAX_ERROR_CODE_CHARS}
              placeholder="UPSTREAM_TIMEOUT"
              hint={t("generations.hints.errorCode")}
              onChange={(errorCode) => {
                patchFilters({ errorCode });
              }}
            />
          </FilterPanel>
        ) : null}

        <FilterChips chips={chips} onClearAll={filterCount === 0 ? undefined : clearFilters} />

        {listNote === null ? null : (
          <ErrorNote
            tone={listNote.tone}
            title={listNote.title}
            message={listNote.message}
            hint={listNote.hint}
            retryable={listNote.canRetry}
            isRetrying={attempts.isFetching}
            onRetry={() => {
              void attempts.refetch();
            }}
          />
        )}

        <div
          className={cn(
            "grid min-w-0 grid-cols-1 gap-4",
            state.attempt !== null && "xl:grid-cols-[minmax(0,1fr)_26rem]",
          )}
        >
          <section aria-label="Generation attempts" className="flex min-w-0 flex-col gap-3">
            <div
              ref={listRef}
              /* A page that is still loading under NEW filters is the PREVIOUS answer;
                 dimming it says so rather than presenting it under the new chips. */
              className={cn(
                "transition-opacity",
                attempts.isPlaceholderData && "opacity-60",
              )}
            >
              <DataTable
                caption={t("generations.tableCaption")}
                columns={columns}
                rows={items}
                getRowKey={(row) => row.id}
                isLoading={attempts.isLoading}
                skeletonRows={DEFAULT_PAGE_LIMIT}
                isRowActive={(row) => row.id === state.attempt}
                onRowClick={(row) => {
                  selectAttempt(row.id);
                }}
                emptyMessage={
                  attempts.error !== null ? (
                    <EmptyState
                      title={t("generations.empty.failedTitle")}
                      message={t("generations.empty.failedMessage")}
                    />
                  ) : filterCount > 0 ? (
                    <EmptyState
                      title={t("generations.empty.noMatchTitle")}
                      message={t("generations.empty.noMatchMessage")}
                      action={
                        <ToolbarButton onClick={clearFilters}>{t("common.clearAllFilters")}</ToolbarButton>
                      }
                    />
                  ) : (
                    <EmptyState
                      title={t("generations.empty.ledgerEmptyTitle")}
                      message={t("generations.empty.ledgerEmptyMessage")}
                    />
                  )
                }
              />
            </div>

            <CursorPager
              rangeLabel={rangeLabel}
              hasPrev={hasPrev}
              hasNext={nextCursor !== null}
              isFetching={attempts.isFetching}
              onPrev={goPrev}
              onNext={goNext}
            />
          </section>

          {state.attempt === null ? null : (
            <div ref={panelRef} tabIndex={-1} className="min-w-0 outline-none">
              {selected.isLoading ? (
                <Skeleton className="h-[32rem] w-full rounded-card" />
              ) : detailNote !== null ? (
                <ErrorNote
                  tone={detailNote.tone}
                  title={detailNote.title}
                  message={detailNote.message}
                  hint={detailNote.hint}
                  retryable={detailNote.canRetry}
                  isRetrying={selected.isFetching}
                  onRetry={() => {
                    void selected.refetch();
                  }}
                />
              ) : selected.data === undefined ? null : (
                <AttemptDetailPanel
                  /* Keyed on the attempt, so a cached one swapped in REMOUNTS the panel. Its
                     cells hold revealed plaintext in their own state, and state that outlived
                     the subject it was bought for would draw one attempt's transcript under
                     another's — with the audit row naming the first. */
                  key={selected.data.id}
                  attempt={selected.data}
                  onClose={closeAttempt}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
