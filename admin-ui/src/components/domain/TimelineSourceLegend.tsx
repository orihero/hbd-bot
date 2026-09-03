/**
 * `<TimelineSourceLegend>` — why a section of the merged timeline is empty.
 *
 * §11.2, for `/orders/:id`: "The merged timeline renders a `sources` legend so an absent
 * section reads as **'not enabled in this deployment'**, never as 'nothing happened'."
 *
 * That distinction is the entire component. `chat` and `payments` have no capture in this
 * deployment at all: there are no rows, there is no endpoint, and an empty chat section
 * means the feature is off — NOT that the customer said nothing. An operator who reads the
 * second meaning concludes a customer never replied and closes a ticket wrongly. The copy
 * is pinned in `SOURCE_UNAVAILABLE_LABEL` and must not be paraphrased.
 *
 * State transitions get their own row, labelled **inferred**: there is no state-transition
 * log on this build (`CapabilitiesView.isStateTransitionLog`), so the ordering of an order's
 * states is reconstructed from what the other sources recorded. "Inferred" is a third
 * answer, distinct from both "available" and "not enabled" — the data is derived, so it is
 * correct as far as it goes and cannot be treated as a record.
 */

import type { ReactElement } from "react";

import { SOURCE_UNAVAILABLE_LABEL, TIMELINE_SOURCE_VALUES, type TimelineSource } from "@/api";
import { cn, humaniseEnum } from "@/lib";

/** `stateTransitions` is labelled `inferred` (§14 Slice 1d acceptance). */
export const STATE_TRANSITIONS_LABEL = "state transitions";
export const INFERRED_SOURCE_LABEL = "inferred";

export interface TimelineSourceLegendProps {
  availableSources: readonly TimelineSource[];
  unavailableSources: readonly TimelineSource[];
  /**
   * Whether the state ordering is derived rather than recorded. `true` on this build —
   * there is no state-transition log — and the row says so either way.
   */
  isStateTransitionsInferred?: boolean | undefined;
  className?: string | undefined;
}

type SourceStanding = "available" | "unavailable" | "unknown";

function standingOf(
  source: TimelineSource,
  available: readonly TimelineSource[],
  unavailable: readonly TimelineSource[],
): SourceStanding {
  if (available.includes(source)) return "available";
  if (unavailable.includes(source)) return "unavailable";
  // The server names every source in one list or the other. A source in neither is not
  // "fine" — it is a source this build has never heard of, and saying so is better than
  // guessing in either direction.
  return "unknown";
}

const STANDING_GLYPH: Record<SourceStanding, string> = {
  available: "✓",
  unavailable: "⊘",
  unknown: "?",
};

/*
 * These paint the `aria-hidden` STANDING_GLYPH only — the row says "not enabled in this
 * deployment" in words beside it — so 1.4.11's 3:1 is the bar.
 *
 * The "unavailable" glyph used to be `--fg-2`, the POLICED mark colour, and needed a waiver
 * in `tokenContrast.test.ts` to say so. It is `--neutral` now: a true grey that is text-safe
 * (4.52:1 worst-case light, 4.60:1 dark) and therefore needs no waiver at all. Clearing the
 * higher bar outright is a better answer than being excused from it, and `⊘` beside the
 * words reads the same either way.
 */
const STANDING_COLOR: Record<SourceStanding, string> = {
  available: "var(--success)",
  unavailable: "var(--neutral)",
  unknown: "var(--caution)",
};

export function TimelineSourceLegend({
  availableSources,
  unavailableSources,
  isStateTransitionsInferred = true,
  className,
}: TimelineSourceLegendProps): ReactElement {
  return (
    <section
      data-testid="timeline-source-legend"
      aria-label="timeline sources"
      className={cn("rounded-card bg-surface-card p-card shadow-card", className)}
    >
      <h3 className="type-caption mb-3 text-ink-muted">sources</h3>
      <ul className="flex flex-col gap-2">
        {TIMELINE_SOURCE_VALUES.map((source) => {
          const standing = standingOf(source, availableSources, unavailableSources);
          return (
            <li
              key={source}
              data-testid="timeline-source"
              data-source={source}
              data-standing={standing}
              className="flex items-baseline gap-2"
            >
              <span aria-hidden="true" style={{ color: STANDING_COLOR[standing] }}>
                {STANDING_GLYPH[standing]}
              </span>
              <span className="type-body-sm text-ink">{humaniseEnum(source)}</span>
              {standing === "available" ? null : (
                <span className="type-body-sm text-ink-muted">
                  {standing === "unavailable" ? SOURCE_UNAVAILABLE_LABEL : "unrecognised source"}
                </span>
              )}
            </li>
          );
        })}
        <li
          data-testid="timeline-source"
          data-source="state_transitions"
          data-standing={isStateTransitionsInferred ? "inferred" : "available"}
          className="flex items-baseline gap-2"
        >
          <span aria-hidden="true" style={{ color: "var(--info)" }}>
            ≈
          </span>
          <span className="type-body-sm text-ink">{STATE_TRANSITIONS_LABEL}</span>
          <span className="type-body-sm text-ink-muted">
            {isStateTransitionsInferred ? INFERRED_SOURCE_LABEL : "recorded"}
          </span>
        </li>
      </ul>
    </section>
  );
}
