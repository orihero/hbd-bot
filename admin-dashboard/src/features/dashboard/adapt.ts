/**
 * Wire shapes → the strings and arrays the cards and charts draw. Pure: no React, no fetch,
 * no clock read, so every rule below is testable and every number on the page is traceable
 * to one line here.
 *
 * THE ONE RULE THIS MODULE EXISTS TO ENFORCE: a null on the wire never becomes a number.
 * `CardValue` is a union, and the absent arm is `{ tag }` — the mockup's hatched pill. A
 * null is "not instrumented", "not priced", "no comparable period"; rendering it as `0`,
 * `$0.00` or a bare em-dash turns a missing measurement into a believed one, and this page
 * is read by somebody deciding whether the business is working.
 *
 * FORMATTING LIVES HERE AND NOWHERE ELSE. The components take strings.
 */

import type {
  AbsenceReason,
  AudienceListsResponse,
  AudienceResponse,
  ComponentState,
  CostSplitView,
  ComponentStatusView,
  CountPointView,
  FinanceResponse,
  MoneyPointView,
  OrderFunnelView,
  OrderState,
  PerformanceResponse,
  PlanLiabilityResponse,
  PulseView,
  RatioView,
  RecentSubscribersView,
  SeriesBucket,
  SeriesResponse,
  SpendPointView,
  TopGeneratorsView,
  Vendor,
  VendorBalanceView,
  VendorCostPerSongView,
  VendorOperation,
  VendorResponse,
  VendorUnitsPerSongView,
  WindowView,
} from "@/api/dashboard";
import type { CardKey } from "@/features/dashboard/cardSpecs";
import type { ChurnCardProps } from "@/features/dashboard/ChurnCard";
import type { VendorCardsProps } from "@/features/dashboard/VendorCards";
/* `BALANCE_STALE_MS`, `ageLabel` and `parseInstant` live in `svg.ts` beside `thresholdOf`,
   not here: the header's balance chip below and the two vendor-health figures each reach the
   verdict "this reading is too old" independently, and a second copy of the cutoff is how a
   chip comes to call a figure stale while the meter beside it paints it green. */
import {
  BALANCE_STALE_MS,
  COST_SPLIT_LANE,
  VENDOR_LABEL,
  ageLabel,
  niceStep,
  parseInstant,
  thresholdLabel,
  thresholdOf,
  type ThresholdState,
} from "@/features/dashboard/svg";
import type { Period } from "@/features/dashboard/window";

/* The eleven new figures declared their props against the wire, so the adapters at the foot of
   this file return the components' OWN interfaces rather than re-declared copies: a prop that
   changes shape then breaks the wiring at compile time instead of at a glance on the page.
   Every one of these is `import type` and therefore erased — those modules import `formatCount`
   and friends back from here at runtime, and a value import in this direction would close a
   module cycle. */
import type { ActiveAccountsProps } from "@/features/dashboard/charts/ActiveAccounts";
import type { CostProvenanceProps } from "@/features/dashboard/charts/CostProvenance";
import type { LanguageMixProps } from "@/features/dashboard/charts/LanguageMix";
import type {
  PlanLiabilityAmount,
  PlanLiabilityProps,
} from "@/features/dashboard/charts/PlanLiability";
import type { PlanUtilisationProps } from "@/features/dashboard/charts/PlanUtilisation";
import type { PollerFreshnessProps } from "@/features/dashboard/charts/PollerFreshness";
import type { VendorBalanceMetersProps } from "@/features/dashboard/charts/VendorBalanceMeters";
import type { VendorUnitsProps } from "@/features/dashboard/charts/VendorUnits";

/* -------------------------------------------------------------------------- */
/* What a card is                                                              */
/* -------------------------------------------------------------------------- */

/**
 * One dot on the System status strip.
 *
 * The STATE travels, not a boolean: `degraded` is "we asked and the vendor refused" and
 * `not_probed` is "nothing has ever looked", and collapsing the pair to "not ok" made every
 * fault hover as the more benign of the two. `id` is the raw component string plus its
 * position — the server can emit one `component` twice (two adapters of one vendor), and a
 * strip keyed by its display label reconciles the wrong dot.
 */
export type StatDot = readonly [id: string, label: string, state: ComponentState];

/**
 * A card that has a number, and a card that does not. The second arm carries only the pill
 * copy, because there is nothing else honest to put in the value slot.
 *
 * `sub`, `unit` and `dots` are OVERRIDES of the `CardSpec` defaults: an adapter sets `sub`
 * when the response knows a truer caption than the mock's generic one, `unit` when the wire
 * quotes a currency the spec did not assume, and `dots` for the one card that draws a strip.
 */
export type CardValue =
  | {
      readonly value: string;
      readonly delta: string;
      readonly sub?: string;
      readonly unit?: string;
      readonly dots?: readonly StatDot[];
      readonly spark?: readonly number[];
    }
  | { readonly tag: string };

/** A section's contribution. The page spreads the four together into one lookup. */
export type CardValues = Readonly<Partial<Record<CardKey, CardValue>>>;

/** Mutable while an adapter fills it; handed out as `CardValues`. */
type Draft = Record<string, CardValue>;

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The mockup groups thousands with a PLAIN space — `1 842`, `12 800`, `98 000` are all
 * U+0020 in `dashboard-mockup.html`, verified byte by byte, not a thin or narrow one. Every
 * value slot is `whitespace-nowrap`, so it cannot break across the gap.
 */
const GROUP = " ";

/** Uzbek soʻm takes U+02BB (turned comma), which is what the mockup's header holds. */
const SOM = "soʻm";

function groupString(digits: string): string {
  let out = "";
  for (let i = 0; i < digits.length; i += 1) {
    const fromEnd = digits.length - i;
    out += digits.charAt(i);
    if (fromEnd > 1 && fromEnd % 3 === 1) out += GROUP;
  }
  return out;
}

/** A count, grouped the mockup's way. */
export function formatCount(n: number): string {
  const rounded = Math.round(Math.abs(n));
  return (n < 0 ? "-" : "") + groupString(String(rounded));
}

/** Three significant figures, trailing zeros trimmed: 2.828 → `2.83`, 19.9 → `19.9`. */
function significant(v: number): string {
  const s = v.toPrecision(3);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

/**
 * Soʻm from MINOR units (tiyin — `single_song_price_minor` is 700_000 for a 7 000 soʻm song).
 * Under a million the mockup groups in full (`98 000`); at and above it shortens (`1.66M`).
 */
export function formatSom(minor: number): string {
  const som = minor / 100;
  return Math.abs(som) >= 1e6 ? `${significant(som / 1e6)}M` : formatCount(som);
}

/** `$3.47`, `$0.25`, `$1 204.10`. Always two decimals — a dollar figure that is a dollar. */
export function formatUsd(v: number): string {
  const fixed = Math.abs(v).toFixed(2);
  const dot = fixed.indexOf(".");
  const whole = groupString(fixed.slice(0, dot));
  return `${v < 0 ? "-" : ""}$${whole}.${fixed.slice(dot + 1)}`;
}

/**
 * Currencies whose minor unit is NOT a hundredth. `currency` is free-form ISO 4217 "as the
 * receipts recorded it" and the schema warns "Today always UZS; never assume it", so a fixed
 * ÷100 would render a yen receipt at a hundredth of its value under its own code.
 */
const MINOR_EXPONENT: Record<string, number> = {
  JPY: 0,
  KRW: 0,
  VND: 0,
  CLP: 0,
  ISK: 0,
  BIF: 0,
  DJF: 0,
  GNF: 0,
  KMF: 0,
  PYG: 0,
  RWF: 0,
  UGX: 0,
  VUV: 0,
  XAF: 0,
  XOF: 0,
  XPF: 0,
  BHD: 3,
  IQD: 3,
  JOD: 3,
  KWD: 3,
  LYD: 3,
  OMR: 3,
  TND: 3,
};

/** 2 is the ISO default and UZS tiyin's own; anything else is named above. */
function minorExponent(currency: string): number {
  return MINOR_EXPONENT[currency] ?? 2;
}

/**
 * Major units, printed with the number of decimals that currency HAS — `19.99 USD`, `2 300
 * JPY`, `1.250 KWD`.
 *
 * Rounding to whole units would have quoted a $19.99 plan as `20 USD`, which is a different
 * amount from the one on the receipt. Soʻm is the exception and does not come through here:
 * the deployment's own currency is quoted in whole soʻm by the mockup, and tiyin are not a
 * unit anybody transacts in.
 */
function formatMajor(minor: number, currency: string): string {
  const exponent = minorExponent(currency);
  const major = minor / 10 ** exponent;
  if (exponent === 0) return formatCount(major);
  const fixed = Math.abs(major).toFixed(exponent);
  const dot = fixed.indexOf(".");
  return `${major < 0 ? "-" : ""}${groupString(fixed.slice(0, dot))}.${fixed.slice(dot + 1)}`;
}

/**
 * Minor units in whatever currency the wire quoted. UZS is the deployment's, and the only
 * one the mock's `soʻm` unit label is true for; anything else carries its ISO code instead.
 *
 * EXPORTED, and it must stay exported: `RecentSubscribers` prints receipts in whatever
 * currency they were recorded in, and the alternative to reaching this function is a second
 * copy of `MINOR_EXPONENT` above — two tables that would eventually disagree about a currency
 * and quote a receipt at a hundredth or a hundred times what the customer actually paid.
 */
export function money(
  minor: number,
  currency: string,
): { readonly value: string; readonly unit: string } {
  return currency === "UZS"
    ? { value: formatSom(minor), unit: SOM }
    : { value: formatMajor(minor, currency), unit: currency };
}

function pad2(n: number): string {
  return n < 10 ? `0${String(n)}` : String(n);
}

/** `48s`, `4m 12s`, `4m 05s`, `1h 04m`. The mockup's own idiom, zero-padded remainders. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${String(total)}s`;
  if (total < 3600) return `${String(Math.floor(total / 60))}m ${pad2(total % 60)}s`;
  return `${String(Math.floor(total / 3600))}h ${pad2(Math.floor((total % 3600) / 60))}m`;
}

/**
 * An INSTANT, in the viewer's own zone — `9 Sep 2026, 14:32`.
 *
 * The same `Intl` shape `RecentSubscribers` stamps its receipts with, so the plan book's
 * `asOf` and the subscriber list's `purchasedAt` cannot read as two different kinds of clock.
 *
 * An unparseable stamp comes back VERBATIM rather than as a dash or an empty string: the wire
 * said something, this module could not read it, and printing the raw text is what lets an
 * operator report the drift instead of wondering which figure lost its date.
 */
const INSTANT = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function formatInstant(iso: string): string {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? iso : INSTANT.format(new Date(ms));
}

/** The coarse form the mockup uses for a p95 inside a caption: `p95 11m`. */
export function formatDurationCoarse(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${String(total)}s`;
  if (total < 3600) return `${String(Math.round(total / 60))}m`;
  return `${String(Math.floor(total / 3600))}h ${pad2(Math.floor((total % 3600) / 60))}m`;
}

/**
 * The delta chip, from the change the SERVER computed over the same scan — never from two
 * responses differenced in the browser, which would compare two different windows.
 *
 * A null change is the empty string and the chip disappears. It means "no comparable prior
 * period" (or a previous of zero, which has no quotient), and `0%` would be a claim.
 *
 * The sign is an ASCII hyphen because `dirOf` in svg.ts reads `charAt(0) === "-"` to colour
 * it; a typographic minus would silently make every fall read as a rise.
 */
export function formatDelta(change: RatioView | null): string {
  if (change === null || change.value === null) return "";
  const pct = change.value * 100;
  const magnitude = Math.abs(pct);
  const shown =
    magnitude < 10
      ? String(Math.round(magnitude * 10) / 10)
      : String(Math.round(magnitude));
  return `${pct < 0 ? "-" : "+"}${shown}%`;
}

/* -------------------------------------------------------------------------- */
/* Absence                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Pill copy per reason. The mock only ever drew three pills ("not tracked", "not polled",
 * "needs balances"); the rest are the same voice — lowercase, four words at most, naming
 * which KIND of missing this is, because "—" makes the operator guess.
 */
const REASON_TAG: Record<AbsenceReason, string> = {
  no_fx_rate: "no fx rate",
  no_price_published: "no price published",
  mixed_currencies: "mixed currencies",
  not_priced: "not priced",
  no_denominator: "no denominator",
  not_instrumented: "not tracked",
};

function tag(reason: AbsenceReason | null, fallback: string): CardValue {
  return { tag: reason === null ? fallback : REASON_TAG[reason] };
}

/* -------------------------------------------------------------------------- */
/* Audience                                                                    */
/* -------------------------------------------------------------------------- */

/** How the three nested activity cutoffs are captioned, and which one a period asks for. */
const ACTIVE_WINDOW: Record<Period, { readonly key: "day" | "week" | "month"; readonly label: string }> = {
  today: { key: "day", label: "24h" },
  week: { key: "week", label: "7d" },
  // A year has no cutoff of its own: thirty days is the coarsest the wire measures, and the
  // caption says so rather than letting a month masquerade as a year.
  month: { key: "month", label: "30d" },
  year: { key: "month", label: "30d" },
};

/**
 * The five Audience cards.
 *
 * `period` only reaches the Active-users card: DAU/WAU/MAU are three cutoffs against one
 * instant and do not move with the request window, so the card has to pick the one the
 * picker is asking about instead of re-fetching.
 */
export function adaptAudience(r: AudienceResponse, period: Period = "today"): CardValues {
  const out: Draft = {};

  out["totalUsers"] = {
    value: formatCount(r.totalAccounts.current),
    delta: formatDelta(r.totalAccounts.change),
  };

  out["newUsers"] = {
    value: formatCount(r.newAccounts.current),
    delta: formatDelta(r.newAccounts.change),
  };

  /* `activeAccounts` is a LIVE count over `users.last_seen_at` and answers from day one —
     `isActivityHistory` is a different capability, saying only whether the nightly snapshot
     job has written a HISTORICAL series (which this card does not draw). Gating the figure on
     it printed "not tracked" over a real measurement, which is the exact inversion the
     server's own comment warns about; the flag is read only to caption the missing history. */
  const active = ACTIVE_WINDOW[period];
  out["activeUsers"] = {
    value: formatCount(r.activeAccounts[active.key]),
    delta: "",
    sub: r.isActivityHistory
      ? `active in the last ${active.label}`
      : `last ${active.label} · no history kept`,
  };

  // Null churn is "never watched". `{blocked: 0}` would be "nobody left", which is a result.
  out["churn"] =
    r.churn === null || !r.isChurnInstrumented
      ? { tag: "not tracked" }
      : {
          value: formatCount(r.churn.blocked.current),
          delta: formatDelta(r.churn.blocked.change),
          sub: `${formatCount(r.botBlockedAccounts)} still blocking`,
        };

  out["barred"] = { value: formatCount(r.blockedAccounts), delta: "" };

  return out;
}

/* -------------------------------------------------------------------------- */
/* Finance                                                                     */
/* -------------------------------------------------------------------------- */

/** Days a window spans, for the run-rate captions. Null when it has no lower bound. */
function windowDays(w: WindowView): number | null {
  if (w.from === null) return null;
  const from = Date.parse(w.from);
  const to = Date.parse(w.to);
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return Math.max(1, Math.round((to - from) / 86_400_000));
}

/** What a balance estimate is worth, said in the caption — a TTS figure is an upper bound. */
const BASIS_CAPTION = {
  trailing_spend_usd: "est. from trailing spend",
  trailing_tts_characters: "upper bound · TTS characters",
} as const;

/** The four money cards plus the run-rate pair and the two balance cards. */
export function adaptFinance(r: FinanceResponse): CardValues {
  const out: Draft = {};

  /* Total revenue is the ESTIMATE (delivered × published price), which is what the mock's
     "delivered × 7 000 soʻm" caption describes. Recorded receipts live in `r.revenue` and
     are never added to it. No trend on this wire, so no delta rather than a fabricated one. */
  const derived = r.derivedRevenue;
  if (derived.amountMinor === null || derived.currency === null || derived.unitPriceMinor === null) {
    out["totalRevenue"] = tag(derived.unavailableReason, "no price published");
  } else {
    const amount = money(derived.amountMinor, derived.currency);
    const price = money(derived.unitPriceMinor, derived.currency);
    out["totalRevenue"] = {
      value: amount.value,
      unit: amount.unit,
      delta: "",
      sub: `${formatCount(derived.deliveredSongs)} × ${price.value} ${price.unit}`,
    };
  }

  const topups = r.unpricedTopups;
  out["topups"] = {
    value: formatCount(topups.priced + topups.unpriced),
    delta: "",
    sub:
      topups.unpriced === 0
        ? `${formatCount(topups.priced)} with amounts`
        : topups.priced === 0
          ? "amount never recorded"
          : `${formatCount(topups.unpriced)} without an amount`,
  };

  const spend = r.vendorSpend;
  /* The fake-provider guard rides on the caption when it fires: every figure here excludes
     those rows structurally, and the pair exists on the wire to make the exclusion visible —
     a window dominated by fake runs otherwise reads as real traffic. */
  const fake =
    r.fakeCalls.fakeCalls > 0 ? ` · ${formatCount(r.fakeCalls.fakeCalls)} fake, excluded` : "";
  out["vendorSpend"] =
    spend.amountUsd === null
      ? tag(spend.unavailableReason, "not tracked")
      : {
          value: formatUsd(spend.amountUsd),
          delta: "",
          sub:
            (spend.costedCalls === spend.calls
              ? `${formatCount(spend.calls)} vendor calls, all priced`
              : `${formatCount(spend.costedCalls)} of ${formatCount(spend.calls)} calls priced`) +
            fake,
        };

  const cps = r.costPerSong;
  const perSong = cps.perSongUsd;
  out["costPerSong"] =
    perSong === null || perSong.value === null
      ? tag(cps.cost.unavailableReason ?? (cps.deliveredOrders === 0 ? "no_denominator" : null), "not tracked")
      : {
          value: formatUsd(perSong.value),
          delta: "",
          sub:
            cps.attributedOrders === cps.deliveredOrders
              ? `${formatCount(cps.deliveredOrders)} delivered, all attributed`
              : `${formatCount(cps.attributedOrders)} of ${formatCount(cps.deliveredOrders)} attributed`,
        };

  /* The run-rate pair is computed over its OWN fixed trailing window, echoed on the
     response. The caption says which, so the card cannot be read as belonging to the period
     picker above it, and ARR is the server's `net × 365 ÷ days` — not MRR × 12. */
  const net = r.netRunRate;
  const days = windowDays(net.window);
  const span = days === null ? "trailing window" : `${String(days)}d`;
  if (net.netMinor === null || net.currency === null) {
    out["mrr"] = tag(net.unavailableReason, "not priced");
  } else {
    const m = money(net.netMinor, net.currency);
    out["mrr"] = { value: m.value, unit: m.unit, delta: "", sub: `revenue − cost, ${span}` };
  }
  if (net.annualisedMinor === null || net.currency === null) {
    out["arr"] = tag(net.unavailableReason, "not priced");
  } else {
    const m = money(net.annualisedMinor, net.currency);
    out["arr"] = { value: m.value, unit: m.unit, delta: "", sub: `net × 365 ÷ ${span}` };
  }

  /* The response's own upper bound is the only clock this module may read — it is the instant
     the server counted to, and it is what a cached balance's age is measured against. */
  const asOf = r.window === null ? null : parseInstant(r.window.to);
  out["vendorBalance"] = adaptVendorBalance(r.vendorBalances, asOf);
  out["songsRemaining"] = adaptSongsRemaining(r.vendorBalances);

  return out;
}

/**
 * One vendor's balance, sized for the header rather than for a card.
 *
 * `isMeasured` is what the header colours on. It is FALSE for every arm that has no figure —
 * uncapped, never answered, stale — because those four states have exactly one thing in
 * common that matters at a glance: there is no number here to plan against. The distinction
 * between them survives in `value` and in `title`, which is where an operator who wants the
 * reason goes.
 */
export interface BalanceChip {
  /** Stable across renders and unique per row: two OpenRouter keys are two chips. */
  readonly key: string;
  /** `ELEVENLABS`, or `OPENROUTER fallback` for the second key of a pair. */
  readonly vendor: string;
  /** `112.6k chars`, `$0.93`, or the reason there is no figure. */
  readonly value: string;
  readonly isMeasured: boolean;
  /** The long form — poll age, last-poll outcome, error code. Never load-bearing. */
  readonly title: string;
  /** The wire's own vendor, for the surface that draws a MARK where the word would be. */
  readonly vendorKey: Vendor;
  /** The second key of a pair. Two OpenRouter chips carry one logo and differ only here. */
  readonly isFallback: boolean;
  /**
   * Remaining as a fraction of the pool, `0..1`, or `null` when there is no denominator.
   *
   * `null` is the common case rather than the exception and must not render as `0`: an
   * uncapped key, a vendor that reported no total, a stale figure and a poll that never
   * answered all land here, and "we cannot say what fraction is left" is a different
   * statement from "none is left". Only a row that is BOTH measured and bounded gets a
   * number — the same rule the value beside it already obeys.
   */
  readonly pct: number | null;
}

/**
 * Remaining over total, clamped, or `null` when the pair cannot state a fraction.
 *
 * The clamp is not defensive noise: OpenRouter permits a small overdraft, so a live account
 * can report `used > total`, and a ring drawn from a negative fraction sweeps the wrong way
 * round the circle — which reads as a FULL account, the most expensive possible misreading of
 * an empty one.
 */
function remainingFraction(remaining: number | null, total: number | null): number | null {
  if (remaining === null || total === null || total <= 0) return null;
  return Math.min(1, Math.max(0, remaining / total));
}

/** `68% left`, for the hover. Rounded to whole points: a balance ring is not a gauge. */
export function percentLabel(pct: number): string {
  return `${String(Math.round(pct * 100))}% left`;
}

/**
 * EVERY polled vendor, in the order the server returned them.
 *
 * This is the whole difference from `adaptVendorBalance`, which answers a single card and so
 * has to choose one row — `balances.find((b) => b.remaining !== null)`. That `find` is why a
 * deployment polling ElevenLabs and OpenRouter showed one balance and looked complete: the
 * second row was never wrong, it was never rendered. A header that names the vendor on each
 * chip has no reason to choose, so it does not.
 *
 * A row with no figure still gets a chip. Dropping it would restore the same silence in a new
 * place — "OpenRouter is absent" and "OpenRouter answered uncapped" would look identical.
 */
export function adaptBalanceChips(
  balances: readonly VendorBalanceView[],
  asOfMs: number | null,
): readonly BalanceChip[] {
  return balances.map((b) => {
    const label = VENDOR_LABEL[b.vendor];
    const vendor = b.isFallback ? `${label} fallback` : label;
    const key = `${b.vendor}:${b.provider}:${String(b.isFallback)}`;
    const fetched = b.fetchedAt === null ? null : parseInstant(b.fetchedAt);
    const ageMs = fetched === null || asOfMs === null ? null : Math.max(0, asOfMs - fetched);
    const failing =
      b.consecutiveFailures > 0
        ? ` · ${String(b.consecutiveFailures)} failed poll${b.consecutiveFailures === 1 ? "" : "s"}`
        : "";
    const reason = b.errorCode === null ? "" : ` · ${b.errorCode}`;

    // Carried by every arm below, measured or not: which account a chip belongs to is
    // configuration, and it is known even when nothing about the balance is.
    const identity = { key, vendor, vendorKey: b.vendor, isFallback: b.isFallback } as const;

    if (b.isUnbounded === true) {
      return {
        ...identity,
        value: "uncapped",
        isMeasured: false,
        pct: null,
        title: `${vendor}: the key reports no cap, so there is no balance to show.${failing}`,
      };
    }
    if (b.remaining === null || b.fetchedAt === null) {
      return {
        ...identity,
        value: b.fetchedAt === null ? "never answered" : "not reported",
        isMeasured: false,
        pct: null,
        title: `${vendor}: polled, but no figure came back.${reason}${failing}`,
      };
    }
    if (ageMs !== null && ageMs > BALANCE_STALE_MS) {
      return {
        ...identity,
        value: `${ageLabel(ageMs)} stale`,
        isMeasured: false,
        pct: null,
        title: `${vendor}: last answered ${ageLabel(ageMs)} ago, too old to plan against.${failing}`,
      };
    }

    const figure =
      b.unit === "usd" ? formatUsd(b.remaining) : `${formatCount(b.remaining)} chars`;
    const age = ageMs === null ? "" : ` · ${ageLabel(ageMs)} old`;
    const ok = b.isLastPollOk ? "" : " · last poll failed";
    const pct = remainingFraction(b.remaining, b.total);
    // The fraction goes in the title as well as on the ring, because a ring is a picture and
    // an operator reporting a number to somebody else needs the number.
    const share = pct === null ? "" : ` · ${percentLabel(pct)}`;
    return {
      ...identity,
      value: figure,
      isMeasured: true,
      pct,
      title: `${vendor}: ${figure} remaining${share}${age}${ok}${failing}${reason}`,
    };
  });
}

/** The header's chips straight from a finance response — the caller the page actually uses. */
export function financeBalanceChips(r: FinanceResponse): readonly BalanceChip[] {
  // The SAME `as of` clock the `vendorBalance` card is aged against (see `adaptFinance`), so
  // the header and the card can never disagree about whether a figure is stale.
  return adaptBalanceChips(r.vendorBalances, r.window === null ? null : parseInstant(r.window.to));
}

/**
 * An empty balance list is the mockup's "not polled" pill — never "zero credit left".
 *
 * TWO CLOCKS ride on every row and staleness is measured against `fetchedAt`, the last
 * ANSWER, not `checkedAt`, the last ASK: a failed poll leaves the last good numbers in place
 * with `isLastPollOk` still true if it never got to ask at all. The age is therefore part of
 * the figure, and an old enough one is a pill rather than a number.
 */
function adaptVendorBalance(
  balances: readonly VendorBalanceView[],
  asOfMs: number | null,
): CardValue {
  if (balances.length === 0) return { tag: "not polled" };

  const reported = balances.find((b) => b.remaining !== null);
  if (reported === undefined) {
    // A vendor that answered "uncapped" has no figure to want; one that answered nothing has
    // not been read yet. Two different silences, two different pills.
    return balances.some((b) => b.isUnbounded === true)
      ? { tag: "uncapped key" }
      : { tag: "not reported" };
  }

  // Never successfully answered: the numbers on the row are whatever the cache was seeded
  // with, and no age can be quoted for them.
  if (reported.fetchedAt === null) return { tag: "never answered" };

  const fetched = parseInstant(reported.fetchedAt);
  const ageMs = fetched === null || asOfMs === null ? null : Math.max(0, asOfMs - fetched);
  if (ageMs !== null && ageMs > BALANCE_STALE_MS) return { tag: `${ageLabel(ageMs)} stale` };

  const remaining = reported.remaining ?? 0;
  const label = VENDOR_LABEL[reported.vendor].toLowerCase();
  const source = reported.isFallback ? `${label} fallback` : label;
  const failed = reported.isLastPollOk ? "" : " · last poll failed";
  const age = ageMs === null ? "" : ` · ${ageLabel(ageMs)} old`;
  const sub = `${source}${failed}${age}`;
  return reported.unit === "usd"
    ? { value: formatUsd(remaining), delta: "", sub }
    : { value: formatCount(remaining), unit: "chars", delta: "", sub };
}

/**
 * The SMALLEST estimate across the vendors that gave one: the vendor that runs out first is
 * what the deployment can actually deliver, and summing estimates in different units (dollars
 * against TTS characters) would produce a number that means nothing.
 */
function adaptSongsRemaining(balances: readonly VendorBalanceView[]): CardValue {
  let best: VendorBalanceView | null = null;
  for (const b of balances) {
    if (b.songsRemaining === null) continue;
    if (best === null || b.songsRemaining < (best.songsRemaining ?? 0)) best = b;
  }
  if (best === null || best.songsRemaining === null) return { tag: "needs balances" };
  const basis = best.estimateBasis === null ? "estimate" : BASIS_CAPTION[best.estimateBasis];
  return {
    value: formatCount(best.songsRemaining),
    delta: "",
    sub: `${VENDOR_LABEL[best.vendor].toLowerCase()} · ${basis}`,
  };
}

/* -------------------------------------------------------------------------- */
/* Performance                                                                 */
/* -------------------------------------------------------------------------- */

/** Machine component names → the strip's tooltips. Vendors keep their own casing. */
const COMPONENT_LABEL: Record<string, string> = {
  vendor_usage: "Vendor usage",
  vendor_cost: "Vendor cost",
  churn: "Churn",
  activity_history: "Activity history",
  plan_revenue: "Plan revenue",
  topup_revenue: "Top-up revenue",
  balance_poller: "Balance poller",
  elevenlabs: "ElevenLabs",
  elevenlabs_fallback: "ElevenLabs (fallback)",
  openrouter: "OpenRouter",
  openrouter_fallback: "OpenRouter (fallback)",
  gemini: "Gemini",
  gemini_fallback: "Gemini (fallback)",
  openai_compatible: "OpenAI-compatible",
  fake: "Fake vendor",
};

function componentLabel(component: string): string {
  const known = COMPONENT_LABEL[component];
  if (known !== undefined) return known;
  const spaced = component.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The five Performance cards.
 *
 * `pulse` is the whole record with no window, and is used for exactly one thing: telling the
 * two reasons a median can be missing apart. "Nothing delivered in this period" and "nothing
 * has ever been delivered" are different sentences, and only the second is a deployment
 * somebody needs to look at. It is never substituted INTO the windowed figure.
 */
export function adaptPerformance(r: PerformanceResponse, pulse: PulseView | null): CardValues {
  const out: Draft = {};

  const latency = r.deliveryLatency;
  if (latency.p50Seconds === null) {
    out["medianSongTime"] =
      pulse !== null && pulse.latency.sampleCount === 0
        ? { tag: "never delivered" }
        : { tag: "none this period" };
  } else {
    const p95 =
      latency.p95Seconds === null ? "" : `p95 ${formatDurationCoarse(latency.p95Seconds)} · `;
    out["medianSongTime"] = {
      value: formatDuration(latency.p50Seconds),
      delta: "",
      sub: `${p95}${formatCount(latency.sampleCount)} songs`,
    };
  }

  out["songsDelivered"] = {
    value: formatCount(r.deliveredOrders.current),
    delta: formatDelta(r.deliveredOrders.change),
  };

  const music = r.musicRenderLatency;
  out["musicRenders"] = {
    value: formatCount(music.calls),
    delta: "",
    sub:
      music.measuredCalls === music.calls
        ? "vendor calls, includes retries"
        : `${formatCount(music.calls - music.measuredCalls)} of ${formatCount(music.calls)} unmeasured`,
  };

  if (music.p50Ms === null) {
    out["musicRenderTime"] = { tag: "not measured" };
  } else {
    const p95 = music.p95Ms === null ? "" : `p95 ${formatDurationCoarse(music.p95Ms / 1000)} · `;
    out["musicRenderTime"] = {
      value: formatDuration(music.p50Ms / 1000),
      delta: "",
      sub: `${p95}${formatCount(music.sampleCount)} calls`,
    };
  }

  out["systemStatus"] = adaptSystemStatus(r.systemStatus);

  return out;
}

function adaptSystemStatus(strip: readonly ComponentStatusView[]): CardValue {
  if (strip.length === 0) return { tag: "not probed" };
  const ok = strip.filter((c) => c.state === "ok").length;
  const degraded = strip.filter((c) => c.state === "degraded").length;
  const unprobed = strip.length - ok - degraded;
  const parts: string[] = [];
  if (degraded > 0) parts.push(`${formatCount(degraded)} degraded`);
  if (unprobed > 0) parts.push(`${formatCount(unprobed)} not probed`);
  const sub = parts.length === 0 ? "all components probed" : parts.join(" · ");
  return {
    value: `${formatCount(ok)} / ${formatCount(strip.length)}`,
    delta: "",
    sub,
    // The index is part of the id and not decoration: `component` is the COARSE vendor, so a
    // deployment polling two adapters of one vendor emits the string twice.
    dots: strip.map(
      (c, i): StatDot => [`${c.component}-${String(i)}`, componentLabel(c.component), c.state],
    ),
  };
}

/* -------------------------------------------------------------------------- */
/* Charts                                                                      */
/* -------------------------------------------------------------------------- */

export interface CountSeriesData {
  readonly points: readonly number[];
  readonly ticks: readonly [string, string, string];
  /**
   * Whether each bucket is a Saturday or Sunday, from its own `startedAt`. EMPTY unless the
   * bucket is a day — the chart's "hollow = weekend" rule was `index % 7`, which is only true
   * of a series that happens to begin on a Monday.
   */
  readonly weekend: readonly boolean[];
}

export interface RevCostData {
  /** `null` at a bucket the series has no point for. Money is never zero-filled. */
  readonly revenue: readonly (number | null)[];
  readonly cost: readonly (number | null)[];
  readonly ticks: readonly string[];
  /** Why a whole series is missing, in the pill vocabulary. Null = it is drawn. */
  readonly revenueNote: string | null;
  readonly costNote: string | null;
}

export interface CostPerSongData {
  readonly values: readonly number[];
  readonly ticks: readonly string[];
  readonly priceLine: number | null;
}

export interface CostSplitRow {
  vendor: string;
  usd: number;
  ticks: number;
}

export interface CostSplitData {
  readonly rows: readonly CostSplitRow[];
  /** What one tick is worth, chosen per window so the tallest row fills the lane. */
  readonly tickUsd: number;
}

export interface FunnelStep {
  label: string;
  delta: number;
  /** An absolute column from zero rather than a drop off the running level. */
  total?: boolean;
}

export interface FunnelData {
  readonly unit: number;
  readonly steps: readonly FunnelStep[];
}

export interface ChartData {
  readonly signups: CountSeriesData;
  readonly delivered: CountSeriesData;
  readonly revCost: RevCostData;
  readonly costPerSong: CostPerSongData;
  readonly costSplit: CostSplitData;
  readonly funnel: FunnelData;
}

/** The mockup's rung charts are six columns wide, so the two of them take the last six. */
const RUNGS = 6;

const BUCKET_LETTER: Record<SeriesBucket, string> = {
  hour: "H",
  day: "D",
  week: "W",
  month: "M",
};

const BUCKET_NOW: Record<SeriesBucket, string> = {
  hour: "NOW",
  day: "TODAY",
  week: "THIS WK",
  month: "THIS MO",
};

const EMPTY_TICKS: readonly [string, string, string] = ["", "", ""];

const MONTH_LABEL: readonly string[] = [
  "JAN",
  "FEB",
  "MAR",
  "APR",
  "MAY",
  "JUN",
  "JUL",
  "AUG",
  "SEP",
  "OCT",
  "NOV",
  "DEC",
];

function hourLabel(startedAt: string): string {
  const at = new Date(startedAt);
  return Number.isNaN(at.getTime()) ? "" : `${pad2(at.getHours())}:00`;
}

function dayMonth(at: Date): string {
  return `${pad2(at.getDate())}/${pad2(at.getMonth() + 1)}`;
}

/** Monday of the calendar week `at` falls in — the key the server folds days into. */
function weekStart(at: Date): number {
  const day = new Date(at.getFullYear(), at.getMonth(), at.getDate());
  return day.getTime() - ((day.getDay() + 6) % 7) * 86_400_000;
}

/**
 * A bucket's OWN label, from the instant it started.
 *
 * The mockup's `D−2` idiom is only honest on a contiguous axis: money is never zero-filled,
 * so a bucket that survived a filter can be weeks from the one drawn beside it, and a
 * positional label would date a spike to a day it did not happen on. `TODAY` / `NOW` is
 * reserved for the bucket the reference instant actually falls in.
 */
function bucketLabel(atMs: number, bucket: SeriesBucket, nowMs: number | null): string {
  if (Number.isNaN(atMs)) return "";
  const at = new Date(atMs);
  const now = nowMs === null ? null : new Date(nowMs);
  const current =
    now === null
      ? false
      : bucket === "hour"
        ? at.getFullYear() === now.getFullYear() &&
          at.getMonth() === now.getMonth() &&
          at.getDate() === now.getDate() &&
          at.getHours() === now.getHours()
        : bucket === "day"
          ? at.toDateString() === now.toDateString()
          : bucket === "week"
            ? weekStart(at) === weekStart(now)
            : at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth();
  if (current) return BUCKET_NOW[bucket];
  if (bucket === "hour") return `${pad2(at.getHours())}:00`;
  if (bucket === "month") return MONTH_LABEL[at.getMonth()] ?? "";
  return dayMonth(at);
}

/**
 * First / middle / last, in the mockup's idiom: `−29D`, `−14D`, `TODAY`. The offsets are the
 * real ones — a point `k` buckets before the newest is labelled `−kD` — where the mock's
 * hand-written table was a bucket out.
 *
 * The `−kD` form is a claim that the axis is a contiguous run of buckets, which is exactly
 * what `isZeroFilled` reports: without it a missing bucket is missing, index distance is not
 * time, and each point is labelled with its own instant instead.
 */
function threeTicks(
  points: readonly CountPointView[],
  bucket: SeriesBucket,
  isDense: boolean,
  nowMs: number | null,
): readonly [string, string, string] {
  const n = points.length;
  if (n === 0) return EMPTY_TICKS;
  const at: readonly number[] = [0, Math.floor((n - 1) / 2), n - 1];
  const labels = at.map((index, slot) => {
    // A short series collapses two slots onto one point; blank the earlier one rather than
    // print the same label twice.
    if (slot > 0 && at[slot - 1] === index) return "";
    const point = points[index];
    if (point === undefined) return "";
    if (!isDense) return bucketLabel(Date.parse(point.startedAt), bucket, nowMs);
    if (bucket === "hour") return hourLabel(point.startedAt);
    const age = n - 1 - index;
    return age === 0 ? BUCKET_NOW[bucket] : `−${String(age)}${BUCKET_LETTER[bucket]}`;
  });
  return [labels[0] ?? "", labels[1] ?? "", labels[2] ?? ""];
}

interface BucketPoint {
  readonly key: string;
  readonly at: number;
  readonly value: number;
}

function ordered(map: ReadonlyMap<string, BucketPoint>): readonly BucketPoint[] {
  return [...map.values()].sort((a, b) => a.at - b.at);
}

function add(map: Map<string, BucketPoint>, key: string, startedAt: string, value: number): void {
  const seen = map.get(key);
  map.set(key, {
    key,
    at: seen?.at ?? Date.parse(startedAt),
    value: (seen?.value ?? 0) + value,
  });
}

/**
 * Recorded receipts per bucket, in minor units — but only when the window holds ONE
 * currency. `MoneyTotal` carries its currency precisely so a consumer cannot sum across it,
 * and a mixed-currency chart is a wrong number rather than a missing one.
 */
function revenueByBucket(points: readonly MoneyPointView[]): {
  readonly buckets: ReadonlyMap<string, BucketPoint>;
  readonly currency: string | null;
  readonly isMixed: boolean;
} {
  const currencies = new Set(points.map((p) => p.currency));
  // "More than one currency" and "no receipts at all" both used to collapse to an empty map
  // with a null currency, and the chart could then tell neither of them from the other.
  if (currencies.size > 1) return { buckets: new Map(), currency: null, isMixed: true };
  const buckets = new Map<string, BucketPoint>();
  for (const p of points) add(buckets, p.bucket, p.startedAt, p.amountMinor);
  return { buckets, currency: [...currencies][0] ?? null, isMixed: false };
}

/** Priced spend per bucket, in USD. A bucket whose calls were all unpriced is ABSENT. */
function spendByBucket(points: readonly SpendPointView[]): ReadonlyMap<string, BucketPoint> {
  const buckets = new Map<string, BucketPoint>();
  for (const p of points) {
    if (p.cost.amountUsd === null) continue;
    add(buckets, p.bucket, p.startedAt, p.cost.amountUsd);
  }
  return buckets;
}

function countByBucket(points: readonly CountPointView[]): ReadonlyMap<string, BucketPoint> {
  const buckets = new Map<string, BucketPoint>();
  for (const p of points) add(buckets, p.bucket, p.startedAt, p.count);
  return buckets;
}

/**
 * Revenue against cost, both in minor soʻm so the two lines share an axis.
 *
 * The conversion is the ONE place this module multiplies by an FX rate, and it is fenced the
 * way the server fences its own: no rate and the cost ladders are not drawn. But an ABSENT
 * ladder reads exactly like a window we spent nothing in, so the reason travels with it as a
 * note the chart prints — the same for revenue the module refuses to sum, which is receipts
 * in more than one currency (`MoneyTotal` carries a currency precisely so nobody adds across
 * it) or receipts quoted in something this soʻm axis cannot hold.
 *
 * The axis is the UNION of the two bucket sets, never their intersection: money is not
 * zero-filled, so a receipt at 10:00 and the vendor calls it paid for at 11:00 are different
 * buckets, and intersecting them dropped both series and captioned the window "no revenue or
 * priced cost". A series with no point for a bucket renders a GAP there.
 */
function adaptRevCost(
  r: SeriesResponse,
  uzsPerUsd: number | null,
  nowMs: number | null,
): RevCostData {
  const { buckets, currency, isMixed } = revenueByBucket(r.revenue);
  const priced = spendByBucket(r.spend);

  const isPlottable = !isMixed && (currency === null || currency === "UZS");
  const revenueNote =
    r.revenue.length === 0 || isPlottable
      ? null
      : isMixed
        ? REASON_TAG.mixed_currencies
        : `revenue in ${currency ?? "another currency"}`;
  const costNote = uzsPerUsd !== null || priced.size === 0 ? null : REASON_TAG.no_fx_rate;

  const revenue = isPlottable ? buckets : new Map<string, BucketPoint>();
  const spend = uzsPerUsd === null ? new Map<string, BucketPoint>() : priced;

  const union = new Map<string, BucketPoint>();
  for (const p of [...ordered(revenue), ...ordered(spend)]) union.set(p.key, p);
  const axis = ordered(union).slice(-RUNGS);

  const rate = uzsPerUsd ?? 0;
  const at = (map: ReadonlyMap<string, BucketPoint>, key: string): number | null =>
    map.get(key)?.value ?? null;
  return {
    // Minor units on both sides: USD × soʻm-per-USD × 100 tiyin.
    revenue: revenue.size === 0 ? [] : axis.map((p) => at(revenue, p.key)),
    cost:
      spend.size === 0
        ? []
        : axis.map((p) => {
            const usd = at(spend, p.key);
            return usd === null ? null : usd * rate * 100;
          }),
    ticks: axis.map((p) => bucketLabel(p.at, r.bucket, nowMs)),
    revenueNote,
    costNote,
  };
}

/**
 * Vendor spend BILLED in a bucket, less the work that reached no order, over the songs
 * delivered in it.
 *
 * This is deliberately NOT the Cost-per-song card's figure and the caption says so. Two
 * differences, both structural: the series' `spend` is fetched with no operation exclusions,
 * so it still carries the balance poller's ~72 daily `HEALTH` quota probes that
 * `unattributedSpend` (and the card) exclude; and the card's `cost_per_delivered_song` joins
 * spend to orders DELIVERED in the window, where a bucket here holds every call billed in it,
 * including calls against orders that failed, were cancelled, or are still generating.
 *
 * A bucket with no delivered song, or no priced spend, is dropped rather than plotted at
 * zero, and each surviving bucket is labelled from its own instant.
 */
function adaptCostPerSong(
  r: SeriesResponse,
  priceUsd: number | null,
  nowMs: number | null,
): CostPerSongData {
  const delivered = countByBucket(r.delivered);
  const spend = spendByBucket(r.spend);
  const unattributed = spendByBucket(r.unattributedSpend);

  const kept: BucketPoint[] = [];
  for (const bucket of ordered(spend)) {
    const songs = delivered.get(bucket.key)?.value ?? 0;
    if (songs <= 0) continue;
    const attributed = bucket.value - (unattributed.get(bucket.key)?.value ?? 0);
    // A negative here would mean the two queries disagree about the window; drop the bucket
    // rather than clamp it to a zero somebody would read as free songs.
    if (attributed < 0) continue;
    kept.push({ key: bucket.key, at: bucket.at, value: attributed / songs });
  }

  const axis = kept.slice(-RUNGS);
  return {
    values: axis.map((p) => p.value),
    ticks: axis.map((p) => bucketLabel(p.at, r.bucket, nowMs)),
    priceLine: priceUsd,
  };
}

const OPERATION_LABEL: Record<VendorOperation, string> = {
  music_compose: "MUSIC",
  music_inpaint: "INPAINT",
  speech_synthesis: "TTS",
  transcription: "STT",
  chat_completion: "CHAT",
  health: "HEALTH",
};

/**
 * Where the money went. A slice whose cost is null is not a $0 bar — it is a vendor we made
 * calls to and never priced, and it is left off rather than drawn as free.
 *
 * The operation is only appended when one vendor appears twice, which is how the mockup got
 * `ELEVENLABS MUSIC` beside `ELEVENLABS TTS` while `GEMINI` stood alone.
 *
 * The mock's tick was a fixed $2.50, which caps the ladder at $75 — a month of ElevenLabs
 * spend saturates it, and two vendors 4x apart then draw the same thirty ticks under a
 * caption still asserting a linear unit. The unit is chosen per window instead, off the
 * heaviest row, and the caption is a function of it.
 */
function adaptCostSplit(slices: readonly CostSplitView[]): CostSplitData {
  const priced = slices.filter((s) => s.cost.amountUsd !== null && s.cost.amountUsd > 0);
  const seen = new Map<Vendor, number>();
  for (const s of priced) seen.set(s.vendor, (seen.get(s.vendor) ?? 0) + 1);

  const heaviest = priced.reduce((m, s) => Math.max(m, s.cost.amountUsd ?? 0), 0);
  const tickUsd = Math.max(0.01, niceStep(heaviest, COST_SPLIT_LANE));

  const rows = priced.map((s): CostSplitRow => {
    const usd = s.cost.amountUsd ?? 0;
    const vendor = VENDOR_LABEL[s.vendor];
    return {
      vendor: (seen.get(s.vendor) ?? 0) > 1 ? `${vendor} ${OPERATION_LABEL[s.operation]}` : vendor,
      usd,
      ticks: Math.max(1, Math.round(usd / tickUsd)),
    };
  });
  return { rows: rows.sort((a, b) => b.usd - a.usd), tickUsd };
}

/** The rung ladder a funnel unit is chosen from — the mockup's 25 is a rung of this shape. */
const UNIT_LADDER: readonly number[] = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10_000];

/** Tallest bar should land near thirty-odd rungs, as the mock's 812 over a unit of 25 does. */
function funnelUnit(tallest: number): number {
  for (const unit of UNIT_LADDER) {
    if (tallest / unit <= 40) return unit;
  }
  return Math.max(1, Math.ceil(tallest / 40));
}

function stateCount(funnel: OrderFunnelView, ...states: readonly OrderState[]): number {
  return funnel.byState
    .filter((s) => states.includes(s.state))
    .reduce((sum, s) => sum + s.count, 0);
}

/**
 * The drop-off waterfall, reconciled by construction: created, less every state the cohort
 * is sitting in, is delivered.
 *
 * `byState` is a SURVIVOR count — there is deliberately no `abandoned` on the wire, because
 * drafts are deleted at the retention cutoff and any stored count of them would decay. Nor
 * can one be derived: `order_funnel` counts `created` and every state in ONE scan over the
 * same rows, so the state counts sum to `created` by construction and a deleted draft is
 * absent from both sides. A step drawn off that difference is always zero.
 */
function adaptFunnel(funnel: OrderFunnelView): FunnelData {
  if (funnel.created === 0) return { unit: 1, steps: [] };

  const unpaid = stateCount(funnel, "draft", "brief_ready", "lyrics_ready");
  const inFlight = stateCount(funnel, "authorized", "generating");
  const failed = stateCount(funnel, "failed");
  const cancelled = stateCount(funnel, "cancelled");
  const delivered = stateCount(funnel, "delivered");

  const steps: FunnelStep[] = [{ label: "BRIEFS", delta: funnel.created, total: true }];
  if (unpaid > 0) steps.push({ label: "UNPAID", delta: -unpaid });
  if (inFlight > 0) steps.push({ label: "IN FLIGHT", delta: -inFlight });
  if (cancelled > 0) steps.push({ label: "CANCELLED", delta: -cancelled });
  if (failed > 0) steps.push({ label: "FAILED", delta: -failed });
  steps.push({ label: "DELIVERED", delta: delivered, total: true });

  return { unit: funnelUnit(funnel.created), steps };
}

/**
 * The six charts.
 *
 * `finance` is optional and is read for two things only, both of which are money the series
 * response does not carry: the FX rate the cost line is converted at, and the published unit
 * price the cost-per-song chart draws its ceiling from. Without it those two degrade to an
 * empty cost line and a null price line — never to a guess.
 */
export function adaptSeries(r: SeriesResponse, finance?: FinanceResponse | null): ChartData {
  const fx = finance?.fx.uzsPerUsd ?? null;
  const derived = finance?.derivedRevenue ?? null;
  const priceUsd =
    fx !== null &&
    fx > 0 &&
    derived !== null &&
    derived.unitPriceMinor !== null &&
    derived.currency === "UZS"
      ? derived.unitPriceMinor / 100 / fx
      : null;

  /* The instant every bucket label is dated against: the window the SERVER counted to, not a
     clock read here. A null window is the whole record, and then no bucket can be called
     "today" — the labels fall back to dates. */
  const nowMs = r.window === null ? null : parseInstant(r.window.to);

  return {
    signups: {
      points: r.signups.map((p) => p.count),
      ticks: threeTicks(r.signups, r.bucket, r.isZeroFilled, nowMs),
      weekend: weekendFlags(r.signups, r.bucket),
    },
    delivered: {
      points: r.delivered.map((p) => p.count),
      ticks: threeTicks(r.delivered, r.bucket, r.isZeroFilled, nowMs),
      weekend: weekendFlags(r.delivered, r.bucket),
    },
    revCost: adaptRevCost(r, fx, nowMs),
    costPerSong: adaptCostPerSong(r, priceUsd, nowMs),
    costSplit: adaptCostSplit(r.costSplit),
    funnel: adaptFunnel(r.orderFunnel),
  };
}

/**
 * Which buckets are a Saturday or a Sunday, read off `startedAt`.
 *
 * Empty for every bucket but the day: an hour is not a weekend and a week bucket contains
 * one. Taken in the browser's own zone, which is the zone the header's clock and the "today"
 * window are already in.
 */
function weekendFlags(
  points: readonly CountPointView[],
  bucket: SeriesBucket,
): readonly boolean[] {
  if (bucket !== "day") return [];
  return points.map((p) => {
    const at = new Date(p.startedAt);
    if (Number.isNaN(at.getTime())) return false;
    const day = at.getDay();
    return day === 0 || day === 6;
  });
}

/* -------------------------------------------------------------------------- */
/* Sparklines                                                                  */
/* -------------------------------------------------------------------------- */

/** The four cards with a sparkline well. Their series is the page's series response. */
export type SparkKey = "newUsers" | "totalRevenue" | "vendorSpend" | "songsDelivered";

export type Sparks = Readonly<Partial<Record<SparkKey, readonly number[]>>>;

/** The mockup's sparks are twelve points wide. */
const SPARK_POINTS = 12;

/**
 * The four card sparklines, which are series data and so cannot come from the card
 * responses. Total revenue rides the delivered curve on purpose: the estimate is delivered ×
 * a CONSTANT price, so the two curves have the same shape and multiplying would only add a
 * price to a picture that has no axis to read it against.
 */
export function adaptSparks(r: SeriesResponse): Sparks {
  const spend = ordered(spendByBucket(r.spend)).map((p) => p.value);
  const delivered = r.delivered.map((p) => p.count);
  return {
    newUsers: r.signups.map((p) => p.count).slice(-SPARK_POINTS),
    totalRevenue: delivered.slice(-SPARK_POINTS),
    vendorSpend: spend.slice(-SPARK_POINTS),
    songsDelivered: delivered.slice(-SPARK_POINTS),
  };
}

/** Attaches the sparks to the cards that have a value; a pill has nowhere to put one. */
export function mergeSparks(values: CardValues, sparks: Sparks): CardValues {
  const out: Draft = { ...values };
  for (const [key, series] of Object.entries(sparks)) {
    const card = out[key];
    if (card === undefined || "tag" in card) continue;
    // A single point is not a line; the mockup's sparkline draws nothing below two.
    if (series.length < 2) continue;
    out[key] = { ...card, spark: series };
  }
  return out;
}

/* -------------------------------------------------------------------------- */
/* The vendor, plan and identified-list figures                                */
/* -------------------------------------------------------------------------- */

/**
 * Eleven components were written against the wire shapes directly, so most of what follows is
 * a NAMED SLICE rather than a transform, and that is deliberate on both counts.
 *
 * Named, because the slice is where a wiring mistake is cheap to prevent and expensive to
 * find: `recentSubscribers` must never meet the page's range picker, `deliveredOrders` off the
 * vendor route is a bare int and the one on the performance route is a `TrendView`, and the
 * two vendor-health figures must be drawn from ONE array or they will disagree about which
 * accounts exist. Each of those is a sentence in a docstring here instead of a bug in
 * `DashboardPage.tsx`.
 *
 * A slice and not a rebuild, because every one of these payloads already distinguishes the
 * absences the components draw — a null unit from a zero one, an unpriced bucket from a free
 * one, a missing night from a night with no activity. Anything this module "normalised" on the
 * way through would be one of those distinctions collapsing. So: no defaulting, no zero-fill,
 * no coalescing, no re-ordering, no filtering. The two real transforms are money labels for
 * the plan liability and instants for the plan book's `asOf`, and both are formatting, which
 * is this module's job and nowhere else's.
 */

/* ---- Audience: the two new figures and the churn card --------------------- */

/**
 * The DAU/WAU/MAU series, verbatim.
 *
 * `activityHistory` is passed through UNTOUCHED — not sorted, not densified, not zero-filled.
 * A night the snapshot job missed is ABSENT from this array, and that absence is the whole
 * signal: the chart re-lays the entries on a nightly axis off their own `startedAt` and breaks
 * the line across the hole. Filling a missing night with `0` here would draw a night on which
 * nobody used the bot, which is a measurement nobody made.
 *
 * `isActivityHistory` travels beside it because an EMPTY array has two meanings and only the
 * flag tells them apart: `false` is "the nightly job has never run here", whose remedy is to
 * schedule it, and `true` is "it runs and recorded nothing in this window", whose remedy is a
 * wider range. `activityBucket` is deliberately NOT forwarded: the route serves one grain,
 * always `day`, the chart asserts it, and a prop would invite a re-bucketing that cannot be
 * done by summing — day ⊆ week ⊆ month counts one person once per day in each.
 */
export function adaptActiveAccounts(r: AudienceResponse): ActiveAccountsProps {
  return { history: r.activityHistory, isActivityHistory: r.isActivityHistory };
}

/**
 * The language split, with the payload's OWN denominator.
 *
 * `accounts` is `languageMix.accounts` and never `languages.reduce(...)`: every `share` on the
 * wire was computed against it, so a lane that re-based its percentages on the entries it
 * chose to draw would print numbers that add to 100% of a population the server never
 * described. Where the two differ the chart draws the remainder as an explicit "not listed"
 * run — which it can only do because the true denominator reached it.
 *
 * A language nobody uses is ABSENT from `languages`, not present at zero, and nothing here
 * inserts it: this is a fully visited population, so the gap is presentational rather than a
 * missing measurement, and a zero row would say "we asked and found none" about a question
 * that was never asked.
 */
export function adaptLanguageMix(r: AudienceResponse): LanguageMixProps {
  return { languages: r.languageMix.languages, accounts: r.languageMix.accounts };
}

/**
 * The two churns, in one card and never in one number.
 *
 * `churn` counts bot-block PASSAGES in the window (people blocking and unblocking) and
 * `subscriptionChurn` is a RATE over plans that ENDED. Different populations, different
 * denominators, different tables, and they fail independently — so both arrive as they are,
 * nulls intact, and the card renders four separate absences.
 *
 * `endedPlans` and `anonymisedEnded` ride along inside `subscriptionChurn` because the rate
 * alone is not renderable honestly: a single-digit denominator swings thirty points on one
 * ending, and the `/forget`-erased endings cannot be followed to a renewal, which makes the
 * published rate a FLOOR on real churn rather than a measurement of it. The card prints the
 * count beside the percentage and the `≥` in front of it for exactly those reasons.
 *
 * **`isLoading` is FALSE here, always, and is not a parameter.** The prop means "the audience
 * section has never answered", which cannot be true of a response this function was handed.
 * Passing a query's `isFetching` instead would blank a card with real numbers on it into
 * skeletons on every background poll; use `CHURN_CARD_PENDING` for the first read, and the
 * section's own failure rendering for a read that failed.
 */
export function adaptChurnCard(r: AudienceResponse): ChurnCardProps {
  return {
    churn: r.churn,
    isChurnInstrumented: r.isChurnInstrumented,
    botBlockedAccounts: r.botBlockedAccounts,
    subscriptionChurn: r.subscriptionChurn,
    isLoading: false,
  };
}

/**
 * The card while the audience read has NEVER answered — both halves draw their skeleton.
 *
 * `botBlockedAccounts: 0` is unreachable in this state (both halves take the loading branch,
 * which reads no count) and it is a placeholder, not a measurement. That is only true while
 * `isLoading` is true, which is why this is a constant for one specific state rather than an
 * "empty" the caller may reuse: a read that FAILED is the audience section's own failure and
 * must render as that, not as a card that skeletons forever.
 */
export const CHURN_CARD_PENDING: ChurnCardProps = {
  churn: null,
  isChurnInstrumented: false,
  botBlockedAccounts: 0,
  subscriptionChurn: null,
  isLoading: true,
};

/* ---- Vendor: health, units and provenance --------------------------------- */

/**
 * The three props `VendorBalanceMeters` and `PollerFreshness` BOTH take, produced once.
 *
 * One object for two figures on purpose: they are two views of one array, and two adapters
 * would be two chances to filter, sort or clock them differently — at which point the meters
 * and the freshness axis disagree about which accounts exist, or about whether a given poll is
 * stale, and nothing on screen says which one is wrong.
 *
 * `asOf` is the SERVER's upper bound, `window.to`, and never a clock read here: every age on
 * both figures is measured against it, and substituting the browser's clock would let an
 * operator in another timezone read a five-hour-old poll as fresh. A null window means no age
 * can be computed at all, and both components then decline to call anything stale — an unknown
 * age is not a fresh one.
 *
 * `balances` is passed through unsorted and unfiltered, including rows with no figure: a row
 * that answered "uncapped" and a vendor that was never polled must stay distinguishable, and
 * dropping the empty rows would make an absent account and an unanswered one look identical.
 */
export function adaptVendorHealth(r: VendorResponse): VendorHealthProps {
  return {
    balances: r.vendorBalances,
    asOf: r.window === null ? null : r.window.to,
    isVendorBalance: r.capabilities.isVendorBalance,
  };
}

/**
 * The props `VendorBalanceMeters` and `PollerFreshness` share, byte for byte.
 *
 * An intersection rather than a re-declaration so the compiler holds the two interfaces
 * together: the day one of them grows a prop, this type stops satisfying it and the wiring
 * breaks loudly instead of the two figures silently drifting apart.
 */
export type VendorHealthProps = VendorBalanceMetersProps & PollerFreshnessProps;

/**
 * Tokens, billed characters and audio milliseconds, per vendor.
 *
 * `deliveredOrders` is the vendor route's BARE INT — the denominator every per-song ratio on
 * these rows was already divided by. It is emphatically NOT `PerformanceResponse.
 * deliveredOrders`, which is a `TrendView` of the same name on another route counted over
 * another window; there is no shared accessor for the two anywhere in this codebase and none
 * may be written. Zero is a real state and the chart says so in words: with nothing delivered,
 * every per-song figure is undefined rather than zero.
 *
 * The rows go through unsorted and unmerged. A null quantity means THIS VENDOR MEASURES NO
 * SUCH UNIT and the row simply does not appear under that family; a `0` means it measured and
 * found nothing. The three unit families share no axis, which is why nothing here is summed
 * into a single "usage" figure — and tokens are a CONSUMPTION measure that never describes a
 * remaining balance.
 */
export function adaptVendorUnits(r: VendorResponse): VendorUnitsProps {
  return { rows: r.unitsPerSongByVendor, deliveredOrders: r.deliveredOrders };
}

/**
 * How every dollar on this page was arrived at — the WHOLE partition, unfiltered.
 *
 * This is the one adapter where dropping a row would be a lie rather than a tidy-up. The
 * buckets partition CALLS, so the denominator of every share drawn is the sum of what is
 * passed: a filtered subset would still tile the lane to 100% and would be a share of a
 * population the payload never described.
 *
 * **The specific collapse this function exists to refuse:** a bucket with `costSource: null`
 * and positive `calls` carries `costUsd: null` and means UNMEASURED — no rate existed for
 * those calls. A `vendor_reported` bucket summing to `0.0` means the vendor said the calls
 * were FREE, which on a deployment whose default OpenRouter model is a `:free` one is normal
 * rather than an error. Coalescing the null to `0`, or the `0` to "no data", turns "nobody
 * could say what this cost" into "this cost nothing" — which is how a deployment concludes its
 * rendering pipeline is free. Both arrive here untouched and the chart draws them as two
 * visibly different marks.
 */
export function adaptCostProvenance(r: VendorResponse): CostProvenanceProps {
  return { buckets: r.costProvenance };
}

/* ---- The per-supplier cards: five figures, one light ---------------------- */

/** Which quantity a supplier bills its consumption in. There is no fourth, and no total. */
type ConsumptionUnit = "tokens" | "characters" | "audio ms";

/** The five slots, in the owner's order. The key is the React key and nothing else. */
export type VendorFigureKey = "balance" | "consumed" | "perSong" | "costPerSong" | "remaining";

export interface VendorFigure {
  readonly key: VendorFigureKey;
  readonly label: string;
  /** `null` is UNMEASURED — the card draws a hatched pill and prints `note` in place of it. */
  readonly value: string | null;
  readonly unit: string;
  /**
   * The reason, when `value` is null. Empty where the figure has nothing to add that the
   * verdict, the unit or the divisor line above the cards has not already said — the card then
   * prints no line at all, rather than a line that repeats one of them.
   */
  readonly note: string;
  /** Only `balance` and `remaining` carry one — the two the owner asked to highlight. */
  readonly state?: ThresholdState;
}

export interface VendorCard {
  readonly vendor: Vendor;
  readonly label: string;
  /** `tokens` / `characters` / `audio ms` — what THIS supplier bills, named in the caption. */
  readonly unitName: string;
  /** The one number both lights read. `null` when nothing could measure a runway. */
  readonly songsOfCover: number | null;
  readonly state: ThresholdState;
  readonly verdict: string;
  readonly figures: readonly VendorFigure[];
  /** One line per billing account, so a supplier with two keys is legible as two. */
  readonly accounts: readonly string[];
}

/**
 * The suppliers the owner named, first and in their order, then anything else the response
 * mentions. `fake` is absent because the aggregates exclude fake rows by default; if one ever
 * arrives it falls through to the tail rather than being hidden, since a demo run showing up
 * in a live panel is a fact worth seeing.
 */
const CARD_ORDER: readonly Vendor[] = ["openrouter", "elevenlabs"];

/** `null` reads as "this supplier measures no such unit", never as a zero. */
function consumptionOf(
  units: VendorUnitsPerSongView | undefined,
): { readonly unit: ConsumptionUnit; readonly total: number; readonly perSong: number | null } | null {
  if (units === undefined) return null;
  if (units.totalTokens !== null) {
    return { unit: "tokens", total: units.totalTokens, perSong: units.tokensPerSong?.value ?? null };
  }
  if (units.billedCharacters !== null) {
    return {
      unit: "characters",
      total: units.billedCharacters,
      perSong: units.charactersPerSong?.value ?? null,
    };
  }
  if (units.audioMs !== null) {
    return { unit: "audio ms", total: units.audioMs, perSong: units.audioMsPerSong?.value ?? null };
  }
  return null;
}

/** A balance in the unit the vendor actually quoted. Never converted, never compared. */
function nativeBalance(b: VendorBalanceView): string | null {
  if (b.remaining === null) return null;
  return b.unit === "usd" ? formatUsd(b.remaining) : `${formatCount(b.remaining)} chars`;
}

/**
 * Why a balance row has no runway, in the operator's terms.
 *
 * Four of these are not levels and must never be painted red: an uncapped key is UNKNOWN, and
 * so is one that has never answered. Collapsing them into a severity is how an account that
 * was never low gets topped up, or an empty one gets ignored.
 */
function balanceReason(b: VendorBalanceView, asOf: number | null): string | null {
  if (b.isUnbounded === true) return "uncapped key — the vendor publishes no cap";
  if (b.fetchedAt === null) return "never answered — no successful poll yet";
  if (b.remaining === null) return "answered without a balance";
  const fetched = parseInstant(b.fetchedAt);
  if (asOf !== null && fetched !== null && asOf - fetched > BALANCE_STALE_MS) {
    return `stale — last answered ${ageLabel(asOf - fetched)} ago`;
  }
  if (b.songsRemaining === null) return "no per-song rate over trailing traffic";
  return null;
}

/**
 * Five figures per supplier, and the honest absence wherever one of them is not a number.
 *
 * The two arithmetic decisions worth stating, because both could reasonably have gone the
 * other way and both would then have printed a plausible wrong number:
 *
 *  * **One `songsOfCover` per card, taken as the WORST across a supplier's accounts.** The
 *    second OpenRouter key is a separate billing relationship, and a funded spare does not
 *    refill an empty primary — the deployment stops when the account carrying traffic stops.
 *  * **A remaining-consumption figure is only DERIVED where a division is defined.** Dividing
 *    a dollar balance by dollars-per-unit needs `costUsd > 0` and a measured unit total. A
 *    `costUsd` of exactly `0` is the vendor REPORTING the calls free (the shipped `:free`
 *    model), which leaves no rate to divide by — the runway there is undefined, not zero, and
 *    not infinite either, so it is printed as an absence with that sentence.
 */
export function adaptVendorCards(r: VendorResponse): VendorCardsProps {
  const asOf = r.window === null ? null : parseInstant(r.window.to);
  const seen = new Set<Vendor>([
    ...r.vendorBalances.map((b) => b.vendor),
    ...r.costPerSongByVendor.map((c) => c.vendor),
    ...r.unitsPerSongByVendor.map((u) => u.vendor),
  ]);
  const ordered = [
    ...CARD_ORDER.filter((v) => seen.has(v)),
    ...[...seen].filter((v) => !CARD_ORDER.includes(v)).sort(),
  ];

  return {
    cards: ordered.map((vendor) => buildCard(vendor, r, asOf)),
    deliveredOrders: r.deliveredOrders,
    isVendorBalance: r.capabilities.isVendorBalance,
  };
}

function buildCard(vendor: Vendor, r: VendorResponse, asOf: number | null): VendorCard {
  const balances = r.vendorBalances.filter((b) => b.vendor === vendor);
  const cost = r.costPerSongByVendor.find((c) => c.vendor === vendor);
  const consumed = consumptionOf(r.unitsPerSongByVendor.find((u) => u.vendor === vendor));
  const unitName = consumed === null ? "consumption" : consumed.unit;

  /* The figures quote the PRIMARY account, so the light must read the primary too or the card
     contradicts itself: a spare key at eight songs would paint a red light beside a funded
     primary's balance and its runway, and there would be no number on the card the colour was
     about. A worse SPARE is still worth knowing, so `verdictOf` names it in words instead —
     which is the one place it can be said without attaching it to somebody else's figure. */
  const lead = balances.find((b) => !b.isFallback) ?? balances[0];
  const songsOfCover = lead?.songsRemaining ?? null;
  const state = thresholdOf(songsOfCover);

  /* `primary` / `fallback` is only worth a word when there are two accounts to tell apart. On
     the single-account supplier the role is the whole supplier, and printing it made every card
     open with a label that distinguished nothing. */
  const named = balances.length > 1;
  const accounts = balances.map((b) => {
    const native = nativeBalance(b);
    const who = named ? `${b.isFallback ? "fallback" : "primary"} ` : "";
    const age =
      b.fetchedAt === null || asOf === null
        ? "never polled"
        : (() => {
            const fetched = parseInstant(b.fetchedAt);
            return fetched === null ? "polled" : `${ageLabel(asOf - fetched)} ago`;
          })();
    return `${who}${native ?? "no balance"} · ${age}`;
  });

  return {
    vendor,
    label: VENDOR_LABEL[vendor],
    unitName,
    songsOfCover,
    state,
    verdict: verdictOf(state, songsOfCover, lead, balances, asOf),
    accounts,
    figures: [
      balanceFigure(lead, songsOfCover, state, asOf),
      consumedFigure(consumed),
      perSongFigure(consumed, r.deliveredOrders),
      costFigure(cost, r.deliveredOrders),
      remainingFigure(lead, consumed, cost, state),
    ],
  };
}

function songsPhrase(songs: number): string {
  return `${formatCount(songs)} song${songs === 1 ? "" : "s"} of cover`;
}

/**
 * The word is mandatory: a threshold carried by colour alone is unreadable to half its readers.
 *
 * A spare account in a worse state than the primary is appended rather than allowed to set the
 * light — see `buildCard`. It reads as a sentence about a named account, so nobody has to
 * guess which of the two the colour was about.
 */
function verdictOf(
  state: ThresholdState,
  songs: number | null,
  lead: VendorBalanceView | undefined,
  balances: readonly VendorBalanceView[],
  asOf: number | null,
): string {
  const spare = balances
    .filter((b) => b !== lead && b.songsRemaining !== null)
    .reduce<VendorBalanceView | null>(
      (worst, b) => (worst === null || (b.songsRemaining ?? 0) < (worst.songsRemaining ?? 0) ? b : worst),
      null,
    );
  const spareNote =
    spare === null || spare.songsRemaining === null || (songs !== null && spare.songsRemaining >= songs)
      ? ""
      : ` · spare key ${thresholdLabel(thresholdOf(spare.songsRemaining))} at ${songsPhrase(spare.songsRemaining)}`;

  if (songs !== null) return `${thresholdLabel(state)} · ${songsPhrase(songs)}${spareNote}`;
  if (lead === undefined) return "unknown · this account has never been polled";
  return `unknown · ${balanceReason(lead, asOf) ?? "no runway could be measured"}${spareNote}`;
}

function balanceFigure(
  lead: VendorBalanceView | undefined,
  songs: number | null,
  state: ThresholdState,
  asOf: number | null,
): VendorFigure {
  const base = { key: "balance" as const, label: "Balance", state };
  if (lead === undefined) {
    return {
      ...base,
      value: null,
      unit: "",
      note: "not polled — no balance row for this account",
    };
  }
  const native = nativeBalance(lead);
  if (native === null) {
    return { ...base, value: null, unit: "", note: balanceReason(lead, asOf) ?? "not reported" };
  }
  /* No note when the runway IS measured: the verdict beside the supplier's name already prints
     `ok · 1 049 songs of cover`, and this line used to repeat it and then append
     `estimateBasis` — a wire column name (`trailing_spend_usd`), which is not a sentence and
     was never meant for an operator. The note is kept for the ABSENCES, which the verdict
     states in one word and this can state in the account's own terms. */
  return {
    ...base,
    value: native,
    unit: "",
    note: songs === null ? (balanceReason(lead, asOf) ?? "runway not measured") : "",
  };
}

function consumedFigure(
  consumed: ReturnType<typeof consumptionOf>,
): VendorFigure {
  if (consumed === null) {
    return {
      key: "consumed",
      label: "Consumed",
      value: null,
      unit: "",
      note: "no token or character count recorded",
    };
  }
  return {
    key: "consumed",
    label: `${COUNT_LABEL[consumed.unit]} count`,
    value: formatCount(consumed.total),
    unit: consumed.unit,
    note: "retries included",
  };
}

function perSongFigure(
  consumed: ReturnType<typeof consumptionOf>,
  delivered: number,
): VendorFigure {
  const label = consumed === null ? "Per song" : `${COUNT_LABEL[consumed.unit]}s per song`;
  if (consumed === null || consumed.perSong === null) {
    return {
      key: "perSong",
      label,
      value: null,
      unit: "",
      note:
        delivered === 0
          ? "nothing delivered in this window"
          : "this supplier measures no such unit",
    };
  }
  /* The denominator is printed ONCE, above the cards — see `VendorCardsProps.deliveredOrders`.
     Repeating it under each per-song figure was the same clause four times a card. */
  return { key: "perSong", label, value: formatCount(consumed.perSong), unit: consumed.unit, note: "" };
}

/** `not_priced` is the shipped state for most legs, and it is not `$0.00`. */
const COST_ABSENCE: Record<AbsenceReason, string> = {
  no_fx_rate: "no FX rate published",
  no_price_published: "no price published",
  mixed_currencies: "mixed currencies — no honest single figure",
  not_priced: "no rate is configured for this supplier",
  no_denominator: "nothing delivered in this window",
  not_instrumented: "this supplier is not instrumented",
};

function costFigure(
  cost: VendorCostPerSongView | undefined,
  delivered: number,
): VendorFigure {
  const base = { key: "costPerSong" as const, label: "Cost per song" };
  const value = cost?.costPerSong?.value ?? null;
  if (cost === undefined || value === null) {
    return {
      ...base,
      value: null,
      unit: "",
      note:
        cost?.unavailableReason == null
          ? delivered === 0
            ? "nothing delivered in this window"
            : "no priced call reached a delivered song here"
          : COST_ABSENCE[cost.unavailableReason],
    };
  }
  return {
    ...base,
    value: formatUsd(value),
    unit: "",
    /* The coverage gap is printed with the figure, never after it: an average over the
       attributed subset improves as instrumentation degrades, and a reader who cannot see the
       denominator cannot see that happening. The PAIR is the whole message, so it is a pair and
       not a sentence about one. */
    note: `${formatCount(cost.attributedOrders)} of ${formatCount(delivered)} priced`,
  };
}

/* No `songs` parameter: the runway this figure carries the light for is the card's one
   `songsOfCover`, and the verdict beside the supplier's name is where it is spelled. */
function remainingFigure(
  lead: VendorBalanceView | undefined,
  consumed: ReturnType<typeof consumptionOf>,
  cost: VendorCostPerSongView | undefined,
  state: ThresholdState,
): VendorFigure {
  const unitName = consumed === null ? "consumption" : consumed.unit;
  const base = { key: "remaining" as const, label: `Remaining ${unitName}`, state };

  if (lead === undefined || lead.remaining === null) {
    return { ...base, value: null, unit: "", note: "no balance to convert" };
  }

  /* MEASURED. ElevenLabs bills characters and its balance IS a character count, so this is
     the same reading the balance figure printed — said once more in the unit the consumption
     rows are quoted in, and labelled as the same number rather than implied to be a second. */
  if (lead.unit === "characters") {
    return {
      ...base,
      value: formatCount(lead.remaining),
      unit: "characters",
      /* Four words, and every one of them load-bearing: the unit is already the suffix and the
         runway is already the verdict, so all this can add is that the figure is the balance
         over again rather than a second reading of it. */
      note: "same as the balance",
    };
  }

  /* DERIVED, and only where the division is defined — see the function docstring above. */
  if (consumed === null || consumed.total <= 0) {
    return { ...base, value: null, unit: "", note: `no ${unitName} consumption measured in this window` };
  }
  if (cost?.costUsd == null) {
    return {
      ...base,
      value: null,
      unit: "",
      note: "no rate configured — the balance cannot be converted",
    };
  }
  if (cost.costUsd <= 0) {
    return {
      ...base,
      value: null,
      unit: "",
      note: "vendor reports these calls free — no price to divide by",
    };
  }
  const usdPerUnit = cost.costUsd / consumed.total;
  return {
    ...base,
    value: formatCount(lead.remaining / usdPerUnit),
    unit: unitName,
    note: `derived · ${formatUsd(lead.remaining)} ÷ ${formatUsd(usdPerUnit * 1e6)}/M`,
  };
}

/**
 * The SINGULAR noun each unit is counted in, for the two labels that name it.
 *
 * Spelled out rather than derived by trimming an `s`, because `audio ms` has no singular worth
 * printing and a generic de-pluraliser would render it `audio m`.
 */
const COUNT_LABEL: Record<ConsumptionUnit, string> = {
  tokens: "Token",
  characters: "Character",
  "audio ms": "Audio millisecond",
};

/* ---- The plan book: one response, two figures, no window ------------------ */

/**
 * How fully the ENDED plans were used.
 *
 * The denominator is `endedPlans`, not live ones: a running plan's ratio is not final, and the
 * route leaves it out rather than counting it early. All ten bins are always present, so a
 * `count` of `0` is "nobody finished at this ratio" and never a gap — nothing here inserts or
 * drops a bin, and the chart reads `bins.length` rather than assuming ten.
 *
 * `asOfLabel` is formatted here because formatting lives in this module, and it is printed
 * because `GET /api/metrics/plans` takes NO window: without the instant beside it the
 * histogram reads as obeying whatever period the picker happens to show.
 */
export function adaptPlanUtilisation(r: PlanLiabilityResponse): PlanUtilisationProps {
  return {
    bins: r.utilisation,
    endedPlans: r.endedPlans,
    isPlanRevenue: r.isPlanRevenue,
    asOfLabel: formatInstant(r.asOf),
  };
}

/**
 * What the running plans owe, in SONGS.
 *
 * Every scalar is a straight read: `unconsumedSongs`, `breakageSongs` and `expiringSongsLeft`
 * keep their nulls, which each mean "there is no such population" (no plan is live, none has
 * ended, none expires inside the horizon) as opposed to `0`, which means the population exists
 * and owes nothing. Two different screens, and coalescing either way loses the one that
 * matters.
 *
 * The single transform is `liveAmounts`: `{currency, amountMinor}` becomes `{currency, label}`
 * with the minor-unit exponent applied for that currency, because a chart that guessed one
 * would misprint a two-decimal currency by a factor of a hundred. Every entry is carried and
 * **none is summed** — there is no honest scalar across two currencies, and today's
 * one-element list is not a licence to collapse it. The money is the measured SALE total of
 * the running plans and is never a valuation of the songs still owed: pricing one means
 * dividing `amountMinor` by `songsIncluded`, an allocation policy nobody here has chosen.
 *
 * `liveHolders` understates by exactly `liveAnonymisedPlans` (`COUNT(DISTINCT)` does not count
 * the nulls `/forget` leaves behind), and both travel so the figure can say so.
 */
export function adaptPlanLiability(r: PlanLiabilityResponse): PlanLiabilityProps {
  return {
    asOfLabel: formatInstant(r.asOf),
    livePlans: r.livePlans,
    liveHolders: r.liveHolders,
    liveAnonymisedPlans: r.liveAnonymisedPlans,
    livePlansWithSongsLeft: r.livePlansWithSongsLeft,
    unconsumedSongs: r.unconsumedSongs,
    liveAmounts: r.liveAmounts.map((a): PlanLiabilityAmount => {
      const m = money(a.amountMinor, a.currency);
      return { currency: a.currency, label: `${m.value} ${m.unit}` };
    }),
    endedPlans: r.endedPlans,
    breakageSongs: r.breakageSongs,
    expiringWithinDays: r.expiringWithinDays,
    expiringPlans: r.expiringPlans,
    expiringSongsLeft: r.expiringSongsLeft,
    isPlanRevenue: r.isPlanRevenue,
  };
}

/* ---- The identified lists: RECORDS_READ, audited, unmasked ---------------- */

/**
 * The ranking half, or `undefined` when the read has not arrived.
 *
 * **`undefined` is never turned into an empty list.** "Nobody delivered anything in this
 * window" and "we were not allowed to look" are different answers and the card prints
 * different words for them; substituting `{items: []}` for a refusal would report the first
 * while the second happened. So the absence is forwarded as an absence, and the caller passes
 * its own `notice` for why.
 *
 * The window on this block narrowed the ranking and nothing else — see below.
 */
export function topGeneratorsOf(
  r: AudienceListsResponse | undefined,
): TopGeneratorsView | undefined {
  return r?.topGenerators;
}

/**
 * The recency half, or `undefined` when the read has not arrived.
 *
 * **This block takes NO window and must never be given one.** The route accepts no parameter
 * that would filter it, the payload carries no window field on it, and its caption is "the
 * last N" — never "this week". The page's range picker has nowhere to attach here, and the
 * only reason this slice has a name is so that fact has somewhere to be written down.
 *
 * `undefined` is "not read", as above. Once it has arrived, `isPlanRevenue` on the block is
 * what separates the two EMPTY answers: nothing has ever sold, or nothing sold recently.
 */
export function recentSubscribersOf(
  r: AudienceListsResponse | undefined,
): RecentSubscribersView | undefined {
  return r?.recentSubscribers;
}

/**
 * The copy for the `notice` slot on both list cards when the read did not answer.
 *
 * A 403 is an EXPECTED outcome here rather than a fault: these lists are `RECORDS_READ` and
 * the rest of the page is `DASHBOARD_READ`, so a role can legitimately hold one and not the
 * other. It is worded as a permission fact and not as an error, and it must render inside
 * these two cards only — the aggregate sections beside them answered fine and must stay up.
 *
 * A string rather than a node, because this module is pure; the caller wraps it.
 */
export function audienceListsNote(status: number): string {
  if (status === 403) {
    return "Your role can read the dashboard aggregates but not customer records, so these two lists were not requested.";
  }
  return "The list was not read. The aggregate figures on this page come from a different request.";
}
