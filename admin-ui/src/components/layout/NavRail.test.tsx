/** The rail: §11.2's order, the 220/64 collapse, and the two different kinds of absence. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { usePrefsStore } from "@/lib/stores";
import { meFixture, renderWithProviders, resetPrefs } from "@/components/util/testRender";

import { NavRail } from "./NavRail";

beforeEach(() => {
  resetPrefs();
});

function labels(): string[] {
  const nav = screen.getByRole("navigation", { name: "Sections" });
  return within(nav)
    .getAllByRole("listitem")
    .map((item) => item.textContent ?? "");
}

describe("order", () => {
  it("is exactly §11.2's, for an OWNER who sees everything", () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    // Live · Orders · Users · Generations · Assets · Chat · Payments · Moderation
    // ─── Config · Audit · Admins
    expect(labels().map((text) => text.replace("phase 3", "").trim())).toEqual([
      "Live",
      "Orders",
      "Users",
      "Generations",
      "Assets",
      "Chat",
      "Payments",
      "Moderation",
      "Config",
      "Audit",
      "Admins",
    ]);
  });

  it("keeps the rule between the operational and administrative groups", () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });
});

describe("phase-3 sections", () => {
  it("are present but not links, so the IA does not reshuffle when they land", () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    for (const label of ["Chat", "Payments", "Moderation"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
    expect(screen.getAllByText("phase 3")).toHaveLength(3);
  });
});

describe("role-based hiding (§11.4)", () => {
  it("hides Audit and Admins from a VIEWER — not disabled, absent", () => {
    renderWithProviders(<NavRail />, { me: meFixture("viewer") });
    expect(screen.queryByText("Audit")).not.toBeInTheDocument();
    expect(screen.queryByText("Admins")).not.toBeInTheDocument();
    expect(screen.getByText("Config")).toBeInTheDocument();
  });

  it("shows Audit to the plan's OPERATOR (wire spelling `admin`) but not Admins", () => {
    renderWithProviders(<NavRail />, { me: meFixture("admin") });
    expect(screen.getByText("Audit")).toBeInTheDocument();
    expect(screen.queryByText("Admins")).not.toBeInTheDocument();
  });

  it("shows Admins only to OWNER", () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    expect(screen.getByText("Admins")).toBeInTheDocument();
  });
});

describe("collapse", () => {
  it("is 220px expanded and 64px collapsed, and the choice is persisted state", async () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(nav).toHaveClass("w-nav");
    expect(nav).toHaveAttribute("data-collapsed", "false");

    await userEvent.click(screen.getByRole("button", { name: "Collapse the sections rail" }));

    expect(usePrefsStore.getState().isNavCollapsed).toBe(true);
    expect(screen.getByRole("navigation", { name: "Sections" })).toHaveClass("w-nav-collapsed");
  });

  it("keeps every item's accessible name at 64px", () => {
    usePrefsStore.setState({ isNavCollapsed: true });
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    // Icon-only, but still navigable: an icon with no name is a rail only its author can use.
    expect(screen.getByRole("link", { name: "Orders" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Live" })).toBeInTheDocument();
  });
});

describe("active marking", () => {
  it("marks only the current section, and `/` is an exact match", () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner"), route: "/orders" });
    expect(screen.getByRole("link", { name: "Orders" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Live" })).not.toHaveAttribute("aria-current");
  });
});
