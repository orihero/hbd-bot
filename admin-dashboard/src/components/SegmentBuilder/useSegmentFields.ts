/**
 * The two reads behind the builder, and the debounce between an operator's keystroke and the
 * audience number.
 *
 * **They are gated separately, because the server gates them separately.**
 * `/segments/fields` is `broadcast.read` and `/segments/preview` is `records.read`, and that is
 * not an oversight: an audience TOTAL must not be harder to obtain than the accounts it counts,
 * so a support operator who can page the list can also see how many the filter selects — while
 * the field registry, which names every dimension the panel can ask about a customer, stays
 * behind the campaign cell. A screen must therefore be able to have one and not the other, and
 * these are two hooks rather than one for exactly that reason.
 *
 * **The registry is cached for the session, never baked into the build.** `isAvailable`
 * answers for the deployment this bundle is actually talking to (`chat_messages` may or may not
 * be installed), and `version` is the document shape the server expects. Both are properties of
 * the server, read once and reused.
 *
 * **The preview is debounced on the TOKEN, not on the object.** A React re-render that produced
 * an identical document must not restart the timer or mint a second cache key, and
 * `encodeSegment` is byte-identical to the token the Users screen puts in the URL — so the
 * count a wizard shows and the rows that URL walks are provably one population, and one query
 * key. An unfiltered, unsorted document is `null`, which is the plain-list cache entry rather
 * than a second spelling of it.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  getSegmentFields,
  previewSegment,
  type SegmentFieldsView,
  type SegmentPreviewView,
} from "@/api/segments";
import { LIST_READ, unwrap, type AdminQueryError } from "@/lib/adminQuery";
import { segmentToken, type Segment } from "@/lib/segmentCodec";

const SEGMENTS_ROOT = "segments";

/**
 * How long the registry counts as fresh.
 *
 * Five minutes rather than the records' ten seconds: this response changes when the server is
 * DEPLOYED, not when a customer does anything, and re-reading it on every window focus would be
 * a request per tab switch for an answer that cannot have moved.
 */
export const SEGMENT_REGISTRY_STALE_TIME_MS = 5 * 60_000;

/** The pause between the last edit and the audience count. The house debounce, doubled. */
export const SEGMENT_PREVIEW_DEBOUNCE_MS = 400;

export const segmentKeys = {
  all: [SEGMENTS_ROOT] as const,
  fields: () => [SEGMENTS_ROOT, "fields"] as const,
  /** Keyed by the TOKEN: two documents that encode the same bytes are one question. */
  preview: (token: string | null) => [SEGMENTS_ROOT, "preview", token] as const,
} as const;

export type SegmentKeys = typeof segmentKeys;

/**
 * The field registry — what a rule may name, and what this deployment can actually answer.
 *
 * `enabled: false` is the shape a screen uses when the role holds no campaign cell: the
 * builder is not rendered at all rather than rendered against an empty field list, because a
 * builder with no fields looks like a server with no data.
 */
export function useSegmentFields(
  options: { readonly enabled?: boolean } = {},
): UseQueryResult<SegmentFieldsView, AdminQueryError> {
  return useQuery<SegmentFieldsView, AdminQueryError>({
    queryKey: segmentKeys.fields(),
    queryFn: ({ signal }) => unwrap(getSegmentFields(signal)),
    enabled: options.enabled ?? true,
    ...LIST_READ,
    // The registry moves on deploy, not on traffic. Everything else in LIST_READ still applies.
    staleTime: SEGMENT_REGISTRY_STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
}

/**
 * The document, held still for {@link SEGMENT_PREVIEW_DEBOUNCE_MS} after the last edit.
 *
 * Exported because the wizard needs to know it is looking at a settled document before it lets
 * an operator commit to the number on screen — an audience count for a segment two keystrokes
 * ago is the wrong number to authorise a send against.
 */
export function useDebouncedSegment(
  segment: Segment | null,
  delayMs: number = SEGMENT_PREVIEW_DEBOUNCE_MS,
): Segment | null {
  const token = segmentToken(segment);
  const latest = useRef(segment);
  latest.current = segment;
  const [settled, setSettled] = useState(segment);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSettled(latest.current);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
    // The TOKEN, deliberately: a re-render that produced an identical document is not an edit.
  }, [token, delayMs]);

  return settled;
}

/**
 * How many accounts this document selects, and how many of them a send would reach.
 *
 * `matched` is exact — never the list's bounded total, because "10,000+" is a refusal to answer
 * rather than an approximation and nobody can approve a broadcast against a ceiling. The two
 * `skipped*` counts OVERLAP (ours and the customer's), so a screen renders them as reasons and
 * never as a sum; only `reachable` is the complement, and it is the number to gate on.
 */
export function useSegmentPreview(
  segment: Segment | null,
  options: { readonly enabled?: boolean; readonly debounceMs?: number } = {},
): UseQueryResult<SegmentPreviewView, AdminQueryError> {
  const settled = useDebouncedSegment(segment, options.debounceMs ?? SEGMENT_PREVIEW_DEBOUNCE_MS);
  return useQuery<SegmentPreviewView, AdminQueryError>({
    queryKey: segmentKeys.preview(segmentToken(settled)),
    queryFn: ({ signal }) => unwrap(previewSegment(settled, signal)),
    enabled: options.enabled ?? true,
    ...LIST_READ,
  });
}
