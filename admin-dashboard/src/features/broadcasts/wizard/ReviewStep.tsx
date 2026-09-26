/**
 * Step 3 — read it back, then authorise it.
 *
 * ## The number is restated, and it is the one that will be frozen
 *
 * Before the campaign exists this is `reachable` from the live preview — the accounts a send
 * would actually attempt, never a sum of the overlapping skips. Once the create has run it is
 * the campaign's own `recipientCount`: the rows that were written, which is what the send will
 * walk. They are two different facts and the panel says which one it is showing.
 *
 * ## The freeze is stated before it happens, not after
 *
 * "Send" here is two calls — `POST /api/broadcasts` freezes the audience by materialising its
 * recipient rows, `POST /{id}/send` authorises the messages — and the operator is told that in
 * the words `broadcasts.audience.frozenNote` uses on the campaign's own screen, so the sentence
 * they read here is the sentence they will read there.
 *
 * ## The transcription box is the last brake
 *
 * BP §5.4 asks the operator to type the audience size. It is not ceremony: every other control
 * on this screen is a click, and the one irreversible act in this section deserves a gesture that
 * cannot be produced by a mis-aimed press. It compares digits only, so `40 000`, `40,000` and
 * `40000` are all the number on screen.
 *
 * ## Now and later are one route
 *
 * `POST /{id}/send` carries `scheduledFor` or omits it, and "now" OMITS it — that absence is what
 * makes the server enqueue the job in the same breath, where a stated instant is left for the due
 * sweep. A past instant is refused here as well as there, because the server's refusal costs a
 * round trip and reads as a 422 about a parameter.
 */

import { useState, type JSX, type ReactNode } from "react";

import type { BroadcastSendRequest, Language } from "@/api/broadcasts";
import { MAX_REASON_TEXT_CHARS } from "@/api/constants";
import type { SegmentFieldView } from "@/api/segments";
import { Badge } from "@/components/Badge";
import { buildSegmentChips } from "@/components/SegmentBuilder";
import {
  BROADCAST_KIND_HINT_KEY,
  BROADCAST_KIND_LABEL_KEY,
  formatAbsolute,
  formatCount,
} from "@/features/broadcasts/broadcastFormat";
import {
  SendScheduleFieldset,
  sendBodyOf,
  useSendSchedule,
} from "@/features/broadcasts/sendSchedule";
import {
  FIELD_CONTROL_CLASS,
  SECTION_LABEL_CLASS,
  TEXTAREA_CONTROL_CLASS,
} from "@/features/reveal/controls";
import {
  EMPTY_REASON,
  REASON_CODE_REQUIRED_HINT,
  REASON_TEXT_HINT,
  REASON_TEXT_LABEL,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { Panel } from "@/features/users/detailKit";
import { useI18n } from "@/i18n";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import { isSegmentEmpty } from "@/lib/segmentCodec";

import { MessagePreview } from "./MessagePreview";
import { bodyAt, type WizardDraft } from "./wizardState";

/** Digits only, so `40 000`, `40,000` and `40000` are all the number that is on screen. */
function digitsOf(value: string): string {
  return value.replace(/\D/gu, "");
}

export interface ReviewStepProps {
  readonly draft: WizardDraft;
  readonly languages: readonly Language[];
  readonly fieldIndex: ReadonlyMap<string, SegmentFieldView>;
  /** `reachable` before the freeze; the campaign's own `recipientCount` after it. */
  readonly audienceCount: number;
  readonly isAudienceFrozen: boolean;
  /** `audienceEvaluatedAt`, once there is a campaign to have evaluated it. */
  readonly frozenAt: string | null;
  readonly onSubmit: (body: BroadcastSendRequest) => void;
  readonly isPending: boolean;
  /** The screen's own failure copy: a drift, a wrong-state 409, a refused send. */
  readonly notice?: ReactNode;
}

export function ReviewStep({
  draft,
  languages,
  fieldIndex,
  audienceCount,
  isAudienceFrozen,
  frozenAt,
  onSubmit,
  isPending,
  notice,
}: ReviewStepProps): JSX.Element {
  const { t, locale } = useI18n();
  const schedule = useSendSchedule();
  const [typedCount, setTypedCount] = useState("");
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  const whenError = schedule.error;

  const isCountConfirmed = digitsOf(typedCount) === String(audienceCount);
  const hasRecipients = audienceCount > 0;
  const canSubmit =
    hasRecipients && whenError === null && isCountConfirmed && canSubmitReason(reason) && !isPending;

  const chips = buildSegmentChips({
    segment: draft.segment,
    fields: fieldIndex,
    t,
    locale,
    // Nothing here edits the audience: on this step it is either about to be frozen or already
    // is, and a remove button would be a control that lies about what it did.
    onChange: () => undefined,
  });

  function submit(): void {
    const reasonBody = reasonBodyOf(reason);
    if (reasonBody === null || !canSubmit) return;
    // "Now" OMITS `scheduledFor`; `sendBodyOf` is the one place that distinction is spelled.
    onSubmit(sendBodyOf(reasonBody, schedule));
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={t("broadcasts.wizard.review.audienceHeading")}
        caption={t("broadcasts.wizard.review.audienceCaption")}
      >
        <p className="m-0 text-[18px] font-semibold leading-6 text-ink-900">
          {isAudienceFrozen
            ? t("broadcasts.wizard.review.audienceFrozenCount", {
                count: formatCount(audienceCount),
              })
            : t("broadcasts.wizard.review.audienceCount", { count: formatCount(audienceCount) })}
        </p>
        <p className="m-0 rounded-field bg-warn-18 p-3 text-[13px] font-semibold text-warn-deep">
          {frozenAt === null
            ? t("broadcasts.wizard.review.freezeWarning")
            : t("broadcasts.audience.frozenNote", { at: formatAbsolute(frozenAt) })}
        </p>
        {isSegmentEmpty(draft.segment) ? (
          <p className="m-0 text-[13px] font-semibold text-warn-deep">
            {t("broadcasts.audience.everyone")}
          </p>
        ) : (
          <div
            role="group"
            aria-label={t("broadcasts.wizard.review.audienceRulesAria")}
            className="flex flex-wrap gap-2"
          >
            {chips.map((chip) => (
              <Badge key={chip.id} tone="accent">
                {`${chip.field}: ${chip.value}`}
              </Badge>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title={t("broadcasts.wizard.review.messageHeading")}
        caption={t("broadcasts.wizard.review.messageCaption")}
      >
        <p className="m-0 text-[14px] font-semibold text-ink-900">{draft.title}</p>
        <p className="m-0 text-[12px] leading-4 text-ink-400">
          {t(BROADCAST_KIND_LABEL_KEY[draft.kind])} — {t(BROADCAST_KIND_HINT_KEY[draft.kind])}
        </p>
        <div className="grid gap-4 lg:grid-cols-2">
          {languages.map((language) => (
            <div key={language} className="flex flex-col gap-2">
              <span className={SECTION_LABEL_CLASS}>{t(LANGUAGE_LABEL_KEY[language])}</span>
              <MessagePreview body={bodyAt(draft, language)} language={language} />
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        title={t("broadcasts.wizard.review.sendHeading")}
        caption={t("broadcasts.wizard.review.sendCaption")}
      >
        <SendScheduleFieldset schedule={schedule} isDisabled={isPending} />

        <ReasonFieldset value={reason} onChange={setReason} isDisabled={isPending} />
        {reason.code === null ? (
          <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
        ) : null}

        {/* The free-text half of the §9.2 trio. `ConfirmDialog` renders it for the dialogs; this
            step is a page, so it renders its own — same label, same cap, same optionality. */}
        <div className="flex flex-col gap-1">
          <label htmlFor="wizard-reason-text" className={SECTION_LABEL_CLASS}>
            {REASON_TEXT_LABEL}
          </label>
          <textarea
            id="wizard-reason-text"
            value={reason.text}
            maxLength={MAX_REASON_TEXT_CHARS}
            disabled={isPending}
            onChange={(event) => {
              setReason((current) => ({ ...current, text: event.target.value }));
            }}
            aria-describedby="wizard-reason-text-hint"
            className={TEXTAREA_CONTROL_CLASS}
          />
          <p id="wizard-reason-text-hint" className="m-0 text-[12px] leading-4 text-ink-400">
            {REASON_TEXT_HINT}
          </p>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="wizard-confirm-count" className={SECTION_LABEL_CLASS}>
            {t("broadcasts.wizard.review.confirmLabel", { count: formatCount(audienceCount) })}
          </label>
          <input
            id="wizard-confirm-count"
            type="text"
            inputMode="numeric"
            value={typedCount}
            onChange={(event) => {
              setTypedCount(event.target.value);
            }}
            aria-describedby="wizard-confirm-count-hint"
            aria-invalid={typedCount !== "" && !isCountConfirmed}
            className={FIELD_CONTROL_CLASS}
          />
          <p id="wizard-confirm-count-hint" className="m-0 text-[12px] leading-4 text-ink-400">
            {t("broadcasts.wizard.review.confirmHint")}
          </p>
          {typedCount === "" || isCountConfirmed ? null : (
            <span role="alert" className="text-[12px] leading-4 text-required-deep">
              {t("broadcasts.wizard.review.confirmMismatch", {
                count: formatCount(audienceCount),
              })}
            </span>
          )}
        </div>

        {notice}

        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="w-fit rounded-button bg-accent px-4 py-2.5 text-[14px] font-semibold text-on-accent outline-none transition-[filter] hover:brightness-95 focus-visible:ring-2 focus-visible:ring-accent-deep disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isPending
            ? t("broadcasts.wizard.review.pending")
            : schedule.when === "now"
              ? t("broadcasts.wizard.review.submitNow", { count: formatCount(audienceCount) })
              : t("broadcasts.wizard.review.submitLater", { count: formatCount(audienceCount) })}
        </button>
        {hasRecipients ? null : (
          <p role="status" className="m-0 text-[13px] font-medium text-required-deep">
            {t("broadcasts.sendDialog.noRecipients")}
          </p>
        )}
      </Panel>
    </div>
  );
}
