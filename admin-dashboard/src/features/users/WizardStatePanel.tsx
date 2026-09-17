/**
 * The live wizard draft, rendered as **presence and counts and nothing else**.
 *
 * For an abandoned session this draft is the only copy of the recipient's name, the note and
 * the whole approved lyric that exists anywhere — it is not in the database, because the person
 * never confirmed an order. The server has already applied a key allowlist; this panel is the
 * second half of the same rule and is deliberately stricter than the wire in one place:
 *
 * `choices` arrives as `Record<string, string>` — snake_case keys with **bare-`string` values**,
 * because they come from Redis JSON that a possibly-older build wrote. A value that cannot be
 * proven to be one of our closed vocabularies is draft content, so only the KEY is drawn. What
 * an operator needs from this panel is "how far did they get and what is holding" — presence
 * answers that, and there is no reveal route for a wizard draft at all, so an affordance here
 * would be a button that cannot succeed.
 *
 * Three states, and none of them is an error:
 *
 *  - **`isStatePresent: false`** — the normal state of everyone not mid-flow right now. It can
 *    also mean the abandoned-draft sweep already ran, which is why the panel says both.
 *  - **`charCount: null`** — the key is absent from the draft entirely.
 *  - **`charCount: 0`** — the key is there and holds an empty string. That is the difference
 *    between "never started the note" and "typed a note and deleted it".
 *
 * `GET /wizard-state` never 404s: every id answers.
 */

import type { JSX } from "react";

import type { WizardStateView } from "@/api/users";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";

import { MONO_CLASS, PANEL_NOTE_CLASS, Panel } from "./detailKit";
import { formatInteger, humaniseEnum } from "./detailFormat";

/** What a text field renders when the key is absent from the draft entirely. */
export const FIELD_ABSENT_LABEL = "not started";
/** What it renders when the key is present and holds an empty string. */
export const FIELD_EMPTY_LABEL = "present, empty";

export interface WizardStatePanelProps {
  readonly state: WizardStateView;
}

export function WizardStatePanel({ state }: WizardStatePanelProps): JSX.Element {
  const { t } = useI18n();

  if (!state.isStatePresent) {
    return (
      <Panel title={t("users.wizard.title")} ariaLabel={t("users.wizard.aria")}>
        <p className={PANEL_NOTE_CLASS}>{t("users.wizard.noDraft")}</p>
      </Panel>
    );
  }

  const choiceKeys = Object.keys(state.choices).sort((left, right) => left.localeCompare(right));

  return (
    <Panel title={t("users.wizard.title")} ariaLabel={t("users.wizard.aria")}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {/* The raw FSM state — the STEP, which is exposable. */}
        <span className={cn(MONO_CLASS, "rounded-button bg-bg px-2 py-1 text-ink-800")}>
          {state.state ?? t("users.wizard.noStepRecorded")}
        </span>
        <span className="text-[12px] leading-4 text-ink-400">{t("users.wizard.step")}</span>
      </div>

      <p className={PANEL_NOTE_CLASS}>
        {t("users.wizard.presenceOnly")}
      </p>

      <div className="flex flex-col gap-2">
        <h4 className="m-0 text-[12px] font-semibold leading-4 text-ink-800">
          {`choices ${formatInteger(choiceKeys.length)}`}
        </h4>
        {choiceKeys.length === 0 ? (
          <p className={PANEL_NOTE_CLASS}>{t("users.wizard.nothingChosen")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {choiceKeys.map((key) => (
              <li
                key={key}
                data-testid="wizard-choice"
                data-choice={key}
                className="inline-flex items-baseline gap-1.5 rounded-pill bg-accent-12 px-3 py-1 text-[12px] leading-4 text-ink-800"
              >
                <span aria-hidden className="text-accent-deep">
                  ✓
                </span>
                {/* The KEY, never `state.choices[key]`. See the header note. */}
                <span>{humaniseEnum(key)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <h4 className="m-0 text-[12px] font-semibold leading-4 text-ink-800">text fields</h4>
        {state.textFields.length === 0 ? (
          <p className={PANEL_NOTE_CLASS}>{t("users.wizard.noTextFields")}</p>
        ) : (
          <dl className="m-0 flex flex-col gap-2">
            {state.textFields.map((field) => (
              <div
                key={field.key}
                data-testid="wizard-text-field"
                data-field={field.key}
                data-present={String(field.isPresent)}
                className="flex items-baseline justify-between gap-3"
              >
                <dt className="text-[12px] leading-4 text-ink-400">{humaniseEnum(field.key)}</dt>
                <dd className="m-0 text-[12px] leading-4 text-ink-800">
                  {field.charCount === null
                    ? FIELD_ABSENT_LABEL
                    : field.charCount === 0
                      ? FIELD_EMPTY_LABEL
                      : `${formatInteger(field.charCount)} chars`}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      <div className="flex items-baseline justify-between gap-3 border-t border-stroke pt-4">
        <span className="text-[12px] leading-4 text-ink-400">lyric writes</span>
        <span className="text-[12px] leading-4 text-ink-800">
          {/* `null` is "not recorded", which is not the same as nobody having written any. */}
          {state.lyricWrites === null ? "not recorded" : formatInteger(state.lyricWrites)}
        </span>
      </div>
    </Panel>
  );
}
