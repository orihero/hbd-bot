/**
 * `<RevealDialog>` — the one control that turns masked data into plaintext (§11.4, §12.3).
 *
 * §11.4 says this component "carries non-obvious weight". Four requirements, and each one is
 * a failure that has already happened somewhere else:
 *
 * 1. **The cost is shown against the remaining budget BEFORE the confirm.** That is what makes
 *    the budget a policy an operator can work inside rather than a surprise 429 halfway
 *    through a support call, on the third of five records somebody is reading out. It is
 *    possible because the charge is deterministic — `plan_reveal` charges 1 for a brief column
 *    and the PAGE SIZE for the attempts' free text, before the read, never the number of rows
 *    found — so `revealCost` can compute it from the checkboxes alone.
 * 2. **No `reasonCode`, no confirm.** The server answers 422 and the UI must not rely on that
 *    to tell the operator: a round trip that fails on a field the form could see is a form
 *    that has decided accountability is the server's problem.
 * 3. **A 403 `STEP_UP_REQUIRED` routes into the step-up flow and back**, not into a dead error.
 *    This is the first real step-up UI in the product — every Phase 1 `STEP_UP_REQUIRED` came
 *    from a router guard that holds no subject and consults no grant, so re-authenticating
 *    could not have changed the answer. `<StepUpPrompt>` and `stepUpTargetOf` are the reusable
 *    halves; this dialog is just their first caller.
 * 4. **A 429 says WHICH budget and WHEN it resets.** The two ceilings have different windows
 *    and spending one never spends the other; "you have run out" is a support ticket.
 *
 * ## The plaintext
 *
 * Revealed values reach the DOM through `<NameText>` and nothing else — one text node inside
 * `<span lang="uz-Latn" dir="ltr">`, untouched.
 *
 * This paragraph used to claim that `NFKD` folds U+02BB (the turned comma in `oʻ` and `gʻ`)
 * to a plain apostrophe. **It does not** — NFC, NFD, NFKC and NFKD are all the identity for
 * U+02BB and U+02BC, verified. The fence is still right, for reasons that are actually true:
 * `.toLowerCase()` turns `Gʻulom` into `gʻulom` (data loss in every locale, not just the
 * Turkish one), `.localeCompare()` at `sensitivity: "base"` reports `Gʻulom` and `gʻulom`
 * as EQUAL and so merges two distinct names, and `text-transform` alters the name on screen
 * with no trace in the DOM. (Collation does NOT treat the mark as ignorable — an earlier
 * version of this paragraph claimed `Gʻulom` and `Gulom` compare equal, and they do not,
 * under any option. `src/lib/uzbekMarks.test.ts` measures it.)
 * Any of those anywhere in this path shows the operator a different name from the one the
 * customer typed, on a screen that is simultaneously reporting whether the name verified.
 * The ESLint fence over `components/domain/` makes those calls unavailable here; do not
 * route around it, and do not add a `text-transform`.
 *
 * `null` in `fields` means the COLUMN IS NULL — purged, or never written. It is not a mask and
 * not `""`, and it is rendered as its own fact beside the two purge stamps, because "no name"
 * and "name erased on schedule on 2026-05-14" are different answers to a data-subject request.
 *
 * ## What it does NOT do
 *
 * It does not cache the plaintext. The result lives in one mutation's state and dies with the
 * dialog; nothing writes it into a query the rest of the app could read, and closing the dialog
 * is the end of the disclosure as far as this tab is concerned. A `nextCursor` is a POSITION,
 * never a licence — page two is a fresh `POST /reveal`, separately step-up-checked, separately
 * charged and separately audited, and the button says so.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { Eye, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactElement } from "react";

import {
  AUDIT_REASON_CODE_VALUES,
  failureOf,
  LONG_REASON_REF_CHARS,
  MAX_REASON_REF_CHARS,
  MAX_REASON_TEXT_CHARS,
  MAX_RECORDS_PER_REVEAL,
  REASON_REF_PATTERN,
  type ApiFailure,
  type AuditReasonCode,
  type RevealedRecord,
  type RevealField,
  type RevealRequest,
  type RevealSubjectType,
} from "@/api";
import { Timestamp } from "@/components/data/Timestamp";
import { Button } from "@/components/util/Button";
import { PermissionGate } from "@/components/util/PermissionGate";
import { cn, formatInteger } from "@/lib";

import { NameText } from "./NameText";
import { PurgedValue } from "./PurgedValue";
import { readBudgetRefusal, willExceedBudget } from "./revealBudget";
import { RevealBudgetMeter } from "./RevealBudgetMeter";
import {
  canSubmitReveal,
  describeRevealCost,
  orderFields,
  revealCost,
  revealShapeOf,
  REVEAL_FIELD_HINTS,
  REVEAL_FIELD_LABELS,
  REVEAL_REASON_LABELS,
  REVEAL_SHAPE_LABELS,
} from "./revealFields";
import { stepUpTargetOf } from "./stepUp";
import { StepUpPrompt } from "./StepUpPrompt";
import { useReveal, useRevealBudget, useRevealCeilings } from "./useReveal";

/** Withheld until a reason is chosen, and this is why — shown, not left to a 422. */
export const REASON_REQUIRED_HINT =
  "Choose a reason code. It is required, it goes on the audit row for 730 days, and the server refuses the reveal without one.";

/** §12.3, said once where an operator will read it. */
export const REVEAL_IS_LOGGED_NOTE =
  "The audit row is written before the read, so this reveal is attributable even if it then fails. It records that these columns were revealed — never what they said.";

/** The credential-shape trap `reasonRef` walks into. */
export const LONG_REF_WARNING =
  "40 or more characters of letters, digits, _ and - reads as a credential to the audit boundary and the reveal will be refused. Shorten it, or add a # or another separator.";

export interface RevealDialogProps {
  readonly isOpen: boolean;
  readonly onOpenChange: (isOpen: boolean) => void;
  readonly subjectType: RevealSubjectType;
  /** The canonical `str(uuid)` the server will compare the step-up scope against. */
  readonly subjectId: string;
  /** OUR words for the subject — an order reference. NEVER a recipient name. */
  readonly subjectLabel: string;
  /** The columns this surface offers. They must share one `RevealShape`. */
  readonly fields: readonly RevealField[];
}

export function RevealDialog({
  isOpen,
  onOpenChange,
  subjectType,
  subjectId,
  subjectLabel,
  fields,
}: RevealDialogProps): ReactElement {
  const [chosen, setChosen] = useState<ReadonlySet<RevealField>>(() => new Set(fields));
  const [reasonCode, setReasonCode] = useState<AuditReasonCode | null>(null);
  const [reasonRef, setReasonRef] = useState("");
  const [reasonText, setReasonText] = useState("");
  const [limit, setLimit] = useState<number>(MAX_RECORDS_PER_REVEAL);
  const [pending, setPending] = useState<RevealRequest | null>(null);

  const reveal = useReveal();
  const budget = useRevealBudget();
  const ceilings = useRevealCeilings(isOpen);

  const selected = useMemo(() => orderFields(fields, chosen), [fields, chosen]);
  const shape = revealShapeOf(selected);
  // The page size IS the charge: `plan_reveal` charges `page.limit` before the read, whatever
  // the read turns out to find. So asking for ten transcripts costs ten records and not fifty,
  // and an operator who only needs the last few takes should not spend a quarter of their hour
  // on the forty they will not read.
  const cost = revealCost(selected, shape === "paged" ? limit : null);

  const { reset } = reveal;
  // A reopened dialog starts clean. Carrying a previous subject's reason code — or, worse, its
  // revealed plaintext — into the next investigation is how the wrong record ends up quoted
  // into a ticket.
  useEffect(() => {
    if (isOpen) return;
    reset();
    setChosen(new Set(fields));
    setReasonCode(null);
    setReasonRef("");
    setReasonText("");
    setLimit(MAX_RECORDS_PER_REVEAL);
    setPending(null);
  }, [isOpen, fields, reset]);

  const failure = failureOf(reveal.error);
  const stepUpTarget = stepUpTargetOf(failure);
  const isRefLong = looksLikeCredential(reasonRef);
  const isRefMalformed = reasonRef !== "" && !REASON_REF_PATTERN.test(reasonRef);
  const canConfirm =
    canSubmitReveal({ fields: selected, reasonCode }) && !reveal.isPending && !isRefMalformed;

  const send = (cursor: string | null): void => {
    if (reasonCode === null || shape === null) return;
    const body: RevealRequest = {
      subjectType,
      subjectId,
      fields: [...selected],
      reasonCode,
      ...(reasonRef === "" ? {} : { reasonRef }),
      ...(reasonText === "" ? {} : { reasonText }),
      // `limit` and `cursor` are refused on a single-record reveal — a page control on
      // something with no pages is how a caller learns to expect one.
      ...(shape === "paged" ? { limit } : {}),
      ...(cursor === null ? {} : { cursor }),
    };
    setPending(body);
    reveal.mutate(body);
  };

  const result = reveal.data;

  return (
    <Dialog.Root open={isOpen} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          /*
           * The scrim has to DIM in both themes, and no single token does that: `--ink` is a
           * dark charcoal in light and a near-white in dark, `--surface` is the reverse. So
           * the light scrim is `--ink` at 40% (a real dim over a `#FAFAFA` page) and the dark
           * one is `--surface` at 75%. Getting this wrong is invisible in jsdom and obvious
           * on screen: a white scrim over a white page leaves the dialog floating on nothing,
           * with only `--shadow-overlay`'s `--edge` ring to say where it ends.
           */
          className="fixed inset-0 z-50 bg-ink opacity-40 dark:bg-surface dark:opacity-75"
        />
        <Dialog.Content
          data-testid="reveal-dialog"
          className={cn(
            "fixed left-1/2 top-[8vh] z-50 w-[min(44rem,94vw)] -translate-x-1/2",
            // `--shadow-overlay` carries the 1px `--edge` ring (3.22:1 on a card) that
            // keeps a floating panel from dissolving into the surface behind it, so the
            // dialog names no border of its own.
            "flex max-h-[84vh] flex-col overflow-hidden rounded-card",
            "bg-surface-card shadow-overlay",
          )}
        >
          <header className="flex items-start gap-3 px-card pb-3 pt-card">
            <Eye aria-hidden="true" className="mt-1 h-4 w-4 text-accent" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <Dialog.Title className="type-h2 text-ink">
                {`Reveal ${subjectType} ${subjectLabel}`}
              </Dialog.Title>
              <Dialog.Description className="type-body-sm text-ink-muted">
                {REVEAL_IS_LOGGED_NOTE}
              </Dialog.Description>
            </div>
            <Dialog.Close
              aria-label="Close"
              className="rounded-full p-2 text-ink-muted transition-colors duration-fast ease-standard hover:bg-surface-control-hover hover:text-ink"
            >
              <X aria-hidden="true" className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
            {/* The budget, above everything, in every phase — including after the reveal,
                where it is the answer to "how much more can I do on this call?". */}
            <RevealBudgetMeter
              budget={budget}
              ceilings={{ records: ceilings.records, conversations: ceilings.conversations }}
              cost={result === undefined ? cost : { records: 0, conversations: 0 }}
            />

            {failure !== null && failure.code === "REVEAL_BUDGET_EXHAUSTED" ? (
              <BudgetExhausted failure={failure} />
            ) : null}

            {stepUpTarget !== null ? (
              <StepUpPrompt
                action={stepUpTarget.action}
                subjectId={stepUpTarget.subjectId}
                subjectLabel={subjectLabel}
                graceS={ceilings.stepUpGraceS}
                note={
                  <span>
                    {`Revealing ${describeRevealCost(cost)} of ${subjectType} `}
                    <span className="type-mono text-ink">{subjectLabel}</span>
                    {" needs a grant scoped to this subject."}
                  </span>
                }
                onGranted={() => {
                  // The grant authorises an ACTION on a SUBJECT, not a request: the server has
                  // no memory of what we were trying to do, so the same body goes again.
                  if (pending !== null) reveal.mutate(pending);
                }}
                onCancel={() => {
                  onOpenChange(false);
                }}
              />
            ) : null}

            {failure !== null &&
            failure.code !== "REVEAL_BUDGET_EXHAUSTED" &&
            stepUpTarget === null ? (
              <RevealFailureNotice
                code={failure.code}
                message={failure.message}
                correlationId={failure.correlationId}
              />
            ) : null}

            {result === undefined && stepUpTarget === null ? (
              <>
                <FieldChooser
                  offered={fields}
                  chosen={chosen}
                  onToggle={(field) => {
                    setChosen((current) => toggled(current, field));
                  }}
                />

                {shape === "paged" ? (
                  <PageSizeChooser limit={limit} onLimit={setLimit} />
                ) : null}

                <ReasonFields
                  reasonCode={reasonCode}
                  onReasonCode={setReasonCode}
                  reasonRef={reasonRef}
                  onReasonRef={setReasonRef}
                  reasonText={reasonText}
                  onReasonText={setReasonText}
                  isRefLong={isRefLong}
                  isRefMalformed={isRefMalformed}
                />

                <CostSummary
                  shapeLabel={shape === null ? null : REVEAL_SHAPE_LABELS[shape]}
                  cost={cost}
                  isOverBudget={willExceedBudget(budget, cost, Date.now())}
                />
              </>
            ) : null}

            {result === undefined ? null : (
              <RevealedRecords
                records={result.records}
                revealedFields={result.revealedFields}
                recordCount={result.recordCount}
              />
            )}
          </div>

          <footer className="flex flex-wrap items-center gap-2 px-card pb-card pt-4">
            {result === undefined ? (
              <>
                <Button
                  variant="primary"
                  data-testid="reveal-confirm"
                  disabled={!canConfirm}
                  onClick={() => {
                    send(null);
                  }}
                >
                  {reveal.isPending
                    ? "Revealing…"
                    : `Reveal — ${describeRevealCost(cost)}`}
                </Button>
                {reasonCode === null ? (
                  <span data-testid="reveal-reason-required" className="type-body-sm text-ink-muted">
                    {REASON_REQUIRED_HINT}
                  </span>
                ) : null}
              </>
            ) : (
              <>
                {result.nextCursor === null ? null : (
                  <Button
                    variant="primary"
                    data-testid="reveal-next-page"
                    disabled={reveal.isPending}
                    onClick={() => {
                      send(result.nextCursor);
                    }}
                  >
                    {`Next page — a fresh reveal, ${describeRevealCost(cost)} again`}
                  </Button>
                )}
                {/* Dismissive, so `quiet`: no ground of its own beside the primary. */}
                <Button
                  variant="quiet"
                  onClick={() => {
                    onOpenChange(false);
                  }}
                >
                  Done
                </Button>
              </>
            )}
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* -------------------------------------------------------------------------- */
/* The trigger                                                                 */
/* -------------------------------------------------------------------------- */

export interface RevealButtonProps extends Omit<RevealDialogProps, "isOpen" | "onOpenChange"> {
  readonly label?: string;
  readonly className?: string | undefined;
}

/**
 * The affordance itself, gated where it is drawn rather than where it is used.
 *
 * §11.4: role-based **hiding**, not disabling. VIEWER holds no reveal cell in §12.2, so a
 * viewer sees nothing at all — not a greyed button, not a tooltip. Putting the gate inside the
 * button means a screen cannot wire the reveal in and forget it, which is the way a
 * `permission.denied` audit row gets written by curiosity rather than by an attack.
 *
 * The permission named is `reveal.personal_data` — §12.2's `A+S` cell, which is what this
 * control ultimately spends. The server ALSO guards the router with the role half
 * (`reveal.personal_data.read`, SUPPORT and above, no step-up) so that a correctly
 * re-authenticated SUPPORT operator is not refused by a guard that holds no subject; that
 * split is a server-side mechanism and is deliberately not mirrored into the client matrix,
 * where both halves would name the same three roles.
 */
export function RevealButton({
  label = "Reveal",
  className,
  ...dialog
}: RevealButtonProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <PermissionGate permission="reveal.personal_data">
      {/*
        SECONDARY, not a grey chip. This is one of the three buttons the brand-language
        finding named by name ("Reveal the brief", "Reveal attempt free text", "Reveal this
        order’s brief"): it was `--surface-control` under `--ink-muted`, grey on grey, which
        the design language rules out however well it measures. It is now the console’s one
        secondary idiom — a tint of the hue with the hue as the label — which also makes it
        read as the consequential action it is.
      */}
      <Button
        variant="secondary"
        data-testid="reveal-button"
        onClick={() => {
          setIsOpen(true);
        }}
        className={className}
      >
        <Eye aria-hidden="true" className="h-3.5 w-3.5" />
        {label}
      </Button>
      <RevealDialog {...dialog} isOpen={isOpen} onOpenChange={setIsOpen} />
    </PermissionGate>
  );
}

/* -------------------------------------------------------------------------- */
/* Pieces                                                                      */
/* -------------------------------------------------------------------------- */

function FieldChooser({
  offered,
  chosen,
  onToggle,
}: {
  readonly offered: readonly RevealField[];
  readonly chosen: ReadonlySet<RevealField>;
  readonly onToggle: (field: RevealField) => void;
}): ReactElement {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="type-caption text-ink-muted">columns to unmask</legend>
      {offered.map((field) => (
        <label key={field} className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={chosen.has(field)}
            onChange={() => {
              onToggle(field);
            }}
            className="mt-1 accent-brand-fill"
          />
          <span className="flex flex-col">
            <span className="type-body-sm text-ink">{REVEAL_FIELD_LABELS[field]}</span>
            <span className="type-caption text-ink-muted">{REVEAL_FIELD_HINTS[field]}</span>
            {/* The column name, verbatim, because it is what lands in the audit row's
                `field_names` and an operator reading `/audit` later needs to recognise it. */}
            <span className="type-mono text-ink-muted">{field}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/**
 * How many records this page is authorised to return — and therefore how many it is charged.
 *
 * Not a display preference. §12.3 counts the budget in RECORDS, and the charge is the page
 * size taken before the read, so this control is the only place in the panel where an operator
 * decides how much personal data to expose. The default is the fifty-record cap because that
 * is the server's default when `limit` is absent; the smaller options exist because most
 * orders have three takes, not fifty.
 */
function PageSizeChooser({
  limit,
  onLimit,
}: {
  readonly limit: number;
  readonly onLimit: (value: number) => void;
}): ReactElement {
  return (
    <label className="flex flex-col gap-1">
      <span className="type-caption text-ink-muted">records this page may return</span>
      <select
        data-testid="reveal-limit"
        value={String(limit)}
        onChange={(event) => {
          onLimit(Number(event.target.value));
        }}
        className="type-body-sm num rounded-control bg-surface-control px-3 py-2 text-ink"
      >
        {PAGE_SIZES.map((size) => (
          <option key={size} value={size}>
            {`${String(size)} records`}
          </option>
        ))}
      </select>
      <span className="type-caption text-ink-muted">
        This is the charge, not a ceiling on what exists: the budget is debited before the read,
        so a page of fifty that finds three still costs fifty.
      </span>
    </label>
  );
}

/** Offered page sizes. The largest is the server's own cap and its default. */
const PAGE_SIZES: readonly number[] = [5, 10, 25, MAX_RECORDS_PER_REVEAL];

function ReasonFields({
  reasonCode,
  onReasonCode,
  reasonRef,
  onReasonRef,
  reasonText,
  onReasonText,
  isRefLong,
  isRefMalformed,
}: {
  readonly reasonCode: AuditReasonCode | null;
  readonly onReasonCode: (code: AuditReasonCode | null) => void;
  readonly reasonRef: string;
  readonly onReasonRef: (value: string) => void;
  readonly reasonText: string;
  readonly onReasonText: (value: string) => void;
  readonly isRefLong: boolean;
  readonly isRefMalformed: boolean;
}): ReactElement {
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="type-caption text-ink-muted">reason code (required)</span>
        <select
          data-testid="reveal-reason-code"
          value={reasonCode ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            onReasonCode(value === "" ? null : (value as AuditReasonCode));
          }}
          className="type-body-sm rounded-control bg-surface-control px-3 py-2 text-ink"
        >
          <option value="">— choose a reason —</option>
          {AUDIT_REASON_CODE_VALUES.map((code) => (
            <option key={code} value={code}>
              {REVEAL_REASON_LABELS[code]}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="type-caption text-ink-muted">ticket reference (optional)</span>
        <input
          type="text"
          data-testid="reveal-reason-ref"
          value={reasonRef}
          maxLength={MAX_REASON_REF_CHARS}
          onChange={(event) => {
            onReasonRef(event.target.value);
          }}
          placeholder="SUP-1423"
          className="type-body-sm rounded-control bg-surface-control px-3 py-2 text-ink"
        />
        {isRefMalformed ? (
          <span role="alert" className="type-caption text-error">
            Letters, digits, #, _ and - only, up to 64 characters.
          </span>
        ) : null}
        {isRefLong ? (
          <span role="alert" data-testid="reveal-ref-credential-warning" className="type-caption text-caution">
            {LONG_REF_WARNING}
          </span>
        ) : null}
      </label>

      <label className="flex flex-col gap-1">
        <span className="type-caption text-ink-muted">
          {`why (optional, ${String(MAX_REASON_TEXT_CHARS)} characters, kept for 90 days)`}
        </span>
        <textarea
          data-testid="reveal-reason-text"
          value={reasonText}
          maxLength={MAX_REASON_TEXT_CHARS}
          rows={2}
          onChange={(event) => {
            onReasonText(event.target.value);
          }}
          className="type-body-sm rounded-control bg-surface-control px-3 py-2 text-ink"
        />
      </label>
    </div>
  );
}

function CostSummary({
  shapeLabel,
  cost,
  isOverBudget,
}: {
  readonly shapeLabel: string | null;
  readonly cost: { readonly records: number; readonly conversations: number };
  readonly isOverBudget: boolean;
}): ReactElement {
  return (
    <div data-testid="reveal-cost" className="flex flex-col gap-1.5 rounded-2xl bg-surface-control p-4">
      {shapeLabel === null ? (
        <p className="type-body-sm text-error">
          Pick columns that belong to one record shape. A brief column and an attempt column
          cannot share a reveal — one record count cannot honestly describe both, and the
          server refuses the request.
        </p>
      ) : (
        <p className="type-body-sm text-ink">
          {`This reveal returns ${shapeLabel} and is charged ${describeRevealCost(cost)}.`}
        </p>
      )}
      {cost.conversations > 0 ? (
        <p className="type-caption text-ink-muted">
          {`A page is at most ${String(MAX_RECORDS_PER_REVEAL)} records and is charged in full, before the read — an empty page costs the same as a full one.`}
        </p>
      ) : (
        <p className="type-caption text-ink-muted">
          Every column on this brief costs the same single record, so revealing them together
          costs once and writes one audit row.
        </p>
      )}
      {isOverBudget ? (
        <p role="alert" data-testid="reveal-over-budget" className="type-body-sm text-caution">
          This is more than the budget this tab last measured. The server will refuse it with
          429 and charge nothing.
        </p>
      ) : null}
    </div>
  );
}

function BudgetExhausted({
  failure,
}: {
  readonly failure: ApiFailure;
}): ReactElement {
  const refusal = readBudgetRefusal(failure, Date.now());
  return (
    <div
      role="alert"
      data-testid="reveal-budget-exhausted"
      data-budget-scope={refusal.scope ?? "unknown"}
      className="flex flex-col gap-1.5 rounded-2xl bg-surface-control p-4"
    >
      <p className="type-body-sm text-error">
        <span aria-hidden="true">⊘</span>
        {` Your ${refusal.scopeLabel} budget is spent.`}
      </p>
      <p className="type-body-sm text-ink">
        {refusal.remaining === null
          ? "The server did not say how many are left."
          : `${formatInteger(refusal.remaining)} left against that ceiling`}
        {refusal.requested === null
          ? ""
          : `, and this reveal asked for ${formatInteger(refusal.requested)} records`}
        {"."}
      </p>
      <p className="type-body-sm text-ink">
        {"It resets at "}
        <Timestamp at={new Date(refusal.resetsAt).toISOString()} seconds />
        {` — ${String(Math.max(1, Math.round(refusal.resetsInS / 60)))} min from now. The window is fixed, not sliding.`}
      </p>
      <p className="type-caption text-ink-muted">
        Nothing was charged and nothing was disclosed: a refused reveal gives its charge back.
      </p>
    </div>
  );
}

function RevealFailureNotice({
  code,
  message,
  correlationId,
}: {
  readonly code: string;
  readonly message: string;
  readonly correlationId: string | null;
}): ReactElement {
  return (
    <div
      role="alert"
      data-testid="reveal-failure"
      data-code={code}
      className="flex flex-col gap-1.5 rounded-2xl bg-surface-control p-4"
    >
      <p className="type-body-sm text-error">
        <span className="type-mono">{code}</span>
        {` — ${message}`}
      </p>
      {code === "STEP_UP_REQUIRED" ? (
        <p className="type-caption text-ink-muted">
          This refusal came from the route's own guard rather than from a grant check, so
          re-authenticating cannot change it. It is a role that holds no cell in this row.
        </p>
      ) : null}
      {correlationId === null ? null : (
        <p className="type-caption text-ink-muted">
          {"correlation "}
          <span className="type-mono text-ink">{correlationId}</span>
        </p>
      )}
    </div>
  );
}

function RevealedRecords({
  records,
  revealedFields,
  recordCount,
}: {
  readonly records: readonly RevealedRecord[];
  readonly revealedFields: readonly RevealField[];
  readonly recordCount: number;
}): ReactElement {
  return (
    <section data-testid="reveal-result" aria-label="revealed records" className="flex flex-col gap-3">
      <p className="type-body-sm text-ink-muted">
        {`${formatInteger(records.length)} of ${formatInteger(recordCount)} charged records returned. `}
        {records.length < recordCount
          ? "The charge is the page this reveal was authorised to return, not what it found."
          : ""}
      </p>

      {records.length === 0 ? (
        <p className="type-body-sm text-ink">
          Nothing to show. The subject exists and holds no value in these columns — which still
          cost a step-up, a budget charge and an audit row, because a miss an operator could
          probe for free is not a budget.
        </p>
      ) : null}

      {records.map((record) => (
        <article
          key={record.recordId}
          data-testid="revealed-record"
          className="flex flex-col gap-2 rounded-2xl bg-surface-control p-4"
        >
          <p className="type-caption text-ink-muted">
            <span className="type-mono">{record.recordId}</span>
            {" · "}
            <Timestamp at={record.createdAt} seconds />
          </p>

          {/* §12.3: `identity_purged_at` is ALWAYS displayed. "No name" and "name purged on
              schedule 2026-05-14" are different facts and only one is defensible. */}
          <p className="type-caption text-ink-muted">
            {"identity clock: "}
            <PurgedValue purgedAt={record.identityPurgedAt} clock="identity retention">
              <span>not purged</span>
            </PurgedValue>
            {" · free-text clock: "}
            <PurgedValue purgedAt={record.textPurgedAt} clock="free-text retention">
              <span>not purged</span>
            </PurgedValue>
          </p>

          {revealedFields.map((field) => (
            <div key={field} data-testid="revealed-field" data-field={field} className="flex flex-col gap-0.5">
              <span className="type-caption text-ink-muted">{REVEAL_FIELD_LABELS[field]}</span>
              <RevealedValue value={record.fields[field]} />
            </div>
          ))}
        </article>
      ))}
    </section>
  );
}

/**
 * One revealed value, whatever shape the column holds.
 *
 * Every string goes through `<NameText>` — not only the name columns. A note, a lyric and a
 * transcript are all customer-authored Uzbek text and all carry the same apostrophes, and a
 * component that folded them "because they are not names" would be the exact bug §11.4's fence
 * exists to prevent. The codepoint toggle rides along, because "which apostrophe" is a
 * question about a transcript as often as about a name.
 *
 * `null` is rendered as the fact it is, never as an em dash and never as an empty line.
 */
function RevealedValue({ value }: { readonly value: unknown }): ReactElement {
  if (value === null || value === undefined) {
    return (
      <span data-testid="revealed-null" className="type-body-sm text-ink-muted">
        null — the column holds nothing. Purged, or never written; the clocks above say which.
      </span>
    );
  }
  if (typeof value === "string") {
    return (
      <span className="type-body-sm text-ink">
        <NameText value={value} isToggleable />
      </span>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="type-body-sm num text-ink">{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    const items: unknown[] = value;
    return (
      <ul className="flex flex-col gap-0.5">
        {items.map((item, index) => (
          <li key={index} className="flex items-baseline gap-2">
            <span className="type-caption num text-ink-muted">{String(index + 1)}</span>
            <RevealedValue value={item} />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="flex flex-col gap-0.5">
      {Object.entries(value as Record<string, unknown>).map(([key, item]) => (
        <div key={key} className="flex items-baseline gap-2">
          {/* The KEY is a column or a JSON field WE define; only the value is theirs. */}
          <span className="type-mono text-ink-muted">{key}</span>
          <RevealedValue value={item} />
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Small pure helpers                                                          */
/* -------------------------------------------------------------------------- */

function toggled(
  current: ReadonlySet<RevealField>,
  field: RevealField,
): ReadonlySet<RevealField> {
  const next = new Set(current);
  if (!next.delete(field)) next.add(field);
  return next;
}

/**
 * Whether `reasonRef` trips `audit._CREDENTIAL_SHAPES`' `[A-Za-z0-9_-]{40,}` rule.
 *
 * The two guards on this field disagree by design and the disagreement is the plan's:
 * `REASON_REF_PATTERN` allows 64 characters, and the audit boundary refuses any 40-character
 * run of that alphabet as a possible credential. The server turns that into a 422 naming the
 * field — with no plaintext and no audit row — but an operator who pasted a long slug deserves
 * to be told before they spend the round trip.
 */
function looksLikeCredential(value: string): boolean {
  return new RegExp(`[A-Za-z0-9_-]{${String(LONG_REASON_REF_CHARS)},}`).test(value);
}
