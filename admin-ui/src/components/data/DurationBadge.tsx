/**
 * `<DurationBadge>` — color-coded latency and duration badge helper.
 *
 * Thresholds:
 *   - < 1s: green (`bg-success-tint`, `text-success`)
 *   - 1-5s: neutral (`bg-surface-control`, `text-ink-muted`)
 *   - 5-15s: amber (`bg-caution-tint`, `text-caution`)
 *   - > 15s: red (`bg-error-tint`, `text-error`)
 *
 * When `isInstrumented` is false, renders "not instrumented", preserving the
 * contract that unmeasured telemetry is never displayed as zero.
 */

import type { ReactElement } from "react";

import { cn, EMPTY_VALUE, formatDurationMs, latencyBand, type LatencyBand } from "@/lib";

export interface DurationBadgeProps {
  readonly ms: number | null | undefined;
  readonly isInstrumented?: boolean | undefined;
  readonly className?: string | undefined;
}

const BAND_CONFIG: Record<
  LatencyBand,
  { readonly bg: string; readonly text: string; readonly dot: string }
> = {
  fast: { bg: "bg-success-tint", text: "text-success", dot: "bg-success" },
  neutral: { bg: "bg-surface-control", text: "text-ink-muted", dot: "bg-neutral-fill" },
  slow: { bg: "bg-caution-tint", text: "text-caution", dot: "bg-caution" },
  critical: { bg: "bg-error-tint", text: "text-error", dot: "bg-error" },
  unknown: { bg: "bg-surface-control", text: "text-ink-muted", dot: "bg-neutral-fill" },
};

export function DurationBadge({
  ms,
  isInstrumented = true,
  className,
}: DurationBadgeProps): ReactElement {
  if (!isInstrumented) {
    return (
      <span
        data-testid="duration-badge-uninstrumented"
        className={cn("type-caption text-ink-muted", className)}
      >
        not instrumented
      </span>
    );
  }

  if (ms === null || ms === undefined || !Number.isFinite(ms)) {
    return (
      <span className={cn("num text-ink-muted", className)} data-empty="true">
        {EMPTY_VALUE}
      </span>
    );
  }

  const band = latencyBand(ms);
  const style = BAND_CONFIG[band];

  return (
    <span
      data-testid="duration-badge"
      data-band={band}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-pill px-2 py-0.5 type-caption num font-medium",
        style.bg,
        style.text,
        className,
      )}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", style.dot)} aria-hidden="true" />
      <span>{formatDurationMs(ms)}</span>
    </span>
  );
}
