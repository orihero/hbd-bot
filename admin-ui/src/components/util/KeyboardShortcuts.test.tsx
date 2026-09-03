/** The global bindings, and the one rule that keeps them tolerable: never steal a keystroke. */

import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { usePrefsStore } from "@/lib/stores";

import { KeyboardShortcuts } from "./KeyboardShortcuts";
import { isTypingTarget, shortcutRows } from "./shortcuts";
import { renderWithProviders, resetPrefs } from "./testRender";

beforeEach(() => {
  resetPrefs();
});

describe("isTypingTarget", () => {
  it("is true for the places an operator composes text", () => {
    for (const tag of ["input", "textarea", "select"] as const) {
      expect(isTypingTarget(document.createElement(tag))).toBe(true);
    }
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    // jsdom does not implement `isContentEditable` from the attribute; assert the property.
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isTypingTarget(editable)).toBe(true);
  });

  it("is false for a button, a link and a null target", () => {
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(isTypingTarget(document.createElement("a"))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("bindings", () => {
  it("⌘K toggles the palette", () => {
    renderWithProviders(<KeyboardShortcuts />);
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(true);
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(false);
  });

  it("Ctrl+K does the same, for the operators who are not on a Mac", () => {
    renderWithProviders(<KeyboardShortcuts />);
    fireEvent.keyDown(document, { key: "K", ctrlKey: true });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(true);
  });

  it("⌘K works even inside a field — it is the global entry point", () => {
    renderWithProviders(
      <KeyboardShortcuts>
        <input aria-label="filter" />
      </KeyboardShortcuts>,
    );
    fireEvent.keyDown(screen.getByLabelText("filter"), { key: "k", metaKey: true });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(true);
  });

  it("/ opens the palette", () => {
    renderWithProviders(<KeyboardShortcuts />);
    fireEvent.keyDown(document, { key: "/" });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(true);
  });

  it("/ inside a filter box types a slash instead of opening the palette", () => {
    // The single most common way a shortcut layer becomes something people ask to turn off.
    renderWithProviders(
      <KeyboardShortcuts>
        <input aria-label="filter" />
      </KeyboardShortcuts>,
    );
    fireEvent.keyDown(screen.getByLabelText("filter"), { key: "/" });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(false);
  });

  it("? opens the shortcut sheet", () => {
    renderWithProviders(<KeyboardShortcuts />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: "?" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Keyboard")).toBeInTheDocument();
  });

  it("ignores a chord it does not own", () => {
    renderWithProviders(<KeyboardShortcuts />);
    fireEvent.keyDown(document, { key: "/", ctrlKey: true });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(false);
  });
});

describe("the sheet", () => {
  it("lists ⌘K on a Mac and Ctrl elsewhere", () => {
    expect(shortcutRows(true)[0]?.keys).toEqual(["⌘", "K"]);
    expect(shortcutRows(false)[0]?.keys).toEqual(["Ctrl", "K"]);
  });

  it("binds nothing destructive to a single key", () => {
    // §12.2 puts every write behind a click and a step-up. A stray keystroke must never
    // start a retry, a force-deliver, a block or a purge.
    const descriptions = shortcutRows(true).map((row) => row.description.toLowerCase());
    for (const forbidden of ["retry", "deliver", "block", "purge", "cancel", "approve"]) {
      expect(descriptions.some((text) => text.includes(forbidden))).toBe(false);
    }
  });
});
