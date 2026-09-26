import type { JSX } from "react";

import type { Language, LanguageMixEntryView, RatioView } from "@/api/dashboard";
import { formatCount } from "@/features/dashboard/adapt";
import { CW } from "@/features/dashboard/data";
import { segmentedShare, usePalette, type Palette, type ShareSegment } from "@/features/dashboard/svg";

/**
 * F11 · the language demography, as a SEGMENTED SHARE RULE.
 *
 * One hairline lane the width of the section, cut by divider ticks into proportional runs,
 * each named above with its count and its share. Not a pie: a reader cannot compare two
 * wedges, and the second question this figure is always asked — "is Russian bigger than
 * Uzbek Cyrillic?" — is a comparison. Not a bar chart either: bars would claim four
 * independent measurements when this is ONE population cut four ways, and the whole point of
 * the rule is that its length is the population.
 *
 * The two things the caption must get right, because both are easy to state wrongly and
 * neither is recoverable by the reader:
 *
 *  * this is `users.ui_language` — the language the customer READS THE BOT IN. It is NOT the
 *    language the song is sung in (`briefs.output_language`), which is chosen per brief and
 *    independently. A customer reading the bot in Russian orders Uzbek songs every day.
 *  * the denominator is the payload's own `accounts`, never the sum of the segments drawn
 *    here. They are equal while the payload is complete and stop being equal the moment
 *    anything truncates — so a caller passing the top few languages gets the rest drawn as an
 *    explicit "not listed" run rather than a lane that quietly re-bases itself to 100%.
 *
 * A share is also a count. `uz_latn` is `NOT NULL DEFAULT`, so an account created by an order
 * alone sits in it without anybody having chosen it: this is a true count of what the bot WILL
 * SPEAK, not a survey of preference, and every segment prints its accounts beside its percent.
 *
 * A segment too thin to draw is NAMED, never dropped — "a language two accounts use" and "a
 * language nobody uses" are different facts, and `segmentedShare` flags the first for exactly
 * this reason. The same line catches segments that had no room for a label above the lane.
 *
 * SIZING — this figure is designed to sit FULL WIDTH under a section heading, not inside a
 * chart card. Its viewBox is 651 × 84, roughly eight times wider than tall; the lane needs the
 * whole width or the labels collide and half of them fall into the footnote. Give it a plain
 * full-width block: it sets `width: 100%` and no height, so the box takes its height from the
 * viewBox's own ratio (about 84px at a 651px column). Dropping it into the 651 × 176 slot the
 * other charts use would leave it floating in half a card.
 */

/** Left/right margin. The lane is the rest, and it is the population. */
const PAD = 14;
const LANE_X = PAD;
const LANE_W = CW - PAD * 2;

/** viewBox height. Two label lines, the lane, the sliver line, the caption. */
const VH = 84;

const NAME_Y = 16;
const STAT_Y = 27;
const ELBOW_Y = 33;
const LANE_Y = 46;
const SLIVER_Y = 64;
const CAPTION_Y = 77;

/** Rough advance widths at the sizes below — enough to keep two labels from overprinting. */
const NAME_ADVANCE = 5.1;
const STAT_ADVANCE = 4.4;
const LABEL_GAP = 12;

/**
 * The four UI languages in full.
 *
 * `uz_latn` and `uz_cyrl` are two SCRIPTS of one language and are never collapsed into
 * "Uzbek": a customer who reads one cannot necessarily read the other, which is the whole
 * difference between a bot somebody can use and one they cannot. Declared here rather than
 * imported from `features/users`, whose copy is keyed on `@/api/users`'s enum — the dashboard
 * has its own `Language` for the module-cycle reason documented in `api/dashboard.ts`, and a
 * chart in this folder depends on nothing outside it.
 */
const LANGUAGE_LABELS: Readonly<Record<Language, string>> = {
  uz_latn: "Uzbek (Latin)",
  uz_cyrl: "Uzbek (Cyrillic)",
  ru: "Russian",
  en: "English",
};

/** What the "not listed" run is called wherever it is printed. Not a language. */
const REMAINDER_LABEL = "not listed";

export interface LanguageMixProps {
  /**
   * `AudienceResponse.languageMix.languages`, verbatim and largest first.
   *
   * Each entry's `share` is the SERVER's, whose denominator is `accounts` below — it is
   * printed as given rather than recomputed from the lane, so a truncated list cannot silently
   * re-base its own percentages. A `share.value` of `null` is "not computed", not zero.
   *
   * A language nobody uses is ABSENT from this array, not present at zero: this is a fully
   * visited population, so the gap is presentational and not a missing measurement — no
   * segment is drawn for it and nothing here says it is unmeasured.
   *
   * Empty means the block reported no languages at all, which with a positive `accounts` is a
   * contract the drawing refuses to guess at and says so in words.
   */
  readonly languages: readonly LanguageMixEntryView[];
  /**
   * `AudienceResponse.languageMix.accounts` — the population the split is a split OF, and the
   * denominator of every share printed here.
   *
   * If it exceeds the sum of `languages`, the difference is drawn as an explicit "not listed"
   * run so the lane still measures the whole population. It is never the other way round in a
   * complete payload; if it is (a caller summing more than it declared), the lane falls back
   * to the sum it was given and the caption says which denominator it used.
   */
  readonly accounts: number;
}

/** One run of the lane, whether it is a language or the unlisted remainder. */
interface Entry {
  readonly key: string;
  readonly name: string;
  readonly count: number;
  /** `1 204 · 62%` — the count first, because at this volume the count is the measurement. */
  readonly stat: string;
  readonly ink: string;
  readonly dash: string | undefined;
}

/** A label that found room above the lane. */
interface Placed {
  readonly entry: Entry;
  readonly segment: ShareSegment;
  readonly x: number;
}

export function LanguageMix({ languages, accounts }: LanguageMixProps): JSX.Element {
  // The ramp for the palette on screen. A figure drawn from a module-level constant keeps its
  // light ink on a dark card; see `usePalette`.
  const PAL = usePalette();

  // The empty renderings come before the geometry: a lane with no runs is a rule, and a rule
  // is a claim that the population was split — which is exactly what has not happened here.
  const population = Number.isFinite(accounts) && accounts > 0 ? Math.round(accounts) : 0;
  if (languages.length === 0) {
    return population > 0 ? (
      <Empty
        headline={`no language reported for ${formatCount(population)} accounts`}
        note="the block counted the population but returned no split"
      />
    ) : (
      <Empty
        headline="no accounts to split"
        note="nobody has been recorded in this window"
      />
    );
  }

  const listed = languages.reduce((sum, l) => sum + Math.max(0, l.accounts), 0);
  // A payload that declares fewer accounts than its own entries sum to is not one this figure
  // can re-base; it keeps the entries and captions the denominator it actually used.
  const denominator = Math.max(population, listed);
  const remainder = Math.max(0, denominator - listed);

  const entries: readonly Entry[] = [
    ...languages.map((l, i) => ({
      key: l.language,
      name: LANGUAGE_LABELS[l.language],
      count: l.accounts,
      stat: `${formatCount(l.accounts)} · ${shareText(l.share, l.accounts, denominator)}`,
      ink: rampInk(PAL, i),
      dash: undefined,
    })),
    ...(remainder > 0
      ? [
          {
            key: "__remainder__",
            name: REMAINDER_LABEL,
            count: remainder,
            stat: `${formatCount(remainder)} · ${shareText(null, remainder, denominator)}`,
            // Dashed and faint: a real, counted quantity whose composition this figure is not
            // reporting. Not hatched — hatching is this page's word for "not measured", and
            // these accounts were.
            ink: PAL.D4,
            dash: "3 2",
          },
        ]
      : []),
  ];

  const lane = segmentedShare(
    entries.map((e) => e.count),
    LANE_W,
  );
  if (lane.total <= 0) {
    return (
      <Empty
        headline="no accounts to split"
        note="every reported language holds zero accounts"
      />
    );
  }

  const { placed, spilled } = planLabels(entries, lane.segments);
  const slivers = lane.segments.filter((s) => s.tooSmall);
  const footnote = spillText(entries, placed, slivers, spilled);

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      width="100%"
      fontFamily="var(--font)"
      role="img"
      aria-label={`Bot interface language of ${formatCount(denominator)} accounts, as one lane split into proportional runs`}
    >
      {/* The lane itself, drawn end to end first: the runs sit ON the population, so a run
          that is too thin to see still leaves the population visible under it. */}
      <line
        x1={LANE_X}
        y1={LANE_Y}
        x2={LANE_X + LANE_W}
        y2={LANE_Y}
        stroke={PAL.D6}
        strokeWidth={1}
      />

      {lane.segments.map((seg) => {
        const entry = entries[seg.index];
        if (entry === undefined || seg.length <= 0) return null;
        return (
          <line
            key={`seg-${entry.key}`}
            x1={LANE_X + seg.offset}
            y1={LANE_Y}
            x2={LANE_X + seg.offset + seg.length}
            y2={LANE_Y}
            stroke={entry.ink}
            strokeWidth={3}
            strokeDasharray={entry.dash}
            strokeLinecap="butt"
          >
            <title>{`${entry.name} — ${entry.stat} of ${formatCount(denominator)} accounts`}</title>
          </line>
        );
      })}

      {/* Divider ticks, one per boundary between two runs that were both drawn. A tick beside
          an invisible neighbour would mark a split nobody can see. */}
      {lane.dividers.map((d) => (
        <line
          key={`div-${d.toFixed(2)}`}
          x1={LANE_X + d}
          y1={LANE_Y - 6}
          x2={LANE_X + d}
          y2={LANE_Y + 6}
          stroke={PAL.D5}
          strokeWidth={0.9}
        />
      ))}

      {placed.map((p) => (
        <g key={`lab-${p.entry.key}`}>
          {/* An elbow rather than a straight drop: a label sits where there is room, and the
              run it names is wherever the run is. */}
          <path
            d={elbow(p.x, LANE_X + p.segment.offset)}
            fill="none"
            stroke={PAL.D5}
            strokeWidth={0.7}
          />
          <text x={p.x} y={NAME_Y} fontSize={8.5} fontWeight={700} fill={PAL.D0} letterSpacing=".04em">
            {p.entry.name}
          </text>
          <text x={p.x} y={STAT_Y} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".06em">
            {p.entry.stat}
          </text>
        </g>
      ))}

      {footnote !== "" && (
        <text x={LANE_X} y={SLIVER_Y} fontSize={8} fontWeight={600} fill={PAL.D3} letterSpacing=".04em">
          {footnote}
        </text>
      )}

      <text x={LANE_X} y={CAPTION_Y} fontSize={8} fontWeight={600} fill={PAL.MUT} letterSpacing=".06em">
        {`interface language · share of all ${formatCount(denominator)} accounts`}
      </text>
    </svg>
  );
}

/**
 * The ink ramp, darkest first — the entries arrive largest first, so the biggest run is the
 * darkest. Past the ramp's end the faintest ink REPEATS rather than cycling back to the
 * darkest, which would paint a two-account language as the one the figure is about. Runs are
 * told apart by ink darkness and by the label above them; never by hue.
 */
function rampInk(palette: Palette, index: number): string {
  const ramp = [palette.D0, palette.D1, palette.D2, palette.D3, palette.D4];
  return ramp[Math.min(index, ramp.length - 1)] ?? palette.D4;
}

/**
 * `62%`, `0.4%`, `<0.1%` — or the server's own word when it computed no ratio.
 *
 * The percentage is decoration beside the count and is rounded like decoration, except at the
 * bottom of the range, where rounding to `0%` would print a language somebody reads the bot in
 * as a language nobody reads the bot in.
 */
function shareText(share: RatioView | null, count: number, denominator: number): string {
  const value =
    share !== null && share.value !== null
      ? share.value
      : denominator > 0
        ? count / denominator
        : null;
  if (value === null || !Number.isFinite(value)) return "share not reported";
  const pct = value * 100;
  if (pct > 0 && pct < 0.1) return "<0.1%";
  if (pct < 9.95) return `${pct.toFixed(1)}%`;
  return `${String(Math.round(pct))}%`;
}

/** The label-to-run connector: down, across, and a short drop onto the lane. */
function elbow(labelX: number, runX: number): string {
  const from = labelX + 1;
  return `M${from.toFixed(1)} ${String(STAT_Y + 3)} V${String(ELBOW_Y)} H${runX.toFixed(1)} V${String(LANE_Y - 5)}`;
}

/**
 * Where each label goes, left to right, and which ones did not fit.
 *
 * A label is anchored at its run's start and pushed right only as far as the previous label
 * forces; the last one may be right-aligned to the lane's end. What it may not do is overlap
 * its neighbour — two overprinted names are worse than one name in the footnote, because the
 * reader cannot tell that anything is missing.
 */
function planLabels(
  entries: readonly Entry[],
  segments: readonly ShareSegment[],
): { readonly placed: readonly Placed[]; readonly spilled: readonly number[] } {
  const placed: Placed[] = [];
  const spilled: number[] = [];
  const laneEnd = LANE_X + LANE_W;
  let cursor = LANE_X;

  for (const seg of segments) {
    const entry = entries[seg.index];
    if (entry === undefined) continue;
    // A run nobody can see gets no label above the lane and no elbow pointing at a mark that
    // is not there. It is named in the footnote instead.
    if (seg.tooSmall || seg.length <= 0) {
      spilled.push(seg.index);
      continue;
    }
    const width = labelWidth(entry);
    let x = Math.max(cursor, LANE_X + seg.offset);
    if (x + width > laneEnd) {
      // One last try, hard against the right edge — the widest run is often the last one.
      const right = laneEnd - width;
      if (right < cursor) {
        spilled.push(seg.index);
        continue;
      }
      x = right;
    }
    placed.push({ entry, segment: seg, x });
    cursor = x + width + LABEL_GAP;
  }
  return { placed, spilled };
}

function labelWidth(entry: Entry): number {
  return Math.max(entry.name.length * NAME_ADVANCE, entry.stat.length * STAT_ADVANCE);
}

/**
 * The line under the lane: every run that is real and not labelled above it, with the reason.
 *
 * Two different absences, kept apart in the wording, because they have different causes: a run
 * too thin to draw at all, and a run drawn but with no room for its name. Both are counted
 * populations and both keep their numbers.
 */
function spillText(
  entries: readonly Entry[],
  placed: readonly Placed[],
  slivers: readonly ShareSegment[],
  spilled: readonly number[],
): string {
  const named = new Set(placed.map((p) => p.entry.key));
  const thin = new Set(slivers.map((s) => s.index));
  const parts: string[] = [];
  for (const index of spilled) {
    const entry = entries[index];
    if (entry === undefined || named.has(entry.key)) continue;
    parts.push(
      `${entry.name} ${entry.stat} ${thin.has(index) ? "(too thin to draw)" : "(no room to label it)"}`,
    );
  }
  return parts.length === 0 ? "" : `also here: ${parts.join(" · ")}`;
}

/**
 * The "nothing to split" renderings. A lane drawn with no runs would be a claim that the
 * population is one undivided language, which is a measurement — and the wrong one.
 */
function Empty({ headline, note }: { readonly headline: string; readonly note: string }): JSX.Element {
  const PAL = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(VH)}`}
      preserveAspectRatio="xMidYMid meet"
      width="100%"
      fontFamily="var(--font)"
      role="img"
      aria-label={`${headline} — ${note}`}
    >
      <line
        x1={LANE_X}
        y1={LANE_Y}
        x2={LANE_X + LANE_W}
        y2={LANE_Y}
        stroke={PAL.D6}
        strokeWidth={1}
        strokeDasharray="3 3"
      />
      <text x={LANE_X} y={NAME_Y + 6} fontSize={11} fontWeight={600} fill={PAL.D3} letterSpacing=".04em">
        {headline}
      </text>
      <text x={LANE_X} y={CAPTION_Y} fontSize={8} fontWeight={600} fill={PAL.D4} letterSpacing=".06em">
        {note}
      </text>
    </svg>
  );
}
