/**
 * The bar across the top of every authenticated screen.
 *
 * ## Why it exists at all
 *
 * The vendor balances used to live in `DashboardPage`'s own header, which meant they were on
 * one of seven screens: an operator reading `/generations` at two in the morning could not see
 * that ElevenLabs was about to run out without navigating away from what they were doing. A
 * balance is not a property of the dashboard, it is a property of the deployment, so it
 * belongs to the shell — the same argument `NavRail`'s docstring already makes about the
 * signed-in identity and Sign out ("they are page chrome, not a property of the dashboard").
 *
 * The dashboard keeps its own strip. That is a deliberate duplication and not an oversight:
 * the strip is wide, names each vendor in words, and sits in a header the operator is reading
 * top-to-bottom; the pills here are compact, name the vendor with a mark, and are read out of
 * the corner of an eye. They share one query (`useHeaderBalances`), so they cannot disagree.
 *
 * ## What is in it, left to right
 *
 * Nothing, then everything: the bar is right-aligned, because the left is where each screen's
 * own `<h1>` already sits a few pixels below and two titles stacked in a column is a page
 * that looks like it lost a heading. The controls are the deployment's state and the
 * operator's own preferences, in that order — balances, language, palette. The language
 * control moved here from the nav rail's footer, where a preference had been sitting among
 * the destinations.
 *
 * ## Sticky above `lg`, static below it
 *
 * `NavRail` becomes a horizontal bar pinned at `top-0` on narrow viewports, and two elements
 * pinned to the same edge is one covering the other. So this bar pins only where the rail is
 * a column (`lg:sticky lg:top-3`); on a phone it scrolls away with the page, which is the
 * right trade for a viewport where the rail is already spending a strip of height.
 */

import type { JSX } from "react";
import { Moon, Sun } from "lucide-react";

import { BalancePill } from "@/components/BalancePill";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Skeleton } from "@/components/Skeleton";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useThemeStore } from "@/state/theme";

import { useHeaderBalances } from "./useHeaderBalances";

/**
 * An OUTLINE, not a `ring` — the form `NavRail` and `Segmented` already use, and for their
 * reason: an outline is painted outside the layout box and survives an ancestor's overflow.
 */
const FOCUS_RING =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep";

/** One round control in the bar. The ground appears on hover; there is no resting border. */
const ICON_BUTTON = cn(
  "grid h-9 w-9 shrink-0 place-items-center rounded-full text-ink-500 transition",
  "hover:bg-row-hover hover:text-ink-900",
  FOCUS_RING,
);

/**
 * The palette switch.
 *
 * A two-state button over a three-state store: the label says what it will DO, not what the
 * store holds, because "System" on a face is a word an operator has to decode before they can
 * predict the click. Picking either side stops the console following the machine — see
 * `state/theme.ts` on why that is the right default and the wrong permanent state.
 */
function ThemeToggle(): JSX.Element {
  const { t } = useI18n();
  const resolved = useThemeStore((state) => state.resolved);
  const toggle = useThemeStore((state) => state.toggle);
  const isDark = resolved === "dark";
  const Icon = isDark ? Sun : Moon;
  /* The face says what the click will DO. Two keys rather than one with a `{palette}` hole:
     Russian and Uzbek both inflect the noun after the verb, and a slot would have to be filled
     with a word in the wrong case. */
  const label = isDark ? t("common.switchToLight") : t("common.switchToDark");

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className={ICON_BUTTON}
    >
      <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
    </button>
  );
}

/** The bar's own quiet pill, for the two states that are a sentence rather than a figure. */
function Note({ children, title }: { readonly children: string; readonly title?: string }): JSX.Element {
  return (
    <div
      title={title}
      className="flex h-9 items-center rounded-chip px-3 text-xs font-medium text-ink-400"
    >
      {children}
    </div>
  );
}

/**
 * The balances, in whichever of the four states they are in.
 *
 * The three absences are drawn differently on purpose (see `useHeaderBalances`): a skeleton
 * for a read in flight, a fault sentence for one that failed with nothing cached, and a quiet
 * one for a deployment that polls no vendor — which is a supported configuration, not a
 * problem, and must not be coloured like one.
 */
function Balances(): JSX.Element {
  const { t } = useI18n();
  const { chips, isUnavailable } = useHeaderBalances();

  if (isUnavailable) return <Note>{t("dashboard.balances.unavailable")}</Note>;
  if (chips === undefined) {
    // Two, because two is what a configured deployment almost always has: the bar does not
    // resize under its own first answer.
    return (
      <div className="flex items-center gap-2">
        <Skeleton className="h-9 w-[124px] rounded-chip" />
        <Skeleton className="h-9 w-[124px] rounded-chip" />
      </div>
    );
  }
  if (chips.length === 0) {
    return (
      <Note title={t("dashboard.balances.notPolledTitle")}>
        {t("dashboard.balances.notPolled")}
      </Note>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {chips.map((chip) => (
        <BalancePill key={chip.key} chip={chip} />
      ))}
    </div>
  );
}

export function TopBar(): JSX.Element {
  return (
    <header
      className={cn(
        "z-20 mx-3 mt-3 flex min-h-[56px] flex-wrap items-center justify-end gap-2",
        "rounded-panel bg-card px-3 py-2",
        "lg:sticky lg:top-3",
      )}
    >
      <Balances />
      {/* The two operator preferences, together at the end of the bar. Both are rows of round
          controls at the same 36px, so the pair reads as one group rather than as a widget
          that wandered in from the sidebar — which is where the language control used to be. */}
      <LanguageSwitcher />
      <ThemeToggle />
    </header>
  );
}
