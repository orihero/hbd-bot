/**
 * The four properties a hand-rolled overlay does not have, asserted rather than assumed.
 *
 * The peek panel this was lifted from had the geometry and none of the behaviour: no Esc, no
 * trap, no focus restore, no `aria-modal`. Those are the assertions here, because they are
 * exactly what a future "simplify" of this file would quietly delete.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { Drawer } from "./Drawer";

function Harness({ onClose }: { readonly onClose?: () => void }): ReactElement {
  const [isOpen, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
      >
        open peek
      </button>
      <Drawer
        isOpen={isOpen}
        onClose={() => {
          setOpen(false);
          onClose?.();
        }}
        title="order 3f2a…"
        description="Polling is paused while this is open."
        footer={<a href="/orders/3f2a">open full record</a>}
      >
        <button type="button">inside the drawer</button>
      </Drawer>
    </>
  );
}

describe("Drawer", () => {
  it("renders nothing until it is opened", () => {
    render(
      <Drawer isOpen={false} onClose={vi.fn()} title="order 3f2a…">
        <p>body</p>
      </Drawer>,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("drawer-backdrop")).not.toBeInTheDocument();
  });

  it("is a modal dialog named by its title, with the drawer geometry", () => {
    render(
      <Drawer isOpen onClose={vi.fn()} title="order 3f2a…">
        <p>body</p>
      </Drawer>,
    );

    const panel = screen.getByRole("dialog", { name: /order 3f2a/ });
    expect(panel).toHaveAttribute("aria-modal", "true");
    // The geometry is the point of the component: an aside pinned to the right edge.
    expect(panel.tagName).toBe("ASIDE");
    expect(panel.className).toContain("fixed inset-y-0 right-0");
    expect(screen.getByTestId("drawer-backdrop")).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Drawer isOpen onClose={onClose} title="order 3f2a…">
        <p>body</p>
      </Drawer>,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on the ✕", () => {
    const onClose = vi.fn();
    render(
      <Drawer isOpen onClose={onClose} title="order 3f2a…">
        <p>body</p>
      </Drawer>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("takes focus into the panel and gives it back to whatever opened it", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "open peek" });
    trigger.focus();

    fireEvent.click(trigger);

    const panel = await screen.findByRole("dialog");
    // Trapped: the focused element is inside the drawer, not back on the list behind it.
    await waitFor(() => {
      expect(panel.contains(document.activeElement)).toBe(true);
    });

    fireEvent.keyDown(document, { key: "Escape" });

    // The row the operator pressed Enter on is where the cursor belongs afterwards —
    // otherwise `j`/`k` resumes at the top of the table and their place is gone.
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });

  it("renders the footer slot, which is where the full-record link lives", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "open peek" }));

    expect(screen.getByRole("link", { name: "open full record" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "inside the drawer" })).toBeInTheDocument();
  });
});
