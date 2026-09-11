/**
 * The audit log's vocabulary, and the several kinds of absence a row can carry.
 *
 * A leaf module, imported by the screen, its filter controls and the chain panel alike. It
 * exists because those three files need the same words for the same wire members, and an
 * outcome humanised two ways is a screen whose chip and whose pill disagree about what the
 * operator filtered on.
 *
 * ## Nothing here de-slugs a wire value
 *
 * `AuditAction`'s values are dotted and abbreviated and they are **not slugs**: `order.deliver`
 * is written by `ORDER_FORCE_DELIVER`, `login.limited` by `LOGIN_RATE_LIMITED`. Prettifying
 * them would print two words the server has never heard of, into the one screen whose whole
 * purpose is that an operator can grep what they read. So actions render verbatim, roles render
 * in the wire's spelling (§12.2 heads the ADMIN row "OPERATOR"; a console using two words for
 * one role is a support call), and `chainProtection` renders exactly as `revoke+hmac` /
 * `hmac-only`, punctuation and all. What this module adds is grouping, tone and the sentences
 * that say what an absence means — never a rewrite of a value.
 *
 * ## Absence has kinds here, and they are not interchangeable
 *
 * `recordCount: null` is "not recorded", never `0` — it is the reveal budget's unit, and a null
 * read as zero understates exposure on the one screen that measures it. `reasonText: null` is
 * either "withheld from your role" or "no free text", and the two are told apart by
 * `hasReasonText` and never by the empty cell. And `hasReasonText: false` on an old row may be
 * the 90-day sweep rather than an operator who typed nothing: `reason_purged_at` exists in the
 * table and is deliberately not projected, so no copy here may claim "no reason was given".
 *
 * ## The four time helpers are duplicated, not imported
 *
 * They are byte-for-byte the ones in `features/generations/attemptFormat.ts`. Importing across
 * features is the coupling that module's own controls docstring argues against, and the shared
 * answer — one module under `src/lib/` — means editing that screen, which is not this change.
 * Duplicating four pure functions is the cheaper honesty; if a third screen wants them, promote
 * all three at once. `formatCount` is NOT duplicated: it comes from the dashboard, because one
 * console has one digit grouping.
 */

import type { AuditAction, AuditOutcome, AuditSubjectType, ChainProtection } from "@/api/audit";
import { AUDIT_ACTION_VALUES } from "@/api/audit";
import type { AdminRole } from "@/api/audit";
import type { BadgeTone } from "@/components/Badge";
import { formatCount } from "@/features/dashboard/adapt";

/* -------------------------------------------------------------------------- */
/* Absence, in its several kinds                                               */
/* -------------------------------------------------------------------------- */

/**
 * `hasReasonText: true` with `reasonText: null`.
 *
 * The exact sentence, because the wrong one is easy and wrong in a specific way: "no reason
 * given" would be a different and false claim about a row that carries one. The text is
 * withheld by ROLE — §12.2 gives `audit.read` as **M** to ADMIN and **R** to OWNER — and no
 * step-up, no button and no second request changes that, so there is no affordance beside it.
 */
export const REASON_WITHHELD_LABEL = "a reason was recorded, you may not read it";

/**
 * `hasReasonText: false`.
 *
 * "No free text on this row" and not "no reason was given": every row carries a `reasonCode`,
 * which IS the reason. See `REASON_SWEEP_CAVEAT` for the second thing this state can mean.
 */
export const NO_REASON_TEXT_LABEL = "no free text on this row";

/**
 * Why "no free text" is not the same as "nobody typed any".
 *
 * `hasReasonText` is computed from the CURRENTLY stored value, and the 90-day sweep nulls
 * `reason_text` while the row itself lives 730 days. `reason_purged_at` is not projected, so a
 * row older than ninety days reads `false` even for an OWNER and the wire carries no way to
 * tell a swept reason from one that was never there.
 */
export const REASON_SWEEP_CAVEAT =
  "Free text is swept at 90 days while the row lives 730, and this wire carries no way to " +
  "tell a swept reason from one that was never typed. The reason code beside it is not swept.";

/** `recordCount: null`, in a cell. Two words, so that the cell says which nothing it is. */
export const RECORD_COUNT_ABSENT_LABEL = "not recorded";

/** `recordCount: null`. The distinction the reveal budget is denominated in. */
export const RECORD_COUNT_ABSENT =
  "No record count was written for this action. That is not zero records — it is a number " +
  "nobody recorded, and the reveal budget counts records rather than rows.";

/** `fieldNames: null` or empty. Field NAMES only ever appear here; values never do (§12.4). */
export const NO_FIELDS_NAMED = "no field names recorded";

/** `subjectId: null`. Not every audited action is about a record. */
export const NO_SUBJECT = "no subject recorded";

/* -------------------------------------------------------------------------- */
/* The reason trichotomy                                                       */
/* -------------------------------------------------------------------------- */

/** Which of the three states the `hasReasonText` / `reasonText` pair is in. */
export type ReasonDisclosure =
  | { readonly kind: "text"; readonly text: string }
  | { readonly kind: "withheld" }
  | { readonly kind: "none" };

/**
 * The pair, resolved into the three facts it can express.
 *
 * `hasReasonText: false` with a non-null `reasonText` is impossible on this wire — `to_view`
 * derives the flag from the same value it projects — but the resolution below prefers the TEXT
 * if it ever arrives anyway: a value on the wire is a fact, and a derived flag disagreeing with
 * it is the flag being wrong.
 */
export function reasonDisclosure(entry: {
  readonly hasReasonText: boolean;
  readonly reasonText: string | null;
}): ReasonDisclosure {
  if (entry.reasonText !== null) return { kind: "text", text: entry.reasonText };
  return entry.hasReasonText ? { kind: "withheld" } : { kind: "none" };
}

/* -------------------------------------------------------------------------- */
/* Closed vocabularies                                                         */
/* -------------------------------------------------------------------------- */

/**
 * The outcome, in the wire's own three words.
 *
 * Not re-worded, and that is a decision rather than laziness. "Succeeded" reads wrong on a
 * `login.failure` row whose outcome is `ok` — the outcome is about the ACTION being carried
 * out, not about the thing it records — and "ok/denied/error" are already plain English that
 * an operator will meet again in a log line and in a filter chip. The meanings below carry the
 * distinction the words alone do not.
 */
export const AUDIT_OUTCOME_LABELS: Readonly<Record<AuditOutcome, string>> = {
  ok: "ok",
  denied: "denied",
  error: "error",
};

/** What each outcome actually says, for the pill's `title` and the filter's hint. */
export const AUDIT_OUTCOME_MEANINGS: Readonly<Record<AuditOutcome, string>> = {
  ok: "The action was permitted and carried out.",
  denied:
    "The permission matrix refused somebody. This is the row a “successes only” log would " +
    "not have, and it is the system working rather than failing.",
  error: "The action was permitted and then failed — an incident, not an access-control event.",
};

/**
 * Outcome as a pill tone.
 *
 * `denied` is `warning` and not `danger` on purpose: a refusal is the control doing its job,
 * and painting it in the alarm colour beside a genuine `error` teaches an operator to ignore
 * the alarm colour. The label carries the meaning either way — colour is not information
 * anyone is required to be able to see.
 */
export const AUDIT_OUTCOME_TONES: Readonly<Record<AuditOutcome, BadgeTone>> = {
  ok: "accent",
  denied: "warning",
  error: "danger",
};

/**
 * The role AT THE TIME of the action, in the wire's spelling.
 *
 * `admin` stays `admin` even though §12.2 heads that row "OPERATOR": a console that shows one
 * word where the API, the audit row and the roster show another is a support call. `system` is
 * not here because it is not a role — a system row carries a real `actorRole` and a null
 * `actorId`, and says `system:<what>` in the username.
 */
export const ADMIN_ROLE_LABELS: Readonly<Record<AdminRole, string>> = {
  owner: "owner",
  admin: "admin",
  support: "support",
  viewer: "viewer",
};

/**
 * `SUBJECT_TYPES`, in words. Only the underscored one is respelled, because `wizard_draft` is
 * an identifier and "wizard draft" is the same value with the same meaning.
 */
export const SUBJECT_TYPE_LABELS: Readonly<Record<AuditSubjectType, string>> = {
  order: "order",
  user: "user",
  asset: "asset",
  chat: "chat",
  config: "config",
  admin: "admin",
  session: "session",
  wizard_draft: "wizard draft",
  system: "system",
  payment: "payment",
};

/**
 * The label for a subject type that arrived from the wire.
 *
 * The column is `str` at both ends with no enum check, so a value outside `SUBJECT_TYPES`
 * renders as itself rather than as a blank cell. Nothing here invents a word for it.
 */
export function subjectTypeLabel(subjectType: string): string {
  const known = Object.hasOwn(SUBJECT_TYPE_LABELS, subjectType)
    ? SUBJECT_TYPE_LABELS[subjectType as AuditSubjectType]
    : undefined;
  return known ?? subjectType;
}

/* -------------------------------------------------------------------------- */
/* Actions, grouped so that thirty-four of them can be chosen from             */
/* -------------------------------------------------------------------------- */

/**
 * The families a picker groups the actions into.
 *
 * Thirty-four toggles in one undifferentiated wrap is a control nobody scans; grouped by the
 * question an operator is actually asking — "who read personal data", "what happened to
 * orders", "who touched an operator account" — they are findable. The families are ours, not
 * the server's: there is no grouping in `AuditAction` and this module invents no wire value.
 */
export type AuditActionFamily =
  | "access"
  | "disclosure"
  | "orders"
  | "customers"
  | "moderation"
  | "config"
  | "retention"
  | "exports"
  | "accounts";

/** Section headings for the picker, in the order it reads them. */
export const AUDIT_ACTION_FAMILY_LABELS: Readonly<Record<AuditActionFamily, string>> = {
  access: "Sessions and access",
  disclosure: "Disclosure",
  orders: "Orders",
  customers: "Customers",
  moderation: "Moderation",
  config: "Configuration",
  retention: "Retention",
  exports: "Exports",
  accounts: "Operator accounts",
};

/**
 * Every member of `AuditAction`, placed.
 *
 * Typed as a total record on purpose: an action added to `AUDIT_ACTION_VALUES` and not placed
 * here is a compile error rather than an action that quietly stops being offered as a filter —
 * which is the failure mode that matters, because an audit filter nobody can select is an
 * investigation that comes back empty and reads as "it never happened".
 *
 * Two placements are worth arguing. `permission.denied` is under `access` rather than under the
 * surface that was refused, because a refusal is a fact about a credential and it is read as a
 * sequence beside the logins around it. `credit.grant` is under `customers` because it issues
 * value into an append-only ledger against a person, which is the thing somebody reviews at
 * end of shift.
 */
export const AUDIT_ACTION_FAMILY: Readonly<Record<AuditAction, AuditActionFamily>> = {
  "login.success": "access",
  "login.failure": "access",
  "login.limited": "access",
  logout: "access",
  "step_up.success": "access",
  "step_up.failure": "access",
  "session.revoked": "access",
  "permission.denied": "access",

  "reveal.personal": "disclosure",
  "asset.stream": "disclosure",

  "order.retry": "orders",
  "order.reenqueue": "orders",
  "order.deliver": "orders",
  "order.cancel": "orders",

  "user.block": "customers",
  "user.unblock": "customers",
  "user.purge.req": "customers",
  "user.purge.done": "customers",
  "user.purge.fail": "customers",
  "credit.grant": "customers",
  /* Re-sending a payment confirmation is a message to ONE person about their own purchase,
     which is the same shift-review question `credit.grant` is under: what did we do to a
     customer today. It is not a `config` action — nothing about the deployment changed. */
  "payment.notify": "customers",

  "moderation.approve": "moderation",
  "moderation.reject": "moderation",

  "config.validate": "config",
  "config.commit": "config",
  "config.rollback": "config",
  /* The Payme pause switch is configuration — it is a Redis key that changes what the bot
     does, in the same class as a committed config version — so it groups with `config.*`
     rather than earning a family of its own. A tenth family would need `FAMILY_ORDER`, a
     label and three locale keys for a group of two. */
  "rail.paused": "config",
  "rail.resumed": "config",

  "retention.extended": "retention",
  "retention.run": "retention",

  "export.aggregate": "exports",
  "export.order": "exports",
  "export.audit": "exports",

  "admin.create": "accounts",
  "admin.role": "accounts",
  "admin.deactivate": "accounts",
  "admin.password": "accounts",
};

/** The order the picker lists the families in: what an investigation reaches for first. */
const FAMILY_ORDER: readonly AuditActionFamily[] = [
  "disclosure",
  "access",
  "customers",
  "orders",
  "moderation",
  "config",
  "retention",
  "exports",
  "accounts",
];

export interface AuditActionGroup {
  readonly family: AuditActionFamily;
  readonly label: string;
  /** In `AuditAction`'s declaration order, which is the order the taxonomy reads in. */
  readonly values: readonly AuditAction[];
}

/**
 * The picker's groups, derived from the placement above rather than written a second time —
 * two lists of thirty-four values drift, and the drift is a filter that silently disappears.
 */
export const AUDIT_ACTION_GROUPS: readonly AuditActionGroup[] = FAMILY_ORDER.map((family) => ({
  family,
  label: AUDIT_ACTION_FAMILY_LABELS[family],
  values: AUDIT_ACTION_VALUES.filter((action) => AUDIT_ACTION_FAMILY[action] === family),
}));

/* -------------------------------------------------------------------------- */
/* Identifiers                                                                 */
/* -------------------------------------------------------------------------- */

/** How much of an opaque id fits in a cell before it starts pushing the columns around. */
const ID_HEAD_CHARS = 12;

export interface ShortenedId {
  /** What the cell shows. */
  readonly short: string;
  /** The whole value, for `title` — nothing is truncated without the full value beside it. */
  readonly full: string;
  /** Whether anything was actually dropped, so a `title` is only promised when it adds one. */
  readonly isShortened: boolean;
}

/** A UUID, a Telegram id or a config version, shortened head-first — ids are compared by prefix. */
export function shortenId(value: string): ShortenedId {
  if (value.length <= ID_HEAD_CHARS) return { short: value, full: value, isShortened: false };
  return { short: `${value.slice(0, ID_HEAD_CHARS)}…`, full: value, isShortened: true };
}

/** How much of the 64-hex seal is shown. See `SEAL_EXPLANATION` for why it is not all of it. */
const SEAL_HEAD_CHARS = 12;

/**
 * Why the tamper-evidence seal is not printed in full.
 *
 * `chainHmac` is 64 hex characters and it is a value to COMPARE, never one to read: without the
 * key it cannot be recomputed, and the only thing an operator does with it is match a row
 * against the anchor line in the server log. Sixty-four monospace characters in a cell push
 * actor, action and subject — the columns somebody is actually scanning — off the right edge,
 * which is how a table stops answering the question it was opened for. Twelve characters is
 * more than enough to match a row against an anchor by eye; the whole value is in the cell's
 * `title`, and the row's `id` is what a link or a ticket should carry anyway.
 */
export const SEAL_EXPLANATION =
  "The chain HMAC for this row, shortened. It is a value to compare against the anchor line " +
  "in the server log, not one to read; the full 64 characters are in this cell's tooltip.";

/** The seal, shortened for a cell. Same shape as `shortenId`, different reason. */
export function shortenSeal(chainHmac: string): ShortenedId {
  if (chainHmac.length <= SEAL_HEAD_CHARS) {
    return { short: chainHmac, full: chainHmac, isShortened: false };
  }
  return { short: `${chainHmac.slice(0, SEAL_HEAD_CHARS)}…`, full: chainHmac, isShortened: true };
}

/** `seq 1,240` — grouped, because a six-figure sequence is unreadable ungrouped. */
export function formatSeq(seq: number): string {
  return `seq ${formatCount(seq)}`;
}

/* -------------------------------------------------------------------------- */
/* The chain verdict                                                           */
/* -------------------------------------------------------------------------- */

export interface ChainVerdict {
  /** The badge's word. Readable on its own — the tone is not the message. */
  readonly label: string;
  readonly tone: BadgeTone;
  /** What it means for the log, in one operator sentence. */
  readonly sentence: string;
}

/**
 * `ok: true` with `isComplete: false` is a THIRD state, and collapsing it into either
 * neighbour is the mistake this function exists to prevent.
 *
 * The walk stopped at its 50 000-row ceiling, so a clean answer over the first 50 000 rows is
 * not a clean answer over the log — and the tail check is deliberately skipped in that case, so
 * a truncated pass cannot claim tail integrity either. It is a caveat, not an alarm: `warning`,
 * never `danger`, and never the green all-clear the flag exists to withhold.
 */
export function chainVerdict(ok: boolean, isComplete: boolean): ChainVerdict {
  if (!ok) {
    return {
      label: "Chain broken",
      tone: "danger",
      sentence:
        "The log does not verify. This is an integrity alarm and not a warning: the chain is " +
        "keyed with an HMAC whose key lives only in the admin process, so a valid link cannot " +
        "be forged by anyone who can write the table. The server has already logged this at " +
        "ERROR with your username.",
    };
  }
  if (!isComplete) {
    return {
      label: "Holds over the rows checked",
      tone: "warning",
      sentence:
        "Every link the walk covered holds, but the walk stopped at its 50,000-row ceiling " +
        "before the end of the table — and the tail check is skipped when it does. This is " +
        "not a clean answer about the whole log, and it is not a finding either.",
    };
  }
  return {
    label: "Chain holds",
    tone: "accent",
    sentence:
      "Every link verifies and the tail matches the newest HEAD anchor. The log has not been " +
      "edited since it was written.",
  };
}

/** What a break at a sequence number does and does not condemn. */
export const BREAK_EXPLANATION =
  "Rows below the first break are still trustworthy; everything at and after it is not. A " +
  "break is one of three things and the verifier detects all three: a mutated row, a prefix " +
  "excision whose survivor no anchor accounts for, or a tail excision — in which case the " +
  "sequence named is the tail rather than a row in the middle.";

/**
 * The two protection modes, in prose. `hmac-only` is NOT a failure and must not read as one.
 *
 * It is the honest answer on any deployment where the database has not confirmed the revoke —
 * including a Postgres deployment where it was configured and did not land. A control that is
 * not deployed is reported as not deployed; the HMAC chain is still standing, and it still
 * means tampering would be detected.
 */
export const CHAIN_PROTECTION_NOTES: Readonly<Record<ChainProtection, string>> = {
  "revoke+hmac":
    "The database confirms the application role cannot UPDATE, DELETE or TRUNCATE this " +
    "table, and every row is HMAC-chained on top of that. Tampering is prevented as well as " +
    "detected.",
  "hmac-only":
    "Every row is HMAC-chained, so tampering would be detected — but the database has not " +
    "confirmed the revoke, so it would not be prevented. On Postgres that usually means " +
    "BAYRAM_ADMIN_AUDIT_DSN is empty and migration 0007's REVOKE never ran.",
};

/** For a protection mode this build has never heard of. It is printed; it is not explained. */
export const CHAIN_PROTECTION_UNKNOWN_NOTE =
  "This build has no note for that protection mode. The value above is what the server " +
  "reported, verbatim.";

/** The note for whatever the server said, without pretending to know an unknown value. */
export function chainProtectionNote(chainProtection: string): string {
  const known = Object.hasOwn(CHAIN_PROTECTION_NOTES, chainProtection)
    ? CHAIN_PROTECTION_NOTES[chainProtection as ChainProtection]
    : undefined;
  return known ?? CHAIN_PROTECTION_UNKNOWN_NOTE;
}

/** Legitimate, expected gaps. Nobody should investigate a hole the system dug itself. */
export const TRUNCATION_EXPLANATION =
  "Each of these is a sequence below which the 730-day sweep deleted rows on schedule and " +
  "wrote a TRUNCATION anchor naming the surviving row. A gap there is not a break — it is the " +
  "reason a log with retired history still verifies.";

/* -------------------------------------------------------------------------- */
/* Time                                                                        */
/* -------------------------------------------------------------------------- */

function pad2(value: number): string {
  return value < 10 ? `0${String(value)}` : String(value);
}

export interface SplitTimestamp {
  /** `2026-09-08`. */
  readonly date: string;
  /** `14:32:05`. Seconds included: `seq` is the tiebreak precisely because `at` collides. */
  readonly time: string;
  /** The whole thing, for a `title` and for a chip. */
  readonly full: string;
  /** True when the string could not be parsed — the raw value is in `full`. */
  readonly isUnparsed: boolean;
}

/**
 * An RFC 3339 instant in the READER'S timezone, split for the kit's two-line cell.
 *
 * Local rather than UTC because the operator is correlating this against a support
 * conversation and a wall clock; the column is captioned with the zone so the choice is stated
 * rather than assumed. An unparseable value is returned verbatim — inventing an epoch for a
 * string the server sent would put a wrong date on screen with no way to tell.
 */
export function splitTimestamp(iso: string): SplitTimestamp {
  const at = new Date(iso);
  const ms = at.getTime();
  if (Number.isNaN(ms)) return { date: iso, time: "", full: iso, isUnparsed: true };

  const date = `${String(at.getFullYear())}-${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}`;
  const time = `${pad2(at.getHours())}:${pad2(at.getMinutes())}:${pad2(at.getSeconds())}`;
  return { date, time, full: `${date} ${time}`, isUnparsed: false };
}

/** The reader's zone, named, so a timestamp column is not a guess. `UTC+5`, `UTC-3:30`. */
export function localZoneLabel(): string {
  // `getTimezoneOffset` is minutes WEST of UTC, so its sign is inverted from the label's.
  const minutesWest = new Date().getTimezoneOffset();
  const sign = minutesWest <= 0 ? "+" : "-";
  const total = Math.abs(minutesWest);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return minutes === 0
    ? `UTC${sign}${String(hours)}`
    : `UTC${sign}${String(hours)}:${pad2(minutes)}`;
}

/**
 * `<input type="datetime-local">` wants `YYYY-MM-DDTHH:mm` in LOCAL time; the API wants
 * RFC 3339 WITH an offset — a naive instant is a 422 saying so in as many words. These two are
 * the only conversion between them, so a window round-trips through the URL without drifting an
 * hour each way.
 */
export function isoToLocalInput(iso: string | null): string {
  if (iso === null) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return (
    `${String(at.getFullYear())}-${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}` +
    `T${pad2(at.getHours())}:${pad2(at.getMinutes())}`
  );
}

/** The inverse. `""` (the box cleared) is `null`, which OMITS the parameter — `?from=` is a 422. */
export function localInputToIso(value: string): string | null {
  if (value === "") return null;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return null;
  return at.toISOString();
}
