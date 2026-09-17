/**
 * The modal shell both privileged dialogs sit in.
 *
 * There is no dialog primitive in this app's dependencies, so the four things a modal owes a
 * keyboard are written out here once rather than half-written twice:
 *
 *  - focus moves INTO the panel on open and back to the trigger on close, so a reveal started
 *    from a table row does not drop the operator at the top of the document;
 *  - Tab cycles inside the panel, because a form that asks for a password must not let Tab
 *    wander onto the page behind it;
 *  - Escape closes, and the scrim is inert — a mis-click must not discard a half-written
 *    reason or, worse, a screen full of plaintext. While a request is IN FLIGHT nothing
 *    closes at all (`isBusy`): the server has already spent the grant, charged the budget and
 *    written the audit row by the time the answer arrives, so a dialog discarded mid-flight
 *    is a disclosure that was paid for and never seen — and the operator's next move is to
 *    buy it a second time;
 *  - the page behind stops scrolling.
 *
 * `aria-modal` plus a labelled `role="dialog"` is what makes a screen reader treat the panel
 * as the whole world while it is open.
 */

import { useCallback, useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import { PANEL_BODY_CLASS, PANEL_TITLE_CLASS } from "./controls";

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Which shells are open, oldest first.
 *
 * The reveal flow really does stack two: a step-up opens over a reveal that is waiting for
 * it. Without this, both would answer the same Escape and both would trap Tab — the one
 * underneath winning the fight, because its listener runs first and pulls focus back out of
 * the password field. Only the top of the stack listens.
 */
const openShells: symbol[] = [];

export interface DialogShellProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** A request this dialog started is in flight. Closing is refused until it answers. */
  readonly isBusy?: boolean | undefined;
  readonly title: string;
  /** One line under the title. Say what this dialog is FOR, not what it looks like. */
  readonly description?: ReactNode;
  readonly icon?: ReactNode;
  readonly children: ReactNode;
  /** Buttons. The primary comes first: it is the action, not the escape hatch. */
  readonly footer?: ReactNode;
  readonly testId?: string;
  readonly className?: string | undefined;
}

export function DialogShell({
  isOpen,
  onClose,
  isBusy = false,
  title,
  description,
  icon,
  children,
  footer,
  testId,
  className,
}: DialogShellProps) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<Element | null>(null);
  const idRef = useRef<symbol>(Symbol("dialog"));
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!isOpen) return;
    const id = idRef.current;
    openShells.push(id);
    return () => {
      const at = openShells.lastIndexOf(id);
      if (at !== -1) openShells.splice(at, 1);
    };
  }, [isOpen]);

  const isTopmost = useCallback((): boolean => openShells.at(-1) === idRef.current, []);

  const focusables = useCallback((): readonly HTMLElement[] => {
    const panel = panelRef.current;
    if (panel === null) return [];
    return [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
      (element) => element.offsetParent !== null || element === document.activeElement,
    );
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    restoreRef.current = document.activeElement;
    // The first field, not the panel: the operator was sent here to type something, and one
    // extra keystroke to reach the field is one more chance to lose the thread of a call.
    const first = focusables()[0] ?? panelRef.current;
    first?.focus();

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      const restore = restoreRef.current;
      if (restore instanceof HTMLElement) restore.focus();
    };
  }, [isOpen, focusables]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      // The shell underneath a step-up stays mounted and stays visible; it just stops
      // answering the keyboard until the panel above it closes.
      if (!isTopmost()) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        // A charged, audited disclosure is on its way back; Escape must not throw it away.
        if (!isBusy) onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusables();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (first === undefined || last === undefined) return;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === panelRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, [isOpen, onClose, isBusy, focusables, isTopmost]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-6">
      {/* Inert by design: a stray click on the scrim must not throw away a written reason or
          close a panel that is currently showing plaintext somebody is reading out. */}
      <div className="fixed inset-0 bg-overlay" aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal
        aria-labelledby={titleId}
        {...(description === undefined ? {} : { "aria-describedby": descriptionId })}
        data-testid={testId}
        tabIndex={-1}
        className={cn(
          "relative my-[6vh] flex max-h-[86vh] w-full max-w-[44rem] flex-col overflow-hidden",
          "rounded-panel border border-stroke bg-card shadow-panel outline-none",
          className,
        )}
      >
        <header className="flex items-start gap-3 border-b border-stroke px-6 pb-4 pt-6">
          {icon === undefined ? null : <span className="mt-[3px] shrink-0">{icon}</span>}
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <h2 id={titleId} className={PANEL_TITLE_CLASS}>
              {title}
            </h2>
            {description === undefined ? null : (
              <p id={descriptionId} className={PANEL_BODY_CLASS}>
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            aria-label={t("common.close")}
            className={cn(
              "shrink-0 rounded-button border border-stroke px-2 py-1 text-[18px] leading-6 text-ink-500",
              "transition-[filter] hover:brightness-95",
              "disabled:cursor-not-allowed disabled:text-ink-300 disabled:hover:brightness-100",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
            )}
          >
            <span aria-hidden>×</span>
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          {children}
        </div>

        {footer === undefined ? null : (
          <footer className="flex flex-wrap items-center gap-3 border-t border-stroke px-6 py-4">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

/**
 * The one place a refusal is drawn, so that a 403 on role, a 429 and a transport failure all
 * look like the same class of thing — a statement — instead of three different alarms.
 */
export type NoticeTone = "refusal" | "caution" | "quiet";

const NOTICE_GROUND: Readonly<Record<NoticeTone, string>> = {
  refusal: "bg-required-06 ring-required-24",
  caution: "bg-bg ring-stroke",
  quiet: "bg-bg ring-stroke",
};

const NOTICE_INK: Readonly<Record<NoticeTone, string>> = {
  refusal: "text-required-deep",
  caution: "text-warn-deep",
  quiet: "text-ink-900",
};

export function Notice({
  tone,
  title,
  children,
  testId,
  code,
}: {
  readonly tone: NoticeTone;
  readonly title: string;
  readonly children?: ReactNode;
  readonly testId?: string;
  /** The wire code, printed verbatim: it is what an operator greps and pastes. */
  readonly code?: string | undefined;
}) {
  return (
    <div
      // A refusal and a warning interrupt; a statement of fact does not. Announcing the cost
      // line every time a checkbox moves would make the alerts worthless.
      {...(tone === "quiet" ? {} : { role: "alert" })}
      data-testid={testId}
      className={cn(
        "flex flex-col gap-1.5 rounded-card p-4 ring-1 ring-inset",
        NOTICE_GROUND[tone],
      )}
    >
      <p className={cn("text-[14px] font-semibold leading-5 tracking-[-0.1px]", NOTICE_INK[tone])}>
        {title}
      </p>
      {children === undefined ? null : (
        <div className="flex flex-col gap-1.5 text-[13px] font-normal leading-[18px] text-ink-500">
          {children}
        </div>
      )}
      {code === undefined ? null : (
        <p className="text-[11px] leading-4 text-ink-300">
          <span className="font-mono">{code}</span>
        </p>
      )}
    </div>
  );
}
