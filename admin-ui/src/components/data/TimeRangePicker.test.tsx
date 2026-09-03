import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { TIME_RANGE_PRESETS, TimeRangePicker, type TimeRange } from "./TimeRangePicker";

function Harness({ initial = {} }: { readonly initial?: TimeRange }) {
  const [value, setValue] = useState<TimeRange>(initial);
  return <TimeRangePicker value={value} onChange={setValue} />;
}

describe("TimeRangePicker", () => {
  it("offers presets as rows, before any calendar", () => {
    render(<TimeRangePicker value={{}} onChange={vi.fn()} />);
    for (const preset of TIME_RANGE_PRESETS) {
      expect(screen.getByRole("button", { name: new RegExp(preset.label) })).toBeInTheDocument();
    }
  });

  it("emits an instant carrying an offset — zInstantParam rejects a naive one", () => {
    const onChange = vi.fn();
    render(<TimeRangePicker value={{}} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Last 7 days/ }));
    const emitted = onChange.mock.calls[0]?.[0] as TimeRange | undefined;
    expect(emitted?.from).toMatch(/Z$/);
    expect(emitted?.to).toMatch(/Z$/);
  });

  it("emits BOTH bounds — half a window is dropped by the API layer and filters nothing", () => {
    const onChange = vi.fn();
    render(<TimeRangePicker value={{}} onChange={onChange} />);
    for (const preset of TIME_RANGE_PRESETS) {
      onChange.mockClear();
      fireEvent.click(screen.getByRole("button", { name: new RegExp(preset.label) }));
      const emitted = onChange.mock.calls[0]?.[0] as TimeRange | undefined;
      expect(emitted?.from, `${preset.id} sent no lower bound`).toBeDefined();
      expect(emitted?.to, `${preset.id} sent half a window`).toBeDefined();
    }
  });

  it("closes the preset window at the click, not at some later now", () => {
    const onChange = vi.fn();
    render(<TimeRangePicker value={{}} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Last 7 days/ }));
    const emitted = onChange.mock.calls[0]?.[0] as TimeRange | undefined;
    const span = Date.parse(emitted?.to ?? "") - Date.parse(emitted?.from ?? "");
    expect(Math.abs(span - 604_800_000)).toBeLessThan(5_000);
    expect(Date.now() - Date.parse(emitted?.to ?? "")).toBeLessThan(5_000);
  });

  it("says so when only one end is set, rather than looking filtered", () => {
    render(<TimeRangePicker value={{ from: "2026-08-01T00:00:00Z" }} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    expect(screen.getByTestId("half-window")).toBeInTheDocument();
  });

  it("emits a from roughly one window back", () => {
    const onChange = vi.fn();
    render(<TimeRangePicker value={{}} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Last 24 hours/ }));
    const emitted = onChange.mock.calls[0]?.[0] as TimeRange | undefined;
    const deltaMs = Date.now() - Date.parse(emitted?.from ?? "");
    expect(Math.abs(deltaMs - 86_400_000)).toBeLessThan(5_000);
  });

  it("lights the chosen preset, and with a glyph as well as a colour", () => {
    render(<Harness />);
    const button = screen.getByRole("button", { name: /Last 30 days/ });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /Last 30 days/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /Last 30 days/ })).toHaveTextContent("✓");
  });

  it("reads a pasted URL's fixed window as custom, not as a rolling preset", () => {
    render(
      <TimeRangePicker
        value={{ from: "2026-08-01T00:00:00Z", to: "2026-08-31T00:00:00Z" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Custom/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("starts on All time when both ends are absent", () => {
    render(<TimeRangePicker value={{}} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /All time/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("hides All time where the endpoint needs a window", () => {
    render(<TimeRangePicker value={{}} onChange={vi.fn()} isAllTime={false} />);
    expect(screen.queryByRole("button", { name: /All time/ })).toBeNull();
  });

  it("keeps the custom fields closed until asked for", () => {
    render(<Harness />);
    expect(screen.queryByLabelText("From")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    expect(screen.getByLabelText("From")).toBeInTheDocument();
    expect(screen.getByLabelText("To")).toBeInTheDocument();
  });

  it("says which clock the operator is typing in — §11.2's rule applies to input too", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    expect(screen.getByText(/entered in local time/)).toBeInTheDocument();
  });

  it("converts a local datetime-local value into an ISO instant with a zone", () => {
    const onChange = vi.fn();
    render(<TimeRangePicker value={{}} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-01T09:30" } });
    const emitted = onChange.mock.calls.at(-1)?.[0] as TimeRange | undefined;
    expect(emitted?.from).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });

  it("clears one end rather than emitting an empty string", () => {
    const onChange = vi.fn();
    render(<TimeRangePicker value={{ from: "2026-08-01T00:00:00Z" }} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "" } });
    const emitted = onChange.mock.calls.at(-1)?.[0] as TimeRange | undefined;
    // `?from=` is a 422; absent is the only correct spelling of "no lower bound".
    expect(emitted?.from).toBeUndefined();
  });
});
