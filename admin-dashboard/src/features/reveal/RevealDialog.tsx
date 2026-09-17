/**
 * `<RevealDialog>` — the one control in this console that turns masked data into plaintext.
 *
 * Four things it owes the operator, and each is a failure that has happened somewhere else:
 *
 * 1. **The cost is on screen before the confirm**, measured against the budget the server
 *    last reported. That is what makes the ceiling a policy somebody can work inside instead
 *    of a surprise 429 on the third of five records they were reading down a phone line. It
 *    is possible only because the charge is deterministic: one record for a single-shaped
 *    reveal however many columns it names, the page size for a paged one, both before the
 *    read.
 * 2. **No reason code, no confirm.** The server answers 422, and a form that leans on that to
 *    tell the operator has decided accountability is somebody else's problem.
 * 3. **A step-up refusal routes into re-authentication and back**, not into a dead error —
 *    and it says that nothing was charged, because it was not.
 * 4. **A budget refusal names WHICH ceiling and WHEN it resets.** The two have different
 *    windows and spending one never spends the other; "you have run out" is a support ticket.
 *
 * And one it owes the customer: the plaintext lives in `useReveal`'s state, is dropped when
 * this dialog closes, and is never written to a cache, a URL, storage or a log.
 */

import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  MAX_RECORDS_PER_REVEAL,
  MAX_REASON_REF_CHARS,
  MAX_REASON_TEXT_CHARS,
  REASON_REF_PATTERN,
} from "@/api/constants";
import {
  AUDIT_REASON_CODE_VALUES,
  revealShapeOf,
  type AuditReasonCode,
  type RevealedRecord,
  type RevealField,
  type RevealRequest,
  type RevealResponse,
  type RevealSubjectType,
} from "@/api/reveal";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import {
  CELL_SECONDARY_CLASS,
  FIELD_CONTROL_CLASS,
  MONO_CLASS,
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SECTION_LABEL_CLASS,
  TEXTAREA_CONTROL_CLASS,
} from "./controls";
import { DialogShell, Notice } from "./DialogShell";
import {
  canSubmitReveal,
  describeRevealCost,
  orderFields,
  revealCost,
  revealFieldsFor,
  revealGroupsFor,
  REVEAL_FIELD_HINT_KEYS,
  REVEAL_FIELD_LABEL_KEYS,
  REVEAL_REASON_KEYS,
  REVEAL_SHAPE_KEYS,
  type RevealFieldGroup,
} from "./revealFields";
import { StepUpDialog } from "./StepUpDialog";
import {
  budgetScopeKey,
  describeRetryAfter,
  revealFailureAdvice,
  REVEAL_IS_AUDITED_NOTE,
  ROLE_REFUSAL_NOTE,
  useReveal,
  type RevealFlow,
} from "./useReveal";

const FORM_ID = "reveal-form";

/** Withheld until a reason is chosen, and this says why rather than leaving it to a 422. */
export const REASON_REQUIRED_HINT =
  "Choose a reason code. It is required, it goes on the audit row, and the server refuses the reveal without one.";

/** The `reasonRef` shape the audit boundary reads as a credential and refuses. */
export const LONG_REF_WARNING =
  "40 or more characters of letters, digits, _ and - reads as a credential to the audit boundary, and the reveal will be refused before it is charged. Shorten it, or add a # or another separator.";

/** Offered page sizes. The largest is the server's own cap and its default. */
const PAGE_SIZES: readonly number[] = [5, 10, 25, MAX_RECORDS_PER_REVEAL];

/** `audit._CREDENTIAL_SHAPES` — a 40-character run of that alphabet is refused. */
const CREDENTIAL_SHAPE = /[A-Za-z0-9_-]{40,}/;

export interface RevealDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly subjectType: RevealSubjectType;
  /**
   * The UUID the server will compare the step-up scope against. For a customer this is
   * `UserView.id`, NOT the Telegram id the block and grant routes are keyed on.
   */
  readonly subjectId: string;
  /** OUR words for the subject — an order reference, a masked Telegram id. Never a name. */
  readonly subjectLabel: string;
  /** The columns this surface offers. Defaults to every column of this subject. */
  readonly fields?: readonly RevealField[];
  /**
   * Handed the plaintext when it lands, so a caller (`<MaskedValue>`) can show it in place.
   *
   * Whatever receives this must hold it in component state and drop it on unmount. It must
   * not be cached, stored, logged or put in a URL: it was bought with a step-up, a budget
   * unit and an audit row naming one operator, one subject and one reason.
   */
  readonly onRevealed?: ((result: RevealResponse) => void) | undefined;
}

export function RevealDialog({
  isOpen,
  onClose,
  subjectType,
  subjectId,
  subjectLabel,
  fields,
  onRevealed,
}: RevealDialogProps) {
  const { t } = useI18n();
  const offered = useMemo(
    // Only this subject's columns, ever. The server checks the subject before it checks
    // anything else, and a dialog that cannot offer a foreign column cannot build the
    // request that would charge a step-up on one table's id to read another's.
    () => (fields ?? revealFieldsFor(subjectType)).filter((field) => offeredFor(field, subjectType)),
    [fields, subjectType],
  );

  const [chosen, setChosen] = useState<ReadonlySet<RevealField>>(() => new Set<RevealField>());
  const [reasonCode, setReasonCode] = useState<AuditReasonCode | null>(null);
  const [reasonRef, setReasonRef] = useState("");
  const [reasonText, setReasonText] = useState("");
  const [limit, setLimit] = useState<number>(MAX_RECORDS_PER_REVEAL);

  const flow = useReveal();
  const { forget, result } = flow;

  useEffect(() => {
    // A reopened dialog starts clean. Carrying a previous subject's reason code — or, far
    // worse, its plaintext — into the next investigation is how the wrong record gets quoted
    // into a ticket.
    if (isOpen) return;
    forget();
    setChosen(new Set<RevealField>());
    setReasonCode(null);
    setReasonRef("");
    setReasonText("");
    setLimit(MAX_RECORDS_PER_REVEAL);
  }, [isOpen, forget]);

  const reportedRef = useRef<RevealResponse | null>(null);
  useEffect(() => {
    // Once per result. `onRevealed` is usually an inline arrow, so a bare dependency on it
    // would hand the same plaintext to the caller on every render — harmless today, and
    // exactly the kind of "why is this firing" that gets fixed by caching it somewhere.
    if (result === null || reportedRef.current === result) return;
    reportedRef.current = result;
    onRevealed?.(result);
  }, [result, onRevealed]);

  const selected = useMemo(() => orderFields(offered, chosen), [offered, chosen]);
  const shape = revealShapeOf(selected);
  const cost = revealCost(selected, shape === "paged" ? limit : null);
  const isRefMalformed = reasonRef !== "" && !REASON_REF_PATTERN.test(reasonRef);
  const isRefCredentialShaped = CREDENTIAL_SHAPE.test(reasonRef);
  const canConfirm =
    canSubmitReveal({ fields: selected, reasonCode }) && !isRefMalformed && !flow.isPending;

  function send(cursor: string | null): void {
    if (reasonCode === null || shape === null) return;
    const body: RevealRequest = {
      subjectType,
      subjectId,
      fields: [...selected],
      reasonCode,
      ...(reasonRef === "" ? {} : { reasonRef }),
      ...(reasonText === "" ? {} : { reasonText }),
      // `limit` and `cursor` are refused on a single-record reveal: a page control on
      // something with no pages teaches a caller to expect one.
      ...(shape === "paged" ? { limit } : {}),
      ...(cursor === null ? {} : { cursor }),
    };
    flow.request(body);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!canConfirm) return;
    send(null);
  }

  const phase = flow.phase;
  /*
   * The form stays mounted through every refusal, and only a RESULT replaces it.
   *
   * A refusal is a thing the operator can often act on — drop the page size after a budget
   * 429, fix a `reasonRef` after a 422, try again after the counter store answers — and
   * unmounting the form would make them close the dialog and retype a reason they had
   * already written. The step-up is the one phase drawn over the top of it rather than
   * beside it, because it is a different credential and deserves the whole panel.
   */
  const isChoosing = result === null;

  return (
    <>
      <DialogShell
        isOpen={isOpen}
        onClose={onClose}
        isBusy={flow.isPending}
        testId="reveal-dialog"
        title={t("reveal.dialog.title", { subjectType, subjectLabel })}
        description={REVEAL_IS_AUDITED_NOTE}
        footer={
          result === null ? (
            <>
              <button
                type="submit"
                form={FORM_ID}
                disabled={!canConfirm}
                data-testid="reveal-confirm"
                className={PRIMARY_BUTTON_CLASS}
              >
                {flow.isPending
                  ? t("reveal.dialog.pending")
                  : t("reveal.dialog.confirm", { cost: describeRevealCost(cost, t) })}
              </button>
              <button
                type="button"
                onClick={onClose}
                disabled={flow.isPending}
                className={SECONDARY_BUTTON_CLASS}
              >
                {t("common.cancel")}
              </button>
              {reasonCode === null ? (
                <span data-testid="reveal-reason-required" className="text-[12px] leading-4 text-ink-400">
                  {REASON_REQUIRED_HINT}
                </span>
              ) : null}
            </>
          ) : (
            <>
              {result.nextCursor === null ? null : (
                <button
                  type="button"
                  disabled={flow.isPending}
                  data-testid="reveal-next-page"
                  onClick={() => send(result.nextCursor)}
                  className={PRIMARY_BUTTON_CLASS}
                >
                  {t("reveal.dialog.nextPage", { cost: describeRevealCost(cost, t) })}
                </button>
              )}
              <button type="button" onClick={onClose} className={SECONDARY_BUTTON_CLASS}>
                Done
              </button>
            </>
          )
        }
      >
        <BudgetLine flow={flow} />

        {phase.kind === "budget" ? (
          <Notice
            tone="refusal"
            testId="reveal-budget-exhausted"
            title={t("reveal.dialog.budgetSpentTitle", {
              scope: t(budgetScopeKey(phase.refusal)),
            })}
            code={phase.failure.code}
          >
            <p>
              {phase.refusal.recordsRequested === null
                ? t("reveal.dialog.recordsUnknown")
                : t("reveal.dialog.recordsAsked", { count: phase.refusal.recordsRequested })}
              {phase.refusal.recordsRemaining === null
                ? ""
                : t("reveal.dialog.recordsLeft", { count: phase.refusal.recordsRemaining })}
              {phase.refusal.conversationsRemaining === null
                ? ""
                : t("reveal.dialog.conversationsLeft", {
                    count: phase.refusal.conversationsRemaining,
                  })}
            </p>
            <p>
              {describeRetryAfter(phase.refusal.retryAfterS, t) === null
                ? t("reveal.dialog.noCountdown")
                : t("reveal.dialog.windowResets", {
                    delay: describeRetryAfter(phase.refusal.retryAfterS, t) ?? "",
                  })}
              {t("reveal.dialog.ceilingsSeparate")}
            </p>
            <p>{t("reveal.dialog.nothingCharged")}</p>
          </Notice>
        ) : null}

        {phase.kind === "refused" ? (
          <Notice
            tone="refusal"
            testId="reveal-failure"
            title={
              phase.isRoleRefusal ? t("reveal.dialog.roleRefused") : t("reveal.dialog.refused")
            }
            code={
              phase.failure.correlationId === null
                ? phase.failure.code
                : `${phase.failure.code} · ${phase.failure.correlationId}`
            }
          >
            <p>{phase.failure.message}</p>
            {phase.failure.code === "STEP_UP_REQUIRED" ? <p>{ROLE_REFUSAL_NOTE}</p> : null}
            {revealFailureAdvice(phase.failure) === null ? null : (
              <p>{revealFailureAdvice(phase.failure)}</p>
            )}
          </Notice>
        ) : null}

        {phase.kind === "stepUp" ? (
          <Notice
            tone="quiet"
            testId="reveal-step-up-pending"
            title={t("reveal.dialog.stepUpPendingTitle")}
          >
            <p>
              {t("reveal.dialog.stepUpAsk", {
                cost: describeRevealCost(cost, t),
                subjectType,
                subjectLabel,
              })}
            </p>
          </Notice>
        ) : null}

        {isChoosing ? (
          <form id={FORM_ID} onSubmit={handleSubmit} className="flex flex-col gap-5" noValidate>
            <FieldChooser
              groups={revealGroupsFor(subjectType)}
              offered={offered}
              chosen={chosen}
              onToggle={(field) =>
                setChosen((current) => {
                  const next = new Set(current);
                  if (!next.delete(field)) next.add(field);
                  return next;
                })
              }
            />

            {shape === "paged" ? <PageSizeChooser limit={limit} onLimit={setLimit} /> : null}

            <ReasonFields
              reasonCode={reasonCode}
              onReasonCode={setReasonCode}
              reasonRef={reasonRef}
              onReasonRef={setReasonRef}
              reasonText={reasonText}
              onReasonText={setReasonText}
              isRefMalformed={isRefMalformed}
              isRefCredentialShaped={isRefCredentialShaped}
            />

            <CostSummary
              shapeLabel={shape === null ? null : t(REVEAL_SHAPE_KEYS[shape])}
              costLabel={describeRevealCost(cost, t)}
              isMixed={selected.length > 0 && shape === null}
            />
          </form>
        ) : null}

        {result === null ? null : (
          <RevealedRecords subjectType={subjectType} result={result} />
        )}
      </DialogShell>

      <StepUpDialog
        isOpen={isOpen && phase.kind === "stepUp"}
        // Cancelling the re-authentication drops back to the form with the reason and the
        // ticked columns still there, rather than closing everything: the operator declined
        // to re-authenticate, they did not abandon the investigation. Nothing was charged.
        onClose={forget}
        action={phase.kind === "stepUp" ? phase.target.action : "reveal"}
        // Byte-identical to what the handler compared: straight off the refusal's details.
        subjectId={phase.kind === "stepUp" ? phase.target.subjectId : subjectId}
        subjectLabel={`${subjectType} ${subjectLabel}`}
        note={t("reveal.dialog.stepUpNote", {
          cost: describeRevealCost(cost, t),
          subjectType,
        })}
        onGranted={() => {
          // The grant authorises an action on a subject, not a request: the server has no
          // memory of what was being attempted, so the same body goes again unchanged.
          flow.retry();
        }}
      />
    </>
  );
}

/** Whether a column belongs to this subject. The dialog offers nothing else. */
function offeredFor(field: RevealField, subjectType: RevealSubjectType): boolean {
  return revealFieldsFor(subjectType).includes(field);
}

/* -------------------------------------------------------------------------- */
/* Pieces                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * What the server last said is left.
 *
 * `null` is NOT zero — it means that counter was not touched by the last reveal, and a meter
 * that printed "0 left" for "not asked" would talk an operator out of work they are entitled
 * to do. Before the first reveal of a session there is no measurement at all, and saying so
 * is more useful than implying a full budget.
 */
function BudgetLine({ flow }: { readonly flow: RevealFlow }) {
  const { t } = useI18n();
  const budget = flow.budget;
  return (
    <p data-testid="reveal-budget" className="text-[12px] leading-4 text-ink-400">
      {budget === null
        ? t("reveal.dialog.budgetNotMeasured")
        : [
            budget.recordsRemaining === null
              ? t("reveal.dialog.recordsNotTouched")
              : t("reveal.dialog.budgetRecords", { count: budget.recordsRemaining }),
            budget.conversationsRemaining === null
              ? t("reveal.dialog.conversationsNotTouched")
              : t("reveal.dialog.budgetConversations", {
                  count: budget.conversationsRemaining,
                }),
          ].join(" · ")}
    </p>
  );
}

function FieldChooser({
  groups,
  offered,
  chosen,
  onToggle,
}: {
  readonly groups: readonly RevealFieldGroup[];
  readonly offered: readonly RevealField[];
  readonly chosen: ReadonlySet<RevealField>;
  readonly onToggle: (field: RevealField) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="flex flex-col gap-4">
      {groups.map((group) => {
        const fields = group.fields.filter((field) => offered.includes(field));
        if (fields.length === 0) return null;
        return (
          <fieldset key={group.key} className="flex flex-col gap-2">
            <legend className={SECTION_LABEL_CLASS}>{group.title}</legend>
            <p className="text-[12px] leading-4 text-ink-400">{group.note}</p>
            {fields.map((field) => (
              <label
                key={field}
                className="flex items-start gap-2 rounded-card px-2 py-1.5 hover:bg-row-hover"
              >
                <input
                  type="checkbox"
                  checked={chosen.has(field)}
                  onChange={() => onToggle(field)}
                  className="mt-[3px] h-4 w-4 shrink-0 accent-accent-deep"
                />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-[14px] font-medium leading-5 text-ink-900">
                    {t(REVEAL_FIELD_LABEL_KEYS[field])}
                  </span>
                  <span className="text-[12px] leading-4 text-ink-400">
                    {t(REVEAL_FIELD_HINT_KEYS[field])}
                  </span>
                  {/* The column name verbatim: it is what lands in the audit row's
                      `field_names`, and an operator reading /audit later has to recognise it. */}
                  <span className={cn(MONO_CLASS, "text-ink-300")}>{field}</span>
                </span>
              </label>
            ))}
          </fieldset>
        );
      })}
    </div>
  );
}

/**
 * How many records this page may return — and therefore how many it is charged.
 *
 * Not a display preference. The charge is the page size, taken before the read, so this is
 * the only control in the panel where an operator decides how much personal data to expose.
 * The default is the server's own cap; the smaller options exist because most orders have
 * three takes, not fifty.
 */
function PageSizeChooser({
  limit,
  onLimit,
}: {
  readonly limit: number;
  readonly onLimit: (value: number) => void;
}) {
  const { t } = useI18n();

  return (
    <label className="flex flex-col gap-1">
      <span className={SECTION_LABEL_CLASS}>{t("reveal.dialog.pageSizeLabel")}</span>
      <select
        data-testid="reveal-limit"
        value={String(limit)}
        onChange={(event) => onLimit(Number(event.target.value))}
        className={FIELD_CONTROL_CLASS}
      >
        {PAGE_SIZES.map((size) => (
          <option key={size} value={size}>
            {t("reveal.dialog.pageSize", { count: size })}
          </option>
        ))}
      </select>
      <span className="text-[12px] leading-4 text-ink-400">
        {t("reveal.dialog.pageSizeNote")}
      </span>
    </label>
  );
}

function ReasonFields({
  reasonCode,
  onReasonCode,
  reasonRef,
  onReasonRef,
  reasonText,
  onReasonText,
  isRefMalformed,
  isRefCredentialShaped,
}: {
  readonly reasonCode: AuditReasonCode | null;
  readonly onReasonCode: (code: AuditReasonCode | null) => void;
  readonly reasonRef: string;
  readonly onReasonRef: (value: string) => void;
  readonly reasonText: string;
  readonly onReasonText: (value: string) => void;
  readonly isRefMalformed: boolean;
  readonly isRefCredentialShaped: boolean;
}) {
  const { t } = useI18n();

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className={SECTION_LABEL_CLASS}>{t("reveal.dialog.reasonCodeLabel")}</span>
        <select
          data-testid="reveal-reason-code"
          value={reasonCode ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            onReasonCode(value === "" ? null : asReasonCode(value));
          }}
          className={FIELD_CONTROL_CLASS}
        >
          <option value="">— choose a reason —</option>
          {AUDIT_REASON_CODE_VALUES.map((code) => (
            <option key={code} value={code}>
              {t(REVEAL_REASON_KEYS[code])}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className={SECTION_LABEL_CLASS}>{t("reveal.dialog.reasonRefLabel")}</span>
        <input
          type="text"
          data-testid="reveal-reason-ref"
          value={reasonRef}
          maxLength={MAX_REASON_REF_CHARS}
          onChange={(event) => onReasonRef(event.target.value)}
          placeholder={t("users.reasonRefPlaceholder")}
          aria-invalid={isRefMalformed}
          className={FIELD_CONTROL_CLASS}
        />
        {isRefMalformed ? (
          <span role="alert" className="text-[12px] leading-4 text-required-deep">
            {t("reveal.dialog.refMalformed")}
          </span>
        ) : null}
        {isRefCredentialShaped ? (
          <span
            role="alert"
            data-testid="reveal-ref-credential-warning"
            className="text-[12px] leading-4 text-warn-deep"
          >
            {t("reveal.dialog.refCredentialShaped")}
          </span>
        ) : null}
      </label>

      <label className="flex flex-col gap-1">
        <span className={SECTION_LABEL_CLASS}>
          {t("reveal.dialog.reasonTextLabel", { max: MAX_REASON_TEXT_CHARS })}
        </span>
        <textarea
          data-testid="reveal-reason-text"
          value={reasonText}
          maxLength={MAX_REASON_TEXT_CHARS}
          rows={2}
          onChange={(event) => onReasonText(event.target.value)}
          className={TEXTAREA_CONTROL_CLASS}
        />
        <span className="text-[12px] leading-4 text-ink-400">
          Your words, not the customer's: this is free text on a 90-day sweep, so never paste
          anything the reveal itself is for.
        </span>
      </label>
    </div>
  );
}

/** The wire values are the option values, so anything else is a bug in this file, not input. */
function asReasonCode(value: string): AuditReasonCode | null {
  return AUDIT_REASON_CODE_VALUES.find((code) => code === value) ?? null;
}

function CostSummary({
  shapeLabel,
  costLabel,
  isMixed,
}: {
  readonly shapeLabel: string | null;
  readonly costLabel: string;
  readonly isMixed: boolean;
}) {
  const { t } = useI18n();

  if (isMixed) {
    return (
      <Notice tone="caution" testId="reveal-mixed-shape" title={t("reveal.dialog.mixedShape")}>
        <p>
          A brief column and an attempt column have different record shapes, and one record
          count cannot honestly describe both — the server refuses the request. Reveal one
          group, then the other.
        </p>
      </Notice>
    );
  }
  return (
    <Notice
      tone="quiet"
      testId="reveal-cost"
      title={
        shapeLabel === null
          ? "Nothing chosen yet."
          : `This reveal returns ${shapeLabel} and is charged ${costLabel}.`
      }
    >
      <p>
        The charge is taken before the read, so it does not depend on what is found. A refusal
        after this point gives the charge back; the audit row does not come back.
      </p>
    </Notice>
  );
}

/* -------------------------------------------------------------------------- */
/* The result                                                                  */
/* -------------------------------------------------------------------------- */

/** Said on a `user_profiles` reveal, because that table has no retention clock at all. */
export const NO_RETENTION_CLOCK_NOTE =
  "This profile is on no retention clock: it is kept while the account exists, and /forget erases it outright.";

function RevealedRecords({
  subjectType,
  result,
}: {
  readonly subjectType: RevealSubjectType;
  readonly result: RevealResponse;
}) {
  const { t } = useI18n();

  return (
    <section data-testid="reveal-result" aria-label={t("reveal.revealedRecordsAria")} className="flex flex-col gap-3">
      <p className="text-[12px] leading-4 text-ink-400">
        {t("reveal.dialog.returnedRecords", {
          returned: result.records.length,
          charged: result.recordCount,
        })}
        {result.records.length < result.recordCount ? t("reveal.dialog.chargeIsThePage") : ""}
      </p>

      {result.records.length === 0 ? (
        <Notice tone="quiet" title={t("reveal.dialog.nothingToShow")}>
          <p>
            The subject exists and holds no value in these columns — which still cost a
            step-up, a budget charge and an audit row, because a miss an operator could probe
            for free is not a budget.
          </p>
        </Notice>
      ) : null}

      {result.records.map((record: RevealedRecord) => (
        <article
          key={record.recordId}
          data-testid="revealed-record"
          className="flex flex-col gap-2 rounded-card bg-bg p-4"
        >
          <p className={cn(CELL_SECONDARY_CLASS, "flex flex-wrap gap-2")}>
            <span className={MONO_CLASS}>{record.recordId}</span>
            <span>{record.createdAt}</span>
          </p>

          <p className="text-[12px] leading-4 text-ink-400">
            {subjectType === "user" ? (
              NO_RETENTION_CLOCK_NOTE
            ) : (
              <>
                {"identity clock: "}
                <PurgeStamp purgedAt={record.identityPurgedAt} />
                {" · free-text clock: "}
                <PurgeStamp purgedAt={record.textPurgedAt} />
              </>
            )}
          </p>

          {result.revealedFields.map((field) => (
            <div
              key={field}
              data-testid="revealed-field"
              data-field={field}
              className="flex flex-col gap-0.5"
            >
              <span className="text-[12px] leading-4 text-ink-300">
                {t(REVEAL_FIELD_LABEL_KEYS[field])}
              </span>
              <RevealedValue value={record.fields[field] ?? null} />
            </div>
          ))}
        </article>
      ))}
    </section>
  );
}

/** "purged <date>" or "not purged". Never blank: the two are different facts. */
function PurgeStamp({ purgedAt }: { readonly purgedAt: string | null }) {
  return purgedAt === null ? (
    <span>not purged</span>
  ) : (
    <span data-testid="purge-stamp" data-purged-at={purgedAt} className="whitespace-nowrap">
      {`🔒 purged ${purgedAt.slice(0, 10)}`}
    </span>
  );
}

/**
 * One revealed value, whatever shape the column holds.
 *
 * Strings reach the DOM as one text node, untouched — no trim, no case fold, no
 * normalisation, no `text-transform`. Any of those shows the operator a different name from
 * the one the customer typed, on a panel that is at the same time reporting whether that name
 * verified.
 *
 * `null` is rendered as the fact it is, never as a blank line: the column holds nothing, and
 * the clocks above say whether that is a purge or a value never written.
 */
function RevealedValue({ value }: { readonly value: unknown }): ReactNode {
  if (value === null || value === undefined) {
    return (
      <span data-testid="revealed-null" className="text-[13px] leading-[18px] text-ink-400">
        null — the column holds nothing. Purged, or never written; the clocks above say which.
      </span>
    );
  }
  if (typeof value === "string") {
    return (
      <span dir="ltr" className="whitespace-pre-wrap break-words text-[14px] leading-5 text-ink-900">
        {value}
      </span>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="text-[14px] leading-5 text-ink-900">{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    const items: readonly unknown[] = value;
    return (
      <ul className="flex flex-col gap-0.5">
        {items.map((item, index) => (
          <li key={index} className="flex items-baseline gap-2">
            <span className="text-[12px] leading-4 text-ink-300">{String(index + 1)}</span>
            <RevealedValue value={item} />
          </li>
        ))}
      </ul>
    );
  }
  // A JSON object from the wire. Read as an open bag of `unknown` rather than keyed on
  // anything: `briefs.recipient_candidates` is a structure the server owns, and a shape this
  // build assumed would render a customer's data wrongly rather than not at all.
  const entries = Object.entries(value as Record<string, unknown>);
  return (
    <div className="flex flex-col gap-0.5">
      {entries.map(([key, item]) => (
        <div key={key} className="flex items-baseline gap-2">
          {/* The KEY is a column or a JSON field WE define; only the value is theirs. */}
          <span className={cn(MONO_CLASS, "text-ink-300")}>{key}</span>
          <RevealedValue value={item} />
        </div>
      ))}
    </div>
  );
}
