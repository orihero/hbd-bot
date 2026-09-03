/**
 * Bucketing `matchConfidence` for `<SimilarityHistogram>` (§11.2, `/generations/names`).
 *
 * The screen's question is "what should `HBD_NAME_CANDIDATE_ORDER` be", and the histogram
 * answers the half of it that the bake-off bars cannot: where the verifier's similarity
 * scores actually pile up relative to `name_match_min_similarity`. A bimodal distribution
 * with the threshold in the trough is a healthy verifier; a single lump straddling the
 * threshold means the threshold is deciding coin flips.
 *
 * `matchConfidence` is `null` on every attempt where verification did not run — those rows
 * are DROPPED here rather than bucketed at zero. A zero-confidence bar built out of rows
 * that never ran is the same class of wrong number as a 0% success rate on a quiet morning.
 */

export interface SimilarityBucket {
  /** Inclusive lower edge. */
  readonly from: number;
  /** Exclusive upper edge — except the last bucket, which includes 1. */
  readonly to: number;
  readonly count: number;
}

export const DEFAULT_BUCKET_COUNT = 20;

/**
 * Build the buckets. Values outside `[0, 1]` are clamped rather than dropped: a provider
 * returning 1.0000000002 is not a reason to lose a sample.
 */
export function buildSimilarityBuckets(
  values: readonly (number | null)[],
  bucketCount: number = DEFAULT_BUCKET_COUNT,
): readonly SimilarityBucket[] {
  const width = 1 / bucketCount;
  const counts = new Array<number>(bucketCount).fill(0);
  for (const value of values) {
    if (value === null || !Number.isFinite(value)) continue;
    const clamped = Math.min(1, Math.max(0, value));
    const index = Math.min(bucketCount - 1, Math.floor(clamped / width));
    counts[index] = (counts[index] ?? 0) + 1;
  }
  return counts.map((count, index) => ({
    from: index * width,
    to: (index + 1) * width,
    count,
  }));
}

/** `0.82` → `0.82`, two digits, no locale. Bucket edges are OUR numbers, not user content. */
export function formatSimilarity(value: number): string {
  return value.toFixed(2);
}
