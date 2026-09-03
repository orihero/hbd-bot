/**
 * The shortcut TABLE and the two predicates around it, split out of `KeyboardShortcuts.tsx`
 * so that file exports a component and nothing else (Fast Refresh reloads a module wholesale
 * when it exports a mix, which would remount the shell on every edit).
 *
 * §11.2 names one shortcut by hand — **⌘K** for the palette, "the single global entry
 * point" — and §11.4 names `j/k` row navigation as `DataTable`'s. The set is deliberately
 * small: an operator during an incident should be able to learn the whole of it from one
 * sheet, and a console with twenty chords has none.
 *
 * The binding that needs justifying is the one that is NOT here. There is no single-key
 * shortcut for anything destructive, at any role. Retry, force-deliver, block and purge all
 * cost a click and a step-up (§12.2); a stray keystroke must never be able to start one.
 */

export interface ShortcutRow {
  /** The keys, already in display form. `⌘K` on a Mac, `Ctrl K` elsewhere. */
  readonly keys: readonly string[];
  readonly description: string;
  /** Where it applies. "anywhere" for the globals; a surface name for the local ones. */
  readonly scope: string;
}

/**
 * Whether this browser reports a Mac, for `⌘` vs `Ctrl` in the sheet.
 *
 * `navigator.userAgent`, not `navigator.platform`: the latter is deprecated and the lint
 * rejects it. This only picks a GLYPH — a wrong guess costs a confusing label in one dialog,
 * never a wrong action — so a UA sniff is proportionate here and nowhere else.
 */
export function isAppleKeyboard(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/u.test(navigator.userAgent);
}

export function shortcutRows(isApple: boolean = isAppleKeyboard()): readonly ShortcutRow[] {
  const meta = isApple ? "⌘" : "Ctrl";
  return [
    { keys: [meta, "K"], description: "Open the command palette", scope: "anywhere" },
    { keys: ["/"], description: "Open the command palette", scope: "anywhere" },
    { keys: ["?"], description: "Show this list", scope: "anywhere" },
    { keys: ["Esc"], description: "Close the palette or a dialog", scope: "anywhere" },
    { keys: ["j"], description: "Next row", scope: "tables" },
    { keys: ["k"], description: "Previous row", scope: "tables" },
    { keys: ["Enter"], description: "Open the focused row", scope: "tables" },
  ];
}

/**
 * Whether the event's target is somewhere the operator is composing text. A shortcut must
 * never steal a character from a filter box, a search field or a reason note — that is the
 * single most common way a shortcut layer becomes something people ask to have turned off.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
