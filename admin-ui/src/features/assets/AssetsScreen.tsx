/**
 * `/assets` — §11.2: *"What is about to expire?"*
 *
 * The dominant signal is **assets expiring within 7 days**, and it is a query of its own
 * (`expiringWithinDays=7&withTotal=true&limit=1`) rather than something derived from the
 * page on screen: the operator's filters must not be able to change the number that answers
 * the screen's question. Its window has no lower bound — rows already past `expires_at` are
 * inside it, because the sweep has not reached them and the bytes are still there — so the
 * tile says so under the figure.
 *
 * **There is no size column, and adding one would be a lie.** §11.2: "storage size is *not*
 * shown — `size_bytes` is always 0". `AssetWireView.sizeBytes` is on the wire and is `0` for
 * every row in production; `formatBytes(0)` renders `0 B`, which for a four-megabyte song is
 * a wrong number an operator has no way to detect. The honest storage fact this screen shows
 * instead is `isStorageKeyRecorded`: `false` means the retention sweep can delete the row and
 * cannot reach the object, so the audio outlives its own deletion.
 *
 * Polling: none. §11.5 puts everything outside the pulse, order detail, moderation and the
 * orders list on "on demand + `refetchOnWindowFocus`", and a retention horizon measured in
 * days does not move in five seconds.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactElement } from "react";
import { useNavigate } from "react-router-dom";

import {
  getAssets,
  unwrapAsync,
  ASSET_KIND_VALUES,
  DEFAULT_PAGE_LIMIT,
  RETENTION_CLASS_VALUES,
  type AssetKind,
  type AssetsQuery,
  type AssetWireView,
  type RetentionClass,
} from "@/api";
import {
  CursorPager,
  DataTable,
  FilterBar,
  StatTile,
  TimeRangePicker,
  Timestamp,
  buildFilterChips,
  type DataColumn,
  type TimeRange,
} from "@/components/data";
import {
  AssetCard,
  BRIEF_REVEAL_FIELDS,
  EXPIRING_SOON_DAYS,
  OrderRefChip,
  RevealButton,
  UNRECORDED_STORAGE_KEY_LABEL,
  retentionUrgency,
  retentionUrgencyColorVar,
} from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Button, segmentVariant, Skeleton, SkeletonTable } from "@/components/util";
import {
  NO_POLLING,
  daysUntil,
  formatDate,
  formatDurationS,
  formatInteger,
  formatTotal,
  humaniseEnum,
  pollWhileVisible,
  queryKeys,
  useSearchParamsState,
  usePrefsStore,
} from "@/lib";
import { href } from "@/routes";

import { LyricSheetPanel } from "./LyricSheetPanel";
import {
  ASSETS_FILTERS_EMPTY,
  EXPIRY_WINDOW_CHOICES,
  assetsFilterFields,
  assetsFilterSchema,
  toAssetsQuery,
} from "./assetsQuery";

/**
 * The dominant signal's own read. `limit: 1` because only `meta.total` is wanted — the rows
 * are on the table below, and asking for fifty of them to count them would be a second copy
 * of the list.
 */
const EXPIRING_SIGNAL_QUERY: AssetsQuery = {
  expiringWithinDays: EXPIRING_SOON_DAYS,
  withTotal: true,
  limit: 1,
};

/** The one control shape this screen needs: a ground instead of a border, 14px corners. */
const SELECT_CLASS =
  "type-body-sm num rounded-control bg-surface-control px-3 py-1.5 text-ink transition-colors duration-fast ease-standard hover:bg-surface-control-hover";

export function AssetsScreen(): ReactElement {
  const navigate = useNavigate();
  const filters = useSearchParamsState(assetsFilterSchema, ASSETS_FILTERS_EMPTY);
  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);
  const density = usePrefsStore((state) => state.density);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const wireQuery = useMemo(() => toAssetsQuery(filters.value), [filters.value]);

  const assets = useQuery({
    queryKey: queryKeys.assets.list(wireQuery),
    queryFn: ({ signal }) => unwrapAsync(getAssets(wireQuery, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const expiring = useQuery({
    queryKey: queryKeys.assets.list(EXPIRING_SIGNAL_QUERY),
    queryFn: ({ signal }) => unwrapAsync(getAssets(EXPIRING_SIGNAL_QUERY, { signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const chips = useMemo(
    () =>
      buildFilterChips(
        filters,
        assetsFilterFields((value) => formatDate(String(value), timeZoneMode)),
      ),
    [filters, timeZoneMode],
  );

  const items = assets.data?.items ?? [];
  const selected = items.find((asset) => asset.id === selectedId) ?? null;

  const columns = useMemo<readonly DataColumn<AssetWireView>[]>(
    () => [
      {
        id: "kind",
        header: "kind",
        isNumeric: false,
        cell: (asset) => <span className="text-ink">{humaniseEnum(asset.kind)}</span>,
      },
      {
        id: "variant",
        header: "variant",
        isNumeric: true,
        width: "5rem",
        cell: (asset) => formatInteger(asset.variantIndex),
      },
      {
        id: "order",
        header: "order",
        isNumeric: false,
        cell: (asset) => <OrderRefChip orderId={asset.orderId} />,
      },
      {
        id: "retentionClass",
        header: "retention class",
        isNumeric: false,
        cell: (asset) => humaniseEnum(asset.retentionClass),
      },
      {
        id: "expires",
        header: "expires",
        isNumeric: false,
        cell: (asset) => <ExpiryCell asset={asset} />,
      },
      {
        id: "duration",
        header: "duration",
        isNumeric: true,
        width: "6rem",
        cell: (asset) => formatDurationS(asset.durationS),
      },
      {
        id: "storageKey",
        header: "storage key",
        isNumeric: false,
        cell: (asset) =>
          asset.isStorageKeyRecorded ? (
            <span className="text-ink-muted">recorded</span>
          ) : (
            // Glyph, word and hue — the same three channels a status pill carries, so the
            // one storage fact this screen is allowed to state survives greyscale.
            <span
              className="inline-flex items-baseline gap-1 text-caution"
              title={UNRECORDED_STORAGE_KEY_LABEL}
            >
              <span aria-hidden="true">⚠</span>
              <span>not recorded</span>
            </span>
          ),
      },
      {
        id: "createdAt",
        header: "created",
        isNumeric: false,
        cell: (asset) => <Timestamp at={asset.createdAt} />,
      },
    ],
    [],
  );

  const signalMeta = expiring.data?.meta ?? null;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Assets"
        description="What is about to expire?"
        signal={
          <AsyncBoundary
            status={expiring.status}
            hasData={expiring.data !== undefined}
            error={expiring.error}
            onRetry={() => void expiring.refetch()}
            {...(expiring.isError ? { dataUpdatedAt: expiring.dataUpdatedAt } : {})}
            noun="the expiry count"
            skeleton={<Skeleton className="h-[7.5rem] w-64" />}
          >
            <div data-testid="assets-expiring-signal">
              <StatTile
                size="hero"
                label={`expiring within ${String(EXPIRING_SOON_DAYS)} days`}
                value={formatTotal(signalMeta?.total ?? null, signalMeta?.isTotalExact ?? null)}
                hint="counts rows already past expiry too — the sweep has not reached them yet"
              />
            </div>
          </AsyncBoundary>
        }
        actions={
          /* The design's SECONDARY button: a tint of the hue with the hue as the label,
             never grey-on-grey. This call site was already right; it is here now so that it
             and the ones that were wrong cannot diverge again. */
          <Button
            variant="secondary"
            shape="pill"
            className="px-4"
            onClick={() => {
              filters.patch({ expiringWithinDays: EXPIRING_SOON_DAYS });
            }}
          >
            {`Show the ${String(EXPIRING_SOON_DAYS)}-day window`}
          </Button>
        }
      >
        <FilterBar
          label="asset filters"
          chips={chips}
          activeCount={filters.activeCount}
          onClear={() => {
            filters.clear();
          }}
        >
          <TimeRangePicker
            label="created"
            value={{ from: filters.value.from, to: filters.value.to }}
            onChange={(next: TimeRange) => {
              filters.patch({ from: next.from, to: next.to });
            }}
          />
          <EnumToggles<AssetKind>
            label="kind"
            values={ASSET_KIND_VALUES}
            selected={filters.value.kind ?? []}
            onChange={(next) => {
              filters.patch({ kind: next.length === 0 ? undefined : next });
            }}
          />
          <EnumToggles<RetentionClass>
            label="retention class"
            values={RETENTION_CLASS_VALUES}
            selected={filters.value.retentionClass ?? []}
            onChange={(next) => {
              filters.patch({ retentionClass: next.length === 0 ? undefined : next });
            }}
          />
          <label className="type-body-sm flex items-center gap-2 text-ink-muted">
            expiring within
            <select
              className={SELECT_CLASS}
              value={filters.value.expiringWithinDays ?? ""}
              onChange={(event) => {
                const raw = event.target.value;
                filters.patch({
                  expiringWithinDays: raw === "" ? undefined : Number(raw),
                });
              }}
            >
              <option value="">any</option>
              {EXPIRY_WINDOW_CHOICES.map((days) => (
                <option key={days} value={days}>
                  {`${String(days)} days`}
                </option>
              ))}
            </select>
          </label>
        </FilterBar>
      </PageHeader>

      <div className="grid grid-cols-1 items-start gap-6 px-gutter pb-gutter xl:grid-cols-[minmax(0,1fr)_21rem]">
        {/* Plain section labels above the cards, not inside them — the design's own way of
            grouping. The page's one `h1` is on the header; these are `h2`. */}
        <section aria-label="stored assets" className="flex min-w-0 flex-col gap-3">
          <h2 className="type-h3 text-ink">Stored assets</h2>
          <AsyncBoundary
            status={assets.status}
            hasData={assets.data !== undefined}
            isEmpty={items.length === 0}
            activeFilterCount={filters.activeCount}
            onClearFilters={() => {
              filters.clear();
            }}
            error={assets.error}
            onRetry={() => void assets.refetch()}
            {...(assets.isError ? { dataUpdatedAt: assets.dataUpdatedAt } : {})}
            noun="assets"
            emptyTitle="No assets stored yet"
            emptyBody="An asset row appears once a kit reaches the persisting stage."
            skeleton={<SkeletonTable rows={8} columns={8} density={density} />}
          >
            <DataTable<AssetWireView>
              label="assets"
              data={items}
              columns={columns}
              getRowId={(asset) => asset.id}
              isRowHighlighted={(asset) => asset.id === selectedId}
              onRowActivate={(asset) => {
                setSelectedId(asset.id);
              }}
              isRefetching={assets.isFetching}
              footer={
                <CursorPager
                  label="assets"
                  meta={assets.data?.meta}
                  itemCount={items.length}
                  cursor={filters.value.cursor ?? null}
                  onCursorChange={(next) => {
                    filters.patch({ cursor: next ?? undefined }, { keepCursor: true });
                  }}
                  limit={filters.value.limit ?? DEFAULT_PAGE_LIMIT}
                  onLimitChange={(limit) => {
                    filters.patch({ limit });
                  }}
                  isFetching={assets.isFetching}
                />
              }
            />
          </AsyncBoundary>
        </section>

        <aside className="flex flex-col gap-3" aria-label="selected asset">
          <h2 className="type-h3 text-ink">Selected asset</h2>
          {selected === null ? (
            <div className="flex flex-col items-center gap-2 rounded-card bg-surface-card px-6 py-12 text-center shadow-card">
              {/* `--ink-muted`, not the policed `--ink-mark`: it is the largest thing on an
                  otherwise empty card, so it clears the text bar and needs no waiver. */}
              <span aria-hidden="true" className="text-[28px] leading-none text-ink-muted">
                ◇
              </span>
              <p className="type-body-sm text-ink-muted">
                Select a row to see its retention clock and storage facts.
              </p>
            </div>
          ) : (
            <>
              <AssetCard asset={selected} timeZoneMode={timeZoneMode} />
              {/* Audio playback lives on the card, which is rendered on order and user
                  detail too and must offer it identically everywhere. The lyric sheet has no
                  home on the card — it is a document, not a field — so its reveal is here,
                  and it renders nothing at all for a row that is not one. */}
              <LyricSheetPanel asset={selected} />
              <Button
                variant="secondary"
                shape="pill"
                className="self-start px-4"
                onClick={() => {
                  navigate(href.order(selected.orderId));
                }}
              >
                Open the order
              </Button>
              {/*
                The OTHER reveal an asset leads to, and it is a different endpoint from the one
                above: the panel reveals the asset's own bytes through the media routes, this
                reveals the ORDER's brief through `POST /api/reveal`. From a lyric sheet whose
                text looks wrong, the next question is almost always "what name was approved?",
                and the answer is a brief column rather than anything on the asset row.

                Keyed on `orderId`, deliberately: `_replace_assets` deletes and re-inserts, so
                `assets.id` is not stable across a re-render, and the reveal's subject must be.
                `RevealButton` carries its own `PermissionGate` — a VIEWER sees nothing here.
              */}
              <RevealButton
                subjectType="order"
                subjectId={selected.orderId}
                subjectLabel={`${selected.orderId.slice(0, 8)}…`}
                fields={BRIEF_REVEAL_FIELDS}
                label="Reveal the order's brief"
              />
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

/** The expiry column: the instant, and how long is left, coloured by urgency. */
function ExpiryCell({ asset }: { readonly asset: AssetWireView }): ReactElement {
  const daysLeft = daysUntil(asset.expiresAt);
  const urgency = retentionUrgency(
    { label: "asset", expiresAt: asset.expiresAt, purgedAt: null },
    daysLeft,
  );
  return (
    <span className="flex flex-wrap items-baseline gap-x-2" data-urgency={urgency}>
      <Timestamp at={asset.expiresAt} />
      <span className="type-body-sm num" style={{ color: retentionUrgencyColorVar(urgency) }}>
        {remainingLabel(daysLeft)}
      </span>
    </span>
  );
}

/** Our own words about our own numbers — the same vocabulary `RetentionClocks` uses. */
function remainingLabel(daysLeft: number | null): string {
  if (daysLeft === null) return "";
  if (daysLeft > 1) return `in ${String(daysLeft)}d`;
  if (daysLeft === 1) return "in 1d";
  if (daysLeft === 0) return "expires today";
  return `${String(Math.abs(daysLeft))}d past expiry`;
}

/**
 * A row of toggles over one of our closed vocabularies.
 *
 * Local to this screen on purpose: the component inventory has no select or multi-select,
 * and inventing a shared one from a feature directory is how two half-finished primitives
 * end up in `components/`. Reported as a gap instead.
 */
function EnumToggles<T extends string>({
  label,
  values,
  selected,
  onChange,
}: {
  readonly label: string;
  readonly values: readonly T[];
  readonly selected: readonly T[];
  readonly onChange: (next: T[]) => void;
}): ReactElement {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={label}>
      <span className="type-caption text-ink-muted">{label}</span>
      {values.map((value) => {
        const isOn = selected.includes(value);
        return (
          /* On is the secondary idiom, off is `quiet` — the same two states the nav rail
             uses, now from the same helper. `aria-pressed` is the channel that does not
             depend on seeing either. */
          <Button
            key={value}
            variant={segmentVariant(isOn)}
            size="xs"
            shape="pill"
            aria-pressed={isOn}
            onClick={() => {
              onChange(isOn ? selected.filter((item) => item !== value) : [...selected, value]);
            }}
          >
            {humaniseEnum(value)}
          </Button>
        );
      })}
    </div>
  );
}

export const Component = AssetsScreen;
