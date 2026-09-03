/** All six of §11.4's states, rendered. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiFailureError, failure } from "@/api";
import { LIVE_THRESHOLD_MS } from "@/lib/queryClient";

import { AsyncBoundary } from "./AsyncBoundary";
import { SkeletonTable } from "./Skeleton";
import { renderWithProviders, resetPrefs } from "./testRender";

const SKELETON = <SkeletonTable rows={3} columns={4} />;

beforeEach(() => {
  resetPrefs();
});

describe("skeleton", () => {
  it("renders the caller's skeleton, never a spinner", () => {
    renderWithProviders(
      <AsyncBoundary status="pending" hasData={false} skeleton={SKELETON} noun="orders">
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByTestId("skeleton-table")).toBeInTheDocument();
    expect(screen.getByText("Loading orders")).toBeInTheDocument();
    expect(screen.queryByText("rows")).not.toBeInTheDocument();
  });

  it("matches the row count it was asked for, so the final dimensions match", () => {
    renderWithProviders(
      <AsyncBoundary
        status="pending"
        hasData={false}
        skeleton={<SkeletonTable rows={7} columns={2} withHeader={false} />}
        noun="orders"
      >
        <p>rows</p>
      </AsyncBoundary>,
    );
    // 7 rows x 2 columns, no header.
    expect(screen.getAllByTestId("skeleton")).toHaveLength(14);
  });
});

describe("empty", () => {
  it("virgin states the fact", () => {
    renderWithProviders(
      <AsyncBoundary status="success" isEmpty skeleton={SKELETON} noun="orders">
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText("No orders yet")).toBeInTheDocument();
  });

  it("filtered names the filter count and offers Clear", async () => {
    const onClearFilters = vi.fn();
    renderWithProviders(
      <AsyncBoundary
        status="success"
        isEmpty
        activeFilterCount={3}
        onClearFilters={onClearFilters}
        skeleton={SKELETON}
        noun="orders"
      >
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText("No orders match these filters")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClearFilters).toHaveBeenCalledOnce();
  });

  it("says 'filter is' for one and 'filters are' for many", () => {
    const { unmount } = renderWithProviders(
      <AsyncBoundary status="success" isEmpty activeFilterCount={1} skeleton={SKELETON}>
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText(/filter is narrowing/u)).toBeInTheDocument();
    unmount();
    renderWithProviders(
      <AsyncBoundary status="success" isEmpty activeFilterCount={2} skeleton={SKELETON}>
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText(/filters are narrowing/u)).toBeInTheDocument();
  });
});

describe("error", () => {
  it("shows the code and a copyable correlation id, and keeps nothing stale on screen", () => {
    const thrown = new ApiFailureError(
      failure({
        code: "UPSTREAM_TIMEOUT",
        message: "the pipeline timed out",
        status: 504,
        endpoint: "orders",
        correlationId: "0123456789abcdef0123456789abcdef",
      }),
    );
    renderWithProviders(
      <AsyncBoundary
        status="error"
        hasData={false}
        error={thrown}
        skeleton={SKELETON}
        noun="orders"
      >
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText("UPSTREAM_TIMEOUT")).toBeInTheDocument();
    expect(screen.getByText("0123456789abcdef0123456789abcdef")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy correlation id" })).toBeInTheDocument();
  });
});

describe("stale", () => {
  it("keeps the last-known children and labels them 'stale 42s'", () => {
    const now = Date.now();
    renderWithProviders(
      <AsyncBoundary
        status="success"
        dataUpdatedAt={now - 42_000}
        skeleton={SKELETON}
        noun="orders"
      >
        <p>last known rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText("last known rows")).toBeInTheDocument();
    expect(screen.getByText("stale 42s")).toBeInTheDocument();
  });

  it("is what a failed poll looks like when data is still in hand", () => {
    const now = Date.now();
    renderWithProviders(
      <AsyncBoundary
        status="error"
        hasData
        error={
          new ApiFailureError(
            failure({ code: "NETWORK_ERROR", message: "offline", status: 0, endpoint: "orders" }),
          )
        }
        dataUpdatedAt={now - LIVE_THRESHOLD_MS - 5_000}
        skeleton={SKELETON}
        noun="orders"
      >
        <p>last known rows</p>
      </AsyncBoundary>,
    );
    // The numbers survive. That is the whole point of §11.4's stale state.
    expect(screen.getByText("last known rows")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // …and the code is on the chip, so the stall is searchable in a log.
    expect(screen.getByText("NETWORK_ERROR")).toBeInTheDocument();
  });
});

describe("purged", () => {
  it("is a lock, a stamp and the clock that did it — never an error, never a blank", () => {
    renderWithProviders(
      <AsyncBoundary
        status="success"
        purgedAt="2026-05-14T03:00:00Z"
        purgedBy="identity retention clock"
        skeleton={SKELETON}
        noun="the recipient"
      >
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText(/🔒/u)).toBeInTheDocument();
    expect(screen.getByText("2026-05-14")).toBeInTheDocument();
    expect(screen.getByText("Removed by the identity retention clock.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("rows")).not.toBeInTheDocument();
  });

  it("beats an error on the same panel", () => {
    renderWithProviders(
      <AsyncBoundary
        status="error"
        hasData={false}
        error={
          new ApiFailureError(
            failure({ code: "NOT_FOUND", message: "gone", status: 404, endpoint: "order" }),
          )
        }
        purgedAt="2026-05-14T03:00:00Z"
        skeleton={SKELETON}
      >
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText("2026-05-14")).toBeInTheDocument();
    expect(screen.queryByText("NOT_FOUND")).not.toBeInTheDocument();
  });
});

describe("ready", () => {
  it("just renders the children", () => {
    renderWithProviders(
      <AsyncBoundary status="success" dataUpdatedAt={Date.now()} skeleton={SKELETON}>
        <p>rows</p>
      </AsyncBoundary>,
    );
    expect(screen.getByText("rows")).toBeInTheDocument();
    expect(screen.queryByTestId("skeleton-table")).not.toBeInTheDocument();
  });
});
