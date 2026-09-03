/** The render-crash boundary. Scoped, resettable, and not where API failures go. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";
import { renderWithProviders } from "./testRender";

function Boom(): never {
  throw new Error("index out of range");
}

// React logs the caught error itself; silencing it keeps the run readable without hiding a
// real failure, because the assertions below are what decide the test.
let consoleError: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  consoleError.mockRestore();
});

describe("ErrorBoundary", () => {
  it("catches a render throw and shows the message to paste into a report", () => {
    renderWithProviders(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("index out of range")).toBeInTheDocument();
  });

  it("says it is a bug in the panel, not a failed request", () => {
    renderWithProviders(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/bug in the panel, not a failed request/u)).toBeInTheDocument();
  });

  it("calls onError with the error", () => {
    const onError = vi.fn();
    renderWithProviders(
      <ErrorBoundary onError={onError}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledOnce();
  });

  it("renders a custom fallback and its reset", async () => {
    let shouldThrow = true;
    function Maybe() {
      if (shouldThrow) throw new Error("boom");
      return <p>recovered</p>;
    }

    renderWithProviders(
      <ErrorBoundary
        fallback={(error, reset) => (
          <button
            type="button"
            onClick={() => {
              shouldThrow = false;
              reset();
            }}
          >
            {error.message}
          </button>
        )}
      >
        <Maybe />
      </ErrorBoundary>,
    );

    await userEvent.click(screen.getByRole("button", { name: "boom" }));
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });

  it("resets when a resetKey changes, so a crash does not follow a navigation", () => {
    let shouldThrow = true;
    function Maybe() {
      if (shouldThrow) throw new Error("boom");
      return <p>next screen</p>;
    }

    const { rerender } = renderWithProviders(
      <ErrorBoundary resetKeys={["/orders"]}>
        <Maybe />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();

    shouldThrow = false;
    rerender(
      <ErrorBoundary resetKeys={["/users"]}>
        <Maybe />
      </ErrorBoundary>,
    );
    expect(screen.getByText("next screen")).toBeInTheDocument();
  });
});
