/**
 * The dashboard wire contract, transcribed from `.openpencil-export/dashboard-openapi.json`
 * (produced by `bayram/admin/routers/dashboard.py` and `bayram/admin/schemas/dashboard.py`).
 *
 * Nine reads carry the whole page: five windowed sections, one windowed-on-one-half
 * IDENTIFIED list pair, and three unwindowed states — the plan book and the two probes, none
 * of which may be captioned with the period picker. The shapes below are the server's, field
 * for field — a prettier local name would turn the `safeParse` in `client.ts` into a permanent
 * `SCHEMA_DRIFT` banner, which is the loudest thing this app can do and must therefore only
 * ever mean a real disagreement.
 *
 * **Eight of the nine are `DASHBOARD_READ` aggregates over which nothing is personal data.
 * `audience-lists` is none of those things** — `RECORDS_READ`, unmasked customer identity, and
 * an audit row written on every single call. It is transcribed at the bottom of this file
 * behind a section comment stating what that costs a caller, and it must not be fetched on the
 * polling cadence the seven aggregates use.
 *
 * Three rules govern how these are READ, and they are the backend's own:
 *
 * **`null` is "not instrumented", never `0`.** `UsdCost.amountUsd`, `NetRunRateView.netMinor`,
 * `DerivedRevenueView.amountMinor`, every quantity on `VendorBalanceView` — a null is a
 * sentence about this deployment's instrumentation, and the mock renders it as a hatched tag
 * pill ("not tracked", "not polled", "needs balances"). Rendering it as a zero puts a number
 * on the screen nobody measured, and a number on this page gets believed.
 *
 * **A bucket that is absent is absent.** Counts are zero-filled only when the request gave a
 * lower bound; `SeriesResponse.isZeroFilled` says whether it happened. Money is NEVER
 * zero-filled, so a gap in `revenue` or `spend` is a gap, not a floor.
 *
 * **A percentile without its `sampleCount` is not a measurement.** `LatencyView` and
 * `OperationLatencyView` both carry theirs first, because `p95 = 4s` over three orders is a
 * fact about three orders.
 *
 * Units are in the field names and the server chose them deliberately: `*Minor` is minor
 * units of the neighbouring `currency` (soʻm tiyin, and there is no scalar money anywhere on
 * this surface), `*Usd` is a USD decimal, `*Seconds` is fractional seconds and `*Ms` is whole
 * milliseconds.
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import { METRICS_PREFIX, OPS_PREFIX } from "./constants";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * RFC 3339, `Z`-suffixed. Not validated past "a string", for `auth.ts`'s reason: a stricter
 * regex turns a timezone-spelling change into a drift banner, and `Date.parse` reads both.
 */
const timestampSchema = z.string();

/** A calendar DATE (`YYYY-MM-DD`), not an instant. Only `FxRateView.asOf` is one. */
const dateSchema = z.string();

/** ISO 4217, as the receipts recorded it. Today always `UZS`; never assume it. */
const currencySchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — closed vocabularies, so a new member must be added here first        */
/* -------------------------------------------------------------------------- */

/** `AbsenceReason`. Why a number that would otherwise be here is not, and what to do. */
export const ABSENCE_REASON_VALUES = [
  "no_fx_rate",
  "no_price_published",
  "mixed_currencies",
  "not_priced",
  "no_denominator",
  "not_instrumented",
] as const;
export const absenceReasonSchema = z.enum(ABSENCE_REASON_VALUES);
export type AbsenceReason = z.infer<typeof absenceReasonSchema>;

/** `Vendor` — invoice granularity, coarser than the adapter name. `fake` is a demo run. */
export const VENDOR_VALUES = [
  "elevenlabs",
  "openrouter",
  "gemini",
  "openai_compatible",
  "fake",
] as const;
export const vendorSchema = z.enum(VENDOR_VALUES);
export type Vendor = z.infer<typeof vendorSchema>;

/** `VendorOperation` — what the vendor was asked to do, the unit a rate card is quoted in. */
export const VENDOR_OPERATION_VALUES = [
  "music_compose",
  "music_inpaint",
  "speech_synthesis",
  "transcription",
  "chat_completion",
  "health",
] as const;
export const vendorOperationSchema = z.enum(VENDOR_OPERATION_VALUES);
export type VendorOperation = z.infer<typeof vendorOperationSchema>;

/** `OrderState`. Forward-only; `delivered`, `failed` and `cancelled` end the walk. */
export const ORDER_STATE_VALUES = [
  "draft",
  "brief_ready",
  "lyrics_ready",
  "authorized",
  "generating",
  "delivered",
  "failed",
  "cancelled",
] as const;
export const orderStateSchema = z.enum(ORDER_STATE_VALUES);
export type OrderState = z.infer<typeof orderStateSchema>;

/** `RevenueSource` — which receipts table a row came from. Never collapse the two. */
export const REVENUE_SOURCE_VALUES = ["plan", "topup"] as const;
export const revenueSourceSchema = z.enum(REVENUE_SOURCE_VALUES);
export type RevenueSource = z.infer<typeof revenueSourceSchema>;

/**
 * `SeriesBucket` — the grains a chart may ask for, and they ARE lowercase (`hour`, `day`,
 * `week`, `month`), verified against `bayram/admin/schemas/overview.py:199`. `week` and `month`
 * are folded from `day` server-side so a monthly series sums to the daily one it came from.
 */
export const SERIES_BUCKET_VALUES = ["hour", "day", "week", "month"] as const;
export const seriesBucketSchema = z.enum(SERIES_BUCKET_VALUES);
export type SeriesBucket = z.infer<typeof seriesBucketSchema>;

/** `ComponentState`. `not_probed` is a third state, NOT a quiet `ok`. */
export const COMPONENT_STATE_VALUES = ["ok", "degraded", "not_probed"] as const;
export const componentStateSchema = z.enum(COMPONENT_STATE_VALUES);
export type ComponentState = z.infer<typeof componentStateSchema>;

/** `BalanceUnit`. "4 312 remaining" is a fortune in dollars and an afternoon in characters. */
export const BALANCE_UNIT_VALUES = ["usd", "characters"] as const;
export const balanceUnitSchema = z.enum(BALANCE_UNIT_VALUES);
export type BalanceUnit = z.infer<typeof balanceUnitSchema>;

/**
 * `BalanceEstimateBasis` — how a "songs remaining" figure was divided out, and therefore how
 * far to trust it. `trailing_tts_characters` UNDERCOUNTS its divisor (music renders bill the
 * same pool without writing characters), so an estimate on that basis is an UPPER BOUND.
 */
export const BALANCE_ESTIMATE_BASIS_VALUES = [
  "trailing_spend_usd",
  "trailing_tts_characters",
] as const;
export const balanceEstimateBasisSchema = z.enum(BALANCE_ESTIMATE_BASIS_VALUES);
export type BalanceEstimateBasis = z.infer<typeof balanceEstimateBasisSchema>;

/**
 * `CostSource` — HOW a dollar figure was arrived at, as `bayram.contracts.CostSource` spells it.
 *
 * This is the real member, and it is narrower than `UsdCost.costSource`, which is a free-form
 * string because the collapsed shapes may answer `"mixed"` there. `costProvenance` is a
 * PARTITION, so `"mixed"` cannot arise in it and the enum is the honest type.
 *
 * `vendor_reported` is what the vendor's own response said, and it is the only one of the
 * three that can legitimately be `0.0` — OpenRouter's free models report exactly that.
 */
export const COST_SOURCE_VALUES = ["vendor_reported", "derived", "estimated"] as const;
export const costSourceSchema = z.enum(COST_SOURCE_VALUES);
export type CostSource = z.infer<typeof costSourceSchema>;

/**
 * `Language` — the language the BOT speaks to an account in, never the language a song is
 * SUNG in. `users.ui_language` and `briefs.output_language` are chosen independently.
 *
 * Declared here rather than imported from `users.ts`, which publishes the identical enum:
 * that module already imports `orderStateSchema` from THIS one, and a second edge would close
 * the cycle. These schemas are built at module scope, so a cycle is not a lint complaint —
 * it is a `ReferenceError` at boot in whichever of the two loads second.
 */
export const LANGUAGE_VALUES = ["uz_latn", "uz_cyrl", "ru", "en"] as const;
export const languageSchema = z.enum(LANGUAGE_VALUES);
export type Language = z.infer<typeof languageSchema>;

/**
 * `PlanKind` — which subscription a `plan_purchases` row records.
 *
 * One member today. The column is a plain `VARCHAR(32)` with no check constraint, so a second
 * plan ships with no migration and no server-side signal — which means the day one is added,
 * this list is what turns it into a loud `SCHEMA_DRIFT` rather than a silent blank cell.
 */
export const PLAN_KIND_VALUES = ["starter"] as const;
export const planKindSchema = z.enum(PLAN_KIND_VALUES);
export type PlanKind = z.infer<typeof planKindSchema>;

/* -------------------------------------------------------------------------- */
/* Shared views                                                                */
/* -------------------------------------------------------------------------- */

/**
 * The half-open `[from, to)` the numbers were counted over.
 *
 * The asymmetry is the contract: `from` is nullable ("everything ever recorded up to `to`" —
 * there is no start instant the operator chose, and an epoch would be one they did not) and
 * `to` never is, because the server resolves an open upper bound to the instant it served
 * the request. Render `from: null` as "all time", never as a date.
 */
export const windowViewSchema = z.object({
  from: timestampSchema.nullable(),
  to: timestampSchema,
});
export type WindowView = z.infer<typeof windowViewSchema>;

/**
 * A quotient that carries the two numbers it came from.
 *
 * `value` is null if and only if `denominator` is zero. There is no bare rate on this wire.
 */
export const ratioViewSchema = z.object({
  value: z.number().nullable(),
  numerator: z.number(),
  denominator: z.number(),
});
export type RatioView = z.infer<typeof ratioViewSchema>;

/**
 * A count and its change against the preceding equal-length window.
 *
 * `previous` is null when the request gave no lower bound — an open-below range has no
 * length and so no predecessor — and `change` is null whenever `previous` is null OR zero.
 * So a null delta means "no comparable period", NOT "no change"; the card shows no chip.
 */
export const trendViewSchema = z.object({
  current: z.number().int(),
  previous: z.number().int().nullable(),
  change: ratioViewSchema.nullable(),
});
export type TrendView = z.infer<typeof trendViewSchema>;

/**
 * DAU / WAU / MAU, NESTED: every account in `day` is also in `week` and in `month`. Three
 * cutoffs against one column, so stacking these three bars triple-counts.
 */
export const activeAccountsViewSchema = z.object({
  day: z.number().int(),
  week: z.number().int(),
  month: z.number().int(),
  asOf: timestampSchema,
});
export type ActiveAccountsView = z.infer<typeof activeAccountsViewSchema>;

/**
 * A dollar figure with its coverage and its provenance.
 *
 * `amountUsd` is null if and only if `costSource` is null: calls were recorded, no rate was
 * configured. That is the hatched "not tracked" pill, never `$0.00`. `costedCalls` of
 * `calls` is what makes a non-null amount readable — nine of nine hundred is a sample.
 */
export const usdCostSchema = z.object({
  /** USD, decimal. Null = not priced; read `unavailableReason` for which kind of not. */
  amountUsd: z.number().nullable(),
  costedCalls: z.number().int(),
  calls: z.number().int(),
  /** Free-form on the wire (a `CostSource` name). Null exactly when `amountUsd` is. */
  costSource: z.string().nullable(),
  unavailableReason: absenceReasonSchema.nullable(),
});
export type UsdCost = z.infer<typeof usdCostSchema>;

/** Sales under one `(source, product, currency, provider)` key. Never summed across it. */
export const moneyTotalSchema = z.object({
  source: revenueSourceSchema,
  product: z.string(),
  currency: currencySchema,
  provider: z.string(),
  /** True while the checkout rail is the stub: recorded, but not settled money. */
  isStubRail: z.boolean(),
  sales: z.number().int(),
  /** Minor units of `currency` — tiyin for UZS. There is no scalar money here. */
  amountMinor: z.number().int(),
});
export type MoneyTotal = z.infer<typeof moneyTotalSchema>;

/**
 * The operator's own soʻm-per-dollar figure and the date they took it.
 *
 * Both fields are null together or set together — the server refuses a boot with only one —
 * so `uzsPerUsd` null means NO RATE IS CONFIGURED, and every conversion downstream is
 * unavailable rather than wrong. There is no feed behind it: `asOf` is the only staleness
 * signal there is, and it only works if the panel renders it beside the rate.
 */
export const fxRateViewSchema = z.object({
  uzsPerUsd: z.number().nullable(),
  asOf: dateSchema.nullable(),
});
export type FxRateView = z.infer<typeof fxRateViewSchema>;

/** `created_at` → `delivered_at`, nearest-rank. `sampleCount` first, because it is the size. */
export const latencyViewSchema = z.object({
  sampleCount: z.number().int(),
  /** Fractional SECONDS. Null when nothing was delivered in the window. */
  p50Seconds: z.number().nullable(),
  p95Seconds: z.number().nullable(),
});
export type LatencyView = z.infer<typeof latencyViewSchema>;

/** One error code's share of the window's failed attempts. `errorCode` null = uncoded. */
export const failureViewSchema = z.object({
  errorCode: z.string().nullable(),
  count: z.number().int(),
  /** 0..1 of failed attempts, not of all attempts. */
  share: z.number(),
  /** Null when the code is unknown to the taxonomy — not "not retryable". */
  isRetryable: z.boolean().nullable(),
});
export type FailureView = z.infer<typeof failureViewSchema>;

/** How many orders of the cohort sit in one state RIGHT NOW. A survivor count. */
export const orderStateCountViewSchema = z.object({
  state: orderStateSchema,
  count: z.number().int(),
});
export type OrderStateCountView = z.infer<typeof orderStateCountViewSchema>;

/**
 * Where a created-at cohort stands. Survivors, never passages — there is deliberately no
 * `abandoned`, because drafts are deleted at the cutoff and any such count would decay.
 */
export const orderFunnelViewSchema = z.object({
  created: z.number().int(),
  paid: z.number().int(),
  byState: z.array(orderStateCountViewSchema),
});
export type OrderFunnelView = z.infer<typeof orderFunnelViewSchema>;

/**
 * What this deployment can honestly answer, PROBED from the schema and the rows — never
 * declared. Every panel branches on these before it decides whether to draw or to say
 * "not instrumented".
 */
export const capabilitiesViewSchema = z.object({
  isCostTelemetry: z.boolean(),
  isLatencyTelemetry: z.boolean(),
  isAssetStorageKeyRecorded: z.boolean(),
  isChatCapture: z.boolean(),
  isPaymentLedger: z.boolean(),
  isStateTransitionLog: z.boolean(),
  isVendorUsage: z.boolean(),
  isVendorCost: z.boolean(),
  isPlanRevenue: z.boolean(),
  isTopupRevenue: z.boolean(),
  isChurnInstrumented: z.boolean(),
  isVendorBalance: z.boolean(),
  isActivityHistory: z.boolean(),
});
export type CapabilitiesView = z.infer<typeof capabilitiesViewSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/dashboard/audience                                         */
/* -------------------------------------------------------------------------- */

/**
 * Blocks and unblocks IN the window — a flow. The gauge beside it is
 * `botBlockedAccounts`. An unblock is only recorded for a previously blocked account
 * returning, so a non-zero count means real returns and never first-time arrivals.
 */
export const churnViewSchema = z.object({
  blocked: trendViewSchema,
  unblocked: trendViewSchema,
});
export type ChurnView = z.infer<typeof churnViewSchema>;

/**
 * Renewal over the plans that ENDED in the window: a RATE, in plans.
 *
 * **This is not `ChurnView` and must never be added to it.** `churn` counts PASSAGES through
 * the membership log — people blocking the bot, and separately coming back — an event count
 * with no denominator at all. This is a proportion over a population whose renewal decision
 * has actually been made. A customer can block the bot with a plan still running and can let
 * a plan lapse while using the bot daily; neither number bounds or corrects the other. The
 * owner wants both in ONE card, which is exactly where a reader would otherwise sum them.
 *
 * **`renewed + lapsed + anonymisedEnded === endedPlans`, on every window.** `lapsed` excludes
 * the erased endings, so `rate` is a FLOOR on real churn — understated by at most
 * `anonymisedEnded`, because a `/forget`-erased customer cannot be followed to a later
 * purchase by anybody, and filing them as lapsed would claim they did not come back when the
 * truth is that nobody can tell.
 *
 * **Print `endedPlans` wherever `rate` is printed.** One thirty-day product first sold weeks
 * ago means a single-digit denominator, where one ending swings the percentage thirty points.
 * Nothing is smoothed and nothing is suppressed below a threshold: at this volume the COUNT
 * is the measurement and the percentage is decoration, which is why `rate` is a `RatioView`
 * and carries its own denominator everywhere it goes.
 */
export const subscriptionChurnViewSchema = z.object({
  /** The denominator: plans that ended inside the window. `0` is a real answer. */
  endedPlans: z.number().int(),
  /** Ended plans whose holder bought again. INFERRED — there is no renewal event — and with
   * no recency bound, so a return after four idle months counts here. */
  renewed: z.number().int(),
  /** Ended, identified, and no later purchase. EXCLUDES the anonymised endings. */
  lapsed: z.number().int(),
  /** The exact width of the blind spot above `lapsed`, published beside it, never folded in. */
  anonymisedEnded: z.number().int(),
  /** `lapsed / endedPlans`. `value` null — never `0` — when nothing has ended yet: "0% churn"
   * is the most flattering lie this panel could tell, and it would be told on precisely the
   * deployments too young to have measured anything. */
  rate: ratioViewSchema,
});
export type SubscriptionChurnView = z.infer<typeof subscriptionChurnViewSchema>;

/**
 * How many accounts read the BOT in one language, with that count's share.
 *
 * The INTERFACE language, never the song's — a caption saying "song language" over this would
 * be a different measurement, not a loose label.
 */
export const languageMixEntryViewSchema = z.object({
  language: languageSchema,
  accounts: z.number().int(),
  /** Denominator is the block's own `accounts`, NOT the sum of the entries you rendered —
   * those are equal today and stop being so the moment anything filters or truncates. */
  share: ratioViewSchema,
});
export type LanguageMixEntryView = z.infer<typeof languageMixEntryViewSchema>;

/**
 * The language split with the population it is a split OF.
 *
 * `ui_language` is `NOT NULL DEFAULT uz_latn`, so the entries really do sum to `accounts` —
 * and the `uz_latn` entry over-counts CHOICE, because an account created by an order alone
 * sits at the default without anybody having picked it. It is a true count of what the bot
 * WILL SPEAK, not a survey. A windowed request narrows this to accounts CREATED in the window.
 */
export const languageMixViewSchema = z.object({
  /** Largest first. A language nobody uses is ABSENT, not present at zero — this is a fully
   * visited population, so the gap is presentational and not a missing measurement. */
  languages: z.array(languageMixEntryViewSchema),
  /** The denominator of every `share` above. */
  accounts: z.number().int(),
});
export type LanguageMixView = z.infer<typeof languageMixViewSchema>;

/**
 * One night's DAU / WAU / MAU from the snapshot table — the history of the gauge above.
 *
 * **Nested cutoffs on one population** (`day ⊆ week ⊆ month`), all three from one predicate at
 * one instant. Three lines. Never a stacked area and never summed: stacking triple-counts
 * everybody active today and the top line would be a number no query can produce.
 *
 * **A night the snapshot job missed is ABSENT and is never filled.** Zero-filling would report
 * that nobody used the bot that day, and it cannot be back-filled either — `users.last_seen_at`
 * is a gauge that was overwritten, so this history exists only from the first night the job
 * ran. Break the line across the gap; `isActivityHistory` says whether it ever ran at all.
 */
export const activityPointViewSchema = z.object({
  /** The bucket's label as the server formatted it — a string, not a `SeriesBucket`. */
  bucket: z.string(),
  startedAt: timestampSchema,
  day: z.number().int(),
  week: z.number().int(),
  month: z.number().int(),
});
export type ActivityPointView = z.infer<typeof activityPointViewSchema>;

/** `GET /api/metrics/dashboard/audience` — the Audience cards in one round trip. */
export const audienceResponseSchema = z.object({
  /** Null = counted over the whole record (neither bound was sent). */
  window: windowViewSchema.nullable(),
  totalAccounts: trendViewSchema,
  newAccounts: trendViewSchema,
  activeAccounts: activeAccountsViewSchema,
  /** Operator's own block flag — a decision somebody made. */
  blockedAccounts: z.number().int(),
  /** Customers who blocked the BOT. The gauge; `churn` is its flow. */
  botBlockedAccounts: z.number().int(),
  /** Null = never watched. "Nobody blocked us" would be `{blocked: 0, unblocked: 0}`. */
  churn: churnViewSchema.nullable(),
  isChurnInstrumented: z.boolean(),
  /** Null = no plan has EVER been sold here (`capabilities.isPlanRevenue` is the probe), so
   * four zeroes would read as "nobody renews" on a deployment that has never sold anything.
   * Rendered in the same card as `churn` and measuring something else entirely. */
  subscriptionChurn: subscriptionChurnViewSchema.nullable(),
  languageMix: languageMixViewSchema,
  /** Oldest first, at `activityBucket`. Empty = the nightly job has never run here. */
  activityHistory: z.array(activityPointViewSchema),
  /** Echoed rather than assumed, and always `day`: this route takes no `?bucket=`, because
   * the rows are one nightly sample and the three counts are GAUGES — a coarser bucket could
   * only be formed by summing them (counting one person once per day) or by picking one
   * sample out of seven (a different measurement nobody asked for). */
  activityBucket: seriesBucketSchema,
  /** False = no HISTORICAL series to draw, even though the live gauge above answers fine. */
  isActivityHistory: z.boolean(),
});
export type AudienceResponse = z.infer<typeof audienceResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/dashboard/finance                                          */
/* -------------------------------------------------------------------------- */

/** Top-ups sold before amounts were recorded. Counted, never back-priced. */
export const unpricedTopupsViewSchema = z.object({
  unpriced: z.number().int(),
  priced: z.number().int(),
});
export type UnpricedTopupsView = z.infer<typeof unpricedTopupsViewSchema>;

/**
 * Songs delivered × the published unit price. An ESTIMATE, and labelled as one — it is a
 * separate field from `revenue` and must never be added to it.
 *
 * `amountMinor`/`unitPriceMinor`/`currency` are null together when this deployment has not
 * mirrored a price, with `unavailableReason: "no_price_published"`. Never `0`, and never the
 * bot's default price, which this deployment may not be charging.
 */
export const derivedRevenueViewSchema = z.object({
  deliveredSongs: z.number().int(),
  /** Minor units of `currency`. Null when no price is published. */
  unitPriceMinor: z.number().int().nullable(),
  currency: currencySchema.nullable(),
  /** Minor units of `currency` — `deliveredSongs × unitPriceMinor`. */
  amountMinor: z.number().int().nullable(),
  unavailableReason: absenceReasonSchema.nullable(),
});
export type DerivedRevenueView = z.infer<typeof derivedRevenueViewSchema>;

/**
 * Vendor spend attributed to the window's delivered songs, over their count.
 *
 * `perSongUsd` is null when the cost is null (calls recorded, no rate) — never `$0.00`.
 * The `attributedOrders` / `deliveredOrders` gap is delivered songs carrying no vendor call
 * at all, which is what the cost figure is silently missing.
 */
export const costPerSongViewSchema = z.object({
  cost: usdCostSchema,
  deliveredOrders: z.number().int(),
  attributedOrders: z.number().int(),
  /** USD per delivered song. Null = no cost or no denominator. */
  perSongUsd: ratioViewSchema.nullable(),
});
export type CostPerSongView = z.infer<typeof costPerSongViewSchema>;

/**
 * Recorded revenue minus vendor spend over a FIXED trailing window of its own — it does NOT
 * use the caller's window, and `window` here echoes the one it did use. The card must be
 * captioned with that window and never read as belonging to the page's period picker.
 *
 * This is the one place on this wire where a currency conversion happens, and it is fenced:
 * `netMinor` is non-null only when an FX rate is published AND the window's receipts hold
 * exactly one currency. Otherwise null with an `unavailableReason` — never a partial figure,
 * never a zero.
 *
 * `currency`, `netMinor` and `annualisedMinor` are null together or set together, and
 * `unavailableReason` is non-null exactly when they are null; the server's validator refuses
 * every other combination. `annualisedMinor` is the net scaled to a year by the window's own
 * length (`net × 365 / days`) — the mock's "ARR", and NOT `netMinor × 12`, so a card that
 * multiplies the MRR itself will disagree with the server on a window that is not 30 days.
 */
export const netRunRateViewSchema = z.object({
  /** NOT the request's window. Its own trailing one, echoed so the card can say so. */
  window: windowViewSchema,
  revenue: z.array(moneyTotalSchema),
  cost: usdCostSchema,
  /** The rate the subtraction was performed at, so the figure is reproducible. */
  fxUsed: fxRateViewSchema,
  currency: currencySchema.nullable(),
  /** Minor units of `currency`. Null with a reason; never 0 as a stand-in. */
  netMinor: z.number().int().nullable(),
  annualisedMinor: z.number().int().nullable(),
  unavailableReason: absenceReasonSchema.nullable(),
});
export type NetRunRateView = z.infer<typeof netRunRateViewSchema>;

/**
 * One vendor's remaining credit, read from the cache the ARQ worker writes. The admin
 * process holds no vendor credential and makes no outbound call.
 *
 * TWO CLOCKS, and they are not interchangeable: `checkedAt` is when the poller last ASKED
 * (never null — there was a poll or there is no row) and `fetchedAt` is when these numbers
 * were last ANSWERED. They diverge during an outage, because a failed poll leaves the last
 * known balance untouched; staleness is measured against `fetchedAt` alone.
 *
 * Every quantity is nullable with no default: a vendor reporting an uncapped key answers
 * `isUnbounded` and no remaining figure, and `0` there would say the account is empty.
 */
export const vendorBalanceViewSchema = z.object({
  vendor: vendorSchema,
  /** True when this row is the fallback key rather than the primary one. */
  isFallback: z.boolean(),
  /** The adapter that was polled (`elevenlabs_music`), finer than `vendor`. */
  provider: z.string(),
  unit: balanceUnitSchema,
  /** In `unit`. Null = not reported (see `isUnbounded`), never "empty". */
  remaining: z.number().nullable(),
  total: z.number().nullable(),
  used: z.number().nullable(),
  /** True = uncapped key, so there is no remaining figure to want. Null = not reported. */
  isUnbounded: z.boolean().nullable(),
  quotaResetsAt: timestampSchema.nullable(),
  /** A phrase when the vendor gives no instant ("monthly"). Null = it said nothing. */
  quotaResetHint: z.string().nullable(),
  planTier: z.string().nullable(),
  subscriptionStatus: z.string().nullable(),
  /** An ESTIMATE. Meaningless without `estimateBasis`; the two are null together. */
  songsRemaining: z.number().int().nullable(),
  /** The divisor the estimate used, in `unit` per song. */
  perSongRate: z.number().nullable(),
  estimateBasis: balanceEstimateBasisSchema.nullable(),
  /** When these numbers were last ANSWERED. Null = never successfully polled. */
  fetchedAt: timestampSchema.nullable(),
  /** When the poller last ASKED. Always present. */
  checkedAt: timestampSchema,
  isLastPollOk: z.boolean(),
  httpStatus: z.number().int().nullable(),
  errorCode: z.string().nullable(),
  consecutiveFailures: z.number().int(),
});
export type VendorBalanceView = z.infer<typeof vendorBalanceViewSchema>;

/**
 * How many of the window's vendor calls were a fake-provider run. Every other number here
 * excludes those rows structurally; this pair is what makes the exclusion visible.
 */
export const fakeCallGuardViewSchema = z.object({
  fakeCalls: z.number().int(),
  totalCalls: z.number().int(),
});
export type FakeCallGuardView = z.infer<typeof fakeCallGuardViewSchema>;

/** `GET /api/metrics/dashboard/finance` — the money half of the page, in one request. */
export const financeResponseSchema = z.object({
  window: windowViewSchema.nullable(),
  /** Recorded receipts, one row per `(source, product, currency, provider)`. May be empty. */
  revenue: z.array(moneyTotalSchema),
  unpricedTopups: unpricedTopupsViewSchema,
  /** The ESTIMATE. Never add it to `revenue`. */
  derivedRevenue: derivedRevenueViewSchema,
  vendorSpend: usdCostSchema,
  costPerSong: costPerSongViewSchema,
  /** Real work that reached no order (`order_id IS NULL AND task IS NOT NULL`) — the leak
   * `costPerSong` cannot see. Quota probes are excluded, so this is not poller noise. */
  unattributedSpend: usdCostSchema,
  netRunRate: netRunRateViewSchema,
  fx: fxRateViewSchema,
  /** Empty when nothing polls balances; that is the "not polled" pill, not "zero left". */
  vendorBalances: z.array(vendorBalanceViewSchema),
  fakeCalls: fakeCallGuardViewSchema,
  capabilities: capabilitiesViewSchema,
});
export type FinanceResponse = z.infer<typeof financeResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/dashboard/performance                                      */
/* -------------------------------------------------------------------------- */

/** Nearest-rank p50/p95 of one vendor operation, with all three of its denominators. */
export const operationLatencyViewSchema = z.object({
  operation: vendorOperationSchema,
  /** Calls made. */
  calls: z.number().int(),
  /** Calls that recorded a duration at all — the gap to `calls` is unmeasured. */
  measuredCalls: z.number().int(),
  /** Calls the percentiles were actually taken over. */
  sampleCount: z.number().int(),
  /** Whole MILLISECONDS (unlike `LatencyView`'s seconds). Null = nothing measured. */
  p50Ms: z.number().int().nullable(),
  p95Ms: z.number().int().nullable(),
});
export type OperationLatencyView = z.infer<typeof operationLatencyViewSchema>;

/**
 * One dot on the System status strip, with the evidence it came from. No outbound call
 * produces any of these — they are read from capabilities and cached balance rows.
 */
export const componentStatusViewSchema = z.object({
  component: z.string(),
  state: componentStateSchema,
  /** Null when nothing has ever observed this component (`state: "not_probed"`). */
  asOf: timestampSchema.nullable(),
  /** A short machine-readable phrase naming what was observed. Always present. */
  evidence: z.string(),
});
export type ComponentStatusView = z.infer<typeof componentStatusViewSchema>;

/** `GET /api/metrics/dashboard/performance` — how fast, how reliably, and what is up. */
export const performanceResponseSchema = z.object({
  window: windowViewSchema.nullable(),
  /** Windowed on `delivered_at`, the same population `deliveryLatency` is taken over. */
  deliveredOrders: trendViewSchema,
  deliveryLatency: latencyViewSchema,
  /** `music_compose` only — the leg a customer actually waits on. */
  musicRenderLatency: operationLatencyViewSchema,
  failures: z.array(failureViewSchema),
  orderFunnel: orderFunnelViewSchema,
  systemStatus: z.array(componentStatusViewSchema),
  capabilities: capabilitiesViewSchema,
});
export type PerformanceResponse = z.infer<typeof performanceResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/dashboard/series                                           */
/* -------------------------------------------------------------------------- */

/** One bucket of a pure count series. Zero-fillable, because zero orders is a fact. */
export const countPointViewSchema = z.object({
  /** The bucket's own label as the server formatted it — a string, not a `SeriesBucket`. */
  bucket: z.string(),
  startedAt: timestampSchema,
  count: z.number().int(),
});
export type CountPointView = z.infer<typeof countPointViewSchema>;

/** One bucket of a revenue series, at the receipts' own grain. NEVER zero-filled. */
export const moneyPointViewSchema = z.object({
  bucket: z.string(),
  startedAt: timestampSchema,
  source: revenueSourceSchema,
  product: z.string(),
  currency: currencySchema,
  provider: z.string(),
  isStubRail: z.boolean(),
  sales: z.number().int(),
  /** Minor units of `currency`. */
  amountMinor: z.number().int(),
});
export type MoneyPointView = z.infer<typeof moneyPointViewSchema>;

/** One bucket of a spend series. `vendor` null = the bucket's spend is unattributed. */
export const spendPointViewSchema = z.object({
  bucket: z.string(),
  startedAt: timestampSchema,
  vendor: vendorSchema.nullable(),
  /** `cost.amountUsd` null = nothing in this bucket was priced. Do not plot it as 0. */
  cost: usdCostSchema,
});
export type SpendPointView = z.infer<typeof spendPointViewSchema>;

/** One `(vendor, operation)` slice of where the money went. Ordered by calls. */
export const costSplitViewSchema = z.object({
  vendor: vendorSchema,
  operation: vendorOperationSchema,
  cost: usdCostSchema,
});
export type CostSplitView = z.infer<typeof costSplitViewSchema>;

/** `GET /api/metrics/dashboard/series` — every chart on the page, in one request. */
export const seriesResponseSchema = z.object({
  window: windowViewSchema.nullable(),
  /** Echoed, and equal to what was asked for: the server refuses rather than coarsens. */
  bucket: seriesBucketSchema,
  /**
   * Whether the COUNT series were filled across the range. False means a missing bucket is
   * missing, not zero — the request gave no lower bound, so filling would invent days this
   * deployment did not exist. Money is never filled either way.
   */
  isZeroFilled: z.boolean(),
  signups: z.array(countPointViewSchema),
  delivered: z.array(countPointViewSchema),
  revenue: z.array(moneyPointViewSchema),
  spend: z.array(spendPointViewSchema),
  unattributedSpend: z.array(spendPointViewSchema),
  costSplit: z.array(costSplitViewSchema),
  orderFunnel: orderFunnelViewSchema,
});
export type SeriesResponse = z.infer<typeof seriesResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/dashboard/vendor                                           */
/* -------------------------------------------------------------------------- */

/**
 * One vendor's cut of the cost-per-delivered-song figure, with its coverage.
 *
 * `CostPerSongView` on the finance response answers "what does a song cost"; this answers
 * "and who charged us for it" — the only form of the number an operator can act on, because
 * the remedy for an expensive song is a different model or a different vendor.
 *
 * **These rows do not sum to the finance card, and three separate things stop them.**
 * `attributedOrders` double-counts an order across every vendor that rendered it, so the
 * coverage column is not additive at all. `costUsd` does partition the window exactly — but
 * only while EVERY row is rendered, which a top-N table or a vendor filter breaks. And a null
 * is not an addend. Take the aggregate from `vendorSpend`, never from a sum of these.
 *
 * **There is no `UsdCost` here and its absence is real.** This read groups by vendor and
 * carries neither `costedCalls` nor a per-vendor `costSource`, so `costUsd` must NOT be read
 * as a priced-and-sourced figure the way `vendorSpend` may be. The provenance for the same
 * window is `costProvenance`, partitioned by source instead.
 */
export const vendorCostPerSongViewSchema = z.object({
  vendor: vendorSchema,
  /** Summed over this vendor's priced rows. Null — never `0.0` — when none carried a cost. */
  costUsd: z.number().nullable(),
  /** Only ever `not_priced`: a vendor with no calls in the window has no row here at all, so
   * "not instrumented" cannot arise on a row that exists. */
  unavailableReason: absenceReasonSchema.nullable(),
  /** Delivered orders carrying at least one call from THIS vendor — how much of the cohort
   * the numerator covers, and the reason the average is not a complete figure. */
  attributedOrders: z.number().int(),
  /** `costUsd / deliveredOrders` — over the WHOLE cohort, deliberately, not over
   * `attributedOrders`. Dividing by the covered subset would report a figure that IMPROVES as
   * instrumentation degrades. Null when the vendor is unpriced or nothing was delivered. */
  costPerSong: ratioViewSchema.nullable(),
});
export type VendorCostPerSongView = z.infer<typeof vendorCostPerSongViewSchema>;

/**
 * What one delivered song CONSUMES from one vendor, in that vendor's own units.
 *
 * **The three unit families do not share an axis.** Tokens, billed characters and milliseconds
 * of audio are incommensurable: one row per unit family on any table, a separate figure each,
 * never three series on one pair of axes, never summed, never totalled into a "units" column.
 * A chat completion has no billed characters and a speech synthesis has no tokens, so each
 * quantity is null for the families nobody measured — a `0` there would say the vendor charged
 * us for nothing.
 *
 * **`totalTokens` is CONSUMPTION and never a remaining balance.** It only grows, and no reading
 * of it says anything about what is left; the remaining side is `vendorBalances`, a different
 * table with a different clock. A tile putting a token count under a "remaining" heading would
 * be reporting spend as headroom.
 */
export const vendorUnitsPerSongViewSchema = z.object({
  vendor: vendorSchema,
  /** Null = this vendor measured no tokens at all. Never `0`. */
  totalTokens: z.number().int().nullable(),
  billedCharacters: z.number().int().nullable(),
  /** Whole MILLISECONDS. Never converted to seconds anywhere on this wire. */
  audioMs: z.number().int().nullable(),
  /** Null = the vendor measured no tokens. A PRESENT ratio whose `value` is null means nothing
   * was delivered to divide by. The two absences are different facts and read differently. */
  tokensPerSong: ratioViewSchema.nullable(),
  charactersPerSong: ratioViewSchema.nullable(),
  audioMsPerSong: ratioViewSchema.nullable(),
});
export type VendorUnitsPerSongView = z.infer<typeof vendorUnitsPerSongViewSchema>;

/**
 * One `cost_source` bucket: how much of the window's money was arrived at HOW.
 *
 * Every other money shape here collapses provenance to one source and a mixed flag, so the
 * actual mix is not reconstructible from them. This is the breakdown that flag summarises, and
 * it partitions CALLS rather than the money above it.
 *
 * **`costSource: null` is its own bucket and means NOT PRICED** — the calls happened and were
 * recorded, and no cost could be computed. So `costUsd` is null there while `calls` is
 * positive, and that combination is the POINT of the row rather than a contradiction in it.
 *
 * **"0 reported" and "not priced" must never render alike.** A vendor reporting a genuine
 * `0.0` lands in `vendor_reported` with `costUsd: 0` — MEASURED, and normal here, because
 * OpenRouter's default model is a `:free` one. A vendor with no configured rate lands in the
 * null bucket — UNMEASURED. One says "this cost nothing", the other "nobody could say", and
 * collapsing them is how a deployment concludes its rendering pipeline is free.
 */
export const costProvenanceViewSchema = z.object({
  /** The real `CostSource` member, not the free-form string `UsdCost` carries: this is a
   * partition, so `"mixed"` cannot arise. Null is a REAL bucket — never defaulted away. */
  costSource: costSourceSchema.nullable(),
  /** Always measured, in every bucket, including the unpriced one. */
  calls: z.number().int(),
  /** Null in the unpriced bucket by construction. `0` in `vendor_reported` is a measurement. */
  costUsd: z.number().nullable(),
});
export type CostProvenanceView = z.infer<typeof costProvenanceViewSchema>;

/**
 * `GET /api/metrics/dashboard/vendor` — who charged us, in what units, and how the figures
 * were made. Its own section on its own cadence: spend moves slower than the audience cards.
 *
 * `vendorSpend` and `vendorBalances` also appear on `/dashboard/finance` under exactly these
 * names, from exactly these functions — republished rather than recomputed, so the breakdown
 * is never rendered without the total it partitions. The two responses agree whenever they are
 * fetched over the same window, which both echo.
 */
export const vendorResponseSchema = z.object({
  window: windowViewSchema.nullable(),
  /** The denominator of EVERY per-song figure below, counted once for the whole cohort.
   *
   * A bare `int` here. `PerformanceResponse.deliveredOrders` is a `TrendView` under the same
   * name on a different route — same word, two types — so there is deliberately no shared
   * accessor for the two and one must never be written. */
  deliveredOrders: z.number().int(),
  /** The window's whole vendor spend, fake-provider rows and unspendable operations excluded
   * structurally — the same figure `/dashboard/finance` publishes under this name. */
  vendorSpend: usdCostSchema,
  /** Most-covered vendor first. Empty = nothing delivered, or nothing delivered carries an
   * attributed call; `capabilities.isVendorUsage` tells those from an uninstrumented worker. */
  costPerSongByVendor: z.array(vendorCostPerSongViewSchema),
  /** One row per vendor, ordered by vendor: all three quantity columns are nullable, so there
   * is no volume column an honest ordering could use. */
  unitsPerSongByVendor: z.array(vendorUnitsPerSongViewSchema),
  /** Busiest bucket first, the unpriced bucket last. A partition of CALLS. */
  costProvenance: z.array(costProvenanceViewSchema),
  /** Read from the cached table — this process makes no outbound call and holds no vendor
   * credential. Empty is the "not polled" pill, never "zero left". */
  vendorBalances: z.array(vendorBalanceViewSchema),
  capabilities: capabilitiesViewSchema,
});
export type VendorResponse = z.infer<typeof vendorResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/plans — a STATE, and the one metrics route with no window   */
/* -------------------------------------------------------------------------- */

/** A money total that carries its unit. There is no scalar money on this surface. */
export const currencyAmountViewSchema = z.object({
  currency: currencySchema,
  amountMinor: z.number().int(),
});
export type CurrencyAmountView = z.infer<typeof currencyAmountViewSchema>;

/**
 * One tenth of the ENDED-plan utilisation distribution. All ten are always present, so a
 * `count` of `0` is a MEASUREMENT — "nobody finished at this ratio" — and never a gap.
 *
 * `from` is a Python keyword server-side, so the field is declared `from_` there with an
 * explicit alias towards this client: the wire name is `from`, and that is what is read here.
 */
export const planUtilisationBucketViewSchema = z.object({
  from: z.number(),
  to: z.number(),
  count: z.number().int(),
});
export type PlanUtilisationBucketView = z.infer<typeof planUtilisationBucketViewSchema>;

/**
 * `GET /api/metrics/plans` — what the running plans owe. **A STATE, so it takes NO window**:
 * "how much was owed during March" is a question this table cannot answer, and the page's
 * range picker therefore has nowhere to attach. `asOf` is the single instant BOTH the
 * liability row and the utilisation histogram were computed at, and must be printed.
 *
 * **The liability is in SONGS.** There is no soʻm figure for unconsumed songs anywhere here,
 * because valuing one means dividing `amountMinor` by `songsIncluded` — an accounting
 * allocation policy nobody in this codebase has chosen. `liveAmounts` is the measured total of
 * what the running plans were SOLD for, which is a different and honest number, and it is
 * per-currency because there is no honest total across two currencies.
 *
 * `liveHolders` excludes every customer who sent `/forget` while their plan was running, since
 * `COUNT(DISTINCT)` does not count NULLs; `liveAnonymisedPlans` is the exact width of that
 * undercount.
 */
export const planLiabilityResponseSchema = z.object({
  asOf: timestampSchema,
  livePlans: z.number().int(),
  /** Distinct IDENTIFIED holders. Understates by exactly `liveAnonymisedPlans`. */
  liveHolders: z.number().int(),
  liveAnonymisedPlans: z.number().int(),
  livePlansWithSongsLeft: z.number().int(),
  /** `null` when no plan is LIVE; `0` when plans are live and owe nothing. Two facts. */
  unconsumedSongs: z.number().int().nullable(),
  /** What the RUNNING plans were sold for, per currency. Never summed across currencies. */
  liveAmounts: z.array(currencyAmountViewSchema),
  endedPlans: z.number().int(),
  /** Songs paid for and never claimed on plans that have ENDED. `null` when none has. */
  breakageSongs: z.number().int().nullable(),
  expiringWithinDays: z.number().int(),
  /** A SUBSET of `livePlans`, never added to it. */
  expiringPlans: z.number().int(),
  /** A SUBSET of `unconsumedSongs`. `null` when no plan expires inside the horizon. */
  expiringSongsLeft: z.number().int().nullable(),
  /** Ten bars, always, over ENDED plans only — `endedPlans` above is the denominator. */
  utilisation: z.array(planUtilisationBucketViewSchema),
  /** False means no plan has ever been sold here: ten empty bars are "nothing to show". */
  isPlanRevenue: z.boolean(),
});
export type PlanLiabilityResponse = z.infer<typeof planLiabilityResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/metrics/dashboard/audience-lists — RECORDS_READ, audited, UNMASKED */
/* -------------------------------------------------------------------------- */

/*
 * The ONE identified payload on this whole surface, and the only exception to the standing
 * invariant that no Telegram id, handle or name reaches the dashboard wire at any role.
 *
 * Four consequences the components below it must carry, none of them optional:
 *
 * 1. **`RECORDS_READ`, not `DASHBOARD_READ`.** A different permission from every other read on
 *    this page, so it needs its OWN query and its own permission-denied rendering: a 403 here
 *    must not blank the four aggregate sections beside it.
 * 2. **Every call writes an audit row**, inside the request's own transaction. The audit entry
 *    is what the owner accepted INSTEAD OF a reveal gate — so this must not be polled on a
 *    timer the way the aggregate cards are. Long `staleTime`, no `refetchInterval`.
 * 3. **A null name is ABSENT, never withheld.** There is no masked variant of these shapes and
 *    adding one would be a bug; no reveal button belongs anywhere near this payload.
 * 4. **The decision covers the ACCOUNT HOLDER only.** Recipient names — the person a song is
 *    ABOUT — are a third party who consented to nothing, are not on this route, and stay
 *    behind `POST /reveal` with the step-up, the budget and the per-view audit row.
 */

/**
 * One customer on the top-generators list, ranked by songs DELIVERED. Unmasked.
 *
 * **`deliveredSongs` and `ordersCreated` are not a conversion rate and no consumer may form
 * one from them.** Both are windowed, but on DIFFERENT columns: an order created Monday and
 * delivered Tuesday is in both; one created before the window and delivered inside it is in
 * `deliveredSongs` only. So `ordersCreated` can legitimately be smaller — and `0` — beside a
 * positive delivery count. The GAP is the story: forty created and three delivered is not a
 * top generator, it is a support case, and one number cannot say which the row is.
 */
export const topGeneratorViewSchema = z.object({
  /** Always present — the ranking is keyed to it. An ERASED customer still appears here, with
   * this id and both names null, until their orders age out: `/forget` anonymises receipts and
   * deletes the profile row but does not touch `orders`. Render it as an account with no known
   * name, not as a bug. */
  telegramUserId: z.number().int(),
  /** Telegram's `@handle` WITHOUT the `@`. Null = the account has none, or no profile row was
   * ever written. Absent, never withheld — there is no masked value on this route. */
  telegramUsername: z.string().nullable(),
  firstName: z.string().nullable(),
  /** The ranking key: orders whose `delivered_at` fell in the window. */
  deliveredSongs: z.number().int(),
  /** Orders CREATED in the same window. Not a denominator — see above. */
  ordersCreated: z.number().int(),
  /** What the BOT speaks to them in, never what a song was sung in. */
  uiLanguage: languageSchema,
  /** `users.created_at` — FIRST CONTACT, not the first order. */
  firstSeenAt: timestampSchema,
  /** Nullable in the shape and never null from this route: presence requires a delivery. */
  lastDeliveredAt: timestampSchema.nullable(),
});
export type TopGeneratorView = z.infer<typeof topGeneratorViewSchema>;

/** The ranked list, with the window it was ranked over and the depth it was cut at. */
export const topGeneratorsViewSchema = z.object({
  /** The range both counts were taken over, echoed so the caption comes from the server's
   * resolved window and not from the request. Null = the whole record. */
  window: windowViewSchema.nullable(),
  /** How deep the cut was made. On the wire because "the top ten" and "everybody, and there
   * were nine" render differently and the list alone cannot tell them apart. */
  limit: z.number().int(),
  /** Most deliveries first, ties broken on the Telegram id so the order is stable across
   * reads. Empty = nothing was delivered in the window. */
  items: z.array(topGeneratorViewSchema),
});
export type TopGeneratorsView = z.infer<typeof topGeneratorsViewSchema>;

/**
 * One recent plan sale, with the buyer's identity and what the plan has left. Unmasked.
 *
 * `isStubRail` travels with the money and is never collapsed: the stub provider stamps a
 * purchase paid having contacted nobody, so a demo sale is indistinguishable from a real one
 * on every field but that one. `currency` is on the row for the same reason — these amounts
 * are per-sale and are never summed here; a total across two currencies would be a figure in
 * an invented unit.
 *
 * **`songsRemaining` means opposite things on the two sides of `isPlanEnded`.** On an ENDED
 * plan it is BREAKAGE — money taken for songs that will never be delivered. On a RUNNING plan
 * it is an obligation this deployment still owes. Same subtraction, opposite facts, which is
 * why the flag is computed server-side against one echoed instant rather than the browser's
 * clock.
 */
export const recentSubscriberViewSchema = z.object({
  /** Null after `/forget`: the receipt survives the erasure and the identity does not, so
   * "was this customer charged for songs they never got?" stays answerable. A lawful erasure,
   * never a missing write and never masking — render the row, a purge is a state not an error. */
  telegramUserId: z.number().int().nullable(),
  /** Null for an erased account, and for an account that simply has no handle. */
  telegramUsername: z.string().nullable(),
  firstName: z.string().nullable(),
  plan: planKindSchema,
  /** Minor units of `currency`. Never converted, never summed across the list. */
  amountMinor: z.number().int(),
  currency: currencySchema,
  /** The rail that answered the charge, raw, as `plan_purchases.provider` stored it. */
  provider: z.string(),
  /** `provider === "stub"`. Recorded, but not settled money. */
  isStubRail: z.boolean(),
  purchasedAt: timestampSchema,
  /** The BUSINESS clock — when the songs stop being claimable. No sweep reads it and no purge
   * acts on it, which is why it is not named `expiresAt`. */
  planEndsAt: timestampSchema,
  songsIncluded: z.number().int(),
  songsUsed: z.number().int(),
  /** `songsIncluded - songsUsed`. Read it WITH `isPlanEnded`; see above. */
  songsRemaining: z.number().int(),
  /** `planEndsAt <= asOf`, against the single instant the block echoes. */
  isPlanEnded: z.boolean(),
});
export type RecentSubscriberView = z.infer<typeof recentSubscriberViewSchema>;

/**
 * The last N plan sales, newest first. **NO WINDOW — this is a recency list.**
 *
 * It deliberately carries no `window` field. Everything else on this screen is windowed and a
 * reader will assume this is too; it is not. Caption it "the last N", NEVER "this week", and
 * do not wire the page's range picker to it. The flow version of the same question already
 * exists as the revenue series on `/dashboard/series`.
 */
export const recentSubscribersViewSchema = z.object({
  /** The one instant every row's `isPlanEnded` was decided against, so two rows either side of
   * a boundary cannot have been judged by two different clocks. */
  asOf: timestampSchema,
  limit: z.number().int(),
  /** Newest purchase first. Empty = nothing sold recently, or nothing sold ever. */
  items: z.array(recentSubscriberViewSchema),
  /** False = no plan has EVER been sold here, so an empty list is "nothing to show" rather
   * than "the read is broken". This is what tells the two empties apart. */
  isPlanRevenue: z.boolean(),
});
export type RecentSubscribersView = z.infer<typeof recentSubscribersViewSchema>;

/**
 * `GET /api/metrics/dashboard/audience-lists` — both identified lists, one round trip.
 *
 * Two BLOCKS rather than two flat lists under a shared window, because only one of them is
 * windowed. A `window` field at the top would state that both were counted over it.
 */
export const audienceListsResponseSchema = z.object({
  topGenerators: topGeneratorsViewSchema,
  recentSubscribers: recentSubscribersViewSchema,
});
export type AudienceListsResponse = z.infer<typeof audienceListsResponseSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/ops/pulse and /api/ops/capabilities                                */
/* -------------------------------------------------------------------------- */

/** Order outcomes over the WHOLE record, and the one rate the panel leads with. */
export const deliveryViewSchema = z.object({
  total: z.number().int(),
  delivered: z.number().int(),
  failed: z.number().int(),
  cancelled: z.number().int(),
  inFlight: z.number().int(),
  /** The `successRate` denominator: terminal orders only, never in-flight ones. */
  terminalCount: z.number().int(),
  /** 0..1. Null when nothing has reached a terminal state at all — not `0%`. */
  successRate: z.number().nullable(),
});
export type DeliveryView = z.infer<typeof deliveryViewSchema>;

/**
 * `GET /api/ops/pulse` — the whole deployment in one round trip. It takes NO window: it is
 * the state of the record as a whole, so it must not be captioned with the page's period.
 */
export const pulseViewSchema = z.object({
  delivery: deliveryViewSchema,
  latency: latencyViewSchema,
  failures: z.array(failureViewSchema),
  /** Travels inside the payload because none of the three above is readable without it. */
  capabilities: capabilitiesViewSchema,
});
export type PulseView = z.infer<typeof pulseViewSchema>;

/* `GET /api/ops/capabilities` publishes this same block on its own. The page does not read
   it: every capability flag it acts on rides on the `audience`, `finance` and `performance`
   payloads it already fetches, so a separate boot read would be one more request for numbers
   already on screen. The fetcher and its hook were deleted rather than left as dead code
   claiming, in a docstring, to run before anything is drawn. */

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const DASHBOARD_ENDPOINT = {
  audience: "GET /api/metrics/dashboard/audience",
  finance: "GET /api/metrics/dashboard/finance",
  performance: "GET /api/metrics/dashboard/performance",
  series: "GET /api/metrics/dashboard/series",
  vendor: "GET /api/metrics/dashboard/vendor",
  /** A state, not a section: no `?from=&to=` exists for it. `DASHBOARD_READ` like its siblings. */
  plans: "GET /api/metrics/plans",
  /** The one route here on `RECORDS_READ`, and the one that writes an audit row per call. */
  audienceLists: "GET /api/metrics/dashboard/audience-lists",
  pulse: "GET /api/ops/pulse",
  capabilities: "GET /api/ops/capabilities",
} as const;

/**
 * `?limit=` on the identified route, from the router's own bounds — the TIGHTER of each pair
 * the two database reads declare, so the boundary can never admit a value one of them would
 * clamp. Restated here so a caller refuses before the round trip: out of range is a 422, and a
 * 422 on this route is a request that disclosed nobody but still cost a failed read.
 *
 * The ceiling is what stops `?limit=100000` from turning a card into a bulk export of
 * customers, which on an unmasked payload is the difference in kind, not degree.
 */
export const MIN_AUDIENCE_LIST_LIMIT = 1;
export const MAX_AUDIENCE_LIST_LIMIT = 100;
export const DEFAULT_AUDIENCE_LIST_LIMIT = 10;

/**
 * The window a section is asked for, already RFC 3339. Both ends are sent: the server
 * accepts either alone, but a page with a period picker always knows both, and sending both
 * is what earns the `previous`/`change` arm on every `TrendView`.
 */
export interface DashboardWindow {
  readonly from: string;
  readonly to: string;
}

/** `?from=&to=`, in the order the server's own docstrings write them. */
function windowQuery(window: DashboardWindow): string {
  return new URLSearchParams({ from: window.from, to: window.to }).toString();
}

/** Population, sign-ups, activity, and both kinds of block. */
export function audience(
  window: DashboardWindow,
  signal?: AbortSignal,
): Promise<ApiResult<AudienceResponse>> {
  return request({
    endpoint: DASHBOARD_ENDPOINT.audience,
    path: `${METRICS_PREFIX}/dashboard/audience?${windowQuery(window)}`,
    schema: audienceResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** What came in, what went out, and what is left at each vendor. */
export function finance(
  window: DashboardWindow,
  signal?: AbortSignal,
): Promise<ApiResult<FinanceResponse>> {
  return request({
    endpoint: DASHBOARD_ENDPOINT.finance,
    path: `${METRICS_PREFIX}/dashboard/finance?${windowQuery(window)}`,
    schema: financeResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** How fast, how reliably, where orders stand, and what is up. */
export function performance(
  window: DashboardWindow,
  signal?: AbortSignal,
): Promise<ApiResult<PerformanceResponse>> {
  return request({
    endpoint: DASHBOARD_ENDPOINT.performance,
    path: `${METRICS_PREFIX}/dashboard/performance?${windowQuery(window)}`,
    schema: performanceResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Every chart on the page, at the grain asked for.
 *
 * A grain the window cannot honestly serve is a 422 naming `bucket` (`INVALID_INPUT`), not a
 * silent coarsening: `bucket=hour` needs a lower bound and a window under eight days, and no
 * grain may exceed 750 points. `bucketFor` in `features/dashboard/window.ts` is what keeps
 * the page on the right side of those.
 */
export function series(
  window: DashboardWindow,
  bucket: SeriesBucket,
  signal?: AbortSignal,
): Promise<ApiResult<SeriesResponse>> {
  const query = new URLSearchParams({ from: window.from, to: window.to, bucket });
  return request({
    endpoint: DASHBOARD_ENDPOINT.series,
    path: `${METRICS_PREFIX}/dashboard/series?${query.toString()}`,
    schema: seriesResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * Which vendor the money went to, in what units, and how each figure was arrived at.
 *
 * Its own request rather than three more fields on `finance`, and on its own cadence: spend
 * moves slower than the audience counters. `vendorSpend` and `vendorBalances` come back
 * identical to the finance response's fields of the same name over the same window — that is
 * the contract, so a disagreement between the two cards is a bug in one of them and never a
 * second, differently-computed figure.
 */
export function vendor(
  window: DashboardWindow,
  signal?: AbortSignal,
): Promise<ApiResult<VendorResponse>> {
  return request({
    endpoint: DASHBOARD_ENDPOINT.vendor,
    path: `${METRICS_PREFIX}/dashboard/vendor?${windowQuery(window)}`,
    schema: vendorResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * What the running plans owe, and how fully the ended ones were used.
 *
 * **No window, so this fetcher takes none** — liability is a state, and the signature is where
 * wiring the page's range picker to it is made impossible rather than merely discouraged. The
 * response's own `asOf` is the instant both halves were computed at, and every caller must
 * print it: without it the figure reads as obeying whatever period the picker shows.
 */
export function plans(signal?: AbortSignal): Promise<ApiResult<PlanLiabilityResponse>> {
  return request({
    endpoint: DASHBOARD_ENDPOINT.plans,
    path: `${METRICS_PREFIX}/plans`,
    schema: planLiabilityResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * The two IDENTIFIED lists. `RECORDS_READ`, audited, unmasked — read the section comment on
 * `audienceListsResponseSchema` before calling this.
 *
 * **`window` narrows the top generators and NOTHING else**, which is why the parameter is
 * named for the block it applies to rather than taken as this fetcher's window. The
 * `recentSubscribers` half is a RECENCY list: the route accepts no parameter that would filter
 * it, the response carries no window field on it, and its caption is "the last N" and never
 * "this week". A caller with the page's range picker in hand should be unable to wire it to
 * that half by accident, and the signature is where that is made hard.
 *
 * `limit` applies to BOTH lists and is bounded server-side; passing one outside
 * `MIN_AUDIENCE_LIST_LIMIT`..`MAX_AUDIENCE_LIST_LIMIT` is a 422 naming the parameter.
 *
 * **Every call writes an audit row**, so this is not a poll. Give it a long `staleTime` and no
 * `refetchInterval`, or the log fills with disclosures nobody made — and because the
 * permission differs from the rest of the page, give it its own query, so a 403 renders in
 * this section alone rather than blanking the aggregates beside it.
 */
export function audienceLists(
  topGeneratorsWindow: DashboardWindow,
  limit: number = DEFAULT_AUDIENCE_LIST_LIMIT,
  signal?: AbortSignal,
): Promise<ApiResult<AudienceListsResponse>> {
  const query = new URLSearchParams({
    from: topGeneratorsWindow.from,
    to: topGeneratorsWindow.to,
    limit: String(limit),
  });
  return request({
    endpoint: DASHBOARD_ENDPOINT.audienceLists,
    path: `${METRICS_PREFIX}/dashboard/audience-lists?${query.toString()}`,
    schema: audienceListsResponseSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/** The deployment as a whole. The route takes no window, so there is none to pass. */
export function pulse(signal?: AbortSignal): Promise<ApiResult<PulseView>> {
  return request({
    endpoint: DASHBOARD_ENDPOINT.pulse,
    path: `${OPS_PREFIX}/pulse`,
    schema: pulseViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

