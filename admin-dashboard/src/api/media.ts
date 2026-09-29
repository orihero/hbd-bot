/**
 * The `/api/media/**` contract for the review queue, transcribed from
 * `bayram/admin/routers/media_reviews.py` over `bayram/admin/schemas/media_reviews.py`
 * (IMAGE_VIDEO_SPEC §6.6, §8).
 *
 * Five routes, all on `media.moderate` (ADMIN and OWNER, a plain `W`). The REFUND mints a
 * credit, so it is in D14's step-up class: its handler enforces `moderation.decide` on the
 * REVIEW id, and the first press answers `STEP_UP_REQUIRED` with that id in `details` — taken
 * verbatim by `stepUpTargetOf`. Release and hold carry no step-up.
 *
 * Nothing on this wire is customer data: job id, SKU, states, closed category codes and
 * timings. The prompt and the images are not here, by design (§8).
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import { auditReasonCodeSchema, type ReasonedRequest } from "./reveal";

export const MEDIA_REVIEWS_PREFIX = "/api/media/reviews";

export const MEDIA_ENDPOINT = {
  list: "GET /api/media/reviews",
  release: "POST /api/media/reviews/{reviewId}/release",
  refund: "POST /api/media/reviews/{reviewId}/refund",
} as const;

export const MEDIA_REVIEW_SOURCE_VALUES = ["output_review", "guard_unavailable", "manual"] as const;
export const MEDIA_REVIEW_DECISION_VALUES = ["released", "blocked", "expired"] as const;
export type MediaReviewDecision = (typeof MEDIA_REVIEW_DECISION_VALUES)[number];
export type MediaReviewSource = (typeof MEDIA_REVIEW_SOURCE_VALUES)[number];

export const mediaReviewViewSchema = z.object({
  id: z.string().uuid(),
  jobId: z.string().uuid(),
  kind: z.enum(["image", "video"]),
  sku: z.enum(["image", "video_standard", "video_fast"]),
  jobState: z.string(),
  paidVia: z.enum(["payme", "credit", "beta"]).nullable(),
  source: z.enum(MEDIA_REVIEW_SOURCE_VALUES),
  subject: z.string(),
  categories: z.array(z.string()),
  outputsRequested: z.number().int(),
  createdAt: z.string(),
  dueAt: z.string(),
  decision: z.enum(MEDIA_REVIEW_DECISION_VALUES).nullable(),
  decidedAt: z.string().nullable(),
  actor: z.string().nullable(),
  reasonCode: auditReasonCodeSchema.nullable(),
  appliedAt: z.string().nullable(),
  isRefundable: z.boolean(),
});
export type MediaReviewView = z.infer<typeof mediaReviewViewSchema>;

export const mediaReviewListSchema = z.object({ items: z.array(mediaReviewViewSchema) });
export type MediaReviewList = z.infer<typeof mediaReviewListSchema>;

export const mediaReviewActionResultSchema = z.object({
  review: mediaReviewViewSchema,
  isQueued: z.boolean(),
});
export type MediaReviewActionResult = z.infer<typeof mediaReviewActionResultSchema>;

export type MediaReviewStatus = "pending" | "decided";

/** A review is addressed by its UUID, passed through untouched (the step-up compares it whole). */
function reviewPath(reviewId: string): string {
  return `${MEDIA_REVIEWS_PREFIX}/${encodeURIComponent(reviewId)}`;
}

export function getMediaReviews(
  status: MediaReviewStatus,
  signal?: AbortSignal,
): Promise<ApiResult<MediaReviewList>> {
  return request({
    endpoint: MEDIA_ENDPOINT.list,
    path: `${MEDIA_REVIEWS_PREFIX}?status=${status}`,
    schema: mediaReviewListSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

export function postMediaReviewRelease(
  reviewId: string,
  body: ReasonedRequest,
): Promise<ApiResult<MediaReviewActionResult>> {
  return request({
    endpoint: MEDIA_ENDPOINT.release,
    path: `${reviewPath(reviewId)}/release`,
    method: "POST",
    body,
    schema: mediaReviewActionResultSchema,
  });
}

export function postMediaReviewRefund(
  reviewId: string,
  body: ReasonedRequest,
): Promise<ApiResult<MediaReviewActionResult>> {
  return request({
    endpoint: MEDIA_ENDPOINT.refund,
    path: `${reviewPath(reviewId)}/refund`,
    method: "POST",
    body,
    schema: mediaReviewActionResultSchema,
  });
}
