import { fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import type { PageMeta } from "@/api";

import { CursorPager } from "./CursorPager";

const meta = (nextCursor: string | null, total: number | null = null): PageMeta => ({
  nextCursor,
  total,
  isTotalExact: total === null ? null : true,
});

describe("CursorPager", () => {
  it("renders the row range, not a page number — a keyset cursor has no ordinal", () => {
    render(
      <CursorPager
        meta={meta("c1")}
        itemCount={50}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
        label="orders"
      />,
    );
    expect(screen.getByText("1–50")).toBeInTheDocument();
    expect(screen.queryByText(/page/i)).toBeNull();
  });

  it("renders a capped total as 10,000+ and never as a flat 10,000", () => {
    render(
      <CursorPager
        meta={{ nextCursor: "c1", total: 10_000, isTotalExact: false }}
        itemCount={50}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
        label="orders"
      />,
    );
    expect(screen.getByText("10,000+")).toBeInTheDocument();
  });

  it("omits the total entirely when withTotal was not requested", () => {
    render(
      <CursorPager
        meta={meta("c1", null)}
        itemCount={50}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
        label="orders"
      />,
    );
    // Absent is not zero. "of 0 orders" would be a lie about an uncounted list.
    expect(screen.queryByText(/ of /)).toBeNull();
  });

  it("disables Previous on page one and Next at the end of the list", () => {
    render(
      <CursorPager
        meta={meta(null)}
        itemCount={12}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
      />,
    );
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("walks forward on nextCursor and back through its own history", () => {
    function Harness(): ReactElement {
      const [cursor, setCursor] = useState<string | null>(null);
      const cursors: Record<string, string | null> = { none: "c1", c1: "c2", c2: null };
      return (
        <CursorPager
          meta={meta(cursors[cursor ?? "none"] ?? null)}
          itemCount={50}
          cursor={cursor}
          onCursorChange={setCursor}
          limit={50}
        />
      );
    }
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("51–100")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("101–150")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(screen.getByText("51–100")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(screen.getByText("1–50")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
  });

  it("resets to page one when the caller clears the cursor after a filter change", () => {
    const { rerender } = render(
      <CursorPager
        meta={meta("c2")}
        itemCount={50}
        cursor="c1"
        onCursorChange={vi.fn()}
        limit={50}
      />,
    );
    rerender(
      <CursorPager
        meta={meta("c1")}
        itemCount={50}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
      />,
    );
    expect(screen.getByText("1–50")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
  });

  it("offers the page size only when the caller can change it", () => {
    const onLimitChange = vi.fn();
    const { rerender } = render(
      <CursorPager
        meta={meta("c1")}
        itemCount={50}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
      />,
    );
    expect(screen.queryByRole("combobox")).toBeNull();

    rerender(
      <CursorPager
        meta={meta("c1")}
        itemCount={50}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
        onLimitChange={onLimitChange}
      />,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "100" } });
    expect(onLimitChange).toHaveBeenCalledWith(100);
  });

  it("says 'no orders' rather than 0–0 on an empty page", () => {
    render(
      <CursorPager
        meta={meta(null)}
        itemCount={0}
        cursor={null}
        onCursorChange={vi.fn()}
        limit={50}
        label="orders"
      />,
    );
    expect(screen.getByText("no orders")).toBeInTheDocument();
  });
});
