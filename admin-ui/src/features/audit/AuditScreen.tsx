/**
 * `/audit` — §11.2: *"Who did something destructive?"*
 *
 * Three things on this screen are requirements rather than choices.
 *
 * **1. Destructive actions in the last 24 h are counted SEPARATELY.** Not a filter on one
 * number, not a percentage of it: two figures side by side, the destructive one at hero
 * size. A single "413 audit rows today" says nothing — the log is mostly logins — and the
 * question the screen exists to answer is about the fifteen actions in
 * `DESTRUCTIVE_AUDIT_ACTIONS`.
 *
 * **2. Reveals are charted by `record_count`, not by row count.** §11.2 and §12.3: the
 * reveal budget "is counted in records, not requests, and that is the correction the review
 * forced". One reveal that unmasks a name is one record; one conversation reveal is up to 50
 * bodies. A bar chart of row counts would draw those the same height and would be the exact
 * misreading the budget design exists to prevent.
 *
 * **3. Both counts are LOWER BOUNDS when the window overflows.** `/api/audit` has no
 * `total` and takes no `withTotal`, so counting means counting rows, and a page that comes
 * back with a `nextCursor` was truncated. Those figures render with a `+`.
 *
 * Polling: none (§11.5's "everything else"). The audit log is read after something happened,
 * not watched.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";

import {
  AUDIT_ACTION_VALUES,
  AUDIT_OUTCOME_VALUES,
  DESTRUCTIVE_AUDIT_ACTIONS,
  DEFAULT_PAGE_LIMIT,
  REASON_WITHHELD_LABEL,
  getAudit,
  getAuditVerify,
  unwrapAsync,
  type AuditAction,
  type AuditEntryView,
  type AuditOutcome,
  type AuditQuery,
} from "@/api";
import {
  ChartFrame,
  CursorPager,
  DataTable,
  FilterBar,
  StatTile,
  TimeRangePicker,
  Timestamp,
  buildFilterChips,
  type ChartDatum,
  type DataColumn,
  type TimeRange,
} from "@/components/data";
import { CorrelationChip, NameText } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import {
  AsyncBoundary,
  Button,
  Skeleton,
  SkeletonTable,
  hasPermission,
  segmentVariant,
  useRole,
} from "@/components/util";
import {
  EMPTY_VALUE,
  NO_POLLING,
  cn,
  formatDate,
  formatInteger,
  formatTotal,
  humaniseEnum,
  pollWhileVisible,
  queryKeys,
  useSearchParamsState,
  usePrefsStore,
} from "@/lib";

import { ChainVerifyPanel } from "./ChainVerifyPanel";
import {
  AUDIT_FILTERS_EMPTY,
  COUNTING_LIMIT,
  DESTRUCTIVE_WINDOW_MS,
  EXPOSURE_WINDOW_MS,
  auditFilterFields,
  auditFilterSchema,
  countDestructive,
  countRoutine,
  isDestructiveAction,
  revealExposureByActor,
  toAuditQuery,
} from "./auditQuery";

/** The one control shape this screen needs: a ground instead of a border, 14px corners. */
const CONTROL_CLASS =
  "type-body-sm rounded-control bg-surface-control px-3 py-1.5 text-ink transition-colors duration-fast ease-standard hover:bg-surface-control-hover";

/**
 * The `action` listbox, and why it does not simply wear `CONTROL_CLASS`.
 *
 * It is a real `<select multiple>` — 33 actions is far too many for the pill toggles the
 * `outcome` filter uses, and the URL-backed OR semantics are unchanged. What was broken was
 * its HEIGHT. Chromium sizes a list box as `size × row-height + padding`, but the padding
 * does not RESERVE a strip: `padding-top` merely pushes the rows down, so the last
 * `padding-bottom` worth of the client box shows the top slice of the NEXT row. With
 * `CONTROL_CLASS`'s `py-1.5` and Chromium's 17px rows that was a 63px control showing three
 * rows and the top 6px of a fourth — a half-drawn row bleeding off the bottom of a
 * borderless control, which in this idiom reads as a rendering fault rather than as "there
 * is more".
 *
 * So the control carries NO padding of its own and the breathing room moves onto the option
 * rows, which is also the only property Chromium honours there (`line-height` on either the
 * select or the option is ignored in a list box; `padding` is not — measured, both). `py-1`
 * takes a row from 17px to a round 24px, and `size={5}` therefore makes the client box
 * exactly 5 × 24px. Rows end where the control ends, at every zoom level, because both
 * numbers come from the same row height.
 */
const ACTION_SELECT_CLASS =
  "type-body-sm min-w-[12rem] rounded-control bg-surface-control p-0 text-ink [&>option]:px-3 [&>option]:py-1";

/** §12.3's audio caveat, which the plan says the audit UI must state. */
const AUDIO_RANGE_NOTE =
  "an <audio> element issues many range requests; the router audits the first per actor and asset per 10 minutes, so one row is one play and not one request";

/**
 * Glyph + word + colour, so an outcome survives greyscale (§11.3).
 *
 * The reskin splits the hue the way the palette recommends for a tinted chip: the GROUND is
 * the family's `-tint`, the GLYPH is the text-safe hue, and the WORD is `--ink` on top of
 * both at 6.6:1. Painting the word in the hue instead would have pinned it to the family's
 * 4.5:1 floor for no gain — the glyph is where the eye catches the colour anyway.
 *
 * `denied` is `--caution`, the softer attention hue: a refusal is the system working. Only
 * `error` gets `--error`.
 */
const OUTCOME_PRESENTATION: Record<
  AuditOutcome,
  { glyph: string; glyphClass: string; groundClass: string }
> = {
  ok: {
    glyph: "✓",
    glyphClass: "text-success",
    groundClass: "bg-success-tint",
  },
  denied: {
    glyph: "⊘",
    glyphClass: "text-caution",
    groundClass: "bg-caution-tint",
  },
  error: { glyph: "✗", glyphClass: "text-error", groundClass: "bg-error-tint" },
};

/**
 * The role check happens OUTSIDE the body, not inside it.
 *
 * §12.2 gives `audit.read` to OPERATOR and OWNER only. A SUPPORT who pastes `/audit` into
 * the bar must not have five reads fired on their behalf: each one is a 403 that writes a
 * `permission.denied` row — into this very log — and §11.4's rule is role-based HIDING, not
 * a control that explains itself by failing. While the role is still unknown the screen
 * renders its skeleton rather than the refusal, because a refusal that appears for 200 ms and
 * then turns into a working screen is worse than a slightly later screen.
 */
export function AuditScreen(): ReactElement {
  const role = useRole();

  if (role === null) {
    return (
      <div className="p-gutter">
        <Skeleton className="h-[7.5rem] w-72" />
      </div>
    );
  }

  if (!hasPermission(role, "audit.read")) {
    return (
      <div className="flex justify-center px-gutter py-gutter" data-testid="audit-forbidden">
        {/*
         * The design's centred card for an absence, built here rather than with
         * `<EmptyState>`: this is a whole screen and needs the page's one `h1`, and
         * `EmptyState` renders its title as a `<p>` inside a `role="status"` region.
         */}
        <section className="flex w-full max-w-xl flex-col items-center gap-3 rounded-card bg-surface-card px-8 py-12 text-center shadow-card">
          <span aria-hidden="true" className="text-[28px] leading-none text-ink-muted">
            🔒
          </span>
          <h1 className="type-h1 text-ink">Audit</h1>
          <p className="type-body max-w-prose text-ink-muted">
            Reading the audit log is an operator and owner capability. Nothing was requested on your
            behalf, so this visit wrote no refusal row.
          </p>
        </section>
      </div>
    );
  }

  return <AuditBody />;
}

function AuditBody(): ReactElement {
  const filters = useSearchParamsState(auditFilterSchema, AUDIT_FILTERS_EMPTY);
  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);
  const density = usePrefsStore((state) => state.density);

  // Pinned at mount: a window recomputed every render would change the query key on every
  // render and poll the API as fast as React re-renders.
  const since24h = useMemo(() => new Date(Date.now() - DESTRUCTIVE_WINDOW_MS).toISOString(), []);
  const since7d = useMemo(() => new Date(Date.now() - EXPOSURE_WINDOW_MS).toISOString(), []);

  const destructiveQuery = useMemo<AuditQuery>(
    () => ({
      from: since24h,
      action: DESTRUCTIVE_AUDIT_ACTIONS,
      limit: COUNTING_LIMIT,
    }),
    [since24h],
  );
  const windowQuery = useMemo<AuditQuery>(
    () => ({ from: since24h, limit: COUNTING_LIMIT }),
    [since24h],
  );
  const revealQuery = useMemo<AuditQuery>(
    () => ({
      from: since7d,
      action: ["reveal.personal"],
      limit: COUNTING_LIMIT,
    }),
    [since7d],
  );
  const listQuery = useMemo(() => toAuditQuery(filters.value), [filters.value]);

  const entries = useQuery({
    queryKey: queryKeys.audit.list(listQuery),
    queryFn: ({ signal }) => unwrapAsync(getAudit(listQuery, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const destructive = useQuery({
    queryKey: queryKeys.audit.list(destructiveQuery),
    queryFn: ({ signal }) => unwrapAsync(getAudit(destructiveQuery, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const routine = useQuery({
    queryKey: queryKeys.audit.list(windowQuery),
    queryFn: ({ signal }) => unwrapAsync(getAudit(windowQuery, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const reveals = useQuery({
    queryKey: queryKeys.audit.list(revealQuery),
    queryFn: ({ signal }) => unwrapAsync(getAudit(revealQuery, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const verify = useQuery({
    queryKey: queryKeys.audit.verify(),
    queryFn: ({ signal }) => unwrapAsync(getAuditVerify({ signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const chips = useMemo(
    () =>
      buildFilterChips(
        filters,
        auditFilterFields((value) => formatDate(String(value), timeZoneMode)),
      ),
    [filters, timeZoneMode],
  );

  const items = entries.data?.items ?? [];

  const exposure = useMemo(
    () => revealExposureByActor(reveals.data?.items ?? []),
    [reveals.data?.items],
  );
  const exposureData = useMemo<readonly ChartDatum[]>(
    () => exposure.map((row) => ({ actor: row.actor, records: row.records })),
    [exposure],
  );
  const uncountedReveals = exposure.reduce((total, row) => total + row.uncountedReveals, 0);

  const columns = useMemo<readonly DataColumn<AuditEntryView>[]>(
    () => [
      {
        id: "seq",
        header: "seq",
        isNumeric: true,
        width: "5rem",
        cell: (row) => formatInteger(row.seq),
      },
      {
        id: "at",
        header: "at",
        isNumeric: false,
        cell: (row) => <Timestamp at={row.at} seconds />,
      },
      {
        id: "actor",
        header: "actor",
        isNumeric: false,
        cell: (row) => (
          <span className="flex flex-wrap items-baseline gap-x-2">
            {/* An operator's own username — our account, not customer content. */}
            <span className="text-ink">{row.actorUsername}</span>
            <span className="type-caption text-ink-muted">{row.actorRole}</span>
          </span>
        ),
      },
      {
        id: "action",
        header: "action",
        isNumeric: false,
        cell: (row) => (
          <span className="flex flex-wrap items-baseline gap-x-2">
            {/* Verbatim: the values are dotted and abbreviated, and are not slugs. */}
            <code className="type-mono text-ink">{row.action}</code>
            {isDestructiveAction(row.action) ? (
              <span className="type-caption inline-flex items-baseline gap-1 rounded-pill bg-error-tint px-2 py-0.5 text-ink">
                <span aria-hidden="true" className="text-error">
                  ⚑
                </span>{" "}
                destructive
              </span>
            ) : null}
          </span>
        ),
      },
      {
        id: "outcome",
        header: "outcome",
        isNumeric: false,
        width: "8rem",
        cell: (row) => {
          const presentation = OUTCOME_PRESENTATION[row.outcome];
          return (
            <span className="flex flex-wrap items-baseline gap-1">
              <span
                className={cn(
                  "type-body-sm inline-flex items-baseline gap-1 rounded-pill px-2 py-0.5 text-ink",
                  presentation.groundClass,
                )}
              >
                <span aria-hidden="true" className={presentation.glyphClass}>
                  {presentation.glyph}
                </span>{" "}
                {row.outcome}
              </span>
              {row.errorCode === null ? null : (
                <code className="type-mono text-ink-muted">{row.errorCode}</code>
              )}
            </span>
          );
        },
      },
      {
        id: "subject",
        header: "subject",
        isNumeric: false,
        cell: (row) => (
          <span className="flex flex-col">
            <span className="type-body-sm text-ink-muted">{row.subjectType}</span>
            {row.subjectId === null ? null : (
              <code className="type-mono text-ink-muted" title={row.subjectId}>
                {row.subjectId.slice(0, 12)}
              </code>
            )}
          </span>
        ),
      },
      {
        id: "records",
        header: "records",
        headerTitle: "how many records this row exposed — the reveal budget's unit",
        isNumeric: true,
        width: "6rem",
        // `null` is "no count recorded", never zero.
        cell: (row) => (row.recordCount === null ? EMPTY_VALUE : formatInteger(row.recordCount)),
      },
      {
        id: "reason",
        header: "reason",
        isNumeric: false,
        cell: (row) => <ReasonCell entry={row} />,
      },
      {
        id: "correlation",
        header: "correlation",
        isNumeric: false,
        cell: (row) => <CorrelationChip correlationId={row.correlationId} />,
      },
    ],
    [],
  );

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Audit"
        description="Who did something destructive?"
        signal={
          <AsyncBoundary
            status={destructive.status}
            hasData={destructive.data !== undefined}
            error={destructive.error}
            onRetry={() => void destructive.refetch()}
            {...(destructive.isError ? { dataUpdatedAt: destructive.dataUpdatedAt } : {})}
            noun="the destructive count"
            skeleton={<Skeleton className="h-[7.5rem] w-72" />}
          >
            <div className="flex flex-wrap items-stretch gap-3" data-testid="audit-signal">
              <StatTile
                size="hero"
                label="destructive actions · 24h"
                value={formatTotal(
                  countDestructive(destructive.data?.items ?? []),
                  // A page carrying a `nextCursor` was truncated at the counting limit, so
                  // the figure is a lower bound and `formatTotal` renders it as `200+`.
                  destructive.data === undefined ? null : destructive.data.meta.nextCursor === null,
                )}
                hint={`${String(DESTRUCTIVE_AUDIT_ACTIONS.length)} actions count as destructive`}
                glyph="⚑"
              />
              <StatTile
                label="everything else · 24h"
                value={
                  routine.data === undefined
                    ? EMPTY_VALUE
                    : formatTotal(
                        countRoutine(routine.data.items),
                        routine.data.meta.nextCursor === null,
                      )
                }
                hint="logins, reads, refusals — counted apart from the figure beside it"
              />
            </div>
          </AsyncBoundary>
        }
      >
        <FilterBar
          label="audit filters"
          chips={chips}
          activeCount={filters.activeCount}
          onClear={() => {
            filters.clear();
          }}
        >
          <TimeRangePicker
            label="window"
            value={{ from: filters.value.from, to: filters.value.to }}
            onChange={(next: TimeRange) => {
              filters.patch({ from: next.from, to: next.to });
            }}
          />
          {/* A segment, so its two states come from `segmentVariant` and nowhere else:
              pressed is the secondary idiom (the brand tint under the brand), unpressed is
              `quiet` — NO ground until hover. It used to hand-roll
              `bg-surface-control text-ink-muted` for the unpressed state, which is the
              grey-on-grey the design language names as the thing not to do; it cleared
              5.28:1, so no contrast gate could see it. `aria-pressed` still carries the
              state for anyone who cannot see either. */}
          <Button
            variant={segmentVariant(
              (filters.value.action ?? []).length === DESTRUCTIVE_AUDIT_ACTIONS.length,
            )}
            size="xs"
            shape="pill"
            data-testid="audit-destructive-only"
            aria-pressed={(filters.value.action ?? []).length === DESTRUCTIVE_AUDIT_ACTIONS.length}
            onClick={() => {
              filters.patch({ action: [...DESTRUCTIVE_AUDIT_ACTIONS] });
            }}
          >
            <span aria-hidden="true">⚑</span> destructive only
          </Button>
          <label className="type-caption flex items-center gap-2 text-ink-muted">
            action
            <select
              multiple
              size={5}
              aria-label="action"
              className={ACTION_SELECT_CLASS}
              value={filters.value.action ?? []}
              onChange={(event) => {
                const chosen = [...event.target.selectedOptions].map(
                  (option) => option.value as AuditAction,
                );
                filters.patch({
                  action: chosen.length === 0 ? undefined : chosen,
                });
              }}
            >
              {AUDIT_ACTION_VALUES.map((action) => (
                <option key={action} value={action}>
                  {action}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="outcome">
            <span className="type-caption text-ink-muted">outcome</span>
            {AUDIT_OUTCOME_VALUES.map((outcome) => {
              const isOn = (filters.value.outcome ?? []).includes(outcome);
              return (
                /* Same segment idiom as "destructive only" above, from the same helper. */
                <Button
                  key={outcome}
                  variant={segmentVariant(isOn)}
                  size="xs"
                  shape="pill"
                  aria-pressed={isOn}
                  onClick={() => {
                    const current = filters.value.outcome ?? [];
                    const next = isOn
                      ? current.filter((item) => item !== outcome)
                      : [...current, outcome];
                    filters.patch({
                      outcome: next.length === 0 ? undefined : next,
                    });
                  }}
                >
                  {outcome}
                </Button>
              );
            })}
          </div>
          <label className="type-caption flex items-center gap-2 text-ink-muted">
            actor
            <input
              type="text"
              value={filters.value.actor ?? ""}
              placeholder="username or id"
              onChange={(event) => {
                const raw = event.target.value.trim();
                filters.patch({ actor: raw === "" ? undefined : raw });
              }}
              className={cn(CONTROL_CLASS, "w-40 placeholder:text-ink-muted")}
            />
          </label>
          <label className="type-caption flex items-center gap-2 text-ink-muted">
            subject id
            <input
              type="text"
              value={filters.value.subjectId ?? ""}
              onChange={(event) => {
                const raw = event.target.value.trim();
                filters.patch({ subjectId: raw === "" ? undefined : raw });
              }}
              className={cn(CONTROL_CLASS, "w-40")}
            />
          </label>
        </FilterBar>
      </PageHeader>

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        <section aria-label="chain and exposure" className="flex flex-col gap-3">
          <h2 className="type-h3 text-ink">Standing checks</h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <AsyncBoundary
              status={verify.status}
              hasData={verify.data !== undefined}
              error={verify.error}
              onRetry={() => void verify.refetch()}
              {...(verify.isError ? { dataUpdatedAt: verify.dataUpdatedAt } : {})}
              noun="the chain verification"
              skeleton={<Skeleton className="h-40 w-full" />}
            >
              {verify.data === undefined ? null : <ChainVerifyPanel verify={verify.data} />}
            </AsyncBoundary>

            <AsyncBoundary
              status={reveals.status}
              hasData={reveals.data !== undefined}
              isEmpty={exposure.length === 0}
              error={reveals.error}
              onRetry={() => void reveals.refetch()}
              {...(reveals.isError ? { dataUpdatedAt: reveals.dataUpdatedAt } : {})}
              noun="reveals"
              emptyTitle="No reveals in the last 7 days"
              emptyBody="Every reveal is audited and charged in records, so an empty chart is a real zero."
              skeleton={<Skeleton className="h-56 w-full" />}
            >
              <div className="flex flex-col gap-2" data-testid="reveal-exposure">
                <ChartFrame
                  title="Reveal exposure by actor · 7 days"
                  subtitle="records exposed, not rows — one reveal can touch up to 50 conversation bodies"
                  kind="bar"
                  data={exposureData}
                  xKey="actor"
                  series={[{ key: "records", label: "records exposed", tone: "c-1" }]}
                  formatY={(value) => formatInteger(value)}
                  formatValue={(value) => formatInteger(value)}
                  isRefetching={reveals.isFetching}
                  emptyLabel="no reveals in this window"
                />
                {uncountedReveals === 0 ? null : (
                  <p className="type-body-sm text-ink-muted">
                    {`${formatInteger(uncountedReveals)} reveal rows recorded no record count and are not in the bars.`}
                  </p>
                )}
                <p className="type-body-sm text-ink-muted">{AUDIO_RANGE_NOTE}</p>
              </div>
            </AsyncBoundary>
          </div>
        </section>

        <section aria-label="audit log" className="flex flex-col gap-3">
          <h2 className="type-h3 text-ink">The log</h2>
          <AsyncBoundary
            status={entries.status}
            hasData={entries.data !== undefined}
            isEmpty={items.length === 0}
            activeFilterCount={filters.activeCount}
            onClearFilters={() => {
              filters.clear();
            }}
            error={entries.error}
            onRetry={() => void entries.refetch()}
            {...(entries.isError ? { dataUpdatedAt: entries.dataUpdatedAt } : {})}
            noun="audit entries"
            emptyTitle="No audit entries yet"
            emptyBody="The first row is written by the first login."
            skeleton={<SkeletonTable rows={10} columns={9} density={density} />}
          >
            <DataTable<AuditEntryView>
              label="audit entries"
              data={items}
              columns={columns}
              getRowId={(row) => String(row.seq)}
              isRowHighlighted={(row) => isDestructiveAction(row.action)}
              isRefetching={entries.isFetching}
              footer={
                <CursorPager
                  label="audit entries"
                  // `/api/audit` has its own envelope: a `nextCursor` and nothing else. There
                  // is no `total` to render and asking for one is a 422.
                  meta={{
                    nextCursor: entries.data?.meta.nextCursor ?? null,
                    total: null,
                    isTotalExact: null,
                  }}
                  itemCount={items.length}
                  cursor={filters.value.cursor ?? null}
                  onCursorChange={(next) => {
                    filters.patch({ cursor: next ?? undefined }, { keepCursor: true });
                  }}
                  limit={filters.value.limit ?? DEFAULT_PAGE_LIMIT}
                  onLimitChange={(limit) => {
                    filters.patch({ limit });
                  }}
                  isFetching={entries.isFetching}
                />
              }
            />
          </AsyncBoundary>
        </section>
      </div>
    </div>
  );
}

/**
 * The reason a row was written.
 *
 * `hasReasonText === true` with `reasonText === null` is an ADMIN reading an OWNER's row:
 * a reason WAS recorded and this role may not read it. §12.3 pins the copy — never
 * "no reason given", which would be a different and false claim. The text itself is the one
 * column an operator can have typed a customer's name into, so it goes through `NameText`.
 */
function ReasonCell({ entry }: { readonly entry: AuditEntryView }): ReactElement {
  return (
    <span className="flex flex-col">
      <span className="type-body-sm text-ink-muted">{humaniseEnum(entry.reasonCode)}</span>
      {entry.reasonRef === null ? null : (
        <code className="type-mono text-ink-muted">{entry.reasonRef}</code>
      )}
      {entry.reasonText !== null ? (
        <NameText value={entry.reasonText} className="type-body-sm" />
      ) : entry.hasReasonText ? (
        <span className="type-body-sm text-ink-muted">{REASON_WITHHELD_LABEL}</span>
      ) : null}
    </span>
  );
}

export const Component = AuditScreen;
