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
 * The strip above the table is on the same clock and on the same verdict: this screen derives
 * `hasBroadcastInFlight` from the list once and hands the boolean to `useBroadcastStats`, because
 * an aggregate of totals cannot tell a busy deployment from a sleeping one. An idle deployment
 * therefore makes no requests at all — not one for the table and not one for the strip.
 *
 * ## Where the count of campaigns is stated, and where it is not
 *
 * ONCE, in the strip. The toolbar used to carry "412 campaigns" under the title, built from
 * `meta.total`, which saturates at the server's count cap and reads "at least 10,000" past it.
 * `GET /api/broadcasts/stats` publishes the same count as the exact sum of its segments, so
 * keeping both would have put two different numbers for one set of campaigns a few hundred pixels
 * apart and left an operator to decide which console to believe. The subtitle was the one that
 * went: the tile says it better, and it says it beside the three figures that give it meaning.
 * `withTotal` went with it — the list no longer needs a bounded count, so it stops paying for the
 * second query, and the pager's "of N" reads the exact figure off the strip.
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
  type BroadcastStateTotalView,
  type BroadcastStatsView,
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
import { PageStats, type PageStat } from "@/components/PageStats";
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
  noteFor,
  type Translate,
} from "@/features/broadcasts/broadcastFormat";
import {
  hasBroadcastInFlight,
  useBroadcastStats,
  useBroadcasts,
} from "@/features/broadcasts/useBroadcasts";
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
/* The strip                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One state's count, LOOKED UP by name and never taken by position.
 *
 * The server publishes every member of a closed vocabulary, including the ones sitting at zero,
 * so a member that is not in the array is not a state with no campaigns — it is a figure this
 * build was not given. `null` says so, and the tile above renders it as absent. Reading the array
 * positionally, or falling back to `0`, would turn a server this bundle does not fully speak into
 * a confident "nothing is sending" on the one tile an operator is meant to act on.
 */
function countOf(
  counts: readonly BroadcastStateTotalView[],
  state: BroadcastState,
): number | null {
  const segment = counts.find((item) => item.state === state);
  return segment === undefined ? null : segment.count;
}

/**
 * A tile, with the one rule this screen must not break: a reason rides along exactly when the
 * value is absent.
 *
 * `PageStats` already refuses to print a reason beside a measured figure, so this is belt and
 * braces — but it is the belt that keeps a stale "no campaign has started yet" from being passed
 * down beside an instant that has since arrived.
 */
function statTile(
  key: string,
  label: string,
  value: string | null,
  reason: string | null,
  tone: "neutral" | "warn" = "neutral",
): PageStat {
  return {
    key,
    label,
    value,
    tone,
    ...(value === null && reason !== null ? { reason } : {}),
  };
}

/**
 * The four figures above the table, each one formatted by the side that knows what it means.
 *
 * `reachedRecipients` and `audienceTotal` arrive as two integers and are divided by nobody: the
 * tile prints "1,240 of 1,500" through the same sentence the delivery column uses, so the two
 * numbers a reader could check against the rows are both on the screen. An `audienceTotal` of zero
 * is not a reach of 0% — it is a quotient with no denominator, which is not a number — and it
 * renders as a dash with `noDenominator` underneath.
 *
 * `lastSendAt` null is a deployment (or a filter set) in which no run has ever started. It is a
 * dash, never the word "never" and never an epoch: both of those are a send nobody made.
 *
 * `failureReason` is the refusal, already translated, when the strip's own fetch failed. It goes
 * on every tile, because it is the answer to why every one of the four is missing, and it reaches
 * nothing else on the screen — the table beside it is a different query and its rows are still
 * good.
 */
function buildStrip(
  stats: BroadcastStatsView | undefined,
  failureReason: string | null,
  t: Translate,
): readonly PageStat[] {
  const counts = stats?.counts;
  const sending = counts === undefined ? null : countOf(counts, "sending");
  const paused = counts === undefined ? null : countOf(counts, "paused");
  /* Sending AND paused, which is narrower than the set that makes this screen poll. The poll also
     watches `ready` and `expanding` because those move on their own; this tile is the count an
     operator is being asked to LOOK at, and a campaign whose ledger is being written is not one of
     them. A pause is: nothing will restart it but a person. */
  const inFlight = sending === null || paused === null ? null : sending + paused;

  let reached: string | null = null;
  let reachedReason = failureReason;
  if (stats !== undefined) {
    reachedReason = stats.audienceTotal === 0 ? t("common.stats.unavailable.noDenominator") : null;
    if (stats.audienceTotal !== 0) {
      reached = t("broadcasts.progress.settledOf", {
        settled: formatCount(stats.reachedRecipients),
        total: formatCount(stats.audienceTotal),
      });
    }
  }

  let lastSend: string | null = null;
  let lastSendReason = failureReason;
  if (stats !== undefined) {
    /* The caption is this namespace's own and not one of `common.stats.unavailable.*`: those six
       mirror the server's `AbsenceReason` vocabulary one for one, and "no run has ever started"
       is derived here from a `lastSendAt` of null rather than sent by anybody. */
    lastSendReason = stats.lastSendAt === null ? t("broadcasts.stats.noSendYet") : null;
    if (stats.lastSendAt !== null) {
      // The relative form, with the exact instant one hover away on the tile's own title — the
      // rule the table's created column follows. An unparseable instant falls back to the raw
      // string rather than to a dash: the server did send us something, and pretending otherwise
      // would report an absence that is not there.
      lastSend = formatRelative(stats.lastSendAt, t) ?? stats.lastSendAt;
    }
  }

  return [
    statTile(
      "campaigns",
      t("broadcasts.stats.campaigns"),
      stats === undefined ? null : formatCount(stats.total),
      failureReason,
    ),
    statTile(
      "inFlight",
      t("broadcasts.stats.inFlight"),
      inFlight === null ? null : formatCount(inFlight),
      failureReason,
      // `warn` only when there is something to act on. A zero here is a measured, honest zero —
      // nothing is sending — and painting it in the caution ink would train an operator to ignore
      // the colour on the day it means something.
      inFlight !== null && inFlight > 0 ? "warn" : "neutral",
    ),
    statTile("recipients", t("broadcasts.stats.recipients"), reached, reachedReason),
    statTile("lastSend", t("broadcasts.stats.lastSend"), lastSend, lastSendReason),
  ];
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
      // No `withTotal`. It bought the toolbar's "412 campaigns" and nothing else, and that count
      // now comes off the strip — exactly, rather than saturated at the server's cap. Asking for
      // it anyway would be a second query per page turn, producing a number this screen would then
      // have to either hide or print beside a different one for the same set of campaigns.
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
  /* The list's verdict, taken once and spent twice: it is what makes the table poll and what is
     handed to the strip, which holds no campaign state of its own to decide with. */
  const isAnyInFlight = hasBroadcastInFlight(campaigns.data);
  const stats = useBroadcastStats(filters, isAnyInFlight);

  /* An abort is a superseded request — a filter change, an unmount — and renders as nothing. */
  const failure =
    campaigns.error !== null && campaigns.error.code !== CLIENT_ERROR_CODES.aborted
      ? campaigns.error
      : null;
  const statsFailure =
    stats.error !== null && stats.error.code !== CLIENT_ERROR_CODES.aborted ? stats.error : null;
  /* Both, because a 401 is a 401 whichever query hits it first and a tab whose session died while
     only the strip was in flight must still be taken to `/login`. The guard reads `status` alone;
     it is not a renderer, and `statsFailure` renders in the strip and nowhere else. */
  useSessionGuard([failure, statsFailure]);

  const items = campaigns.data?.items ?? [];

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

  /* The strip's count, not the list's: exact, and the only one on this screen. `null` while the
     strip has not arrived or was refused, which the pager below already knows how to say nothing
     about. */
  const total = stats.data?.total ?? null;

  /* The subtitle survives only for the states the strip cannot speak for. Once the rows are here
     the title stands alone: the count moved to the tile, and a second line repeating either it or
     the pager's range would be the third statement of one fact on one screen. */
  const subtitle =
    campaigns.data === undefined
      ? failure === null
        ? t("broadcasts.subtitles.reading")
        : t("broadcasts.subtitles.failed")
      : undefined;

  const strip = useMemo<readonly PageStat[]>(
    () =>
      buildStrip(
        stats.data,
        /* The refusal as a sentence an operator can act on — `noteFor`'s title, the same copy the
           table's own note would use. `isStale` is false because this string can only ever reach a
           tile that has NO figure: once `stats.data` is held, every tile explains itself out of
           the data and a failed refetch leaves the last measured numbers standing rather than
           blanking four figures that were true a poll ago. */
        statsFailure === null
          ? null
          : noteFor(statsFailure, false, t, t("broadcasts.subject")).title,
        t,
      ),
    [stats.data, statsFailure, t],
  );

  let rangeLabel: string;
  if (campaigns.isPlaceholderData) {
    // The rows on screen belong to the PREVIOUS request and the walk has already moved on.
    rangeLabel = t("broadcasts.range.loadingNext");
  } else if (campaigns.data === undefined) {
    rangeLabel = failure === null ? t("broadcasts.range.loading") : t("broadcasts.range.noneLoaded");
  } else if (items.length === 0) {
    rangeLabel = filterCount === 0 ? t("broadcasts.range.none") : t("broadcasts.range.noneMatching");
  } else {
    /* The strip's exact sum, so there is no "at least" to qualify. When the strip has not arrived
       or was refused the clause is empty — the pager says where the walk is and declines to
       invent a size for the set it is walking. */
    const totalClause =
      total === null ? "" : t("broadcasts.range.ofTotal", { total: formatCount(total) });
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

        {/* Under the chips and above the table, because the chips are what these four figures are
            scoped BY — the strip answers for the whole filter set, not for the page — and a reader
            who has just narrowed the list needs the totals to move in the same breath as the rows.
            `isPending` and not `isFetching`: a poll refreshing the numbers must not blank them. */}
        <PageStats stats={strip} isLoading={stats.isPending} />

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
