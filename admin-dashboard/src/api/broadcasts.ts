/**
 * The `/api/broadcasts/**` contract, transcribed from `bayram/admin/routers/broadcasts.py` over
 * `bayram/admin/schemas/broadcasts.py`.
 *
 * Twelve routes across two routers: four reads on `broadcast.read` (**M** for all four roles,
 * because a campaign record holds operator copy, closed enums and counters and no customer data
 * at all), and eight writes on `broadcast.write` (ADMIN and OWNER), two of which enforce
 * `broadcast.send`'s step-up INSIDE the handler on the campaign id.
 *
 * ## Six rules this module encodes, all of them the backend's
 *
 * **The audience is frozen by `POST /api/broadcasts` and by nothing else.** The recipient rows
 * are materialised from the segment at creation, so `expectedAudienceSize` — the wizard's
 * optimistic-concurrency catch — is checked THERE, at the call that decides who is in, and not
 * at the send. That is why {@link BroadcastReviseRequest} carries a title and bodies and refuses
 * a segment: changing what is said is an edit, and changing who hears it is a different
 * campaign. Read a `409` from the create through {@link audienceDriftOf}, which unpacks both
 * numbers the refusal publishes.
 *
 * **"Send now" and "send on Thursday" are ONE route.** {@link BroadcastSendRequest} carries the
 * instant or omits it, and the server enqueues only for the immediate case — a future instant is
 * the due sweep's to pick up. {@link sendBroadcastNow} and {@link scheduleBroadcast} are two
 * spellings of `POST /{id}/send`, kept because they are two decisions an operator makes, not
 * because there are two endpoints. A separate `/schedule` would have been a second place to
 * forget the step-up.
 *
 * **The send and the test send need a step-up scoped to the CAMPAIGN.** `broadcast.send` with
 * `subjectId` = the broadcast UUID, taken from the refusal's `details` verbatim
 * (`stepUpTargetOf` in `api/reveal.ts`) and never re-formatted here — the server compares
 * `"broadcast.send:{id}"` whole. Pause, resume and cancel take NO step-up on purpose: pausing is
 * the action that makes fewer messages leave, and a password box in front of the brake costs
 * seconds at exactly the moment somebody needs them.
 *
 * **No raw Telegram id is on this wire.** {@link BroadcastRecipientView} publishes the mask
 * alone and there is no unmasked variant to ask for: nothing here routes on the id (a recipient
 * row is addressed by its own UUID), and this is the one list in the API that pages through a
 * membership decision made ABOUT people. `telegramUserIdMasked: null` means `/forget` nulled the
 * column — `isErased` names that state, and the row is still evidence that a message went out.
 *
 * **The test send is an allowlist, not a permission.** `admin_broadcast_test_recipients` ships
 * empty, so the route answers `403 FORBIDDEN` until a deployment names the operators' own ids.
 * The step-up runs first, before the 404 and before the allowlist, so a refusal discloses
 * neither which campaigns nor which ids exist.
 *
 * **The strip is a SIBLING route, and it publishes integers where a percentage would fit.**
 * `GET /api/broadcasts/stats` takes the list's identical filter dependency and answers for the
 * whole filter set rather than for a page, which is why it is its own URL and not `meta` on the
 * list: on `meta` it would be recomputed on every `?cursor=` an operator turns, for numbers that
 * did not change. {@link BroadcastStatsView.reachedRecipients} and `audienceTotal` cross as the
 * two counts they were formed from — a reader can see what was divided and check it against the
 * rows — and `lastSendAt` is `null` for a deployment that has never sent anything, which is a
 * fact and not an instant. Its `total` is EXACT, unlike the list's capped `meta.total`; the two
 * disagree above the cap and a screen that draws both is drawing one number twice.
 *
 * ## Two counts of the same funnel, and the panel shows both
 *
 * `BroadcastView.progress` is the campaign row's own rollup — what the worker last wrote.
 * `BroadcastDetailView.countedProgress` is the same funnel recounted from `broadcast_recipients`
 * — the rows, which are truth. They differ exactly while a send is being watched live, and
 * collapsing them would hide a stalled rollup behind a number that keeps looking right.
 * `audienceSize` and `recipientCount` differ for the same kind of reason: the first is what the
 * segment counted at creation, the second is how many rows the expansion has actually written.
 *
 * ## The segment document
 *
 * The `Segment` a create request carries — and the one the detail publishes back, re-validated —
 * is `lib/segmentCodec.ts`'s, re-exported below and never redefined here. This module does not
 * INTERPRET the document: it has no opinion about which fields exist or what an operator may
 * filter on, which is `GET /api/segments/fields`' job and the rule builder's. What it does say is
 * that the document is FROZEN by the create and re-pointed by nothing.
 */

import { z } from "zod";

import { segmentSchema } from "@/lib/segmentCodec";

import { request, type ApiFailure, type ApiResult } from "./client";
import {
  BROADCASTS_PREFIX,
  MAX_BROADCAST_BODIES,
  MAX_BROADCAST_BODY_CHARS,
  MAX_BROADCAST_BUTTON_LABEL_CHARS,
  MAX_BROADCAST_BUTTON_URL_CHARS,
  MAX_BROADCAST_CAPTION_CHARS,
  MAX_BROADCAST_MEDIA_KEY_CHARS,
  MAX_BROADCAST_TITLE_CHARS,
} from "./constants";
import {
  appendEach,
  appendPage,
  appendParam,
  pageMetaSchema,
  queryOf,
  type PageRequest,
} from "./pagination";
import { auditReasonCodeSchema, reasonedRequestSchema, type ReasonedRequest } from "./reveal";
import { languageSchema, type Language } from "./users";

/* `Language` is the customer's vocabulary, declared beside `UserView` where it is first
   consumed. Imported rather than retyped: a body is written per language and a recipient row
   records the one it was sent in, so two spellings of that enum would be two answers to "which
   of these people got the Russian text". */
export { LANGUAGE_VALUES, languageSchema, type Language } from "./users";

/* One `admin_audit_log.reason_code` column, shared by every §9.2 action — the send, the pause,
   the resume, the cancel and the test send all carry the same trio. */
export { AUDIT_REASON_CODE_VALUES, auditReasonCodeSchema, type AuditReasonCode } from "./reveal";
export { reasonedRequestSchema, type ReasonedRequest } from "./reveal";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from the spec; a new member must be added here first        */
/* -------------------------------------------------------------------------- */

/**
 * `BroadcastKind` — what a campaign IS, declared at composition and frozen for the run.
 *
 * `service` is a message the product owes the customer (an outage, a price change); `marketing`
 * is one it wants to send them. They are never one predicate: the kind selects the eligibility
 * rule the audience was built under, which is why {@link BroadcastReviseRequest} cannot change
 * it. A screen that offers them as interchangeable styling is the day somebody widens the first
 * and quietly widens the second.
 */
export const BROADCAST_KIND_VALUES = ["service", "marketing"] as const;
export const broadcastKindSchema = z.enum(BROADCAST_KIND_VALUES);
export type BroadcastKind = z.infer<typeof broadcastKindSchema>;

/**
 * `BroadcastState` — where a campaign is in its one run.
 *
 * `draft -> expanding -> ready -> sending -> completed`, with `paused` the only state that goes
 * back. `expanding` and `ready` are separate because materialising the audience is a resumable
 * multi-chunk job, and only `ready` may be authorised: a campaign whose ledger is half-written
 * cannot be scheduled, and asking is a `409` naming the state.
 *
 * `failed` grades the RUN, never the recipients — a campaign in which 12 of 40 000 messages were
 * refused is `completed`, and the per-account outcome lives on {@link BroadcastRecipientView}.
 *
 * Whether a state is terminal is **not** derived here: the server publishes
 * {@link BroadcastView.isTerminal} from its own `TERMINAL_STATES` set, so a ninth state cannot
 * arrive with a second copy of that decision in TypeScript quietly disagreeing.
 */
export const BROADCAST_STATE_VALUES = [
  "draft",
  "expanding",
  "ready",
  "sending",
  "paused",
  "completed",
  "cancelled",
  "failed",
] as const;
export const broadcastStateSchema = z.enum(BROADCAST_STATE_VALUES);
export type BroadcastState = z.infer<typeof broadcastStateSchema>;

/**
 * `BroadcastRecipientState` — one account's outcome in one campaign.
 *
 * `unknown` is the deliberate hole: a row a killed job left claimed may or may not have reached
 * the customer, and it is never retried. It is neither sent nor failed and must be rendered as
 * its own number — reporting it as a failure claims a message did not arrive when it may well
 * have. The two skips are not one either: `skipped_blocked` covers both directions of a block
 * (ours and the customer's), `undeliverable` is Telegram saying the chat is gone.
 */
export const BROADCAST_RECIPIENT_STATE_VALUES = [
  "pending",
  "sending",
  "sent",
  "failed",
  "skipped_blocked",
  "undeliverable",
  "unknown",
] as const;
export const broadcastRecipientStateSchema = z.enum(BROADCAST_RECIPIENT_STATE_VALUES);
export type BroadcastRecipientState = z.infer<typeof broadcastRecipientStateSchema>;

/**
 * `schemas.broadcasts.TELEGRAM_TAGS` — the markup a body may use, mirrored so a compose form can
 * say what is allowed rather than discovering it as a 422.
 *
 * The server validates against an ALLOWLIST and never strips: an unknown tag is refused by name
 * of the rule, and an unclosed one is refused rather than silently closed, because either repair
 * changes what the message says for every recipient at once. Four of Telegram's own are
 * deliberately absent (`<span class="tg-spoiler">`, `<pre class>`, `<tg-emoji>`,
 * `<blockquote expandable>`) — each carries an attribute, and `a href` is the only attribute this
 * API accepts anywhere.
 */
export const TELEGRAM_BODY_TAGS = [
  "b",
  "strong",
  "i",
  "em",
  "u",
  "ins",
  "s",
  "strike",
  "del",
  "code",
  "pre",
  "tg-spoiler",
  "blockquote",
  "a",
] as const;
export type TelegramBodyTag = (typeof TELEGRAM_BODY_TAGS)[number];

/* -------------------------------------------------------------------------- */
/* The segment document, carried but not interpreted                           */
/* -------------------------------------------------------------------------- */

/*
 * The audience filter travels through this module and is decided nowhere in it.
 *
 * `lib/segmentCodec.ts` owns the document — its vocabulary, its shape refusals and the
 * base64url envelope `?segment=` carries — and `api/segments.ts` owns the registry that says
 * which fields exist. Both are imported rather than restated: a second copy of the shape here
 * would be a second thing to keep true, and the failure it produces is a campaign pointed at a
 * filter that means something slightly different from the one the operator built.
 *
 * `segmentSchema` is `.strict()`, so a stored document from a build this one does not speak is
 * a parse refusal rather than a half-read filter — which is exactly what
 * `BroadcastDetailView.isSegmentReadable` reports, and why the server publishes that flag
 * instead of failing the whole read.
 */
export { segmentSchema, type Segment } from "@/lib/segmentCodec";

/* -------------------------------------------------------------------------- */
/* Responses                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The funnel from audience to messages, as arithmetic rather than as a percentage.
 *
 * **The five outcome counters do not add up to the audience, and that is the shape saying why.**
 * `audienceSize` is what the segment counted at creation; `recipientCount` is how many rows the
 * expansion actually wrote, and `isAudienceComplete` is the two compared — a half-written
 * expansion is visible instead of hiding behind one number that looks right.
 *
 * `unsettledCount` is everything not yet terminal (`pending` AND rows a claim moved to
 * `sending`), deliberately not split: the difference between them is a few seconds of a worker's
 * life. `unknownCount` is never folded into `failedCount`.
 */
export const broadcastProgressViewSchema = z.object({
  audienceSize: z.number().int(),
  recipientCount: z.number().int(),
  isAudienceComplete: z.boolean(),
  sentCount: z.number().int(),
  failedCount: z.number().int(),
  skippedCount: z.number().int(),
  undeliverableCount: z.number().int(),
  unknownCount: z.number().int(),
  /** The five terminal counters summed — the rows this campaign is finished with. */
  settledCount: z.number().int(),
  /** `recipientCount - settledCount`, floored at zero so a rollup bug is not a negative bar. */
  unsettledCount: z.number().int(),
});
export type BroadcastProgressView = z.infer<typeof broadcastProgressViewSchema>;

/**
 * One campaign: what it is, who authorised it, and how far it got.
 *
 * The segment DOCUMENT is deliberately absent — a list of twenty campaigns would otherwise carry
 * twenty filter documents nobody on that screen reads. `segmentHash` is what a list needs,
 * because it answers "is this the segment I am looking at?" without comparing two JSON blobs.
 *
 * `reasonText` is NOT here and is not on the row: `admin_audit_log` owns the operator's prose,
 * because it owns the 90-day clock that nulls it. The closed half — `reasonCode`, `reasonRef` —
 * travels, so a list can say what a send was filed under.
 */
export const broadcastViewSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  kind: broadcastKindSchema,
  state: broadcastStateSchema,
  /** The SERVER's `TERMINAL_STATES`, not a second copy of it here. */
  isTerminal: z.boolean(),
  /** SHA-256 of the stored segment document. An identity, never a filter to re-run. */
  segmentHash: z.string(),
  /**
   * The `now` the segment was compiled against. With `progress.audienceSize` it is the whole
   * answer to "why did twelve fewer people get this than the preview said": they joined
   * afterwards, and the audience was frozen here.
   */
  audienceEvaluatedAt: timestampSchema,
  scheduledFor: timestampSchema.nullable(),
  startedAt: timestampSchema.nullable(),
  finishedAt: timestampSchema.nullable(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
  /** Denormalised onto the row so a list renders without a join. Staff, so never masked. */
  createdByAdminId: z.string().uuid().nullable(),
  createdByUsername: z.string().nullable(),
  scheduledByAdminId: z.string().uuid().nullable(),
  scheduledByUsername: z.string().nullable(),
  reasonCode: auditReasonCodeSchema.nullable(),
  reasonRef: z.string().nullable(),
  /** Why the RUN failed, from a closed vocabulary. Never a vendor's message. */
  errorCode: z.string().nullable(),
  progress: broadcastProgressViewSchema,
});
export type BroadcastView = z.infer<typeof broadcastViewSchema>;

export const broadcastsPageSchema = z.object({
  items: z.array(broadcastViewSchema),
  meta: pageMetaSchema,
});
export type BroadcastsPage = z.infer<typeof broadcastsPageSchema>;

/** One segment of the strip: a state, and how many campaigns in the filter set are in it. */
export const broadcastStateTotalViewSchema = z.object({
  state: broadcastStateSchema,
  count: z.number().int(),
});
export type BroadcastStateTotalView = z.infer<typeof broadcastStateTotalViewSchema>;

/**
 * The aggregate above the campaign list, for its WHOLE filter set rather than for a page.
 *
 * **`counts` carries every `BroadcastState`, in enum order, and a zero is a real answer here.**
 * The vocabulary is closed, so a state with no campaigns is a question the response answers
 * rather than one it leaves out — the opposite of a time series, where a day nobody measured has
 * to stay missing. A consumer must still look a member UP rather than trusting its position: a
 * member this build does not find is a figure that was not published, and it renders as absent,
 * never as `0`.
 *
 * **`reachedRecipients` and `audienceTotal` are two integers and never a percentage.** The pair
 * is what a screen draws "1 240 of 1 500" from, and what lets a reader check the quotient against
 * the rows. `audienceTotal === 0` is a rate with no denominator, which is not a number: render a
 * dash and say why, not "0%".
 *
 * **`lastSendAt` is `null` when no campaign in this filter set has ever STARTED.** It is
 * `MAX(broadcasts.started_at)`, a column that stays NULL until the first message of a run leaves.
 * The null crosses as a null and must be rendered as an absence — an epoch, a creation date or
 * the word "never" spelled as a zero would each read as a send nobody made.
 *
 * `total` is the sum of the segments and is EXACT, unlike `BroadcastsPage`'s `meta.total`, which
 * saturates at the server's count cap. The two therefore disagree above that cap and should.
 */
export const broadcastStatsViewSchema = z.object({
  counts: z.array(broadcastStateTotalViewSchema),
  total: z.number().int(),
  /** Recipient rows these campaigns are FINISHED with — sent, failed, skipped, undeliverable and
      unknown alike. The numerator, and not a count of deliveries. */
  reachedRecipients: z.number().int(),
  /** What those campaigns froze into their audiences at creation. The denominator, and the number
      a human authorised — never shrunk to a half-written expansion to flatter the ratio. */
  audienceTotal: z.number().int(),
  /** The most recent instant a run STARTED, UTC, or `null`. See the schema comment. */
  lastSendAt: timestampSchema.nullable(),
});
export type BroadcastStatsView = z.infer<typeof broadcastStatsViewSchema>;

/**
 * One language's message, as composed and as it will be sent.
 *
 * **Both strings are on the wire and neither is redundant.** `text` is what the operator typed
 * and what an editor must load to let them change it; `renderedText` is the exact argument the
 * sender hands Telegram, and it is the artefact a reviewer approves. Showing only the first asks
 * somebody to sign off on markup by imagining its parse; showing only the second makes the edit
 * box lossy.
 *
 * `renderedLength` is what Telegram counts — compare it against
 * {@link broadcastBodyLimit}, not against `text.length`.
 */
export const broadcastBodyViewSchema = z.object({
  language: languageSchema,
  text: z.string(),
  renderedText: z.string(),
  renderedLength: z.number().int(),
  hasMedia: z.boolean(),
  /** An object-store key, so an editor can show the image. Not a URL and not a Telegram handle. */
  mediaStorageKey: z.string().nullable(),
  /**
   * Whether Telegram has already handed us a `file_id` for that image — i.e. whether the next
   * recipient costs an upload. The id itself is never published: it addresses nothing the panel
   * can use and everything our own bot's storage holds.
   */
  isMediaCached: z.boolean(),
  buttonLabel: z.string().nullable(),
  buttonUrl: z.string().nullable(),
});
export type BroadcastBodyView = z.infer<typeof broadcastBodyViewSchema>;

/**
 * One campaign with its bodies and the filter it was pointed at.
 *
 * **`segment` is nullable and its readability is its own field, because a stored document is
 * history and history does not re-validate.** The document was legal when it was written; a later
 * schema version may not speak it, and the campaign it belongs to has already gone out. So an
 * unreadable filter is reported as a state — render `isSegmentReadable: false` as "this build
 * cannot read the filter", never as "no filter" — and `segmentHash` still identifies it.
 */
export const broadcastDetailViewSchema = z.object({
  broadcast: broadcastViewSchema,
  /** In the order the read layer returned them; group by language in the screen. */
  bodies: z.array(broadcastBodyViewSchema),
  segment: segmentSchema.nullable(),
  isSegmentReadable: z.boolean(),
  /** The funnel recounted from the ROWS, beside `broadcast.progress`'s copy from the rollup. */
  countedProgress: broadcastProgressViewSchema,
});
export type BroadcastDetailView = z.infer<typeof broadcastDetailViewSchema>;

/**
 * One account's outcome in one campaign. **No Telegram id, at any role.**
 *
 * There is no unmasked variant to ask for and no reveal that would produce one: nothing here
 * routes on the id, and this is the one list in the API that pages in bulk through a membership
 * decision made about people.
 *
 * `telegramUserIdMasked: null` is not masking — `/forget` nulled the column, and the row survives
 * as evidence that a message was sent to an account this database no longer holds. `isErased`
 * names that, so a `null` is never read as a bug.
 */
export const broadcastRecipientViewSchema = z.object({
  id: z.string().uuid(),
  /** `•••••789`, or `null` after an erasure. */
  telegramUserIdMasked: z.string().nullable(),
  isErased: z.boolean(),
  language: languageSchema,
  state: broadcastRecipientStateSchema,
  /** How many times the sender has tried. `0` on a row nothing has claimed. */
  attempts: z.number().int(),
  /** A closed classification of Telegram's refusal, never its text. */
  errorCode: z.string().nullable(),
  /**
   * When this row reached a TERMINAL state — any of them, not just a send. A delivery is
   * `state === "sent"` TOGETHER WITH this instant; a skip stamps the same column, which is what
   * stops "never settled" and "settled, but not by a send" from sharing one `null`.
   */
  settledAt: timestampSchema.nullable(),
  createdAt: timestampSchema,
});
export type BroadcastRecipientView = z.infer<typeof broadcastRecipientViewSchema>;

export const broadcastRecipientsPageSchema = z.object({
  items: z.array(broadcastRecipientViewSchema),
  meta: pageMetaSchema,
});
export type BroadcastRecipientsPage = z.infer<typeof broadcastRecipientsPageSchema>;

/**
 * What the test send asked of the worker, and of whom — masked.
 *
 * The raw Telegram id is not echoed even though the caller sent it: this API does not put an
 * unmasked account identifier into a response nobody asked to reveal, and a caller who supplied a
 * value does not need it read back to know what they typed.
 */
export const broadcastTestSendResultViewSchema = z.object({
  broadcastId: z.string().uuid(),
  telegramUserIdMasked: z.string(),
  /** The ARQ job this enqueued. Unique per call — a second test send must not be deduplicated. */
  jobId: z.string(),
  requestedAt: timestampSchema,
});
export type BroadcastTestSendResultView = z.infer<typeof broadcastTestSendResultViewSchema>;

/* -------------------------------------------------------------------------- */
/* Requests                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Which ceiling this body is measured against, chosen by whether an image is attached.
 *
 * A photo caption is a quarter of a message and the database enforces the same 1 024 on the
 * stored text, so an over-long caption is a 422 naming the body rather than an `IntegrityError`
 * raised half-way through a transaction that has already counted an audience.
 *
 * The server applies this bound TWICE — once to the raw text, once to the rendered — so a counter
 * built on this alone is necessary and not sufficient: `Tom & Jerry` is 11 characters typed and
 * 15 on the wire.
 */
export function broadcastBodyLimit(hasMedia: boolean): number {
  return hasMedia ? MAX_BROADCAST_CAPTION_CHARS : MAX_BROADCAST_BODY_CHARS;
}

/**
 * One language's message: text, an optional image, an optional button. Nothing else.
 *
 * The text is stored VERBATIM — every server-side check reads it and none rewrites it, so the
 * body that reaches the database differs from the one that was typed in no byte. The
 * canonicalisation happens on the way to Telegram, where it is a rendering.
 *
 * **`mediaFileId` has no counterpart here on purpose.** It is minted by Telegram on the first
 * send and written by the worker; a client that could supply one could address a file this
 * deployment never uploaded.
 *
 * **The button is a PAIR.** A label with no URL is a dead button and a URL with no label is a
 * button nobody can see, so the server refuses either alone — {@link isButtonPair} is that rule
 * where a form can apply it, and {@link isTelegramButtonUrl} is the URL rule.
 */
export const broadcastBodyInputSchema = z.object({
  language: languageSchema,
  text: z.string().min(1).max(MAX_BROADCAST_BODY_CHARS),
  mediaStorageKey: z.string().max(MAX_BROADCAST_MEDIA_KEY_CHARS).nullish(),
  buttonLabel: z.string().max(MAX_BROADCAST_BUTTON_LABEL_CHARS).nullish(),
  buttonUrl: z.string().max(MAX_BROADCAST_BUTTON_URL_CHARS).nullish(),
});
export type BroadcastBodyInput = z.infer<typeof broadcastBodyInputSchema>;

/**
 * Compose a draft and FREEZE its audience. **This is the call that decides who.**
 *
 * `expectedAudienceSize` is what the operator was shown by `GET /api/segments/preview`. It is
 * optional because the same endpoint serves a caller that never rendered a preview — but a wizard
 * that omits it has switched off its own concurrency catch, so send it. The server refuses when
 * the audience has moved by more than a configured FRACTION (not a count, and not zero: people
 * sign up between the preview and the button), and publishes both numbers so the operator can
 * decide whether to re-preview or to insist. Read them with {@link audienceDriftOf}.
 *
 * There is no reason code and the asymmetry with {@link BroadcastSendRequest} is the point: this
 * messages nobody. It writes rows and spends one exact count. The authorisation to put text in
 * front of those people is the send.
 */
export const broadcastCreateRequestSchema = z.object({
  title: z.string().min(1).max(MAX_BROADCAST_TITLE_CHARS),
  kind: broadcastKindSchema,
  /** Stored on the row verbatim and never re-evaluated. */
  segment: segmentSchema,
  bodies: z.array(broadcastBodyInputSchema).min(1).max(MAX_BROADCAST_BODIES),
  /** What the operator was shown. `null`/absent means "do not check". */
  expectedAudienceSize: z.number().int().min(0).nullish(),
});
export type BroadcastCreateRequest = z.infer<typeof broadcastCreateRequestSchema>;

/**
 * Re-compose a campaign that has not gone out: the title and the WHOLE set of bodies, replaced
 * together.
 *
 * A whole replacement rather than a patch, because "leave the Russian body alone" and "delete the
 * Russian body" are the same JSON document under optional fields — sending the set makes the
 * intent explicit. There is no `segment` and no `kind`: the recipient rows exist from creation,
 * so a new filter here would describe an audience nobody is going to receive this, and the kind is
 * what selected the eligibility rule the audience was built under. Both are a new campaign.
 */
export const broadcastReviseRequestSchema = z.object({
  title: z.string().min(1).max(MAX_BROADCAST_TITLE_CHARS),
  bodies: z.array(broadcastBodyInputSchema).min(1).max(MAX_BROADCAST_BODIES),
});
export type BroadcastReviseRequest = z.infer<typeof broadcastReviseRequestSchema>;

/**
 * Authorise the send — now, or at a stated instant. **The destructive action.**
 *
 * `scheduledFor` absent means immediately. It must carry a UTC offset (`2026-08-30T12:00:00Z`) —
 * a naive instant is a 422 naming the field — and it must not already have passed, which the
 * handler checks against the same clock it stamps the row with. Only a `ready` campaign may be
 * authorised; anything else is a 409 naming the state ({@link broadcastStateConflictOf}).
 *
 * The reason trio is required here and on every lifecycle move, because this is the row that
 * records who authorised messaging how many people.
 */
export const broadcastSendRequestSchema = reasonedRequestSchema.extend({
  scheduledFor: timestampSchema.nullish(),
});
export type BroadcastSendRequest = z.infer<typeof broadcastSendRequestSchema>;

/**
 * Send the composed bodies to ONE allowlisted account, so a human can read them.
 *
 * `telegramUserId` is a field but it is **not** the control: the handler refuses any id outside
 * `admin_broadcast_test_recipients`, which is configuration — whoever may edit `.env.admin` is a
 * smaller population than whoever holds an ADMIN session, and a limit the caller supplies is not
 * a limit. `min(1)` here only stops `0` and the negative chat ids (a channel, a group) from
 * reaching a send meant for a person.
 */
export const broadcastTestSendRequestSchema = reasonedRequestSchema.extend({
  telegramUserId: z.number().int().min(1),
});
export type BroadcastTestSendRequest = z.infer<typeof broadcastTestSendRequestSchema>;

/* -------------------------------------------------------------------------- */
/* The two body rules a form can apply before a round trip                     */
/* -------------------------------------------------------------------------- */

/**
 * `ck_broadcast_bodies_button_pair`, one layer up: a label and a URL, or neither.
 *
 * Blank strings count as absent, because that is what an emptied input holds and the server would
 * see a 422 for a label of `""` rather than the "no button" the operator meant.
 */
export function isButtonPair(label: string | null | undefined, url: string | null | undefined): boolean {
  const hasLabel = typeof label === "string" && label.trim() !== "";
  const hasUrl = typeof url === "string" && url.trim() !== "";
  return hasLabel === hasUrl;
}

/**
 * Characters `schemas.broadcasts._URL_FORBIDDEN` refuses anywhere in a URL — checked BEFORE the
 * URL is parsed, because a parser strips ASCII tabs and newlines per WHATWG and would otherwise
 * turn a URL with a newline spliced into it into a clean one that no longer resembles what was
 * submitted.
 *
 * Written out character by character rather than spread from a string: a spread decomposes by
 * code point, and this list is ASCII by definition.
 */
const URL_FORBIDDEN_CHARS: ReadonlySet<string> = new Set([
  " ",
  "\t",
  "\r",
  "\n",
  '"',
  "<",
  ">",
  "\\",
  "^",
  "`",
  "{",
  "|",
  "}",
]);

/**
 * Whether a URL is one a Telegram inline button can actually open — the server's rule, restated
 * so a form refuses before a round trip.
 *
 * Absolute, `http`/`https`, with a host carrying a dot: a broadcast button points at a public
 * name, and `https://intranet/` in a message to the whole database is a mistake rather than a
 * deployment this product has. No userinfo — `https://user:pw@host/` both leaks a credential into
 * forty thousand chat logs and is the shape a phishing link uses to hide its real host.
 *
 * `http` is allowed beside `https` because Telegram accepts it and a link pasted from a partner
 * is not ours to silently upgrade.
 */
export function isTelegramButtonUrl(raw: string): boolean {
  if (raw === "") return false;
  for (const char of raw) {
    if (URL_FORBIDDEN_CHARS.has(char)) return false;
    const code = char.codePointAt(0);
    // A C0 control spliced into a URL is not a typo worth tolerating in a message sent to the
    // whole database. `undefined` is unreachable over a `for…of` of a string; refused anyway.
    if (code === undefined || code < 0x20) return false;
  }
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return false;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
  if (parsed.username !== "" || parsed.password !== "") return false;
  const host = parsed.hostname;
  return host.includes(".") && !host.endsWith(".");
}

/* -------------------------------------------------------------------------- */
/* Reading the two refusals this namespace invents                             */
/* -------------------------------------------------------------------------- */

/** Both counts of the audience, off the 409 the create answers when the world moved. */
export interface AudienceDrift {
  /** What the wizard sent — the number the operator was shown by the preview. */
  readonly expectedAudienceSize: number;
  /** What the segment counts NOW. The audience a create would actually freeze. */
  readonly audienceSize: number;
}

/**
 * A `409 CONFLICT` from `POST /api/broadcasts`, unpacked — its own state, never a generic error.
 *
 * `null` for every other conflict, `POST /{id}/send`'s wrong-state 409 included, so the two are
 * told apart by which reader answers rather than by matching a message. Both numbers are
 * published deliberately: a refusal that said only "it moved" would leave the operator with no
 * way to choose between re-previewing and insisting.
 */
export function audienceDriftOf(failure: ApiFailure | null): AudienceDrift | null {
  if (failure === null || failure.code !== "CONFLICT" || failure.details === null) return null;
  const expected = failure.details["expectedAudienceSize"];
  const actual = failure.details["audienceSize"];
  if (typeof expected !== "number" || typeof actual !== "number") return null;
  return { expectedAudienceSize: expected, audienceSize: actual };
}

/**
 * The state a lifecycle move was refused against, off the 409 the send, revise, pause, resume and
 * cancel routes answer.
 *
 * The state IS published — unlike the id in this namespace's 404s — and the difference is what the
 * caller can do with it: an operator whose "pause" lost a race to the campaign finishing needs to
 * know it finished. It is the state read a moment BEFORE the conditional `UPDATE` that actually
 * refused, which is the honest thing to report rather than pretending to have raced it.
 */
export function broadcastStateConflictOf(failure: ApiFailure | null): BroadcastState | null {
  if (failure === null || failure.code !== "CONFLICT" || failure.details === null) return null;
  const parsed = broadcastStateSchema.safeParse(failure.details["state"]);
  return parsed.success ? parsed.data : null;
}

/* -------------------------------------------------------------------------- */
/* Filters                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The campaign list's filters. Repeats are OR within a field and AND across fields; an omitted
 * field is not sent, because absent and empty are different questions.
 */
export interface BroadcastsFilters {
  /**
   * Ask for the bounded count as well. Off by default because it is a second query, and it
   * arrives as the `total`/`isTotalExact` pair — render both or neither.
   */
  readonly withTotal?: boolean;
  /** REPEATED on the wire. Empty = do not filter. */
  readonly state?: readonly BroadcastState[];
  /** REPEATED, like `state`. */
  readonly kind?: readonly BroadcastKind[];
  /** `broadcasts.created_at`, half-open `[from, to)`, RFC 3339. Either end may stand alone. */
  readonly from?: string | null;
  readonly to?: string | null;
  /**
   * Matches the campaign TITLE and nothing else. The bodies are deliberately not searchable: an
   * `EXISTS` over a child table this list cannot render would return campaigns with no visible
   * reason for being on the page. Cap the INPUT at `MAX_SEARCH_CHARS` — an over-long value is a
   * 422 naming the parameter, and truncating it here would hide that behind a page nobody asked
   * for.
   */
  readonly q?: string | null;
}

function broadcastsQuery(filters: BroadcastsFilters, page: PageRequest): string {
  const params = new URLSearchParams();
  // Sent only when asked: the server's default is false, and `withTotal=false` would be a second
  // spelling of the same request — two react-query keys, two lines in the request log.
  if (filters.withTotal === true) params.append("withTotal", "true");
  appendEach(params, "state", filters.state);
  appendEach(params, "kind", filters.kind);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendParam(params, "q", filters.q);
  appendPage(params, page);
  return queryOf(params);
}

/**
 * The strip's filters: the list's, minus the two things a strip has no use for.
 *
 * **No page**, because the aggregate is over the whole filter set and a cursor would narrow it to
 * the twenty campaigns somebody happens to be looking at — a strip that changed as an operator
 * paged would be describing the page and calling it the total.
 *
 * **No `withTotal`**, because `total` here is the sum of the segments and is already exact. There
 * is no second query to opt into and no cap to disclose, so the parameter would be a flag the
 * server does not read and a second spelling of one request in the cache.
 */
export type BroadcastsStatsFilters = Omit<BroadcastsFilters, "withTotal">;

function statsQuery(filters: BroadcastsStatsFilters): string {
  const params = new URLSearchParams();
  appendEach(params, "state", filters.state);
  appendEach(params, "kind", filters.kind);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendParam(params, "q", filters.q);
  return queryOf(params);
}

/**
 * One campaign's ledger filters. **There is no window and no cross-campaign read.**
 *
 * Every row of one campaign was written by one expansion within minutes of itself, so a date range
 * narrows nothing an operator would ask for. What they ask is "show me the failures" and "did this
 * person get it", which is `state` and `telegramUserId`.
 */
export interface BroadcastRecipientsFilters {
  readonly withTotal?: boolean;
  /** REPEATED. Empty = do not filter. */
  readonly state?: readonly BroadcastRecipientState[];
  /** REPEATED. The language the body was sent in, not the customer's UI language today. */
  readonly language?: readonly Language[];
  /**
   * EXACT `telegram_user_id`, for an id pasted whole from a support ticket.
   *
   * It is a FILTER and never a projection: the answer is a masked row like every other, so
   * "did this person get it" is answered without the id being read back off the wire.
   */
  readonly telegramUserId?: number | null;
}

function recipientsQuery(filters: BroadcastRecipientsFilters, page: PageRequest): string {
  const params = new URLSearchParams();
  if (filters.withTotal === true) params.append("withTotal", "true");
  appendEach(params, "state", filters.state);
  appendEach(params, "language", filters.language);
  appendParam(params, "telegramUserId", filters.telegramUserId);
  appendPage(params, page);
  return queryOf(params);
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The route templates, as a failure names them.
 *
 * `sendNow` and `schedule` are the SAME route, spelled twice because they are two decisions an
 * operator makes. Every failure from either names `POST /api/broadcasts/{broadcastId}/send`.
 */
export const BROADCASTS_ENDPOINT = {
  list: "GET /api/broadcasts",
  stats: "GET /api/broadcasts/stats",
  detail: "GET /api/broadcasts/{broadcastId}",
  recipients: "GET /api/broadcasts/{broadcastId}/recipients",
  create: "POST /api/broadcasts",
  revise: "POST /api/broadcasts/{broadcastId}/revise",
  send: "POST /api/broadcasts/{broadcastId}/send",
  pause: "POST /api/broadcasts/{broadcastId}/pause",
  resume: "POST /api/broadcasts/{broadcastId}/resume",
  cancel: "POST /api/broadcasts/{broadcastId}/cancel",
  testSend: "POST /api/broadcasts/{broadcastId}/test-send",
} as const;

/**
 * A campaign is addressed by its UUID, and the id is passed through untouched.
 *
 * The same string is what `broadcast.send`'s step-up scope is composed from, so re-formatting one
 * here — upper-casing, brace-stripping — would be a permanent silent 403 that looks exactly like
 * a wrong password.
 */
function broadcastPath(broadcastId: string): string {
  return `${BROADCASTS_PREFIX}/${broadcastId}`;
}

/** One keyset page of campaigns, newest composed first. ONE ROW PER CAMPAIGN, never per recipient. */
export function listBroadcasts(
  filters: BroadcastsFilters,
  page: PageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastsPage>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.list,
    path: `${BROADCASTS_PREFIX}${broadcastsQuery(filters, page)}`,
    schema: broadcastsPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * The strip: campaigns per state, what they reached, and the last send — for the whole filter set.
 *
 * `/stats` is a fixed segment and the server registers it BEFORE `/{broadcastId}`, so it is not
 * swallowed by the parameterised route and answered as a 422 about a malformed UUID. Nothing here
 * addresses a campaign, so the path is built from the prefix and never through `broadcastPath`.
 *
 * Counts, closed enum members and one UTC instant. There is no title, no body, no recipient and
 * no Telegram id on this response — it is an aggregate surface, and nothing on one is about a
 * person.
 */
export function getBroadcastStats(
  filters: BroadcastsStatsFilters,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastStatsView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.stats,
    path: `${BROADCASTS_PREFIX}/stats${statsQuery(filters)}`,
    schema: broadcastStatsViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * One campaign: its bodies rendered as Telegram will see them, its frozen filter, and both counts
 * of the funnel. 404 for an id we hold nothing on, and the id is not echoed in the refusal.
 */
export function getBroadcast(
  broadcastId: string,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.detail,
    path: broadcastPath(broadcastId),
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * This campaign's ledger, paged and masked. Every row, including the erased ones.
 *
 * **No 404 for an unknown campaign** — this is a filtered collection, and an empty page is the
 * right answer to a filter that matched nothing. The route is reached from a detail screen that
 * has already answered 404, so an empty page here means the filter, not the campaign.
 */
export function listBroadcastRecipients(
  broadcastId: string,
  filters: BroadcastRecipientsFilters,
  page: PageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastRecipientsPage>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.recipients,
    path: `${broadcastPath(broadcastId)}/recipients${recipientsQuery(filters, page)}`,
    schema: broadcastRecipientsPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Compose a campaign and freeze its audience. Answers with the campaign as it now stands.
 *
 * No step-up: this messages nobody. The refusals worth branching on are `409 CONFLICT` with both
 * audience counts ({@link audienceDriftOf}) and `422 INVALID_INPUT` for a body Telegram would
 * refuse — a length measured on the RENDERED text, markup outside the allowlist, an unclosed tag,
 * a button that is half a pair, a URL that is not absolute `http(s)`.
 */
export function createBroadcast(
  body: BroadcastCreateRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.create,
    path: BROADCASTS_PREFIX,
    method: "POST",
    body,
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Replace the title and the whole body set of a campaign that has not gone out.
 *
 * 409 once the campaign has left the states the writer accepts — and the refusal is that
 * conditional `UPDATE`'s rather than a check taken a moment earlier, because the send job runs in
 * another process and the gap between a `SELECT` and an `UPDATE` is exactly long enough for the
 * first message to leave under the old text.
 */
export function reviseBroadcast(
  broadcastId: string,
  body: BroadcastReviseRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.revise,
    path: `${broadcastPath(broadcastId)}/revise`,
    method: "POST",
    body,
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Authorise the send. **The one call in this panel that reaches outside the building.**
 *
 * Needs a live step-up scoped to `broadcast.send:{broadcastId}` — the UUID as the server spelled
 * it — so expect `STEP_UP_REQUIRED` on the first attempt and drive `POST /api/auth/step-up` from
 * the refusal's `details`, then replay this identical body. The step-up runs FIRST, so a refusal
 * costs nothing and changes nothing.
 *
 * Only a `ready` campaign may be authorised: one whose audience is still being materialised would
 * be a send against a half-written ledger, which is exactly the distinction `expanding` and
 * `ready` exist to keep. That is a 409 naming the state.
 *
 * Prefer {@link sendBroadcastNow} or {@link scheduleBroadcast} at a call site — they are this
 * function with the instant decided, and the decision is what a reader needs to see.
 */
export function sendBroadcast(
  broadcastId: string,
  body: BroadcastSendRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.send,
    path: `${broadcastPath(broadcastId)}/send`,
    method: "POST",
    body,
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Send immediately: {@link sendBroadcast} with `scheduledFor` omitted.
 *
 * Omitted rather than sent as `null`, so the request is byte-identical to one from a caller that
 * never heard of scheduling. This is the shape that enqueues the send job in the same breath.
 */
export function sendBroadcastNow(
  broadcastId: string,
  reason: ReasonedRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return sendBroadcast(broadcastId, reason, signal);
}

/**
 * Send at a stated instant: {@link sendBroadcast} with `scheduledFor` set.
 *
 * `at` must carry a UTC offset and must not already have passed — the server checks the second
 * against the same clock it stamps the row with, so a browser whose clock runs slow gets a 422
 * rather than a campaign that never fires. Nothing is enqueued now; the due sweep picks it up.
 */
export function scheduleBroadcast(
  broadcastId: string,
  at: string,
  reason: ReasonedRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return sendBroadcast(broadcastId, { ...reason, scheduledFor: at }, signal);
}

/**
 * Stop delivering, from `sending`. **No step-up**, deliberately: this is the brake.
 *
 * Setting the column is all this does and all it can do — the chunk job reads the state at the top
 * of each chunk and again every few messages, so a pause takes effect within seconds. A row a
 * worker has already claimed has either been sent or has an unknown outcome, and neither is undone
 * by pausing.
 */
export function pauseBroadcast(
  broadcastId: string,
  body: ReasonedRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.pause,
    path: `${broadcastPath(broadcastId)}/pause`,
    method: "POST",
    body,
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** `paused -> sending`, and the chunk job that stopped is re-enqueued. `startedAt` is not re-stamped. */
export function resumeBroadcast(
  broadcastId: string,
  body: ReasonedRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.resume,
    path: `${broadcastPath(broadcastId)}/resume`,
    method: "POST",
    body,
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Stop the campaign for good, from any non-terminal state — `expanding` included.
 *
 * **Cancelling does not un-send what has gone.** A campaign cancelled halfway is a cancelled
 * campaign with `sentCount` messages already delivered, and the counters keep saying so rather
 * than being reset; the recipient rows stay as the evidence of what was about to happen. A screen
 * that promises otherwise is promising something no API can do.
 */
export function cancelBroadcast(
  broadcastId: string,
  body: ReasonedRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastDetailView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.cancel,
    path: `${broadcastPath(broadcastId)}/cancel`,
    method: "POST",
    body,
    schema: broadcastDetailViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Send the composed bodies to ONE allowlisted account.
 *
 * Same step-up as the send — `broadcast.send:{broadcastId}` — and a `403 FORBIDDEN` when the
 * recipient is not on this deployment's allowlist. That refusal names neither the campaign nor the
 * id, masked or otherwise, so a screen must not echo the typed id back into it.
 *
 * This changes no campaign row: it writes an audit row and enqueues a job. Nothing about the
 * campaign is stale afterwards.
 */
export function testSendBroadcast(
  broadcastId: string,
  body: BroadcastTestSendRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BroadcastTestSendResultView>> {
  return request({
    endpoint: BROADCASTS_ENDPOINT.testSend,
    path: `${broadcastPath(broadcastId)}/test-send`,
    method: "POST",
    body,
    schema: broadcastTestSendResultViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
