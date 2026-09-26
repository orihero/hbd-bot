import type { Vendor } from "@/api/dashboard";
import { useThemeStore } from "@/state/theme";

/**
 * The ink ramp the mockup draws with. These are the same values as the `--d*` tokens in
 * tokens.css, repeated here because SVG presentation attributes (`stroke`, `fill`) cannot
 * take a `var()` through a Tailwind class the way a CSS property can.
 *
 * That duplication is why there are now TWO of these and a hook to pick between them: a chart
 * drawn from literals is the one part of the app a `[data-theme]` selector cannot reach, so
 * without this every panel would keep its light-palette ink on a dark card — a #0D0D12 series
 * on a #16181D ground, which is a chart nobody can see. Read them through `usePalette()`;
 * importing either constant directly re-introduces exactly that bug.
 */
export interface PaletteRamp {
  readonly D0: string;
  readonly D1: string;
  readonly D2: string;
  readonly D3: string;
  readonly D4: string;
  readonly D5: string;
  readonly D6: string;
  readonly PAPER: string;
  readonly GRID: string;
  readonly ACCENT: string;
  readonly DEEP: string;
  readonly MUT: string;
}

export const PAL_LIGHT: Palette = {
  D0: "#0D0D12",
  D1: "#3A3B3F",
  D2: "#5B5A64",
  D3: "#8D8D8D",
  D4: "#B4B4B7",
  D5: "#D3D3D4",
  D6: "#E8E8E8",
  PAPER: "#FFFFFF",
  GRID: "rgba(0,0,0,.06)",
  ACCENT: "#75FC96",
  DEEP: "#218C3B",
  MUT: "#666D80",
  // Threshold inks — see the block at the foot of this file, and `--th-*` in tokens.css.
  OK: "#14663F",
  WARN: "#7A4B00",
  BAD: "#A11221",
  UNKNOWN: "#5B5A64",
  HATCH: "#8D8D8D",
};

/**
 * The same roles under the dark palette, kept in step with `tokens.css`'s dark block
 * by hand. The ramp is REVERSED rather than darkened — D0 is the ink nearest the foreground
 * in both palettes — and `PAPER` is the card, not the page: these charts sit on `--card`.
 */
export const PAL_DARK: Palette = {
  D0: "#F2F3F5",
  D1: "#CBD0D9",
  D2: "#A3AAB7",
  D3: "#7E8695",
  D4: "#5C6470",
  D5: "#3E444E",
  D6: "#272B33",
  PAPER: "#16181D",
  GRID: "rgba(255,255,255,.07)",
  ACCENT: "#75FC96",
  DEEP: "#7BF39D",
  MUT: "#949AA8",
  // Derived against this palette's own PAPER (#16181D), not lightened from the light pair:
  // #7A4B00 is 1.6:1 here and #A11221 is 2.2:1, so reusing them would print the two states
  // that matter most as two indistinguishable smudges.
  OK: "#43C98E",
  WARN: "#F8C46F",
  BAD: "#FF9AA3",
  UNKNOWN: "#A3AAB7",
  HATCH: "#7E8695",
};

/**
 * The ramp for the palette currently on screen.
 *
 * A hook rather than a module-level read, so a chart re-renders when the operator flips the
 * toggle. Every chart component calls it once at the top and shadows the old `PAL` name.
 */
export function usePalette(): Palette {
  return useThemeStore((state) => (state.resolved === "dark" ? PAL_DARK : PAL_LIGHT));
}

/**
 * Hash-based jitter for the hand-drawn rung/tick charts. Deterministic on purpose: the
 * jitter is part of the drawing, so it must not reshuffle on every render.
 */
export function rnd(i: number, k: number): number {
  return Math.abs(((i * 73856093) ^ (k * 19349663)) % 1000) / 1000;
}

/** Soʻm amounts, shortened the way the mockup shortens them. */
export function uzs(v: number): string {
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return String(Math.round(v / 1e3)) + "k";
  return String(v);
}

/**
 * The cost-split ladder's length, in ticks: the guide rule is drawn to `X0 + LANE * PX`, so
 * this is the geometry's number and the adapter sizes its tick unit against it. Shared so the
 * unit, the drawing and the caption cannot each hold a different one.
 */
export const COST_SPLIT_LANE = 30;

/** Smallest 1–2–5 step that keeps `max` inside `rungs` rungs. Never zero. */
export function niceStep(max: number, rungs: number): number {
  if (!(max > 0) || rungs <= 0) return 1;
  const rough = max / rungs;
  const mag = 10 ** Math.floor(Math.log10(rough));
  for (const m of [1, 2, 5]) if (rough <= m * mag) return m * mag;
  return 10 * mag;
}

/**
 * Above this many rungs in the tallest column the ladder is finer than a hairline, and a rung
 * nobody can count is texture rather than measurement. Shared by the two ladder charts, which
 * held a byte-identical copy each.
 */
export const RUNG_CAP = 160;

/** Which levels get a line. The topmost is always one — the value label hangs off it. */
export function rungIndices(n: number, stride: number): readonly number[] {
  const out: number[] = [];
  for (let k = 0; k < n; k += stride) out.push(k);
  if (out[out.length - 1] !== n - 1) out.push(n - 1);
  return out;
}

/**
 * Which way a delta string reads. `invert` flips it for metrics where a rise is bad
 * (vendor spend, cost per song, latency).
 */
export function dirOf(d: string, invert?: boolean): "" | "up" | "down" {
  if (!d) return "";
  const neg = d.charAt(0) === "-";
  return (invert ? neg : !neg) ? "up" : "down";
}

/* ===========================================================================
 * THRESHOLD INKS — the vendor-balance traffic light
 * ===========================================================================
 *
 * These five roles are declared TWICE, here and as `--th-*` in `src/styles/tokens.css`, and
 * THE TWO FILES MUST MOVE TOGETHER. The duplication is the same one that forced `PAL_LIGHT`
 * and `PAL_DARK` into existence: an SVG presentation attribute cannot take a `var()` through
 * a Tailwind class, so a chart drawn from tokens alone would keep its light ink on a dark
 * card. Read them here through `usePalette()`; read them in HTML (a caption, a legend chip)
 * as `var(--th-ok)` and friends. Change one file and you have introduced a theme bug that
 * only shows up in the half of the UI you did not look at.
 *
 * Why `OK` is not `ACCENT`: `#75FC96` already means "this is the mark the figure is about" on
 * every chart in this folder — the last dot of the sign-ups line, the hero rung of the
 * funnel. Painting health with it makes emphasis and health the same statement, so a healthy
 * vendor would read as the vendor the chart is about. `OK` is a separate, deeper green,
 * distinguishable from `ACCENT`/`DEEP` by lightness as well as hue (1.6:1 against them in
 * either palette) rather than by hue alone.
 *
 * Measured against each palette's own `PAPER` — `#FFFFFF` light, `#16181D` dark — because
 * these charts sit on the card, not the page:
 *
 *   light: OK #14663F 7.0:1 · WARN #7A4B00 7.4:1 · BAD #A11221 8.0:1 · UNKNOWN #5B5A64 6.8:1
 *   dark:  OK #43C98E 8.4:1 · WARN #F8C46F 11.1:1 · BAD #FF9AA3 8.8:1 · UNKNOWN #A3AAB7 7.6:1
 *
 * All four clear AA at `fontSize` 8, which is the size a threshold word is actually printed
 * at here. The bright `--warn` (#F5A524) and `--required` (#E93544) do NOT clear it and are
 * deliberately absent: they are GROUNDS in this design system, and the readable ink member of
 * each family is the `-deep` one, which is what `WARN`/`BAD` are. The dark pair is not the
 * light pair reused — #7A4B00 is 1.6:1 on `#16181D` and #A11221 is 2.2:1, i.e. invisible —
 * it is the dark `-deep` pair, derived against the dark card.
 *
 * The three coloured inks are near-isoluminant WITHIN a palette (1.0–1.3:1 between them), so
 * a monochrome or dichromatic reader cannot separate them by ink at all. That is deliberate
 * and it is why `thresholdLabel` exists: the colour is a second channel, never the only one.
 */
export interface ThresholdInks {
  /** Health green. NEVER `ACCENT` — see the note above. */
  readonly OK: string;
  /** Amber ink (the `-deep` member of the warn family), not the amber ground. */
  readonly WARN: string;
  /** Red ink (the `-deep` member of the required family), not the alarm ground. */
  readonly BAD: string;
  /**
   * Achromatic, and an existing grey off the ramp (`D2`): "we do not know" is the ABSENCE of
   * a reading, and a hue would make it look like a fourth severity between amber and green.
   */
  readonly UNKNOWN: string;
  /**
   * The fainter grey (`D3`) the unmeasured track's diagonals are stroked in. A texture of
   * hairlines reads lighter than a solid line of the same ink, so the track is one step
   * darker than a gridline and one step lighter than the word beside it.
   */
  readonly HATCH: string;
}

export type Palette = PaletteRamp & ThresholdInks;

/**
 * The four states a vendor balance can be in. `unknown` is a STATE, not an error case: it is
 * the common one. `uncapped`, `never answered`, `not reported` and `stale` all land here, and
 * none of them is a level — painting them green makes an empty account look funded, painting
 * them red sends the operator to top up an account that was never low.
 */
export type ThresholdState = "ok" | "warn" | "bad" | "unknown";

/**
 * The owner's boundaries, in songs of cover, exported so a caption can quote the same numbers
 * the drawing used. Both are EXCLUSIVE lower bounds — `< 30` is bad, `< 100` is warn — which
 * is why a balance of exactly 30 is amber and exactly 100 is green.
 */
export const THRESHOLD_BAD_BELOW = 30;
export const THRESHOLD_WARN_BELOW = 100;

/**
 * The traffic light, in one place, because five components each holding their own `< 30`
 * is five chances for the dashboard to disagree with itself about whether a vendor is out.
 *
 * `null` is unknown and so is any non-finite number: a NaN that fell out of
 * `balance / costPerSong` is not a reading, and the one thing worse than not knowing a
 * balance is drawing a colour for a balance nobody computed. Zero IS a reading — an account
 * that can fund no songs at all is `bad`, not unknown.
 */
export function thresholdOf(songsOfCover: number | null): ThresholdState {
  if (songsOfCover === null || !Number.isFinite(songsOfCover)) return "unknown";
  if (songsOfCover < THRESHOLD_BAD_BELOW) return "bad";
  if (songsOfCover < THRESHOLD_WARN_BELOW) return "warn";
  return "ok";
}

/**
 * The WORD that must accompany the colour, everywhere, without exception — the three coloured
 * inks are near-isoluminant by design, so the word is the channel a colour-blind or
 * monochrome reader actually has. Short enough to sit at `fontSize` 8 beside a dot.
 *
 * `unmeasured` says what we know (nothing) rather than why; the reason — uncapped, stale,
 * never answered — is data the caller has and this module does not, and it belongs beside
 * this word, not instead of it.
 */
export function thresholdLabel(state: ThresholdState): string {
  switch (state) {
    case "ok":
      return "healthy";
    case "warn":
      return "low";
    case "bad":
      return "critical";
    case "unknown":
      return "unmeasured";
  }
}

/** The ink for a state, off the palette on screen. Never index the palette by hand. */
export function thresholdInk(palette: Palette, state: ThresholdState): string {
  switch (state) {
    case "ok":
      return palette.OK;
    case "warn":
      return palette.WARN;
    case "bad":
      return palette.BAD;
    case "unknown":
      return palette.UNKNOWN;
  }
}

/* ---------------------------------------------------------------------------
 * The vendors, named once
 * ------------------------------------------------------------------------ */

/**
 * What a vendor is CALLED on this page, in one table.
 *
 * The Vendor tab stacks the balance meters, the poller-freshness rows and the unit tables
 * one under the other, and the header's balance chips sit above all three. Every one of those
 * names the same accounts, so every one of them naming them from its own copy of this map is
 * how `OPENAI` comes to be `OPENAI-COMPATIBLE` in one figure and not in the one below it —
 * two names for one account, in one screenful, and no way for the reader to know they are the
 * same supplier.
 *
 * `provider` on the wire is finer than this (it distinguishes the two OpenRouter keys) and
 * rides the `<title>` instead; a `Record<Vendor, string>` means the day a fifth vendor lands
 * this is a type error rather than a row labelled `undefined`.
 */
export const VENDOR_LABEL: Record<Vendor, string> = {
  elevenlabs: "ELEVENLABS",
  openrouter: "OPENROUTER",
  gemini: "GEMINI",
  openai_compatible: "OPENAI",
  fake: "FAKE",
};

/* ---------------------------------------------------------------------------
 * How old is too old — the fourth unmeasured state's other half
 * ------------------------------------------------------------------------ */

/**
 * Past this a vendor balance is a MEMORY of a balance rather than a balance, and drawing it
 * as one lets a stopped poller read as a funded account for as long as nobody checks the job.
 *
 * It lives HERE, beside `thresholdOf`, for exactly the reason that function does: "stale"
 * is a verdict three different places on this page reach independently — the header's balance
 * chip in `adapt.ts`, the meter lanes, and the tick `PollerFreshness` draws its axis against —
 * and three copies of `7 * 86_400_000` is three chances for the header to call a figure stale
 * while the meter beside it paints the same figure green. One deployment, one cutoff.
 */
export const BALANCE_STALE_MS = 7 * 86_400_000;

/**
 * `12m`, `6h`, `3d` — the age of a cached number, not a duration anybody is timing.
 *
 * Single-sourced with `BALANCE_STALE_MS` and for the same reason: the chip and the lane print
 * the same age about the same poll, and two roundings would eventually disagree by an hour.
 */
export function ageLabel(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 60) return `${String(minutes)}m`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${String(hours)}h` : `${String(Math.round(hours / 24))}d`;
}

/** `null` for anything the clock cannot read, so a bad instant never becomes a fake age. */
export function parseInstant(iso: string): number | null {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/* ---------------------------------------------------------------------------
 * The unmeasured track
 * ------------------------------------------------------------------------ */

/** A box in user units. `width`/`height` below 0 are treated as 0 rather than mirrored. */
export interface HatchBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** One diagonal, ready to spread onto a `<line>`. */
export interface HatchLine {
  readonly x1: number;
  readonly y1: number;
  readonly x2: number;
  readonly y2: number;
}

/** Default spacing between diagonals, in user units. Coarse enough to read as texture. */
export const HATCH_GAP = 4;

/**
 * The unmeasured track, as STROKED DIAGONALS rather than an SVG `<pattern>` fill.
 *
 * A `<pattern>` would have to be painted through `fill`, and this folder has exactly one rule
 * that admits no exceptions: nothing is a filled shape. So there is no exception here either
 * — the hatch is a list of `<line>`s, clipped to the box, stroked in `PAL.HATCH` at the same
 * hairline weight as everything else. It costs a handful of extra elements per track and buys
 * a figure that stays inside the idiom, keeps working when the caller reorders defs, and can
 * be aria-labelled per track instead of once per document.
 *
 * Deterministic and free of jitter on purpose: a hatch is the one mark in these charts that
 * means "no reading", and a hand-drawn wobble would make it look like data.
 *
 * The diagonals run bottom-left to top-right and are clipped by shortening, not by a clip
 * path, so the result is safe to drop anywhere.
 */
export function hatchLines(box: HatchBox, gap: number = HATCH_GAP): readonly HatchLine[] {
  const w = Number.isFinite(box.width) ? Math.max(0, box.width) : 0;
  const h = Number.isFinite(box.height) ? Math.max(0, box.height) : 0;
  const step = Number.isFinite(gap) && gap > 0 ? gap : HATCH_GAP;
  if (w <= 0 || h <= 0) return [];

  const out: HatchLine[] = [];
  const right = box.x + w;
  const bottom = box.y + h;
  // Start a full box-height to the left so the first diagonals still cross the left edge;
  // without that the top-left corner is bare and the track reads as half-hatched.
  for (let c = -h; c < w; c += step) {
    let x1 = box.x + c;
    let y1 = bottom;
    let x2 = box.x + c + h;
    let y2 = box.y;
    if (x1 < box.x) {
      // Slope is exactly -1, so clipping x by d moves y by d.
      const d = box.x - x1;
      x1 = box.x;
      y1 = bottom - d;
    }
    if (x2 > right) {
      const d = x2 - right;
      x2 = right;
      y2 = box.y + d;
    }
    if (x2 - x1 > 0.01) out.push({ x1, y1, x2, y2 });
  }
  return out;
}

/* ---------------------------------------------------------------------------
 * The segmented share rule
 * ------------------------------------------------------------------------ */

/**
 * Below this drawn length a segment is thinner than the hairline it would be drawn with, so
 * it is not a mark at all. Segments under it keep their true geometry and are FLAGGED — see
 * `ShareSegment.tooSmall`.
 */
export const SHARE_MIN_PX = 0.75;

export interface ShareSegment {
  /**
   * Position in the INPUT array. Preserved so a caller can look the category's name back up:
   * nothing is dropped or reordered by this function, including the zero-width ones.
   */
  readonly index: number;
  /** The value as passed, after the non-finite/negative floor described on `segmentedShare`. */
  readonly value: number;
  /** `value / total`, in 0..1. Zero when the total is zero — never NaN. */
  readonly share: number;
  /** Start of the segment along the lane, from the lane's own origin (0). */
  readonly offset: number;
  /** Drawn length. Exact, never rounded: consecutive offsets tile the lane with no drift. */
  readonly length: number;
  /**
   * The segment is real but too thin to see (`length < SHARE_MIN_PX`). It is returned anyway,
   * flagged, because silently dropping it turns "a language two accounts use" into "a
   * language nobody uses" — a claim the payload never made. The caller decides what to do:
   * name it in the legend, fold it into a "+N more" tail, print it as a footnote. What it may
   * not do is pretend it was not there.
   */
  readonly tooSmall: boolean;
}

export interface SegmentedShare {
  /** Sum of the floored values. Zero for empty input or for input that is all zeroes. */
  readonly total: number;
  /** The lane length the offsets were computed against, floored at 0. */
  readonly width: number;
  /** One per input value, in input order. Empty only for empty input. */
  readonly segments: readonly ShareSegment[];
  /**
   * Where to put a divider tick: the boundary between each pair of ADJACENT DRAWN segments.
   * Zero-width segments contribute no divider (two ticks at the same x is a thicker tick, not
   * a boundary), and there is never a tick at 0 or at `width` — the lane's own ends are the
   * ends. Empty for a single category at 100%, which is the correct drawing: one unbroken
   * rule, because there is nothing to divide it from.
   */
  readonly dividers: readonly number[];
}

/**
 * Geometry for the segmented share rule — the language mix, the cost-provenance strip. One
 * hairline lane, split by ticks into proportional stroked runs. It DRAWS NOTHING: the caller
 * owns the stroke, the ink and the labels, which is what lets the same geometry serve a
 * figure whose segments are ordered by size and one whose segments are ordered by meaning.
 *
 * Shares are computed against the sum of the values PASSED IN. That makes the caller
 * responsible for a real decision: `languageMix.share` has the block's own `accounts` as its
 * denominator, so a lane built from the top five languages is a share of those five, not of
 * all accounts, and the caption must say so or add the remainder as a sixth value.
 *
 * Non-finite and negative values are floored to 0 rather than skipped — a share of a negative
 * number is not a length, and dropping the entry would renumber every index after it.
 *
 * The three cases that must not surprise anyone:
 *  * one category at 100% → one segment spanning the lane, and NO dividers;
 *  * a category that rounds to nothing → returned with its true sub-pixel length and
 *    `tooSmall: true`, never dropped;
 *  * empty input, an all-zero total, or a non-positive width → `segments` sized to the input,
 *    every length 0, `total` 0. There is no lane to draw and the caller shows its empty state.
 */
export function segmentedShare(values: readonly number[], width: number): SegmentedShare {
  const w = Number.isFinite(width) ? Math.max(0, width) : 0;
  const safe = values.map((v) => (Number.isFinite(v) && v > 0 ? v : 0));
  const total = safe.reduce((sum, v) => sum + v, 0);

  if (total <= 0 || w <= 0) {
    return {
      total,
      width: w,
      segments: safe.map((value, index) => ({
        index,
        value,
        share: total > 0 ? value / total : 0,
        offset: 0,
        length: 0,
        tooSmall: value > 0,
      })),
      dividers: [],
    };
  }

  const segments: ShareSegment[] = [];
  const dividers: number[] = [];
  let cursor = 0;
  let drewSomethingBefore = false;
  for (const [index, value] of safe.entries()) {
    const share = value / total;
    const length = share * w;
    const drawn = length >= SHARE_MIN_PX;
    // A divider marks a boundary between two things that were both drawn. Emitting one for a
    // zero-width neighbour would put a tick where the eye reads a split that is not there.
    if (drawn && drewSomethingBefore) dividers.push(cursor);
    segments.push({ index, value, share, offset: cursor, length, tooSmall: value > 0 && !drawn });
    cursor += length;
    drewSomethingBefore = drewSomethingBefore || drawn;
  }
  return { total, width: w, segments, dividers };
}

/* ---------------------------------------------------------------------------
 * The stepped series with holes
 * ------------------------------------------------------------------------ */

/** A run of consecutive recorded buckets, already stepped. */
export interface StepRun {
  /** Index of the first and last bucket in the run, inclusive — for titles and end labels. */
  readonly from: number;
  readonly to: number;
  /** The run's own path. Draw one `<path>` per run; NEVER concatenate two runs' `d`. */
  readonly d: string;
  /** The same geometry as points, for callers that want dots on the treads. */
  readonly points: readonly (readonly [number, number])[];
}

/** A stretch of buckets with no reading. The line does not cross it. */
export interface StepGap {
  /** First and last MISSING bucket, inclusive. */
  readonly from: number;
  readonly to: number;
  /** The hole's extent along x, so a caller can mark it ("not recorded") instead of hiding it. */
  readonly x1: number;
  readonly x2: number;
}

export interface StepSeries {
  readonly runs: readonly StepRun[];
  readonly gaps: readonly StepGap[];
}

/**
 * Geometry for a step line that BREAKS at missing buckets — the DAU/WAU/MAU series, where a
 * night the snapshot job missed is absent from the array.
 *
 * A `null` bucket is not zero and a gap is not a join: interpolating across the hole invents
 * a reading, and plotting zero claims nobody used the bot that day. Both are lies the drawing
 * would tell more confidently than any caption could take back, so this returns one run per
 * unbroken stretch and leaves the holes as holes — plus `gaps`, so a caller can say in words
 * where the recorder stopped rather than leaving a mysterious blank.
 *
 * A step rather than a line because these are DAILY SNAPSHOTS, not samples of a continuous
 * quantity: the value describes the whole bucket, so it is drawn as a tread across the whole
 * bucket, and the change between two days is a riser at the boundary, not a slope through it.
 *
 * `x` must accept FRACTIONAL indices — every mapper in this folder is linear in the index, so
 * they all do — because a tread runs from `x(i - 0.5)` to `x(i + 0.5)`. The two outermost
 * edges are clamped to `x(0)` and `x(n - 1)`, so a series never draws half a bucket outside
 * its own axis; the first and last treads are therefore half-width, which is honest — the
 * axis ends where the data ends.
 *
 * A one-bucket run still draws: a single tread, the width of its bucket. A day that stands
 * alone between two outages is a measurement, and dropping it because a path needs two points
 * would delete the only reading in the window. The one case with no bucket width to use — a
 * series of length ONE, where `x(0)` and `x(n - 1)` are the same point — gets a
 * `STEP_MIN_TREAD`-wide tread centred on it instead of the zero-length path the arithmetic
 * would otherwise produce, so callers never have to special-case "we have exactly one day".
 */
/**
 * Width of the fallback tread for a reading with no bucket width — see `stepPoints`. Short
 * enough to read as one bucket rather than a bar, long enough to be a mark at `CW` 651.
 */
export const STEP_MIN_TREAD = 6;

export function stepPoints(
  values: readonly (number | null)[],
  x: (index: number) => number,
  y: (value: number) => number,
): StepSeries {
  const n = values.length;
  if (n === 0) return { runs: [], gaps: [] };

  const lo = x(0);
  const hi = x(n - 1);
  const left = (i: number): number => (i <= 0 ? lo : Math.max(lo, x(i - 0.5)));
  const right = (i: number): number => (i >= n - 1 ? hi : Math.min(hi, x(i + 0.5)));
  /** The reading at `i`, or `null` for a bucket that was never recorded. */
  const at = (i: number): number | null => {
    const v = values[i];
    return v !== null && v !== undefined && Number.isFinite(v) ? v : null;
  };

  const runs: StepRun[] = [];
  const gaps: StepGap[] = [];
  let i = 0;
  while (i < n) {
    if (at(i) === null) {
      const from = i;
      while (i < n && at(i) === null) i += 1;
      gaps.push({ from, to: i - 1, x1: left(from), x2: right(i - 1) });
      continue;
    }
    const from = i;
    const points: (readonly [number, number])[] = [];
    let v = at(i);
    while (v !== null) {
      const yv = y(v);
      let l = left(i);
      let r = right(i);
      // Only reachable when the mapper gives the bucket no width at all — a one-bucket series,
      // where x(0) and x(n-1) are the same point. A zero-length path is not a reading anyone
      // can see, and the reading exists.
      if (r - l <= 0) {
        const c = x(i);
        l = c - STEP_MIN_TREAD / 2;
        r = c + STEP_MIN_TREAD / 2;
      }
      // Two points per bucket: the tread's ends. The riser to the next bucket is implicit —
      // consecutive treads share an x, so the straight line between them is vertical.
      points.push([l, yv], [r, yv]);
      i += 1;
      // Past the end this reads `undefined` and stops the run, which is the same statement as
      // a hole: there is no bucket there.
      v = at(i);
    }
    const d = points
      .map(([px, py], k) => (k === 0 ? "M" : "L") + px.toFixed(1) + " " + py.toFixed(1))
      .join(" ");
    runs.push({ from, to: i - 1, d, points });
  }
  return { runs, gaps };
}
