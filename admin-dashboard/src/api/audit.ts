/**
 * `GET /api/audit` and `GET /api/audit/verify` — the compliance record, and the check that it
 * has not been edited.
 *
 * Transcribed from `bayram/admin/routers/audit.py` over `bayram/admin/schemas/audit.py`. Both routes
 * are reads and neither writes a row of any kind: the obvious convenience — having `/verify`
 * drop a fresh anchor while it is already walking the chain — would put a write behind a `GET`
 * that a browser prefetch could fire. There is nothing to add here later; §6.8 ships no audit
 * writes on this build.
 *
 * ## What this wire says that a table must not flatten
 *
 * **`reasonText: null` with `hasReasonText: true` is a REFUSAL, not an absence.** `to_view`
 * projects the free text only for an unmasked role (§12.2 gives `audit.read` as **M** to ADMIN
 * and **R** to OWNER), and `hasReasonText` is computed from the stored value either way. So
 * the pair spells three distinguishable facts and the middle one — "a reason was recorded, you
 * may not read it" — is the one a screen gets wrong by rendering an empty cell. The masking is
 * a pure function of the caller's role: it is not per-row, not per-subject, and no step-up
 * changes it.
 *
 * **`hasReasonText: false` does not mean nobody gave a reason.** Free text is swept at 90 days
 * while the row lives 730, and `reason_purged_at` is deliberately not projected — so an old row
 * reads `false` even for an OWNER and the wire carries no way to tell a swept reason from one
 * that was never typed. Every row carries a `reasonCode` regardless; that is the reason.
 *
 * **`recordCount: null` is "not recorded", never `0`.** It is the reveal budget's unit — 1 for
 * a name, up to 50 for a conversation page — and a null read as zero understates exposure on
 * the one screen that measures it.
 *
 * **`actorUsername` is a SNAPSHOT, not a join.** A rename does not rewrite history, and
 * `actorRole` is the role at the time of the action rather than the actor's role today. For
 * system rows (`bootstrap CLI`, the retention cron) `actorId` is null and the username reads
 * `system:<what>`. It is staff data either way — never a customer's name, so it needs no mask.
 *
 * **`subjectId` is an opaque identifier.** A UUID, a Telegram id or a config version, matched
 * by exact equality and never a name (`_SUBJECT_ID_PATTERN` refuses anything else). Render it
 * as an identifier; a screen that labels it as a person is asserting something the column
 * cannot carry.
 *
 * **Paging is by `seq` DESC, and it is NOT the API's usual `(createdAt, id)` cursor.**
 * `schemas/page.py` opts audit out on purpose: `seq` is the bigint the hash chain depends on,
 * so the walk order and the integrity order are the same order. `nextCursor` is minted only
 * when a page came back completely full, which means a full final page costs one extra request
 * that answers `items: []`. Stop on `null`, never on `""`.
 *
 * **There is no `total` here.** `AuditPageMeta` carries `nextCursor` and nothing else, so
 * `withTotal` is deliberately absent from `AuditFilters` below rather than present and ignored
 * — a filter object with a field the endpoint cannot honour is a promise a screen will
 * eventually try to keep.
 *
 * ## Roles
 *
 * One router-level guard, `require_permission(Permission.AUDIT_READ)`, which resolves to
 * `check_role`. OWNER and ADMIN get 200; SUPPORT and VIEWER get a 403 whose refusal is itself
 * audited. **Neither route takes a step-up** — with no subject there is no scope to compare one
 * against — so a `STEP_UP_REQUIRED` from either is a server bug, and a client that answered it
 * with a password prompt would offer a loop the operator cannot win.
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import { adminRoleSchema } from "./auth";
import { AUDIT_PREFIX } from "./constants";
import {
  appendEach,
  appendPage,
  appendParam,
  pageMetaSchema,
  queryOf,
  type PageRequest,
} from "./pagination";
import { auditReasonCodeSchema } from "./reveal";

/* `AdminRole` is the login's vocabulary, declared beside `MeResponse` where it is first
   consumed. Imported rather than retyped: two spellings of one closed vocabulary drift, and
   here the drift would show up as an audit row whose actor has no role label at all. `auth.ts`
   exports the tuple and the schema but no type, so the alias below is the type OVER THAT
   SCHEMA — it cannot disagree with it. */
export { ADMIN_ROLE_VALUES, adminRoleSchema } from "./auth";
export type AdminRole = z.infer<typeof adminRoleSchema>;

/* One `admin_audit_log.reason_code` column, shared by reveal, block, unblock and grant, so the
   vocabulary lives beside its first consumer in `reveal.ts` and is re-exported rather than
   declared twice. The operator-facing labels for it are `REVEAL_REASON_LABELS`. */
export { AUDIT_REASON_CODE_VALUES, auditReasonCodeSchema, type AuditReasonCode } from "./reveal";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from the spec; a new member must be added here first        */
/* -------------------------------------------------------------------------- */

/**
 * `AuditAction` — the closed taxonomy of what a row records, `bayram.db.enums.AuditAction`, in
 * declaration order.
 *
 * The values are dotted and abbreviated and they are **not slugs**: `order.deliver` is written
 * by `ORDER_FORCE_DELIVER` and `login.limited` by `LOGIN_RATE_LIMITED`, so a screen that
 * de-slugged them would print two words the server has never heard of. The wire value is what
 * a filter matches on and what an investigation greps for, so it is what gets rendered.
 *
 * The tuple is what the picker offers; see `auditEntryViewSchema.action` for why the wire field
 * is not parsed with the schema below.
 */
export const AUDIT_ACTION_VALUES = [
  "login.success",
  "login.failure",
  "login.limited",
  "logout",
  "step_up.success",
  "step_up.failure",
  "session.revoked",
  "reveal.personal",
  "asset.stream",
  "order.retry",
  "order.reenqueue",
  "order.deliver",
  "order.cancel",
  "user.block",
  "user.unblock",
  "user.purge.req",
  "user.purge.done",
  "user.purge.fail",
  "moderation.approve",
  "moderation.reject",
  "config.validate",
  "config.commit",
  "config.rollback",
  "retention.extended",
  "retention.run",
  "export.aggregate",
  "export.order",
  "export.audit",
  "admin.create",
  "admin.role",
  "admin.deactivate",
  "admin.password",
  "permission.denied",
  "credit.grant",
  /*
   * The Payme rail's three. `rail.paused`/`rail.resumed` are written against
   * `subject_type: "config"` with `subject_id: "payme_rail"` — the switch IS configuration —
   * and `payment.notify` against `subject_type: "payment"` with the intent's UUID.
   *
   * Added here BEFORE the first row can be written, and the timing is the point on the sibling
   * console: admin-ui parses the wire's `action` with the closed enum, so an unlisted value
   * turns its whole `/audit` screen into a SCHEMA_DRIFT banner. This app parses it as
   * `z.string()` (see `auditEntryViewSchema.action`), so the cost here is smaller and
   * different — an action missing from this tuple is one nobody can FILTER on, which is an
   * investigation that comes back empty and reads as "it never happened".
   */
  "rail.paused",
  "rail.resumed",
  "payment.notify",
  /*
   * The four things an operator does to a support ticket from the panel, all against
   * `subject_type: "ticket"` with the ticket's UUID. Four members and not one `ticket.update`
   * with the verb in a field, for this enum's founding reason: "show me every reply we sent
   * this week" has to be an indexed equality on `action`, and an investigation under time
   * pressure must not have to parse `fieldNames` to tell an internal note nobody saw from a
   * message we put in a customer's phone.
   *
   * Python and TypeScript hold two independent copies of this taxonomy with NO cross-language
   * parity test, so these four landed here by hand in the same change as `AuditAction`'s. The
   * cost of forgetting is not a crash — this app parses `action` as `z.string()` — it is four
   * actions nobody can FILTER on, which is an investigation that comes back empty and reads as
   * "it never happened".
   */
  "ticket.status",
  "ticket.note",
  "ticket.reply",
  "ticket.assign",
  /*
   * Repointing the support inbox, and switching it off. Written against
   * `subject_type: "bot_chat"` with the chat id as text — on a clear, the chat that WAS selected.
   *
   * **Two members and not one `support.group.change` with the verb in a field**, on this enum's
   * founding reason: "who stopped the cards going anywhere, and when" is the question asked
   * during an incident where tickets are arriving in the panel and nobody in the Telegram group
   * has seen one, and it has to be an indexed equality on `action` rather than a filter that
   * parses `fieldNames` — `support.group.clear` is exactly one row and it is the row that
   * explains the silence. They are also not symmetrical acts: a select names a NEW chat and is
   * checked by a worker afterwards, a clear names nothing and is final on arrival.
   *
   * Python and TypeScript hold two independent copies of this taxonomy with NO cross-language
   * parity test, so these two landed here by hand in the same change as `AuditAction`'s. The
   * cost of forgetting is not a crash — this app parses `action` as `z.string()` — it is two
   * actions nobody can FILTER on, which is an investigation that comes back empty and reads as
   * "it never happened".
   */
  "support.group.select",
  "support.group.clear",
] as const;
export const auditActionSchema = z.enum(AUDIT_ACTION_VALUES);
export type AuditAction = z.infer<typeof auditActionSchema>;

/**
 * `AuditOutcome` — `bayram.db.models.admin_audit.AuditOutcome`, three members and no fourth.
 *
 * Parsed with the enum where `action` is not, and the difference is not an inconsistency. This
 * vocabulary is the writer's own three-way split — it happened, it was refused, it was allowed
 * and then failed — and every call site in `src/bayram` picks one of the three. It is also the
 * axis a pill's tone is chosen on, so an unhandled fourth member would render as an unmarked
 * cell rather than as the drift banner it actually is. Actions are added whenever a feature
 * ships; outcomes are not.
 */
export const AUDIT_OUTCOME_VALUES = ["ok", "denied", "error"] as const;
export const auditOutcomeSchema = z.enum(AUDIT_OUTCOME_VALUES);
export type AuditOutcome = z.infer<typeof auditOutcomeSchema>;

/**
 * `bayram.db.admin.audit.SUBJECT_TYPES` — the only values the column can ever hold, in the order
 * a picker reads best rather than the frozenset's (a set has no order). The frozenset is CLOSED
 * server-side: a value outside it raises inside `append`, which `audit_sink` swallows and
 * retries with `subject_id: null`, so every addition there is an addition here.
 *
 * For the FILTER only. `subjectType` is typed `str` on both the query and the response, with no
 * enum check at either boundary, so the wire field is a plain string below: a tenth subject
 * type added server-side must render as itself rather than blank every row on the screen.
 */
export const AUDIT_SUBJECT_TYPE_VALUES = [
  "order",
  "user",
  "asset",
  "chat",
  "config",
  "admin",
  "session",
  "wizard_draft",
  "system",
  /*
   * ONE payment intent, by its `payment_intents.id`. Not `order` — a purchased credit is
   * fungible and cannot be attributed to the song it rendered, so the two are joined by
   * nothing this schema records — and not `user`, because money columns survive `/forget` and
   * the buyer does not: an erased payment still has a subject while its buyer has none.
   *
   * It is offered as a filter here so "everything anyone did to this payment" stays one
   * indexed equality on `(subjectType, subjectId)` rather than a guess about which `action`
   * values to OR together, which is the argument `payment` was added to `SUBJECT_TYPES` under.
   */
  "payment",
  /*
   * ONE support ticket, by its `support_tickets.id` — never `publicRef` (which the customer
   * was told and a staffer shouts down a phone line) and never the reporter's Telegram id.
   *
   * Not `user`: four operators working four complaints from one account would collapse into
   * one subject, and "what did we do about THIS ticket" would stop being answerable. Not
   * `order` either — roughly half of all tickets arrive by `/support` and carry no order at
   * all. Offered as a filter here for the reason `payment` was added under: "everything
   * anyone did to this ticket" stays one indexed equality on `(subjectType, subjectId)`
   * rather than a guess about which `action` values to OR together.
   */
  "ticket",
  /*
   * ONE Telegram chat the bot is in, by its `bot_chats.chat_id` — Telegram's own negative
   * integer, which is that table's primary key.
   *
   * Not `chat`: that subject is a CUSTOMER's private conversation with the bot, and every row
   * under it is about a person. A `bot_chats` row holds no person at all — the one field that
   * would have been one, who added the bot, is the field the table deliberately does not store —
   * so filing the two under one subject would put a group's configuration history and a
   * customer's messages in the same `(subjectType, subjectId)` space, where `-1002…` and a
   * positive user id are told apart only by a minus sign.
   *
   * Not `config` either, which is where `rail.paused` files a Redis key under an invented
   * subject id. There is a real row here with a real primary key, and "everything anyone ever
   * did to this group" is worth being one indexed equality rather than a scan for a magic
   * string.
   */
  "bot_chat",
] as const;
export const auditSubjectTypeSchema = z.enum(AUDIT_SUBJECT_TYPE_VALUES);
export type AuditSubjectType = z.infer<typeof auditSubjectTypeSchema>;

/**
 * `ChainProtection` — what is actually protecting the log on THIS deployment.
 *
 * `revoke+hmac` is claimed only when the database confirms the application role genuinely
 * cannot `UPDATE`/`DELETE`/`TRUNCATE` the table; `hmac-only` is the honest answer everywhere
 * else, including a Postgres deployment where the revoke was configured and did not land. Note
 * the `+` and the `-`: these are not identifiers to prettify, and §12.4 says they are rendered
 * verbatim.
 *
 * The tuple carries the two values a panel has prose for. `chainVerifySchema.chainProtection`
 * is a plain string for the same reason as `subjectType`: a third protection mode is a value to
 * print with an "this build has no note for that" caveat, not a reason to refuse the whole
 * integrity report — which is the one report a deployment most needs when something is off.
 */
export const CHAIN_PROTECTION_VALUES = ["revoke+hmac", "hmac-only"] as const;
export const chainProtectionSchema = z.enum(CHAIN_PROTECTION_VALUES);
export type ChainProtection = z.infer<typeof chainProtectionSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/audit                                                              */
/* -------------------------------------------------------------------------- */

/** One row of the compliance record. */
export const auditEntryViewSchema = z.object({
  /** The chain and paging key. Monotonic, DB-assigned; two rows can share `at`, not this. */
  seq: z.number().int(),
  /** The stable external reference. Row keys and links use this, never `seq`. */
  id: z.string().uuid(),
  at: timestampSchema,
  /** `null` only for the system itself — the bootstrap CLI, the retention cron. */
  actorId: z.string().uuid().nullable(),
  /** A snapshot taken when the row was written. A rename does not rewrite history. */
  actorUsername: z.string(),
  /** The role AT THE TIME. Not the actor's role today, and not a join. */
  actorRole: adminRoleSchema,
  /**
   * Free-form on this schema on purpose.
   *
   * The Python enum is closed, but it gains a member every time a feature ships an audited
   * action — and a member this bundle has not been redeployed for would fail `safeParse` and
   * turn the whole page into a `SCHEMA_DRIFT` banner. An unknown action is a row an operator
   * can still read: the dotted value is the label. `AUDIT_ACTION_VALUES` is what the picker
   * offers, where a closed vocabulary is correct because an unknown value there IS a 422.
   */
  action: z.string(),
  /** `SUBJECT_TYPES` in practice, `str` on the wire at both ends. */
  subjectType: z.string(),
  /** An opaque identifier — a UUID, a Telegram id, a config version. Never a name. */
  subjectId: z.string().nullable(),
  /** Field NAMES only, never values (§12.4). Half of a read's blast radius. */
  fieldNames: z.array(z.string()).nullable(),
  /** The other half, and the reveal budget's unit. `null` is "not recorded", never `0`. */
  recordCount: z.number().int().nullable(),
  reasonCode: auditReasonCodeSchema,
  /** A ticket reference, `^[A-Za-z0-9#_-]{1,64}$`. Not prose. */
  reasonRef: z.string().nullable(),
  /** Masked-safe: true even when the text itself is withheld. See the header. */
  hasReasonText: z.boolean(),
  /** `null` at a masked role AND when none was recorded. `hasReasonText` tells them apart. */
  reasonText: z.string().nullable(),
  outcome: auditOutcomeSchema,
  /** An `ErrorCode`/`AdminErrorCode` value as a bare string — not a typed enum on this model. */
  errorCode: z.string().nullable(),
  /** Joins this row to the bot's and the worker's log lines. */
  correlationId: z.string().nullable(),
  /** ≤45 chars — IPv6 with an IPv4-mapped tail is the long case. */
  ip: z.string().nullable(),
  /** Which settings version a config action produced, or rolled back to. */
  configVersion: z.number().int().nullable(),
  /**
   * The tamper-evidence seal, 64 hex characters.
   *
   * Published deliberately: without the key it cannot be recomputed, and it is what lets an
   * operator match a row against the anchor line in the server log. It is a value to COMPARE,
   * never one to read.
   */
  chainHmac: z.string(),
});
export type AuditEntryView = z.infer<typeof auditEntryViewSchema>;

/**
 * `AuditPage`. `pageMetaSchema` composes here even though `AuditPageMeta` carries only
 * `nextCursor` — `total` and `isTotalExact` default to `null`, which is exactly the fact: this
 * endpoint counts nothing. That is also what makes this page structurally a `PagedResponse`, so
 * `nextCursorOf` and `hasNextPage` work on it without a second declaration.
 */
export const auditPageSchema = z.object({
  items: z.array(auditEntryViewSchema),
  meta: pageMetaSchema,
});
export type AuditPage = z.infer<typeof auditPageSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/audit/verify                                                       */
/* -------------------------------------------------------------------------- */

/** §12.4's report: does the chain hold, where does it first not, and what is protecting it. */
export const chainVerifySchema = z.object({
  /** Every link the walk covered holds, AND the tail matches the newest HEAD anchor. */
  ok: z.boolean(),
  /** `null` exactly when `ok`. Rows BELOW it are still trustworthy; from it on, nothing is. */
  firstBreakSeq: z.number().int().nullable(),
  /** Rendered verbatim (§12.4). A string, not the enum — see `CHAIN_PROTECTION_VALUES`. */
  chainProtection: z.string(),
  /** How many rows this pass actually walked. `0` on an empty table. */
  checkedRows: z.number().int(),
  /** The highest `seq` reached. `null` when nothing was walked — `last_seq or None`, so a 0 too. */
  lastSeq: z.number().int().nullable(),
  /**
   * `false` only when the 50 000-row ceiling stopped the walk before the end of the table. It
   * is a caveat on `ok: true` and never an alarm — and note the inverse: when `ok` is false the
   * walk stopped because it found the answer, so a break always arrives complete.
   */
  isComplete: z.boolean(),
  /**
   * Sequence numbers below which rows were deleted ON PURPOSE by the 730-day sweep, ascending.
   * Present entries are the reason a chain with missing history still verifies. A gap there is
   * not a break.
   */
  truncationPoints: z.array(z.number().int()).default([]),
});
export type ChainVerify = z.infer<typeof chainVerifySchema>;

/* -------------------------------------------------------------------------- */
/* Filters                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * §6.8's filter set — every parameter `build_query` and the handler accept, and no other.
 *
 * There is deliberately no `withTotal`: `AuditPageMeta` has one field and it is the cursor, so
 * a count switch here would be a control that changes nothing and a subtitle that could never
 * be filled in.
 */
export interface AuditFilters {
  /**
   * ONE parameter, two meanings, and that is the router's design: `_actor` matches an exact
   * `actor_id` when the value parses as a UUID, and otherwise casefolds it and matches
   * `actor_username` EXACTLY — usernames are stored casefolded, so it is case-insensitive but
   * never a prefix and never a substring. An empty string is no filter and never a 422.
   */
  readonly actor?: string | null;
  /** REPEATED on the wire: OR within the field, AND across fields. Empty = do not filter. */
  readonly action?: readonly AuditAction[];
  /** Exact equality, `max_length=32`. Over-length is a 422 naming the parameter. */
  readonly subjectType?: string | null;
  /** Exact equality, `max_length=64`. An opaque id, pasted rather than typed. */
  readonly subjectId?: string | null;
  /** REPEATED, like `action`. */
  readonly outcome?: readonly AuditOutcome[];
  /**
   * `at >= from` and `at <= to`, both **INCLUSIVE** — this route does not use `resolve_window`
   * and its window is not the half-open one every other list takes. A naive instant is a 422
   * saying so; there is no `to < from` ordering check, so an inverted pair is an empty page
   * rather than a refusal.
   */
  readonly from?: string | null;
  readonly to?: string | null;
}

function auditQuery(filters: AuditFilters, page: PageRequest): string {
  const params = new URLSearchParams();
  appendParam(params, "actor", filters.actor);
  appendEach(params, "action", filters.action);
  appendParam(params, "subjectType", filters.subjectType);
  appendParam(params, "subjectId", filters.subjectId);
  appendEach(params, "outcome", filters.outcome);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendPage(params, page);
  return queryOf(params);
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. Neither takes a path parameter. */
export const AUDIT_ENDPOINT = {
  list: "GET /api/audit",
  verify: "GET /api/audit/verify",
} as const;

/** One keyset page of the log, newest `seq` first. */
export function listAudit(
  filters: AuditFilters,
  page: PageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<AuditPage>> {
  return request({
    endpoint: AUDIT_ENDPOINT.list,
    path: `${AUDIT_PREFIX}${auditQuery(filters, page)}`,
    schema: auditPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Walk the chain and report on it. No parameters at all — the walk is the whole table, bounded
 * at 50 000 rows, and there is nothing for a caller to narrow.
 *
 * `bayram.admin.routers.audit.VERIFY_PATH`, which is `AUDIT_PATH + "/verify"`.
 */
export function verifyAuditChain(signal?: AbortSignal): Promise<ApiResult<ChainVerify>> {
  return request({
    endpoint: AUDIT_ENDPOINT.verify,
    path: `${AUDIT_PREFIX}/verify`,
    schema: chainVerifySchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
