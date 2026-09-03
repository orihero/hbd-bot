import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChartFrame, type ChartDatum, type ChartSeriesSpec } from "./ChartFrame";

const rows: readonly ChartDatum[] = [
  { day: "2026-08-30", delivered: 41, failed: 3 },
  { day: "2026-08-31", delivered: 38, failed: 7 },
  { day: "2026-09-01", delivered: 52, failed: 1 },
];

const series: readonly ChartSeriesSpec[] = [
  { key: "delivered", label: "delivered", tone: "delivered" },
  { key: "failed", label: "failed", tone: "failed" },
];

describe("ChartFrame", () => {
  it("names the chart and its window", () => {
    render(
      <ChartFrame
        title="Orders per day"
        subtitle="last 30 days"
        kind="line"
        data={rows}
        xKey="day"
        series={series}
      />,
    );
    expect(screen.getByRole("heading", { name: "Orders per day" })).toBeInTheDocument();
    expect(screen.getByText("last 30 days")).toBeInTheDocument();
  });

  it("always renders a legend for two or more series", () => {
    render(<ChartFrame title="t" kind="line" data={rows} xKey="day" series={series} />);
    const legend = screen.getByRole("list", { name: "series legend" });
    expect(within(legend).getByText("delivered")).toBeInTheDocument();
    expect(within(legend).getByText("failed")).toBeInTheDocument();
  });

  it("renders no legend box for a single series — the title names it", () => {
    render(
      <ChartFrame
        title="Delivered"
        kind="line"
        data={rows}
        xKey="day"
        series={[series[0] as ChartSeriesSpec]}
      />,
    );
    expect(screen.queryByRole("list", { name: "series legend" })).toBeNull();
  });

  it("gives every series a dash and a marker, so hue is never the only channel", () => {
    const { container } = render(
      <ChartFrame title="t" kind="line" data={rows} xKey="day" series={series} />,
    );
    const legend = screen.getByRole("list", { name: "series legend" });
    const lines = legend.querySelectorAll("line");
    expect(lines).toHaveLength(2);
    expect(lines[0]?.getAttribute("stroke-dasharray")).toBe("0");
    expect(lines[1]?.getAttribute("stroke-dasharray")).toBe("6 3");
    // …and a marker shape beside each key.
    expect(legend.querySelectorAll("path")).toHaveLength(2);
    expect(container).toBeTruthy();
  });

  it("paints a semantic series with its status token, not a ramp slot", () => {
    render(<ChartFrame title="t" kind="line" data={rows} xKey="day" series={series} />);
    const legend = screen.getByRole("list", { name: "series legend" });
    const strokes = [...legend.querySelectorAll("line")].map((line) => line.getAttribute("stroke"));
    expect(strokes).toEqual(["var(--st-delivered)", "var(--st-failed)"]);
  });

  it("ships a table twin so no value is gated behind a hover", () => {
    render(<ChartFrame title="Orders per day" kind="bar" data={rows} xKey="day" series={series} />);
    const table = screen.getByRole("table", { name: "Orders per day as a table" });
    expect(within(table).getByText("2026-08-31")).toBeInTheDocument();
    expect(within(table).getByText("38")).toBeInTheDocument();
  });

  it("renders — rather than 0 for a series missing from a row", () => {
    render(
      <ChartFrame
        title="t"
        kind="line"
        data={[{ day: "2026-09-01", delivered: 4 }]}
        xKey="day"
        series={series}
      />,
    );
    const table = screen.getByRole("table");
    // A day the endpoint omitted is a gap, not a zero-delivery day.
    expect(within(table).getByText("—")).toBeInTheDocument();
  });

  it("shows a distinct empty message rather than an axis with nothing on it", () => {
    render(
      <ChartFrame
        title="t"
        kind="line"
        data={[]}
        xKey="day"
        series={series}
        emptyLabel="no orders in this window"
      />,
    );
    expect(screen.getByText("no orders in this window")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("holds the frame at reduced opacity while refetching", () => {
    const { container } = render(
      <ChartFrame title="t" kind="line" data={rows} xKey="day" series={series} isRefetching />,
    );
    expect(container.querySelector(".opacity-70")).not.toBeNull();
    // No skeleton, no layout jump: the table twin is still populated.
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("lets a caller suppress the table twin when the same table is already on screen", () => {
    render(
      <ChartFrame
        title="t"
        kind="line"
        data={rows}
        xKey="day"
        series={series}
        isTableView={false}
      />,
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("formats table values through the caller's formatter", () => {
    render(
      <ChartFrame
        title="t"
        kind="bar"
        data={rows}
        xKey="day"
        series={[series[0] as ChartSeriesSpec]}
        formatValue={(value) => `${String(value)} orders`}
      />,
    );
    expect(screen.getByText("41 orders")).toBeInTheDocument();
  });

  it("records the chart kind so a screen cannot silently get a different shape", () => {
    const { container } = render(
      <ChartFrame title="t" kind="stacked-bar" data={rows} xKey="day" series={series} />,
    );
    expect(container.querySelector('[data-chart-kind="stacked-bar"]')).not.toBeNull();
  });
});
