/**
 * "Now, or at a stated instant" — written once, read by both surfaces that authorise a send.
 *
 * The wizard's review step and the campaign screen's send dialog ask the operator the same
 * question and had grown two answers to it: two `When` unions, two copies of the past-instant
 * check, two `datetime-local` fields and two spellings of the body assembly. Two copies of a
 * validator is two clocks, and the day one of them stops refusing yesterday is the day a
 * campaign goes out against a schedule the other half would have caught.
 *
 * Three things here are load-bearing rather than tidy:
 *
 * 1. **"Now" OMITS `scheduledFor`.** Not `null` for it — its ABSENCE is what makes the server
 *    enqueue the job in the same breath, where a stated instant is left for the due sweep.
 *    {@link sendBodyOf} is the only place that distinction is spelled, so it cannot drift.
 * 2. **A past instant is caught before the press.** The server refuses it against its own
 *    clock, and that refusal costs a round trip and reads as a 422 about a parameter. `min`
 *    on the input discourages it; {@link useSendSchedule} catches what the picker still allows.
 * 3. **`datetime-local`, not a date beside a time.** The server takes one instant, and two
 *    fields are two chances to send tomorrow's campaign today.
 *
 * The copy is `broadcasts.sendDialog.*` in both places on purpose: the sentence an operator
 * reads in the wizard is the sentence they read on the campaign.
 */

import { useCallback, useId, useState, type JSX } from "react";

import type { BroadcastSendRequest } from "@/api/broadcasts";
import type { ReasonedRequest } from "@/api/reveal";
import { Segmented } from "@/components/Segmented";
import { localInstantToIso } from "@/features/broadcasts/broadcastFormat";
import { FIELD_CONTROL_CLASS, SECTION_LABEL_CLASS } from "@/features/reveal/controls";
import { useI18n } from "@/i18n";

/** Now, or at a stated instant. Two decisions an operator makes; one route on the wire. */
export type SendWhen = "now" | "later";

/** What the two surfaces hold while the operator decides, and what they read back. */
export interface SendSchedule {
  readonly when: SendWhen;
  readonly setWhen: (next: SendWhen) => void;
  /** The raw `datetime-local` string, in the operator's own zone. */
  readonly at: string;
  readonly setAt: (next: string) => void;
  /** The instant as RFC 3339, or `null` while "now" or while the value is incomplete. */
  readonly scheduledIso: string | null;
  /** The message under the field; `null` when the choice as it stands is sendable. */
  readonly error: string | null;
  /** Back to "now", with no instant held — what a closed dialog must forget. */
  readonly reset: () => void;
}

export function useSendSchedule(): SendSchedule {
  const { t } = useI18n();
  const [when, setWhen] = useState<SendWhen>("now");
  const [at, setAt] = useState("");

  const scheduledIso = when === "now" ? null : localInstantToIso(at);
  const isInPast = scheduledIso !== null && new Date(scheduledIso).getTime() <= Date.now();
  const error =
    when === "now"
      ? null
      : scheduledIso === null
        ? t("broadcasts.sendDialog.atMissing")
        : isInPast
          ? t("broadcasts.sendDialog.atInPast")
          : null;

  const reset = useCallback(() => {
    setWhen("now");
    setAt("");
  }, []);

  return { when, setWhen, at, setAt, scheduledIso, error, reset };
}

/**
 * The reason, plus the instant or nothing at all.
 *
 * The absent field is the whole distinction between `sendBroadcastNow` and `scheduleBroadcast`,
 * one layer down; this is the body half of it.
 */
export function sendBodyOf(reason: ReasonedRequest, schedule: SendSchedule): BroadcastSendRequest {
  return schedule.scheduledIso === null
    ? { ...reason }
    : { ...reason, scheduledFor: schedule.scheduledIso };
}

export interface SendScheduleFieldsetProps {
  readonly schedule: SendSchedule;
  /** Locked while the send is in flight — the instant is already on its way. */
  readonly isDisabled?: boolean | undefined;
}

/** The now/later toggle, and the instant when "later" is the answer. */
export function SendScheduleFieldset({
  schedule,
  isDisabled = false,
}: SendScheduleFieldsetProps): JSX.Element {
  const { t } = useI18n();
  const { when, setWhen, at, setAt, error } = schedule;
  const id = `${useId()}-send-at`;
  const hintId = `${id}-hint`;

  return (
    <>
      <div className="flex flex-col gap-2">
        <span className={SECTION_LABEL_CLASS}>{t("broadcasts.sendDialog.whenLabel")}</span>
        <Segmented<SendWhen>
          ariaLabel={t("broadcasts.sendDialog.whenLabel")}
          value={when}
          onChange={setWhen}
          options={[
            { value: "now", label: t("broadcasts.sendDialog.whenNow") },
            { value: "later", label: t("broadcasts.sendDialog.whenLater") },
          ]}
        />
      </div>

      {when === "later" ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={id} className={SECTION_LABEL_CLASS}>
            {t("broadcasts.sendDialog.atLabel")}
          </label>
          <input
            id={id}
            type="datetime-local"
            value={at}
            disabled={isDisabled}
            onChange={(event) => {
              setAt(event.target.value);
            }}
            aria-invalid={error !== null}
            aria-describedby={hintId}
            className={FIELD_CONTROL_CLASS}
          />
          <p id={hintId} className="m-0 text-[12px] leading-4 text-ink-400">
            {t("broadcasts.sendDialog.atHint")}
          </p>
          {error === null ? null : (
            <span role="alert" className="text-[12px] leading-4 text-required-deep">
              {error}
            </span>
          )}
        </div>
      ) : null}
    </>
  );
}
