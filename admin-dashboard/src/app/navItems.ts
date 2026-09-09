/**
 * The rail's contents, as data.
 *
 * Seven sections are listed, and every one of them is routed. Audit and Admins were the last
 * two to arrive and the prediction this file made about them held: the item did not move when
 * the screen shipped, because it had been sitting in its final place since before there was
 * anything behind it. That is the whole argument, and it is the same one
 * admin-ui/src/components/layout/navItems.ts makes at length — the information architecture
 * is a promise about WHERE a thing will be. An operator who learned that Audit sits at the
 * bottom, under a rule, kept that knowledge on the day Audit arrived. Hiding an unbuilt
 * section would instead have moved every remaining item on the day it shipped, and would have
 * left an operator who knows this product from admin-ui quietly wondering whether this console
 * had dropped half of it.
 *
 * Config was the one section that argument was still carrying, and it is gone from the rail
 * as of 2026-09-09 — not because the argument stopped holding, but because there is no plan
 * to build the screen here yet, and a permanently locked item is a promise nobody is keeping.
 * It comes back with the screen, at the top of `SECONDARY_NAV`. The rail still knows how to
 * render an unrouted section — `href: null` plus `notYetKey`, drawn as an `aria-disabled`
 * span with a padlock in `NavRail.tsx` — so re-adding it is one entry and two strings.
 *
 * Two differences from admin-ui's version of this file, both because this app is smaller:
 *
 *  - No `permission`. admin-ui hides Config/Audit/Admins from a role that cannot read them
 *    (§11.4) so nobody discovers their role by clicking. That reasoning no longer applies
 *    unchanged here, because Admins IS reachable now and IS owner-only (`admin.read`, §6.8
 *    line 949). The gate is the server's: the route guard refuses the other three roles with
 *    a plain 403, and `AdminsScreen` renders that refusal as a denial naming the role, with
 *    no Retry. A client-side copy of the rule is still not being added, for two reasons.
 *    It would be a second, forgeable statement of a policy the server already enforces —
 *    and the one that matters is the server's, since a rail that hides the item does not
 *    stop a typed URL. And hiding it would break the promise the paragraph above rests on:
 *    an owner and a support operator would see two different information architectures, and
 *    the support operator would have no way to learn that this console administers admin
 *    accounts at all. The cost of letting the server answer is bounded — one
 *    `permission.denied` row per wrong-role visit, and nothing on that screen retries or
 *    polls.
 *  - A plain `href`, not a route NAME resolved during render. admin-ui needs the indirection
 *    because its nav imports `ROUTES` from `routes.tsx`, which imports the rail back — a
 *    cycle that a module-scope read would turn into a TDZ crash. Here the paths live in
 *    `app/paths.ts`, a leaf module that imports nothing, so there is no cycle to dodge.
 */

import {
  LayoutDashboard,
  Megaphone,
  MessageSquare,
  ScrollText,
  Sparkles,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";

import { PATH } from "@/app/paths";
import type { TranslationPath } from "@/i18n/types";

export interface NavItem {
  readonly key: string;
  /**
   * Translation key for our own chrome label. Never user content, and never the label
   * itself: the rail is rendered once per locale change, so the string has to be resolved
   * during render rather than frozen into this module at import time.
   */
  readonly labelKey: TranslationPath;
  /** `null` when the section has no route on this build — then `notYet` says why. */
  readonly href: string | null;
  readonly icon: LucideIcon;
  /** `end` for `NavLink`: only `/` needs an exact match, or it matches everywhere. */
  readonly isExact?: boolean;
  /**
   * Translation key for why the section is not reachable. Present exactly when `href` is
   * null, and shown to the operator — as a tooltip and to a screen reader — so the absence is
   * explained rather than mysterious. One sentence: it has to fit in a `title`.
   */
  readonly notYetKey?: TranslationPath;
}

/** Above the rule. What the console is for. */
export const PRIMARY_NAV: readonly NavItem[] = [
  {
    key: "dashboard",
    labelKey: "nav.items.dashboard",
    href: PATH.dashboard,
    icon: LayoutDashboard,
    // The only exact match in the rail, and it has to be: `/` is a prefix of every path.
    isExact: true,
  },
  {
    key: "chats",
    labelKey: "nav.items.chats",
    href: PATH.chats,
    icon: MessageSquare,
  },
  {
    key: "users",
    labelKey: "nav.items.users",
    href: PATH.users,
    icon: Users,
  },
  {
    key: "generations",
    labelKey: "nav.items.generations",
    href: PATH.generations,
    icon: Sparkles,
  },
  {
    /*
     * Campaigns. Last above the rule, because it is the only operational section that WRITES
     * to customers rather than reading about them, and because §11.2's rail enumeration puts
     * it there — this file is transcribed from that section and is not extended by inference.
     *
     * Ungated, and that is the matrix's own answer rather than this file declining to check:
     * `broadcast.read` is `M` at all four roles (permissions.py — viewer, support, admin and
     * owner alike list campaigns and open one), so a client-side gate here would hide nothing
     * from anybody. What DOES differ by role is composing and sending — `broadcast.write`,
     * ADMIN and OWNER — and that is gated where it is spent, on the buttons themselves, via
     * `useCanWriteBroadcasts`. A rail entry that vanished for a support operator would also
     * break the promise the module docstring rests on: the information architecture is the
     * same for everyone, and the server is the authority on what each role may do inside it.
     */
    key: "broadcasts",
    labelKey: "nav.items.broadcasts",
    href: PATH.broadcasts,
    icon: Megaphone,
  },
];

/** Below the rule. What the console is administered by. */
export const SECONDARY_NAV: readonly NavItem[] = [
  {
    key: "audit",
    labelKey: "nav.items.audit",
    href: PATH.audit,
    icon: ScrollText,
  },
  {
    /*
     * Owner-only, and deliberately shown to everyone anyway — see the `permission` note in
     * the module docstring. `AdminsScreen` turns the server's 403 into the refusal an
     * operator can act on; a hidden item would turn it into a question they cannot ask.
     */
    key: "admins",
    labelKey: "nav.items.admins",
    href: PATH.admins,
    icon: UserCog,
  },
];

export interface NavSection {
  readonly key: string;
  /**
   * The group's name. A `<p>`, deliberately not a heading and not a list item: the rail is
   * already a labelled landmark, and seven items under two extra headings is more structure to
   * walk, not less. (Seven is the count this file declares — five above the rule and two
   * below — and it is the number this argument has to be checked against.) Hidden when the
   * rail is collapsed to icons — the rule still separates them, and a two-letter abbreviation
   * would be a worse label than none.
   */
  readonly labelKey: TranslationPath;
  readonly items: readonly NavItem[];
}

/** The two groups, in render order, with §11.2's rule between them. */
export const NAV_SECTIONS: readonly NavSection[] = [
  { key: "operations", labelKey: "nav.groups.operations", items: PRIMARY_NAV },
  { key: "administration", labelKey: "nav.groups.administration", items: SECONDARY_NAV },
];
