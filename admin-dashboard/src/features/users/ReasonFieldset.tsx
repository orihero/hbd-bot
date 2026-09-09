/**
 * The audit reason, shared by Block/Unblock and Grant credits.
 *
 * Every §9.2 write on this screen takes the same trio — a required `reasonCode` from a closed
 * vocabulary, an optional `reasonRef` (a ticket id) and optional prose — and each is validated
 * HERE, before the request, for one reason that is easy to miss: **a body the server refuses
 * as invalid writes NO audit row.** A 422 is the one failure mode of a privileged action that
 * leaves no trace of the attempt, so a malformed `reasonRef` must be caught in the form rather
 * than discovered by the operator as a red banner with nothing recorded behind it.
 *
 * The prose field is not here: `<ConfirmDialog>` already owns one, and this fieldset is what
 * goes in its `children`. `reasonText` still travels in `ReasonState` so that one object is
 * the whole reason, and `reasonBodyOf` is the only place it is turned into a request body.
 */

import { useId, type JSX } from "react";

import { useI18n } from "@/i18n";

import {
  MAX_REASON_REF_CHARS,
  MAX_REASON_TEXT_CHARS,
  REASON_REF_PATTERN,
} from "@/api/constants";
import { AUDIT_REASON_CODE_VALUES, type AuditReasonCode, type ReasonedRequest } from "@/api/reveal";
import { REVEAL_REASON_KEYS } from "@/features/reveal";
import { FIELD_CONTROL_CLASS, SECTION_LABEL_CLASS } from "@/features/reveal/controls";

/**
 * The audit boundary reads a 40-character run of `[A-Za-z0-9_-]` as a credential and refuses
 * the whole request — before it writes anything. Warned, not blocked: it is a legal
 * `reasonRef` by the pattern, and the operator may have a genuinely long ticket id to shorten.
 */
const CREDENTIAL_SHAPE = /[A-Za-z0-9_-]{40,}/;

/** What a form holds while the operator decides. One object, so nothing travels half-filled. */
export interface ReasonState {
  readonly code: AuditReasonCode | null;
  readonly ref: string;
  readonly text: string;
}

export const EMPTY_REASON: ReasonState = { code: null, ref: "", text: "" };

/** Said in the footer while the confirm is withheld, so the block is explained before the 422. */
export const REASON_CODE_REQUIRED_HINT =
  "Choose a reason code. It is required, it goes on the audit row, and the server refuses the write without one.";

export const REASON_REF_MALFORMED =
  "Letters, digits, #, _ and - only, up to 64 characters. The server refuses anything else — and a refused body writes no audit row, which is the wrong way to fail a privileged action.";

export const REASON_REF_CREDENTIAL_WARNING =
  "40 or more characters of letters, digits, _ and - reads as a credential to the audit boundary, and the write will be refused before it happens. Shorten it, or add a # or another separator.";

/** The caption over the prose field. The customer's words never go in an audit column. */
export const REASON_TEXT_HINT =
  "Your words, not the customer's. Free text on a 90-day sweep — never paste anything the action is about.";

export const REASON_TEXT_LABEL = `why (optional, up to ${String(MAX_REASON_TEXT_CHARS)} characters)`;

/** `true` when the ref is present and cannot be sent. Blocks the confirm. */
export function isReasonRefMalformed(reason: ReasonState): boolean {
  return reason.ref !== "" && !REASON_REF_PATTERN.test(reason.ref);
}

/** `true` when the ref is legal but shaped like a secret. Warns; does not block. */
export function isReasonRefCredentialShaped(reason: ReasonState): boolean {
  return CREDENTIAL_SHAPE.test(reason.ref);
}

/** Everything that must hold before a §9.2 body may be sent. */
export function canSubmitReason(reason: ReasonState): boolean {
  return reason.code !== null && !isReasonRefMalformed(reason);
}

/**
 * The reason as a request body, or `null` when it is not sendable yet.
 *
 * The optional halves are OMITTED rather than sent empty: `""` fails the server's pattern,
 * and a `reasonRef: ""` is a 422 on a field the operator deliberately left blank.
 */
export function reasonBodyOf(reason: ReasonState): ReasonedRequest | null {
  if (!canSubmitReason(reason) || reason.code === null) return null;
  return {
    reasonCode: reason.code,
    ...(reason.ref === "" ? {} : { reasonRef: reason.ref }),
    ...(reason.text === "" ? {} : { reasonText: reason.text }),
  };
}

export interface ReasonFieldsetProps {
  readonly value: ReasonState;
  readonly onChange: (next: ReasonState) => void;
  /** Locked while the write is in flight — the reason is already on its way. */
  readonly isDisabled?: boolean | undefined;
}

export function ReasonFieldset({
  value,
  onChange,
  isDisabled = false,
}: ReasonFieldsetProps): JSX.Element {
  const { t } = useI18n();
  const ids = useId();
  const codeId = `${ids}-code`;
  const refId = `${ids}-ref`;
  const isMalformed = isReasonRefMalformed(value);
  const isCredentialShaped = isReasonRefCredentialShaped(value);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={codeId} className={SECTION_LABEL_CLASS}>
          reason code (required)
        </label>
        <select
          id={codeId}
          data-testid="reason-code"
          value={value.code ?? ""}
          disabled={isDisabled}
          onChange={(event) => {
            onChange({ ...value, code: asReasonCode(event.target.value) });
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
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={refId} className={SECTION_LABEL_CLASS}>
          ticket reference (optional)
        </label>
        <input
          id={refId}
          type="text"
          data-testid="reason-ref"
          value={value.ref}
          maxLength={MAX_REASON_REF_CHARS}
          disabled={isDisabled}
          placeholder={t("users.reasonRefPlaceholder")}
          aria-invalid={isMalformed}
          onChange={(event) => {
            onChange({ ...value, ref: event.target.value });
          }}
          className={FIELD_CONTROL_CLASS}
        />
        {isMalformed ? (
          <span role="alert" className="text-[12px] leading-4 text-required-deep">
            {REASON_REF_MALFORMED}
          </span>
        ) : null}
        {isCredentialShaped ? (
          <span
            role="alert"
            data-testid="reason-ref-credential-warning"
            className="text-[12px] leading-4 text-warn-deep"
          >
            {REASON_REF_CREDENTIAL_WARNING}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** The option values ARE the wire values, so anything else is a bug here, not operator input. */
function asReasonCode(value: string): AuditReasonCode | null {
  return AUDIT_REASON_CODE_VALUES.find((code) => code === value) ?? null;
}
