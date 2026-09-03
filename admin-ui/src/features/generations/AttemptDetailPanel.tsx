/**
 * One row of the render ledger, opened from `/generations` via `?attempt=<uuid>`.
 *
 * §11.2's route table has no `/generations/:id`, and `routes.tsx` has no such route — the
 * detail is a panel on the list, addressed by a search parameter so it is still a link an
 * operator can paste. It reads `GET /api/generations/{attempt_id}` rather than the row
 * already in hand: the endpoint exists, it is the same bytes, and a panel that renders a row
 * from a page fetched two minutes ago would silently disagree with the same panel opened
 * from a fresh URL.
 *
 * Three fields here are not what they look like, and §12.3 is why:
 *
 *  - `nameCandidate` is MASKED (`G•••`) and still user content, so it goes through
 *    `<NameText>` — which is also the only way the `U+` toggle is available, and "which
 *    apostrophe did the customer type" is the first question a failed verification raises.
 *  - `sttTranscriptChars` is a LENGTH. The transcript itself needs `POST /reveal`, Phase 2.
 *  - `costUsd` and `latencyMs` are `null`, never `0`, when `isInstrumented` is false — which
 *    is every row in production today. `formatCostUsd`/`formatLatencyMs` render
 *    "not instrumented" rather than `$0.00`, which would say the call was free.
 *
 * The reskin made it a card of its own — `--surface-card` at 28px with `--shadow-card`, no
 * border — and titles itself, because it opens beside the table rather than under a section
 * label of its own. Its three groups are separated by a hairline rather than by a heavier
 * rule: `--hairline` is decoration between rows of a dense list and is never the boundary of
 * a control.
 *
 * The outcome line is the design's tinted pill — the WORD in `--ink`, the hue in the ground
 * and the glyph — rather than a coloured word. A hue painted straight onto text sits at its
 * 4.5:1 floor in the light palette; this reads at 6.6:1 and still carries ✓/✗ so the fact
 * survives greyscale.
 */

import type { ReactElement, ReactNode } from "react";
import { Link } from "react-router-dom";

import type { AttemptWireView } from "@/api";
import { Timestamp } from "@/components/data";
import {
  ErrorCodeBadge,
  NameText,
  OrderRefChip,
  PurgedValue,
  formatSimilarity,
} from "@/components/domain";
import { Button, CopyButton } from "@/components/util";
import {
  EMPTY_VALUE,
  cn,
  formatCostUsd,
  formatInteger,
  formatLatencyMs,
  humaniseEnum,
} from "@/lib";
import { href } from "@/routes";

/** An attempt with no order: a pre-order preview, or the order was deleted. */
export const ORPHANED_LABEL = "orphaned — no order row";
/** `isNameVerified === null`: verification did not run on this attempt. */
export const VERIFICATION_NOT_RUN_LABEL = "did not run";

export interface AttemptDetailPanelProps {
  readonly attempt: AttemptWireView;
  readonly onClose: () => void;
  readonly className?: string;
}

export function AttemptDetailPanel({
  attempt,
  onClose,
  className,
}: AttemptDetailPanelProps): ReactElement {
  return (
    <aside
      data-testid="attempt-detail"
      data-attempt-id={attempt.id}
      aria-label="generation attempt"
      className={cn(
        "flex flex-col gap-5 rounded-card bg-surface-card p-card shadow-card",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="type-h2 text-ink">{humaniseEnum(attempt.kind)}</h2>
          <p className="type-body-sm num text-ink-muted">
            {`sequence ${formatInteger(attempt.sequence)} · attempt ${formatInteger(attempt.attempt)}`}
          </p>
        </div>
        {/* Dismissive, so `quiet` — no ground of its own. */}
        <Button
          variant="quiet"
          size="xs"
          shape="pill"
          onClick={onClose}
          aria-label="close attempt detail"
        >
          close
        </Button>
      </header>

      <dl className="flex flex-col gap-3">
        <Field label="attempt id">
          <span className="type-mono inline-flex items-center gap-1 text-ink-muted">
            {attempt.id}
            <CopyButton value={attempt.id} label="attempt id" />
          </span>
        </Field>

        <Field label="order">
          {attempt.orderId === null ? (
            <span className="text-ink-muted">{ORPHANED_LABEL}</span>
          ) : (
            <OrderRefChip orderId={attempt.orderId} />
          )}
        </Field>

        <Field label="outcome">
          <span
            data-testid="attempt-outcome"
            data-success={String(attempt.isSuccess)}
            className={cn(
              "type-body-sm inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-ink",
              attempt.isSuccess ? "bg-success-tint" : "bg-error-tint",
            )}
          >
            <span
              aria-hidden="true"
              className={attempt.isSuccess ? "text-success" : "text-error"}
            >
              {attempt.isSuccess ? "✓" : "✗"}
            </span>{" "}
            {attempt.isSuccess ? "succeeded" : "failed"}
          </span>
        </Field>

        {attempt.errorCode === null && attempt.errorMessage === null ? null : (
          <Field label="error">
            <ErrorCodeBadge
              code={attempt.errorCode}
              isRetryable={attempt.isRetryable}
              message={attempt.errorMessage}
            />
          </Field>
        )}

        <Field label="provider">
          <span className="type-mono text-ink-muted">{attempt.provider ?? EMPTY_VALUE}</span>
        </Field>

        <Field label="provider id">
          {attempt.providerRemoteId === null ? (
            <span className="text-ink-muted">{EMPTY_VALUE}</span>
          ) : (
            <span className="type-mono inline-flex items-center gap-1 text-ink-muted">
              {attempt.providerRemoteId}
              <CopyButton value={attempt.providerRemoteId} label="provider id" />
            </span>
          )}
        </Field>

        <Field label="language">
          <span className="text-ink-muted">
            {attempt.language === null ? EMPTY_VALUE : humaniseEnum(attempt.language)}
          </span>
        </Field>
      </dl>

      <section aria-label="name verification" className="border-t border-hairline pt-5">
        <h3 className="type-body-sm text-ink-muted">name verification</h3>
        <dl className="mt-3 flex flex-col gap-3">
          <Field label="candidate">
            <PurgedValue purgedAt={attempt.identityPurgedAt} clock="identity retention">
              <NameText value={attempt.nameCandidate} isToggleable />
            </PurgedValue>
          </Field>
          <Field label="strategy">
            <span className="text-ink-muted">
              {attempt.nameCandidateStrategy === null
                ? EMPTY_VALUE
                : humaniseEnum(attempt.nameCandidateStrategy)}
            </span>
            {attempt.nameCandidateRank === null ? null : (
              <span className="type-body-sm num ml-2 text-ink-muted">
                {`rank ${formatInteger(attempt.nameCandidateRank)}`}
              </span>
            )}
          </Field>
          <Field label="verified">
            {/* Tri-state. `null` is "the verifier did not run", not "failed". */}
            <span data-testid="attempt-verified" data-verified={String(attempt.isNameVerified)}>
              {attempt.isNameVerified === null ? (
                <span className="text-ink-muted">{VERIFICATION_NOT_RUN_LABEL}</span>
              ) : (
                <span
                  className={cn(
                    "type-body-sm inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-ink",
                    attempt.isNameVerified ? "bg-success-tint" : "bg-error-tint",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={attempt.isNameVerified ? "text-success" : "text-error"}
                  >
                    {attempt.isNameVerified ? "✓" : "✗"}
                  </span>{" "}
                  {attempt.isNameVerified ? "verified" : "not matched"}
                </span>
              )}
            </span>
          </Field>
          <Field label="match confidence">
            <span className="num text-ink-muted">
              {attempt.matchConfidence === null
                ? EMPTY_VALUE
                : formatSimilarity(attempt.matchConfidence)}
            </span>
            <Link
              to={href.nameStrategies()}
              className="type-body-sm ml-2 text-brand underline-offset-4 hover:underline"
            >
              bake-off →
            </Link>
          </Field>
          <Field label="transcript">
            {/* A LENGTH, never the transcript. The text needs POST /reveal (Phase 2). */}
            <PurgedValue purgedAt={attempt.textPurgedAt} clock="transcript retention">
              <span className="num text-ink-muted">
                {attempt.sttTranscriptChars === null
                  ? EMPTY_VALUE
                  : `${formatInteger(attempt.sttTranscriptChars)} chars`}
              </span>
            </PurgedValue>
          </Field>
        </dl>
      </section>

      <section aria-label="telemetry" className="border-t border-hairline pt-5">
        <h3 className="type-body-sm text-ink-muted">telemetry</h3>
        <dl className="mt-3 flex flex-col gap-3">
          <Field label="cost">
            <span className="num text-ink-muted">
              {formatCostUsd(attempt.costUsd, attempt.isInstrumented)}
            </span>
            {attempt.costSource === null ? null : (
              <span className="type-body-sm ml-2 text-ink-muted">{attempt.costSource}</span>
            )}
          </Field>
          <Field label="latency">
            <span className="num text-ink-muted">
              {formatLatencyMs(attempt.latencyMs, attempt.isInstrumented)}
            </span>
          </Field>
          <Field label="created">
            <Timestamp at={attempt.createdAt} seconds />
          </Field>
        </dl>
      </section>
    </aside>
  );
}

function Field({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
      <dt className="type-body-sm text-ink-muted">{label}</dt>
      <dd className="type-body-sm text-ink">{children}</dd>
    </div>
  );
}
