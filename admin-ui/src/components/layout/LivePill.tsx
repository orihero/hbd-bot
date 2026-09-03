/**
 * §11.2's `● LIVE` pill, and §11.5's rule for what drives it:
 *
 * > The `LIVE` pill reads `dataUpdatedAt` and the query's error count — **it is not a
 * > separate connection concept**. Green pulsing <10 s, amber 10–30 s or retrying, red >30 s
 * > with a countdown, slate when paused.
 *
 * There is no socket to be connected to (§11.5 explains why there never will be), so
 * "connected" would be a claim about nothing. Freshness IS the connection, and `liveStatus()`
 * in `lib/queryClient.ts` is the single implementation of the thresholds — this component
 * only renders what it returns.
 *
 * Paused is not an error. Every poll is gated on `document.visibilityState === "visible"`,
 * so a backgrounded tab genuinely stops fetching; without the visibility input the pill
 * would go red on a tab left open over lunch and greet the operator with an incident that
 * never happened.
 *
 * The word changes with the state, not just the hue — §11.3's "never colour alone". `LIVE`,
 * `LAGGING`, `STALLED`, `PAUSED` are legible in greyscale and on a bad projector, which is
 * the condition this console is most often read under.
 */

import type { LiveStatus } from "@/lib/queryClient";
import { cn } from "@/lib/utils";

import { useLiveHeartbeat } from "./useLiveHeartbeat";

/**
 * Ground and dot carry the hue; the WORD is always `--ink`.
 *
 * That split is a contrast finding, not a preference. The `-fill` members are measured at
 * WCAG 1.4.11's 3:1 for a graphic — which a dot is — and the text members at 1.4.3's 4.5:1;
 * `--ink` is the only token measured against every one of these tint grounds in both
 * palettes (6.61:1 at its worst), and 11px text is the last place to accept a marginal
 * number. So the hue lives in the ground and the dot, and the word stays legible on both
 * palettes — the same decision `EnvBadge` makes, for the same reason.
 *
 * `paused` is `--slate`, the COOL grey, rather than `--neutral`: slate is the palette's
 * "somebody or something stopped this" hue, which is exactly what a backgrounded tab is,
 * and it is visibly bluer than the neutral a draft or a skipped stage wears.
 */
const TONE = {
  live: "bg-success-tint",
  lagging: "bg-caution-tint",
  stalled: "bg-error-tint",
  paused: "bg-slate-tint",
} as const;

const DOT_TONE = {
  live: "text-success-fill",
  lagging: "text-caution-fill",
  stalled: "text-error-fill",
  paused: "text-slate-fill",
} as const;

const WORD = {
  live: "LIVE",
  lagging: "LAGGING",
  stalled: "STALLED",
  paused: "PAUSED",
} as const;

export interface LivePillProps {
  readonly status: LiveStatus;
  /** Force a refetch. The stalled pill is a button, because "try now" is the obvious wish. */
  readonly onRefresh?: (() => void) | undefined;
  readonly className?: string;
}

/** The presentational half — pure, so every state is one render away in a test. */
export function LivePill({ status, onRefresh, className }: LivePillProps) {
  const ageS = status.ageMs === null ? null : Math.round(status.ageMs / 1_000);
  const detail =
    status.state === "paused"
      ? "tab in background"
      : status.countdownS !== null
        ? `${String(ageS ?? 0)}s · retry ${String(status.countdownS)}s`
        : ageS === null
          ? ""
          : `${String(ageS)}s`;

  const body = (
    <>
      <span
        aria-hidden="true"
        className={cn(
          "leading-none",
          DOT_TONE[status.state],
          // `◉ generating` is the only animated status glyph in §11.3; this dot is chrome,
          // not a status glyph, and the pulse is what "live" means here.
          status.state === "live" && "animate-pulse-ring motion-reduce:animate-none",
        )}
      >
        ●
      </span>
      <span>{WORD[status.state]}</span>
      {detail === "" ? null : <span className="num">{detail}</span>}
    </>
  );

  const shell = cn(
    "type-caption inline-flex shrink-0 items-center gap-1.5 rounded-pill px-3 py-1.5 text-ink",
    TONE[status.state],
    className,
  );

  const label = `Data freshness: ${WORD[status.state]}${detail === "" ? "" : `, ${detail}`}`;

  if (status.state === "stalled" && onRefresh !== undefined) {
    return (
      <button
        type="button"
        onClick={onRefresh}
        data-live-state={status.state}
        aria-label={`${label}. Retry now.`}
        className={cn(shell, "transition-opacity duration-fast ease-standard hover:opacity-80")}
      >
        {body}
      </button>
    );
  }

  return (
    <span role="status" data-live-state={status.state} aria-label={label} className={shell}>
      {body}
    </span>
  );
}

/** The wired one, for the top bar. */
export function LiveHeartbeatPill({ className }: { className?: string }) {
  const { status, refetch } = useLiveHeartbeat();
  return <LivePill status={status} onRefresh={refetch} {...(className === undefined ? {} : { className })} />;
}
