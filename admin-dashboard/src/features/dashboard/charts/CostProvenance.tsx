import type { JSX } from "react";

import type { CostProvenanceView, CostSource } from "@/api/dashboard";
import { formatCount, formatUsd } from "@/features/dashboard/adapt";
import { CH, CW } from "@/features/dashboard/data";
import { hatchLines, segmentedShare, usePalette, type Palette } from "@/features/dashboard/svg";

/* -------------------------------------------------------------------------- */
/* Geometry                                                                    */
/* -------------------------------------------------------------------------- */

const LX = 20;
const RX = CW - 20;
/** The lane the whole partition tiles. Width IS the share; there is no other encoding. */
const LANE_W = RX - LX;
const LANE_Y = 44;
/**
 * The unmeasured stretch is a HATCHED TRACK, not a rule: it has height where the measured
 * segments have only a stroke, so the two never read as the same kind of mark even in a
 * screenshot with the labels cropped off.
 */
const HATCH_H = 9;
const LEG_Y0 = 82;
const LEG_PITCH = 25;
/** Legend columns. Word · counted calls · what the money in that bucket actually is. */
const LEG_WORD_X = LX + 34;
const LEG_CALLS_X = 200;
const LEG_MEANING_X = 352;

/* -------------------------------------------------------------------------- */
/* The four buckets                                                            */
/* -------------------------------------------------------------------------- */

/**
 * `costSource` with its null lifted into a name. The null bucket is a REAL member of the
 * partition — calls that happened, were recorded, and that nobody could put a price on — so
 * it gets a name here rather than being folded into an "other" or defaulted to zero dollars.
 */
type Kind = CostSource | "unpriced";

/**
 * Drawn left to right in DESCENDING CREDIBILITY, not by size, which is the one ordering that
 * makes the lane readable as a claim: everything left of a boundary is better evidence than
 * everything right of it, and the rightmost stretch is the part of the window's money that
 * was never measured at all. `segmentedShare` preserves input order precisely so a figure
 * ordered by meaning stays ordered by meaning.
 */
const ORDER: readonly Kind[] = ["vendor_reported", "derived", "estimated", "unpriced"];

interface Style {
  /** The word beside the mark. Colour is never the only channel; neither is stroke weight. */
  readonly word: string;
  readonly weight: number;
  readonly dash: string | undefined;
}

const STYLE: Record<Kind, Style> = {
  vendor_reported: { word: "VENDOR-REPORTED", weight: 2.4, dash: undefined },
  derived: { word: "DERIVED", weight: 1.6, dash: undefined },
  estimated: { word: "ESTIMATED", weight: 1.6, dash: "4 3" },
  // Weight is unused for the unpriced bucket: it is drawn as a hatch, not as a rule.
  unpriced: { word: "NOT PRICED", weight: 0, dash: undefined },
};

/** Ink darkness carries the same ordering the lane does. The unpriced track is achromatic. */
function inkOf(palette: Palette, kind: Kind): string {
  switch (kind) {
    case "vendor_reported":
      return palette.D0;
    case "derived":
      return palette.D1;
    case "estimated":
      return palette.D2;
    case "unpriced":
      return palette.UNKNOWN;
  }
}

interface Bucket {
  readonly kind: Kind;
  readonly calls: number;
  /** Summed over the wire rows of this kind. Null = not one of them carried a figure. */
  readonly costUsd: number | null;
}

/**
 * THE SENTENCE THIS WHOLE COMPONENT EXISTS FOR.
 *
 * `vendor_reported` summing to `0.00` is a MEASUREMENT: the vendor's own response said the
 * call cost nothing, and on this deployment that is the normal case rather than a fault —
 * OpenRouter's default model is a `:free` one, so a large "reported $0.00" stretch is what a
 * healthy window looks like. The null bucket is the opposite: the calls are counted, no rate
 * existed to price them with, and the honest statement is that nobody knows. Rendering the
 * two alike is how a deployment concludes its rendering pipeline is free.
 */
function meaningOf(bucket: Bucket): string {
  const { kind, costUsd } = bucket;
  if (kind === "unpriced") {
    return "unmeasured — no rate existed";
  }
  if (costUsd === null) {
    return kind === "vendor_reported"
      ? "no figure came back with these calls"
      : "no figure could be computed for these calls";
  }
  if (kind === "vendor_reported") {
    return costUsd === 0
      ? `${formatUsd(0)} reported — the vendor said these were free`
      : `${formatUsd(costUsd)} — the vendor's own figure`;
  }
  if (kind === "derived") return `${formatUsd(costUsd)} — worked out from a rate card`;
  return `${formatUsd(costUsd)} — estimated`;
}

/**
 * `62%`, `3%`, `<1%`. A real bucket never rounds away to `0%`: it was measured, and a zero
 * beside a positive call count is the reader concluding the row is empty.
 */
function sharePct(share: number): string {
  if (!Number.isFinite(share) || share <= 0) return "0%";
  const pct = share * 100;
  if (pct < 1) return "<1%";
  return `${String(Math.round(pct))}%`;
}

/* -------------------------------------------------------------------------- */

export interface CostProvenanceProps {
  /**
   * `VendorResponse.costProvenance`, straight off the wire and in any order — this component
   * sorts into the credibility order itself.
   *
   * It is a PARTITION OF CALLS, so the denominator of every share drawn here is the sum of
   * what you pass. Pass the whole array: a filtered subset would still tile the lane to 100%
   * and would be a share of a population the payload never described.
   *
   * A bucket with `calls: 0` is dropped — it has no width and prints as a row saying nothing
   * happened. A bucket with `costSource: null` is NEVER dropped: positive `calls` with a null
   * `costUsd` is the unmeasured stretch, and it is the whole point of the figure.
   */
  readonly buckets: readonly CostProvenanceView[];
}

/**
 * Where the money on the rest of this page came from — the strip that bounds how much of it
 * can be believed.
 *
 * Every other money figure on the dashboard collapses provenance into one source and a mixed
 * flag, so none of them can tell you what fraction of the window was actually priced. This
 * one claims exactly that and nothing more: how many recorded CALLS were priced by the
 * vendor's own answer, how many were worked out from a rate card, how many were estimated,
 * and how many nobody could price at all.
 *
 * What it deliberately does NOT claim: it is not a breakdown of dollars. The lane partitions
 * calls, because the unpriced stretch has no dollars to contribute and a money lane would
 * therefore be a lane the unmeasured part is invisible in — which is the one thing this
 * figure must never let happen. Dollars are printed per bucket, in words, and only where a
 * dollar figure exists. It also says nothing about whether the priced figures are RIGHT; a
 * vendor-reported number is evidence of what we were told, not of what we were billed.
 */
export function CostProvenance({ buckets }: CostProvenanceProps): JSX.Element {
  const PAL = usePalette();

  const folded = new Map<Kind, Bucket>();
  for (const b of buckets) {
    const kind: Kind = b.costSource ?? "unpriced";
    const prev = folded.get(kind);
    const calls = Number.isFinite(b.calls) ? Math.max(0, b.calls) : 0;
    // A null cost is not an addend. Summing it as zero is the exact confusion this figure is
    // built to prevent, so the sum stays null until some row in the bucket carries a figure.
    const cost =
      b.costUsd === null || !Number.isFinite(b.costUsd)
        ? (prev?.costUsd ?? null)
        : (prev?.costUsd ?? 0) + b.costUsd;
    folded.set(kind, { kind, calls: (prev?.calls ?? 0) + calls, costUsd: cost });
  }

  const rows: Bucket[] = [];
  for (const kind of ORDER) {
    const b = folded.get(kind);
    if (b !== undefined && b.calls > 0) rows.push(b);
  }

  if (rows.length === 0) {
    return <Empty note="no vendor calls recorded in this window" />;
  }

  const lane = segmentedShare(
    rows.map((r) => r.calls),
    LANE_W,
  );
  const totalCalls = lane.total;

  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label="How the window's cost figures were arrived at: calls priced by the vendor's own answer, worked out from a rate card, estimated, or never priced at all"
    >
      <text
        x={LX}
        y={20}
        fontSize={8}
        fontWeight={700}
        fill={PAL.MUT}
        letterSpacing=".08em"
      >
        {`${formatCount(totalCalls)} RECORDED CALLS · WIDTH IS EACH BUCKET'S SHARE OF THEM`}
      </text>

      {lane.segments.map((seg) => {
        const row = rows[seg.index];
        if (row === undefined) return null;
        const style = STYLE[row.kind];
        const ink = inkOf(PAL, row.kind);
        const x = LX + seg.offset;
        const title = `${style.word} — ${formatCount(row.calls)} calls, ${sharePct(seg.share)} · ${meaningOf(row)}`;

        // A segment too thin to be a mark is still a measurement: it keeps its place on the
        // lane as a full-height tick, and its legend row prints the count it stands for.
        if (seg.tooSmall) {
          return (
            <g key={`seg-${row.kind}`}>
              <line
                x1={x}
                y1={LANE_Y - 5}
                x2={x}
                y2={LANE_Y + 5}
                stroke={ink}
                strokeWidth={1}
              />
              <title>{title}</title>
            </g>
          );
        }

        if (row.kind === "unpriced") {
          return (
            <g key={`seg-${row.kind}`}>
              {hatchLines({
                x,
                y: LANE_Y - HATCH_H / 2,
                width: seg.length,
                height: HATCH_H,
              }).map((h, k) => (
                <line
                  key={k}
                  x1={h.x1}
                  y1={h.y1}
                  x2={h.x2}
                  y2={h.y2}
                  stroke={PAL.HATCH}
                  strokeWidth={0.7}
                />
              ))}
              <title>{title}</title>
            </g>
          );
        }

        return (
          <g key={`seg-${row.kind}`}>
            <line
              x1={x}
              y1={LANE_Y}
              x2={x + seg.length}
              y2={LANE_Y}
              stroke={ink}
              strokeWidth={style.weight}
              strokeDasharray={style.dash}
            />
            <title>{title}</title>
          </g>
        );
      })}

      {/* Boundaries between two DRAWN stretches. `segmentedShare` emits none at the lane's
          own ends and none beside an invisible neighbour, so a tick here always marks a
          split the eye can actually see. */}
      {lane.dividers.map((d, k) => (
        <line
          key={`div-${String(k)}`}
          x1={LX + d}
          y1={LANE_Y - 7}
          x2={LX + d}
          y2={LANE_Y + 7}
          stroke={PAL.D5}
          strokeWidth={0.8}
        />
      ))}

      {rows.map((row, i) => {
        const seg = lane.segments[i];
        const y = LEG_Y0 + i * LEG_PITCH;
        const style = STYLE[row.kind];
        const ink = inkOf(PAL, row.kind);
        const unpriced = row.kind === "unpriced";

        return (
          <g key={`leg-${row.kind}`}>
            {unpriced ? (
              hatchLines({ x: LX, y: y - 4, width: 26, height: 8 }, 3).map((h, k) => (
                <line
                  key={k}
                  x1={h.x1}
                  y1={h.y1}
                  x2={h.x2}
                  y2={h.y2}
                  stroke={PAL.HATCH}
                  strokeWidth={0.7}
                />
              ))
            ) : (
              <line
                x1={LX}
                y1={y}
                x2={LX + 26}
                y2={y}
                stroke={ink}
                strokeWidth={style.weight}
                strokeDasharray={style.dash}
              />
            )}
            <text
              x={LEG_WORD_X}
              y={y + 3}
              fontSize={10}
              fontWeight={700}
              fill={unpriced ? PAL.UNKNOWN : PAL.D0}
              letterSpacing=".06em"
            >
              {style.word}
            </text>
            <text x={LEG_CALLS_X} y={y + 3} fontSize={9} fontWeight={600} fill={PAL.D1}>
              {`${formatCount(row.calls)} calls · ${sharePct(seg?.share ?? 0)}`}
            </text>
            <text x={LEG_MEANING_X} y={y + 3} fontSize={9} fontWeight={500} fill={PAL.D2}>
              {meaningOf(row)}
              {seg?.tooSmall === true ? " · thinner than a hairline on the lane" : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/**
 * A lane with nothing on it would read as a window whose calls were all priced at nothing —
 * the exact reading this figure exists to prevent — so there is no lane at all until there
 * is a call to put on it.
 */
function Empty({ note }: { readonly note: string }): JSX.Element {
  const PAL = usePalette();
  return (
    <svg
      viewBox={`0 0 ${String(CW)} ${String(CH)}`}
      preserveAspectRatio="xMidYMid meet"
      fontFamily="var(--font)"
      width="100%"
      height="100%"
      role="img"
      aria-label={note}
    >
      <text
        x={CW / 2}
        y={CH / 2}
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
