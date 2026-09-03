/**
 * The shortcut sheet's open state, as a context.
 *
 * §11.1 allows **exactly three** Zustand stores and this is not one of them. The palette's
 * open flag already lives in `usePrefsStore` (unpersisted); the help sheet's does not, and
 * adding a fourth store to carry one boolean would be the kind of drift that ends with the
 * session in Zustand too. So `KeyboardShortcuts` is a PROVIDER — it wraps the shell, owns
 * the flag in React state, and hands this API to the account menu and the top bar.
 *
 * The context object lives here rather than in `KeyboardShortcuts.tsx` so that file exports
 * a component and nothing else (Fast Refresh reloads a mixed module wholesale, which would
 * remount the shell on every edit).
 */

import { createContext, useContext } from "react";

export interface ShortcutHelpApi {
  readonly isOpen: boolean;
  readonly setOpen: (open: boolean) => void;
}

/** What `useShortcutHelp()` returns outside a provider: a no-op, never a throw. */
const INERT_HELP: ShortcutHelpApi = { isOpen: false, setOpen: () => undefined };

export const ShortcutHelpContext = createContext<ShortcutHelpApi | null>(null);

/**
 * Open or close the shortcut sheet from anywhere inside `<KeyboardShortcuts>`.
 *
 * Outside the provider it is inert rather than a throw: a component rendered in isolation by
 * a test should not fail because the shell is absent, and there is nothing to be wrong
 * about — the sheet simply cannot open.
 */
export function useShortcutHelp(): ShortcutHelpApi {
  return useContext(ShortcutHelpContext) ?? INERT_HELP;
}
