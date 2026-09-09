/**
 * `<MaskedValue>` — one personal field, in whichever of its four states is the true one.
 *
 * Everything personal arrives masked and is rendered masked. This component is the only place
 * that changes, and it distinguishes four facts that a lazier component would render alike:
 *
 *  - **masked** — the twin the server sent (`•••`, last two digits, first grapheme). With a
 *    reveal affordance beside it, for a role that holds the cell.
 *  - **revealed** — plaintext, in this component's state, with a way to put it back. It is
 *    dropped on unmount and on sign-out; nothing caches it, stores it or logs it.
 *  - **purged** — `identityPurgedAt`/`textPurgedAt` is set. "purged 2026-05-14", and NO
 *    affordance: there is nothing behind the button, and a reveal that cannot succeed is
 *    worse than no button. A blank would read as a rendering bug and send support hunting for
 *    a value the system deliberately destroyed.
 *  - **not permitted** — a role with no reveal cell sees the masked value and nothing else.
 *    Not a greyed button, not a tooltip: pressing it would write a `permission.denied` audit
 *    row against somebody who did nothing wrong, and teach them the console is broken.
 *
 * A fifth case hides inside the first: a masked twin of `null` means the COLUMN IS NULL.
 * There is no plaintext behind it, so it gets no affordance either — spending a step-up, a
 * budget unit and an audit row to be told "nothing" is the reveal this component exists to
 * prevent.
 */

import { useEffect, useState } from "react";

import { REVEAL_FIELD_SUBJECTS, type RevealField, type RevealResponse } from "@/api/reveal";
import { cn } from "@/lib/cn";
import { useCanReveal } from "@/lib/rbac";
import { useAuthStore } from "@/state/auth";

import { useI18n } from "@/i18n";

import { CELL_PRIMARY_CLASS } from "./controls";
import { RevealDialog } from "./RevealDialog";
import { formatRevealedValue, REVEAL_FIELD_LABEL_KEYS, revealedValuesOf } from "./revealFields";

/** What a field with no value renders as. Not a blank — a blank reads as a bug. */
export const EMPTY_VALUE = "—";

/**
 * A retention stamp, drawn wherever one is set — with no affordance beside it.
 *
 * Its own component because a purged value is reached by two paths (a revealable cell, and a
 * cell with no subject to reveal against) and the two drifting apart would leave one of them
 * rendering a blank, which reads as a rendering fault rather than as a value the system
 * deliberately destroyed on schedule.
 */
export function PurgedValue({
  purgedAt,
  className,
}: {
  readonly purgedAt: string;
  readonly className?: string | undefined;
}) {
  return (
    <span
      data-testid="masked-value-purged"
      data-purged-at={purgedAt}
      className={cn("whitespace-nowrap text-[12px] leading-4 text-ink-400", className)}
    >
      {`🔒 purged ${purgedAt.slice(0, 10)}`}
    </span>
  );
}

export interface MaskedValueProps {
  /** The masked twin, verbatim from the wire. `null` means the column itself is NULL. */
  readonly masked: string | null;
  /** Which column a reveal would ask for. Its subject type comes from the spec, not a prop. */
  readonly field: RevealField;
  /**
   * The reveal subject's UUID — `UserView.id` for a profile column, the order's id for a
   * brief or attempt column. NOT the Telegram id: that is what block and grant are keyed on,
   * and passing it here is a 404 or, worse, a reveal of the wrong subject.
   */
  readonly subjectId: string;
  /** OUR words for the subject, for the dialog's title. Never customer content. */
  readonly subjectLabel: string;
  /**
   * Which RECORD of a paged reveal this cell is. `generation_attempts.*` columns are subject-
   * typed `order`, so one reveal returns a record per take of that order — and the take this
   * cell belongs to is identified by its attempt id, never by its position in the page.
   * Omitted for a `single`-shaped column, which has exactly one record.
   */
  readonly recordId?: string | undefined;
  /** The retention stamp covering this value, when the row carries one. */
  readonly purgedAt?: string | null | undefined;
  readonly className?: string | undefined;
}

export function MaskedValue({
  masked,
  field,
  subjectId,
  subjectLabel,
  recordId,
  purgedAt = null,
  className,
}: MaskedValueProps) {
  const { t } = useI18n();
  const canReveal = useCanReveal();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  /**
   * The plaintext. Component state and nothing else: no query key, no store, no storage, no
   * URL. It dies with this cell, which is the whole of its retention policy.
   */
  const [plaintext, setPlaintext] = useState<string | null>(null);

  const status = useAuthStore((state) => state.status);
  useEffect(() => {
    // The session that authorised this disclosure is over; a cell still showing what it
    // bought would be a disclosure with no live authorisation behind it.
    if (status !== "authed") setPlaintext(null);
  }, [status]);

  useEffect(() => {
    // The cell is now pointed at a different subject, column or record — a cached user or
    // attempt swapped in under a panel that was re-rendered rather than remounted. Plaintext
    // was bought for ONE subject and one reason; kept here it would be drawn under another
    // person's masked field, with the audit row naming somebody else entirely.
    setPlaintext(null);
    setIsDialogOpen(false);
  }, [subjectId, field, recordId, masked]);

  if (purgedAt !== null) return <PurgedValue purgedAt={purgedAt} className={className} />;

  if (plaintext !== null) {
    return (
      <span className={cn("inline-flex items-center gap-2", className)}>
        {/* One text node, untouched: no trim, no case fold, no text-transform. The operator is
            reading this back to a customer or comparing it against a ticket. */}
        <span
          dir="ltr"
          data-testid="masked-value-plaintext"
          data-field={field}
          className="whitespace-pre-wrap break-words text-[14px] leading-5 text-ink-900"
        >
          {plaintext}
        </span>
        <button
          type="button"
          onClick={() => setPlaintext(null)}
          className="shrink-0 rounded-button border border-stroke px-2 py-0.5 text-[11px] leading-4 text-ink-500 transition-[filter] hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep"
        >
          Hide
        </button>
      </span>
    );
  }

  const maskedText = masked ?? EMPTY_VALUE;
  // No twin means no value behind it, and a role with no cell gets no affordance at all.
  const isRevealable = canReveal && masked !== null;

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span data-testid="masked-value" className={cn(CELL_PRIMARY_CLASS, "break-words")}>
        {maskedText}
      </span>
      {isRevealable ? (
        <>
          <button
            type="button"
            data-testid="masked-value-reveal"
            aria-label={t("reveal.revealFieldAria", { field: t(REVEAL_FIELD_LABEL_KEYS[field]) })}
            onClick={() => setIsDialogOpen(true)}
            className="shrink-0 rounded-button border border-stroke px-2 py-0.5 text-[11px] leading-4 text-ink-800 transition-[filter] hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep"
          >
            {t("reveal.revealButton")}
          </button>
          <RevealDialog
            isOpen={isDialogOpen}
            onClose={() => setIsDialogOpen(false)}
            subjectType={REVEAL_FIELD_SUBJECTS[field]}
            subjectId={subjectId}
            subjectLabel={subjectLabel}
            // Only this column is offered here. Its group-mates cost the same single record,
            // which the dialog says — but a cell's affordance should ask for the cell's value,
            // and an operator who wants the whole brief opens the dialog from the brief.
            fields={[field]}
            onRevealed={(result: RevealResponse) => {
              const values = revealedValuesOf(result, field);
              // A paged column returns a record per take of the subject, newest first, so
              // position 0 is the NEWEST take and not this cell's. This cell's take is named
              // by `recordId`; when the page does not carry it, the cell stays masked and the
              // dialog's record list — which prints every record id — is the answer. A
              // single-shaped column has exactly one record and no id to match.
              const mine =
                recordId === undefined
                  ? values[0]
                  : values.find((value) => value.recordId === recordId);
              if (mine === undefined || mine.value === null) return;
              setPlaintext(formatRevealedValue(mine.value));
            }}
          />
        </>
      ) : null}
    </span>
  );
}
