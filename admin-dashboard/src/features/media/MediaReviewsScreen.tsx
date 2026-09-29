/**
 * The media review queue (IMAGE_VIDEO_SPEC §6.6, §8) — the minimal screen M3.2 ships.
 *
 * One table of held image/video jobs, oldest first (the one nearest its 24-hour SLA on top),
 * with two decisions per row, and the decided history behind a toggle. What an operator
 * decides from is what the server publishes: job id, SKU, closed category codes and timings.
 * There is no prompt and no image here by design — revealing outputs is M5's reveal subject.
 *
 * Three properties this screen would be wrong without:
 *
 * 1. **Refund is recovered through the step-up, not reported.** It mints a credit (D25), so the
 *    first press answers `STEP_UP_REQUIRED` with `moderation.decide` and the REVIEW id; the
 *    id is taken from the refusal verbatim and the SAME body goes again after the grant.
 * 2. **Release carries no step-up** — it delivers what the customer paid for — so a 403 there
 *    is a role refusal and renders as one, never as a password box.
 * 3. **A 409 is "somebody decided first"**, and the queue is re-read rather than retried.
 *
 * Buttons are hidden, not disabled, for a role without `media.moderate` (`lib/rbac.ts`), and
 * the server's guard is still the authority: the whole route is ADMIN and OWNER only.
 */

import { useState, type JSX } from "react";

import type { MediaReviewStatus, MediaReviewView } from "@/api/media";
import { stepUpTargetOf, type ReasonedRequest } from "@/api/reveal";
import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { Segmented } from "@/components/Segmented";
import { Toolbar } from "@/components/Toolbar";
import { StepUpDialog } from "@/features/reveal";
import {
  EMPTY_REASON,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useI18n } from "@/i18n";
import { failureOf } from "@/lib/adminQuery";
import { useCanModerateMedia } from "@/lib/rbac";
import { useSessionGuard } from "@/state/useSessionGuard";

import { useMediaDecision, useMediaReviews, type MediaDecision } from "./useMediaReviews";

interface PendingDecision {
  readonly decision: MediaDecision;
  readonly review: MediaReviewView;
}

/** A short, stable handle for a job — the first block of its UUID. Our id, never a person. */
function shortId(id: string): string {
  return id.slice(0, 8);
}

export function MediaReviewsScreen(): JSX.Element {
  const { t } = useI18n();
  const [status, setStatus] = useState<MediaReviewStatus>("pending");
  const [open, setOpen] = useState<PendingDecision | null>(null);
  const reviews = useMediaReviews(status);
  const canModerate = useCanModerateMedia();
  useSessionGuard([reviews.error]);

  const error = reviews.error;
  const columns: Column<MediaReviewView>[] = [
    {
      key: "job",
      header: t("media.reviews.columns.job"),
      render: (row) => (
        <span className="font-mono text-[12px]" title={row.jobId}>
          {shortId(row.jobId)}
        </span>
      ),
    },
    {
      key: "sku",
      header: t("media.reviews.columns.sku"),
      render: (row) => t(`media.reviews.sku.${row.sku}`),
    },
    {
      key: "source",
      header: t("media.reviews.columns.source"),
      render: (row) => t(`media.reviews.source.${row.source}`),
    },
    {
      key: "categories",
      header: t("media.reviews.columns.categories"),
      render: (row) =>
        row.categories.length === 0 ? (
          <span className="text-ink-400">{t("media.reviews.noCategories")}</span>
        ) : (
          <span className="flex flex-wrap gap-1">
            {row.categories.map((code) => (
              <Badge key={code} tone="warning">
                {code}
              </Badge>
            ))}
          </span>
        ),
    },
    {
      key: "when",
      header:
        status === "pending"
          ? t("media.reviews.columns.dueAt")
          : t("media.reviews.columns.decidedAt"),
      render: (row) =>
        new Date(status === "pending" ? row.dueAt : (row.decidedAt ?? row.dueAt)).toLocaleString(),
    },
    status === "pending"
      ? {
          key: "actions",
          header: t("media.reviews.columns.actions"),
          srOnlyHeader: true,
          render: (row) =>
            canModerate ? (
              <span className="flex gap-2">
                <button
                  type="button"
                  className="rounded-card border border-line px-2 py-1 text-[12px]"
                  onClick={() => {
                    setOpen({ decision: "release", review: row });
                  }}
                >
                  {t("media.reviews.release.action")}
                </button>
                <button
                  type="button"
                  className="rounded-card border border-line px-2 py-1 text-[12px] text-danger-600"
                  onClick={() => {
                    setOpen({ decision: "refund", review: row });
                  }}
                >
                  {t("media.reviews.refund.action")}
                </button>
              </span>
            ) : null,
        }
      : {
          key: "decision",
          header: t("media.reviews.columns.decision"),
          render: (row) => (
            <span>
              {row.decision === null ? "" : t(`media.reviews.decision.${row.decision}`)}
              {row.actor === null ? null : (
                <span className="ml-1 text-ink-400">· {row.actor}</span>
              )}
              {row.appliedAt === null ? (
                <span className="ml-1 text-ink-400">· {t("media.reviews.notApplied")}</span>
              ) : null}
            </span>
          ),
        },
  ];

  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("media.reviews.title")}
          subtitle={t("media.reviews.subtitle")}
          filters={
            <Segmented
              ariaLabel={t("media.reviews.title")}
              value={status}
              options={[
                { value: "pending", label: t("media.reviews.pending") },
                { value: "decided", label: t("media.reviews.decided") },
              ]}
              onChange={(value) => {
                setStatus(value);
              }}
            />
          }
        />

        {error === null ? null : (
          <ErrorNote
            tone={error.status === 403 ? "denied" : error.status === 0 ? "offline" : "error"}
            title={t("media.reviews.loadFailed")}
            message={error.message}
            hint={
              error.correlationId === null ? undefined : `${error.endpoint} · ${error.correlationId}`
            }
            retryable={error.status !== 403}
            isRetrying={reviews.isFetching}
            onRetry={() => {
              void reviews.refetch();
            }}
          />
        )}

        <DataTable
          caption={t("media.reviews.title")}
          columns={columns}
          rows={reviews.data?.items ?? []}
          getRowKey={(row) => row.id}
          isLoading={reviews.isLoading}
          emptyMessage={
            <EmptyState
              title={
                status === "pending" ? t("media.reviews.emptyPending") : t("media.reviews.emptyDecided")
              }
            />
          }
        />
      </div>

      <DecisionDialog
        pending={open}
        onClose={() => {
          setOpen(null);
        }}
      />
    </main>
  );
}

interface DecisionDialogProps {
  readonly pending: PendingDecision | null;
  readonly onClose: () => void;
}

function DecisionDialog({ pending, onClose }: DecisionDialogProps): JSX.Element | null {
  const { t } = useI18n();
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);
  /** The body actually sent, kept so a step-up retry resends it BYTE-IDENTICAL. */
  const [sent, setSent] = useState<ReasonedRequest | null>(null);
  const decide = useMediaDecision();
  if (pending === null) return null;

  const { decision, review } = pending;
  const failure = failureOf(decide.error);
  const stepUpTarget = stepUpTargetOf(failure);
  const isConflict = failure?.code === "CONFLICT";
  const label = shortId(review.jobId);

  function close(): void {
    // The reason dies with the dialog: carried to the next row it would attach one decision's
    // stated reason to a different customer's request, on a row that outlives both.
    setReason(EMPTY_REASON);
    setSent(null);
    decide.reset();
    onClose();
  }

  function submit(body: ReasonedRequest | null): void {
    if (body === null) return;
    setSent(body);
    decide.mutate({ decision, reviewId: review.id, body }, { onSuccess: close });
  }

  const isRefund = decision === "refund";
  const description = isRefund
    ? review.isRefundable
      ? t("media.reviews.refund.body", { job: label })
      : t("media.reviews.refund.bodyBeta", { job: label })
    : t("media.reviews.release.body", { job: label });

  return (
    <>
      <ConfirmDialog
        isOpen={stepUpTarget === null}
        onClose={close}
        title={isRefund ? t("media.reviews.refund.title") : t("media.reviews.release.title")}
        description={description}
        tone={isRefund ? "danger" : "default"}
        confirmLabel={
          isRefund
            ? t("media.reviews.refund.confirm", { job: label })
            : t("media.reviews.release.confirm", { job: label })
        }
        pendingLabel={t("media.reviews.pendingLabel")}
        isPending={decide.isPending}
        isConfirmDisabled={!canSubmitReason(reason) || isConflict}
        onConfirm={() => {
          submit(reasonBodyOf(reason));
        }}
        reason={{
          label: t("media.reviews.reasonLabel"),
          hint: t("media.reviews.reasonHint"),
          value: reason.text,
          isRequired: false,
          onChange: (text) => {
            setReason({ ...reason, text });
          },
        }}
        error={
          decide.error === null || stepUpTarget !== null ? undefined : (
            <ErrorNote
              tone={decide.error.status === 403 ? "denied" : "error"}
              title={isConflict ? t("media.reviews.conflictTitle") : t("media.reviews.failedTitle")}
              message={isConflict ? t("media.reviews.conflictMessage") : decide.error.message}
              retryable={false}
            />
          )
        }
      >
        <ReasonFieldset value={reason} onChange={setReason} isDisabled={decide.isPending} />
      </ConfirmDialog>

      <StepUpDialog
        isOpen={stepUpTarget !== null}
        /* Cancelling drops back to the confirm dialog with the reason still typed. */
        onClose={decide.reset}
        action={stepUpTarget?.action ?? "moderation.decide"}
        subjectId={stepUpTarget?.subjectId ?? review.id}
        subjectLabel={label}
        note={t("media.reviews.refund.stepUpNote", { job: label })}
        onGranted={() => {
          // The server has no memory of what was being attempted, so the SAME body goes again.
          submit(sent);
        }}
      />
    </>
  );
}
