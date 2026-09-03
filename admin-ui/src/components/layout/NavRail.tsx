/**
 * The left rail — `--nav-w` (264px), collapsible to `--nav-w-collapsed` (76px), persisted
 * (§11.2).
 *
 * The widths are tokens, never literals, so the one place they change is `tokens.css`; both
 * are read through the `w-nav` / `w-nav-collapsed` utilities, whose NAMES are asserted in
 * `NavRail.test.tsx`. The collapsed state lives in `usePrefsStore`, which persists it: an
 * operator who works in a narrow window should not re-collapse the rail on every reload.
 *
 * Collapsed does not mean unlabelled. Each item keeps its accessible name and gains a
 * `title`, so a 76px rail is still navigable by screen reader and by hover. An icon-only rail
 * whose icons have no names is a rail only its author can use.
 *
 * Two kinds of absence, and they are not the same thing:
 *
 *  - **Role.** Audit and Admins sit behind a `PermissionGate` and are simply not rendered for
 *    a role that cannot read them (§11.4: hiding, not disabling).
 *  - **Phase.** Chat, Payments and Moderation have no route on this build. They ARE rendered,
 *    as non-interactive rows marked `phase 3`, so the IA does not reshuffle when they land.
 *
 * ## What the reskin changed, and what it did not
 *
 * The rail is now its own full-height surface with NO right border — `--surface-nav` against
 * the page ground plus a whisper of shadow is the whole separation — and each group's items
 * are indented beneath a plain section label instead of floating either side of a bare rule.
 * §11.2's rule between the operational and the administrative sections is still drawn,
 * because it is the thing that says these are two kinds of screen and not eleven of one.
 *
 * The ACTIVE item is a filled pill in `--brand-tint` with `--brand` text and a `--brand` icon.
 * §11.3's "never colour alone" is still honoured, and by three channels rather than one: the
 * pill's ground APPEARS (a shape, not a hue), the label goes semibold, and the link carries
 * `aria-current="page"` for anything that cannot see either. The old 2px violet bar is gone
 * with the border-heavy language it belonged to; the pill replaces it as the second channel.
 */

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router-dom";

import { PermissionGate } from "@/components/util";
import { buttonVariants, segmentVariant } from "@/components/util";
import { usePrefsStore } from "@/lib/stores";
import { cn } from "@/lib/utils";

import { NAV_SECTIONS, navHref, type NavItem, type NavSection } from "./navItems";

interface RowProps {
  readonly item: NavItem;
  readonly isCollapsed: boolean;
}

function NavRow({ item, isCollapsed }: RowProps) {
  const Icon = item.icon;
  // Resolved HERE, during render, and never at module scope: see the cycle note in
  // `navItems.ts`.
  const to = navHref(item);

  const shared = cn(
    "group relative flex h-10 items-center justify-start gap-3 rounded-button px-3",
    "transition-colors duration-fast ease-standard",
    isCollapsed && "justify-center px-0",
  );

  if (to === null) {
    return (
      <li>
        <span
          aria-disabled="true"
          title={`${item.label} — not in this build (${item.notYet ?? "later"})`}
          className={cn(shared, "cursor-default text-ink-muted")}
        >
          <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
          {isCollapsed ? (
            <span className="sr-only">
              {item.label} — not in this build ({item.notYet ?? "later"})
            </span>
          ) : (
            <>
              <span className="type-body-sm truncate">{item.label}</span>
              {/*
               * "not yet" is said in WORDS, not by dimming. A greyed-out row would be exactly
               * the unexplained affordance §11.4 rejects, and the muted tokens that could
               * draw one (`--ink-mark`, `--ink-rule`) are policed for precisely that reason.
               * The chip is the signal; `--ink-muted` clears AA on every ground it can land
               * on, so the row reads as "later", not as "broken".
               */}
              <span
                className={cn(
                  "type-caption ml-auto shrink-0 rounded-pill bg-surface-control px-2 py-0.5",
                  "text-ink-muted",
                )}
              >
                {item.notYet ?? "later"}
              </span>
            </>
          )}
        </span>
      </li>
    );
  }

  return (
    <li>
      <NavLink
        to={to}
        end={item.isExact ?? false}
        title={isCollapsed ? item.label : undefined}
        className={({ isActive }) =>
          /*
           * The rail is where this console's active/inactive pairing was already right, and
           * it is now the same pairing every tab strip and toggle group uses: ACTIVE is the
           * secondary idiom (the brand tint with the brand as the label), INACTIVE is
           * `quiet` — `--ink-muted` with no ground until hover. `segmentVariant` is the one
           * place that choice is made.
           */
          cn(buttonVariants({ variant: segmentVariant(isActive), size: "none" }), shared)
        }
      >
        {({ isActive }) => (
          <>
            <Icon
              aria-hidden="true"
              className={cn("h-4 w-4 shrink-0", isActive && "text-brand-fill")}
            />
            {isCollapsed ? (
              <span className="sr-only">{item.label}</span>
            ) : (
              <span className={cn("type-body-sm truncate", isActive && "font-semibold")}>
                {item.label}
              </span>
            )}
          </>
        )}
      </NavLink>
    </li>
  );
}

function NavGroup({ section, isCollapsed }: { section: NavSection; isCollapsed: boolean }) {
  return (
    <div className="flex flex-col">
      {/*
       * A plain section label set ABOVE the items, not a heading and not a list item — see
       * the note on `NAV_SECTIONS`.
       *
       * Sentence case, deliberately. `.type-caption` would have been the obvious class and
       * it uppercases; this design's own rule for a section label is "sentence case, never
       * uppercase micro-caps", and the fact that these two words are ours rather than a
       * customer's makes the transform permitted, not appropriate.
       */}
      {isCollapsed ? null : (
        <p className="type-body-sm px-3 pb-2 font-semibold text-ink-muted">{section.label}</p>
      )}
      <ul className={cn("flex flex-col gap-1", isCollapsed ? "px-2" : "pl-2 pr-0")}>
        {section.items.map((item) =>
          item.permission === undefined ? (
            <NavRow key={item.key} item={item} isCollapsed={isCollapsed} />
          ) : (
            <PermissionGate key={item.key} permission={item.permission}>
              <NavRow item={item} isCollapsed={isCollapsed} />
            </PermissionGate>
          ),
        )}
      </ul>
    </div>
  );
}

/**
 * `noUncheckedIndexedAccess` means `NAV_SECTIONS[0]` is possibly `undefined`. An empty
 * section renders nothing, which is the honest fallback for a table that would have to have
 * been emptied at module scope for this to happen at all.
 */
const EMPTY_SECTION: NavSection = { key: "none", label: "", items: [] };

export function NavRail() {
  const isCollapsed = usePrefsStore((state) => state.isNavCollapsed);
  const toggleNav = usePrefsStore((state) => state.toggleNav);

  return (
    <nav
      aria-label="Sections"
      data-collapsed={isCollapsed ? "true" : "false"}
      className={cn(
        "flex shrink-0 flex-col bg-surface-nav shadow-xs",
        "transition-[width] duration-base ease-standard",
        isCollapsed ? "w-nav-collapsed" : "w-nav",
      )}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 py-5">
        <NavGroup section={NAV_SECTIONS[0] ?? EMPTY_SECTION} isCollapsed={isCollapsed} />
        {/* §11.2's `───` between the operational and the administrative sections. */}
        <hr className="mx-3 border-hairline" />
        <NavGroup section={NAV_SECTIONS[1] ?? EMPTY_SECTION} isCollapsed={isCollapsed} />
      </div>

      <div className={cn("p-3", isCollapsed && "flex justify-center")}>
        <button
          type="button"
          onClick={toggleNav}
          aria-expanded={!isCollapsed}
          aria-label={isCollapsed ? "Expand the sections rail" : "Collapse the sections rail"}
          className={cn(
            buttonVariants({ variant: "quiet", size: "none" }),
            "h-10 justify-start gap-3 px-3",
            isCollapsed ? "w-10 justify-center px-0" : "w-full",
          )}
        >
          {isCollapsed ? (
            <PanelLeftOpen aria-hidden="true" className="h-4 w-4" />
          ) : (
            <PanelLeftClose aria-hidden="true" className="h-4 w-4" />
          )}
          {isCollapsed ? null : <span className="type-body-sm">Collapse</span>}
        </button>
      </div>
    </nav>
  );
}
