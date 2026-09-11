/**
 * The Payme rail's twelve routes, transcribed from `bayram/admin/schemas/billing.py` over
 * `bayram/admin/routers/billing.py`.
 *
 * Nine reads and three writes across four server routers, and the split is not arbitrary: six
 * reads are `dashboard.read` aggregates over which nothing is personal data, three are
 * `records.read` (a payment is a record with a masked buyer on it, in the same class as an
 * order), pause/resume are `rail.control`, and the notify is `payment.notify` — a cell of its
 * own so a support operator can re-send a confirmation without also holding the switch that
 * stops the business selling.
 *
 * ## What this wire says that a screen must not flatten
 *
 * **There is NO `telegramUserId` field on this surface, and there will not be one.** A payer
 * identity is a `POST /api/reveal` question; adding a second door to plaintext would be a
 * second audit shape and a second budget for one disclosure. What travels instead is
 * `telegramUserIdMasked` (the server's `mask_telegram_user_id`, or `null`) beside an EXPLICIT
 * `isBuyerErased`. Those are two different facts — `null` because `/forget` ran, versus a
 * mask of a column that is populated — and a screen that collapses them turns "the money
 * moved and there is nobody left to grant to" into a blank cell that reads as a bug.
 *
 * **`idempotencyKey` is absent by design.** It is shaped `topup:{tg}:{scope}:{seq}` and
 * embeds the customer's Telegram id, which is precisely why `publicRef` exists. It stays a
 * server-side join key: it is not on a view model, it is not a lookup parameter, and a
 * tooltip warning would not stop it reaching a DOM node, a screenshot and a support ticket.
 *
 * **A state with no rows is ABSENT from a funnel, never zero.** Both `intents` and
 * `transactions` are sparse lists of `{state, count}`, so a chart must not assume a fixed set
 * of bars — a zero bar is a claim about payments nobody attempted on a day this rail may not
 * have been switched on.
 *
 * **Every count travels beside a window-BLIND probe.** `hasOpenedAnyIntent`,
 * `hasRecordedTransaction`, `hasRecordedInboundCall`, `hasRecordedSettlement` — each is
 * measured with the range deliberately ignored, so `0` never has to mean two things. This is
 * `getVendorUsage`'s shape and it is the whole reason this section is legible today: the rail
 * has taken nothing, and "nothing in your range" and "this has never run here" are two
 * screens with two remedies.
 *
 * **`verdict` is computed on the SERVER and rendered, never recomputed.** The five-minute
 * `run_payme_sweep` logs the same identity from the same query; a console that reached its own
 * conclusion would send an operator to reconcile two tools instead of two tables. Note the
 * identity is `transactionsPerformed + operatorSettlements == receiptsWritten`, NOT the
 * three-way equality — a hand-settled payment has no performed transaction — and that
 * `grantsWritten <= receiptsWritten` because grants are the single-song subset.
 *
 * **`isPaused` is a `boolean`, not `boolean | null`.** `bayram.payme.pause.is_paused` never
 * raises and answers `false` when Redis is unwell, BECAUSE that is what the bot's own checkout
 * path will do. A panel reporting UNKNOWN would be a second reader disagreeing with the one
 * the bot consults, which is two answers to "is the rail paused". The two caveats belong in
 * copy beside the switch, not in a third state on the wire.
 *
 * Every nullable field below is `.nullable()` and never `.nullish()`: FastAPI ships every key
 * (`response_model_exclude_unset=False`), so a key marked optional and then omitted is real
 * drift this build would swallow. `.strict()` is deliberately not used — an unknown key is
 * forward compatibility, not disagreement.
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import { BILLING_PREFIX, METRICS_PREFIX, OPS_PREFIX } from "./constants";
import {
  appendCountedPage,
  appendEach,
  appendParam,
  pageMetaSchema,
  queryOf,
  type CountedPageRequest,
} from "./pagination";
import { reasonedRequestSchema } from "./reveal";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A plain string, for `dashboard.ts`'s reason: a stricter regex turns
 * a timezone-spelling change into a drift banner, and `Date.parse` reads both spellings. */
const timestampSchema = z.string();

/** ISO 4217 as the intent recorded it. Today always `UZS`; never assume it. */
const currencySchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — closed vocabularies, so a new server member must be added here first */
/* -------------------------------------------------------------------------- */

/**
 * `PaymentIntentState` — the five states of `payment_intents`, forward-only.
 *
 * `awaiting` means a rail transaction holds the mutex; `expired` is reachable only from
 * `pending`, because our clock and Payme's are not the same clock and the expiry sweep
 * deliberately refuses to touch a payment the rail may be charging right now.
 */
export const INTENT_STATE_VALUES = [
  "pending",
  "awaiting",
  "paid",
  "cancelled",
  "expired",
] as const;
export const intentStateSchema = z.enum(INTENT_STATE_VALUES);
export type IntentState = z.infer<typeof intentStateSchema>;

/** `IntentProduct` — a single song, or the starter plan. Two members, and `starter` is the
 * only one that carries `planSongs`/`planDays`. */
export const INTENT_PRODUCT_VALUES = ["single", "starter"] as const;
export const intentProductSchema = z.enum(INTENT_PRODUCT_VALUES);
export type IntentProduct = z.infer<typeof intentProductSchema>;

/**
 * `PaymeState` — the rail's own four, stored as text and never as the wire integers.
 *
 * `cancelled_after_perform` is never written from an inbound request: a cancel of a performed
 * transaction is refused with -31007, because `credit_accounts.balance` is a fungible scalar
 * and a reversal could burn a credit paid for in a different purchase. It exists so a
 * manually reconciled cabinet refund has somewhere true to be recorded.
 */
export const RAIL_TRANSACTION_STATE_VALUES = [
  "created",
  "performed",
  "cancelled",
  "cancelled_after_perform",
] as const;
export const railTransactionStateSchema = z.enum(RAIL_TRANSACTION_STATE_VALUES);
export type RailTransactionState = z.infer<typeof railTransactionStateSchema>;

/**
 * `SettleSource` — who moved this money.
 *
 * Not a stored column: `payment_intents.settle_note` holds `payme` or `operator:<ref>` and the
 * server classifies the string. An enum rather than a boolean because "was this settled by
 * hand?" is the first question of every reconciliation, and an `isManual` flag is one somebody
 * eventually inverts. `null` while the payment has not settled at all.
 */
export const SETTLE_SOURCE_VALUES = ["rail", "operator"] as const;
export const settleSourceSchema = z.enum(SETTLE_SOURCE_VALUES);
export type SettleSource = z.infer<typeof settleSourceSchema>;

/**
 * `AttentionPopulation` — the board's three chips, as a list filter.
 *
 * One member per count, and the pairing is enforced on the SERVER: the predicate behind each
 * is a module-private helper that `attention_counts` and `list_intents` both call. A chip
 * reading "4 stuck" over a list showing three of them is impossible rather than unlikely, and
 * that is only true while the console links the chip to `?attention=` instead of composing an
 * equivalent-looking filter of its own.
 */
export const ATTENTION_POPULATION_VALUES = [
  "awaiting_stale",
  "paid_unnotified",
  "paid_no_receipt",
] as const;
export const attentionPopulationSchema = z.enum(ATTENTION_POPULATION_VALUES);
export type AttentionPopulation = z.infer<typeof attentionPopulationSchema>;

/**
 * `SettlementVerdict` — five words, in the server's precedence order.
 *
 * `never_settled` is first and is NOT `balanced`: a zero-equals-zero green tick on a rail that
 * has never taken a payment is indistinguishable from a healthy quiet week, and it is the
 * state this deployment is in today. `grants_over_receipts` is the only strictly impossible
 * combination and the only one rendered as a fault.
 */
export const SETTLEMENT_VERDICT_VALUES = [
  "never_settled",
  "grants_over_receipts",
  "receipts_short",
  "receipts_over",
  "balanced",
] as const;
export const settlementVerdictSchema = z.enum(SETTLEMENT_VERDICT_VALUES);
export type SettlementVerdict = z.infer<typeof settlementVerdictSchema>;

/** `LifelineStep` — the six things that have to happen for money to become a song, in order. */
export const LIFELINE_STEP_VALUES = [
  "opened",
  "rail_transaction",
  "performed",
  "receipt",
  "credit_granted",
  "customer_told",
] as const;
export const lifelineStepSchema = z.enum(LIFELINE_STEP_VALUES);
export type LifelineStep = z.infer<typeof lifelineStepSchema>;

/**
 * `LifelineStatus` — what the panel can SEE of one step.
 *
 * Four and not three, because `not_applicable` is the whole value of this renderer: a plan sale
 * that grants no credit and an erased buyer who gets no receipt are both COMPLETE payments, and
 * a three-state renderer would have to call them broken.
 */
export const LIFELINE_STATUS_VALUES = ["done", "pending", "not_applicable", "missing"] as const;
export const lifelineStatusSchema = z.enum(LIFELINE_STATUS_VALUES);
export type LifelineStatus = z.infer<typeof lifelineStatusSchema>;

/**
 * `LifelineNote` — WHY a step looks the way it does, as a closed slug.
 *
 * English sentences on the wire were the rejected alternative: this console is trilingual with
 * asserted key parity, so a sentence here would be a fourth translation no locale file could
 * reach. Every one of the seven is reachable and every one needs a string in `en`, `ru` and
 * `uz` — `Lifeline.test.tsx` asserts exactly that.
 */
export const LIFELINE_NOTE_VALUES = [
  "never_opened",
  "awaiting_rail",
  "buyer_erased",
  "plan_grants_nothing",
  "not_settled",
  "already_told",
  "purged",
] as const;
export const lifelineNoteSchema = z.enum(LIFELINE_NOTE_VALUES);
export type LifelineNote = z.infer<typeof lifelineNoteSchema>;

/** `ChainStopKind` — which of the two endings this payment has. See `ChainStopView`. */
export const CHAIN_STOP_KIND_VALUES = ["single_song", "plan"] as const;
export const chainStopKindSchema = z.enum(CHAIN_STOP_KIND_VALUES);
export type ChainStopKind = z.infer<typeof chainStopKindSchema>;

/**
 * `NotifyRefusal` — the three cases where re-enqueuing the confirmation would do nothing.
 *
 * All three are evaluable from the intent row alone, which is why the dossier ships them on
 * the read: the button can be disabled with its reason showing before any round trip. The
 * server re-checks all three anyway — a disabled button is a courtesy and the handler is the
 * authority — and a refusal arrives as a 409 carrying `details.refusalCode` from this same
 * vocabulary, so there is one set of words and not two.
 */
export const NOTIFY_REFUSAL_VALUES = ["not_paid", "buyer_erased", "already_notified"] as const;
export const notifyRefusalSchema = z.enum(NOTIFY_REFUSAL_VALUES);
export type NotifyRefusal = z.infer<typeof notifyRefusalSchema>;

/**
 * `IntentReferenceMatch.matched_on` — which unique index answered a lookup.
 *
 * Worth carrying rather than dropping: an operator who pasted a Payme transaction id and
 * landed on a payment needs to know the console matched THEIR identifier and not ours.
 */
export const LOOKUP_MATCH_VALUES = ["public_ref", "payme_transaction_id"] as const;
export const lookupMatchSchema = z.enum(LOOKUP_MATCH_VALUES);
export type LookupMatch = z.infer<typeof lookupMatchSchema>;

/** `PaymentReceipt.source` — the literal table name the sale landed in. Never collapsed: a
 * top-up and a plan are two products with two shapes, and one word for both hides which. */
export const RECEIPT_SOURCE_VALUES = ["topup_purchases", "plan_purchases"] as const;
export const receiptSourceSchema = z.enum(RECEIPT_SOURCE_VALUES);
export type ReceiptSource = z.infer<typeof receiptSourceSchema>;

/* -------------------------------------------------------------------------- */
/* Shared views                                                                */
/* -------------------------------------------------------------------------- */

/**
 * The half-open `[since, until)` a windowed number was counted over.
 *
 * Spelled `since`/`until` here and `from`/`to` on the dashboard's own `WindowView` — the
 * server named this pair differently because `from` is a Python keyword and would have forced
 * the only hand-written alias in that package. Transcribe it as it is: a prettier local name
 * turns `client.ts`'s `safeParse` into a permanent `SCHEMA_DRIFT` banner.
 *
 * `since: null` is "everything ever recorded up to `until`" and must render as "all time",
 * never as a date. On the settlement route it is never null, because `?from=` is required
 * there — the identity is a statement about a window, and "all time" is a different and, on
 * a column indexed only as of migration 0025, expensive question.
 */
export const billingWindowSchema = z.object({
  since: timestampSchema.nullable(),
  until: timestampSchema,
});
export type BillingWindow = z.infer<typeof billingWindowSchema>;

/** One state and how many rows are in it. A state with no rows is ABSENT from the list. */
export const stateCountSchema = z.object({
  state: z.string(),
  count: z.number().int(),
});
export type StateCount = z.infer<typeof stateCountSchema>;

/**
 * Provider, cashbox and sandbox flag — MEASURED off the newest `payment_intents` row.
 *
 * Not configuration, and the difference is the reason this shape exists. The bot's
 * `CHECKOUT_PROVIDER` lives in an env file the admin process does not load, and
 * `PAYME_ENABLED` lives in the gateway's own `/etc/bayram/payme.env`; a `checkoutProvider`
 * field on `AdminSettings` would have read `.env.admin` — a third file — and rendered `stub`
 * with total confidence while the bot sold through Payme. `seenAt` is on the wire so a stale
 * reading is VISIBLY stale rather than quietly wrong.
 */
export const checkoutSeenSchema = z.object({
  provider: z.string(),
  merchantId: z.string(),
  isSandbox: z.boolean(),
  seenAt: timestampSchema,
});
export type CheckoutSeen = z.infer<typeof checkoutSeenSchema>;

/**
 * One inbound JSON-RPC call from the rail, and how this deployment answered it.
 *
 * `replyCode` tells success from fault BY SIGN — `0` is success and every protocol fault is
 * negative — and there is no second column. `cancelReason` on a transaction is the same kind
 * of value: the rail's own vocabulary, which they extend without asking us, so both are named
 * at the presentation edge only with the raw integer always visible beside the name.
 *
 * `peerIp` is Payme's data centre and never a customer's address. This table holds no Telegram
 * id, no request body and no header at all — that absence is the design, and it is what keeps
 * the journal off the retention and privacy inventories.
 */
export const inboundCallSchema = z.object({
  id: z.string(),
  at: timestampSchema,
  method: z.string(),
  publicRef: z.string().nullable(),
  paymeTransactionId: z.string().nullable(),
  replyCode: z.number().int(),
  peerIp: z.string().nullable(),
  durationMs: z.number().int(),
});
export type InboundCall = z.infer<typeof inboundCallSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/ops/rail — the board's header, and the only unwindowed read         */
/* -------------------------------------------------------------------------- */

/**
 * Is this machine armed, and what has it heard?
 *
 * There is deliberately NO `gatewayEnabled` and NO `checkoutProvider` here, not even a
 * nullable one: a field that is always null teaches the next reader that it might one day be
 * populated, and neither value is readable from the admin process. The console states the
 * refusal in copy instead, which teaches the truth.
 */
export const railStatusSchema = z.object({
  checkoutSeen: checkoutSeenSchema.nullable(),
  isPaused: z.boolean(),
  pauseKey: z.string(),
  lastInboundCall: inboundCallSchema.nullable(),
  hasOpenedAnyIntent: z.boolean(),
  hasRecordedTransaction: z.boolean(),
  hasRecordedInboundCall: z.boolean(),
  hasSettledAnyIntent: z.boolean(),
  asOf: timestampSchema,
});
export type RailStatus = z.infer<typeof railStatusSchema>;

const RAIL_PATH = `${OPS_PREFIX}/rail`;
const RAIL_PAUSE_PATH = `${RAIL_PATH}/pause`;
const RAIL_RESUME_PATH = `${RAIL_PATH}/resume`;
const RAIL_METRICS_PREFIX = `${METRICS_PREFIX}/rail`;
const SETTLEMENT_PATH = `${RAIL_METRICS_PREFIX}/settlement`;
const FUNNEL_PATH = `${RAIL_METRICS_PREFIX}/funnel`;
const ATTENTION_PATH = `${RAIL_METRICS_PREFIX}/attention`;
const FAULTS_PATH = `${RAIL_METRICS_PREFIX}/calls-by-code`;
const CALLS_PATH = `${BILLING_PREFIX}/calls`;
const LOOKUP_PATH = `${BILLING_PREFIX}/lookup`;
const INTENTS_PATH = `${BILLING_PREFIX}/intents`;

/** The route templates a failure names and a query key is built from. The server's spelling,
 * snake_case parameter included, because it is an identity and not a URL. */
export const BILLING_ENDPOINT = {
  railStatus: "GET /api/ops/rail",
  settlement: "GET /api/metrics/rail/settlement",
  funnel: "GET /api/metrics/rail/funnel",
  attention: "GET /api/metrics/rail/attention",
  faults: "GET /api/metrics/rail/calls-by-code",
  calls: "GET /api/billing/calls",
  intents: "GET /api/billing/intents",
  lookup: "GET /api/billing/lookup",
  dossier: "GET /api/billing/intents/{intent_id}",
  pause: "POST /api/ops/rail/pause",
  resume: "POST /api/ops/rail/resume",
  notify: "POST /api/billing/intents/{intent_id}/notify",
} as const;

/**
 * The rail's current state. **No window parameter, and that is deliberate on the server.**
 *
 * Every field is either a current fact or a probe measured with any range ignored. A window
 * here would invite the console to render "the rail is off" because somebody narrowed the
 * picker, which is the one sentence this screen must never say by accident.
 */
export function getRailStatus(signal?: AbortSignal): Promise<ApiResult<RailStatus>> {
  return request({
    endpoint: BILLING_ENDPOINT.railStatus,
    path: RAIL_PATH,
    schema: railStatusSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* The four windowed aggregates                                                */
/* -------------------------------------------------------------------------- */

/** `?from=`/`?to=`, RFC 3339 with an offset. A naive instant is a 422 naming `UTC offset`. */
export interface BillingWindowQuery {
  readonly from?: string | null;
  readonly to?: string | null;
}

function windowParams(window: BillingWindowQuery): URLSearchParams {
  const params = new URLSearchParams();
  appendParam(params, "from", window.from);
  appendParam(params, "to", window.to);
  return params;
}

/**
 * The reconciliation identity over one bounded window, with the verdict attached.
 *
 * The identity is written `performed + settledByHand = receiptsWritten`, and `grantsWritten`
 * sits beside it as the single-song SUBSET rather than as a third term — a plan sale writes a
 * receipt and grants nothing at purchase, because a plan mints songs as they are used. The
 * two-way form that `payme_sql.settlement_counts`' own docstring asserts would make every use
 * of the recovery button read as a defect, which is how an alert gets muted.
 */
export const settlementSchema = z.object({
  window: billingWindowSchema,
  transactionsPerformed: z.number().int(),
  operatorSettlements: z.number().int(),
  receiptsWritten: z.number().int(),
  grantsWritten: z.number().int(),
  hasRecordedSettlement: z.boolean(),
  verdict: settlementVerdictSchema,
});
export type Settlement = z.infer<typeof settlementSchema>;

/**
 * The settlement identity. **`from` is REQUIRED**: without it the server answers 422 naming
 * the parameter rather than silently widening to all time.
 */
export function getSettlement(
  window: BillingWindowQuery,
  signal?: AbortSignal,
): Promise<ApiResult<Settlement>> {
  return request({
    endpoint: BILLING_ENDPOINT.settlement,
    path: `${SETTLEMENT_PATH}${queryOf(windowParams(window))}`,
    schema: settlementSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Where a window's payments got to, on both sides of the rail, plus the RPC volume.
 *
 * `window` is nullable here and on the faults list — an unwindowed request is "the whole
 * record", which is a different answer from "since the beginning of time" and the null is how
 * the wire says so.
 */
export const railFunnelSchema = z.object({
  window: billingWindowSchema.nullable(),
  intents: z.array(stateCountSchema),
  intentsExpiredAfterTransaction: z.number().int(),
  intentsExpiredWithNoTransaction: z.number().int(),
  transactions: z.array(stateCountSchema),
  rpcCalls: z.number().int(),
  rpcFaults: z.number().int(),
  hasOpenedAnyIntent: z.boolean(),
  hasRecordedTransaction: z.boolean(),
  hasRecordedInboundCall: z.boolean(),
});
export type RailFunnel = z.infer<typeof railFunnelSchema>;

export function getRailFunnel(
  window: BillingWindowQuery,
  signal?: AbortSignal,
): Promise<ApiResult<RailFunnel>> {
  return request({
    endpoint: BILLING_ENDPOINT.funnel,
    path: `${FUNNEL_PATH}${queryOf(windowParams(window))}`,
    schema: railFunnelSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * The three populations an operator can act on, as of one instant. **No window, ever.**
 *
 * A payment stuck last Tuesday is still stuck today; scoping these counts to the page's date
 * picker would hide exactly the rows they exist to find, which is the failure mode of every
 * alerts panel that inherits the header's range. `staleAfterHours` is echoed back so a chip
 * can carry the same cutoff into `?attention=` and the two cannot disagree.
 */
export const attentionSchema = z.object({
  asOf: timestampSchema,
  staleAfterHours: z.number().int(),
  awaitingHeldPastTimeout: z.number().int(),
  paidNeverAnnounced: z.number().int(),
  paidWithNoReceipt: z.number().int(),
});
export type Attention = z.infer<typeof attentionSchema>;

export function getAttention(
  staleAfterHours?: number,
  signal?: AbortSignal,
): Promise<ApiResult<Attention>> {
  const params = new URLSearchParams();
  appendParam(params, "staleAfterHours", staleAfterHours);
  return request({
    endpoint: BILLING_ENDPOINT.attention,
    path: `${ATTENTION_PATH}${queryOf(params)}`,
    schema: attentionSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** `method` × `replyCode`, counted, with the span it happened over and its worst latency. */
export const faultClusterSchema = z.object({
  method: z.string(),
  replyCode: z.number().int(),
  calls: z.number().int(),
  firstAt: timestampSchema,
  lastAt: timestampSchema,
  slowestMs: z.number().int(),
});
export type FaultCluster = z.infer<typeof faultClusterSchema>;

/**
 * The fault table, with the probe that says whether an empty one means anything.
 *
 * Two meanings, one of which is good news: "nothing failed in your range" and "Payme has never
 * called this endpoint". The probe is the only thing that separates them.
 */
export const faultClusterListSchema = z.object({
  window: billingWindowSchema.nullable(),
  clusters: z.array(faultClusterSchema),
  hasRecordedInboundCall: z.boolean(),
});
export type FaultClusterList = z.infer<typeof faultClusterListSchema>;

export interface FaultClusterQuery extends BillingWindowQuery {
  /** 1..`MAX_FAULT_CLUSTERS`. Over the ceiling is a 422 naming the parameter, never a clamp. */
  readonly limit?: number;
}

export function getFaultClusters(
  query: FaultClusterQuery = {},
  signal?: AbortSignal,
): Promise<ApiResult<FaultClusterList>> {
  const params = windowParams(query);
  appendParam(params, "limit", query.limit);
  return request({
    endpoint: BILLING_ENDPOINT.faults,
    path: `${FAULTS_PATH}${queryOf(params)}`,
    schema: faultClusterListSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* GET /api/billing/calls — the inbound journal                                */
/* -------------------------------------------------------------------------- */

export const callPageSchema = z.object({
  items: z.array(inboundCallSchema),
  meta: pageMetaSchema,
});
export type CallPage = z.infer<typeof callPageSchema>;

/**
 * The journal's filters.
 *
 * `method` is the one free-text filter value this whole API accepts, and it is deliberate:
 * `payme_rpc_log.method` records an UNKNOWN method on purpose — a closed type would have
 * raised on the way in and lost exactly the row an incident needs — so a filter that could not
 * name one would be unable to find it. An empty list means NO filter and never "match none".
 */
export interface CallFilters extends BillingWindowQuery {
  readonly method?: readonly string[];
  readonly faultsOnly?: boolean;
  /** 24 lowercase hex. Malformed is a 422 naming the parameter. */
  readonly ref?: string | null;
  /** 24 hex, case-insensitive: it is Payme's identifier, pasted out of Payme's cabinet. */
  readonly transactionId?: string | null;
}

export function listCalls(
  filters: CallFilters,
  page: CountedPageRequest = {},
  signal?: AbortSignal,
): Promise<ApiResult<CallPage>> {
  const params = windowParams(filters);
  appendEach(params, "method", filters.method);
  // Sent only when true: the server's default is `false`, so `faultsOnly=false` would be a
  // second spelling of one request — two cache entries and two lines in the request log.
  if (filters.faultsOnly === true) params.append("faultsOnly", "true");
  appendParam(params, "ref", filters.ref);
  appendParam(params, "transactionId", filters.transactionId);
  appendCountedPage(params, page);
  return request({
    endpoint: BILLING_ENDPOINT.calls,
    path: `${CALLS_PATH}${queryOf(params)}`,
    schema: callPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* GET /api/billing/intents — the payments list                                */
/* -------------------------------------------------------------------------- */

/**
 * One started payment, with its whole fulfilment chain answered as booleans.
 *
 * `hasGrant: false` on a settled PLAN sale is the normal case and not a gap — a plan grants
 * nothing at purchase. `settleSource` distinguishes the rail's own settlement from the
 * recovery button, which is the first question of every reconciliation. `transactionCount` and
 * `latestTransactionState` are correlated scalars and are NOT a join: the relation is 1:N, and
 * a join would fan every money column out per transaction.
 */
export const intentListItemSchema = z.object({
  intentId: z.string(),
  publicRef: z.string(),
  createdAt: timestampSchema,
  validUntil: timestampSchema,
  state: z.string(),
  product: z.string(),
  planSongs: z.number().int().nullable(),
  planDays: z.number().int().nullable(),
  amountMinor: z.number().int(),
  currency: currencySchema,
  provider: z.string(),
  merchantId: z.string(),
  isSandbox: z.boolean(),
  telegramUserIdMasked: z.string().nullable(),
  isBuyerErased: z.boolean(),
  transactionCount: z.number().int(),
  latestTransactionState: z.string().nullable(),
  latestPerformTime: timestampSchema.nullable(),
  hasReceipt: z.boolean(),
  hasGrant: z.boolean(),
  settledAt: timestampSchema.nullable(),
  settleSource: settleSourceSchema.nullable(),
  settleNote: z.string().nullable(),
  notifiedAt: timestampSchema.nullable(),
});
export type IntentListItem = z.infer<typeof intentListItemSchema>;

/**
 * The three window-blind probes that ride INSIDE the page envelope.
 *
 * A second request to `/ops/capabilities` was the rejected alternative: an empty list would
 * then be legible only after a second round trip landed, so the first paint of the most common
 * state on this deployment — nothing, ever — would be a bare zero. `getVendorUsage` ships its
 * probes the same way and for the same reason.
 */
export const railProbesSchema = z.object({
  hasOpenedAnyIntent: z.boolean(),
  hasRecordedTransaction: z.boolean(),
  hasSettledAnyIntent: z.boolean(),
});
export type RailProbes = z.infer<typeof railProbesSchema>;

export const intentPageSchema = z.object({
  items: z.array(intentListItemSchema),
  meta: pageMetaSchema,
  capabilities: railProbesSchema,
});
export type IntentPage = z.infer<typeof intentPageSchema>;

/**
 * What `GET /api/billing/intents` may be narrowed by.
 *
 * There is no `q`, no name search and no buyer filter, and that is a standing refusal in this
 * panel rather than an omission: billing is searched by `publicRef` and by Payme transaction
 * id — the two identifiers that are not people.
 *
 * `staleAfterHours` is read by the server ONLY when `attention` is `awaiting_stale`. Carry it
 * whenever the board's card is not on the default, or the chip and the list compute one
 * population against two different cutoffs.
 */
export interface IntentFilters extends BillingWindowQuery {
  readonly state?: readonly IntentState[];
  readonly product?: readonly IntentProduct[];
  readonly settledBy?: SettleSource | null;
  readonly attention?: AttentionPopulation | null;
  /** Tri-state: absent is "do not filter", and `false` is a real filter for production rows. */
  readonly sandbox?: boolean | null;
  readonly staleAfterHours?: number | null;
}

export function listIntents(
  filters: IntentFilters,
  page: CountedPageRequest = {},
  signal?: AbortSignal,
): Promise<ApiResult<IntentPage>> {
  const params = windowParams(filters);
  appendEach(params, "state", filters.state);
  appendEach(params, "product", filters.product);
  appendParam(params, "settledBy", filters.settledBy);
  appendParam(params, "attention", filters.attention);
  appendParam(params, "sandbox", filters.sandbox);
  // Sent only alongside the population it qualifies. On any other filter the server ignores
  // it, and a parameter that is ignored is one a reader will eventually believe.
  if (filters.attention === "awaiting_stale") {
    appendParam(params, "staleAfterHours", filters.staleAfterHours);
  }
  appendCountedPage(params, page);
  return request({
    endpoint: BILLING_ENDPOINT.intents,
    path: `${INTENTS_PATH}${queryOf(params)}`,
    schema: intentPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* GET /api/billing/lookup — "the customer read me a reference over the phone"  */
/* -------------------------------------------------------------------------- */

/**
 * A reference resolved to a payment, or an honest not-found.
 *
 * Three outcomes and not two, and keeping them apart is the whole point of this route: a
 * malformed reference is a 422 naming the parameter (the operator mistyped), a well-formed one
 * that matches nothing is a **200** carrying two nulls ("no payment exists under that
 * reference on this deployment"), and a match is an id to navigate to. Collapsing the first
 * two would tell somebody their customer never paid when in fact they dropped a character.
 */
export const intentLookupSchema = z.object({
  intentId: z.string().nullable(),
  matchedOn: lookupMatchSchema.nullable(),
});
export type IntentLookup = z.infer<typeof intentLookupSchema>;

/** Exactly one of the two. Neither and both are each a 422 naming the parameters. */
export interface LookupQuery {
  readonly ref?: string | null;
  readonly transactionId?: string | null;
}

export function getIntentLookup(
  query: LookupQuery,
  signal?: AbortSignal,
): Promise<ApiResult<IntentLookup>> {
  const params = new URLSearchParams();
  appendParam(params, "ref", query.ref);
  appendParam(params, "transactionId", query.transactionId);
  return request({
    endpoint: BILLING_ENDPOINT.lookup,
    path: `${LOOKUP_PATH}${queryOf(params)}`,
    schema: intentLookupSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* GET /api/billing/intents/{intentId} — the dossier                           */
/* -------------------------------------------------------------------------- */

/** The dossier's head. `IntentListItem`'s fields, as its own type on the server so a future
 * detail-only field does not widen every list row. It carries no `idempotencyKey`. */
export const intentDetailSchema = intentListItemSchema;
export type IntentDetail = z.infer<typeof intentDetailSchema>;

/**
 * One rail-side transaction and the three instants a replay must be able to repeat.
 *
 * `createTime`, `performTime` and `cancelTime` are PERSISTED, never derived: a replayed method
 * must return the ORIGINAL instant or certification fails. `paymeTime` is the rail's own
 * creation instant — the 12-hour timeout runs off it, and it is what these rows are ordered by,
 * never `createdAt`.
 */
export const railTransactionSchema = z.object({
  paymeTransactionId: z.string(),
  state: z.string(),
  paymeTime: timestampSchema,
  createTime: timestampSchema,
  performTime: timestampSchema.nullable(),
  cancelTime: timestampSchema.nullable(),
  cancelReason: z.number().int().nullable(),
});
export type RailTransaction = z.infer<typeof railTransactionSchema>;

/**
 * The sale written under this payment's key, from whichever receipts table it landed in.
 *
 * `reference` is the rail's own id — what an operator searches the Payme cabinet for.
 * `creditsGranted` is populated for a top-up and `songsIncluded`/`songsUsed`/`planEndsAt` for a
 * plan; the null halves are the product saying which it is, not a missing measurement.
 */
export const receiptSchema = z.object({
  source: z.string(),
  amountMinor: z.number().int(),
  currency: currencySchema,
  provider: z.string(),
  reference: z.string().nullable(),
  creditsGranted: z.number().int().nullable(),
  songsIncluded: z.number().int().nullable(),
  songsUsed: z.number().int().nullable(),
  planEndsAt: timestampSchema.nullable(),
  createdAt: timestampSchema,
});
export type Receipt = z.infer<typeof receiptSchema>;

/** One `credit_ledger` movement under this payment's key. `delta` is SIGNED. */
export const ledgerEntrySchema = z.object({
  kind: z.string(),
  delta: z.number().int(),
  reason: z.string(),
  actor: z.string().nullable(),
  createdAt: timestampSchema,
});
export type LedgerEntry = z.infer<typeof ledgerEntrySchema>;

/**
 * One lifeline step: what it is, what the panel can see, when, and why it looks like that.
 *
 * The rule the renderer follows: **`status` is what the panel can SEE, `noteCode` is WHY.**
 * A note can ride on a `done` step (`already_told` answers "was the confirmation sent, and
 * when?", which is what the operator opened the dossier to ask) and on a `missing` one
 * (`purged` says the evidence aged out rather than never existed).
 */
export const lifelineStepViewSchema = z.object({
  key: lifelineStepSchema,
  status: lifelineStatusSchema,
  at: timestampSchema.nullable(),
  noteCode: lifelineNoteSchema.nullable(),
});
export type LifelineStepView = z.infer<typeof lifelineStepViewSchema>;

export const lifelineSchema = z.object({
  steps: z.array(lifelineStepViewSchema),
});
export type Lifeline = z.infer<typeof lifelineSchema>;

/**
 * Where the chain stops. **Always rendered, never hidden.**
 *
 * For `single_song` the honest answer is that whether the purchased credit became a song is
 * unanswerable by construction: `credit_accounts.balance` is a fungible scalar with no lot
 * structure, so a later `DEBIT`/`ORDER_RENDER` row cannot be attributed to the grant that
 * funded it. Stating that beats hiding the panel, because a missing panel reads as a screen
 * that failed to load. For `plan` the chain continues — `songsUsed` of `songsIncluded`.
 */
export const chainStopSchema = z.object({
  kind: chainStopKindSchema,
  songsUsed: z.number().int().nullable(),
  songsIncluded: z.number().int().nullable(),
  planEndsAt: timestampSchema.nullable(),
});
export type ChainStop = z.infer<typeof chainStopSchema>;

export const notifyEligibilitySchema = z.object({
  canNotify: z.boolean(),
  refusalCode: notifyRefusalSchema.nullable(),
  notifiedAt: timestampSchema.nullable(),
});
export type NotifyEligibility = z.infer<typeof notifyEligibilitySchema>;

/**
 * Everything an operator needs to answer "did this customer's money turn into a song?".
 *
 * **One request, and the server takes all six reads inside ONE transaction.** That is not
 * incidental: an operator has to trust the receipt and the transaction were true at the same
 * instant, and six separate reads during a live settlement would show a performed transaction
 * with no receipt beside it. A console that assembled this from six queries would reintroduce
 * exactly the race the server went to the trouble of closing.
 *
 * `settleCommand` is text the dossier RENDERS and never runs. There is no route behind it: the
 * transition it performs is the one move in the whole state machine that names no holder and
 * therefore drops the mutex, and the evidence that authorises it is a charge in the Payme
 * cabinet this process is structurally forbidden to see.
 */
export const intentDossierSchema = z.object({
  intent: intentDetailSchema,
  transactions: z.array(railTransactionSchema),
  receipt: receiptSchema.nullable(),
  ledger: z.array(ledgerEntrySchema),
  calls: z.array(inboundCallSchema),
  lifeline: lifelineSchema,
  chainStop: chainStopSchema,
  notify: notifyEligibilitySchema,
  settleCommand: z.string(),
});
export type IntentDossier = z.infer<typeof intentDossierSchema>;

/** One payment's dossier. A 404 means this deployment holds no payment under that id. */
export function getIntentDossier(
  intentId: string,
  signal?: AbortSignal,
): Promise<ApiResult<IntentDossier>> {
  return request({
    endpoint: BILLING_ENDPOINT.dossier,
    path: `${INTENTS_PATH}/${encodeURIComponent(intentId)}`,
    schema: intentDossierSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/* -------------------------------------------------------------------------- */
/* The three writes                                                            */
/* -------------------------------------------------------------------------- */

/**
 * `RailSwitchRequest` — a reason and nothing else.
 *
 * **No step-up, and that is argued rather than overlooked.** `bayram/payme/pause.py` states in
 * its own docstring that this switch "is not a security control and must never be documented,
 * tested or relied upon as one"; a hijacked session that presses it stops the bot QUOTING new
 * checkouts, moves no money, discloses nobody and mints nothing, and the next operator undoes
 * it in one click. It is an incident brake, and a password box in front of a brake costs
 * ninety seconds at exactly the moment somebody needs them. What it gets instead is a
 * mandatory `reasonCode`, a confirmation dialog, ADMIN and OWNER only, and an audit row.
 */
export const railSwitchRequestSchema = reasonedRequestSchema;
export type RailSwitchRequest = z.infer<typeof railSwitchRequestSchema>;

/**
 * The switch as STORED, not as requested.
 *
 * The handler re-reads the key after writing it, so this is what the bot's own checkout path
 * would now see rather than an echo of what was asked for. Render THIS, never the request:
 * the two differ exactly when something went wrong, which is the case worth showing.
 */
export const railSwitchSchema = z.object({
  isPaused: z.boolean(),
  pauseKey: z.string(),
  changedAt: timestampSchema,
});
export type RailSwitch = z.infer<typeof railSwitchSchema>;

function postSwitch(
  endpoint: string,
  path: string,
  body: RailSwitchRequest,
): Promise<ApiResult<RailSwitch>> {
  return request({ endpoint, path, method: "POST", body, schema: railSwitchSchema });
}

/** Stop the bot opening new checkouts. Payments already in flight are unaffected. */
export function postRailPause(body: RailSwitchRequest): Promise<ApiResult<RailSwitch>> {
  return postSwitch(BILLING_ENDPOINT.pause, RAIL_PAUSE_PATH, body);
}

/** Let the bot open checkouts again. */
export function postRailResume(body: RailSwitchRequest): Promise<ApiResult<RailSwitch>> {
  return postSwitch(BILLING_ENDPOINT.resume, RAIL_RESUME_PATH, body);
}

/**
 * `NotifyRequest` — re-enqueue the confirmation this customer was already owed.
 *
 * `requestId` is accepted and deliberately not needed for correctness: idempotency here is
 * STRUCTURAL rather than promised. `payme_notify_job_id(publicRef)` is deterministic so ARQ
 * collapses a double press into one job, and `mark_intent_notified` stamps `notified_at` only
 * `WHERE notified_at IS NULL`, so this enqueue and the worker's own five-minute backstop
 * cannot both message one person.
 */
export const notifyRequestSchema = reasonedRequestSchema.extend({
  requestId: z.string().uuid().nullish(),
});
export type NotifyRequest = z.infer<typeof notifyRequestSchema>;

/**
 * What the queue did — and `isReplay` is the interesting half.
 *
 * ARQ answers `None` when the deterministic job id is already queued, and the server turns that
 * into `isReplay: true` rather than asking a second time to find out, which would race the
 * worker. A replay is a success: the message is going out, it is just not going out twice.
 */
export const notifyEnqueuedSchema = z.object({
  intentId: z.string(),
  publicRef: z.string(),
  jobId: z.string(),
  isReplay: z.boolean(),
  enqueuedAt: timestampSchema,
});
export type NotifyEnqueued = z.infer<typeof notifyEnqueuedSchema>;

/**
 * Re-send one payment's confirmation.
 *
 * The three refusals are 409s carrying `details.refusalCode` from `NOTIFY_REFUSAL_VALUES`.
 * They are not a second vocabulary: the dossier already ships `notify.refusalCode` on the
 * read, so the button is disabled with its reason showing and the 409 is only the server
 * re-checking a fact that may have moved since the page loaded.
 */
export function postIntentNotify(
  intentId: string,
  body: NotifyRequest,
): Promise<ApiResult<NotifyEnqueued>> {
  return request({
    endpoint: BILLING_ENDPOINT.notify,
    path: `${INTENTS_PATH}/${encodeURIComponent(intentId)}/notify`,
    method: "POST",
    body,
    schema: notifyEnqueuedSchema,
  });
}

/**
 * The `refusalCode` a 409 from the notify route carries, when it carries one.
 *
 * Read through this rather than by casting `error.details`: the bag is server-shaped, and a
 * cast that guessed wrong would render "already notified" for a refusal that said something
 * else entirely. `null` for any other failure, including a 409 whose details are absent.
 */
export function notifyRefusalOf(details: Record<string, unknown> | null): NotifyRefusal | null {
  if (details === null) return null;
  const parsed = notifyRefusalSchema.safeParse(details["refusalCode"]);
  return parsed.success ? parsed.data : null;
}
