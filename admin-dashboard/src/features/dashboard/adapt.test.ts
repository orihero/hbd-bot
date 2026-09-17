import { describe, expect, it } from "vitest";

import type { FinanceResponse, MoneyTotal } from "@/api/dashboard";
import {
  adaptFinance,
  formatAudio,
  formatCents,
  unavailableKey,
  type CardValue,
} from "@/features/dashboard/adapt";

/**
 * The two units the vendor cards were re-denominated into, and the three ways each of them was
 * got wrong on the way here. Every case below is a regression, not a specification exercise.
 */
describe("formatCents — the figure that used to read $0.00", () => {
  it("keeps the digits of a sub-cent song, which is the whole reason it exists", () => {
    // The shipped OpenRouter model renders a song for about four tenths of a cent.
    // `formatUsd` rounds that to `$0.00`; two decimal places of a DOLLAR is no precision at
    // all three orders of magnitude below one.
    expect(formatCents(0.00415206)).toBe("0.42¢");
  });

  it("does not route the fraction through formatCount, which rounds to a whole number", () => {
    // The first cut did exactly that and rendered every sub-cent figure as `0¢` — the same
    // defect in a new unit.
    expect(formatCents(0.004)).toBe("0.4¢");
    expect(formatCents(0.0099)).toBe("0.99¢");
  });

  it("stays in cents above a dollar rather than switching units under the reader", () => {
    // A card whose unit depends on its value renders `30¢` one window and `$1.20` the next,
    // and nothing tells the reader the scale moved.
    expect(formatCents(1.2)).toBe("120¢");
    expect(formatCents(12.5)).toBe("1 250¢");
  });

  it("trims a trailing decimal zero without eating a significant one", () => {
    // `120`.replace(/\.?0+$/) is `12`. The trim is guarded on the decimal point for this.
    expect(formatCents(0.05)).toBe("5¢");
    expect(formatCents(1.2)).toBe("120¢");
  });

  it("says <0.01¢ rather than rounding a real cost to nothing", () => {
    expect(formatCents(0.000009)).toBe("<0.01¢");
    expect(formatCents(0)).toBe("0¢");
  });

  it("keeps the sign", () => {
    expect(formatCents(-0.225)).toBe("-22.5¢");
  });
});

describe("formatAudio — rendered audio as a length", () => {
  it("reads a song as minutes and seconds", () => {
    expect(formatAudio(90_000)).toBe("1:30");
    expect(formatAudio(180_000)).toBe("3:00");
  });

  it("grows an hours field, because a window total is hours of audio", () => {
    // A minutes-only formatter renders this `247:30`, which reads as four minutes to anyone
    // who does not stop and count the digits.
    expect(formatAudio(14_850_000)).toBe("4:07:30");
  });

  it("pads both fields once an hour is present", () => {
    expect(formatAudio(3_723_000)).toBe("1:02:03");
  });

  it("renders well under a second as 0:00 rather than inventing a unit for it", () => {
    expect(formatAudio(400)).toBe("0:00");
    expect(formatAudio(0)).toBe("0:00");
  });

  it("never renders a negative clock", () => {
    expect(formatAudio(-5_000)).toBe("0:00");
  });
});

/**
 * A finance response from the deployment that reported the defect: the panel has no published
 * unit price and no FX rate, so the estimate and the run-rate pair have no figure and the
 * server says which of the two is missing on each. Everything not read by `adaptFinance` is
 * filled with the smallest legal value — these are the counts and flags of a quiet window, and
 * not one of them is a measurement this file asserts on.
 */
/** One receipts row. UZS from the stub rail unless a test says otherwise — today's shape. */
function receipt(over: Partial<MoneyTotal> = {}): MoneyTotal {
  return {
    source: "plan",
    product: "starter",
    currency: "UZS",
    provider: "stub",
    isStubRail: false,
    sales: 1,
    amountMinor: 0,
    ...over,
  };
}

function financeWithNoPrices(): FinanceResponse {
  const noCost = {
    amountUsd: null,
    costedCalls: 0,
    calls: 0,
    costSource: null,
    unavailableReason: null,
  } as const;
  const noFx = { uzsPerUsd: null, asOf: null } as const;
  const window = { from: "2026-09-01T00:00:00Z", to: "2026-09-15T00:00:00Z" } as const;
  return {
    window,
    revenue: [],
    unpricedTopups: { unpriced: 0, priced: 0 },
    derivedRevenue: {
      // Songs WERE delivered — the estimate is missing its price, not its population, which
      // is exactly the case a zero-filled card would have reported as "no revenue".
      deliveredSongs: 12,
      unitPriceMinor: null,
      currency: null,
      amountMinor: null,
      unavailableReason: "no_price_published",
    },
    vendorSpend: noCost,
    costPerSong: { cost: noCost, deliveredOrders: 12, attributedOrders: 0, perSongUsd: null },
    unattributedSpend: noCost,
    netRunRate: {
      window,
      revenue: [],
      cost: noCost,
      fxUsed: noFx,
      currency: null,
      netMinor: null,
      annualisedMinor: null,
      unavailableReason: "no_fx_rate",
    },
    fx: noFx,
    vendorBalances: [],
    fakeCalls: { fakeCalls: 0, totalCalls: 0 },
    capabilities: {
      isCostTelemetry: true,
      isLatencyTelemetry: true,
      isAssetStorageKeyRecorded: true,
      isChatCapture: true,
      isPaymentLedger: true,
      isStateTransitionLog: true,
      isVendorUsage: true,
      isVendorCost: true,
      isPlanRevenue: true,
      isTopupRevenue: true,
      isChurnInstrumented: true,
      isVendorBalance: true,
      isActivityHistory: true,
    },
  };
}

/**
 * The mapping that carries a server's reason onto the card, and the three ways it must stay
 * quiet. This is the Finances defect written down: the deployment returned 200 with
 * `no_price_published` on `derivedRevenue` and `no_fx_rate` on `netRunRate`, and the operator
 * saw three bare em dashes, because the reason reached `CardValue` and went no further.
 */
describe("unavailableKey — the reason a card has no number", () => {
  it("resolves every reason the wire can name, so none of the six can go silently missing", () => {
    // Written out one by one rather than looped over `ABSENCE_REASON_VALUES`: a loop asserts
    // that the table has an entry, and what is being pinned here is WHICH entry — swapping
    // `no_fx_rate` and `no_price_published` would tell an operator to configure the wrong
    // thing, and a loop would pass.
    expect(unavailableKey({ tag: "no fx rate", reason: "no_fx_rate" })).toBe(
      "common.stats.unavailable.noFxRate",
    );
    expect(unavailableKey({ tag: "no price published", reason: "no_price_published" })).toBe(
      "common.stats.unavailable.noPricePublished",
    );
    expect(unavailableKey({ tag: "mixed currencies", reason: "mixed_currencies" })).toBe(
      "common.stats.unavailable.mixedCurrencies",
    );
    expect(unavailableKey({ tag: "not priced", reason: "not_priced" })).toBe(
      "common.stats.unavailable.notPriced",
    );
    expect(unavailableKey({ tag: "no denominator", reason: "no_denominator" })).toBe(
      "common.stats.unavailable.noDenominator",
    );
    expect(unavailableKey({ tag: "not tracked", reason: "not_instrumented" })).toBe(
      "common.stats.unavailable.notInstrumented",
    );
  });

  it("says nothing for a member it has never heard of, rather than printing the wire string", () => {
    // A bucket name is the realistic accident: `SeriesBucket` and `AbsenceReason` are two
    // closed vocabularies of short snake_case words, and `hour`/`day`/`week`/`month` are what
    // arrives if a response ever puts the wrong one in the reason slot. The cast is the whole
    // point of the case — this cannot be built through the types, and it can still be served.
    for (const bucket of ["hour", "day", "week", "month"]) {
      const value = { tag: "not tracked", reason: bucket } as unknown as CardValue;
      expect(unavailableKey(value)).toBeNull();
    }
  });

  it("says nothing for an absence this module inferred itself", () => {
    // `not polled`, `never answered`, `4h stale` are prose written in `adapt.ts`, not wire
    // members: there is no key for them and no translation, and an English phrase under a
    // Russian card is worse than the dash alone.
    expect(unavailableKey({ tag: "not polled" })).toBeNull();
    expect(unavailableKey({ tag: "never answered" })).toBeNull();
    expect(unavailableKey({ tag: "4h stale" })).toBeNull();
  });

  it("leaves a measured card and a card still in flight alone", () => {
    // A number is not an absence, and a section that has not answered yet has not said
    // anything to caption — the skeleton owns that state.
    expect(unavailableKey({ value: "1 842", delta: "+12%" })).toBeNull();
    expect(unavailableKey({ value: "0", delta: "" })).toBeNull();
    expect(unavailableKey(undefined)).toBeNull();
  });
});

/**
 * The adapter end of the same defect: the finance cards have to CARRY the reason before a card
 * can render it, including on the paths where the server left `unavailableReason` null and the
 * fallback is this module's own reading of the shape it got.
 */
describe("adaptFinance — the absent money cards name their reason", () => {
  it("carries the server's reason onto MRR and ARR", () => {
    const out = adaptFinance(financeWithNoPrices());
    expect(out.mrr).toEqual({ tag: "no fx rate", reason: "no_fx_rate" });
    expect(out.arr).toEqual({ tag: "no fx rate", reason: "no_fx_rate" });
  });

  it("keeps the pill copy byte for byte when it falls back", () => {
    // The fallback used to be the phrase and is now the member it was the phrase OF, so the
    // text is unchanged and the card gains something it can translate.
    const r = financeWithNoPrices();
    const out = adaptFinance({
      ...r,
      netRunRate: { ...r.netRunRate, unavailableReason: null },
    });
    expect(out.mrr).toEqual({ tag: "not priced", reason: "not_priced" });
  });

  it("does not touch a card that has a figure", () => {
    const r = financeWithNoPrices();
    const out = adaptFinance({ ...r, revenue: [receipt({ amountMinor: 1_500_000 })] });
    expect(out.totalRevenue).toEqual({ value: "15 000", unit: "soʻm", delta: "" });
    expect(unavailableKey(out.totalRevenue)).toBeNull();
  });
});

/**
 * Revenue is the RECEIPTS now, not the delivered × price estimate, and the card has to answer
 * four differently-shaped windows: money in one currency, money in two, a period nobody
 * bought in, and a deployment where nobody ever has.
 */
describe("adaptFinance — Revenue is what was recorded", () => {
  it("sums the window's rows when they share a currency", () => {
    const out = adaptFinance({
      ...financeWithNoPrices(),
      revenue: [
        receipt({ amountMinor: 1_500_000 }),
        receipt({ source: "topup", product: "pack_5", amountMinor: 500_000 }),
      ],
    });
    expect(out.totalRevenue).toEqual({ value: "20 000", unit: "soʻm", delta: "" });
  });

  it("counts a stub-rail sale, because the chart under the card counts it too", () => {
    const out = adaptFinance({
      ...financeWithNoPrices(),
      revenue: [receipt({ amountMinor: 700_000, isStubRail: true })],
    });
    expect(out.totalRevenue).toEqual({ value: "7 000", unit: "soʻm", delta: "" });
  });

  it("refuses to add across currencies", () => {
    const out = adaptFinance({
      ...financeWithNoPrices(),
      revenue: [
        receipt({ amountMinor: 1_500_000 }),
        receipt({ currency: "USD", amountMinor: 500 }),
      ],
    });
    expect(out.totalRevenue).toEqual({ tag: "mixed currencies", reason: "mixed_currencies" });
  });

  it("reports a quiet period as zero, not as an absence", () => {
    // Both receipts tables are authoritative about their own rows: nobody bought anything is
    // a measurement, and a pill here would send an operator to configure a working panel.
    const out = adaptFinance(financeWithNoPrices());
    expect(out.totalRevenue).toEqual({ value: "0", delta: "" });
  });

  it("reports a deployment that has never recorded a receipt as untracked", () => {
    const r = financeWithNoPrices();
    const out = adaptFinance({
      ...r,
      capabilities: { ...r.capabilities, isPlanRevenue: false, isTopupRevenue: false },
    });
    expect(out.totalRevenue).toEqual({ tag: "not tracked", reason: "not_instrumented" });
  });
});
