import type { JSX } from "react";

import { Skeleton } from "@/components/Skeleton";
import { cn } from "@/lib/cn";

/**
 * The strip of compact measurements that sits above an index screen's list.
 *
 * It is the dashboard's `StatCard` rule carried to the four screens that are not the
 * dashboard — Users, Generations, Billing, Broadcasts — and it is deliberately DUMB. It does
 * not call `useI18n`, it does not import anything from `features/dashboard`, and it knows no
 * union of card keys. Every string it prints arrives already translated from the screen that
 * owns it. That is the whole reason four unrelated screens can share one component: the
 * dashboard's vocabulary — its `CardKey`, its `dashboard.cards.*` namespace, its period
 * selector — would otherwise have to be extended every time another screen wanted a number,
 * and the Users screen would end up reading its label out of a dashboard translation key.
 * Presentation-only is not laziness here; it is what keeps the coupling from forming.
 *
 * THE CAPTION IS THE POINT. A tile whose `value` is null prints an em dash — never a zero,
 * because a figure that could not be measured is absent and absence is not the number nought —
 * and prints `reason` underneath it. A blank number an operator cannot explain is the exact
 * defect this component exists to fix: "0 settled" and "we have no FX rate for this window"
 * are different facts, and an operator who cannot tell them apart will either chase an outage
 * that is not happening or ignore one that is. The reason caption is how the tile says which.
 *
 * The unit goes with the number. A dash beside `soʻm` quotes a currency for a figure that does
 * not exist, so `unit` is suppressed exactly when `value` is null — the same rule, and for the
 * same reason, as the dashboard's `StatCard`.
 */

/**
 * What stands in the value slot of a tile that has no value. It is not a number, and where a
 * `reason` was supplied it is never alone.
 */
const NO_VALUE = "—";

/**
 * Two tones, both from the palette `tailwind.config.ts` already exposes.
 *
 * `warn` is for a count an operator must ACT on — stuck intents, broadcasts wedged in flight —
 * and it is `--warn-deep`, the caution ink the kit already writes on its own `warn-18` ground
 * and the same ink `Badge`'s `warning` tone uses. It is not `required`: red in this console is
 * reserved for something that has already failed, and a queue that needs attention has not.
 *
 * Tone tints the VALUE and nothing else. The label stays `ink-400` in both arms, because a tone
 * is an emphasis on a measurement and not a second, colour-only status announcement that an
 * operator who cannot distinguish the two inks would simply never receive.
 */
const TONE_VALUE: Record<"neutral" | "warn", string> = {
  neutral: "text-ink-800",
  warn: "text-warn-deep",
};

export interface PageStat {
  /** Stable, for React keys and test queries. Not shown, and never translated. */
  readonly key: string;
  /** ALREADY TRANSLATED by the caller. This component never touches the i18n catalogue. */
  readonly label: string;
  /**
   * The measurement, already formatted (thousands separators, dates, percentages) by whoever
   * knows what it means. `null` means "not measured" — it renders an em dash and DROPS the
   * unit. It must never arrive as `"0"` standing in for an absent figure.
   */
  readonly value: string | null;
  /** Suffix, e.g. "so'm". Suppressed when `value` is null, along with the number it qualified. */
  readonly unit?: string;
  /** ALREADY TRANSLATED. Why the value is null; rendered as a small caption under the dash. */
  readonly reason?: string;
  /**
   * ALREADY TRANSLATED. A second, smaller line under a MEASURED value — the qualifier that
   * says what the headline figure is made of, e.g. `143 payments` under a sum of money.
   *
   * It occupies the same row `reason` does and the two can never both show, which is why they
   * are separate fields rather than one: `reason` explains an ABSENT figure and `caption`
   * qualifies a PRESENT one. Collapsing them into a single `hint` would make it possible to
   * write a caption that silently disappears exactly when the tile fails, which is the moment
   * an operator most needs to know what they are looking at.
   *
   * Never put the unit here — that is `unit`, and it is suppressed with the number it
   * qualifies for the reason this file's own comment gives.
   */
  readonly caption?: string;
  /** `warn` for a count an operator must act on. Default `neutral`. */
  readonly tone?: "neutral" | "warn";
}

export interface PageStatsProps {
  readonly stats: readonly PageStat[];
  /**
   * True while the figures have never arrived. Renders skeletons and `aria-busy`, and — the
   * part that matters — renders NO DIGITS at all. A tile that shows `0` while it waits has
   * told the operator something false, and it will keep on being false until the response
   * lands, which is precisely the window in which somebody reads it.
   */
  readonly isLoading?: boolean;
}

/**
 * One tile. Split out only so the loading arm and the measured arm can share a frame without
 * either one having to reproduce the other's padding.
 */
function StatTile({ stat, isLoading }: { readonly stat: PageStat; readonly isLoading: boolean }): JSX.Element {
  const measured = !isLoading && stat.value !== null;
  const tone = stat.tone ?? "neutral";

  return (
    /*
     * A `li` because the strip is a list and an assistive technology should be able to walk it
     * and be told how many tiles there are. `min-w-[132px]` with `flex-1` is what makes the row
     * WRAP rather than overflow: on a narrow viewport the tiles reflow onto a second line
     * instead of pushing the fourth one off the right-hand edge where nobody scrolls to find it.
     */
    <li className="min-w-[132px] flex-1 rounded-card border border-stroke bg-card px-4 py-3">
      {/*
       * The label is associated with its value through `aria-labelledby` rather than by sitting
       * next to it, so a screen reader announces "Settled, 412" as one thing. Without it the two
       * are read as separate, unrelated strings and the number arrives with no noun attached.
       */}
      <div id={`page-stat-${stat.key}-label`} className="text-[11px] font-semibold tracking-[-.1px] text-ink-400">
        {stat.label}
      </div>

      {isLoading ? (
        /* Sized to the rows they stand in — 24px of value, 13px of caption — so the tile does
           not change height the moment the figure arrives and shove the list below it down. */
        <>
          <div className="mt-1 flex h-6 items-center">
            <Skeleton className="h-[18px] w-[72px]" />
          </div>
          <div className="mt-[3px] flex h-[13px] items-center">
            <Skeleton className="h-[9px] w-[60%]" />
          </div>
        </>
      ) : (
        <>
          <div
            aria-labelledby={`page-stat-${stat.key}-label`}
            className={cn(
              "mt-1 flex h-6 items-baseline gap-[5px] whitespace-nowrap text-[22px] font-bold leading-none tracking-[-.6px]",
              measured ? TONE_VALUE[tone] : "text-ink-300",
            )}
          >
            <span>{measured ? stat.value : NO_VALUE}</span>
            {/* The unit lives or dies with the number. See the file comment: a currency printed
                beside a dash quotes a price for a figure nobody ever measured. */}
            {measured && stat.unit !== undefined && stat.unit !== "" && (
              <u className="text-[11px] font-medium tracking-[-.2px] text-ink-400 no-underline">
                {stat.unit}
              </u>
            )}
          </div>

          {/* Only under the dash. A measured figure explains itself; an absent one cannot, and
              this caption is the sentence that says why it is absent. */}
          {!measured && stat.reason !== undefined && stat.reason !== "" && (
            <div className="mt-[3px] text-[11px] font-normal leading-[1.2] text-ink-300">
              {stat.reason}
            </div>
          )}

          {/* The mirror of the line above, on the same row and never at the same time: what a
              MEASURED figure is made of. Dimmer than the value on purpose — it is the qualifier,
              not the answer, and a payments strip that gave equal weight to the money and the
              row count would be the strip this one replaced. */}
          {measured && stat.caption !== undefined && stat.caption !== "" && (
            <div className="mt-[3px] text-[11px] font-normal leading-[1.2] text-ink-400">
              {stat.caption}
            </div>
          )}
        </>
      )}
    </li>
  );
}

export function PageStats({ stats, isLoading = false }: PageStatsProps): JSX.Element {
  return (
    /*
     * `aria-busy` rides the LIST, not the individual tiles: it is one fetch that fills all of
     * them, and announcing four separate busy regions for one request is four interruptions
     * where the operator needed none. The same division `Skeleton`'s own comment describes —
     * the placeholder says nothing, the section that owns it carries the fact.
     */
    <ul
      aria-busy={isLoading}
      className="m-0 flex list-none flex-wrap items-stretch gap-3 p-0"
    >
      {stats.map((stat) => (
        <StatTile key={stat.key} stat={stat} isLoading={isLoading} />
      ))}
    </ul>
  );
}
