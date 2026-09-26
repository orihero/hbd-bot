import { useEffect, useId, useRef, type JSX, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

/**
 * The modal the privileged actions are confirmed in — block, unblock, grant, reveal.
 *
 * Hand-rolled rather than Radix, because this app has no Radix dependency and adding one to
 * get a focus trap is a bigger change than the trap. Everything Radix would have provided is
 * here and is required, not decorative:
 *
 *   - `role="dialog"` + `aria-modal`, named by its own heading and described by its body.
 *   - Focus moves INTO the dialog on open (to the reason field when there is one, otherwise to
 *     Cancel — never to the destructive button, which would let a stray Enter fire it).
 *   - Focus cannot leave: Tab cycles, and a `focusin` anywhere outside pulls it back, which is
 *     the case a Tab-only trap misses after a click on the scrim.
 *   - Escape closes, and focus RETURNS to whatever opened the dialog, so the operator is back
 *     on the row they pressed rather than at the top of the document.
 *
 * Two rules come from the API rather than from accessibility:
 *
 * 1. **The confirm button carries the verb.** "Block user", "Grant 5 credits", "Reveal phone
 *    number" — never "OK". These write an audit row that names the operator for 730 days; the
 *    button has to say what is about to be recorded.
 * 2. **Nothing closes while a request is in flight.** Escape, the scrim and Cancel all rest
 *    during `isPending`. A grant that is retried on the same idempotency key answers 200 with
 *    `isReplay: true` and NOTHING MOVED, and the only place that fact can be read is the
 *    result of the call this dialog is waiting on. Closing over it turns "already granted" into
 *    an operator pressing the button a second time.
 *
 * The reason field is built in because `reasonCode` is required by every one of these routes
 * and a body without one is a 422 that writes NO audit row — the wrong way to fail a
 * privileged action. The screen still owns the reason CODE (a fixed vocabulary); this handles
 * the free text beside it and refuses to confirm while a required one is blank.
 */

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export interface ConfirmDialogReason {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder?: string | undefined;
  /** Said before the operator types, not after the server refuses. */
  readonly hint?: string | undefined;
  /** Cap the INPUT at the server's limit; a truncated body is a 422 nobody can see. */
  readonly maxLength?: number | undefined;
  /** Defaults to required — that is why the field is here at all. */
  readonly isRequired?: boolean | undefined;
  /** A client-side validation message. Shown under the field and blocks the confirm. */
  readonly error?: string | undefined;
}

interface ConfirmDialogProps {
  readonly isOpen: boolean;
  readonly title: string;
  /** What the action does and what it costs. The first thing read after the heading. */
  readonly description?: ReactNode;
  /** Anything else the decision needs: the reason-code select, a budget meter, a preview. */
  readonly children?: ReactNode;
  /** THE VERB. "Block user", never "Confirm". */
  readonly confirmLabel: string;
  readonly cancelLabel?: string;
  /** `danger` for a write the customer will feel. */
  readonly tone?: "danger" | "default";
  readonly reason?: ConfirmDialogReason | undefined;
  readonly isPending?: boolean;
  /** What the button says while the request is out. "Blocking…". */
  readonly pendingLabel?: string | undefined;
  /** For a precondition this dialog cannot see — an unchosen reason code, a cost over budget. */
  readonly isConfirmDisabled?: boolean;
  /** The failure of the last attempt. An `<ErrorNote>` belongs here. */
  readonly error?: ReactNode;
  readonly onConfirm: () => void;
  readonly onClose: () => void;
}

export function ConfirmDialog({
  isOpen,
  title,
  description,
  children,
  confirmLabel,
  cancelLabel,
  tone = "default",
  reason,
  isPending = false,
  pendingLabel,
  isConfirmDisabled = false,
  error,
  onConfirm,
  onClose,
}: ConfirmDialogProps): JSX.Element | null {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const ids = useId();
  const titleId = `${ids}-title`;
  const descriptionId = `${ids}-description`;
  const reasonId = `${ids}-reason`;
  const reasonHintId = `${ids}-reason-hint`;

  /* Remember the trigger, and give focus back to it on close. Both halves in one effect so
     they cannot drift apart. */
  useEffect(() => {
    if (!isOpen) return;
    const active = document.activeElement;
    restoreRef.current = active instanceof HTMLElement ? active : null;
    return () => {
      const trigger = restoreRef.current;
      restoreRef.current = null;
      if (trigger !== null && trigger.isConnected) trigger.focus();
    };
  }, [isOpen]);

  /* Move focus in. The reason field when there is one; otherwise Cancel, marked by the caller
     of `data-autofocus` below — never the destructive button. */
  useEffect(() => {
    if (!isOpen) return;
    const node = dialogRef.current;
    if (node === null) return;
    const target =
      node.querySelector<HTMLElement>("[data-autofocus]") ??
      node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (target ?? node).focus();
  }, [isOpen]);

  /* Escape, and the focus fence. The fence catches what a Tab-only trap misses: a click on the
     scrim leaves focus on <body>, from where Tab walks back out into the page behind. */
  useEffect(() => {
    if (!isOpen) return;

    function onKeyDown(event: globalThis.KeyboardEvent): void {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      if (!isPending) onClose();
    }

    function onFocusIn(event: FocusEvent): void {
      const node = dialogRef.current;
      if (node === null) return;
      const target = event.target;
      if (target instanceof Node && node.contains(target)) return;
      const first = node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (first ?? node).focus();
    }

    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [isOpen, isPending, onClose]);

  /* The page behind must not scroll under the scrim. The previous value is restored rather than
     cleared, so a nested overlay does not un-lock the one below it. */
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const isReasonRequired = reason !== undefined && reason.isRequired !== false;
  const isReasonBlank = isReasonRequired && reason.value.trim() === "";
  const hasReasonError = reason?.error !== undefined && reason.error !== "";
  const canConfirm = !isPending && !isConfirmDisabled && !isReasonBlank && !hasReasonError;

  function onTabKey(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== "Tab") return;
    const node = dialogRef.current;
    if (node === null) return;
    const focusables = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (first === undefined || last === undefined) {
      event.preventDefault();
      node.focus();
      return;
    }
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === node)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onScrimMouseDown(event: MouseEvent<HTMLDivElement>): void {
    if (event.target !== event.currentTarget) return;
    if (isPending) return;
    onClose();
  }

  return createPortal(
    <div
      onMouseDown={onScrimMouseDown}
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-overlay p-4"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description === undefined ? undefined : descriptionId}
        aria-busy={isPending}
        tabIndex={-1}
        onKeyDown={onTabKey}
        className="w-full max-w-[440px] rounded-panel border border-stroke bg-card p-6 shadow-panel outline-none"
      >
        <h2
          id={titleId}
          className="m-0 text-[22px] font-semibold leading-[30.052px] tracking-[-0.44px] text-ink-900"
        >
          {title}
        </h2>

        {description === undefined ? null : (
          <div
            id={descriptionId}
            className="mt-2 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500"
          >
            {description}
          </div>
        )}

        {children === undefined ? null : <div className="mt-4">{children}</div>}

        {reason === undefined ? null : (
          <div className="mt-4">
            <label
              htmlFor={reasonId}
              className="block text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-label"
            >
              {reason.label}
              {isReasonRequired ? (
                <span className="text-required" aria-hidden>
                  {" *"}
                </span>
              ) : null}
            </label>
            {reason.hint === undefined ? null : (
              <p
                id={reasonHintId}
                className="m-0 mt-1 text-[11px] font-normal leading-[1.35] text-ink-400"
              >
                {reason.hint}
              </p>
            )}
            <textarea
              id={reasonId}
              value={reason.value}
              onChange={(event) => reason.onChange(event.target.value)}
              placeholder={reason.placeholder}
              maxLength={reason.maxLength}
              required={isReasonRequired}
              aria-required={isReasonRequired}
              aria-invalid={hasReasonError}
              aria-describedby={reason.hint === undefined ? undefined : reasonHintId}
              disabled={isPending}
              rows={3}
              data-autofocus
              className={cn(
                "mt-2 block w-full resize-y rounded-field border bg-card px-3 py-2",
                "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-900",
                "placeholder:text-ink-300",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
                "disabled:cursor-not-allowed disabled:bg-bg",
                hasReasonError ? "border-required" : "border-stroke",
              )}
            />
            {hasReasonError ? (
              <p className="m-0 mt-1 text-[11px] font-semibold leading-[1.35] text-required-deep">
                {reason.error}
              </p>
            ) : null}
          </div>
        )}

        {error === undefined ? null : <div className="mt-4">{error}</div>}

        <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            data-autofocus={reason === undefined ? true : undefined}
            className={cn(
              "flex h-12 cursor-pointer items-center rounded-button border border-stroke bg-card px-4 py-3",
              "text-[18px] font-medium leading-[24.588px] tracking-[-0.36px] text-ink-800",
              "transition-colors hover:bg-bg",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
              "disabled:cursor-not-allowed disabled:opacity-45",
            )}
          >
            {cancelLabel ?? t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            className={cn(
              "flex h-12 cursor-pointer items-center rounded-button px-4 py-3",
              "text-[18px] font-medium leading-[24.588px] tracking-[-0.36px]",
              "transition-[color,background-color,filter] hover:brightness-95 active:brightness-90",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
              "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:brightness-100",
              tone === "danger" ? "bg-required-deep text-card" : "bg-accent text-on-accent",
            )}
          >
            {isPending && pendingLabel !== undefined ? pendingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
