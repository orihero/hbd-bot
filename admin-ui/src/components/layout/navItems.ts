/**
 * The left rail's contents, as data — §11.2, in §11.2's order:
 *
 * > **Live · Orders · Users · Generations · Assets · Chat · Payments · Moderation ③** ───
 * > **Config · Audit · Admins**
 *
 * Three of those (Chat, Payments, Moderation) have no route and no endpoint on this build.
 * They are rendered anyway, visibly not-yet-enabled, because the information architecture is
 * a promise about where things will be: an operator who learns that Payments sits below
 * Assets keeps that knowledge when it arrives. Hiding them would move every item below them
 * on the day they ship.
 *
 * That is a different rule from §11.4's hiding, which is about ROLE. Audit and Admins carry
 * a `permission` and are genuinely absent for a role that cannot read them — an operator
 * must not discover their role by clicking, and every refusal writes an audit row.
 *
 * ## Two routes that are deliberately not in the rail
 *
 * `/generations/names` and `/retention` exist in `routes.tsx` and are NOT in §11.2's rail
 * enumeration. They are not added here: the rail is transcribed from the plan, not extended
 * by inference. Both are reachable from the ⌘K palette, which §11.2 calls "the single global
 * entry point", and `/generations/names` is additionally where the Generations screen links
 * for the strategy bake-off.
 *
 * ## Why an item names a ROUTE and not an href
 *
 * There is an unavoidable import cycle here: `routes.tsx` → `RootLayout` → `AppShell` →
 * `NavRail` → this file → `routes.tsx`. ESM tolerates a cycle as long as no binding is READ
 * while the modules are still evaluating, so nothing in this file may touch `ROUTES` at
 * module scope — `PRIMARY_NAV` would otherwise be built from an `undefined` import and every
 * `href` would be `undefined`. Storing the route NAME and resolving it during render is what
 * keeps that from happening, and it is why `navHref()` exists rather than a plain field.
 */

import {
  Activity,
  ClipboardList,
  Coins,
  CreditCard,
  Flag,
  MessageSquare,
  Music,
  ScrollText,
  SlidersHorizontal,
  Sparkles,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Permission } from "@/api";
import { ROUTES, type RouteName } from "@/routes";

export interface NavItem {
  readonly key: string;
  /** Our own chrome label. Never user content. */
  readonly label: string;
  /** `null` when the section has no route on this build. */
  readonly route: RouteName | null;
  readonly icon: LucideIcon;
  /** The §12.2 permission the section needs, when it needs one. */
  readonly permission?: Permission;
  /** `end` for `NavLink`: only `/` needs an exact match, or it is active everywhere. */
  readonly isExact?: boolean;
  /** Shown beside a not-yet-enabled item so the absence is explained, not mysterious. */
  readonly notYet?: string;
}

/**
 * Resolve an item's path. MUST be called during render, never at module scope — see the
 * cycle note above.
 */
export function navHref(item: NavItem): string | null {
  return item.route === null ? null : ROUTES[item.route];
}

/** Above the rule. The operational sections, in §11.2's order. */
export const PRIMARY_NAV: readonly NavItem[] = [
  { key: "live", label: "Live", route: "live", icon: Activity, isExact: true },
  { key: "orders", label: "Orders", route: "orders", icon: ClipboardList },
  { key: "users", label: "Users", route: "users", icon: Users },
  { key: "generations", label: "Generations", route: "generations", icon: Sparkles },
  /*
   * An ELEVENTH item §11.2's transcription does not have, and the one addition to the rail
   * this file allows itself — because `/vendors` is not a screen the plan forgot to list, it
   * is a screen for a table the plan predates. It sits after Generations because that is the
   * question it continues: Generations asks what the pipeline attempted, Vendors asks what
   * those attempts asked of a third party and what it cost.
   *
   * No `permission` field, deliberately: the routes behind it are guarded by
   * `DASHBOARD_READ`, which all four roles hold (§12.3 classes costs and latencies as
   * always-visible non-personal data). An item every role can reach needs no gate, and a
   * gate naming a permission nobody lacks is one a reader has to disprove.
   */
  { key: "vendors", label: "Vendors", route: "vendors", icon: Coins },
  { key: "assets", label: "Assets", route: "assets", icon: Music },
  { key: "chat", label: "Chat", route: null, icon: MessageSquare, notYet: "phase 3" },
  { key: "payments", label: "Payments", route: null, icon: CreditCard, notYet: "phase 3" },
  { key: "moderation", label: "Moderation", route: null, icon: Flag, notYet: "phase 3" },
];

/** Below the rule. The administrative sections. */
export const SECONDARY_NAV: readonly NavItem[] = [
  {
    key: "config",
    label: "Config",
    route: "config",
    icon: SlidersHorizontal,
    permission: "config.read",
  },
  { key: "audit", label: "Audit", route: "audit", icon: ScrollText, permission: "audit.read" },
  { key: "admins", label: "Admins", route: "admins", icon: UserCog, permission: "admin.read" },
];

/** The two groups, in render order, separated by §11.2's rule. */
export const NAV_GROUPS: readonly (readonly NavItem[])[] = [PRIMARY_NAV, SECONDARY_NAV];

/**
 * The same two groups with the name §11.2's own prose already gives them.
 *
 * The rail's docstring, and the plan's, call these "the operational sections" and "the
 * administrative sections"; the flat rail simply never wrote it down and drew a `───` where
 * the words would have gone. The reskin's rail indents each group's items beneath its label,
 * so the label became something to render rather than something to imply.
 *
 * This is presentation, not information architecture: the same eleven items in the same
 * order, the same rule between them, no new destination and no new grouping. The label is a
 * `<p>`, deliberately NOT a heading and NOT a list item — a screen reader already has the
 * `<nav aria-label="Sections">` landmark, and eleven items under two extra headings is more
 * structure to walk, not less.
 */
export interface NavSection {
  readonly key: string;
  /** Our own chrome label for the group. Hidden when the rail is collapsed to icons. */
  readonly label: string;
  readonly items: readonly NavItem[];
}

export const NAV_SECTIONS: readonly NavSection[] = [
  { key: "operations", label: "Operations", items: PRIMARY_NAV },
  { key: "administration", label: "Administration", items: SECONDARY_NAV },
];
