/**
 * The six things that have to happen for money to become a song, and where this payment got to.
 *
 * This is the dossier's dominant panel and the section's whole value over reading the tables by
 * hand. It **computes nothing**: `status`, `at` and `noteCode` are all decided on the server by
 * `schemas/billing.py::build_lifeline`, so the four-state logic is unit-tested there without a
 * router, and two clients cannot invent a fifth state between them. What this file owns is the
 * rendering — a mark, a word, an instant and a sentence — and it is testable against a fixture
 * array with no query client and no server.
 *
 * ## Four states, and why the fourth exists
 *
 * `done` / `pending` / `missing` would have been the obvious three, and it would have called
 * two perfectly complete payments broken. A PLAN sale grants no credit at purchase — a plan
 * mints songs as they are used — and a payment whose buyer asked to be forgotten between paying
 * and settling gets no receipt at all, because there is nobody left to sell to. Both are
 * `not_applicable`: the step will never happen, and that is correct. Painting either red would
 * send an operator hunting for a defect the system deliberately produced.
 *
 * ## `status` is what the panel can SEE; `noteCode` is WHY
 *
 * They are separate fields because they answer separate questions, and a note can ride on any
 * status. `already_told` sits on a DONE step — "was the confirmation sent, and when?" is what
 * the operator opened this dossier to ask. `purged` sits on a MISSING one and changes its
 * meaning entirely: the evidence aged out on a retention schedule, so the step happened and the
 * row that recorded it is gone. Rendering the status without the note would turn a normal
 * thirteen-month-old payment into an incident.
 *
 * Every one of the server's seven note codes is reachable and every one has a string in all
 * three locales — `Lifeline.test.tsx` asserts exactly that, because a note code with no
 * translation renders as its own slug on the one panel whose job is explaining things.
 */

import { Check, CircleSlash, Clock, TriangleAlert, type LucideIcon } from "lucide-react";
import type { JSX } from "react";

import type { Lifeline as LifelineData, LifelineNote, LifelineStatus, LifelineStep } from "@/api/billing";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";

import { Instant } from "./instants";

/** The step's name, in the operator's language. Never the wire slug. */
const STEP_KEYS: Readonly<Record<LifelineStep, TranslationPath>> = {
  opened: "billing.lifeline.steps.opened",
  rail_transaction: "billing.lifeline.steps.railTransaction",
  performed: "billing.lifeline.steps.performed",
  receipt: "billing.lifeline.steps.receipt",
  credit_granted: "billing.lifeline.steps.creditGranted",
  customer_told: "billing.lifeline.steps.customerTold",
};

const STATUS_KEYS: Readonly<Record<LifelineStatus, TranslationPath>> = {
  done: "billing.lifeline.status.done",
  pending: "billing.lifeline.status.pending",
  not_applicable: "billing.lifeline.status.notApplicable",
  missing: "billing.lifeline.status.missing",
};

const NOTE_KEYS: Readonly<Record<LifelineNote, TranslationPath>> = {
  never_opened: "billing.lifeline.notes.neverOpened",
  awaiting_rail: "billing.lifeline.notes.awaitingRail",
  buyer_erased: "billing.lifeline.notes.buyerErased",
  plan_grants_nothing: "billing.lifeline.notes.planGrantsNothing",
  not_settled: "billing.lifeline.notes.notSettled",
  already_told: "billing.lifeline.notes.alreadyTold",
  purged: "billing.lifeline.notes.purged",
};

/**
 * A mark per state, and it is never the only channel.
 *
 * The word beside it says the same thing — colour and shape are not information anybody is
 * required to be able to see, and this panel is read under pressure. `not_applicable` gets a
 * struck circle rather than a cross: a cross reads as failure, and the whole point of that
 * state is that nothing failed.
 */
const STATUS_ICON: Readonly<Record<LifelineStatus, LucideIcon>> = {
  done: Check,
  pending: Clock,
  not_applicable: CircleSlash,
  missing: TriangleAlert,
};

/**
 * `missing` is the only state drawn in the alarm colour, and only one step can honestly reach
 * it on a healthy payment: a settled sale whose confirmation never went out. Everything else
 * that looks like an absence is `not_applicable` and is drawn in the muted ramp — quieter than
 * `pending`, because it is finished rather than waiting.
 */
const STATUS_MARK_CLASS: Readonly<Record<LifelineStatus, string>> = {
  done: "bg-accent-70 text-ink-800",
  pending: "bg-bg text-ink-400",
  not_applicable: "bg-bg text-ink-300",
  missing: "bg-required-24 text-required-deep",
};

const STATUS_WORD_CLASS: Readonly<Record<LifelineStatus, string>> = {
  done: "text-ink-800",
  pending: "text-ink-400",
  not_applicable: "text-ink-300",
  missing: "text-required-deep",
};

export interface LifelineProps {
  readonly lifeline: LifelineData;
  readonly className?: string | undefined;
}

export function Lifeline({ lifeline, className }: LifelineProps): JSX.Element {
  const { t } = useI18n();

  return (
    <section
      aria-label={t("billing.lifeline.title")}
      className={cn("rounded-card border border-stroke bg-card p-4", className)}
    >
      <h2 className="m-0 text-[16px] font-semibold leading-[21.856px] tracking-[-0.32px] text-ink-900">
        {t("billing.lifeline.title")}
      </h2>

      {/* An ordered list, because the order is the meaning: each step is downstream of the one
          above it, and a screen reader should walk them in that order and be told so. */}
      <ol className="m-0 mt-4 flex list-none flex-col gap-0 p-0">
        {lifeline.steps.map((step, index) => {
          const Icon = STATUS_ICON[step.status];
          const isLast = index === lifeline.steps.length - 1;
          return (
            <li
              key={step.key}
              data-testid={`lifeline-step-${step.key}`}
              data-status={step.status}
              className="flex gap-3"
            >
              <div className="flex flex-col items-center">
                <span
                  aria-hidden
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                    STATUS_MARK_CLASS[step.status],
                  )}
                >
                  <Icon className="h-3 w-3" strokeWidth={2.5} />
                </span>
                {/* The rail between marks. Decorative, and absent under the last step so the
                    list does not appear to continue past its end. */}
                {isLast ? null : <span aria-hidden className="w-px flex-1 bg-stroke" />}
              </div>

              <div className={cn("flex min-w-0 flex-col gap-[2px]", isLast ? "pb-0" : "pb-4")}>
                <p className="m-0 flex flex-wrap items-baseline gap-2">
                  <span className="text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-900">
                    {t(STEP_KEYS[step.key])}
                  </span>
                  <span
                    className={cn(
                      "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px]",
                      STATUS_WORD_CLASS[step.status],
                    )}
                  >
                    {t(STATUS_KEYS[step.status])}
                  </span>
                </p>

                {step.at === null ? null : (
                  <Instant at={step.at} className="text-[12px] leading-4 text-ink-500" />
                )}

                {step.noteCode === null ? null : (
                  <p
                    data-testid={`lifeline-note-${step.key}`}
                    className="m-0 max-w-[60ch] text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500"
                  >
                    {t(NOTE_KEYS[step.noteCode])}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
