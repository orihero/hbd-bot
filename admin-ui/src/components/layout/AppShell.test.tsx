/**
 * The shell's four load-bearing placements. Each test is a regression guard for a specific
 * way the layout can be "tidied" into a bug.
 */

import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { meFixture, configFixture, renderWithProviders, resetPrefs } from "@/components/util/testRender";
import { usePlayerStore } from "@/lib/stores";

import { AppShell } from "./AppShell";

beforeEach(() => {
  resetPrefs();
  usePlayerStore.getState().stop();
});

afterEach(() => {
  usePlayerStore.getState().stop();
});

describe("AppShell", () => {
  it("renders the rail, the top bar and the screen", () => {
    renderWithProviders(
      <AppShell>
        <p>screen body</p>
      </AppShell>,
      { me: meFixture("owner"), config: configFixture("staging") },
    );
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("screen body");
  });

  it("reads the environment from /api/config for the badge", () => {
    renderWithProviders(
      <AppShell>
        <p>screen body</p>
      </AppShell>,
      { me: meFixture("owner"), config: configFixture("prod") },
    );
    expect(screen.getByText("prod")).toBeInTheDocument();
  });

  it("says 'env unknown' when config is unavailable, rather than guessing dev", () => {
    renderWithProviders(
      <AppShell>
        <p>screen body</p>
      </AppShell>,
      { me: meFixture("owner"), config: null },
    );
    expect(screen.getByText("env unknown")).toBeInTheDocument();
  });

  it("puts the skip link first, ahead of eleven rail items", () => {
    renderWithProviders(
      <AppShell>
        <p>screen body</p>
      </AppShell>,
      { me: meFixture("owner") },
    );
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("keeps the player OUTSIDE main, so one <audio> survives a route change", () => {
    usePlayerStore.getState().play({
      assetId: "a1",
      orderId: null,
      src: "/api/assets/a1/stream",
      kind: "song",
      label: "order 4f2a · song v1",
      durationS: 61,
    });

    renderWithProviders(
      <AppShell>
        <p>screen body</p>
      </AppShell>,
      { me: meFixture("owner") },
    );

    const player = screen.getByRole("region", { name: "Audio player" });
    expect(player).toBeInTheDocument();
    expect(screen.getByRole("main").contains(player)).toBe(false);
  });

  it("scopes the crash boundary to main, so the rail and top bar survive a broken screen", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Boom(): never {
      throw new Error("screen exploded");
    }

    renderWithProviders(
      <AppShell>
        <Boom />
      </AppShell>,
      { me: meFixture("owner") },
    );

    expect(screen.getByText("screen exploded")).toBeInTheDocument();
    // The operator can still navigate away from the screen that broke.
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
