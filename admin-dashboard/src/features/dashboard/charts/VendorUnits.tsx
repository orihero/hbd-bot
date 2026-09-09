import type { JSX } from "react";

import type { RatioView, Vendor, VendorUnitsPerSongView } from "@/api/dashboard";
import { formatCount } from "@/features/dashboard/adapt";
import { VENDOR_LABEL, rnd, usePalette } from "@/features/dashboard/svg";

/* -------------------------------------------------------------------------- */
/* Geometry                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * This figure is a TABLE OF WHISKERS, and it is the one chart in this folder that is not
 * 651x176. It carries up to three unit families, each with its own heading, its own scale and
 * one row per vendor, and squeezing that into 176 units means either a pitch no tick label
 * survives or type below `fontSize` 8 — and the house rule is that the type never shrinks, the
 * box grows. So the box grows, to exactly twice the standard height, and the two constants are
 * exported so whoever drops this into a card sizes the box with `aspect-[651/352]` rather than
 * guessing at the ratio and letting `preserveAspectRatio` pad it.
 */
export const VENDOR_UNITS_CW = 651;
export const VENDOR_UNITS_CH = 352;

const PAD_X = 20;
/** Vendor names are right-aligned here, so the whisker roots line up whatever the name. */
const LABEL_X = 116;
const X0 = 126;
const LANE = 260;
/** Totals are right-aligned here; per-song figures at the right edge. Both end-anchored so a
 *  seven-figure token count grows leftwards into the lane's slack instead of over the column
 *  beside it. */
const TOTAL_X = 505;
const PERSONG_X = 640;

const CAPTION_Y = 18;
const BODY_TOP = 34;
const GROUP_HEAD = 22;
const ROW = 24;
const FOOT = 14;
const BOTTOM = 10;
const AVAILABLE = VENDOR_UNITS_CH - BODY_TOP - BOTTOM;

/** Rows per family before the tail is announced rather than drawn. */
const MAX_ROWS_PER_GROUP = 4;

/* -------------------------------------------------------------------------- */
/* The three unit families                                                     */
/* -------------------------------------------------------------------------- */

interface Family {
  readonly key: string;
  /** The family's own heading. Never the word "usage": there is no such quantity here. */
  readonly heading: string;
  /** Printed on EVERY row, in both columns, so no number is ever loose from its unit. */
  readonly unit: string;
  readonly total: (row: VendorUnitsPerSongView) => number | null;
  readonly perSong: (row: VendorUnitsPerSongView) => RatioView | null;
}

/**
 * Ordered by meaning — what the model consumed, what the voice consumed, what came out —
 * never by size. Sorting the FAMILIES by magnitude would be sorting three different units
 * against each other, which is the mistake this whole layout exists to make impossible.
 */
const FAMILIES: readonly Family[] = [
  {
    key: "tokens",
    heading: "TOKENS",
    unit: "tokens",
    total: (r) => r.totalTokens,
    perSong: (r) => r.tokensPerSong,
  },
  {
    key: "characters",
    heading: "BILLED CHARACTERS",
    unit: "chars",
    total: (r) => r.billedCharacters,
    perSong: (r) => r.charactersPerSong,
  },
  {
    key: "audio",
    heading: "MILLISECONDS OF AUDIO",
    unit: "ms",
    total: (r) => r.audioMs,
    perSong: (r) => r.audioMsPerSong,
  },
];

interface Row {
  readonly vendor: Vendor;
  readonly total: number;
  readonly perSong: RatioView | null;
}

interface Group {
  readonly family: Family;
  /** Heaviest first. Ranking is within the family and never across families. */
  readonly rows: readonly Row[];
  readonly max: number;
}

/**
 * A vendor that measures none of a family has NO ROW in it — absent, not zero. An LLM bills no
 * characters and a voice bills no tokens, and a zero printed under either would be a claim
 * that the vendor charged us for nothing rather than that it was never asked.
 */
function groupsOf(rows: readonly VendorUnitsPerSongView[]): readonly Group[] {
  const out: Group[] = [];
  for (const family of FAMILIES) {
    const picked: Row[] = [];
    for (const r of rows) {
      const total = family.total(r);
      // A null total is "this vendor measures no such unit"; a non-finite one is not a
      // reading at all. Zero IS a reading — the vendor measured, and measured nothing.
      if (total === null || !Number.isFinite(total)) continue;
      picked.push({ vendor: r.vendor, total, perSong: family.perSong(r) });
    }
    if (picked.length === 0) continue;
    picked.sort((a, b) => b.total - a.total || VENDOR_LABEL[a.vendor].localeCompare(VENDOR_LABEL[b.vendor]));
    out.push({ family, rows: picked, max: picked.reduce((m, r) => Math.max(m, r.total), 0) });
  }
  return out;
}

/**
 * How many rows each family gets to draw. Every family keeps at least one row, and a family
 * whose tail is cut says so on its own footnote line — the drawn rows are the largest, so
 * what is missing is always smaller than what is shown, and the footnote says how many.
 */
function fitRows(groups: readonly Group[]): readonly number[] {
  const shown = groups.map((g) => Math.min(g.rows.length, MAX_ROWS_PER_GROUP));
  const height = (): number =>
    groups.reduce((h, g, i) => {
      const n = shown[i] ?? 0;
      return h + GROUP_HEAD + n * ROW + (n < g.rows.length ? FOOT : 0);
    }, 0);

  // Bounded by construction: every pass removes a row and no count goes below one.
  for (let guard = 0; guard < 64 && height() > AVAILABLE; guard += 1) {
    let worst = -1;
    for (let i = 0; i < shown.length; i += 1) {
      // `>=` breaks a tie towards the LAST family, so successive passes take a row from a
      // different table each time instead of stripping the first one bare.
      if ((shown[i] ?? 0) > 1 && (worst < 0 || (shown[i] ?? 0) >= (shown[worst] ?? 0))) worst = i;
    }
    if (worst < 0) break;
    shown[worst] = (shown[worst] ?? 1) - 1;
  }
  return shown;
}

/**
 * `1 204 tokens/song`, or the reason there is no such number.
 *
 * The two absences are DIFFERENT FACTS and are printed differently. A null ratio means the
 * vendor measured nothing to divide; a present ratio whose `value` is null means nothing was
 * delivered in the window to divide BY. Neither is zero, and a zero here would say a song
 * consumed nothing.
 */
function perSongText(ratio: RatioView | null, unit: string): { text: string; muted: boolean } {
  if (ratio === null) return { text: "not measured", muted: true };
  if (ratio.value === null) return { text: "nothing delivered to divide by", muted: true };
  if (!Number.isFinite(ratio.value)) return { text: "not a reading", muted: true };
  if (ratio.value > 0 && ratio.value < 1) return { text: `<1 ${unit}/song`, muted: false };
  return { text: `${formatCount(ratio.value)} ${unit}/song`, muted: false };
}

/* -------------------------------------------------------------------------- */

export interface VendorUnitsProps {
  /**
   * `VendorResponse.unitsPerSongByVendor`, straight off the wire and in any order — the rows
   * are grouped and ranked here.
   *
   * Every quantity on a row is independently nullable and a null means THIS VENDOR MEASURES
   * NO SUCH UNIT: the row simply does not appear under that family. A `0` is the opposite —
   * a vendor that measured and found nothing — and is drawn as a rooted whisker of no length
   * with its zero printed.
   */
  readonly rows: readonly VendorUnitsPerSongView[];
  /**
   * `VendorResponse.deliveredOrders` — the BARE INT from the vendor route, the denominator
   * every per-song ratio on these rows was computed against.
   *
   * NOT `PerformanceResponse.deliveredOrders`, which is a `TrendView` of the same name on a
   * different route. Passing `.current` off that one would caption this figure with a number
   * counted over a different window; there is deliberately no shared accessor for the two.
   *
   * Zero is a real state and gets said in words: with nothing delivered, every per-song figure
   * is undefined rather than zero.
   */
  readonly deliveredOrders: number;
}

/**
 * What one delivered song CONSUMES from each vendor, in that vendor's own units.
 *
 * The figure claims one thing per row: this vendor recorded this much of this unit over the
 * window, and that came to this much per song delivered. It claims nothing across rows of
 * different families. Tokens, billed characters and milliseconds of audio are incommensurable
 * — there is no exchange rate between them and no total that means anything — so they are
 * drawn as three separate tables with three separate scales and a heading each, and no row
 * can be compared to a row under a different heading however similar the two whiskers look.
 * The single "usage" bar chart this replaces would have been a picture of nothing.
 *
 * **Tokens are a CONSUMPTION measure and never describe a remaining balance.** The count only
 * grows; no reading of it says anything about what is left to spend, and it is not a headroom
 * figure however close to one this figure is rendered. What remains lives in `vendorBalances`
 * — a different table, a different clock, a different question — and a token count printed
 * under a "remaining" heading is spend reported as headroom.
 *
 * The other thing it refuses to say: a per-song figure in a window with no deliveries is
 * undefined, not zero. "Nothing shipped" and "it was free" are not the same sentence and this
 * figure prints the first one in words rather than a tempting `0`.
 */
export function VendorUnits({ rows, deliveredOrders }: VendorUnitsProps): JSX.Element {
  const PAL = usePalette();
  const groups = groupsOf(rows);

  if (groups.length === 0) {
    return <Empty note="no vendor recorded any usage in this window" />;
  }

  const shown = fitRows(groups);
  const delivered = Number.isFinite(deliveredOrders) ? Math.max(0, Math.round(deliveredOrders)) : 0;
  const caption =
    delivered === 0
      ? "NOTHING DELIVERED IN THIS WINDOW · PER-SONG FIGURES ARE UNDEFINED, NOT ZERO"
      : `${formatCount(delivered)} DELIVERED SONGS · RANKED WITHIN EACH UNIT · THE UNITS SHARE NO AXIS`;

  let y = BODY_TOP;

  return (
    <svg
      viewBox={`0 0 ${String(VENDOR_UNITS_CW)} ${String(VENDOR_UNITS_CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label="What one delivered song consumes from each vendor, one table per unit family — tokens, billed characters and milliseconds of audio — each on its own scale"
    >
      <text x={PAD_X} y={CAPTION_Y} fontSize={8} fontWeight={700} fill={PAL.MUT} letterSpacing=".08em">
        {caption}
      </text>

      {groups.map((group, gi) => {
        const n = shown[gi] ?? 0;
        const drawn = group.rows.slice(0, n);
        const hidden = group.rows.length - drawn.length;
        const headY = y + 10;
        const rowTop = y + GROUP_HEAD;
        const groupHeight = GROUP_HEAD + n * ROW + (hidden > 0 ? FOOT : 0);
        y += groupHeight;

        return (
          <g key={group.family.key}>
            <text
              x={PAD_X}
              y={headY}
              fontSize={9}
              fontWeight={700}
              fill={PAL.D0}
              letterSpacing=".1em"
            >
              {group.family.heading}
            </text>
            <text x={TOTAL_X} y={headY} fontSize={8} fontWeight={700} fill={PAL.MUT} textAnchor="end" letterSpacing=".08em">
              TOTAL
            </text>
            <text x={PERSONG_X} y={headY} fontSize={8} fontWeight={700} fill={PAL.MUT} textAnchor="end" letterSpacing=".08em">
              PER SONG
            </text>
            {/* The rule under a heading is what makes the grouping a grouping: it says the
                scale below it starts here and does not continue past the next one. */}
            <line
              x1={PAD_X}
              y1={headY + 5}
              x2={PERSONG_X}
              y2={headY + 5}
              stroke={PAL.GRID}
              strokeWidth={1}
            />

            {drawn.map((row, i) => {
              const ry = rowTop + i * ROW + ROW / 2;
              const hero = i === 0;
              // Scale is the family's own heaviest row. A family whose rows are all zero has
              // no length to give anyone; the printed zeros carry it instead.
              const len = group.max > 0 ? (LANE * row.total) / group.max : 0;
              const cap = 3 + rnd(i + 1, gi + 2) * 1.6;
              const ink = hero ? PAL.D0 : PAL.D1;
              const totalText = `${formatCount(row.total)} ${group.family.unit}`;
              const per = perSongText(row.perSong, group.family.unit);

              return (
                <g key={`${group.family.key}-${row.vendor}`}>
                  <text
                    x={LABEL_X}
                    y={ry + 3}
                    fontSize={8}
                    fontWeight={700}
                    fill={hero ? PAL.DEEP : PAL.MUT}
                    textAnchor="end"
                    letterSpacing=".08em"
                  >
                    {VENDOR_LABEL[row.vendor]}
                  </text>
                  {/* The root cap: every whisker starts at the same x, so length is the only
                      thing that differs between two rows of the same family. */}
                  <line
                    x1={X0}
                    y1={ry - cap}
                    x2={X0}
                    y2={ry + cap}
                    stroke={PAL.D5}
                    strokeWidth={0.8}
                  />
                  {len > 0 && (
                    <line
                      x1={X0}
                      y1={ry}
                      x2={X0 + len}
                      y2={ry}
                      stroke={ink}
                      strokeWidth={hero ? 1.4 : 1.1}
                      opacity={0.6 + rnd(i + 3, gi + 5) * 0.4}
                    />
                  )}
                  <circle
                    cx={X0 + len}
                    cy={ry}
                    r={hero ? 3.4 : 2.2}
                    fill={hero ? PAL.ACCENT : ink}
                    stroke={hero ? PAL.D0 : "none"}
                    strokeWidth={hero ? 1.1 : 0}
                  >
                    <title>
                      {`${VENDOR_LABEL[row.vendor]} — ${totalText} in this window · ${per.text}`}
                    </title>
                  </circle>
                  <text
                    x={TOTAL_X}
                    y={ry + 3}
                    fontSize={11}
                    fontWeight={700}
                    fill={hero ? PAL.DEEP : PAL.D0}
                    textAnchor="end"
                  >
                    {totalText}
                  </text>
                  <text
                    x={PERSONG_X}
                    y={ry + 3}
                    fontSize={9}
                    fontWeight={600}
                    fill={per.muted ? PAL.D3 : PAL.D2}
                    textAnchor="end"
                  >
                    {per.text}
                  </text>
                </g>
              );
            })}

            {hidden > 0 && (
              <text
                x={X0}
                y={rowTop + n * ROW + 9}
                fontSize={8}
                fontWeight={600}
                fill={PAL.D3}
                letterSpacing=".04em"
              >
                {`+${String(hidden)} more vendor${hidden === 1 ? "" : "s"}, each smaller than the rows above`}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Three empty tables with three empty scales would read as three vendors that consumed
 * nothing. Nobody measured anything, which is a different sentence, so it is the only one
 * drawn.
 */
function Empty({ note }: { readonly note: string }): JSX.Element {
  const PAL = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(VENDOR_UNITS_CW)} ${String(VENDOR_UNITS_CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={note}
    >
      <text
        x={VENDOR_UNITS_CW / 2}
        y={VENDOR_UNITS_CH / 2}
        fontSize={11}
        fontWeight={600}
        fill={PAL.D3}
        textAnchor="middle"
        letterSpacing=".04em"
      >
        {note}
      </text>
    </svg>
  );
}
