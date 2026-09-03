/**
 * The copy button, including the failure it must not swallow.
 *
 * `fireEvent`, not `userEvent`, on purpose: user-event installs its own `navigator.clipboard`
 * stub when it sets up, which would quietly replace the stub each of these tests depends on.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "./CopyButton";
import { renderWithProviders } from "./testRender";

function stubClipboard(writeText: (value: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("CopyButton", () => {
  it("copies the value verbatim and announces it", async () => {
    const writeText = vi.fn<(value: string) => Promise<void>>().mockResolvedValue(undefined);
    stubClipboard(writeText);

    renderWithProviders(
      <CopyButton value="0123456789abcdef0123456789abcdef" label="correlation id" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy correlation id" }));

    expect(writeText).toHaveBeenCalledWith("0123456789abcdef0123456789abcdef");
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("correlation id copied");
    });
  });

  it("says so when the clipboard refuses — a silent no-op is the worse bug", async () => {
    // Outside a secure context, or under a permissions policy, `writeText` rejects. An
    // operator who then pastes gets whatever was in the clipboard BEFORE.
    stubClipboard(vi.fn<(value: string) => Promise<void>>().mockRejectedValue(new Error("denied")));

    renderWithProviders(<CopyButton value="abc" label="order id" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy order id" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("could not copy order id");
    });
  });

  it("says so when there is no clipboard API at all", async () => {
    Reflect.deleteProperty(navigator, "clipboard");
    renderWithProviders(<CopyButton value="abc" label="order id" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy order id" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("could not copy order id");
    });
  });

  it("can show the value beside the glyph", () => {
    renderWithProviders(<CopyButton value="abc" withValue />);
    expect(screen.getByText("abc")).toBeInTheDocument();
  });
});
