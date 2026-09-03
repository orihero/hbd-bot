/**
 * The live wizard draft, rendered as **presence and counts and nothing else**.
 *
 * §12.3's table has one row that is stricter than every other:
 *
 * > **FSM wizard-draft fields (Redis)** — Hidden at every role; only key presence, char
 * > counts and the step are exposed, via a key allowlist in the serializer.
 *
 * For an abandoned session that draft is the only copy of the recipient's name, the note and
 * the whole approved lyric that exists anywhere — it is not in the database, because the
 * person never confirmed an order. §14's acceptance is the matching assertion:
 * `/users/{tg}/wizard-state` must contain no substring of the fixture draft's plaintext **at
 * any role**, OWNER included. The plaintext is reachable only through `POST /reveal`
 * (`subjectType="wizard_draft"`), which is Phase 2 and does not exist on this build.
 *
 * The server has already applied the allowlist. This panel is the second half of the same
 * rule, and it is deliberately stricter than the wire in one place: `WizardStateView.choices`
 * arrives as `Record<string, string>` — snake_case keys with **bare-`string` values**,
 * because they come from Redis JSON that a possibly-older build wrote, which is exactly why
 * `schemas.ts` refuses to type them as enums. A value that cannot be proven to be one of our
 * closed vocabularies is draft content, so only the KEY is drawn. What an operator needs
 * from this panel is "how far did they get and what is holding" — presence answers that.
 *
 * `charCount` is tri-state and the three readings are different facts:
 * `null` = the key is absent, `0` = present and empty, `n` = present with `n` characters.
 *
 * ## Why the panel no longer prints its own title
 *
 * The reskin's idiom puts a plain section label ABOVE a card rather than a heading inside
 * it, and `UserDetailScreen` supplies "Wizard session" there. Printing it twice would be the
 * loudest thing on a panel whose entire content is deliberately quiet. The `<section>` keeps
 * an `aria-label` so the landmark is still named for a screen reader reading the panel on
 * its own, which the visible `h2` used to do.
 */

import type { ReactElement } from "react";

import { WIZARD_CHOICE_KEYS, type WizardStateView } from "@/api";
import { EMPTY_VALUE, cn, formatInteger, humaniseEnum } from "@/lib";

export interface WizardStatePanelProps {
  readonly state: WizardStateView;
  readonly className?: string;
}

/** What a text field renders when the key is absent from the draft entirely. */
export const FIELD_ABSENT_LABEL = "not started";
/** What it renders when the key is present and holds an empty string. */
export const FIELD_EMPTY_LABEL = "present, empty";

export function WizardStatePanel({ state, className }: WizardStatePanelProps): ReactElement {
  if (!state.isStatePresent) {
    return (
      <section
        aria-label="wizard session"
        data-testid="wizard-state"
        data-present="false"
        className={cn("rounded-card bg-surface-card p-card shadow-card", className)}
      >
        <p className="type-body-sm text-ink-muted">
          No draft in Redis for this Telegram id. Either they are not mid-wizard, or the
          session expired.
        </p>
      </section>
    );
  }

  const choiceCount = WIZARD_CHOICE_KEYS.filter((key) => key in state.choices).length;

  return (
    <section
      aria-label="wizard session"
      data-testid="wizard-state"
      data-present="true"
      className={cn(
        "flex flex-col gap-5 rounded-card bg-surface-card p-card shadow-card",
        className,
      )}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        {/* aiogram's raw state string — the STEP, which §12.3 names as exposable. */}
        <span className="type-mono rounded-control bg-surface-control px-2.5 py-1 text-ink">
          {state.state ?? EMPTY_VALUE}
        </span>
        <span className="type-body-sm text-ink-muted">step</span>
      </header>

      <p className="type-body-sm text-ink-muted">
        presence and counts only — the draft's text is never on this wire at any role
      </p>

      <div className="flex flex-col gap-2">
        <h3 className="type-body-sm text-ink-muted">
          choices <span className="num text-ink">{`${formatInteger(choiceCount)}/${formatInteger(WIZARD_CHOICE_KEYS.length)}`}</span>
        </h3>
        <ul className="flex flex-wrap gap-1.5">
          {WIZARD_CHOICE_KEYS.map((key) => {
            const isPresent = key in state.choices;
            return (
              <li
                key={key}
                data-testid="wizard-choice"
                data-choice={key}
                data-present={String(isPresent)}
                /* Ground and glyph carry the state; the WORD stays `--ink`/`--ink-muted`,
                   so presence is never colour alone and never below the text bar. */
                className={cn(
                  "type-body-sm inline-flex items-baseline gap-1.5 rounded-pill px-3 py-1",
                  isPresent ? "bg-success-tint text-ink" : "bg-surface-control text-ink-muted",
                )}
              >
                <span aria-hidden="true" className={isPresent ? "text-success" : "text-neutral"}>
                  {isPresent ? "✓" : "○"}
                </span>
                {/* The KEY, never `state.choices[key]`. See the header note. */}
                <span>{humaniseEnum(key)}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="type-body-sm text-ink-muted">text fields</h3>
        <dl className="flex flex-col gap-2">
          {state.textFields.map((field) => (
            <div
              key={field.key}
              data-testid="wizard-text-field"
              data-field={field.key}
              data-present={String(field.isPresent)}
              className="flex items-baseline justify-between gap-3"
            >
              <dt className="type-body-sm text-ink-muted">{humaniseEnum(field.key)}</dt>
              <dd className="type-body-sm num text-ink">
                {field.charCount === null
                  ? FIELD_ABSENT_LABEL
                  : field.charCount === 0
                    ? FIELD_EMPTY_LABEL
                    : `${formatInteger(field.charCount)} chars`}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="flex items-baseline justify-between gap-3 border-t border-hairline pt-4">
        <span className="type-body-sm text-ink-muted">lyric writes</span>
        <span className="type-body-sm num text-ink">{formatInteger(state.lyricWrites)}</span>
      </div>
    </section>
  );
}
