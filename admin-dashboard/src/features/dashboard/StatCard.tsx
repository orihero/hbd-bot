import { useMemo, type JSX } from "react";

import type { ComponentState } from "@/api/dashboard";
import { Segmented, type SegmentedOption } from "@/components/Segmented";
import { Skeleton } from "@/components/Skeleton";
import { Sparkline } from "@/components/Sparkline";
import { unavailableKey, type CardValue } from "@/features/dashboard/adapt";
import type { CardSpec } from "@/features/dashboard/cardSpecs";
import { MINI_KEY, PERIODS, type Period } from "@/features/dashboard/data";
import { dirOf } from "@/features/dashboard/svg";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * Three states, three tones. A `degraded` component is "we asked and the vendor refused" and
 * `not_probed` is "nothing has ever looked" — painting both grey and titling both "not
 * probed" reported every fault as the more benign of the two.
 */
const STATE_DOT: Record<ComponentState, string> = {
  ok: "bg-accent-deep",
  degraded: "bg-required",
  not_probed: "bg-d5",
};

const STATE_TITLE_KEY: Record<ComponentState, "dashboard.componentState.ok" | "dashboard.componentState.degraded" | "dashboard.componentState.notProbed"> = {
  ok: "dashboard.componentState.ok",
  degraded: "dashboard.componentState.degraded",
  not_probed: "dashboard.componentState.notProbed",
};

const DELTA_CLASS: Record<"" | "up" | "down", string> = {
  "": "",
  up: "text-accent-deep",
  down: "text-ink-400",
};

/**
 * What the mockup puts in the value slot of a card that has no value. It is not a number, and
 * wherever the wire named an absence it is not alone either: the caption under it names which
 * kind of absence this is, which is the whole reason the dash is allowed here at all. The
 * mockup drew that as a hatched pill; it is a line of small text here, and it is translated.
 */
const NO_VALUE = "—";

/*
 * The pill for a card whose section answered but said nothing about it is
 * `dashboard.unreported`. Not expected — every adapter fills all of its keys — so it is kept
 * as the honest fallback rather than left to render an unexplained dash if one ever stops.
 */

interface StatCardProps {
  /** Label, unit, fallback caption, delta polarity — presentation only, never a measurement. */
  readonly spec: CardSpec;
  /**
   * The adapter's value for this card: the numeric arm, the `{tag}` arm for something the wire
   * could not measure, or `undefined` while the section it comes from is still in flight.
   */
  readonly value: CardValue | undefined;
  /** True while this card's section has never answered. Drives the skeleton, not the pill. */
  readonly isLoading: boolean;
  /** THIS card's window, not the page's. Only cards with `sel` can be moved off the default. */
  readonly period: Period;
  /**
   * Moves this card and nothing else.
   *
   * The mockup wired the mini selector to a page-global period, so reading "new users this
   * year" dragged all eighteen cards and six charts into a year — an operator could not put
   * two windows beside each other, which is the one thing a per-card selector is for. The
   * page now keeps a period per card key and passes the matching setter here; a card whose
   * period differs from its neighbours' costs one extra read of its own section, and cards
   * left on the default still share a single request.
   */
  readonly onPeriodChange: (p: Period) => void;
}

export function StatCard({
  spec,
  value,
  isLoading,
  period,
  onPeriodChange,
}: StatCardProps): JSX.Element {
  const { t } = useI18n();
  const miniOptions = useMemo<readonly SegmentedOption<Period>[]>(
    () => PERIODS.map((p) => ({ value: p, label: t(MINI_KEY[p]) })),
    [t],
  );
  const label = t(`dashboard.cards.${spec.key}.label`);
  const pending = value === undefined && isLoading;

  /* The two arms, resolved once. A card the wire could not measure prints a dash and keeps
     its caption — printing "soʻm" beside that dash would quote a currency for a figure that
     does not exist, so the unit is dropped with the number. */
  const measured = value !== undefined && !("tag" in value) ? value : null;

  /* WHY THE DASH IS ALLOWED TO SPEAK.
     The rule this page is built on is that a number which could not be measured is absent and
     names its own reason — `adapt.ts` says it in its first paragraph, and the server says it
     twice over: `AbsenceReason` is a closed vocabulary whose entry test is that every member
     is something an operator can go and DO (publish a price, set an FX rate, start the poller).
     All of that machinery ended here, at the last inch, in a card that resolved the two arms
     and dropped the reason on the floor. What the deployment showed for Est. revenue, MRR and
     ARR was three bare em dashes over a server returning 200 and saying `no_price_published`
     and `no_fx_rate` — a blank that reads as "the panel is broken" rather than as one
     environment variable. A dash with nothing under it is not honesty about a missing figure;
     it is the same silence the null-is-not-zero rule exists to prevent, wearing a nicer glyph.
     `unavailableKey` returns null for a measured card and for an absence nobody named, so the
     caption appears exactly where the wire had something actionable to say. */
  const reasonKey = unavailableKey(value);
  const reason = reasonKey === null ? null : t(reasonKey);

  /* The adapter overrides the spec whenever the response knows something truer — today only
     a currency the spec did not assume. It used to override the CAPTION too, with one carrying
     the real denominators (`12 of 19 calls priced`); there is no caption to override now. */
  const unit = measured?.unit ?? spec.unit;
  const delta = measured?.delta ?? "";
  const dots = measured?.dots;
  const series = measured?.spark ?? [];

  return (
    <article aria-busy={pending} className="relative h-24 overflow-hidden rounded-card bg-card p-4">
      <div className="flex h-5 items-center justify-between">
        <span className="text-[11px] font-semibold tracking-[-.1px] text-ink-400">
          {label}
        </span>
        {spec.sel === true && (
          <Segmented
            options={miniOptions}
            value={period}
            onChange={onPeriodChange}
            variant="mini"
            ariaLabel={t("dashboard.cardPeriodAria", { label })}
          />
        )}
      </div>

      {pending ? (
        /* Sized to the rows they stand in — 32px of value, 13px of caption — so the card does
           not move a pixel when the number arrives. */
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
              "mt-1 flex items-baseline gap-[6px] whitespace-nowrap text-[32px] font-bold leading-none tracking-[-1.92px]",
              measured === null ? "text-ink-300" : "text-ink-800",
              /* The card is 96px tall with 16px of padding, and the rows inside it already
                 spend all 64px: 20 of header, 4 of gap, 32 of value, and the 3 + 13 of the
                 caption row below. A reason caption therefore cannot be added, only afforded,
                 and the 8px it is short comes out of the LINE BOX of the dash rather than out
                 of the dash. `leading-[24px]` on 32px type would clip an ascender or a
                 descender; the absent arm has neither, because its whole contents is one em
                 dash — a horizontal bar on the centre line, with no unit beside it (dropped
                 with the number) and no delta (the absent arm carries none). So the dash
                 renders at exactly the size and weight it always has, the header above it and
                 the card around it do not move, and the caption fits in the space the tighter
                 line gives back. A card with no reason to print keeps `leading-none` and is
                 pixel-for-pixel what it was. */
              reason === null ? "" : "leading-[24px]",
            )}
          >
            <span>{measured === null ? NO_VALUE : measured.value}</span>
            {measured !== null && unit !== "" && (
              <u className="text-[13px] font-medium tracking-[-.2px] text-ink-400 no-underline">
                {unit}
              </u>
            )}
            <em
              className={cn(
                "text-[11px] font-semibold not-italic tracking-[-.1px]",
                DELTA_CLASS[dirOf(delta, spec.invert)],
              )}
            >
              {delta}
            </em>
          </div>

          {/* The reason the figure above is a dash, in the reader's own language and in the
              row the dots would otherwise have used — the two can never collide, because dots
              are part of a MEASURED value and a reason only exists on the absent arm.
              `title` carries the full sentence: the Est. revenue card reserves 60px of its
              width for a sparkline well, which leaves a Russian caption enough room to be
              truncated, and an operator who cannot read the whole remedy can hover for it. */}
          {reason !== null && (
            <div
              title={reason}
              className={cn(
                "mt-[3px] overflow-hidden text-ellipsis whitespace-nowrap text-[11px] font-normal leading-[13px] text-ink-300",
                spec.spark === true && "pr-[66px]",
              )}
            >
              {reason}
            </div>
          )}

          {/* The caption that sat here — `ever contacted the bot`, `delivered × published
              price`, `net, annualised` — is gone from all eighteen cards: a title and a
              figure, and nothing between them and the next card. The row itself stays, and
              keeps its height, ONLY while it has dots to carry: those are the System status
              card's actual measurement rather than a sentence about one. */}
          {dots !== undefined && (
            <div className="mt-[3px] overflow-hidden text-ellipsis whitespace-nowrap text-[11px] font-normal leading-[1.2] text-ink-300">
              <span className="relative top-[-1px] mr-[7px] inline-flex gap-[3px] align-middle">
                {dots.map(([id, name, state]) => (
                  <i
                    key={id}
                    title={`${name} — ${t(STATE_TITLE_KEY[state])}`}
                    className={cn("inline-block h-[5px] w-[5px] rounded-full", STATE_DOT[state])}
                  />
                ))}
              </span>
            </div>
          )}
        </>
      )}

      {spec.spark === true && (
        <div className="absolute bottom-3 right-[14px] h-6 w-[60px]">
          {pending ? <Skeleton className="h-6 w-[60px]" /> : <Sparkline series={series} />}
        </div>
      )}
    </article>
  );
}
