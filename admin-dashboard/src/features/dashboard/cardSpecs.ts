/**
 * The stat cards, as PRESENTATION ONLY: what each one is called, what unit it is quoted in,
 * what the caption under it says when the wire has nothing more specific to say, which row it
 * sits in at that row's design width, and — since the page became four tabs — which SECTION
 * that row belongs to.
 *
 * This is the mockup's `ROWS` table with every value, delta, spark array and `pv` block
 * stripped out. Nothing here is a measurement, so nothing here can go stale or be believed
 * as one — the numbers arrive from `adapt.ts` keyed by `CardKey` and are merged over these
 * at render time.
 *
 * `sub` is a DEFAULT: an adapter overrides it whenever the response carries something truer
 * than the mock's generic phrase (a coverage pair, the price the estimate actually used, the
 * sample count behind a percentile).
 *
 * ## `section` is where a card is DRAWN, and it is not where its number comes FROM
 *
 * They agree today — every row is drawn on the tab that names its read — but they are still
 * two questions, and this file answers only the first. `DashboardPage` keeps its own card→read
 * map so that a card moving between tabs cannot silently re-point at another endpoint; the
 * four vendor cards were drawn on **Vendor** off the **finance** read for exactly as long as
 * that row existed.
 */

import type { TranslationPath } from "@/i18n/types";

/**
 * The four tabs. A section is a place on screen — an allocation of vertical space and a URL —
 * and not a request: `audience`, `finance` and `performance` happen to name reads as well,
 * `vendor` names no read of its own (its cards come from finance, its figures from the vendor
 * and series routes).
 */
export type SectionKey = "audience" | "finance" | "vendor" | "performance";

/** The card identities the adapters key their output by. Order is the mockup's. */
export type CardKey =
  | "totalUsers"
  | "newUsers"
  | "activeUsers"
  | "churn"
  | "barred"
  | "totalRevenue"
  | "topups"
  | "vendorSpend"
  | "costPerSong"
  | "mrr"
  | "arr"
  | "vendorBalance"
  | "songsRemaining"
  | "medianSongTime"
  | "songsDelivered"
  | "musicRenders"
  | "musicRenderTime"
  | "systemStatus";

export interface CardSpec {
  /**
   * The card's identity — and, since the console became multilingual, its whole vocabulary:
   * `dashboard.cards.<key>` carries the label and the fallback caption in every language, so
   * neither is spelled here. A key with no entry there does not compile.
   */
  readonly key: CardKey;
  /** The suffix beside the number (`soʻm`, `OK`). Empty for a bare count or a $ figure. */
  readonly unit: string;
  /** Down is good (spend, cost, latency, people blocking the bot): flips the delta colour. */
  readonly invert?: true;
  /** Card has a sparkline well; the series for it comes from `adaptSparks`. */
  readonly spark?: true;
  /** Card carries the mini period selector, and so owns its own window. */
  readonly sel?: true;
}

export interface CardRow {
  /** Which tab draws this row. Every card in it is drawn there, and served by one read. */
  readonly section: SectionKey;
  /**
   * Translation key for the group heading above the row. `null` for a row that continues the
   * one above it — which is the shape the empty string used to carry.
   */
  readonly labelKey: TranslationPath | null;
  /** The mockup's design card width on its 1440px stage: 270.4 for five, 340.5 for four. */
  readonly w: number;
  readonly cards: readonly CardSpec[];
}

/**
 * **Five keys have no row, and all five are deliberately kept.**
 *
 * `churn` lost its card because it printed `churn.blocked` — one of the four numbers the
 * `ChurnCard` leads with — and a page that shows a quantity twice invites the reader to
 * believe whichever copy suits them.
 *
 * `vendorBalance`, `songsRemaining`, `vendorSpend` and `costPerSong` lost the whole ROW they
 * shared, at the top of the Vendor tab, for the same reason four times over: every one of
 * them is printed again a few hundred pixels below, per supplier and in that supplier's own
 * unit, by `VendorCards` — and the per-supplier reading is the truer one, because a balance in
 * dollars and a balance in characters have no honest sum to lead with.
 *
 * The keys stay in `CardKey` because `adaptAudience` and `adaptFinance` still fill them: an
 * adapter is its response's vocabulary, not this file's layout, and pruning a key here would
 * be this file deciding what a response is allowed to say.
 */
export const CARD_ROWS: readonly CardRow[] = [
  {
    section: "audience",
    labelKey: "dashboard.groups.audience",
    w: 340.5,
    cards: [
      {
        key: "totalUsers",
        unit: "",
      },
      {
        key: "newUsers",
        unit: "",
        spark: true,
        sel: true,
      },
      {
        key: "activeUsers",
        unit: "",
        sel: true,
      },
      {
        key: "barred",
        unit: "",
      },
    ],
  },
  {
    section: "finance",
    labelKey: "dashboard.groups.finances",
    w: 340.5,
    cards: [
      {
        /* The RECORDED receipts, summed over the window — the wire's `revenue`, which the
           chart below plots and which the server insists must never be added to the
           delivered × published-price estimate beside it. The card held that estimate until
           the label had to say "est." to keep the two apart; it now holds the same quantity
           the figure under it does, and the estimate keeps its own place on the wire. */
        key: "totalRevenue",
        unit: "soʻm",
        spark: true,
        sel: true,
      },
      {
        key: "topups",
        unit: "",
        sel: true,
      },
      {
        // Its own fixed trailing window, echoed by the response — never the page's period.
        key: "mrr",
        unit: "soʻm",
      },
      {
        // net × 365 ÷ the window's own days. NOT MRR × 12, whatever the mockup captioned it.
        key: "arr",
        unit: "soʻm",
      },
    ],
  },
  {
    section: "performance",
    labelKey: "dashboard.groups.performance",
    w: 270.4,
    cards: [
      {
        key: "medianSongTime",
        unit: "",
        invert: true,
        sel: true,
      },
      {
        key: "songsDelivered",
        unit: "",
        spark: true,
        sel: true,
      },
      {
        key: "musicRenders",
        unit: "",
        sel: true,
      },
      {
        key: "musicRenderTime",
        unit: "",
        invert: true,
        sel: true,
      },
      {
        key: "systemStatus",
        unit: "OK",
      },
    ],
  },
];

/** The rows one tab draws, in page order. */
export function cardRowsFor(section: SectionKey): readonly CardRow[] {
  return CARD_ROWS.filter((row) => row.section === section);
}

/** The keys of the cards one tab draws that own a period selector. */
export function selectableKeysIn(section: SectionKey): readonly CardKey[] {
  return cardRowsFor(section).flatMap((row) =>
    row.cards.filter((card) => card.sel === true).map((card) => card.key),
  );
}
