/**
 * `/assets` — the dominant signal, and the column that must not exist.
 *
 * The negative test is the important one. `sizeBytes` is on the wire and is always `0`, so a
 * size column renders `0 B` beside a four-megabyte song and an operator has no way to tell it
 * is a lie. §11.2 forbids the column; this asserts it stayed forbidden, including the
 * plausible-looking near-misses ("size", "0 B") a future tidy-up would reintroduce.
 */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { AdminRole, AssetsPage } from "@/api";
import { makeAsset } from "@/components/domain/fixtures";
import {
  configFixture,
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { AssetsScreen } from "./AssetsScreen";

const EXPIRING_KEY = { expiringWithinDays: 7, withTotal: true, limit: 1 };

function page(items: AssetsPage["items"], meta: Partial<AssetsPage["meta"]> = {}): AssetsPage {
  return {
    items,
    meta: { nextCursor: null, total: null, isTotalExact: null, ...meta },
  };
}

interface Seed {
  readonly list?: AssetsPage;
  readonly listQuery?: Record<string, unknown>;
  readonly expiring?: AssetsPage;
  readonly route?: string;
  /** The signed-in role. `reveal.personal_data` is SUPPORT and above; VIEWER holds no cell. */
  readonly role?: AdminRole;
}

function renderScreen(seed: Seed = {}) {
  const client = makeTestQueryClient();
  client.setQueryData(
    queryKeys.assets.list(seed.listQuery ?? { limit: 50 }),
    seed.list ?? page([makeAsset()]),
  );
  client.setQueryData(
    queryKeys.assets.list(EXPIRING_KEY),
    seed.expiring ?? page([], { total: 12, isTotalExact: true }),
  );
  return renderWithProviders(<AssetsScreen />, {
    client,
    route: seed.route ?? "/assets",
    me: meFixture(seed.role ?? "owner"),
    // The reveal dialog reads the two ceilings off `/api/config`, which a live session has
    // already cached from the top bar. Seeded so opening it is not a network call.
    config: configFixture(),
  });
}

beforeEach(() => {
  resetPrefs();
});

describe("AssetsScreen", () => {
  it("leads with the count of assets expiring within 7 days", () => {
    renderScreen();
    const signal = screen.getByTestId("assets-expiring-signal");
    expect(within(signal).getByText("expiring within 7 days")).toBeInTheDocument();
    expect(within(signal).getByText("12")).toBeInTheDocument();
    expect(within(signal).getByText(/already past expiry/)).toBeInTheDocument();
  });

  it("renders a capped total with the plus that says 'at least'", () => {
    renderScreen({ expiring: page([], { total: 10_000, isTotalExact: false }) });
    expect(within(screen.getByTestId("assets-expiring-signal")).getByText("10,000+")).toBeInTheDocument();
  });

  it("shows no storage size column — sizeBytes is always 0 and 0 B would be a lie", () => {
    renderScreen();
    const table = screen.getByRole("table", { name: "assets" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent ?? "");
    expect(headers).not.toContain("size");
    expect(headers.some((header) => /size|bytes/i.test(header))).toBe(false);
    expect(screen.queryByText("0 B")).not.toBeInTheDocument();
  });

  it("flags a row whose storage key was never recorded", () => {
    renderScreen({ list: page([makeAsset({ isStorageKeyRecorded: false })]) });
    expect(screen.getByText("not recorded")).toBeInTheDocument();
  });

  it("says 'recorded' when the sweep will be able to reach the object", () => {
    renderScreen({ list: page([makeAsset({ isStorageKeyRecorded: true })]) });
    expect(screen.getByText("recorded")).toBeInTheDocument();
  });

  it("offers Clear on an empty result that a filter explains", () => {
    renderScreen({
      list: page([]),
      listQuery: { kind: ["greeting"], limit: 50 },
      route: "/assets?kind=greeting",
    });
    expect(screen.getByText(/no assets match/i)).toBeInTheDocument();
  });

  it("distinguishes an empty table with no filters from a filtered one", () => {
    renderScreen({ list: page([]) });
    expect(screen.getByText("No assets stored yet")).toBeInTheDocument();
  });

  it("opens the retention card for the row the operator picked", async () => {
    const user = userEvent.setup();
    renderScreen({ list: page([makeAsset({ id: "aaaaaaaa-1111-2222-3333-444444444444" })]) });
    expect(screen.getByText(/Select a row/)).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "assets" });
    const firstRow = within(table).getAllByRole("row")[1];
    expect(firstRow).toBeDefined();
    await user.click(firstRow as HTMLElement);

    expect(screen.getByTestId("asset-card")).toBeInTheDocument();
    // §12.3's audio caveat travels with the card, not with the table.
    expect(screen.getByTestId("asset-playback-note")).toBeInTheDocument();
  });

  it("offers the lyric-sheet reveal beside the card for a lyric row", async () => {
    const user = userEvent.setup();
    renderScreen({
      list: page([makeAsset({ kind: "lyric_sheet", mime: "text/plain; charset=utf-8" })]),
    });

    const table = screen.getByRole("table", { name: "assets" });
    await user.click(within(table).getAllByRole("row")[1] as HTMLElement);

    expect(screen.getByTestId("lyric-sheet-panel")).toBeInTheDocument();
    expect(screen.getByTestId("lyric-sheet-reveal")).toBeInTheDocument();
  });

  it("draws exactly one playback control for an audio row — the card's, never a second", async () => {
    const user = userEvent.setup();
    renderScreen({ list: page([makeAsset({ kind: "song", mime: "audio/mpeg" })]) });

    const table = screen.getByRole("table", { name: "assets" });
    await user.click(within(table).getAllByRole("row")[1] as HTMLElement);

    expect(screen.getAllByTestId("asset-play")).toHaveLength(1);
    // The lyric panel renders nothing at all for a row the text route would refuse.
    expect(screen.queryByTestId("lyric-sheet-panel")).toBeNull();
  });

  /*
   * The OTHER reveal an asset leads to. The panel above reveals the asset's own bytes through
   * the media routes; this one reveals the ORDER's brief through `POST /api/reveal`, which is
   * a different endpoint, a different permission cell and a different budget charge. Keyed on
   * `orderId` rather than on the asset id, because `_replace_assets` deletes and re-inserts
   * and `assets.id` is therefore not stable across a re-render.
   */
  it("offers the order's brief from a selected asset, keyed on the ORDER id", async () => {
    const user = userEvent.setup();
    const asset = makeAsset();
    renderScreen({ list: page([asset]) });

    const table = screen.getByRole("table", { name: "assets" });
    await user.click(within(table).getAllByRole("row")[1] as HTMLElement);

    const trigger = screen.getByRole("button", { name: /Reveal the order's brief/u });
    expect(trigger).toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByTestId("reveal-dialog").textContent).toContain(asset.orderId.slice(0, 8));
  });

  it("shows a VIEWER no reveal control at all", async () => {
    const user = userEvent.setup();
    renderScreen({ list: page([makeAsset()]), role: "viewer" });

    const table = screen.getByRole("table", { name: "assets" });
    await user.click(within(table).getAllByRole("row")[1] as HTMLElement);

    expect(screen.queryByTestId("reveal-button")).toBeNull();
  });
});
