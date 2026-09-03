/** §11.4's error state, and §11.1's loud SCHEMA_DRIFT banner. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiFailureError, failure } from "@/api";

import { ErrorState } from "./ErrorState";
import { renderWithProviders } from "./testRender";

describe("ErrorState", () => {
  it("shows the code, the message and a copyable correlation id", () => {
    renderWithProviders(
      <ErrorState
        failure={failure({
          code: "UPSTREAM_5XX",
          message: "the provider returned 502",
          status: 502,
          endpoint: "orders",
          correlationId: "0123456789abcdef0123456789abcdef",
        })}
        what="orders"
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("UPSTREAM_5XX")).toBeInTheDocument();
    expect(screen.getByText("the provider returned 502")).toBeInTheDocument();
    expect(screen.getByText("0123456789abcdef0123456789abcdef")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy correlation id" })).toBeInTheDocument();
  });

  it("unwraps a thrown ApiFailureError from a query", () => {
    renderWithProviders(
      <ErrorState
        error={
          new ApiFailureError(
            failure({ code: "NOT_FOUND", message: "no such order", status: 404, endpoint: "order" }),
          )
        }
        what="this order"
      />,
    );
    expect(screen.getByText("NOT_FOUND")).toBeInTheDocument();
  });

  it("names the refused permission on a 403, so the absence is explained", () => {
    renderWithProviders(
      <ErrorState
        failure={failure({
          code: "FORBIDDEN",
          message: "refused",
          status: 403,
          endpoint: "audit",
          details: { permission: "audit.read" },
        })}
        what="the audit log"
      />,
    );
    expect(screen.getByText("Your role cannot read the audit log")).toBeInTheDocument();
    expect(screen.getByText("audit.read")).toBeInTheDocument();
  });

  it("renders SCHEMA_DRIFT loudly, naming the endpoint and each failing field path", () => {
    // §11.1: the frontend twin of treating a stored-row ValidationError as a loud
    // data-integrity bug. The one thing that must not happen is a quiet retry.
    renderWithProviders(
      <ErrorState
        failure={failure({
          code: "SCHEMA_DRIFT",
          message: "response did not match",
          status: 200,
          endpoint: "orders",
          issues: [
            { path: "items.0.state", message: "invalid enum value" },
            { path: "", message: "expected object" },
          ],
        })}
        what="orders"
      />,
    );
    expect(screen.getByText("schema drift")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
    expect(screen.getByText("items.0.state")).toBeInTheDocument();
    // An empty path is the root, and must not render as an empty bullet.
    expect(screen.getByText("(root)")).toBeInTheDocument();
  });

  it("shows Retry-After on a rate limit", () => {
    renderWithProviders(
      <ErrorState
        failure={failure({
          code: "LOGIN_RATE_LIMITED",
          message: "too many attempts",
          status: 429,
          endpoint: "login",
          retryAfterS: 90,
        })}
      />,
    );
    expect(screen.getByText("90")).toBeInTheDocument();
  });

  it("offers Try again only when the caller supplied a retry", async () => {
    const onRetry = vi.fn();
    const { unmount } = renderWithProviders(
      <ErrorState
        failure={failure({ code: "UNKNOWN", message: "x", status: 500, endpoint: "orders" })}
        onRetry={onRetry}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
    unmount();

    renderWithProviders(
      <ErrorState
        failure={failure({ code: "FORBIDDEN", message: "x", status: 403, endpoint: "audit" })}
      />,
    );
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("hides the HTTP badge for a transport failure, which has no status", () => {
    renderWithProviders(
      <ErrorState
        failure={failure({ code: "NETWORK_ERROR", message: "offline", status: 0, endpoint: "ops" })}
      />,
    );
    expect(screen.queryByText(/^HTTP/u)).not.toBeInTheDocument();
  });
});
