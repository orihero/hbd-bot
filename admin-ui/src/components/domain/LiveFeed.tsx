/**
 * `<LiveFeed>` — the running log on `/`, and the pause control that makes it readable.
 *
 * The state lives in `useFeedStore` rather than in the query cache for one reason, written
 * into that store's docstring: **the newest item pushing the list down is actively hostile**
 * to an operator reading a failure. Paused, new arrivals buffer and the visible list does
 * not move; the buffered count stays on screen so nobody thinks the system went quiet.
 *
 * Two things this component must NOT imply:
 *
 * - **It is not a stream.** §11.5: there is no event bus (the only production
 *   `ProgressSink` edits one Telegram message), and `KitPipeline._replay` returns a stored
 *   kit before the reporter exists, so a *retried* order emits ZERO progress events. The
 *   feed is a poll of what was recorded, and an empty feed means "nothing was recorded",
 *   never "nothing happened".
 * - **It is not a filter on the truth.** The severity filter is a client-side view; the
 *   header keeps saying how many events are held so a filtered feed cannot be mistaken for
 *   a quiet one.
 *
 * `GET /api/ops/feed` does not exist on this build. The screen supplies events — from
 * `PulseView.failures`, an in-flight orders list, or the audit log — and `FeedEvent` is a
 * client shape, not a wire type.
 */

import type { ReactElement } from "react";

import { Button, segmentVariant } from "@/components/util";
import {
  cn,
  formatInteger,
  formatTimestamp,
  useFeedStore,
  useVisibleFeed,
  type FeedEvent,
  type FeedSeverity,
  type TimeZoneMode,
} from "@/lib";

import { feedSeverityColorVar, feedSeverityGlyph, tintVar } from "./colors";
import { CorrelationChip } from "./CorrelationChip";
import { OrderRefChip } from "./OrderRefChip";
import { useTimeZoneMode } from "./useTimeZoneMode";

const SEVERITIES: readonly FeedSeverity[] = ["info", "warn", "error"];

export interface LiveFeedProps {
  /** Overrides the store — for a screen that renders a fixed slice, and for tests. */
  events?: readonly FeedEvent[] | undefined;
  timeZoneMode?: TimeZoneMode | undefined;
  className?: string | undefined;
}

export function LiveFeed({ events, timeZoneMode, className }: LiveFeedProps): ReactElement {
  const mode = useTimeZoneMode(timeZoneMode);
  const stored = useVisibleFeed();
  const isPaused = useFeedStore((state) => state.isPaused);
  const bufferedCount = useFeedStore((state) => state.buffered.length);
  const severityFilter = useFeedStore((state) => state.severityFilter);
  const togglePaused = useFeedStore((state) => state.togglePaused);
  const flushBuffered = useFeedStore((state) => state.flushBuffered);
  const setSeverityFilter = useFeedStore((state) => state.setSeverityFilter);

  const shown = events ?? stored;

  return (
    <section
      data-testid="live-feed"
      aria-label="live feed"
      // A card: paper, a 28px radius and a whisper of shadow. No border, and no rule under
      // the header either — the gap does that work now.
      className={cn("flex flex-col rounded-card bg-surface-card shadow-card", className)}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 px-card pb-3 pt-card">
        <h2 className="type-h2 text-ink">feed</h2>
        <div className="flex items-center gap-1">
          {SEVERITIES.map((severity) => (
            /*
             * A segmented control, and the one place the secondary idiom is painted in a hue
             * that is not known until render. Pressed, it is `tinted`: the severity's own
             * `--x-tint` as the ground and that family's text-safe `--x` as the label, which
             * is exactly the pair `tokenContrast.test.ts` measures per family per palette
             * (`--error` on `--error-tint` is 4.71:1 light, 4.64:1 dark). Unpressed, it is
             * `quiet` — no ground at all, rather than the grey chip it used to be.
             */
            <Button
              key={severity}
              variant={severityFilter === severity ? "tinted" : "quiet"}
              size="chip"
              shape="pill"
              aria-pressed={severityFilter === severity}
              onClick={() => {
                setSeverityFilter(severityFilter === severity ? null : severity);
              }}
              style={
                severityFilter === severity
                  ? {
                      color: feedSeverityColorVar(severity),
                      backgroundColor: tintVar(feedSeverityColorVar(severity)),
                    }
                  : {}
              }
            >
              {severity}
            </Button>
          ))}
          <Button
            variant={segmentVariant(isPaused)}
            size="chip"
            shape="pill"
            data-testid="live-feed-pause"
            aria-pressed={isPaused}
            onClick={togglePaused}
          >
            {isPaused ? "▶ resume" : "❚❚ pause"}
          </Button>
        </div>
      </header>

      {/* "N events held while paused — show" is an ACTION, so it is the secondary idiom
          rather than a grey slab: a tint of the hue with the hue as the label. */}
      {isPaused ? (
        <Button
          variant="secondary"
          size="xs"
          data-testid="live-feed-buffered"
          onClick={flushBuffered}
          className="mx-card mb-2 justify-start rounded-control px-3 py-2 text-left"
        >
          <span className="num">{formatInteger(bufferedCount)}</span>
          {bufferedCount === 1 ? " event held while paused" : " events held while paused"}
          {" — show"}
        </Button>
      ) : null}

      {/* Feed items are separated by SPACE, not by rules — a `divide-y` here was the old
          language, and this design draws no hairlines between prose rows. */}
      <ol className="flex flex-col gap-0.5 px-2 pb-3">
        {shown.length === 0 ? (
          <li className="type-body-sm px-3 py-6 text-ink-muted" data-testid="live-feed-empty">
            {/* Never "nothing happened": the feed reports what was RECORDED (§11.5). */}
            nothing recorded yet
          </li>
        ) : (
          shown.map((event) => (
            <li
              key={event.id}
              data-testid="live-feed-row"
              data-severity={event.severity}
              className={cn(
                "flex flex-wrap items-baseline gap-2 rounded-control px-3 py-2",
                "transition-colors duration-fast ease-standard hover:bg-surface-control",
              )}
            >
              <span
                aria-hidden="true"
                style={{ color: feedSeverityColorVar(event.severity) }}
                className="leading-none"
              >
                {feedSeverityGlyph(event.severity)}
              </span>
              <span className="type-mono num text-ink-muted">{formatTimestamp(event.at, mode)}</span>
              <span className="type-body-sm flex-1 text-ink">{event.label}</span>
              {event.orderId === null ? null : <OrderRefChip orderId={event.orderId} />}
              {event.correlationId === null ? null : (
                <CorrelationChip correlationId={event.correlationId} />
              )}
            </li>
          ))
        )}
      </ol>
    </section>
  );
}
