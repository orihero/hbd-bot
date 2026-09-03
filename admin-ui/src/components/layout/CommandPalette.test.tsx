/** The palette as an operator meets it: type a shape, press Enter, land somewhere. */

import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes, useLocation } from "react-router-dom";

import { renderWithProviders, resetPrefs } from "@/components/util/testRender";
import { usePrefsStore } from "@/lib/stores";

import { CommandPalette } from "./CommandPalette";

const UUID = "0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30";

function Here() {
  const location = useLocation();
  return <p data-testid="here">{`${location.pathname}${location.search}`}</p>;
}

function Harness() {
  return (
    <>
      <CommandPalette />
      <Routes>
        <Route path="*" element={<Here />} />
      </Routes>
    </>
  );
}

beforeEach(() => {
  resetPrefs();
  usePrefsStore.setState({ isCommandPaletteOpen: true });
});

function type(value: string): void {
  fireEvent.change(screen.getByRole("combobox", { name: "Search" }), { target: { value } });
}

describe("CommandPalette", () => {
  it("lists every section when it opens", () => {
    renderWithProviders(<Harness />);
    expect(screen.getByRole("option", { name: /Live Ops/u })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Retention/u })).toBeInTheDocument();
  });

  it("a UUID resolves to the order and Enter navigates there", () => {
    renderWithProviders(<Harness />);
    type(UUID);
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Enter" });
    expect(screen.getByTestId("here")).toHaveTextContent(`/orders/${UUID}`);
  });

  it("a bare integer resolves to the user", () => {
    renderWithProviders(<Harness />);
    type("987654321");
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Enter" });
    expect(screen.getByTestId("here")).toHaveTextContent("/users/987654321");
  });

  it("a 32-hex string resolves to the correlation filter", () => {
    renderWithProviders(<Harness />);
    type("0123456789abcdef0123456789abcdef");
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Enter" });
    expect(screen.getByTestId("here")).toHaveTextContent(
      "/orders?correlationId=0123456789abcdef0123456789abcdef",
    );
  });

  it("closes on navigation", () => {
    renderWithProviders(<Harness />);
    type(UUID);
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Enter" });
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(false);
  });

  it("moves a virtual cursor with the arrows while the input keeps focus", () => {
    renderWithProviders(<Harness />);
    const input = screen.getByRole("combobox", { name: "Search" });
    const first = screen.getAllByRole("option")[0];
    expect(first).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("wraps at the ends rather than getting stuck", () => {
    renderWithProviders(<Harness />);
    const input = screen.getByRole("combobox", { name: "Search" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    const options = screen.getAllByRole("option");
    expect(options[options.length - 1]).toHaveAttribute("aria-selected", "true");
  });

  it("does not navigate on the unavailable row", () => {
    renderWithProviders(<Harness />);
    type("Oʻktam");
    const [only] = screen.getAllByRole("option");
    expect(only).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Enter" });
    expect(screen.getByTestId("here")).toHaveTextContent("/");
    expect(usePrefsStore.getState().isCommandPaletteOpen).toBe(true);
  });

  it("starts blank when reopened, so the last incident's id is not still in the box", () => {
    renderWithProviders(<Harness />);
    type(UUID);
    act(() => {
      usePrefsStore.getState().setCommandPaletteOpen(false);
    });
    act(() => {
      usePrefsStore.getState().setCommandPaletteOpen(true);
    });
    expect(screen.getByRole("combobox", { name: "Search" })).toHaveValue("");
  });
});
