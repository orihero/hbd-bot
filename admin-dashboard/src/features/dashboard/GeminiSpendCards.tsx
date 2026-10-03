/**
 * Gemini (Lyria) spend, on Finances: month-to-date, and what the figure window spent there.
 *
 * Google exposes no balance API, so there is no balance here — only our own metered SPEND, at
 * a flat per-request price, and every figure says `est.`. The month card reads
 * `GET /api/metrics/gemini-spend` (UTC calendar month, no window), the same query the
 * Generations badge uses. When the latest Gemini call was refused for lack of prepay credit
 * the card turns red and says so, because renders are then failing over to ElevenLabs.
 *
 * The window card is the series response's `costSplit` for `gemini`, over the FIGURE window —
 * its label names that window, because no stat card on this tab otherwise obeys the picker.
 * It is fetched at the untoggled grain so it shares the cost-split chart's request.
 */

import type { JSX } from "react";

import { Skeleton } from "@/components/Skeleton";
import { adaptGeminiSpend, formatUsd } from "@/features/dashboard/adapt";
import { PERIOD_LABEL_KEY, type Period } from "@/features/dashboard/data";
import { useGeminiSpend, useSeries } from "@/features/dashboard/useDashboardData";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import { GroupLabel, UNTOGGLED_GRANS, granOr } from "./sections/SectionChrome";

function Card({
  label,
  value,
  caption,
  tone = "normal",
  title,
  isLoading,
}: {
  readonly label: string;
  readonly value: string | null;
  readonly caption: string;
  readonly tone?: "normal" | "bad";
  readonly title?: string | undefined;
  readonly isLoading: boolean;
}): JSX.Element {
  return (
    <article
      aria-busy={isLoading}
      title={title}
      className="relative h-24 overflow-hidden rounded-card bg-card p-4"
    >
      <div className="flex h-5 items-center">
        <span className="text-[11px] font-semibold tracking-[-.1px] text-ink-400">{label}</span>
      </div>
      {isLoading ? (
        <>
          <div className="mt-1 flex h-8 items-center">
            <Skeleton className="h-[22px] w-[104px]" />
          </div>
          <div className="mt-[3px] flex h-[13px] items-center">
            <Skeleton className="h-[9px] w-[72%]" />
          </div>
        </>
      ) : (
        <>
          <div
            className={cn(
              "mt-1 whitespace-nowrap text-[32px] font-bold leading-[24px] tracking-[-1.92px]",
              value === null
                ? "text-ink-300"
                : tone === "bad"
                  ? "text-required-deep"
                  : "text-ink-800",
            )}
          >
            {value ?? "—"}
          </div>
          <div
            title={caption}
            className={cn(
              "mt-[3px] overflow-hidden text-ellipsis whitespace-nowrap text-[11px] font-normal leading-[13px]",
              tone === "bad" ? "text-required-deep" : "text-ink-300",
            )}
          >
            {caption}
          </div>
        </>
      )}
    </article>
  );
}

export function GeminiSpendCards({ period }: { readonly period: Period }): JSX.Element {
  const { t } = useI18n();
  const month = useGeminiSpend();
  const series = useSeries(period, granOr(UNTOGGLED_GRANS, period, "daily"));

  const view = month.data;
  const monthCaption =
    view === undefined
      ? (month.error?.message ?? "")
      : view.isDepleted
        ? t("dashboard.gemini.outOfCredit")
        : t("dashboard.gemini.monthSub", {
            songs: view.monthToDate.pricedCalls,
            today: formatUsd(view.today.spentUsd),
          });

  const spend = series.data === undefined ? null : adaptGeminiSpend(series.data.costSplit);
  const spendValue = spend === null || spend.usd === null ? null : formatUsd(spend.usd);
  /* A partial sum and a wholly unpriced window both say so: neither is the whole bill. */
  const spendCaption =
    spend === null
      ? (series.error?.message ?? "")
      : spend.usd === null || spend.isPartial
        ? t("dashboard.gemini.notPriced")
        : "";

  return (
    <section>
      <GroupLabel>{t("dashboard.gemini.heading")}</GroupLabel>
      <div
        className="mb-[10px] grid gap-[10px]"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))" }}
      >
        <Card
          label={t("dashboard.gemini.monthLabel")}
          value={view === undefined ? null : formatUsd(view.monthToDate.spentUsd)}
          caption={monthCaption}
          tone={view?.isDepleted === true ? "bad" : "normal"}
          title={t("dashboard.gemini.estimateHint")}
          isLoading={month.isLoading}
        />
        <Card
          label={t("dashboard.gemini.spendLabel", { period: t(PERIOD_LABEL_KEY[period]) })}
          value={spendValue}
          caption={spendCaption}
          isLoading={series.isLoading}
        />
      </div>
    </section>
  );
}
