/**
 * Audience: who is here, who is leaving, and — behind its own permission — who they are.
 *
 * Three reads meet on this tab and they fail independently, which is the whole reason the
 * layout is what it is:
 *
 *  - `/dashboard/audience` (`DASHBOARD_READ`) serves the two figures below. It is the same
 *    route the stat cards in the band above the tabs come off, so its note is already drawn up
 *    there; this group blocks quietly rather than repeating the same sentence a second time.
 *  - `/series` (`DASHBOARD_READ`) serves Sign-ups, through `ChartPanel`, which carries its own
 *    failure inside its own card.
 *
 * ## What moved out, and why it is not here any more
 *
 * The four STAT CARDS, the CHURN card and the two identified-customer lists — top generators,
 * recent subscribers — used to open this tab, in that order. The owner asked for all of it
 * above the tab content on EVERY tab, so `DashboardPage` draws it now, once, over whichever
 * section is open, in the order it always had. Nothing about it changed except where it is
 * mounted; the reasoning for the lists' permission boundary and their masking (there is none,
 * by decision) moved with them and lives in that file.
 *
 * What is left here is FIGURES, which is why this file no longer reads `state`, `values` or the
 * card periods at all — it takes `SectionProps` for the one shape all four tabs are handed and
 * uses the figure half of it.
 */

import type { JSX } from "react";

import type { AudienceResponse } from "@/api/dashboard";
import { Skeleton } from "@/components/Skeleton";
import { adaptActiveAccounts, adaptLanguageMix } from "@/features/dashboard/adapt";
import { ActiveAccounts, LanguageMix } from "@/features/dashboard/charts";
import { chartSpecsFor } from "@/features/dashboard/chartSpecs";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import {
  ChartPanels,
  FigureCard,
  FigureGrid,
  FigureHeading,
  FigureSkeleton,
  GroupLabel,
  type Query,
  type SectionProps,
} from "./SectionChrome";

export interface AudienceSectionProps extends SectionProps {
  /**
   * The audience response at the FIGURE period — the same route the stat cards come off, asked
   * for at the window the figure picker names.
   *
   * A separate hook from the four the cards use so that `keepPreviousData` applies to it: a
   * figure period change keeps the previous drawing on screen, dimmed, instead of blanking
   * three figures for a round trip. When the picker is on the base window it is the same query
   * key as the cards' base read, so it costs nothing.
   */
  readonly figures: Query<AudienceResponse>;
}

export function AudienceSection({
  figurePeriod,
  picker,
  grans,
  onGranChange,
  finance,
  figures,
}: AudienceSectionProps): JSX.Element {
  const { t } = useI18n();
  const audience = figures.data;
  /* A read that failed with nothing to show draws no figures; the note above the stat band is
     the same route's note and has already said why. */
  const blocked = audience === undefined && figures.error !== null;
  const dim = figures.isPlaceholderData;

  return (
    <>
      <FigureHeading label={t("dashboard.figures.heading")}>{picker}</FigureHeading>

      {!blocked && (
        <>
          <FigureGrid>
            <ChartPanels
              specs={chartSpecsFor("audience")}
              period={figurePeriod}
              grans={grans}
              onGranChange={onGranChange}
              finance={finance}
            />
            <FigureCard
              title={t("dashboard.figures.activeAccounts.title")}
              sub={t("dashboard.figures.activeAccounts.sub")}
              cov={t("dashboard.figures.activeAccounts.cov")}
              isPlaceholder={dim}
            >
              {audience === undefined ? (
                <FigureSkeleton />
              ) : (
                <ActiveAccounts {...adaptActiveAccounts(audience)} />
              )}
            </FigureCard>
          </FigureGrid>

          {/* NOT a card: the lane is 651x84, about eight times wider than tall, and in a
              651x176 chart box it would float in half a card with its caption stranded. It
              prints its own caption and its own "also here" line, so a heading is all it
              needs. */}
          <GroupLabel>{t("dashboard.figures.interfaceLanguage")}</GroupLabel>
          <div className={cn("transition-opacity", dim && "opacity-50")}>
            {audience === undefined ? (
              <Skeleton className="aspect-[651/84] w-full rounded-card" />
            ) : (
              <LanguageMix {...adaptLanguageMix(audience)} />
            )}
          </div>
        </>
      )}
    </>
  );
}
