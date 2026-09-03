/**
 * The top bar's controls. The UTC/local toggle gets the most attention here because §11.2
 * says an ambiguous "14:32" is a support incident, and the toggle is the only thing standing
 * between the operator and one.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { configFixture, meFixture, renderWithProviders, resetPrefs } from "@/components/util/testRender";
import { localOffsetLabel } from "@/lib/format";
import { usePrefsStore } from "@/lib/stores";

import { TopBar } from "./TopBar";

beforeEach(() => {
  resetPrefs();
});

describe("TopBar", () => {
  it("shows §11.2's controls: env, palette, LIVE, clock, theme, account", () => {
    renderWithProviders(<TopBar />, { me: meFixture("owner"), config: configFixture("dev") });
    expect(screen.getByText("dev")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open the command palette" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/LIVE|LAGGING|STALLED|PAUSED/u);
    expect(screen.getByRole("button", { name: /Timestamps are shown in UTC/u })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Theme:/u })).toBeInTheDocument();
    expect(screen.getByText("operator")).toBeInTheDocument();
  });

  it("defaults to UTC and names both zones on the toggle", async () => {
    renderWithProviders(<TopBar />, { me: meFixture("owner") });
    const toggle = screen.getByRole("button", { name: /Timestamps are shown in UTC/u });
    // The label states the CURRENT setting and what a click would change it to — an
    // operator must never have to click to find out which clock they are reading.
    expect(toggle).toHaveAccessibleName(`Timestamps are shown in UTC. Switch to ${localOffsetLabel()}.`);

    await userEvent.click(toggle);
    expect(usePrefsStore.getState().timeZoneMode).toBe("local");
    expect(screen.getByRole("button", { name: /Switch to UTC/u })).toBeInTheDocument();
  });

  it("cycles the theme light → dark → system → light", async () => {
    // The cycle starts from LIGHT because the store now defaults to it: `:root` carries the
    // light palette and `[data-theme="dark"]` overrides it, so light is what an operator who
    // has never touched this button is looking at.
    renderWithProviders(<TopBar />, { me: meFixture("owner") });
    await userEvent.click(screen.getByRole("button", { name: "Theme: Light. Switch to Dark." }));
    expect(usePrefsStore.getState().theme).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Theme: Dark. Switch to System." }));
    expect(usePrefsStore.getState().theme).toBe("system");
    await userEvent.click(screen.getByRole("button", { name: "Theme: System. Switch to Light." }));
    expect(usePrefsStore.getState().theme).toBe("light");
  });

  it("opens the palette from its trigger as well as from ⌘K", async () => {
    renderWithProviders(<TopBar />, { me: meFixture("owner") });
    await userEvent.click(screen.getByRole("button", { name: "Open the command palette" }));
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(true);
  });

  it("names the signed-in role, the one place an absent affordance is explained", () => {
    renderWithProviders(<TopBar />, { me: meFixture("support") });
    expect(screen.getByText("support")).toBeInTheDocument();
  });
});
