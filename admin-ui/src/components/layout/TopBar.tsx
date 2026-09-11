/**
 * The top bar — `--topbar-h` (68px), §11.2's five controls and nothing else:
 *
 * > env badge · ⌘K palette · `● LIVE` connection pill · **UTC/local toggle** · theme ·
 * > account
 *
 * The UTC/local toggle is the one that looks optional and is not. §11.2: "every column is
 * `timestamptz` and three parties may be in three places; an ambiguous '14:32' is a support
 * incident." The customer is in Tashkent, the server logs in UTC, the operator is wherever
 * they are — so the toggle is global, its current setting is written on its face, and
 * `lib/format.ts` has no bare-time formatter for anything to fall back to.
 *
 * `usePrefsStore` defaults it to **UTC** deliberately: a support conversation that starts
 * from a server log is a UTC conversation, and an operator who wants their own clock opts in.
 *
 * ## What the reskin changed
 *
 * The bar is now the full width of the window with the product mark at its far left and the
 * env chip beside it — the mark moved here out of the rail's head, because a mark that sits
 * to the RIGHT of a 264px rail is not a brand mark, it is a column heading. The controls on
 * the right became circular icon buttons carrying their own ground instead of bordered
 * rectangles, and the bar has no bottom rule: `--surface-topbar` over the page ground plus
 * `--shadow-2xs` is the separation.
 *
 * The ⌘K trigger is one of those circular buttons rather than a wide search field. It keeps
 * the accessible name it always had ("Open the command palette") and moves the shapes it
 * accepts into its `title`, so nothing is lost but the width — and the palette itself still
 * says, on its own placeholder, what it resolves.
 *
 * There is no notifications button. The Gogo bar has one; this console has no notification
 * feed to put behind it, and inventing an affordance that opens an empty list is exactly the
 * "reskin quietly became a redesign" failure this pass is not allowed to make.
 */

import { useQuery } from "@tanstack/react-query";
import { Clock, Monitor, Moon, Search, Sun } from "lucide-react";

import type { AdminEnvironment, ConfigView } from "@/api";
import { getConfig, unwrapAsync } from "@/api";
import { isAppleKeyboard, useShortcutHelp } from "@/components/util";
import { localOffsetLabel, timeZoneLabel } from "@/lib/format";
import { queryKeys } from "@/lib/queryKeys";
import { usePrefsStore, type ThemeChoice } from "@/lib/stores";
import { cn } from "@/lib/utils";

import { AccountMenu } from "./AccountMenu";
import { buttonVariants } from "@/components/util";

import { EnvBadge } from "./EnvBadge";
import { LiveHeartbeatPill } from "./LivePill";

/**
 * One circular icon button. No border at all: the ground appears on hover, which is this
 * design's whole idiom for a control, and `--ink-muted` clears AA on every ground it can
 * land on so the glyph inside is legible before it is hovered.
 */
const ICON_BUTTON_CLASS = buttonVariants({ variant: "quiet", size: "icon", shape: "pill" });

/**
 * Which database this is. Shared query key with the Config screen, so the two cost one
 * request between them.
 *
 * `retry: false` on purpose: `/api/config` answers `CAPABILITY_DISABLED` when
 * `BAYRAM_ADMIN_CONFIG_ENABLED` is off, and that will not become true by asking again. The
 * badge then says "env unknown", which is the honest answer.
 */
function useEnvironment(): AdminEnvironment | null {
  const query = useQuery<ConfigView>({
    queryKey: queryKeys.config.detail(),
    queryFn: ({ signal }) => unwrapAsync(getConfig({ signal })),
    staleTime: 5 * 60_000,
    retry: false,
  });
  return query.data?.environment ?? null;
}

/**
 * The cycle starts from LIGHT, because light is now the default palette and a toggle whose
 * first step is "leave the default" is the one an operator learns backwards.
 */
const NEXT_THEME: Readonly<Record<ThemeChoice, ThemeChoice>> = {
  light: "dark",
  dark: "system",
  system: "light",
};

const THEME_LABEL: Readonly<Record<ThemeChoice, string>> = {
  dark: "Dark",
  light: "Light",
  system: "System",
};

function ThemeToggle() {
  const theme = usePrefsStore((state) => state.theme);
  const setTheme = usePrefsStore((state) => state.setTheme);
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  const next = NEXT_THEME[theme];

  return (
    <button
      type="button"
      onClick={() => {
        setTheme(next);
      }}
      aria-label={`Theme: ${THEME_LABEL[theme]}. Switch to ${THEME_LABEL[next]}.`}
      title={`Theme: ${THEME_LABEL[theme]} → ${THEME_LABEL[next]}`}
      className={ICON_BUTTON_CLASS}
    >
      <Icon aria-hidden="true" className="h-4 w-4" />
    </button>
  );
}

function TimeZoneToggle() {
  const mode = usePrefsStore((state) => state.timeZoneMode);
  const toggle = usePrefsStore((state) => state.toggleTimeZoneMode);
  const otherLabel = mode === "utc" ? localOffsetLabel() : "UTC";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Timestamps are shown in ${timeZoneLabel(mode)}. Switch to ${otherLabel}.`}
      title={`Timestamps in ${timeZoneLabel(mode)} — click for ${otherLabel}`}
      // Wider than the round buttons beside it, because the CURRENT zone is written on its
      // face: §11.2 says an operator must never have to click to find out which clock they
      // are reading, and an icon alone would make them.
      className={cn(buttonVariants({ variant: "quiet", size: "none", shape: "pill" }), "h-10 gap-1.5 px-3")}
    >
      <Clock aria-hidden="true" className="h-4 w-4" />
      <span className="type-caption num">{timeZoneLabel(mode)}</span>
    </button>
  );
}

function PaletteTrigger() {
  const setOpen = usePrefsStore((state) => state.setCommandPaletteOpen);
  const meta = isAppleKeyboard() ? "⌘" : "Ctrl";

  return (
    <button
      type="button"
      onClick={() => {
        setOpen(true);
      }}
      aria-label="Open the command palette"
      title={`Search — order id, Telegram id, correlation id, or a section (${meta}K)`}
      className={ICON_BUTTON_CLASS}
    >
      <Search aria-hidden="true" className="h-4 w-4" />
    </button>
  );
}

export function TopBar() {
  const environment = useEnvironment();
  const shortcutHelp = useShortcutHelp();

  return (
    <header
      className={cn(
        "flex h-topbar shrink-0 items-center gap-3 bg-surface-topbar px-4 shadow-2xs",
      )}
    >
      {/*
       * The product mark. The short form of the product name — the full
       * `Bayram — Tabriklar, Qoʻshiqlar` would not fit this row. The env
       * chip sits immediately beside it, which is where §11.2 wants the loudest answer to
       * "which database am I looking at" to be: in the same glance as the product name.
       */}
      <span className="type-h2 shrink-0 text-ink">Bayram</span>
      <EnvBadge environment={environment} />

      <div className="min-w-0 flex-1" />

      <LiveHeartbeatPill />
      <PaletteTrigger />
      <TimeZoneToggle />
      <ThemeToggle />
      <button
        type="button"
        onClick={() => {
          shortcutHelp.setOpen(true);
        }}
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (?)"
        className={ICON_BUTTON_CLASS}
      >
        <span aria-hidden="true" className="type-body">
          ?
        </span>
      </button>
      <AccountMenu />
    </header>
  );
}
