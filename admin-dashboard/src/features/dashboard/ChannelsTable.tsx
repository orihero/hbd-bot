/**
 * Marketing channels traffic attribution table.
 *
 * Displays acquisition performance for each marketing channel navigating to the bot
 * via deep-links (?start=channel, ?start=utm_source=channel, etc.):
 *  - Clicks / Starts
 *  - New first-touch users
 *  - Onboarded users
 *  - Delivered songs
 *  - Paying customers
 *  - Revenue in UZS
 *  - Conversion rate (%)
 */

import { useMemo, useState, type JSX } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Tag } from "lucide-react";

import type { ChannelPerformanceView } from "@/api/dashboard";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { formatCount, money } from "@/features/dashboard/adapt";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

export type ChannelSortKey =
  | "channel"
  | "clicks"
  | "newUsers"
  | "onboardedUsers"
  | "ordersCount"
  | "payingUsers"
  | "revenueMinor"
  | "conversionRate";

export interface ChannelsTableProps {
  readonly channels: readonly ChannelPerformanceView[];
  readonly isLoading: boolean;
  readonly isPlaceholder?: boolean;
}

export function ChannelsTable({
  channels,
  isLoading,
  isPlaceholder = false,
}: ChannelsTableProps): JSX.Element {
  const { t } = useI18n();
  const [sortKey, setSortKey] = useState<ChannelSortKey>("clicks");
  const [sortAsc, setSortAsc] = useState<boolean>(false);

  const handleSort = (key: ChannelSortKey) => {
    if (sortKey === key) {
      setSortAsc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortAsc(key === "channel");
    }
  };

  const sortedChannels = useMemo(() => {
    const list = [...channels];
    list.sort((a, b) => {
      const valA = a[sortKey];
      const valB = b[sortKey];
      if (typeof valA === "string" && typeof valB === "string") {
        return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }
      const numA = Number(valA);
      const numB = Number(valB);
      return sortAsc ? numA - numB : numB - numA;
    });
    return list;
  }, [channels, sortKey, sortAsc]);

  const totalClicks = useMemo(() => channels.reduce((acc, c) => acc + c.clicks, 0), [channels]);
  const totalRevenue = useMemo(
    () => channels.reduce((acc, c) => acc + c.revenueMinor, 0),
    [channels]
  );
  const totalPaying = useMemo(() => channels.reduce((acc, c) => acc + c.payingUsers, 0), [channels]);
  const formattedRevenue = money(totalRevenue, "UZS");

  return (
    <article
      className={cn(
        "flex flex-col overflow-hidden rounded-card bg-card px-5 py-[18px] transition-opacity",
        isPlaceholder && "opacity-50"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="m-0 text-base font-semibold leading-[1.35] tracking-[-.32px] text-ink-900">
              {t("dashboard.figures.channels.heading")}
            </h3>
            {channels.length > 0 && (
              <span className="whitespace-nowrap rounded-md bg-bg px-2 py-0.5 text-[10px] font-bold uppercase tracking-[.06em] text-ink-400">
                {`${formatCount(channels.length)} ${channels.length === 1 ? "channel" : "channels"}`}
              </span>
            )}
          </div>
          <p className="mb-0 mt-1 text-xs font-normal leading-[1.3] text-ink-400">
            {t("dashboard.figures.channels.subtitle")}
          </p>
        </div>

        {channels.length > 0 && (
          <div className="flex flex-wrap items-center gap-4 text-xs text-ink-600">
            <span className="flex items-center gap-1.5">
              <span className="text-ink-400">Total Starts:</span>
              <span className="font-semibold text-ink-900">{formatCount(totalClicks)}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="text-ink-400">Paying Users:</span>
              <span className="font-semibold text-ink-900">{formatCount(totalPaying)}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="text-ink-400">Total Revenue:</span>
              <span className="font-semibold text-ink-900">
                {formattedRevenue.value} {formattedRevenue.unit}
              </span>
            </span>
          </div>
        )}
      </div>

      <div className="mt-4" aria-busy={isLoading && channels.length === 0}>
        {isLoading && channels.length === 0 ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-9 w-full rounded" />
            <Skeleton className="h-10 w-full rounded" />
            <Skeleton className="h-10 w-full rounded" />
            <Skeleton className="h-10 w-full rounded" />
          </div>
        ) : channels.length === 0 ? (
          <div className="py-2">
            <EmptyState
              title={t("dashboard.figures.channels.emptyTitle")}
              message={t("dashboard.figures.channels.emptyMessage")}
            />
            <div className="mx-auto mt-4 max-w-lg rounded-lg border border-dashed border-stroke p-3 text-center text-xs text-ink-400">
              <span className="font-medium text-ink-700">Supported deep-link patterns:</span>
              <div className="mt-1 flex flex-wrap justify-center gap-2 font-mono text-[11px] text-accent">
                <span className="rounded bg-surface px-1.5 py-0.5">?start=utm_source=channel_name</span>
                <span className="rounded bg-surface px-1.5 py-0.5">?start=utm_source_channel_name</span>
                <span className="rounded bg-surface px-1.5 py-0.5">?start=c_channel_name</span>
                <span className="rounded bg-surface px-1.5 py-0.5">?start=channel_name</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-stroke text-ink-400">
                  <Th
                    label={t("dashboard.figures.channels.colChannel")}
                    sortKey="channel"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                  />
                  <Th
                    label={t("dashboard.figures.channels.colClicks")}
                    sortKey="clicks"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                  <Th
                    label={t("dashboard.figures.channels.colNewUsers")}
                    sortKey="newUsers"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                  <Th
                    label={t("dashboard.figures.channels.colOnboarded")}
                    sortKey="onboardedUsers"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                  <Th
                    label={t("dashboard.figures.channels.colOrders")}
                    sortKey="ordersCount"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                  <Th
                    label={t("dashboard.figures.channels.colPaying")}
                    sortKey="payingUsers"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                  <Th
                    label={t("dashboard.figures.channels.colRevenue")}
                    sortKey="revenueMinor"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                  <Th
                    label={t("dashboard.figures.channels.colConversion")}
                    sortKey="conversionRate"
                    currentSort={sortKey}
                    isAsc={sortAsc}
                    onSort={handleSort}
                    align="right"
                  />
                </tr>
              </thead>
              <tbody className="divide-y divide-stroke/50">
                {sortedChannels.map((item) => {
                  const rev = money(item.revenueMinor, "UZS");
                  const convPct = (item.conversionRate * 100).toFixed(1);
                  const isHighConv = item.conversionRate >= 0.1 && item.payingUsers > 0;

                  return (
                    <tr
                      key={item.channel}
                      className="group transition-colors hover:bg-surface/50"
                    >
                      <td className="py-2.5 pr-4 font-mono">
                        <div className="flex items-center gap-1.5">
                          <Tag className="h-3.5 w-3.5 text-accent opacity-70" />
                          <span className="rounded bg-surface px-2 py-0.5 font-mono text-[12px] font-semibold text-ink-900 border border-stroke/60">
                            {item.channel}
                          </span>
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-ink-900">
                        {formatCount(item.clicks)}
                      </td>
                      <td className="py-2.5 px-3 text-right text-ink-700">
                        {formatCount(item.newUsers)}
                      </td>
                      <td className="py-2.5 px-3 text-right text-ink-700">
                        {formatCount(item.onboardedUsers)}
                      </td>
                      <td className="py-2.5 px-3 text-right text-ink-700">
                        {formatCount(item.ordersCount)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-ink-900">
                        {formatCount(item.payingUsers)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-ink-900">
                        {item.revenueMinor > 0 ? (
                          <span>
                            {rev.value} <span className="text-[10px] text-ink-400">{rev.unit}</span>
                          </span>
                        ) : (
                          <span className="text-ink-300">—</span>
                        )}
                      </td>
                      <td className="py-2.5 pl-3 text-right">
                        {item.newUsers > 0 ? (
                          <Badge
                            tone={isHighConv ? "accent" : "neutral"}
                            className="font-mono text-[11px]"
                          >
                            {convPct}%
                          </Badge>
                        ) : (
                          <span className="text-ink-300">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </article>
  );
}

function Th({
  label,
  sortKey,
  currentSort,
  isAsc,
  onSort,
  align = "left",
}: {
  readonly label: string;
  readonly sortKey: ChannelSortKey;
  readonly currentSort: ChannelSortKey;
  readonly isAsc: boolean;
  readonly onSort: (key: ChannelSortKey) => void;
  readonly align?: "left" | "right";
}): JSX.Element {
  const isCurrent = currentSort === sortKey;
  return (
    <th
      className={cn(
        "py-2 px-3 font-medium cursor-pointer select-none transition-colors hover:text-ink-800",
        align === "right" ? "text-right" : "text-left"
      )}
      onClick={() => {
        onSort(sortKey);
      }}
    >
      <div
        className={cn(
          "inline-flex items-center gap-1",
          align === "right" && "flex-row-reverse"
        )}
      >
        <span>{label}</span>
        {isCurrent ? (
          isAsc ? (
            <ArrowUp className="h-3 w-3 text-accent" />
          ) : (
            <ArrowDown className="h-3 w-3 text-accent" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30 group-hover:opacity-70" />
        )}
      </div>
    </th>
  );
}
