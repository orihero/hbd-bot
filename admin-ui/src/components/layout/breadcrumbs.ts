/**
 * The breadcrumb trail under every page title, derived from the route and nothing else.
 *
 * The trail is new DOM that the reskin adds and the old design had nowhere to put: a 26px
 * title with a small muted "Home / Orders / Detail" beneath it is the Gogo page header, and
 * without the second line the header is just a bigger version of the old one.
 *
 * Three rules keep it presentation rather than information architecture:
 *
 *  1. **It is derived, never passed.** Twelve screens render `<PageHeader>` and none of them
 *     had to change: the trail comes from `useLocation().pathname`, so it cannot disagree
 *     with the URL and cannot be forgotten on a new screen.
 *  2. **It invents no destination.** Every crumb but the last links to a path that is
 *     already in `ROUTES`; a segment with no route of its own (an order id, a Telegram id)
 *     becomes plain text. There is no crumb an operator can click to a 404.
 *  3. **It renders no customer content.** A crumb is one of our own labels — "Orders",
 *     "Detail" — and never an id, a name or anything a customer typed. §12.3 masks names at
 *     the response boundary; a breadcrumb should not be the one place a raw value reappears,
 *     and "Detail" says as much as a 36-character UUID would.
 *
 * The root crumb is "Home", which is Live Ops. That is the plan's own name for `/` in a
 * navigational sense — the rail calls the SCREEN "Live" and this calls the PLACE "Home", the
 * way the design's own trail does.
 */

import { ROUTES } from "@/routes";

export interface Crumb {
  /** Our own chrome label. Never user content. */
  readonly label: string;
  /** `null` for the current page, which is text rather than a link. */
  readonly href: string | null;
}

/**
 * Path segment → label, for the segments that name a section.
 *
 * Keyed on the segment rather than on the whole path because every one of these is unique
 * across the table, and a nested map would need an entry for `/generations/names` that
 * repeated what `generations` and `names` already say.
 */
const SEGMENT_LABELS: Readonly<Record<string, string>> = {
  orders: "Orders",
  users: "Users",
  generations: "Generations",
  names: "Name strategies",
  vendors: "Vendors",
  assets: "Assets",
  audit: "Audit",
  retention: "Retention",
  config: "Config",
  admins: "Admins",
  login: "Sign in",
};

/**
 * The set of paths that are real routes, so a crumb only ever links somewhere that exists.
 * Parameterised routes are excluded by the `:` test — `/orders/:orderId` is a pattern, not a
 * place, and the concrete path it stands for is the page we are already on.
 *
 * Built on FIRST CALL and never at module scope, for the same reason `navHref()` exists in
 * `navItems.ts`: there is an unavoidable import cycle here — `routes.tsx` → `RootLayout` →
 * `AppShell` → `PageHeader` → this file → `routes.tsx` — and ESM tolerates it only as long as
 * no binding is READ while the modules are still evaluating. A `new Set(Object.values(ROUTES))`
 * at module scope reads `ROUTES` mid-cycle, gets `undefined`, and either throws at import or
 * (with a `?? {}` to quiet it) yields an EMPTY set, which is worse: every crumb silently stops
 * being a link and no test that renders a trail would notice. `breadcrumbTrail` is only ever
 * called during render, by which time the cycle has settled.
 */
let realPaths: ReadonlySet<string> | null = null;

function isRealPath(path: string): boolean {
  realPaths ??= new Set(Object.values(ROUTES).filter((route) => !route.includes(":")));
  return realPaths.has(path);
}

/**
 * Build the trail for a pathname.
 *
 * The last crumb is always the current page and never a link, which is what
 * `aria-current="page"` marks in the DOM. Everything before it links only if the prefix is
 * a route in its own right: `/generations/names` yields a linked `Generations`, while
 * `/orders/<uuid>` yields a linked `Orders` and a plain `Detail`.
 */
export function breadcrumbTrail(pathname: string): readonly Crumb[] {
  const segments = pathname.split("/").filter((segment) => segment !== "");
  const home: Crumb = { label: "Home", href: segments.length === 0 ? null : ROUTES.live };
  if (segments.length === 0) return [home];

  const crumbs: Crumb[] = [home];
  let prefix = "";
  segments.forEach((segment, index) => {
    prefix += `/${segment}`;
    const isLast = index === segments.length - 1;
    // A segment we have no label for is a route parameter — an order id, a Telegram id, or
    // the `*` catch-all's path. It is named for what it IS, not printed.
    const label = SEGMENT_LABELS[segment] ?? "Detail";
    crumbs.push({ label, href: isLast || !isRealPath(prefix) ? null : prefix });
  });
  return crumbs;
}
