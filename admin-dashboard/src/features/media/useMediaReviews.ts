/**
 * The review queue's reads and its two decisions (IMAGE_VIDEO_SPEC §6.6).
 *
 * A decision invalidates the whole queue key rather than patching one row: the row leaves the
 * pending list and joins the decided one, and both are one small bounded read.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getMediaReviews,
  postMediaReviewRefund,
  postMediaReviewRelease,
  type MediaReviewActionResult,
  type MediaReviewList,
  type MediaReviewStatus,
} from "@/api/media";
import type { ReasonedRequest } from "@/api/reveal";
import { LIST_READ, PRIVILEGED_WRITE, unwrap, type AdminQueryError } from "@/lib/adminQuery";

export const mediaReviewKeys = {
  all: () => ["media", "reviews"] as const,
  list: (status: MediaReviewStatus) => ["media", "reviews", status] as const,
};

export function useMediaReviews(
  status: MediaReviewStatus,
): UseQueryResult<MediaReviewList, AdminQueryError> {
  return useQuery<MediaReviewList, AdminQueryError>({
    queryKey: mediaReviewKeys.list(status),
    queryFn: ({ signal }) => unwrap(getMediaReviews(status, signal)),
    ...LIST_READ,
  });
}

export type MediaDecision = "release" | "refund";

export interface MediaDecisionVariables {
  readonly decision: MediaDecision;
  readonly reviewId: string;
  readonly body: ReasonedRequest;
}

/**
 * Release or refund one review. Expect `STEP_UP_REQUIRED` on a refund's first attempt — the
 * scope is `moderation.decide:{reviewId}` — and a 409 when somebody else decided it first.
 */
export function useMediaDecision(): UseMutationResult<
  MediaReviewActionResult,
  AdminQueryError,
  MediaDecisionVariables
> {
  const queryClient = useQueryClient();
  return useMutation<MediaReviewActionResult, AdminQueryError, MediaDecisionVariables>({
    mutationFn: ({ decision, reviewId, body }) =>
      unwrap(
        decision === "release"
          ? postMediaReviewRelease(reviewId, body)
          : postMediaReviewRefund(reviewId, body),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: mediaReviewKeys.all() });
    },
    ...PRIVILEGED_WRITE,
  });
}
