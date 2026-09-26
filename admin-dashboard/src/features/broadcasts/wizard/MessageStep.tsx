/**
 * Step 2 — what it says, in every language the audience reads.
 *
 * ## The counter measures the string that will be SENT
 *
 * The server bounds a body twice against one ceiling: the raw text, and the text once literal
 * runs are escaped and allowlisted tags are re-emitted. `&` costs one character in this textarea
 * and five on the wire; `&nbsp;` costs six here and one there. So the counter shows both numbers
 * and the limit is applied to the larger — a counter over `value.length` alone would let a body
 * through and lose the campaign to a 422 the editor gave no warning of.
 *
 * ## The markup is an allowlist, and a refusal names the rule
 *
 * `TELEGRAM_BODY_TAGS` is what Telegram's parser accepts. Anything else — an unknown tag, an
 * attribute, a self-closing tag, an unclosed one — is refused by name of the rule rather than
 * stripped, because a `<script>` silently deleted teaches an operator nothing and an unclosed
 * `<b>` silently closed changes what the message says. An unclosed tag is a `TelegramBadRequest`
 * for EVERY recipient, so catching it in a form is the difference between a typo and a dead
 * campaign.
 *
 * ## One body per language the audience actually reads
 *
 * The tabs come from `GET /api/segments/preview`'s `byLanguage`, which is the audience's own
 * split. A language nobody in it reads is not offered — that body would reach nobody — and a
 * language somebody does read cannot be skipped, because the alternative is a person in the
 * audience who receives nothing.
 *
 * ## The kind is stated as its consequence
 *
 * `service` and `marketing` are not two labels for one thing: the kind selects the eligibility
 * rule the audience was built under, and it is the one control here that can widen who a message
 * reaches. So the sentence under the choice says what it DOES, and it is the catalogue's, in
 * three languages.
 */

import { type JSX } from "react";

import {
  BROADCAST_KIND_VALUES,
  TELEGRAM_BODY_TAGS,
  type BroadcastKind,
  type Language,
} from "@/api/broadcasts";
import {
  MAX_BROADCAST_BUTTON_LABEL_CHARS,
  MAX_BROADCAST_BUTTON_URL_CHARS,
  MAX_BROADCAST_MEDIA_KEY_CHARS,
  MAX_BROADCAST_TITLE_CHARS,
} from "@/api/constants";
import type { SegmentPreviewView } from "@/api/segments";
import { Badge } from "@/components/Badge";
import { Segmented } from "@/components/Segmented";
import {
  BROADCAST_KIND_HINT_KEY,
  BROADCAST_KIND_LABEL_KEY,
  formatCount,
  type Translate,
} from "@/features/broadcasts/broadcastFormat";
import { FIELD_CONTROL_CLASS, SECTION_LABEL_CLASS } from "@/features/reveal/controls";
import { Panel } from "@/features/users/detailKit";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";

import { codePointLength } from "./bodyMarkup";
import { MessagePreview } from "./MessagePreview";
import {
  bodyAt,
  bodyIssues,
  bodyLimitOf,
  bodyScan,
  withBody,
  type BodyDraft,
  type BodyIssue,
  type MessageRefusal,
  type WizardDraft,
} from "./wizardState";

const ISSUE_KEY: Readonly<Record<BodyIssue["code"], TranslationPath>> = {
  empty: "broadcasts.wizard.message.issues.empty",
  blankText: "broadcasts.wizard.message.issues.blankText",
  incompleteTag: "broadcasts.wizard.message.issues.incompleteTag",
  unknownTag: "broadcasts.wizard.message.issues.unknownTag",
  badAttribute: "broadcasts.wizard.message.issues.badAttribute",
  selfClosing: "broadcasts.wizard.message.issues.selfClosing",
  unbalanced: "broadcasts.wizard.message.issues.unbalanced",
  nestedLink: "broadcasts.wizard.message.issues.nestedLink",
  notMarkup: "broadcasts.wizard.message.issues.notMarkup",
  badHref: "broadcasts.wizard.message.issues.badHref",
  tooLong: "broadcasts.wizard.message.issues.tooLong",
  badUrl: "broadcasts.wizard.message.issues.badUrl",
  buttonPair: "broadcasts.wizard.message.issues.buttonPair",
  badStorageKey: "broadcasts.wizard.message.issues.badStorageKey",
};

/** One refusal, in the words of the rule it broke. */
export function issueMessage(t: Translate, issue: BodyIssue): string {
  if (issue.code === "tooLong") {
    return t(ISSUE_KEY.tooLong, {
      limit: formatCount(issue.limit ?? 0),
      actual: formatCount(issue.actual ?? 0),
    });
  }
  return t(ISSUE_KEY[issue.code]);
}

const TEXTAREA_CLASS =
  "min-h-[180px] w-full resize-y rounded-field border border-stroke bg-card p-3 " +
  "font-mono text-[13px] leading-5 text-ink-900 shadow-field outline-none transition-shadow " +
  "placeholder:text-muted focus:border-accent-deep focus:ring-2 focus:ring-accent " +
  "disabled:cursor-not-allowed disabled:opacity-60";

export interface MessageStepProps {
  readonly draft: WizardDraft;
  readonly onChange: (next: WizardDraft) => void;
  /** The audience's own languages, from the preview breakdown. */
  readonly languages: readonly Language[];
  readonly language: Language | null;
  readonly onLanguageChange: (next: Language) => void;
  readonly preview: SegmentPreviewView | null;
  readonly refusal: MessageRefusal | null;
  /** Present only while the deployment has a test-send allowlist to send to. */
  readonly onTestSend: (() => void) | null;
  readonly isTestSendPending: boolean;
}

export function MessageStep({
  draft,
  onChange,
  languages,
  language,
  onLanguageChange,
  preview,
  refusal,
  onTestSend,
  isTestSendPending,
}: MessageStepProps): JSX.Element {
  const { t } = useI18n();
  const counts = new Map(preview?.byLanguage.map((entry) => [entry.language, entry.count]) ?? []);

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={t("broadcasts.wizard.message.heading")}
        caption={t("broadcasts.wizard.message.caption")}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="wizard-title" className={SECTION_LABEL_CLASS}>
            {t("broadcasts.wizard.message.titleLabel")}
          </label>
          <input
            id="wizard-title"
            type="text"
            value={draft.title}
            maxLength={MAX_BROADCAST_TITLE_CHARS}
            onChange={(event) => {
              onChange({ ...draft, title: event.target.value });
            }}
            aria-describedby="wizard-title-hint"
            aria-invalid={refusal?.isTitleMissing === true || refusal?.isTitleTooLong === true}
            className={FIELD_CONTROL_CLASS}
          />
          <p id="wizard-title-hint" className="m-0 text-[12px] leading-4 text-ink-400">
            {t("broadcasts.wizard.message.titleHint", {
              limit: formatCount(MAX_BROADCAST_TITLE_CHARS),
            })}
          </p>
          {refusal?.isTitleMissing === true ? (
            <span role="alert" className="text-[12px] leading-4 text-required-deep">
              {t("broadcasts.wizard.message.titleMissing")}
            </span>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <span className={SECTION_LABEL_CLASS} id="wizard-kind-label">
            {t("broadcasts.wizard.message.kindLabel")}
          </span>
          <Segmented<BroadcastKind>
            ariaLabel={t("broadcasts.wizard.message.kindLabel")}
            value={draft.kind}
            onChange={(kind) => {
              onChange({ ...draft, kind });
            }}
            options={BROADCAST_KIND_VALUES.map((kind) => ({
              value: kind,
              label: t(BROADCAST_KIND_LABEL_KEY[kind]),
            }))}
          />
          <p className="m-0 text-[12px] leading-4 text-ink-400">
            {t(BROADCAST_KIND_HINT_KEY[draft.kind])}
          </p>
        </div>
      </Panel>

      {language === null ? (
        <Panel title={t("broadcasts.wizard.message.bodiesHeading")}>
          <p className="m-0 text-[13px] text-required-deep">
            {t("broadcasts.wizard.message.noLanguages")}
          </p>
        </Panel>
      ) : (
        <Panel
          title={t("broadcasts.wizard.message.bodiesHeading")}
          caption={t("broadcasts.wizard.message.bodiesCaption")}
          actions={
            onTestSend === null ? undefined : (
              <button
                type="button"
                onClick={onTestSend}
                disabled={isTestSendPending}
                aria-label={t("broadcasts.wizard.message.testSend.actionAria")}
                className="rounded-field border border-stroke bg-card px-3 py-2 text-[13px] font-semibold text-ink-800 outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
              >
                {t("broadcasts.wizard.message.testSend.action")}
              </button>
            )
          }
        >
          {languages.length < 2 ? null : (
            /* A group of toggles rather than a `tablist`: there is one editor below and it is
               not a tabpanel, and half-implemented tab semantics (no roving tabindex, no
               `aria-controls`) announce a widget that does not behave like one. */
            <div
              role="group"
              aria-label={t("broadcasts.wizard.message.languagesAria")}
              className="flex flex-wrap gap-2"
            >
              {languages.map((entry) => {
                const isDone = bodyIssues(bodyAt(draft, entry)).length === 0;
                const isCurrent = entry === language;
                return (
                  <button
                    key={entry}
                    type="button"
                    aria-pressed={isCurrent}
                    onClick={() => {
                      onLanguageChange(entry);
                    }}
                    className={
                      "flex items-center gap-2 rounded-field border px-3 py-2 text-[13px] font-semibold outline-none focus-visible:ring-2 focus-visible:ring-accent " +
                      (isCurrent
                        ? "border-accent-deep bg-accent-12 text-ink-900"
                        : "border-stroke bg-card text-ink-500")
                    }
                  >
                    <span>{t(LANGUAGE_LABEL_KEY[entry])}</span>
                    <span className="text-[12px] font-normal text-ink-400">
                      {formatCount(counts.get(entry) ?? 0)}
                    </span>
                    <Badge tone={isDone ? "accent" : "muted"}>
                      {isDone
                        ? t("broadcasts.wizard.message.languageReady")
                        : t("broadcasts.wizard.message.languageMissing")}
                    </Badge>
                  </button>
                );
              })}
            </div>
          )}

          <BodyEditor
            language={language}
            body={bodyAt(draft, language)}
            onChange={(body) => {
              onChange(withBody(draft, language, body));
            }}
          />
        </Panel>
      )}

      {refusal === null || refusal.blocking.length === 0 ? null : (
        <p role="status" className="m-0 text-[13px] font-medium text-required-deep">
          {t("broadcasts.wizard.message.incomplete", {
            languages: refusal.blocking.map((entry) => t(LANGUAGE_LABEL_KEY[entry])).join(", "),
          })}
        </p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One language's message                                                      */
/* -------------------------------------------------------------------------- */

function BodyEditor({
  language,
  body,
  onChange,
}: {
  readonly language: Language;
  readonly body: BodyDraft;
  readonly onChange: (next: BodyDraft) => void;
}): JSX.Element {
  const { t } = useI18n();
  const scan = bodyScan(body);
  const limit = bodyLimitOf(body);
  const rawLength = codePointLength(body.text);
  const renderedLength = scan.ok ? scan.renderedLength : rawLength;
  const measured = Math.max(rawLength, renderedLength);
  const issues = body.text === "" ? [] : bodyIssues(body);

  const textId = `wizard-body-${language}`;
  const countId = `${textId}-count`;
  const hintId = `${textId}-hint`;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor={textId} className={SECTION_LABEL_CLASS}>
            {t("broadcasts.wizard.message.bodyLabel", {
              language: t(LANGUAGE_LABEL_KEY[language]),
            })}
          </label>
          <textarea
            id={textId}
            value={body.text}
            onChange={(event) => {
              onChange({ ...body, text: event.target.value });
            }}
            aria-describedby={`${countId} ${hintId}`}
            aria-invalid={issues.length > 0}
            className={TEXTAREA_CLASS}
          />
          <p
            id={countId}
            aria-live="polite"
            className={
              measured > limit
                ? "m-0 text-[12px] font-semibold leading-4 text-required-deep"
                : "m-0 text-[12px] leading-4 text-ink-400"
            }
          >
            {t("broadcasts.wizard.message.counter", {
              sent: formatCount(renderedLength),
              limit: formatCount(limit),
              typed: formatCount(rawLength),
            })}
          </p>
          <p id={hintId} className="m-0 text-[12px] leading-4 text-ink-400">
            {t("broadcasts.wizard.message.markupHint", {
              tags: TELEGRAM_BODY_TAGS.join(", "),
            })}
          </p>
        </div>

        {issues.length === 0 ? null : (
          <ul role="alert" className="m-0 flex list-none flex-col gap-1 p-0">
            {issues.map((issue) => (
              <li key={issue.code} className="text-[12px] leading-4 text-required-deep">
                {issueMessage(t, issue)}
              </li>
            ))}
          </ul>
        )}

        <TextField
          id={`${textId}-media`}
          label={t("broadcasts.wizard.message.imageLabel")}
          hint={t("broadcasts.wizard.message.imageHint")}
          value={body.mediaStorageKey}
          maxLength={MAX_BROADCAST_MEDIA_KEY_CHARS}
          onChange={(mediaStorageKey) => {
            onChange({ ...body, mediaStorageKey });
          }}
        />

        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            id={`${textId}-button-label`}
            label={t("broadcasts.wizard.message.buttonLabelLabel")}
            hint={t("broadcasts.wizard.message.buttonHint")}
            value={body.buttonLabel}
            maxLength={MAX_BROADCAST_BUTTON_LABEL_CHARS}
            onChange={(buttonLabel) => {
              onChange({ ...body, buttonLabel });
            }}
          />
          <TextField
            id={`${textId}-button-url`}
            label={t("broadcasts.wizard.message.buttonUrlLabel")}
            hint={t("broadcasts.wizard.message.buttonUrlHint")}
            value={body.buttonUrl}
            maxLength={MAX_BROADCAST_BUTTON_URL_CHARS}
            onChange={(buttonUrl) => {
              onChange({ ...body, buttonUrl });
            }}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className={SECTION_LABEL_CLASS}>
          {t("broadcasts.wizard.message.previewHeading")}
        </span>
        <MessagePreview body={body} language={language} />
        <p className="m-0 text-[12px] leading-4 text-ink-400">
          {t("broadcasts.wizard.message.previewCaption")}
        </p>
      </div>
    </div>
  );
}

function TextField({
  id,
  label,
  hint,
  value,
  maxLength,
  onChange,
}: {
  readonly id: string;
  readonly label: string;
  readonly hint: string;
  readonly value: string;
  readonly maxLength: number;
  readonly onChange: (next: string) => void;
}): JSX.Element {
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className={SECTION_LABEL_CLASS}>
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        maxLength={maxLength}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        aria-describedby={hintId}
        className={FIELD_CONTROL_CLASS}
      />
      <p id={hintId} className="m-0 text-[12px] leading-4 text-ink-400">
        {hint}
      </p>
    </div>
  );
}
