/**
 * §11.2: "The ⌘K palette is the single global entry point and **resolves by shape**: a UUID
 * jumps to the order, a bare integer to the user, a 32-hex string to a `correlation_id`, free
 * text searches recipient display names."
 *
 * Resolution is a pure function so the shape rules are testable without a DOM, and so the one
 * genuinely ambiguous case is decided in one visible place rather than inside a component.
 *
 * ## The ambiguity, and how it is settled
 *
 * A `correlation_id` is `^[0-9a-f]{32}$` (`CORRELATION_ID_PATTERN`). A UUID with its dashes
 * removed is *also* 32 hex characters. The plan assigns dashed → order and 32-hex →
 * correlation, and that is what the ordering below does; but a 32-hex string that dashes into
 * a well-formed v4 UUID ALSO gets an order result, second, because an operator who stripped
 * the dashes out of a log line should not be told their id does not exist. The plan is silent
 * on the collision; this ranks rather than chooses.
 *
 * ## What free text cannot do on this build
 *
 * Nothing on the shipped surface searches recipient names. §12.3 masks
 * `recipient_name_display` to a first grapheme plus `•••` at the response boundary, and no
 * list endpoint accepts a name or a free-text parameter (`OrdersQuery` has `state`, `isPaid`,
 * `telegramUserId`, `correlationId`, `hasAssets`, and a window; `UsersQuery` has no `q`).
 * So free text falls back to matching SECTION names, and the palette says plainly that name
 * search is not available rather than returning an empty list an operator would read as "no
 * such customer".
 */

import { CORRELATION_ID_PATTERN } from "@/api";
import { ROUTES, href, type RouteName } from "@/routes";

/** `8-4-4-4-12`, case-insensitive: the server emits lower case, a pasted log line may not. */
export const UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/u;

/** A bare integer — a Telegram user id. No sign, no separators, no leading `+`. */
export const TELEGRAM_ID_PATTERN = /^\d{1,19}$/u;

/** 32 hex, no dashes. Deliberately case-insensitive even though the server emits lower. */
export const BARE_HEX32_PATTERN = /^[0-9a-fA-F]{32}$/u;

export type PaletteResultKind = "order" | "user" | "correlation" | "route" | "unavailable";

export interface PaletteResult {
  /** Stable across renders for the same input, so keyboard focus does not jump. */
  readonly id: string;
  readonly kind: PaletteResultKind;
  /** What the row says. Our own text — the palette never renders customer content. */
  readonly label: string;
  /** The secondary line: why this row matched. */
  readonly hint: string;
  /** Where Enter goes. `null` for an `unavailable` row, which is not actionable. */
  readonly href: string | null;
}

interface RouteEntry {
  readonly name: RouteName;
  readonly label: string;
  /** Extra words an operator might type for it. Our own vocabulary, never user content. */
  readonly keywords: readonly string[];
}

/**
 * Every navigable route, including the two §11.2's rail omits. The palette is "the single
 * global entry point", so `/retention` and `/generations/names` are reachable here even
 * though the rail (transcribed from §11.2) does not list them.
 */
export const ROUTE_ENTRIES: readonly RouteEntry[] = [
  { name: "live", label: "Live Ops", keywords: ["dashboard", "pulse", "home"] },
  { name: "orders", label: "Orders", keywords: ["order", "list"] },
  { name: "users", label: "Users", keywords: ["customer", "telegram"] },
  { name: "generations", label: "Generations", keywords: ["attempts", "llm", "provider"] },
  {
    name: "nameStrategies",
    label: "Name strategies",
    keywords: ["bake-off", "verification", "candidate order"],
  },
  { name: "assets", label: "Assets", keywords: ["audio", "expiring", "storage"] },
  { name: "audit", label: "Audit", keywords: ["log", "reveals", "chain"] },
  { name: "retention", label: "Retention", keywords: ["purge", "sweep", "clocks"] },
  { name: "config", label: "Config", keywords: ["settings", "overrides", "environment"] },
  { name: "admins", label: "Admins", keywords: ["accounts", "roles"] },
];

/**
 * A section's path.
 *
 * Resolved through `ROUTES` at CALL time rather than into a module-scope table, because
 * there is an import cycle (`routes.tsx` → `RootLayout` → `AppShell` → `CommandPalette` →
 * this file → `routes.tsx`) and reading `ROUTES` while the modules are still evaluating
 * would bake `undefined` into every href. Same reasoning as `navHref` in `navItems.ts`.
 */
function routeHref(name: RouteName): string {
  return ROUTES[name];
}

/** Insert the dashes back into 32 bare hex characters. */
export function dashUuid(hex32: string): string {
  return [
    hex32.slice(0, 8),
    hex32.slice(8, 12),
    hex32.slice(12, 16),
    hex32.slice(16, 20),
    hex32.slice(20, 32),
  ].join("-");
}

function routeResults(query: string): readonly PaletteResult[] {
  // `query` is OUR chrome vocabulary being matched against OUR labels — never a name, a note
  // or anything a customer typed. Case folding here cannot destroy a datum; inside
  // `components/domain/` the same call is banned, and for good reason (§11.4).
  const needle = query.trim().toLowerCase();
  return ROUTE_ENTRIES.filter((entry) => {
    if (needle === "") return true;
    if (entry.label.toLowerCase().includes(needle)) return true;
    return entry.keywords.some((keyword) => keyword.includes(needle));
  }).map((entry) => ({
    id: `route:${entry.name}`,
    kind: "route" as const,
    label: entry.label,
    hint: routeHref(entry.name),
    href: routeHref(entry.name),
  }));
}

/**
 * Resolve what the operator typed, best match first.
 *
 * An empty input lists every section, which is what makes ⌘K usable as a launcher and not
 * only as a lookup.
 */
export function resolvePalette(input: string): readonly PaletteResult[] {
  const value = input.trim();
  if (value === "") return routeResults("");

  const results: PaletteResult[] = [];

  if (UUID_PATTERN.test(value)) {
    results.push({
      id: `order:${value}`,
      kind: "order",
      label: `Order ${value}`,
      hint: "looks like an order id",
      href: href.order(value),
    });
  } else if (BARE_HEX32_PATTERN.test(value)) {
    // §11.2 assigns 32-hex to `correlation_id`, so that is first.
    const lowered = CORRELATION_ID_PATTERN.test(value) ? value : value.toLowerCase();
    results.push({
      id: `correlation:${lowered}`,
      kind: "correlation",
      label: `Orders with correlation ${lowered}`,
      hint: "looks like a correlation id",
      href: `${href.orders()}?correlationId=${encodeURIComponent(lowered)}`,
    });
    // …and the same 32 characters are a dash-stripped UUID, which is what a log line often
    // carries. Offered second rather than chosen over the plan's rule.
    const dashed = dashUuid(lowered);
    results.push({
      id: `order:${dashed}`,
      kind: "order",
      label: `Order ${dashed}`,
      hint: "the same 32 characters, read as an order id",
      href: href.order(dashed),
    });
  } else if (TELEGRAM_ID_PATTERN.test(value)) {
    const telegramUserId = Number(value);
    if (Number.isSafeInteger(telegramUserId)) {
      results.push({
        id: `user:${value}`,
        kind: "user",
        label: `User ${value}`,
        hint: "looks like a Telegram user id",
        href: href.user(telegramUserId),
      });
      results.push({
        id: `orders-of:${value}`,
        kind: "route",
        label: `Orders for user ${value}`,
        hint: "filter the orders list to this person",
        href: `${href.orders()}?telegramUserId=${encodeURIComponent(value)}`,
      });
    }
  }

  results.push(...routeResults(value));

  // The honest ending. An empty palette after typing a name would read as "no such
  // customer", which is a claim this build cannot make.
  if (results.length === 0) {
    results.push({
      id: "unavailable:name-search",
      kind: "unavailable",
      label: "Searching by recipient name is not available on this build",
      hint: "names are masked at the response boundary (§12.3) and no endpoint accepts free text",
      href: null,
    });
  }

  return results;
}
