import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterBar } from "./FilterBar";
import type { FilterChipModel } from "./filterChips";

const chip = (id: string, label: string, value: string, remove = vi.fn()): FilterChipModel => ({
  id,
  label,
  value,
  remove,
});

describe("FilterBar", () => {
  it("renders the controls and the chips in one row", () => {
    render(
      <FilterBar chips={[chip("state:failed", "state", "failed")]} onClear={vi.fn()}>
        <input aria-label="search" />
      </FilterBar>,
    );
    expect(screen.getByLabelText("search")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "remove filter state failed" })).toBeInTheDocument();
  });

  it("makes the whole chip the remove target", () => {
    const remove = vi.fn();
    render(
      <FilterBar chips={[chip("state:failed", "state", "failed", remove)]} onClear={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "remove filter state failed" }));
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it("names the count of filters in the Clear affordance", () => {
    render(
      <FilterBar
        chips={[chip("a", "state", "failed"), chip("b", "paid", "yes")]}
        activeCount={2}
        onClear={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Clear all 2 filters" })).toBeInTheDocument();
  });

  it("says 'Clear filter' in the singular", () => {
    render(<FilterBar chips={[chip("a", "state", "failed")]} activeCount={1} onClear={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Clear filter" })).toBeInTheDocument();
  });

  it("hides Clear entirely when nothing is filtered", () => {
    render(<FilterBar chips={[]} activeCount={0} onClear={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Clear/ })).toBeNull();
  });

  it("uses activeCount, not the chip count — paging is not filtering", () => {
    // A screen may filter on something it does not render a chip for; the count still
    // comes from SearchParamsState.activeCount, which excludes limit/cursor/withTotal.
    render(<FilterBar chips={[chip("a", "state", "failed")]} activeCount={3} onClear={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Clear all 3 filters" })).toBeInTheDocument();
  });

  it("exposes the active count on the region for a screen's empty-filtered copy", () => {
    render(<FilterBar chips={[]} activeCount={2} onClear={vi.fn()} label="order filters" />);
    expect(screen.getByRole("region", { name: "order filters" })).toHaveAttribute(
      "data-active-count",
      "2",
    );
  });

  it("calls onClear", () => {
    const onClear = vi.fn();
    render(<FilterBar chips={[chip("a", "state", "failed")]} onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: /Clear/ }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
