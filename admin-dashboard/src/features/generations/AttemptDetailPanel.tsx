import type { JSX, ReactNode } from "react";

import type { AttemptWireView } from "@/api/generations";
import { Badge } from "@/components/Badge";
import { EMPTY_VALUE, MaskedValue, PurgedValue } from "@/features/reveal";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";

import {
  GENERATION_KIND_KEY,
  NAME_STRATEGY_KEY,
  NOT_TRACKED,
  VERIFICATION_NOT_RUN,
  formatCharCount,
  formatConfidence,
  formatCostUsd,
  formatLatencyMs,
  splitTimestamp,
} from "./attemptFormat";

/**
 * One row of the render ledger, opened beside the table from `?attempt=<uuid>`.
 *
 * It renders the attempt the SCREEN fetched by id rather than the row already in hand: the
 * endpoint exists, it is the same projection, and a panel drawing a row from a page fetched
 * two minutes ago would silently disagree with the same panel opened from a fresh link.
 *
 * ## The two text fields are bought, not shown
 *
 * `generation_attempts.name_candidate_text` and `.stt_transcript` are the only plaintext on
 * this row, and neither is on this wire. What arrives is a MASK (`G•••`) and a LENGTH
 * (`sttTranscriptChars`) respectively, and the plaintext costs a step-up, a unit of reveal
 * budget and an audit row naming one operator, one subject and one reason. `<MaskedValue>` is
 * the only thing here that can spend that, and it hides itself entirely for a role with no
 * reveal cell — a button that always 403s is worse than no button, and pressing it writes a
 * `permission.denied` row against somebody who did nothing wrong.
 *
 * **The reveal subject for both is the ORDER, not the attempt.** `FIELD_SUBJECTS` in
 * `schemas/reveal.py` maps every `generation_attempts.*` field to `RevealSubjectType.ORDER`,
 * and the step-up scope the server compares is that order's UUID. So an ORPHANED attempt —
 * `orderId === null` — has no reveal subject at all, and this panel says that in words instead
 * of offering a button whose request could only 404.
 *
 * ## Purged is not missing, and the two clocks are not one clock
 *
 * `name_candidate_text` is nulled at `identity_expires_at` and `stt_transcript` at
 * `text_expires_at`, so the candidate reads `identityPurgedAt` and the transcript reads
 * `textPurgedAt`. A non-null stamp renders "purged {date}" with NO affordance; a blank would
 * read as a rendering fault and send support hunting for a value the system deliberately
 * destroyed.
 *
 * ## Three fields that look like numbers and are not
 *
 *  - `costUsd` / `latencyMs` — `null` and `isInstrumented: false` on every row in production
 *    today. They render "not tracked". `$0.00 / 0 ms` would say the vendor call was free and
 *    instantaneous.
 *  - `isNameVerified` — TRI-STATE. `null` is "the verifier never ran", which is neither a pass
 *    nor a failure and must not be drawn as one.
 *  - `isRetryable` — `null` means the code is unknown to the taxonomy, NOT "not retryable".
 */

export interface AttemptDetailPanelProps {
  readonly attempt: AttemptWireView;
  readonly onClose: () => void;
  readonly className?: string | undefined;
}

const LABEL_CLASS =
  "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-300";
const VALUE_CLASS = "text-[14px] font-medium leading-5 tracking-[-0.084px] text-ink-900";
const MONO_CLASS = "font-mono text-[12px] leading-[16px] tracking-[-0.2px] break-all text-ink-800";
const SECTION_TITLE_CLASS =
  "text-[16px] font-normal leading-[21.856px] tracking-[-0.64px] text-ink-300";
const NOTE_CLASS =
  "m-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-400";

export function AttemptDetailPanel({
  attempt,
  onClose,
  className,
}: AttemptDetailPanelProps): JSX.Element {
  const { t } = useI18n();
  const created = splitTimestamp(attempt.createdAt);
  const confidence = formatConfidence(attempt.matchConfidence);
  const transcriptLength = formatCharCount(attempt.sttTranscriptChars);
  /* OUR words for the subject, never customer content — it titles the reveal dialog. */
  const subjectLabel =
    attempt.orderId === null ? "" : `order ${attempt.orderId.slice(0, 8)}`;

  return (
    <aside
      aria-label={t("generations.detailAria")}
      data-attempt-id={attempt.id}
      className={cn(
        "flex h-fit flex-col gap-5 rounded-card border border-stroke bg-card p-4",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="m-0 text-[22px] font-semibold leading-[30.052px] tracking-[-0.44px] text-ink-800">
            {t(GENERATION_KIND_KEY[attempt.kind])}
          </h2>
          <p className={cn(NOTE_CLASS, "mt-1")}>
            {t("generations.sequenceLine", {
              sequence: attempt.sequence,
              attempt: attempt.attempt,
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className={cn(
            "shrink-0 cursor-pointer rounded-button border border-stroke bg-card px-3 py-1",
            "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-800",
            "transition-colors hover:bg-bg",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
          )}
        >
          {t("generations.detail.close")}
        </button>
      </header>

      <Section title={t("generations.detail.identity")}>
        <Field label={t("generations.fields.attemptId")}>
          <span className={MONO_CLASS}>{attempt.id}</span>
        </Field>
        <Field label={t("generations.fields.order")}>
          {attempt.orderId === null ? (
            <div className="flex flex-col gap-1">
              <Badge tone="muted" title={t("generations.orphanedExplanation")}>
                {t("generations.orphanedLabel")}
              </Badge>
              <p className={NOTE_CLASS}>{t("generations.orphanedExplanation")}</p>
            </div>
          ) : (
            <span className={MONO_CLASS}>{attempt.orderId}</span>
          )}
        </Field>
        <Field label={t("generations.fields.created")}>
          <span className={VALUE_CLASS}>{created.full}</span>
        </Field>
      </Section>

      <Section title={t("generations.detail.outcome")}>
        <Field label={t("generations.fields.result")}>
          {attempt.isSuccess ? (
            <Badge tone="accent">{t("generations.outcomes.succeeded")}</Badge>
          ) : (
            <Badge tone="danger">{t("generations.outcomes.failed")}</Badge>
          )}
        </Field>
        {attempt.errorCode === null && attempt.errorMessage === null ? null : (
          <>
            <Field label={t("generations.fields.errorCode")}>
              <span className={MONO_CLASS}>{attempt.errorCode ?? EMPTY_VALUE}</span>
            </Field>
            {attempt.errorMessage === null ? null : (
              /* Our own operator prose plus a closed-vocabulary code — never a customer's
                 words — so it is printed verbatim, which is the string that gets grepped. */
              <Field label={t("generations.fields.errorMessage")}>
                <span className={cn(VALUE_CLASS, "whitespace-pre-wrap break-words")}>
                  {attempt.errorMessage}
                </span>
              </Field>
            )}
            <Field label={t("generations.fields.retryable")}>
              {/* `null` = the code is not in the taxonomy. That is not "no". */}
              {attempt.isRetryable === null ? (
                <span className={cn(VALUE_CLASS, "text-ink-400")}>
                  unknown to the error taxonomy
                </span>
              ) : (
                <Badge tone={attempt.isRetryable ? "warning" : "muted"}>
                  {attempt.isRetryable
                    ? t("generations.detail.retryable")
                    : t("generations.detail.notRetryable")}
                </Badge>
              )}
            </Field>
          </>
        )}
      </Section>

      <Section title={t("generations.detail.vendor")}>
        <Field label={t("generations.fields.provider")}>
          <span className={MONO_CLASS}>
            {attempt.provider ??
              /* The model: "None for a NAME_VERIFICATION verdict, which is our own judgement,
                 not a vendor's." An em dash there would read as missing data. */
              (attempt.kind === "name_verification" ? t("generations.noVendorCall") : EMPTY_VALUE)}
          </span>
        </Field>
        <Field label={t("generations.fields.providerId")}>
          <span className={MONO_CLASS}>{attempt.providerRemoteId ?? EMPTY_VALUE}</span>
        </Field>
        <Field label={t("generations.fields.language")}>
          <span className={VALUE_CLASS}>
            {attempt.language === null ? EMPTY_VALUE : t(LANGUAGE_LABEL_KEY[attempt.language])}
          </span>
        </Field>
      </Section>

      <Section title={t("generations.detail.nameVerification")}>
        <Field label={t("generations.fields.candidate")}>
          <RevealableText
            masked={attempt.nameCandidate}
            field="generation_attempts.name_candidate_text"
            recordId={attempt.id}
            orderId={attempt.orderId}
            subjectLabel={subjectLabel}
            purgedAt={attempt.identityPurgedAt}
          />
        </Field>
        <Field label={t("generations.fields.strategy")}>
          <span className={VALUE_CLASS}>
            {attempt.nameCandidateStrategy === null
              ? EMPTY_VALUE
              : t(NAME_STRATEGY_KEY[attempt.nameCandidateStrategy])}
          </span>
          {attempt.nameCandidateRank === null ? null : (
            <span className={cn(NOTE_CLASS, "ml-2 inline")}>
              {`rank ${String(attempt.nameCandidateRank)}`}
            </span>
          )}
        </Field>
        <Field label={t("generations.fields.verified")}>
          {attempt.isNameVerified === null ? (
            <span className={cn(VALUE_CLASS, "text-ink-400")}>{VERIFICATION_NOT_RUN}</span>
          ) : (
            <Badge tone={attempt.isNameVerified ? "accent" : "danger"}>
              {attempt.isNameVerified
                ? t("generations.detail.verified")
                : t("generations.detail.noMatch")}
            </Badge>
          )}
        </Field>
        <Field label={t("generations.fields.matchConfidence")}>
          <span className={VALUE_CLASS}>{confidence ?? EMPTY_VALUE}</span>
        </Field>
      </Section>

      <Section title={t("generations.detail.transcript")}>
        <Field label={t("generations.fields.length")}>
          {/* A LENGTH is all of the transcript that is on this wire — it is a near-verbatim
              copy of the whole song, so the text itself only ever arrives through a reveal.
              The length doubles as the mask here: it is what the operator sees until they
              buy the rest, and a `null` (no transcript) correctly gets no affordance. */}
          <RevealableText
            masked={transcriptLength}
            field="generation_attempts.stt_transcript"
            recordId={attempt.id}
            orderId={attempt.orderId}
            subjectLabel={subjectLabel}
            purgedAt={attempt.textPurgedAt}
          />
        </Field>
      </Section>

      <Section title={t("generations.detail.telemetry")}>
        <Field label={t("generations.fields.cost")}>
          <span className={cn(VALUE_CLASS, !attempt.isInstrumented && "text-ink-400")}>
            {formatCostUsd(attempt.costUsd, attempt.isInstrumented)}
          </span>
          {attempt.costSource === null || !attempt.isInstrumented ? null : (
            <span className={cn(NOTE_CLASS, "ml-2 inline")}>{attempt.costSource}</span>
          )}
        </Field>
        <Field label={t("generations.fields.latency")}>
          <span className={cn(VALUE_CLASS, !attempt.isInstrumented && "text-ink-400")}>
            {formatLatencyMs(attempt.latencyMs, attempt.isInstrumented)}
          </span>
        </Field>
        {attempt.isInstrumented ? null : (
          <p className={NOTE_CLASS}>
            {`Cost and latency read "${NOT_TRACKED}" because this attempt's telemetry was never ` +
              "written. That is not a measurement of zero."}
          </p>
        )}
      </Section>
    </aside>
  );
}

/* -------------------------------------------------------------------------- */
/* Parts                                                                       */
/* -------------------------------------------------------------------------- */

function Section({
  title,
  children,
}: {
  readonly title: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <section aria-label={title} className="flex flex-col gap-3 border-t border-stroke pt-4">
      <h3 className={cn("m-0", SECTION_TITLE_CLASS)}>{title}</h3>
      <dl className="m-0 flex flex-col gap-3">{children}</dl>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <div className="flex min-w-0 flex-col gap-[2px]">
      <dt className={LABEL_CLASS}>{label}</dt>
      <dd className="m-0 min-w-0">{children}</dd>
    </div>
  );
}

/**
 * A `generation_attempts.*` text column: revealable when there is an order to reveal it
 * against, and honest about it when there is not.
 *
 * Both of this row's plaintext columns are subject-typed `order` server-side, so the whole
 * disclosure — the step-up scope, the audit subject, the read — is keyed on the order's UUID.
 * An orphaned attempt has none, and no re-authentication can invent one, so the masked value
 * stands alone with a sentence saying why rather than beside a button that could only 404.
 *
 * The retention stamp is tested FIRST, because the two clocks run whether or not the attempt
 * ever had an order: a purged orphan carries a stamp and a `null` value, and drawn under the
 * orphan branch it would render a bare em dash — the "purged is not missing" rule inverted.
 */
function RevealableText({
  masked,
  field,
  recordId,
  orderId,
  subjectLabel,
  purgedAt,
}: {
  readonly masked: string | null;
  readonly field: "generation_attempts.stt_transcript" | "generation_attempts.name_candidate_text";
  /** This attempt's id — which record of the ORDER-wide paged reveal this cell is. */
  readonly recordId: string;
  readonly orderId: string | null;
  readonly subjectLabel: string;
  readonly purgedAt: string | null;
}): JSX.Element {
  if (purgedAt !== null) return <PurgedValue purgedAt={purgedAt} />;

  if (orderId === null) {
    return (
      <div className="flex flex-col gap-1">
        <span className={cn(VALUE_CLASS, masked === null && "text-ink-400")}>
          {masked ?? EMPTY_VALUE}
        </span>
        {masked === null ? null : (
          <p className={NOTE_CLASS}>
            This attempt has no order, and a reveal of it is addressed to the order. There is no
            subject to authorise or audit the disclosure against.
          </p>
        )}
      </div>
    );
  }

  return (
    <MaskedValue
      masked={masked}
      field={field}
      subjectId={orderId}
      subjectLabel={subjectLabel}
      recordId={recordId}
      purgedAt={purgedAt}
    />
  );
}
