/**
 * ⌘K — §11.2's "single global entry point".
 *
 * The shape resolution lives in `paletteResolve.ts` and is pure; this file is the dialog
 * around it. Three things are deliberate:
 *
 *  - **It is a listbox, not a menu.** The input keeps focus while ↑/↓ move a virtual cursor
 *    (`aria-activedescendant`), so an operator never has to leave the field to choose. A
 *    Radix menu would move DOM focus and swallow the next keystroke.
 *  - **No filtering library.** The results are already ranked by SHAPE — a UUID outranks a
 *    section name — and a fuzzy scorer would reorder them, which is exactly the behaviour
 *    §11.2 rules out by saying the palette resolves by shape.
 *  - **It renders no customer content.** Every row's text is ours: an id the operator typed,
 *    a section name, or an explanation. §12.3 masks names at the response boundary, so there
 *    is nothing to leak here and nothing to normalise.
 *
 * The reskin restyled the dialog and moved nothing: `left-1/2 top-[12vh] -translate-x-1/2`
 * and `w-[min(38rem,94vw)]` are asserted BY THEIR EFFECT in `e2e/smoke.spec.ts` (centred,
 * at 12vh, never full-bleed), and the same spec is the one that proves the scroll lock's
 * nonce path still works. Restyle freely; do not move the box.
 *
 * `--shadow-overlay` rather than a plain shadow, because it carries the 1px `--edge` ring
 * the old `--e-3` did. A floating panel over a card of the same colour needs a boundary, and
 * this design's whisper shadows do not supply one on their own.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { usePrefsStore } from "@/lib/stores";
import { cn } from "@/lib/utils";

import { resolvePalette, type PaletteResult } from "./paletteResolve";

const KIND_GLYPH: Readonly<Record<PaletteResult["kind"], string>> = {
  order: "◆",
  user: "◑",
  correlation: "⧉",
  route: "→",
  unavailable: "⊘",
};

export function CommandPalette() {
  const isOpen = usePrefsStore((state) => state.isCommandPaletteOpen);
  const setOpen = usePrefsStore((state) => state.setCommandPaletteOpen);
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const listId = useRef(`palette-list-${String(Math.trunc(Math.random() * 1e9))}`).current;

  const results = useMemo(() => resolvePalette(query), [query]);

  // A reopened palette starts blank. Carrying the previous query over means the first ⌘K of
  // a new investigation shows the last one's order id, which is how the wrong record gets
  // opened during an incident.
  useEffect(() => {
    if (!isOpen) {
      setQuery("");
      setCursor(0);
    }
  }, [isOpen]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  const go = (result: PaletteResult | undefined): void => {
    if (result === undefined || result.href === null) return;
    setOpen(false);
    navigate(result.href);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((index) => (results.length === 0 ? 0 : (index + 1) % results.length));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((index) =>
        results.length === 0 ? 0 : (index - 1 + results.length) % results.length,
      );
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      go(results[cursor]);
    }
  };

  const activeId = results[cursor] === undefined ? undefined : `${listId}-${String(cursor)}`;

  return (
    <Dialog.Root open={isOpen} onOpenChange={setOpen}>
      <Dialog.Portal>
        {/*
         * The scrim. It has to darken in BOTH themes, and a Tailwind alpha modifier is not
         * available: every colour in this design is a `var(--token)` string, and `/40` on
         * one produces an invalid colour that fails silently. So the element's own opacity
         * does the work, over `--ink` in the light theme (a soft charcoal veil) and over
         * `--surface-sunken` in dark, where inking the scrim would LIGHTEN the page.
         */}
        <Dialog.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-ink opacity-30",
            "dark:bg-surface-sunken dark:opacity-80",
          )}
        />
        <Dialog.Content
          aria-label="Command palette"
          className={cn(
            "fixed left-1/2 top-[12vh] z-50 w-[min(38rem,94vw)] -translate-x-1/2",
            "overflow-hidden rounded-3xl bg-surface-card shadow-overlay",
          )}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">
            Type an order id, a Telegram user id, a correlation id, or a section name.
          </Dialog.Description>

          {/* The one rule in the dialog. A search field with nothing under it but whitespace
              reads as the top of the list rather than as the thing that filters it. */}
          <div className="flex items-center gap-3 border-b border-hairline px-5">
            <span aria-hidden="true" className="type-body text-ink-muted">
              ⌘K
            </span>
            <input
              /* The dialog exists to be typed into; anything else needs a second keystroke. */
              autoFocus
              type="text"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              onKeyDown={onKeyDown}
              placeholder="Order id, Telegram id, correlation id, or a section"
              aria-label="Search"
              aria-controls={listId}
              aria-expanded="true"
              aria-autocomplete="list"
              role="combobox"
              {...(activeId === undefined ? {} : { "aria-activedescendant": activeId })}
              className={cn(
                "type-body h-14 w-full bg-transparent text-ink outline-none",
                "placeholder:text-ink-muted",
              )}
            />
          </div>

          <ul
            id={listId}
            role="listbox"
            aria-label="Results"
            className="max-h-[52vh] overflow-y-auto p-2"
          >
            {results.map((result, index) => {
              const isActive = index === cursor;
              const isActionable = result.href !== null;
              return (
                <li
                  key={result.id}
                  id={`${listId}-${String(index)}`}
                  role="option"
                  aria-selected={isActive}
                  aria-disabled={isActionable ? undefined : true}
                  onMouseEnter={() => {
                    setCursor(index);
                  }}
                  onClick={() => {
                    go(result);
                  }}
                  className={cn(
                    "flex cursor-default items-center gap-3 rounded-2xs px-3 py-2.5",
                    "transition-colors duration-fast ease-standard",
                    isActive && isActionable && "bg-surface-control",
                    !isActionable && "opacity-80",
                  )}
                >
                  {/*
                   * `aria-hidden` iconography — the row's words carry the meaning. It is
                   * `--ink-muted` rather than the policed `--ink-mark`: a mark that sits
                   * beside words still has to be seen, `--ink-muted` clears 4.5:1 on every
                   * ground in both palettes, and it needs no waiver to say so.
                   */}
                  <span
                    aria-hidden="true"
                    className="w-4 text-center text-ink-muted"
                  >
                    {KIND_GLYPH[result.kind]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "type-body block truncate",
                        isActionable ? "text-ink" : "text-ink-muted",
                      )}
                    >
                      {result.label}
                    </span>
                    <span className="type-body-sm block truncate text-ink-muted">
                      {result.hint}
                    </span>
                  </span>
                  {result.kind === "route" ? null : (
                    <span
                      className={cn(
                        "type-caption shrink-0 rounded-pill bg-surface-control px-2 py-0.5",
                        "text-ink-muted",
                      )}
                    >
                      {result.kind}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
