/**
 * §14's Slice 1d acceptance criterion, as a test:
 *
 *   "Order detail shows a 9-stage `stagePlan` (not 11) with the two greeting stages
 *    ghosted, and the failed stage highlighted with its error code and retryability."
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PIPELINE_STAGE_VALUES } from "@/api";

import { makeFailedStagePlan, makeStagePlan } from "./fixtures";
import { PipelineTimeline } from "./PipelineTimeline";
import { NO_RECORD_LABEL, planEntries } from "./stagePlan";

describe("nine stages by default, not eleven", () => {
  it("draws all eleven and marks nine as scheduled", () => {
    render(<PipelineTimeline plan={makeStagePlan()} />);
    expect(screen.getAllByTestId("pipeline-stage")).toHaveLength(PIPELINE_STAGE_VALUES.length);
    expect(screen.getByTestId("scheduled-stage-count")).toHaveTextContent("9");
  });

  it("ghosts the two greeting stages rather than dropping them", () => {
    render(<PipelineTimeline plan={makeStagePlan()} />);
    const ghosted = screen
      .getAllByTestId("pipeline-stage")
      .filter((node) => node.getAttribute("data-planned") === "false");
    expect(ghosted).toHaveLength(2);
    expect(ghosted.map((node) => node.getAttribute("data-stage"))).toEqual([
      "writing_scripts",
      "rendering_greetings",
    ]);
    // Present and captioned, not silently missing.
    expect(ghosted[0]).toHaveTextContent("not planned in this deployment");
  });

  it("keeps every stage when the deployment schedules all eleven", () => {
    const plan = makeStagePlan({ scheduledStageCount: 11, greetingEvidence: "present" });
    render(<PipelineTimeline plan={plan} />);
    expect(
      screen
        .getAllByTestId("pipeline-stage")
        .filter((node) => node.getAttribute("data-planned") === "false"),
    ).toHaveLength(0);
  });
});

describe("the failed stage", () => {
  it("carries its error code and its retryability, not just a red dot", () => {
    render(<PipelineTimeline plan={makeFailedStagePlan()} />);
    const failed = screen
      .getAllByTestId("pipeline-stage")
      .find((node) => node.getAttribute("data-outcome") === "failed");
    expect(failed).toBeDefined();
    expect(failed).toHaveTextContent("MUSIC_PROVIDER_TIMEOUT");
    expect(failed).toHaveTextContent("retryable");
    expect(failed).toHaveTextContent("3 attempts");
    // The failure ring: `--shadow-glow-red` was retired with the old palette; the reskin's
    // equivalent is a 1px `--error-fill` ring, which clears 1.4.11's 3:1 in both themes.
    // It is a THIRD channel here, never the only one — the code and the word are above it.
    expect(failed?.className).toContain("shadow-ring-error");
  });
});

describe("what an absence means", () => {
  it("says 'no record' for not_observed — never 'did not run'", () => {
    render(<PipelineTimeline plan={makeStagePlan()} />);
    const validating = screen
      .getAllByTestId("pipeline-stage")
      .find((node) => node.getAttribute("data-stage") === "validating");
    expect(validating).toHaveTextContent(NO_RECORD_LABEL);
    expect(validating).not.toHaveTextContent("did not run");
  });

  it("captions the plan as inferred, because it is reconstructed from attempt rows", () => {
    render(<PipelineTimeline plan={makeStagePlan()} />);
    expect(screen.getByTestId("pipeline-timeline")).toHaveTextContent(
      "inferred from attempt rows",
    );
  });

  it("says so when the greeting evidence does not settle the question", () => {
    render(<PipelineTimeline plan={makeStagePlan({ isConclusive: false })} />);
    expect(screen.getByTestId("pipeline-timeline")).toHaveTextContent(
      "greeting evidence is inconclusive",
    );
  });
});

describe("planEntries", () => {
  it("reads scheduledStageCount and never stages.length", () => {
    const entries = planEntries(makeStagePlan({ scheduledStageCount: 10 }));
    expect(entries.filter((entry) => !entry.isPlanned)).toHaveLength(1);
    // Ghosting runs from the END, so the later greeting stage is the one dropped.
    expect(entries.find((entry) => !entry.isPlanned)?.stage).toBe("rendering_greetings");
  });
});
