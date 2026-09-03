/**
 * The page header: one `h1`, §11.2's dominant-signal slot, and the trail the reskin added
 * beneath the title.
 *
 * The two assertions that are requirements rather than descriptions: there is still exactly
 * ONE `h1` per screen with the trail present (the browser gate locates screens by
 * `getByRole("heading", { name, level: 1 })`), and the `signal` slot still renders — §11.2's
 * dominant signal is the loudest thing on the screen and the header is where it lives.
 */

import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/components/util/testRender";

import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("renders the title as the screen's one and only h1", () => {
    renderWithProviders(<PageHeader title="Orders" />, { route: "/orders" });
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("Orders");
  });

  it("puts a breadcrumb trail under the title, derived from the route", () => {
    renderWithProviders(<PageHeader title="Order detail" />, {
      route: "/orders/0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30",
    });
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(within(trail).getByRole("link", { name: "Orders" })).toHaveAttribute("href", "/orders");
    // The current page is text, not a link, and says so to a screen reader.
    expect(within(trail).queryByRole("link", { name: "Detail" })).not.toBeInTheDocument();
    expect(within(trail).getByText("Detail")).toHaveAttribute("aria-current", "page");
  });

  it("does not add a second heading — the trail is a nav, not a hierarchy", () => {
    // A trail built out of headings would compete with the h1 for the page's structure and
    // would break the browser gate's `level: 1` lookup.
    renderWithProviders(<PageHeader title="Orders" />, { route: "/orders" });
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).queryAllByRole("heading")).toHaveLength(0);
  });

  it("still renders §11.2's dominant signal, the description and the actions", () => {
    renderWithProviders(
      <PageHeader
        title="Live Ops"
        description="Is the pipeline delivering?"
        signal={<p>the loudest number</p>}
        actions={<button type="button">Refresh</button>}
      >
        <p>a filter bar</p>
      </PageHeader>,
      { route: "/" },
    );
    expect(screen.getByText("the loudest number")).toBeInTheDocument();
    expect(screen.getByText("Is the pipeline delivering?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.getByText("a filter bar")).toBeInTheDocument();
  });

  it("shows a trail on the root screen too, so no page is missing its place", () => {
    renderWithProviders(<PageHeader title="Live Ops" />, { route: "/" });
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByText("Home")).toHaveAttribute("aria-current", "page");
  });
});
