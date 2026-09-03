import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePrefsStore } from "@/lib";

import { DataTable, type DataColumn, type DataTableProps } from "./DataTable";

interface Row {
  readonly id: string;
  readonly name: string;
  readonly count: number;
}

const rows: readonly Row[] = [
  { id: "a", name: "Oʻktam", count: 4 },
  { id: "b", name: "Gʻulom", count: 12 },
  { id: "c", name: "Dilnoza", count: 7 },
];

const columns: readonly DataColumn<Row>[] = [
  { id: "name", header: "recipient", cell: (row) => row.name, isNumeric: false },
  { id: "count", header: "orders", cell: (row) => row.count, isNumeric: true },
];

afterEach(() => {
  usePrefsStore.setState({ density: "comfortable" });
});

function renderTable(overrides: Partial<DataTableProps<Row>> = {}) {
  return render(
    <DataTable<Row>
      data={rows}
      columns={columns}
      getRowId={(row) => row.id}
      label="orders"
      {...overrides}
    />,
  );
}

describe("DataTable", () => {
  it("renders every row and column", () => {
    renderTable();
    expect(screen.getByRole("table", { name: "orders" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(rows.length + 1);
    expect(screen.getByText("Dilnoza")).toBeInTheDocument();
  });

  it("renders user content byte-for-byte — U+02BB must survive the grid", () => {
    renderTable();
    // Not `O'ktam`, not `Oktam`: the modifier letter turned comma is the datum.
    expect(screen.getByText("Oʻktam").textContent).toBe("Oʻktam");
  });

  it("puts .num and a right edge on numeric columns only (§11.3)", () => {
    renderTable();
    const firstBody = screen.getAllByRole("row")[1];
    expect(firstBody).toBeDefined();
    const cells = within(firstBody as HTMLElement).getAllByRole("cell");
    expect(cells[0]).not.toHaveClass("num");
    expect(cells[1]).toHaveClass("num");
    expect(cells[1]).toHaveClass("text-right");
  });

  it("keeps the header sticky, and opaque so rows cannot show through it", () => {
    renderTable();
    const header = screen.getByRole("table").querySelector("thead");
    expect(header).toHaveClass("sticky");
    // The head is a label row, not a filled bar — but it still has to occlude the rows
    // sliding under it, and the card colour is the one opacity that is invisible.
    expect(header).toHaveClass("bg-surface-card");
  });

  it("is a borderless card, and separates rows by space rather than by rules", () => {
    const { container } = renderTable();
    const card = container.firstElementChild;
    expect(card).toHaveClass("rounded-card", "bg-surface-card", "shadow-card");
    // The old grid was built out of 1px rules: `border border-line` on the box and
    // `border-b border-line/60` on every row. This design has neither.
    expect(card?.className).not.toMatch(/\bborder\b/u);
    for (const row of screen.getAllByRole("row").slice(1)) {
      expect(row.className).not.toMatch(/\bborder-b\b/u);
    }
  });

  it("paints the row cursor on the cells, so the tint reads as a rounded band", () => {
    renderTable();
    fireEvent.keyDown(screen.getByRole("table"), { key: "j" });
    const cells = within(screen.getAllByRole("row")[1] as HTMLElement).getAllByRole("cell");
    expect(cells[0]).toHaveClass("bg-surface-control", "rounded-l-control");
    expect(cells[cells.length - 1]).toHaveClass("rounded-r-control");
  });

  it("moves the active row with j and k", () => {
    renderTable();
    const table = screen.getByRole("table");

    fireEvent.keyDown(table, { key: "j" });
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("data-active", "true");

    fireEvent.keyDown(table, { key: "j" });
    expect(screen.getAllByRole("row")[2]).toHaveAttribute("data-active", "true");

    fireEvent.keyDown(table, { key: "k" });
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("data-active", "true");
  });

  it("clamps at both ends rather than wrapping", () => {
    renderTable();
    const table = screen.getByRole("table");
    fireEvent.keyDown(table, { key: "k" });
    fireEvent.keyDown(table, { key: "k" });
    // `k` from nowhere lands on the last row; a second `k` steps up, never past the top.
    fireEvent.keyDown(table, { key: "Home" });
    fireEvent.keyDown(table, { key: "k" });
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("data-active", "true");

    fireEvent.keyDown(table, { key: "End" });
    fireEvent.keyDown(table, { key: "j" });
    expect(screen.getAllByRole("row")[3]).toHaveAttribute("data-active", "true");
  });

  it("activates the focused row on Enter", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    const table = screen.getByRole("table");
    fireEvent.keyDown(table, { key: "j" });
    fireEvent.keyDown(table, { key: "Enter" });
    expect(onRowActivate).toHaveBeenCalledWith(rows[0]);
  });

  it("ignores j/k typed into a filter box", () => {
    const onRowActivate = vi.fn();
    renderTable({
      onRowActivate,
      toolbar: <input aria-label="search" />,
    });
    const input = screen.getByLabelText("search");
    fireEvent.keyDown(input, { key: "j" });
    expect(screen.queryByRole("row", { selected: true })).toBeNull();
    expect(screen.getAllByRole("row")[1]).not.toHaveAttribute("data-active");
  });

  it("leaves ⌘K to the command palette", () => {
    renderTable();
    const table = screen.getByRole("table");
    fireEvent.keyDown(table, { key: "k", metaKey: true });
    expect(screen.getAllByRole("row")[1]).not.toHaveAttribute("data-active");
  });

  it("reads density from the prefs store, not from a prop", () => {
    renderTable();
    expect(screen.getByRole("table")).toHaveAttribute("data-density", "comfortable");
    fireEvent.click(screen.getByRole("button", { name: /comfortable/ }));
    expect(screen.getByRole("table")).toHaveAttribute("data-density", "compact");
    expect(usePrefsStore.getState().density).toBe("compact");
  });

  it("shows the caller's empty state rather than an empty grid", () => {
    renderTable({ data: [], emptyState: <p>no orders match this filter</p> });
    expect(screen.getByText("no orders match this filter")).toBeInTheDocument();
  });

  it("holds the previous render at reduced opacity while refetching", () => {
    const { container } = renderTable({ isRefetching: true });
    expect(container.querySelector(".opacity-70")).not.toBeNull();
    // The rows are still there — a dashboard that blanks on a poll is worse (§11.4).
    expect(screen.getByText("Dilnoza")).toBeInTheDocument();
  });
  /*
   * The overflow affordance. A borderless card in a browser with overlay scrollbars gives an
   * operator nothing to read a cut-off column by: `/orders` shipped with 31px of "updated"
   * hidden and no cue at all. jsdom has no layout, so the geometry is stubbed — what is under
   * test is the RULE ("only when there is really something past this edge"), not Chromium's
   * measurements, which the Playwright gate measures instead.
   */
  describe("the horizontal overflow cue", () => {
    function scroller(container: HTMLElement): HTMLElement {
      const element = container.querySelector<HTMLElement>(".overflow-auto");
      if (element === null) throw new Error("no scroll port");
      return element;
    }

    function stubGeometry(
      element: HTMLElement,
      geometry: { scrollWidth: number; clientWidth: number; scrollLeft: number },
    ): void {
      Object.defineProperty(element, "scrollWidth", {
        configurable: true,
        get: () => geometry.scrollWidth,
      });
      Object.defineProperty(element, "clientWidth", {
        configurable: true,
        get: () => geometry.clientWidth,
      });
      Object.defineProperty(element, "scrollLeft", {
        configurable: true,
        get: () => geometry.scrollLeft,
      });
    }

    it("shows no cue at all when the grid fits", () => {
      const { container } = renderTable();
      const port = scroller(container);
      stubGeometry(port, { scrollWidth: 800, clientWidth: 800, scrollLeft: 0 });
      fireEvent.scroll(port);
      expect(screen.queryByTestId("table-scroll-fade-start")).toBeNull();
      expect(screen.queryByTestId("table-scroll-fade-end")).toBeNull();
      expect(port.parentElement).toHaveAttribute("data-overflow-x", "false");
    });

    it("fades the trailing edge while a column is still cut off there", () => {
      const { container } = renderTable();
      const port = scroller(container);
      stubGeometry(port, { scrollWidth: 1231, clientWidth: 1200, scrollLeft: 0 });
      fireEvent.scroll(port);
      const end = screen.getByTestId("table-scroll-fade-end");
      // A fade, not a rule: this language has no hard borders left to reintroduce.
      expect(end.className).toMatch(/bg-gradient-to-l/u);
      expect(end.className).toMatch(/from-surface-card/u);
      expect(end.className).not.toMatch(/\bborder\b/u);
      // It must never eat a click meant for the grid under it.
      expect(end).toHaveClass("pointer-events-none");
      // Nothing at the leading edge: there is nothing off that side yet.
      expect(screen.queryByTestId("table-scroll-fade-start")).toBeNull();
      expect(port.parentElement).toHaveAttribute("data-overflow-x", "true");
    });

    it("drops the trailing fade once the last column is whole, and marks the other side", () => {
      const { container } = renderTable();
      const port = scroller(container);
      stubGeometry(port, { scrollWidth: 1231, clientWidth: 1200, scrollLeft: 31 });
      fireEvent.scroll(port);
      // Scrolled to the end: the last column is fully visible, so nothing is over its text.
      expect(screen.queryByTestId("table-scroll-fade-end")).toBeNull();
      expect(screen.getByTestId("table-scroll-fade-start")).toBeInTheDocument();
    });

    it("ignores a sub-pixel remainder rather than cueing half a pixel of nothing", () => {
      const { container } = renderTable();
      const port = scroller(container);
      stubGeometry(port, { scrollWidth: 1200.6, clientWidth: 1200, scrollLeft: 0 });
      fireEvent.scroll(port);
      expect(screen.queryByTestId("table-scroll-fade-end")).toBeNull();
    });
  });
});
