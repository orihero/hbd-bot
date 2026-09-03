/**
 * The global key bindings, and the sheet that lists them.
 *
 * §11.2 names one shortcut by hand — **⌘K** for the palette, "the single global entry
 * point" — and §11.4 names `j/k` row navigation as `DataTable`'s. Everything else here is
 * this component's own, kept deliberately small: an operator during an incident should be
 * able to learn the whole set from one sheet, and a console with twenty chords has none.
 *
 * The binding that needs justifying is the one that is NOT here. There is no single-key
 * shortcut for anything destructive, at any role. Retry, force-deliver, block and purge all
 * cost a click and a step-up (§12.2); a stray keystroke must never be able to start one.
 *
 * The table itself, and the "is the operator typing?" predicate that keeps `/` from eating a
 * character out of a filter box, live in `shortcuts.ts` — this file exports a component and
 * nothing else, so Fast Refresh does not remount the shell on every edit.
 *
 * The sheet's open state is a context, not a fourth Zustand store — see `shortcutHelp.ts`
 * for why. This component is the provider: it wraps the shell.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { usePrefsStore } from "@/lib/stores";
import { cn } from "@/lib/utils";

import { buttonVariants } from "./buttonVariants";
import { ShortcutHelpContext, type ShortcutHelpApi } from "./shortcutHelp";
import { isAppleKeyboard, isTypingTarget, shortcutRows } from "./shortcuts";

export interface KeyboardShortcutsProps {
  /** The shell. Rendered inside the provider so any of it can open the sheet. */
  readonly children?: ReactNode;
}

export function KeyboardShortcuts({ children }: KeyboardShortcutsProps) {
  const setCommandPaletteOpen = usePrefsStore((state) => state.setCommandPaletteOpen);
  const toggleCommandPalette = usePrefsStore((state) => state.toggleCommandPalette);
  const [isOpen, setOpen] = useState(false);

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;

      // ⌘K / Ctrl+K works even inside a field: it is the global entry point, and an
      // operator who is mid-filter and wants to jump elsewhere should not have to escape
      // the field first. Both cases spelled out, because `toLowerCase()` is the call §11.4
      // bans on user content and habits formed here leak into `components/domain/`.
      if (
        (event.metaKey || event.ctrlKey) &&
        !event.altKey &&
        (event.key === "k" || event.key === "K")
      ) {
        event.preventDefault();
        toggleCommandPalette();
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      if (event.key === "/") {
        event.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }
      if (event.key === "?") {
        event.preventDefault();
        setOpen((previous) => !previous);
      }
    },
    [setCommandPaletteOpen, toggleCommandPalette],
  );

  useEffect(() => {
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onKeyDown]);

  const api = useMemo<ShortcutHelpApi>(() => ({ isOpen, setOpen }), [isOpen]);
  const isApple = useMemo(() => isAppleKeyboard(), []);

  return (
    <ShortcutHelpContext.Provider value={api}>
      {children}
      <Dialog.Root open={isOpen} onOpenChange={setOpen}>
        <Dialog.Portal>
          {/* The same scrim the palette uses, and for the same reason: an alpha modifier on
              a `var(--token)` colour is an invalid colour that fails silently, so the
              element's own opacity does the darkening. */}
          <Dialog.Overlay
            className={cn(
              "fixed inset-0 z-50 bg-ink opacity-30",
              "dark:bg-surface-sunken dark:opacity-80",
            )}
          />
          <Dialog.Content
            className={cn(
              "fixed left-1/2 top-1/2 z-50 w-[min(30rem,92vw)] -translate-x-1/2 -translate-y-1/2",
              // `--shadow-overlay` carries the 1px `--edge` ring; a floating panel over a
              // card of the same colour needs a boundary this design draws nowhere else.
              "rounded-3xl bg-surface-card p-6 shadow-overlay",
            )}
          >
            <Dialog.Title className="type-h2 text-ink">Keyboard</Dialog.Title>
            <Dialog.Description className="type-body-sm mt-1 text-ink-muted">
              Nothing here changes an order. Every write costs a click.
            </Dialog.Description>
            <ul className="mt-4 flex flex-col gap-1">
              {shortcutRows(isApple).map((row) => (
                <li
                  key={`${row.scope}:${row.keys.join("+")}`}
                  className="flex items-center justify-between gap-4 rounded-control px-3 py-2"
                >
                  <span className="type-body-sm text-ink">{row.description}</span>
                  <span className="flex items-center gap-2">
                    <span className="type-caption text-ink-muted">{row.scope}</span>
                    <span className="flex gap-1">
                      {row.keys.map((key) => (
                        <kbd
                          key={key}
                          className={cn(
                            "type-mono rounded-2xs bg-surface-control px-2",
                            "leading-6 text-ink",
                          )}
                        >
                          {key}
                        </kbd>
                      ))}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            {/* A Radix `Dialog.Close` is its own `<button>`, so it takes the CLASSES from
                the shared definition rather than the component. Same four variants. */}
            <Dialog.Close
              className={cn(
                buttonVariants({ variant: "secondary", shape: "pill" }),
                "mt-5",
              )}
            >
              Close
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </ShortcutHelpContext.Provider>
  );
}
