/**
 * What the two Broadcasts screens agree on: the vocabularies, the numbers and the refusals.
 *
 * Three of these tables are `Record`s over a wire enum rather than lookups with a fallback, so
 * a ninth `BroadcastState` or an eighth `BroadcastRecipientState` is a COMPILE error here
 * instead of a blank badge on a screen somebody is watching a send from.
 *
 * The lifecycle predicates are the server's own guards, restated once:
 *
 *   send    only from `ready`   — `mark_scheduled` (db/broadcasts.py) is `WHERE state = READY`
 *   pause   only from `sending`
 *   resume  only from `paused`
 *   cancel  from every non-terminal state, `expanding` included
 *
 * They decide what is DRAWN, never what is allowed: every one of those routes takes a
 * conditional `UPDATE` and answers 409 with the state it actually found, because the worker
 * moves the campaign in another process while this screen is being read. A button hidden by
 * these predicates is an affordance withheld; the refusal is still the server's.
 */

import type {
  BroadcastKind,
  BroadcastRecipientState,
  BroadcastState,
  BroadcastView,
} from "@/api/broadcasts";
import { CLIENT_ERROR_CODES } from "@/api/client";
import type { BadgeTone } from "@/components/Badge";
import type { NoteTone } from "@/components/ErrorNote";
import type { TranslationPath } from "@/i18n/types";
import type { AdminQueryError } from "@/lib/adminQuery";

/** Every sentence on these screens, bound to the operator's chosen language. */
export type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

/* -------------------------------------------------------------------------- */
/* Vocabularies                                                                */
/* -------------------------------------------------------------------------- */

export const BROADCAST_STATE_LABEL_KEY: Readonly<Record<BroadcastState, TranslationPath>> = {
  draft: "broadcasts.state.draft",
  expanding: "broadcasts.state.expanding",
  ready: "broadcasts.state.ready",
  sending: "broadcasts.state.sending",
  paused: "broadcasts.state.paused",
  completed: "broadcasts.state.completed",
  cancelled: "broadcasts.state.cancelled",
  failed: "broadcasts.state.failed",
};

/** The long form, on the badge's `title`. What the state means for the MESSAGES. */
export const BROADCAST_STATE_HINT_KEY: Readonly<Record<BroadcastState, TranslationPath>> = {
  draft: "broadcasts.stateHint.draft",
  expanding: "broadcasts.stateHint.expanding",
  ready: "broadcasts.stateHint.ready",
  sending: "broadcasts.stateHint.sending",
  paused: "broadcasts.stateHint.paused",
  completed: "broadcasts.stateHint.completed",
  cancelled: "broadcasts.stateHint.cancelled",
  failed: "broadcasts.stateHint.failed",
};

/**
 * Colour is the second thing a state says; the word inside the badge is the first.
 *
 * `failed` is the only alarm, because it is the only one that grades the RUN as broken.
 * `cancelled` is muted rather than red — a deliberate stop is not an incident — and `paused`
 * is the warning tone because it is the one non-terminal state nothing will leave on its own.
 */
export const BROADCAST_STATE_TONE: Readonly<Record<BroadcastState, BadgeTone>> = {
  draft: "muted",
  expanding: "neutral",
  ready: "neutral",
  sending: "accent",
  paused: "warning",
  completed: "accent",
  cancelled: "muted",
  failed: "danger",
};

export const BROADCAST_KIND_LABEL_KEY: Readonly<Record<BroadcastKind, TranslationPath>> = {
  service: "broadcasts.kind.service",
  marketing: "broadcasts.kind.marketing",
};

export const BROADCAST_KIND_HINT_KEY: Readonly<Record<BroadcastKind, TranslationPath>> = {
  service: "broadcasts.kindHint.service",
  marketing: "broadcasts.kindHint.marketing",
};

export const RECIPIENT_STATE_LABEL_KEY: Readonly<
  Record<BroadcastRecipientState, TranslationPath>
> = {
  pending: "broadcasts.recipientState.pending",
  sending: "broadcasts.recipientState.sending",
  sent: "broadcasts.recipientState.sent",
  failed: "broadcasts.recipientState.failed",
  skipped_blocked: "broadcasts.recipientState.skippedBlocked",
  undeliverable: "broadcasts.recipientState.undeliverable",
  unknown: "broadcasts.recipientState.unknown",
};

/**
 * `unknown` is NOT drawn as a failure.
 *
 * The row may well have reached the customer — a killed job left it claimed and it is never
 * retried — so painting it in the alarm colour beside `failed` would state, in the one channel
 * that needs no reading, that a message did not arrive. It gets the warning tone it shares with
 * the two skips: something to look at, not something that went wrong.
 */
export const RECIPIENT_STATE_TONE: Readonly<Record<BroadcastRecipientState, BadgeTone>> = {
  pending: "muted",
  sending: "neutral",
  sent: "accent",
  failed: "danger",
  skipped_blocked: "muted",
  undeliverable: "warning",
  unknown: "warning",
};

/* -------------------------------------------------------------------------- */
/* What the campaign's state permits                                           */
/* -------------------------------------------------------------------------- */

/** Only `ready`: a campaign whose ledger is half-written cannot be authorised. */
export function canSendCampaign(broadcast: BroadcastView): boolean {
  return broadcast.state === "ready";
}

export function canPauseCampaign(broadcast: BroadcastView): boolean {
  return broadcast.state === "sending";
}

export function canResumeCampaign(broadcast: BroadcastView): boolean {
  return broadcast.state === "paused";
}

/** Every non-terminal state, `expanding` included — and `isTerminal` is the SERVER's set. */
export function canCancelCampaign(broadcast: BroadcastView): boolean {
  return !broadcast.isTerminal;
}

/* -------------------------------------------------------------------------- */
/* Numbers and instants                                                        */
/* -------------------------------------------------------------------------- */

const NUMBER_FORMAT = new Intl.NumberFormat();
const RELATIVE_FORMAT = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function formatCount(value: number): string {
  return NUMBER_FORMAT.format(value);
}

/**
 * A bounded count, said honestly.
 *
 * `isTotalExact: false` is the count cap talking and `null` is the server declining to say;
 * neither is a promise, so both read as "at least".
 */
export function formatTotal(total: number, isTotalExact: boolean | null, t: Translate): string {
  return isTotalExact === true
    ? formatCount(total)
    : t("broadcasts.atLeast", { count: formatCount(total) });
}

const MINUTE_S = 60;
const HOUR_S = 60 * MINUTE_S;
const DAY_S = 24 * HOUR_S;
const MONTH_S = 30 * DAY_S;
const YEAR_S = 365 * DAY_S;

/** "3 minutes ago", and "in 2 days" for a scheduled instant. The exact one rides in a `title`. */
export function formatRelative(iso: string, t: Translate): string | null {
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  const elapsedS = Math.round((at - Date.now()) / 1000);
  const magnitude = Math.abs(elapsedS);
  if (magnitude < MINUTE_S) return t("common.justNow");
  if (magnitude < HOUR_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / MINUTE_S), "minute");
  if (magnitude < DAY_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / HOUR_S), "hour");
  if (magnitude < MONTH_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / DAY_S), "day");
  if (magnitude < YEAR_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / MONTH_S), "month");
  return RELATIVE_FORMAT.format(Math.round(elapsedS / YEAR_S), "year");
}

export function formatAbsolute(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString();
}

/**
 * `YYYY-MM-DDTHH:mm` for a `datetime-local` input → an RFC 3339 instant in the operator's zone.
 *
 * `null` for anything that is not a complete instant. A half-typed value must drop out of the
 * request rather than be sent as a string the server will 422 — a schedule refused on a
 * parameter nobody typed is a refusal nobody can act on.
 */
export function localInstantToIso(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/u.test(value)) return null;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString();
}

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

export interface NoteCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly canRetry: boolean;
}

/**
 * A failed read, as something an operator can act on — the `UsersScreen` rule, restated for
 * this namespace's own subjects and its own 404.
 *
 * Branching is on the CODE, not the status. None of `FORBIDDEN`, `ORIGIN_REJECTED`,
 * `CSRF_REJECTED`, `SCHEMA_DRIFT`, 404 or 422 is fixed by asking again, so none of them offers
 * a Retry: on a 403 each press writes a `permission.denied` audit row against somebody who did
 * nothing wrong, and a button that always fails is worse than no button.
 */
export function noteFor(
  error: AdminQueryError,
  isStale: boolean,
  t: Translate,
  subject: string,
): NoteCopy {
  if (error.code === "FORBIDDEN") {
    return {
      tone: "denied",
      title: t("errors.query.forbiddenTitle", { subject }),
      message: t("broadcasts.notes.forbiddenMessage"),
      canRetry: false,
    };
  }

  if (error.code === "ORIGIN_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.originTitle"),
      message: t("errors.query.originMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.code === "CSRF_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.sessionEndedTitle"),
      message: t("broadcasts.notes.sessionEndedMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.code === CLIENT_ERROR_CODES.schemaDrift) {
    const paths = (error.issues ?? []).map((issue) => issue.path).join(", ");
    return {
      tone: "error",
      title: t("errors.query.driftTitle", { subject }),
      message:
        paths === ""
          ? error.message
          : t("errors.query.driftMessage", { message: error.message, paths }),
      canRetry: false,
    };
  }

  if (error.status === 404) {
    return {
      tone: "error",
      title: t("errors.query.notFoundTitle", { subject }),
      message: t("broadcasts.notes.notFoundMessage"),
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("errors.query.refusedFiltersTitle", { subject }),
      message: t("broadcasts.notes.refusedFiltersMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.status === 429) {
    const wait =
      error.retryAfterS === null
        ? ""
        : t("errors.query.rateLimitedWait", { seconds: error.retryAfterS });
    return {
      tone: "error",
      title: t("errors.query.rateLimitedTitle", { subject }),
      message: `${error.message}${wait}`,
      canRetry: false,
    };
  }

  if (isStale) {
    return {
      tone: "stale",
      title: t("errors.query.staleTitle", { subject }),
      message: t("errors.query.staleMessage", { message: error.message }),
      canRetry: true,
    };
  }

  if (error.status === 0) {
    return {
      tone: "offline",
      title: t("errors.query.offlineTitle", { subject }),
      message: error.message,
      canRetry: true,
    };
  }

  return {
    tone: "error",
    title: t("errors.query.failedTitle", { subject }),
    message: error.message,
    canRetry: true,
  };
}
