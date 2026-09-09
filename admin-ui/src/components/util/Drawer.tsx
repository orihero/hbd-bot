/**
 * `<Drawer>` — the right-hand slide-out, extracted so there is exactly one of them.
 *
 * The markup is lifted from the orders list's inline peek panel (a fixed scrim plus a
 * `fixed inset-y-0 right-0` aside on `--surface-card` at `--shadow-overlay`), which was the
 * only drawer in the console and could not be reused because it was a private component in a
 * screen file. Nothing about that screen changes here; this is the same panel with the four
 * things a hand-rolled overlay never has:
 *
 *  1. **Esc closes it.** An operator who opened a peek to read one fact should not have to
 *     find the ✕ with the mouse to get back to the list.
 *  2. **Focus is trapped inside while it is open.** A drawer the keyboard can walk out of is
 *     a drawer that reads, to a screen reader, as though the page behind it is still live.
 *  3. **Focus is restored to whatever opened it.** The row the operator pressed Enter on is
 *     where the cursor belongs when the panel goes away — otherwise `j`/`k` resumes from the
 *     top of the table and the place in the list is lost.
 *  4. **`role="dialog"`, `aria-modal` and an accessible name**, so it is announced as a
 *     panel rather than as a pile of text appended to the end of the page.
 *
 * All four come from Radix's `Dialog`, which is already this console's modal primitive
 * (`KeyboardShortcuts`, `RevealDialog`). This component is that primitive wearing the
 * drawer's geometry — `asChild` keeps the element an `<aside>` so the landmark survives.
 *
 * The scrim is `RevealDialog`'s rather than the peek panel's `bg-black/40`, and deliberately:
 * a black wash dims a light page and *lightens* a dark one. `--ink` at 40% in light and
 * `--surface` at 75% in dark dims in both, which is the difference between a panel that
 * floats over a dimmed console and one that floats over nothing.
 *
 * ## The title is OURS
 *
 * `title` is rendered as the dialog's accessible name, so it must be console copy — an order
 * reference, a masked id, a heading. Never a recipient's name: an accessible name is read
 * aloud, is not `<NameText>`, and would put customer content outside the fence.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useRef, type ReactElement, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./Button";

export interface DrawerProps {
  readonly isOpen: boolean;
  /** Esc, the ✕ and a click on the scrim all arrive here. */
  readonly onClose: () => void;
  /** The heading AND the accessible name. Our words — see the note above. */
  readonly title: ReactNode;
  /** Beside the title: status pills, a reference chip, a copy button. */
  readonly headerExtra?: ReactNode | undefined;
  /** One line under the title. Radix wants a description or it warns; give it one. */
  readonly description?: ReactNode | undefined;
  /** Pinned under the scrolling body — the "open full record" link, usually. */
  readonly footer?: ReactNode | undefined;
  readonly children: ReactNode;
  /** The panel's width cap. `max-w-lg` is the peek panel's. */
  readonly widthClassName?: string | undefined;
  /** Suffixed with `-backdrop` for the scrim, so a test can address either half. */
  readonly testId?: string | undefined;
  readonly className?: string | undefined;
}

export function Drawer({
  isOpen,
  onClose,
  title,
  headerExtra,
  description,
  footer,
  children,
  widthClassName = "max-w-lg",
  testId = "drawer",
  className,
}: DrawerProps): ReactElement {
  /*
   * Whatever had focus when the panel opened — a table row, a chip, a button.
   *
   * Radix restores focus to its own `Dialog.Trigger`, and this drawer has none: it is
   * controlled, and what opens it is a row activation inside `DataTable`. With no trigger
   * ref, Radix's restore focuses `null` and the cursor lands on `<body>`, which is exactly
   * the "lost my place in the list" failure this component exists to avoid. So the opener is
   * recorded on the mount-autofocus event — dispatched BEFORE focus moves into the panel,
   * which is the only moment `document.activeElement` is still the row — and restored on the
   * way out.
   */
  const openerRef = useRef<HTMLElement | null>(null);

  return (
    <Dialog.Root
      open={isOpen}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          data-testid={`${testId}-backdrop`}
          className="fixed inset-0 z-40 bg-ink opacity-40 dark:bg-surface dark:opacity-75"
        />
        {/* `asChild` so the panel stays an `<aside>`: Radix puts `role="dialog"` and
            `aria-modal` on it, and the landmark is what a screen reader's rotor lists. */}
        <Dialog.Content
          asChild
          onOpenAutoFocus={() => {
            const active = document.activeElement;
            openerRef.current = active instanceof HTMLElement ? active : null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            openerRef.current?.focus();
          }}
        >
          <aside
            data-testid={testId}
            // Radix hides the rest of the page with `aria-hidden` and does not write this
            // one itself; a panel that traps focus and does not say it is modal is a panel a
            // screen reader will happily read the dimmed page behind.
            aria-modal="true"
            className={cn(
              "fixed inset-y-0 right-0 z-50 flex w-full flex-col gap-6 overflow-y-auto",
              "bg-surface-card p-6 shadow-overlay",
              "transition-transform duration-base ease-standard sm:border-l sm:border-line",
              widthClassName,
              className,
            )}
          >
            <header className="flex flex-wrap items-start justify-between gap-3 border-b border-hairline pb-4">
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <Dialog.Title className="type-h2 text-ink">{title}</Dialog.Title>
                <Dialog.Description
                  className={cn(
                    "type-body-sm text-ink-muted",
                    description === undefined ? "sr-only" : undefined,
                  )}
                >
                  {description ?? "Press Escape to close this panel."}
                </Dialog.Description>
                {headerExtra === undefined ? null : (
                  <div className="flex flex-wrap items-center gap-2 pt-1">{headerExtra}</div>
                )}
              </div>
              <Dialog.Close asChild>
                <Button variant="quiet" size="xs" shape="pill" aria-label="Close">
                  <X aria-hidden="true" className="h-3.5 w-3.5" />
                </Button>
              </Dialog.Close>
            </header>

            <div className="flex min-h-0 flex-1 flex-col gap-6">{children}</div>

            {footer === undefined ? null : (
              <footer className="flex flex-wrap items-center gap-2 border-t border-hairline pt-4">
                {footer}
              </footer>
            )}
          </aside>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
