/**
 * The pieces the four user-detail panels share.
 *
 * A panel here is the kit's card — white, radius 26, a 1px --stroke edge, a 16/600 title over
 * a full-width rule (`.openpencil-export/project-card.jsx`, `Frame 2147225734` and its
 * `Line 183`). Tables are NOT wrapped in one: `<DataTable>` already draws the kit's Task List
 * card at radius 15, and a card inside a card is two edges saying the same thing.
 *
 * Two behaviours in here are correctness rather than layout:
 *
 * 1. **`<PurgedValue>` refuses to render an absence as a blank.** A retention clock that has
 *    run is a fact the system recorded on purpose; a blank cell reads as a bug and sends
 *    support hunting for a value that was deliberately destroyed.
 * 2. **`describeFailure` decides whether Retry is even offered.** Asking again cannot change a
 *    403, a 422 or a contract mismatch, and on the privileged routes each retry writes another
 *    `permission.denied` row against an operator who did nothing wrong. The rate-limit codes
 *    are withheld for the opposite reason: they DO become retryable, later, and the message
 *    says when.
 */

import { useState, type JSX, type ReactNode } from "react";

import type { PageMeta } from "@/api/pagination";
import { stepUpTargetOf } from "@/api/reveal";
import { ErrorNote, type NoteTone } from "@/components/ErrorNote";
import { ROLE_REFUSAL_NOTE, revealFailureAdvice } from "@/features/reveal";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import type { AdminQueryError } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";

/** Every sentence in this kit, bound to the operator's chosen language. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

import { formatDay } from "./detailFormat";

/* -------------------------------------------------------------------------- */
/* Type                                                                        */
/* -------------------------------------------------------------------------- */

/** The kit's card title: 16/600, -0.32, --ink-900. Also this screen's section headings. */
export const PANEL_TITLE_CLASS =
  "text-[16px] font-semibold leading-[21.856px] tracking-[-0.32px] text-ink-900";

/** The kit's column-header type, used for a fact's label and a group's caption. */
export const FACT_LABEL_CLASS =
  "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-400";

/** A fact's value: the kit's 14/500 control label, one step up from a table cell. */
export const FACT_VALUE_CLASS =
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-ink-900";

/** Prose inside a panel — a note that explains two numbers that look like a contradiction. */
export const PANEL_NOTE_CLASS = "text-[12px] font-normal leading-[16.392px] text-ink-400";

/** An identifier printed for comparison, not for reading. */
export const MONO_CLASS = "font-mono text-[12px] leading-[16px] tracking-[-0.2px] break-all";

/* -------------------------------------------------------------------------- */
/* Panel                                                                       */
/* -------------------------------------------------------------------------- */

export interface PanelProps {
  readonly title?: string | undefined;
  /** One line under the title. What the panel is scoped to, or what it cannot show. */
  readonly caption?: ReactNode;
  /** Right-hand slot of the title row. */
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  readonly ariaLabel?: string | undefined;
  readonly className?: string | undefined;
}

export function Panel({
  title,
  caption,
  actions,
  children,
  ariaLabel,
  className,
}: PanelProps): JSX.Element {
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "flex flex-col gap-4 rounded-panel border border-stroke bg-card p-4",
        className,
      )}
    >
      {title === undefined ? null : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className={cn("m-0", PANEL_TITLE_CLASS)}>{title}</h3>
            {actions === undefined ? null : <div className="flex items-center gap-2">{actions}</div>}
          </div>
          {/* The kit's `Line 183`: the title is separated by a rule, not by air. */}
          <hr className="m-0 h-px border-0 bg-stroke" />
        </div>
      )}
      {caption === undefined ? null : <p className={cn("m-0", PANEL_NOTE_CLASS)}>{caption}</p>}
      {children}
    </section>
  );
}

/** A page-level heading over a card. `<h2>`, because the toolbar's title is the `<h1>`. */
export function SectionHeading({ children }: { readonly children: ReactNode }): JSX.Element {
  return <h2 className={cn("m-0", PANEL_TITLE_CLASS)}>{children}</h2>;
}

/* -------------------------------------------------------------------------- */
/* Facts                                                                       */
/* -------------------------------------------------------------------------- */

/** A `<dl>` of label/value pairs that reflows rather than scrolling. */
export function FactGrid({ children }: { readonly children: ReactNode }): JSX.Element {
  return (
    <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 xl:grid-cols-4">
      {children}
    </dl>
  );
}

export interface FactProps {
  readonly label: string;
  /**
   * The long form, on the label's `title`. For a number whose name is shorter than what it
   * means — "projected" is three numbers' worth of explanation.
   */
  readonly hint?: string | undefined;
  readonly children: ReactNode;
}

export function Fact({ label, hint, children }: FactProps): JSX.Element {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className={FACT_LABEL_CLASS} title={hint}>
        {label}
      </dt>
      <dd className={cn("m-0 min-w-0", FACT_VALUE_CLASS)}>{children}</dd>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Purged                                                                      */
/* -------------------------------------------------------------------------- */

export interface PurgedValueProps {
  /** The retention stamp. Non-null means the value is gone, whatever the masked twin says. */
  readonly purgedAt: string | null;
  /**
   * The row's own boolean, where it carries one. `true` with a `null` stamp is a real state —
   * purged by a writer that recorded no clock — and it must not read as "still here".
   */
  readonly isPurged?: boolean | undefined;
  /** Which clock ran, for the tooltip. "identity retention", "text retention". */
  readonly clock?: string | undefined;
  readonly children: ReactNode;
}

/**
 * Purged data is not missing data.
 *
 * A non-null stamp renders "purged {date}" and NOTHING else — no value, and no affordance to
 * go and get one, because there is nothing behind it and a reveal that cannot succeed is worse
 * than no button at all.
 */
export function PurgedValue({
  purgedAt,
  isPurged = false,
  clock,
  children,
}: PurgedValueProps): JSX.Element {
  if (purgedAt !== null) {
    return (
      <span
        data-testid="purged-value"
        data-purged-at={purgedAt}
        title={clock === undefined ? undefined : `${clock} clock`}
        className="whitespace-nowrap text-[12px] leading-4 text-ink-400"
      >
        {`🔒 purged ${formatDay(purgedAt)}`}
      </span>
    );
  }
  if (isPurged) {
    return (
      <span
        data-testid="purged-value"
        data-purged-at=""
        title={clock === undefined ? undefined : `${clock} clock`}
        className="whitespace-nowrap text-[12px] leading-4 text-ink-400"
      >
        🔒 purged — no date recorded
      </span>
    );
  }
  return <>{children}</>;
}

/* -------------------------------------------------------------------------- */
/* Keyset paging                                                               */
/* -------------------------------------------------------------------------- */

export interface CursorStack {
  /** What to ask for. `null` is page one. */
  readonly cursor: string | null;
  /** 0-based, for composing "51–100" — a keyset page has no number of its own. */
  readonly pageIndex: number;
  readonly hasPrev: boolean;
  readonly toNext: (nextCursor: string) => void;
  readonly toPrev: () => void;
  /** Back to page one. What a write that inserts at the top must do. */
  readonly toFirst: () => void;
}

/**
 * The trail of cursors that led to the page on screen.
 *
 * Keyset paging has no page numbers and no "previous" cursor — the server mints only the NEXT
 * one — so going back is only possible if the client remembers where it has been. The trail
 * always starts at `null` (page one), which is why `pageIndex` is `length - 1` and why
 * `toFirst` is a truncation rather than a fetch.
 *
 * This is component state and not the URL, deliberately, and the argument is the same one
 * `admin-ui` makes for its ledger: two independent tables on one screen would need two opaque
 * keyset keys in a link somebody pastes into a ticket, and a trail cannot survive a reload
 * anyway — so a "Previous" restored from a link would be either missing or wrong. The
 * addressable state of this screen is the Telegram id in its path.
 */
export function useCursorStack(): CursorStack {
  const [trail, setTrail] = useState<readonly (string | null)[]>([null]);

  const cursor = trail[trail.length - 1] ?? null;

  return {
    cursor,
    pageIndex: trail.length - 1,
    hasPrev: trail.length > 1,
    toNext: (nextCursor: string) => {
      setTrail((current) => [...current, nextCursor]);
    },
    toPrev: () => {
      setTrail((current) => (current.length > 1 ? current.slice(0, -1) : current));
    },
    toFirst: () => {
      setTrail([null]);
    },
  };
}

/**
 * "51–100 of 4,312" — composed by the screen, because the pager cannot know the total.
 *
 * `isTotalExact: false` is the server's count cap talking, so the number is a floor and is
 * printed with a `+`. A capped total drawn as an exact one is a number an operator will quote.
 */
export function rangeLabelOf(
  pageIndex: number,
  limit: number,
  count: number,
  meta: PageMeta | undefined,
): string {
  if (count === 0) return "No rows on this page";
  const start = pageIndex * limit + 1;
  const end = start + count - 1;
  const range = `${INTEGER.format(start)}–${INTEGER.format(end)}`;
  if (meta === undefined || meta.total === null) return range;
  const total = `${INTEGER.format(meta.total)}${meta.isTotalExact === false ? "+" : ""}`;
  return `${range} of ${total}`;
}

const INTEGER = new Intl.NumberFormat();

/* -------------------------------------------------------------------------- */
/* Failures                                                                    */
/* -------------------------------------------------------------------------- */

export interface FailureCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly hint: string;
  /** Whether pressing Retry could change the answer. */
  readonly retryable: boolean;
  /** `true` for a cancelled request, which must render as nothing at all. */
  readonly isSilent: boolean;
}

/**
 * One failure, in the words the operator needs, keyed on `code` and never on the status.
 *
 * The codes exist precisely so an SPA does not have to read "403" three ways: a role refusal,
 * a step-up refusal and a dead CSRF cookie are the same status and three different remedies.
 */
export function describeFailure(error: AdminQueryError, noun: string, t: Translate): FailureCopy {
  const hint =
    error.correlationId === null ? error.endpoint : `${error.endpoint} · ${error.correlationId}`;
  const base = { hint, isSilent: false } as const;
  const advice = revealFailureAdvice(error.failure);

  switch (error.code) {
    case "REQUEST_ABORTED":
      // A cancelled request is not a failure anyone should read about.
      return { ...base, tone: "stale", title: "", message: "", retryable: false, isSilent: true };

    case "UNAUTHENTICATED":
    case "CSRF_REJECTED":
      return {
        ...base,
        tone: "denied",
        title: t("errors.detail.sessionEndedTitle"),
        message: t("errors.detail.sessionEndedMessage"),
        retryable: false,
      };

    case "ORIGIN_REJECTED":
      return {
        ...base,
        tone: "denied",
        title: t("errors.detail.misconfiguredTitle"),
        message: t("errors.detail.misconfiguredMessage"),
        retryable: false,
      };

    case "FORBIDDEN":
      return {
        ...base,
        tone: "denied",
        title: t("errors.detail.forbiddenTitle", { noun }),
        message: advice === null ? error.message : `${error.message} ${advice}`,
        retryable: false,
      };

    case "STEP_UP_REQUIRED":
      // Two failures share this code. With `details` it is the handler asking for a password
      // and the caller should have opened a step-up rather than reached this copy; with none
      // it is the router's own guard, which re-authenticating cannot move.
      return {
        ...base,
        tone: "denied",
        title:
          stepUpTargetOf(error.failure) === null
            ? t("errors.detail.roleCannotTitle")
            : t("errors.detail.needsReauthTitle"),
        message:
          stepUpTargetOf(error.failure) === null
            ? `${error.message} ${ROLE_REFUSAL_NOTE}`
            : error.message,
        retryable: false,
      };

    case "NOT_FOUND":
      return {
        ...base,
        tone: "denied",
        title: t("errors.detail.notFoundTitle", { noun }),
        message: error.message,
        retryable: false,
      };

    case "CONFLICT":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.conflictTitle"),
        message: t("errors.detail.conflictMessage", { message: error.message }),
        retryable: false,
      };

    case "INVALID_INPUT":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.invalidTitle"),
        message: t("errors.detail.invalidMessage", { message: error.message }),
        retryable: false,
      };

    case "REAUTH_RATE_LIMITED":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.tooManyStepUpsTitle"),
        message: t("errors.detail.tooManyStepUpsMessage", { message: error.message }),
        retryable: false,
      };

    case "LOGIN_RATE_LIMITED":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.rateLimitedTitle"),
        message: retryAfterSentence(error.message, error.retryAfterS, t),
        retryable: false,
      };

    case "REVEAL_BUDGET_EXHAUSTED":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.budgetSpentTitle"),
        message: retryAfterSentence(error.message, error.retryAfterS, t),
        retryable: false,
      };

    case "SCHEMA_DRIFT":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.driftTitle"),
        message: t("errors.detail.driftMessage", {
          message: error.message,
          fields: describeIssues(error, t),
        }),
        retryable: false,
      };

    case "NETWORK_ERROR":
      return {
        ...base,
        tone: "offline",
        title: t("errors.detail.offlineTitle", { noun }),
        message: error.message,
        retryable: true,
      };

    case "SERVICE_UNAVAILABLE":
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.dependencyTitle"),
        message: retryAfterSentence(error.message, error.retryAfterS, t),
        retryable: true,
      };

    default:
      return {
        ...base,
        tone: "error",
        title: t("errors.detail.failedTitle", { noun }),
        message: error.message,
        retryable: true,
      };
  }
}

function retryAfterSentence(message: string, retryAfterS: number | null, t: Translate): string {
  return retryAfterS === null
    ? t("errors.detail.noCountdown", { message })
    : t("errors.detail.tryAgainIn", { message, seconds: retryAfterS });
}

/** The field paths this build did not understand — the only actionable part of a drift. */
function describeIssues(error: AdminQueryError, t: Translate): string {
  const issues = error.issues;
  if (issues === null || issues.length === 0) return "";
  return t("errors.detail.driftFields", { paths: issues.map((issue) => issue.path).join(", ") });
}

export interface QueryErrorNoteProps {
  readonly error: AdminQueryError;
  /** What failed, in the operator's words: "this customer's orders". */
  readonly noun: string;
  readonly onRetry?: (() => void) | undefined;
  readonly isRetrying?: boolean | undefined;
}

/** `describeFailure`, drawn. Renders nothing for a cancelled request. */
export function QueryErrorNote({
  error,
  noun,
  onRetry,
  isRetrying = false,
}: QueryErrorNoteProps): JSX.Element | null {
  const { t } = useI18n();
  const copy = describeFailure(error, noun, t);
  if (copy.isSilent) return null;
  return (
    <ErrorNote
      tone={copy.tone}
      title={copy.title}
      message={copy.message}
      hint={copy.hint}
      onRetry={onRetry}
      isRetrying={isRetrying}
      retryable={copy.retryable}
    />
  );
}
