/**
 * `/vendors`, pinned against the one mistake this screen exists to refuse: printing a number
 * where the system has an absence.
 *
 * Four absences, four different sentences, and a test for each of them — because they are
 * indistinguishable the moment any of them becomes a `0`:
 *
 *  - no writer at all (`isInstrumented: false`) — Empty-VIRGIN, no remedy offered;
 *  - a window with nothing in it — Empty-FILTERED, and a Clear affordance, which is the
 *    remedy the first one does not have;
 *  - a deployment that records calls and prices none of them — "not priced", never `$0.00`;
 *  - a measure nobody reported for a group — `—`, never `0`.
 *
 * There is no MSW here. Every query is seeded into the TanStack cache with the SAME key
 * builder the screen uses, so a test that drifts from the screen's query shape fails by
 * rendering a skeleton rather than by asserting on a fixture the screen never asked for.
 */

import { fireEvent, screen, within } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  VendorErrorView,
  VendorUsagePerDayView,
  VendorUsageResponse,
  VendorUsageRollupView,
} from "@/api";
import {
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { NOT_INSTRUMENTED_TITLE, VendorsScreen } from "./VendorsScreen";
import { toVendorUsageQuery, type VendorFilters } from "./vendorsFilters";

const FILTERED_EMPTY_TITLE = "No vendor calls in this window";

/** A `StatTile` is an `<article>` whose label is its heading; the heading is the handle. */
function tileNamed(label: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: label });
  const tile = heading.closest("article");
  if (tile === null) throw new Error(`no tile for ${label}`);
  return tile;
}

/** How many times a phrase appears in an element's text. One absence, said once. */
function occurrences(element: HTMLElement, phrase: string): number {
  return (element.textContent ?? "").split(phrase).length - 1;
}

/** The Breakdown table, which is where a row's money and its provenance are rendered. */
function breakdownTable(): HTMLElement {
  return screen.getByRole("table", { name: "vendor usage by operation" });
}

/** Reads the URL back out of the router, which is where all filter state lives. */
function SearchProbe(): ReactElement {
  const location = useLocation();
  return <div data-testid="search-probe">{location.search}</div>;
}

function rollupRow(overrides: Partial<VendorUsageRollupView> = {}): VendorUsageRollupView {
  return {
    vendor: "openrouter",
    operation: "chat_completion",
    modelId: "google/gemma-4-31b-it:free",
    calls: 120,
    successes: 118,
    failures: 2,
    successRate: 118 / 120,
    promptTokens: 40_000,
    completionTokens: 12_000,
    totalTokens: 52_000,
    // A chat group has no characters and no audio: nobody MEASURED those units here, which
    // is a null and never a zero.
    billedCharacters: null,
    audioMs: null,
    costUsd: null,
    costSource: null,
    costedCalls: 0,
    avgLatencyMs: 940,
    maxLatencyMs: 4_200,
    ...overrides,
  };
}

function usageFixture(overrides: Partial<VendorUsageResponse> = {}): VendorUsageResponse {
  const rows = overrides.rows ?? [rollupRow()];
  return {
    window: { from: "2026-09-01T00:00:00Z", to: "2026-09-07T00:00:00Z" },
    isInstrumented: true,
    isCostPriced: false,
    hasRowsInWindow: rows.length > 0,
    totals: {
      calls: 120,
      successes: 118,
      failures: 2,
      successRate: 118 / 120,
      costUsd: null,
      costedCalls: 0,
      totalTokens: 52_000,
      billedCharacters: null,
      audioMs: null,
      avgLatencyMs: 940,
    },
    ...overrides,
    rows,
  };
}

interface SeedInput {
  readonly usage?: VendorUsageResponse | null;
  readonly byDay?: readonly VendorUsagePerDayView[] | null;
  readonly errors?: readonly VendorErrorView[] | null;
  readonly filters?: VendorFilters;
}

/** Seeds all three of the screen's reads for ONE filter, the way the server answers them. */
function seed(client: QueryClient, input: SeedInput = {}): void {
  const query = toVendorUsageQuery(input.filters ?? {});
  if (input.usage !== null) {
    client.setQueryData(queryKeys.vendors.usage(query), input.usage ?? usageFixture());
  }
  if (input.byDay !== null) {
    client.setQueryData(queryKeys.vendors.byDay(query), [...(input.byDay ?? [])]);
  }
  if (input.errors !== null) {
    client.setQueryData(queryKeys.vendors.errors(query), [...(input.errors ?? [])]);
  }
}

function renderVendors(input: SeedInput = {}, route = "/vendors") {
  const client = makeTestQueryClient();
  seed(client, input);
  return renderWithProviders(
    <>
      <VendorsScreen />
      <SearchProbe />
    </>,
    { client, route },
  );
}

beforeEach(() => {
  resetPrefs();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the four absences", () => {
  it("says vendor usage is not recorded here, and puts no currency on the screen at all", () => {
    // Arrange: no worker in this deployment writes a vendor_usage row.
    renderVendors({
      usage: usageFixture({
        isInstrumented: false,
        isCostPriced: false,
        hasRowsInWindow: false,
        rows: [],
      }),
    });

    // Act / Assert: the virgin copy, and not one dollar sign — a `$0.00` here would tell an
    // operator the vendors worked for free.
    expect(screen.getAllByText(NOT_INSTRUMENTED_TITLE).length).toBeGreaterThan(0);
    expect(screen.queryByText(FILTERED_EMPTY_TITLE)).toBeNull();
    expect(document.body.textContent ?? "").not.toContain("$");
  });

  it("distinguishes an empty WINDOW from an absent writer, and offers Clear for the one that has a remedy", () => {
    // Arrange: rows exist somewhere in the record; none of them is in this window.
    renderVendors({
      usage: usageFixture({ isInstrumented: true, hasRowsInWindow: false, rows: [] }),
    });

    // Act / Assert: the filtered copy — a different sentence, with a way out.
    expect(screen.getAllByText(FILTERED_EMPTY_TITLE).length).toBeGreaterThan(0);
    expect(screen.queryByText(NOT_INSTRUMENTED_TITLE)).toBeNull();
    expect(screen.getAllByRole("button", { name: "Clear filters" }).length).toBeGreaterThan(0);
  });

  it("renders an unpriced row as 'not priced' and never as $0.00", () => {
    // Arrange: the shipped default — calls recorded, no rate configured anywhere.
    renderVendors({
      usage: usageFixture({ isCostPriced: false, rows: [rollupRow()] }),
    });

    // Act / Assert.
    expect(screen.getAllByText("not priced").length).toBeGreaterThan(0);
    expect(document.body.textContent ?? "").not.toContain("$0.00");
  });

  it("renders a measure nobody reported as an em dash, not as zero", () => {
    // Arrange: a window in which no call reported a token count.
    renderVendors({
      usage: usageFixture({
        totals: {
          calls: 12,
          successes: 12,
          failures: 0,
          successRate: 1,
          costUsd: null,
          costedCalls: 0,
          totalTokens: null,
          billedCharacters: null,
          audioMs: null,
          avgLatencyMs: null,
        },
      }),
    });

    // Act / Assert: the tile shows the absence, and shows no digit.
    const tokens = tileNamed("tokens");
    expect(tokens).toHaveTextContent("—");
    expect(tokens).not.toHaveTextContent(/\d/);
  });
});

describe("cost provenance", () => {
  it("prints the word 'mixed' beside a group whose legs were priced differently", () => {
    // Arrange: one group with a vendor-reported leg and a derived one, collapsed server-side.
    renderVendors({
      usage: usageFixture({
        isCostPriced: true,
        rows: [rollupRow({ costUsd: 1.5, costSource: "mixed", costedCalls: 120 })],
      }),
    });

    // Act.
    const chip = screen.getByTestId("cost-source-chip");

    // Assert: the provenance is a word beside the money, not a colour instead of it — a
    // total that mixes an estimate with a vendor's own figure is not a bill.
    expect(chip).toHaveTextContent("mixed");
    expect(chip).toHaveAttribute("data-cost-source", "mixed");
    expect(screen.getAllByText("$1.50").length).toBeGreaterThan(0);
  });

  it("omits the provenance chip for an unpriced group, so the row says 'not priced' once", () => {
    // Arrange: a group with no cost and therefore no source — the common shipped row, since
    // the speech and LLM rates ship at 0.0.
    renderVendors({ usage: usageFixture({ rows: [rollupRow()] }) });

    // Act.
    const row = breakdownTable();

    // Assert: the value carries the absence and nothing repeats it. The chip used to render
    // `costSourceLabel(null)`, which is the same string, so the cell read "not priced not
    // priced".
    expect(within(row).queryByTestId("cost-source-chip")).toBeNull();
    expect(occurrences(row, "not priced")).toBe(1);
  });

  it("keeps the chip beside a group that HAS a cost, because provenance qualifies a figure", () => {
    // Arrange: a music group priced from the shipped placeholder rate.
    renderVendors({
      usage: usageFixture({
        isCostPriced: true,
        rows: [
          rollupRow({
            vendor: "elevenlabs",
            operation: "music_compose",
            modelId: "music_v2",
            costUsd: 0.45,
            costSource: "estimated",
            costedCalls: 120,
          }),
        ],
      }),
    });

    // Act / Assert: the weakest claim on the screen, printed beside the money it qualifies.
    const chip = within(breakdownTable()).getByTestId("cost-source-chip");
    expect(chip).toHaveTextContent("estimated");
    expect(chip).toHaveAttribute("data-cost-source", "estimated");
  });

  it("says 'not priced' once in the hero tile too, dropping the provenance it does not have", () => {
    // Arrange: nothing in the window was priced, so `dominantCostSource` is null and
    // `costSourceLabel` would render it as a second "not priced".
    renderVendors({ usage: usageFixture({ isCostPriced: false, rows: [rollupRow()] }) });

    // Act.
    const hero = tileNamed("spend in this window");

    // Assert: the figure states the absence; the hint keeps the coverage count, which is a
    // measured count of priced calls and not a money zero.
    expect(occurrences(hero, "not priced")).toBe(1);
    expect(hero).toHaveTextContent("0 of 120 calls priced");
  });
});

describe("what the cost chart's dollars cover", () => {
  function dayPoint(overrides: Partial<VendorUsagePerDayView> = {}): VendorUsagePerDayView {
    return {
      day: "2026-09-01",
      vendor: "openrouter",
      calls: 900,
      costUsd: null,
      costedCalls: 0,
      ...overrides,
    };
  }

  it("says how many of the window's calls were priced, beside a partial dollar total", () => {
    // Arrange: 900 unpriced chat calls and one day of music priced from the shipped rate —
    // the stack draws $0.45 over a window in which nine calls out of 909 carried a cost.
    renderVendors({
      usage: usageFixture({ isCostPriced: true }),
      byDay: [
        dayPoint(),
        dayPoint({
          day: "2026-09-02",
          vendor: "elevenlabs",
          calls: 9,
          costUsd: 0.45,
          costedCalls: 9,
        }),
      ],
    });

    // Act.
    const caption = screen.getByTestId("cost-coverage-caption");

    // Assert: the count the server computes per point, carried through the pivot and said
    // out loud — a total covering nine of nine hundred and nine calls cannot be misread as
    // the bill for all of them.
    expect(caption).toHaveTextContent(
      "The bars above total the 9 of this window's 909 calls that carried a cost.",
    );
  });

  it("gives the empty cost plot a denominator rather than leaving the absence uncounted", () => {
    // Arrange: calls recorded, none of them priced — the cost series is empty by design.
    renderVendors({ usage: usageFixture(), byDay: [dayPoint()] });

    // Act / Assert: the well says WHY there are no bars; the caption says how much the
    // silence covers.
    expect(screen.getByTestId("cost-coverage-caption")).toHaveTextContent(
      "None of this window's 900 calls carried a cost.",
    );
  });

  it("says nothing about coverage on the calls chart, where a priced count means nothing", () => {
    // Arrange / Act: both charts render from the same series.
    renderVendors({ usage: usageFixture(), byDay: [dayPoint()] });

    // Assert: exactly one caption on the screen, and it belongs to the cost chart.
    expect(screen.getAllByTestId("cost-coverage-caption")).toHaveLength(1);
  });
});

describe("the async states", () => {
  it("surfaces a failed read as an alert with a way to try again", async () => {
    // Arrange: nothing seeded, and the transport rejects.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("network down"))),
    );

    // Act.
    renderVendors({ usage: null, byDay: null, errors: null });

    // Assert: §11.4's error state — an alert naming the failure, and a retry.
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Try again" }).length).toBeGreaterThan(0);
  });

  it("shows a skeleton of the finished shape while the first read is in flight", () => {
    // Arrange: a request that never settles, so the screen stays pending.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => undefined)),
    );

    // Act.
    renderVendors({ usage: null, byDay: null, errors: null });

    // Assert: the table skeleton, and the sr-only status that names what is loading.
    expect(screen.getAllByTestId("skeleton-table").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Loading vendor calls/).length).toBeGreaterThan(0);
  });
});

describe("the vendor filter", () => {
  it("writes the selection into the URL, so a spend question pastes into Slack", () => {
    // Arrange.
    renderVendors();
    expect(screen.getByTestId("search-probe")).toHaveTextContent("");

    // Act: toggle one vendor on.
    fireEvent.click(screen.getByRole("button", { name: "elevenlabs" }));

    // Assert: the parameter is in the URL, spelled the way the API repeats it.
    expect(screen.getByTestId("search-probe")).toHaveTextContent("vendor=elevenlabs");
  });

  it("drops the parameter entirely when the last chip is cleared — never `?vendor=`", () => {
    // Arrange: arrive on a link that already carries the filter.
    renderVendors(
      { filters: { vendor: ["elevenlabs"] } },
      "/vendors?vendor=elevenlabs",
    );
    expect(screen.getByTestId("search-probe")).toHaveTextContent("vendor=elevenlabs");

    // Act: clear it.
    fireEvent.click(screen.getByRole("button", { name: /^Clear / }));

    // Assert: an empty `?vendor=` is a 422, so the parameter is gone rather than emptied.
    expect(screen.getByTestId("search-probe")).not.toHaveTextContent("vendor");
  });
});
