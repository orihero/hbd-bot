/**
 * What the Support group dialog needs to turn a `bot_chats` row into words: four label tables,
 * two tone tables, and this namespace's own refusals.
 *
 * A leaf module beside `ticketFormat.ts` rather than more exports inside it. The two files look
 * alike and their subjects are not: `ticketFormat.ts` is about a customer's complaint and is
 * imported by two screens that must agree on the grammar of a move, and everything here is about
 * a ROOM. The concrete cost of merging them is {@link groupNoteFor} — the ticket copy for a 409
 * says "this ticket moved first", for a 404 "no ticket is held under that id" and for a 503 "the
 * card in the Telegram group", and every one of those sentences is wrong on this surface. One
 * `noteFor` with a subject parameter would have meant a table of sentences selected by an enum,
 * which is the shape that eventually renders a ticket's words over a chat id.
 *
 * Every table below is a `Record` over a wire enum rather than a lookup with a fallback, so a
 * fourth `BotChatType` or a seventh `BotChatStatus` is a COMPILE error here instead of a blank
 * chip on a screen somebody is choosing a support inbox from. That matters more than usual for
 * {@link BOT_STATUS_LABEL_KEY}: `BotChatStatus` is explicitly NOT a closed set — Telegram owns
 * the vocabulary and `unknown` exists because it can move — so the day a seventh status is added
 * server-side, this file is the thing that notices.
 */

import type {
  BotChatSource,
  BotChatStatus,
  BotChatType,
  SupportGroupVerification,
  SupportGroupView,
} from "@/api/support";
import { CLIENT_ERROR_CODES } from "@/api/client";
import type { BadgeTone } from "@/components/Badge";
import type { NoteCopy, Translate } from "@/features/support/ticketFormat";
import type { AdminQueryError } from "@/lib/adminQuery";
import type { TranslationPath } from "@/i18n/types";

/* -------------------------------------------------------------------------- */
/* The four vocabularies                                                       */
/* -------------------------------------------------------------------------- */

/** `BotChatType`. Three members; `private` is absent server-side and cannot appear here. */
export const CHAT_TYPE_LABEL_KEY: Readonly<Record<BotChatType, TranslationPath>> = {
  group: "support.groups.type.group",
  supergroup: "support.groups.type.supergroup",
  channel: "support.groups.type.channel",
};

/**
 * `BotChatSource` — **the distinction this screen exists to show.**
 *
 * `membership_event` is Telegram's own word that the bot is in the room, sent as a
 * `my_chat_member` update. `manual` is a number an operator typed, with an inferred chat type
 * and no evidence behind it at all. The two values exist only because Telegram has no "list my
 * groups" API, and drawing them identically presents a typo with the confidence of a fact.
 */
export const CHAT_SOURCE_LABEL_KEY: Readonly<Record<BotChatSource, TranslationPath>> = {
  membership_event: "support.groups.source.membershipEvent",
  manual: "support.groups.source.manual",
};

export const CHAT_SOURCE_HINT_KEY: Readonly<Record<BotChatSource, TranslationPath>> = {
  membership_event: "support.groups.sourceHint.membershipEvent",
  manual: "support.groups.sourceHint.manual",
};

/**
 * A source's tone. `manual` is `warning` and `membership_event` is `neutral`, which is the
 * strongest visual claim this module makes.
 *
 * Not `danger`: a pasted id is very often correct — it is the ONLY way to reach a group the bot
 * was already sitting in when this shipped, which is most of them — so marking it as an error
 * would train operators to ignore the one colour that means "nothing has checked this".
 */
export const CHAT_SOURCE_TONE: Readonly<Record<BotChatSource, BadgeTone>> = {
  membership_event: "neutral",
  manual: "warning",
};

/**
 * `BotChatStatus`, in words. **Evidence, never permission — see {@link BOT_STATUS_TONE}.**
 */
export const BOT_STATUS_LABEL_KEY: Readonly<Record<BotChatStatus, TranslationPath>> = {
  member: "support.groups.botStatus.member",
  administrator: "support.groups.botStatus.administrator",
  restricted: "support.groups.botStatus.restricted",
  left: "support.groups.botStatus.left",
  kicked: "support.groups.botStatus.kicked",
  unknown: "support.groups.botStatus.unknown",
};

/**
 * The bot's standing, toned — and **`member` and `administrator` are deliberately `muted`, not
 * `accent`.**
 *
 * This is the one table in the file where the obvious choice is the dangerous one. A green pill
 * beside "administrator" is a screen claiming the bot can post in a room it may not be able to
 * post in: an administrator can have `can_post_messages` taken away with no membership
 * transition sent at all, a group can be deleted under us with no update at all, and a `manual`
 * row has never had a transition in the first place. The only field that answers "can the bot
 * post here" is `verifiedAt`, and {@link VERIFICATION_TONE} is the only table in this module
 * allowed to be green.
 *
 * `left` and `kicked` ARE marked, because a negative reading of this column is trustworthy in a
 * way a positive one is not: Telegram told us the bot is out, and no amount of missing evidence
 * makes that a false alarm.
 */
export const BOT_STATUS_TONE: Readonly<Record<BotChatStatus, BadgeTone>> = {
  member: "muted",
  administrator: "muted",
  restricted: "warning",
  left: "danger",
  kicked: "danger",
  unknown: "muted",
};

/**
 * The three verification states, toned. **The only green in this feature is earned here.**
 *
 * `checking` is `neutral` rather than `warning`: it is the ordinary state of a selection made
 * four seconds ago, and marking it as a problem would make the normal path look broken. It is
 * also where a deployment with no worker stays for ever, which is what
 * `support.groups.verification.checkingHint` says out loud rather than leaving to be discovered.
 */
export const VERIFICATION_TONE: Readonly<Record<SupportGroupVerification, BadgeTone>> = {
  verified: "accent",
  failed: "danger",
  checking: "neutral",
};

export const VERIFICATION_LABEL_KEY: Readonly<
  Record<SupportGroupVerification, TranslationPath>
> = {
  verified: "support.groups.verification.verified",
  failed: "support.groups.verification.failed",
  checking: "support.groups.verification.checking",
};

/* -------------------------------------------------------------------------- */
/* Reading a row                                                               */
/* -------------------------------------------------------------------------- */

/**
 * What to call a chat: its title, or its `@handle`, or its id — in that order, and never a
 * made-up word.
 *
 * A row's title is `null` until something learns it, which for a pasted id means until the
 * verification job's `getChat` has run. The id is the honest last resort and is the value an
 * operator can match against Telegram; a placeholder like "Untitled group" would be this panel
 * inventing a name for a room it knows nothing about, and four of those in a list are
 * indistinguishable from each other.
 */
export function chatDisplayName(group: SupportGroupView): string {
  if (group.title !== null && group.title.trim() !== "") return group.title;
  if (group.username !== null && group.username.trim() !== "") return `@${group.username}`;
  return String(group.chatId);
}

/**
 * The selected chat, or `null`.
 *
 * Found by LOOKING rather than taken from a field beside the list, because the flag on the row
 * is the same fact the database enforces to be true of at most one row — a separate `selected`
 * field would be a second answer assembled from a second statement. `find` and not a filter with
 * a length check: if the invariant were ever broken, the first row is also the one the server
 * ordered first, which is the same chat every other part of this screen would agree about.
 */
export function selectedGroupOf(groups: readonly SupportGroupView[]): SupportGroupView | null {
  return groups.find((group) => group.isSupportGroup) ?? null;
}

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

/**
 * A failed read or write on this surface, as something an operator can act on.
 *
 * Branching is on the CODE, not the status, and the two entries worth arguing are the two this
 * namespace does differently from every other screen in the console:
 *
 * **503 is `stale`, not `error`, and it offers no retry.** Everywhere else a 503 means the whole
 * action rolled back for want of a worker. Here it does not: the handler commits the selection
 * and THEN enqueues — the other order was a critical defect in the ticket feature — so a 503
 * means the inbox HAS moved and nothing will check it. Telling an operator "nothing was written"
 * would be the one lie this feature exists to remove, and offering a Retry would invite a second
 * selection of a group that is already selected.
 *
 * **409 offers no retry either**, for the ordinary reason: two operators pressed Select in the
 * same instant, the partial unique index refused the second, and the same bytes lose the same
 * race. The directory is re-read instead.
 *
 * A 403 is the role lacking `support.group.write` and never a step-up — that cell is a plain `W`
 * — so there is nothing to answer and each press would write another `permission.denied` row
 * against somebody who did nothing wrong.
 */
export function groupNoteFor(
  error: AdminQueryError,
  isStale: boolean,
  t: Translate,
): NoteCopy {
  const subject = t("support.groups.subject");

  if (error.code === "FORBIDDEN" || error.code === "STEP_UP_REQUIRED") {
    return {
      tone: "denied",
      title: t("errors.query.forbiddenTitle", { subject }),
      message: t("support.groups.notes.forbiddenMessage"),
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
      message: t("support.groups.notes.sessionEndedMessage", { message: error.message }),
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

  if (error.status === 409) {
    return {
      tone: "stale",
      title: t("support.groups.notes.conflictTitle"),
      message: t("support.groups.notes.conflictMessage"),
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("support.groups.notes.refusedTitle"),
      message: t("support.groups.notes.refusedMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.status === 503) {
    return {
      tone: "stale",
      title: t("support.groups.notes.workerTitle"),
      message: t("support.groups.notes.workerMessage"),
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
