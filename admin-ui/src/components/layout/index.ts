/**
 * §11.4's Layout inventory: `AppShell`, `NavRail`, `TopBar`, `CommandPalette`, `PageHeader`,
 * `PlayerBar` — plus the top bar's three pieces, which are separate files because each has
 * its own reason to change (§11.2's env rule, §11.5's freshness rule, §12.2's role display).
 *
 * Import from `@/components/layout`, not from the files.
 */

export { AppShell, type AppShellProps } from "./AppShell";
export { AccountMenu } from "./AccountMenu";
export { breadcrumbTrail, type Crumb } from "./breadcrumbs";
export { CommandPalette } from "./CommandPalette";
export {
  BARE_HEX32_PATTERN,
  ROUTE_ENTRIES,
  TELEGRAM_ID_PATTERN,
  UUID_PATTERN,
  dashUuid,
  resolvePalette,
  type PaletteResult,
  type PaletteResultKind,
} from "./paletteResolve";
export { EnvBadge, type EnvBadgeProps } from "./EnvBadge";
export { LiveHeartbeatPill, LivePill, type LivePillProps } from "./LivePill";
export { useLiveHeartbeat } from "./useLiveHeartbeat";
export { NavRail } from "./NavRail";
export {
  NAV_GROUPS,
  NAV_SECTIONS,
  PRIMARY_NAV,
  SECONDARY_NAV,
  navHref,
  type NavItem,
  type NavSection,
} from "./navItems";
export { PageHeader, type PageHeaderProps } from "./PageHeader";
export { PlayerBar } from "./PlayerBar";
export { TopBar } from "./TopBar";
