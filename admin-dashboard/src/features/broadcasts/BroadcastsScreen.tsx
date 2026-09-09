/**
 * `/broadcasts` — the campaigns this console has composed.
 *
 * ## One row per CAMPAIGN
 *
 * Not one per recipient, and the difference is forty thousand rows. `GET /api/broadcasts` pages
 * campaigns; the ledger of who received what lives under one campaign, on its detail screen,
 * and is reachable only from there. A list that mixed the two would put a customer's row on a
 * screen whose filters are about campaigns, and would make "12 results" mean two different
 * things on one page.
 *
 * ## The counters move while nobody touches this screen
 *
 * This is the only list in the panel whose rows change on their own: a worker is delivering
 * messages and the funnel climbs under the reader. `useBroadcasts` polls for exactly as long as
 * a campaign on the page is expanding, ready, sending or paused, and stops the moment none is —
 * the interval is a function of the data rather than a flag this screen sets, so a table of
 * completed campaigns costs nothing and nobody has to remember to turn a timer off.
 *
 * ## What the delivery column may claim
 *
 * `settledCount` over `recipientCount`, and never a percentage of the AUDIENCE: the audience was
 * frozen at composition and the recipient rows are written afterwards, so a campaign mid-
 * expansion has fewer rows than accounts and a bar drawn against the audience would sit at 30%
 * while the send was in fact complete. `unknownCount` is never folded into `failedCount` here or
 * anywhere else — a killed job left those rows claimed and the message may well have arrived.
 *
 * ## The filters are the two closed vocabularies, and nothing else
 *
 * State and kind, both repeated parameters the server reads as OR. There is deliberately no
 * search box: `?q=` matches the campaign TITLE only — the bodies are not searchable — and a box
 * that looked like the directory's would invite an operator to look for a customer in it.
 */

import { Megaphone } from "lucide-react";
import { useCallback, useMemo, useState, type JSX } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  BROADCAST_KIND_VALUES,
  BROADCAST_STATE_VALUES,
  type BroadcastKind,
  type BroadcastState,
  type BroadcastView,
  type BroadcastsFilters,
} from "@/api/broadcasts";
import { CLIENT_ERROR_CODES } from "@/api/client";
import { DEFAULT_PAGE_LIMIT, nextCursorOf, type PageRequest } from "@/api/pagination";
import { broadcastDetailPath, broadcastNewPath } from "@/app/paths";
import { Badge } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import {
  BROADCAST_KIND_HINT_KEY,
  BROADCAST_KIND_LABEL_KEY,
  BROADCAST_STATE_HINT_KEY,
  BROADCAST_STATE_LABEL_KEY,
  BROADCAST_STATE_TONE,
  formatAbsolute,
  formatCount,
  formatRelative,
  formatTotal,
  noteFor,
  type Translate,
} from "@/features/broadcasts/broadcastFormat";
import { useBroadcasts } from "@/features/broadcasts/useBroadcasts";
import { EnumToggleGroup } from "@/features/users/filterControls";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useCanWriteBroadcasts } from "@/lib/rbac";
import { useSessionGuard } from "@/state/useSessionGuard";

/* -------------------------------------------------------------------------- */
/* URL state                                                                   */
/* -------------------------------------------------------------------------- */

interface BroadcastsUrlState {
  readonly state: readonly BroadcastState[];
  readonly kind: readonly BroadcastKind[];
  readonly cursor: string | null;
}

function readText(params: URLSearchParams, name: string): string | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * A repeated parameter, read back as the members this build knows.
 *
 * An unknown member is DROPPED rather than sent on: the server would answer 422 naming the
 * parameter, which empties the table and blames a filter the operator cannot see. Dropping it
 * narrows nothing they asked for, and the chip row still shows what survived.
 */
function readMembers<T extends string>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
): readonly T[] {
  const seen: T[] = [];
  for (const raw of params.getAll(name)) {
    const member = allowed.find((value) => value === raw.trim());
    if (member !== undefined && !seen.includes(member)) seen.push(member);
  }
  return seen;
}

function parseUrlState(params: URLSearchParams): BroadcastsUrlState {
  return {
    state: readMembers(params, "state", BROADCAST_STATE_VALUES),
    kind: readMembers(params, "kind", BROADCAST_KIND_VALUES),
    cursor: readText(params, "cursor"),
  };
}

function writeUrlState(state: BroadcastsUrlState): URLSearchParams {
  const params = new URLSearchParams();
  for (const member of state.state) params.append("state", member);
  for (const member of state.kind) params.append("kind", member);
  if (state.cursor !== null) params.set("cursor", state.cursor);
  return params;
}

/** The cursor is a position, not a filter. Each vocabulary counts once, however many members. */
function activeFilterCount(state: BroadcastsUrlState): number {
  return (state.state.length === 0 ? 0 : 1) + (state.kind.length === 0 ? 0 : 1);
}

/* -------------------------------------------------------------------------- */
/* The walk                                                                    */
/* -------------------------------------------------------------------------- */

/** One stop on the keyset walk: the cursor that fetched it, and how many rows preceded it. */
interface PageStop {
  readonly cursor: string | null;
  /** `null` once the walk was joined mid-way — a pasted link knows no offset, and neither do we. */
  readonly offset: number | null;
}

interface Walk extends PageStop {
  readonly trail: readonly PageStop[];
}

const FIRST_STOP: Walk = { cursor: null, offset: 0, trail: [] };

/* -------------------------------------------------------------------------- */
/* Delivery                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * How far this campaign has got, as a sentence with a bar under it.
 *
 * The SENTENCE carries the meaning and the bar is `aria-hidden` decoration beside it: a
 * progress element announced as "34 percent" tells a screen-reader user a proportion of
 * something it cannot name, and the proportion here needs naming — it is settled rows over
 * rows WRITTEN, not over the frozen audience.
 */
function DeliveryCell({
  broadcast,
  t,
}: {
  readonly broadcast: BroadcastView;
  readonly t: Translate;
}): JSX.Element {
  const { settledCount, recipientCount } = broadcast.progress;
  if (recipientCount === 0) {
    return <span className={CELL_SECONDARY_CLASS}>{t("broadcasts.progress.notStarted")}</span>;
  }
  const share = Math.min(1, Math.max(0, settledCount / recipientCount));
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <span className="whitespace-nowrap">
        {t("broadcasts.progress.settledOf", {
          settled: formatCount(settledCount),
          total: formatCount(recipientCount),
        })}
      </span>
      <span aria-hidden className="block h-1 w-full overflow-hidden rounded bg-bg">
        <span
          className="block h-full rounded bg-accent"
          style={{ width: `${String(Math.round(share * 100))}%` }}
        />
      </span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

export function BroadcastsScreen(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [walk, setWalk] = useState<Walk>(FIRST_STOP);
  const canWrite = useCanWriteBroadcasts();

  const url = useMemo(() => parseUrlState(searchParams), [searchParams]);
  const filterCount = activeFilterCount(url);

  /** A filter change starts the walk again: a cursor is a position in ONE filtered set. */
  const patch = useCallback(
    (change: Partial<Omit<BroadcastsUrlState, "cursor">>) => {
      setWalk(FIRST_STOP);
      setSearchParams(writeUrlState({ ...url, ...change, cursor: null }), { replace: true });
    },
    [setSearchParams, url],
  );

  const goToStop = useCallback(
    (stop: Walk) => {
      setWalk(stop);
      setSearchParams(writeUrlState({ ...url, cursor: stop.cursor }), { replace: true });
    },
    [setSearchParams, url],
  );

  const clearAll = useCallback(() => {
    setWalk(FIRST_STOP);
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  const filters = useMemo<BroadcastsFilters>(
    () => ({
      // Asked for deliberately: the toolbar states a count, and a count nobody asked for is a
      // count that must not be invented. It is bounded and says so.
      withTotal: true,
      state: url.state,
      kind: url.kind,
    }),
    [url.kind, url.state],
  );

  const page = useMemo<PageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: url.cursor }),
    [url.cursor],
  );

  const campaigns = useBroadcasts(filters, page);
  /* An abort is a superseded request — a filter change, an unmount — and renders as nothing. */
  const failure =
    campaigns.error !== null && campaigns.error.code !== CLIENT_ERROR_CODES.aborted
      ? campaigns.error
      : null;
  useSessionGuard([failure]);

  const items = campaigns.data?.items ?? [];
  const meta = campaigns.data?.meta ?? null;

  const isWalkCurrent = walk.cursor === url.cursor;
  const offset = isWalkCurrent ? walk.offset : null;
  const trail = isWalkCurrent ? walk.trail : [];
  const previousStop = trail.length === 0 ? undefined : trail[trail.length - 1];
  const nextCursor = campaigns.data === undefined ? null : nextCursorOf(campaigns.data);

  const chips = useMemo<readonly FilterChip[]>(() => {
    const list: FilterChip[] = [];
    if (url.state.length > 0) {
      list.push({
        id: "state",
        field: t("broadcasts.chips.state"),
        // Words, never the wire spelling: `skipped_blocked` in a chip is a database column.
        value: url.state
          .map((member) => t(BROADCAST_STATE_LABEL_KEY[member]))
          .join(t("broadcasts.chips.join")),
        onRemove: () => {
          patch({ state: [] });
        },
      });
    }
    if (url.kind.length > 0) {
      list.push({
        id: "kind",
        field: t("broadcasts.chips.kind"),
        value: url.kind
          .map((member) => t(BROADCAST_KIND_LABEL_KEY[member]))
          .join(t("broadcasts.chips.join")),
        onRemove: () => {
          patch({ kind: [] });
        },
      });
    }
    return list;
  }, [patch, t, url.kind, url.state]);

  const columns = useMemo<readonly Column<BroadcastView>[]>(
    () => [
      {
        key: "title",
        header: t("broadcasts.table.title"),
        width: "22rem",
        render: (row) => (
          <span className="flex min-w-0 flex-col">
            <span className="truncate">{row.title}</span>
            {row.scheduledFor === null ? null : (
              <span
                className={cn(CELL_SECONDARY_CLASS, "truncate")}
                title={formatAbsolute(row.scheduledFor)}
              >
                {t("broadcasts.table.scheduledFor", {
                  at: formatRelative(row.scheduledFor, t) ?? row.scheduledFor,
                })}
              </span>
            )}
          </span>
        ),
      },
      {
        key: "kind",
        header: t("broadcasts.table.kind"),
        width: "8rem",
        render: (row) => (
          <Badge tone="muted" title={t(BROADCAST_KIND_HINT_KEY[row.kind])}>
            {t(BROADCAST_KIND_LABEL_KEY[row.kind])}
          </Badge>
        ),
      },
      {
        key: "state",
        header: t("broadcasts.table.state"),
        width: "11rem",
        render: (row) => (
          <Badge
            tone={BROADCAST_STATE_TONE[row.state]}
            title={t(BROADCAST_STATE_HINT_KEY[row.state])}
          >
            {t(BROADCAST_STATE_LABEL_KEY[row.state])}
          </Badge>
        ),
      },
      {
        key: "audience",
        header: t("broadcasts.table.audience"),
        width: "10rem",
        align: "right",
        render: (row) => (
          <span className="flex min-w-0 flex-col items-end">
            <span
              className="whitespace-nowrap"
              title={t("broadcasts.audience.frozenAt", {
                at: formatAbsolute(row.audienceEvaluatedAt),
              })}
            >
              {formatCount(row.progress.audienceSize)}
            </span>
            {row.progress.isAudienceComplete ? null : (
              /* The two numbers differ only while the ledger is being written, and hiding the
                 gap behind the frozen size would show a full audience for a half-built one. */
              <span className={cn(CELL_SECONDARY_CLASS, "whitespace-nowrap")}>
                {t("broadcasts.audience.written", {
                  written: formatCount(row.progress.recipientCount),
                  size: formatCount(row.progress.audienceSize),
                })}
              </span>
            )}
          </span>
        ),
      },
      {
        key: "progress",
        header: t("broadcasts.table.progress"),
        width: "12rem",
        render: (row) => <DeliveryCell broadcast={row} t={t} />,
      },
      {
        key: "createdBy",
        header: t("broadcasts.table.createdBy"),
        width: "10rem",
        render: (row) =>
          row.createdByUsername === null ? (
            /* Staff, so never masked — but the row outlives the account, and an empty cell
               would read as "composed by nobody". */
            <span className={CELL_SECONDARY_CLASS}>{t("broadcasts.table.noCreator")}</span>
          ) : (
            <span className="truncate">{row.createdByUsername}</span>
          ),
      },
      {
        key: "createdAt",
        header: t("broadcasts.table.created"),
        width: "10rem",
        render: (row) => (
          <span
            className={cn(CELL_SECONDARY_CLASS, "whitespace-nowrap")}
            title={formatAbsolute(row.createdAt)}
          >
            {formatRelative(row.createdAt, t) ?? row.createdAt}
          </span>
        ),
      },
    ],
    [t],
  );

  /* ---------------------------------------------------------------------- */
  /* What the toolbar and the pager are allowed to claim                     */
  /* ---------------------------------------------------------------------- */

  const total = meta?.total ?? null;
  const isTotalExact = meta?.isTotalExact ?? null;

  let subtitle: string;
  if (campaigns.data === undefined) {
    subtitle =
      failure === null ? t("broadcasts.subtitles.reading") : t("broadcasts.subtitles.failed");
  } else if (total === null) {
    subtitle = t("broadcasts.subtitles.onThisPage", { count: formatCount(items.length) });
  } else {
    const shown = formatTotal(total, isTotalExact, t);
    subtitle =
      filterCount === 0
        ? t("broadcasts.subtitles.campaigns", { total: shown })
        : t("broadcasts.subtitles.campaignsFiltered", { total: shown });
  }

  let rangeLabel: string;
  if (campaigns.isPlaceholderData) {
    // The rows on screen belong to the PREVIOUS request and the walk has already moved on.
    rangeLabel = t("broadcasts.range.loadingNext");
  } else if (campaigns.data === undefined) {
    rangeLabel = failure === null ? t("broadcasts.range.loading") : t("broadcasts.range.noneLoaded");
  } else if (items.length === 0) {
    rangeLabel = filterCount === 0 ? t("broadcasts.range.none") : t("broadcasts.range.noneMatching");
  } else {
    const totalClause =
      total === null
        ? ""
        : t("broadcasts.range.ofTotal", { total: formatTotal(total, isTotalExact, t) });
    rangeLabel =
      offset === null
        ? t("broadcasts.range.onThisPage", {
            count: formatCount(items.length),
            total: totalClause,
          })
        : t("broadcasts.range.numbered", {
            start: formatCount(offset + 1),
            end: formatCount(offset + items.length),
            total: totalClause,
          });
  }

  const emptyMessage = (
    <EmptyState
      title={filterCount === 0 ? t("broadcasts.empty.title") : t("broadcasts.empty.filteredTitle")}
      message={
        filterCount === 0 ? t("broadcasts.empty.message") : t("broadcasts.empty.filteredMessage")
      }
      {...(filterCount === 0
        ? {}
        : {
            action: (
              <ToolbarButton onClick={clearAll} variant="secondary">
                {t("common.clearAllFilters")}
              </ToolbarButton>
            ),
          })}
    />
  );

  const note = failure === null ? null : noteFor(failure, campaigns.data !== undefined, t, t("broadcasts.subject"));

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("broadcasts.title")}
          subtitle={subtitle}
          actions={
            <>
              <ToolbarButton
                variant="secondary"
                ariaExpanded={isPanelOpen}
                ariaControls="broadcasts-filter-panel"
                onClick={() => {
                  setIsPanelOpen((open) => !open);
                }}
              >
                {filterCount === 0
                  ? t("common.filters")
                  : t("common.filtersCount", { count: filterCount })}
              </ToolbarButton>
              {canWrite ? (
                <ToolbarButton
                  /* The kit's PRIMARY action, and here it earns it: the only control on this
                     screen that starts something rather than narrowing it. Hidden — not
                     disabled — for a role without `broadcast.write`, because a press would be
                     a 403 and a `permission.denied` row against somebody who did nothing. */
                  variant="primary"
                  icon={<Megaphone className="h-5 w-5" aria-hidden />}
                  ariaLabel={t("broadcasts.newCampaignAria")}
                  onClick={() => {
                    navigate(broadcastNewPath(null));
                  }}
                >
                  {t("broadcasts.newCampaign")}
                </ToolbarButton>
              ) : null}
            </>
          }
        />

        <div
          id="broadcasts-filter-panel"
          role="group"
          aria-label={t("broadcasts.filtersAria")}
          hidden={!isPanelOpen}
          className="rounded-card border border-stroke bg-card px-4 py-4"
        >
          <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
            <EnumToggleGroup<BroadcastState>
              label={t("broadcasts.filter.state")}
              values={BROADCAST_STATE_VALUES}
              selected={url.state}
              onChange={(next) => {
                patch({ state: next });
              }}
              format={(member) => t(BROADCAST_STATE_LABEL_KEY[member])}
              hint={t("broadcasts.filter.stateHint")}
            />
            <EnumToggleGroup<BroadcastKind>
              label={t("broadcasts.filter.kind")}
              values={BROADCAST_KIND_VALUES}
              selected={url.kind}
              onChange={(next) => {
                patch({ kind: next });
              }}
              format={(member) => t(BROADCAST_KIND_LABEL_KEY[member])}
              hint={t("broadcasts.filter.kindHint")}
            />
          </div>
        </div>

        <FilterChips chips={chips} onClearAll={chips.length === 0 ? undefined : clearAll} />

        {note === null || failure === null ? null : (
          <ErrorNote
            tone={note.tone}
            title={note.title}
            message={note.message}
            hint={`${failure.endpoint} · ${failure.correlationId ?? t("errors.query.noCorrelationId")}`}
            onRetry={() => {
              void campaigns.refetch();
            }}
            isRetrying={campaigns.isFetching}
            retryable={note.canRetry}
          />
        )}

        {/* A failed FIRST read has nothing to draw: the note above is the whole answer. */}
        {campaigns.data === undefined && failure !== null ? null : (
          <div
            aria-busy={campaigns.isPlaceholderData}
            className={cn("transition-opacity", campaigns.isPlaceholderData && "opacity-50")}
          >
            <DataTable
              columns={columns}
              rows={items}
              getRowKey={(row) => row.id}
              isLoading={campaigns.isPending}
              skeletonRows={DEFAULT_PAGE_LIMIT}
              caption={t("broadcasts.tableCaption")}
              emptyMessage={emptyMessage}
              onRowClick={(row) => {
                navigate(broadcastDetailPath(row.id));
              }}
            />
          </div>
        )}

        <CursorPager
          hasPrev={previousStop !== undefined}
          hasNext={nextCursor !== null}
          isFetching={campaigns.isFetching}
          rangeLabel={rangeLabel}
          onPrev={
            previousStop === undefined
              ? undefined
              : () => {
                  goToStop({
                    cursor: previousStop.cursor,
                    offset: previousStop.offset,
                    trail: trail.slice(0, -1),
                  });
                }
          }
          onNext={
            nextCursor === null
              ? undefined
              : () => {
                  goToStop({
                    cursor: nextCursor,
                    offset: offset === null ? null : offset + items.length,
                    trail: [...trail, { cursor: url.cursor, offset }],
                  });
                }
          }
        />
      </div>
    </main>
  );
}
