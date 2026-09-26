/**
 * The four tabs, and the one query parameter that says which is open.
 *
 * ## Why tabs and not one scroll
 *
 * The page carries about eleven figures now. The recorded constraint on this console caps a
 * page at six and names "sections as real tabs" as the resolution, and the reason is not
 * tidiness: every drawing here is a 651-unit viewBox scaled to its column, so a figure below
 * the fold is not merely unread, it is a live query polling on a cadence for a picture nobody
 * is looking at. A tab gives each section its own allocation of the page AND its own
 * allocation of the API — the sections that are not open are unmounted, and their reads go
 * inactive with them. That matters most for the identified lists, which write an audit row per
 * call: a scroll would have read customer identities on every visit to the dashboard.
 *
 * ## Why links and not buttons
 *
 * The open tab is in the URL, so it survives a refresh and can be pasted to a colleague — and
 * a thing that changes the URL is a link. Rendering it as a `<button>` that calls
 * `setSearchParams` would look identical and would silently drop middle-click, ctrl-click and
 * "copy link address", which is how an operator actually shares "look at the vendor tab".
 *
 * The default tab writes NO parameter, matching how every other screen in this app spells an
 * absent value (`?provider=` is a filter matching nothing): `/` is Audience, and only a tab
 * the operator moved to appears in the address bar. An unrecognised value reads as the
 * default rather than as an error — a hand-edited or outdated link lands somewhere real.
 */

import type { JSX } from "react";
import { Link } from "react-router-dom";

import { PATH } from "@/app/paths";
import type { SectionKey } from "@/features/dashboard/cardSpecs";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";

/** The parameter name, in one place, so the reader and the writer cannot drift. */
export const TAB_PARAM = "tab";

/** The tab the page opens on, and the one that writes no parameter. */
export const DEFAULT_TAB: SectionKey = "audience";

/** Tab order, which is also the order the sections are meant to be read in. */
const TABS: readonly { readonly key: SectionKey; readonly labelKey: TranslationPath }[] = [
  { key: "audience", labelKey: "dashboard.groups.audience" },
  { key: "finance", labelKey: "dashboard.groups.finances" },
  { key: "vendor", labelKey: "dashboard.groups.vendor" },
  { key: "performance", labelKey: "dashboard.groups.performance" },
];

function isSectionKey(value: string): value is SectionKey {
  return TABS.some((tab) => tab.key === value);
}

/** The open tab, from the URL. Anything unrecognised — or absent — is the default. */
export function readTab(params: URLSearchParams): SectionKey {
  const raw = params.get(TAB_PARAM);
  return raw !== null && isSectionKey(raw) ? raw : DEFAULT_TAB;
}

/** The address one tab lives at. The default tab is the bare path, with no parameter. */
export function tabPath(tab: SectionKey): string {
  return tab === DEFAULT_TAB ? PATH.dashboard : `${PATH.dashboard}?${TAB_PARAM}=${tab}`;
}

/**
 * The tab strip, styled as the `Segmented` control's `main` variant.
 *
 * Not `Segmented` itself: that component renders `<button aria-pressed>`, and these are links.
 * The classes are copied deliberately rather than shared, because the day the picker's styling
 * changes is not necessarily the day this strip should follow it.
 */
export function SectionTabs({ tab }: { readonly tab: SectionKey }): JSX.Element {
  const { t } = useI18n();

  return (
    <nav aria-label={t("dashboard.sectionTabsAria")} className="flex h-8 gap-[2px] rounded-chip bg-card p-[3px]">
      {TABS.map((entry) => {
        const on = entry.key === tab;
        return (
          <Link
            key={entry.key}
            to={tabPath(entry.key)}
            /* `page` rather than `true`: this link addresses a page, and `aria-current="page"`
               is what a screen reader announces as "current page" instead of just "current". */
            aria-current={on ? "page" : undefined}
            className={cn(
              "flex items-center rounded-chip px-3 text-xs font-semibold leading-none tracking-[-.24px] no-underline transition-[color,background-color,filter]",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
              on
                ? "bg-accent text-ink-900 hover:brightness-95 active:brightness-90"
                : "text-ink-400 hover:text-ink-900 active:text-ink-900",
            )}
          >
            {t(entry.labelKey)}
          </Link>
        );
      })}
    </nav>
  );
}
