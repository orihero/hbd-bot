/**
 * The left rail.
 *
 * ## Where the look comes from
 *
 * The PlanIQ kit has no sidebar. Its dashboard navigates from a HORIZONTAL pill bar
 * (.openpencil-export/navbar-light.jsx, node 0:7758), so this file is a translation rather
 * than a transcription. What is carried over verbatim is the part that makes it recognisably
 * the same product as the sign-in screen: the white card ground on the #F6F6F6 page, the
 * generous radius, the 40px mark + wordmark lockup, and — exactly — the item itself:
 *
 *     active    bg #75FC96, radius 26, Manrope 12/500, line-height 16.392, tracking -0.36
 *     inactive  transparent ground, same type, same metrics
 *
 * The kit paints BOTH states' label #000000. That is legible across six items in a row; down
 * a column of ten it leaves the green pill doing all the work of saying where you are, so an
 * inactive label is toned to --ink-500 and comes back to --ink-900 on hover. That is the only
 * colour decision here the kit did not make. The kit also gives its items no hover, focus or
 * disabled treatment at all — a nav that cannot be seen under a keyboard is not a nav, so
 * those are added, in the same idiom `components/Segmented.tsx` already uses.
 *
 * ## Two layouts, not one
 *
 * Below 1024px the rail does not narrow — it becomes the kit's own horizontal pill bar again,
 * scrolled sideways, pinned to the top. Narrowing was the other option and it is worse here:
 * a 76px icon column out of a 375px viewport is a fifth of the screen spent on chrome, and
 * the dashboard's stat rows are already the tightest thing on the page. Going horizontal
 * costs one strip of height, keeps every label readable, and is the shape the design was
 * drawn in to begin with. `useIsCompact` is a real media-query subscription rather than a CSS
 * duplicate of the markup so a section is in the DOM once and there is one focus order.
 *
 * ## The footer
 *
 * The signed-in identity and Sign out live here, not on the dashboard header. They are page
 * chrome, not a property of the dashboard: the second screen would otherwise either duplicate
 * them or silently drop the only way out of a session. `DashboardPage` still renders its own
 * copy at the time of writing — that one goes.
 *
 * The language control USED to sit above the identity, in both layouts. It is in `TopBar` now,
 * beside the palette toggle: the rail answers "where can I go", and a preference is not a
 * destination. Keeping it here also meant maintaining two more presentation variants of one
 * control for two widths of one sidebar.
 */

import {
  Fragment,
  useCallback,
  useEffect,
  useState,
  useSyncExternalStore,
  type JSX,
} from "react";
import { LogOut, Lock, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router-dom";

import { NAV_SECTIONS, type NavItem, type NavSection } from "@/app/navItems";
import { BrandMark } from "@/components/icons";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/state/auth";

/** Matches the `lg` breakpoint Tailwind uses elsewhere in this app. */
const COMPACT_QUERY = "(max-width: 1023.98px)";

const COLLAPSED_KEY = "hbd.dashboard.navRailCollapsed";

/** The kit's item metrics, to the decimal. Shared by every item in both layouts. */
const ITEM_TYPE = "font-sans text-xs font-medium leading-[16.392px] tracking-[-0.36px]";

/**
 * An OUTLINE, not a `ring`. A ring is a box-shadow, and both scrollers here clip it: setting
 * `overflow-y: auto` on the wide rail's item column computes `overflow-x` to `auto` too, so a
 * full-width item's ring loses its left and right edges, and the compact bar's horizontal
 * scroller does the same top and bottom. An outline is painted outside the layout box and is
 * not clipped by an ancestor's overflow — the form `components/Segmented.tsx` already uses.
 */
const FOCUS_RING =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    // Storage can be denied outright (private mode, blocked site data). An expanded rail is
    // a fine outcome; failing to render the nav is not.
    return false;
  }
}

function writeCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    /* see readCollapsed */
  }
}

/**
 * True below 1024px. `useSyncExternalStore` rather than an effect + state so the first paint
 * is already the right layout — a resize-driven effect renders the wide rail for one frame on
 * every phone load.
 */
function useIsCompact(): boolean {
  const [query] = useState(() => window.matchMedia(COMPACT_QUERY));

  const subscribe = useCallback(
    (onChange: () => void) => {
      query.addEventListener("change", onChange);
      return () => {
        query.removeEventListener("change", onChange);
      };
    },
    [query],
  );

  return useSyncExternalStore(subscribe, () => query.matches);
}

/** Two letters off the username. Never an image: `admin_users` has no avatar column. */
function initialsOf(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

function BrandLockup({ compact }: { readonly compact: boolean }): JSX.Element {
  return (
    <span className="flex select-none items-center gap-3">
      <BrandMark className="h-10 w-10 shrink-0" />
      {compact ? null : (
        <span className="font-wordmark text-[18.89px] font-medium leading-[26.44px] text-wordmark">
          hbd
        </span>
      )}
    </span>
  );
}

/**
 * One row of the rail.
 *
 * A section with no route is NOT a link with a swallowed click — it is a `<span>` with
 * `aria-disabled`, so it never enters the tab order and never lands in a screen reader's link
 * list as a destination that does not exist. The reason rides along three ways: the `title`
 * for a mouse, the padlock for an eye, and an `sr-only` sentence appended to the accessible
 * name, because a `title` on a non-interactive element is not reliably announced.
 */
function RailItem({
  item,
  collapsed,
}: {
  readonly item: NavItem;
  readonly collapsed: boolean;
}): JSX.Element {
  const { t } = useI18n();
  const Icon = item.icon;
  const notYet = item.notYetKey === undefined ? undefined : t(item.notYetKey);
  const shape = cn(
    "group relative flex w-full items-center rounded-panel py-[10px] transition-colors",
    ITEM_TYPE,
    collapsed ? "justify-center px-0" : "gap-3 px-4",
  );

  const label = (
    <>
      <span className={cn(collapsed && "sr-only")}>{t(item.labelKey)}</span>
      {notYet === undefined ? null : <span className="sr-only"> — {notYet}</span>}
    </>
  );

  if (item.href === null) {
    return (
      <li>
        <span
          aria-disabled="true"
          title={notYet}
          className={cn(shape, "cursor-not-allowed text-ink-300")}
        >
          <Icon className="h-[18px] w-[18px] shrink-0 opacity-60" strokeWidth={1.75} aria-hidden />
          {label}
          {collapsed ? null : (
            <Lock className="ml-auto h-3 w-3 shrink-0 opacity-70" strokeWidth={2} aria-hidden />
          )}
        </span>
      </li>
    );
  }

  return (
    <li>
      <NavLink
        to={item.href}
        end={item.isExact === true}
        title={collapsed ? t(item.labelKey) : undefined}
        className={({ isActive }) =>
          cn(
            shape,
            FOCUS_RING,
            isActive
              ? "bg-accent text-ink-800 hover:brightness-95"
              : "text-ink-500 hover:bg-bg hover:text-ink-900",
          )
        }
      >
        <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
        {label}
      </NavLink>
    </li>
  );
}

function RailSection({
  section,
  collapsed,
}: {
  readonly section: NavSection;
  readonly collapsed: boolean;
}): JSX.Element {
  const { t } = useI18n();

  return (
    <div>
      {collapsed ? null : (
        <p className="mb-1 px-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
          {t(section.labelKey)}
        </p>
      )}
      <ul className="m-0 flex list-none flex-col gap-[2px] p-0">
        {section.items.map((item) => (
          <RailItem key={item.key} item={item} collapsed={collapsed} />
        ))}
      </ul>
    </div>
  );
}

/**
 * Whose session this is, and the only way out of it.
 *
 * Without a visible identity a stale session on a shared machine looks exactly like a fresh
 * one, and the cookie is server-TTL'd — closing the tab does not end it.
 *
 * Three shapes for three grounds: the expanded rail's footer has room for name and role, the
 * collapsed rail's 52px of usable width has room for one control at a time, and the compact
 * bar has height for one row and no more.
 */
type IdentityVariant = "full" | "stacked" | "inline";

function Identity({ variant }: { readonly variant: IdentityVariant }): JSX.Element | null {
  const { t } = useI18n();
  const account = useAuthStore((state) => state.account);
  const signOut = useAuthStore((state) => state.signOut);

  if (account === null) return null;

  const compact = variant !== "full";

  const signOutButton = (
    <button
      type="button"
      onClick={() => {
        // The store clears this tab whatever the API answers, and RequireAuth takes it to
        // /login the moment `status` flips.
        void signOut();
      }}
      title={t("nav.footer.signOut")}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-panel text-ink-500 transition-colors hover:bg-bg hover:text-ink-900",
        FOCUS_RING,
        compact ? "h-9 w-9" : "h-8 w-8",
      )}
    >
      <LogOut className="h-4 w-4" strokeWidth={1.75} aria-hidden />
      <span className="sr-only">{t("nav.footer.signOut")}</span>
    </button>
  );

  if (compact) {
    return (
      <div
        className={cn(
          "flex items-center gap-1",
          variant === "stacked" ? "flex-col gap-2" : "flex-row",
        )}
      >
        <span
          title={`${account.username} · ${account.role}`}
          className="grid h-9 w-9 place-items-center rounded-full bg-accent text-[11px] font-bold text-on-accent"
        >
          <span aria-hidden>{initialsOf(account.username)}</span>
          <span className="sr-only">
            {t("nav.footer.signedInAs", { username: account.username, role: account.role })}
          </span>
        </span>
        {signOutButton}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 px-1">
      <span
        aria-hidden
        className="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-full bg-accent text-xs font-bold text-on-accent"
      >
        {initialsOf(account.username)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold leading-[18px] tracking-[-0.32px] text-ink-800">
          {account.username}
        </span>
        <span className="block truncate text-xs font-normal leading-[16.392px] tracking-[-0.24px] text-ink-300">
          {account.role}
        </span>
        <span className="sr-only">{t("nav.footer.signedIn")}</span>
      </span>
      {signOutButton}
    </div>
  );
}

/** The wide layout: a white card pinned to the left, the page scrolling beside it. */
function WideRail(): JSX.Element {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(readCollapsed);

  // The persist is OUTSIDE the updater: an updater must be pure, React may call it twice for
  // one dispatch (StrictMode does, in development), and this is the shape that quietly
  // corrupts state the moment the effect stops being idempotent.
  const toggle = useCallback(() => {
    setCollapsed((prev) => !prev);
  }, []);

  useEffect(() => {
    writeCollapsed(collapsed);
  }, [collapsed]);

  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;
  const toggleLabel = collapsed
    ? t("nav.footer.expandSidebar")
    : t("nav.footer.collapseSidebar");

  return (
    <nav
      aria-label={t("nav.sections")}
      className={cn(
        "sticky top-3 m-3 mr-0 flex h-[calc(100vh-1.5rem)] shrink-0 flex-col rounded-panel bg-card p-3 transition-[width]",
        collapsed ? "w-[76px]" : "w-[248px]",
      )}
    >
      <div className={cn("flex items-center gap-2", collapsed ? "flex-col" : "justify-between px-1")}>
        <BrandLockup compact={collapsed} />
        {/* The name flips, so there is no `aria-pressed`: the two conventions are mutually
            exclusive, and together a collapsed rail announced "Expand the sidebar … pressed",
            which reads as the expand action being the active one. */}
        <button
          type="button"
          onClick={toggle}
          title={toggleLabel}
          className={cn(
            "grid h-8 w-8 shrink-0 place-items-center rounded-panel text-ink-400 transition-colors hover:bg-bg hover:text-ink-900",
            FOCUS_RING,
          )}
        >
          <ToggleIcon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
          <span className="sr-only">{toggleLabel}</span>
        </button>
      </div>

      {/* The rail owns the overflow: ten items plus a footer do not fit a 600px-tall laptop
          window, and a footer pushed below the fold takes Sign out with it. */}
      <div className="mt-5 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        {NAV_SECTIONS.map((section, index) => (
          <div key={section.key} className="flex flex-col gap-4">
            {index === 0 ? null : <hr className="m-0 border-0 border-t border-stroke" />}
            <RailSection section={section} collapsed={collapsed} />
          </div>
        ))}
      </div>

      <div
        className={cn(
          "mt-3 flex shrink-0 flex-col gap-3 border-t border-stroke pt-3",
          collapsed && "items-center",
        )}
      >
        <Identity variant={collapsed ? "stacked" : "full"} />
      </div>
    </nav>
  );
}

/**
 * The compact layout: the kit's horizontal pill bar, back in its original orientation.
 *
 * The rule between the two groups becomes a vertical hairline in the scroller — the same
 * separation, rotated with everything else. No collapse toggle: there is nothing to collapse
 * into, and a control that only appears above 1024px is one an operator learns twice.
 */
function CompactBar(): JSX.Element {
  const { t } = useI18n();

  return (
    <nav
      aria-label={t("nav.sections")}
      className="sticky top-0 z-30 m-3 mb-0 flex items-center gap-3 rounded-panel bg-card px-3 py-2"
    >
      <BrandLockup compact />
      <div className="min-w-0 flex-1 overflow-x-auto">
        <ul className="m-0 flex list-none items-center gap-1 p-0">
          {NAV_SECTIONS.map((section, index) => (
            <Fragment key={section.key}>
              {index === 0 ? null : (
                <li aria-hidden className="mx-1 h-5 w-px shrink-0 bg-stroke" />
              )}
              {section.items.map((item) => (
                <CompactItem key={item.key} item={item} />
              ))}
            </Fragment>
          ))}
        </ul>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Identity variant="inline" />
      </div>
    </nav>
  );
}

function CompactItem({ item }: { readonly item: NavItem }): JSX.Element {
  const { t } = useI18n();
  const Icon = item.icon;
  const notYet = item.notYetKey === undefined ? undefined : t(item.notYetKey);
  const shape = cn(
    "flex shrink-0 items-center gap-2 whitespace-nowrap rounded-panel px-4 py-[10px]",
    ITEM_TYPE,
  );

  if (item.href === null) {
    return (
      <li>
        <span aria-disabled="true" title={notYet} className={cn(shape, "text-ink-300")}>
          <Icon className="h-[18px] w-[18px] opacity-60" strokeWidth={1.75} aria-hidden />
          {t(item.labelKey)}
          {notYet === undefined ? null : <span className="sr-only"> — {notYet}</span>}
        </span>
      </li>
    );
  }

  return (
    <li>
      <NavLink
        to={item.href}
        end={item.isExact === true}
        className={({ isActive }) =>
          cn(
            shape,
            FOCUS_RING,
            isActive ? "bg-accent text-ink-800" : "text-ink-500 hover:bg-bg hover:text-ink-900",
          )
        }
      >
        <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
        {t(item.labelKey)}
      </NavLink>
    </li>
  );
}

export function NavRail(): JSX.Element {
  return useIsCompact() ? <CompactBar /> : <WideRail />;
}
