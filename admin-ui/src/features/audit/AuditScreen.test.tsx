/**
 * `/audit` — the dominant signal, and the two ways it can silently become the wrong number.
 *
 * The counting queries are keyed on a window computed at mount, so the clock is frozen here:
 * a test that seeded `Date.now()` a millisecond late would miss the cache and assert against
 * a skeleton.
 */

import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUDIT_ACTION_VALUES,
  DESTRUCTIVE_AUDIT_ACTIONS,
  type AuditEntryView,
  type AuditPage,
  type ChainVerifyResponse,
} from "@/api";
import {
  makeTestQueryClient,
  meFixture,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { AuditScreen } from "./AuditScreen";
import { COUNTING_LIMIT, DESTRUCTIVE_WINDOW_MS, EXPOSURE_WINDOW_MS } from "./auditQuery";

const NOW = new Date("2026-09-02T12:00:00.000Z").getTime();

function entry(overrides: Partial<AuditEntryView> = {}): AuditEntryView {
  return {
    seq: 1,
    id: "11111111-2222-3333-4444-555555555555",
    at: "2026-09-02T11:00:00Z",
    actorId: "11111111-2222-3333-4444-555555555555",
    actorUsername: "operator",
    actorRole: "owner",
    action: "login.success",
    subjectType: "admin_user",
    subjectId: null,
    fieldNames: null,
    recordCount: null,
    reasonCode: "routine_ops",
    reasonRef: null,
    hasReasonText: false,
    reasonText: null,
    outcome: "ok",
    errorCode: null,
    correlationId: null,
    ip: null,
    configVersion: null,
    chainHmac: "abc",
    ...overrides,
  };
}

const page = (items: readonly AuditEntryView[], nextCursor: string | null = null): AuditPage => ({
  items: [...items],
  meta: { nextCursor },
});

const verifyFixture = (overrides: Partial<ChainVerifyResponse> = {}): ChainVerifyResponse => ({
  ok: true,
  firstBreakSeq: null,
  chainProtection: "revoke+hmac",
  checkedRows: 10,
  lastSeq: 10,
  isComplete: true,
  truncationPoints: [],
  ...overrides,
});

interface Seed {
  readonly list?: AuditPage;
  readonly destructive?: AuditPage;
  readonly window?: AuditPage;
  readonly reveals?: AuditPage;
  readonly verify?: ChainVerifyResponse;
}

function renderScreen(seed: Seed = {}) {
  const client = makeTestQueryClient();
  const since24h = new Date(NOW - DESTRUCTIVE_WINDOW_MS).toISOString();
  const since7d = new Date(NOW - EXPOSURE_WINDOW_MS).toISOString();

  client.setQueryData(queryKeys.audit.list({ limit: 50 }), seed.list ?? page([entry()]));
  client.setQueryData(
    queryKeys.audit.list({
      from: since24h,
      action: DESTRUCTIVE_AUDIT_ACTIONS,
      limit: COUNTING_LIMIT,
    }),
    seed.destructive ?? page([]),
  );
  client.setQueryData(
    queryKeys.audit.list({ from: since24h, limit: COUNTING_LIMIT }),
    seed.window ?? page([]),
  );
  client.setQueryData(
    queryKeys.audit.list({ from: since7d, action: ["reveal.personal"], limit: COUNTING_LIMIT }),
    seed.reveals ?? page([]),
  );
  client.setQueryData(queryKeys.audit.verify(), seed.verify ?? verifyFixture());

  return renderWithProviders(<AuditScreen />, { client, route: "/audit" });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  resetPrefs();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AuditScreen", () => {
  it("counts destructive actions apart from everything else", () => {
    renderScreen({
      destructive: page([
        entry({ seq: 2, action: "reveal.personal" }),
        entry({ seq: 3, action: "user.block" }),
      ]),
      // Five rows in the window: two destructive, three routine. The two figures are
      // deliberately different, so a regression that renders one of them twice fails here.
      window: page([
        entry({ seq: 1, action: "login.success" }),
        entry({ seq: 2, action: "reveal.personal" }),
        entry({ seq: 3, action: "user.block" }),
        entry({ seq: 4, action: "logout" }),
        entry({ seq: 5, action: "permission.denied" }),
      ]),
    });

    const signal = screen.getByTestId("audit-signal");
    expect(within(signal).getByText("destructive actions · 24h")).toBeInTheDocument();
    expect(within(signal).getByText("2")).toBeInTheDocument();
    expect(within(signal).getByText("everything else · 24h")).toBeInTheDocument();
    expect(within(signal).getByText("3")).toBeInTheDocument();
  });

  it("marks a truncated count as a lower bound rather than an answer", () => {
    renderScreen({
      destructive: page([entry({ seq: 2, action: "reveal.personal" })], "next-page-cursor"),
    });
    expect(within(screen.getByTestId("audit-signal")).getByText("1+")).toBeInTheDocument();
  });

  it("charts reveal exposure by records, not by rows", () => {
    renderScreen({
      reveals: page([
        entry({ seq: 9, actorUsername: "bulk", action: "reveal.personal", recordCount: 500 }),
        entry({ seq: 10, actorUsername: "careful", action: "reveal.personal", recordCount: 1 }),
      ]),
    });
    const chart = screen.getByTestId("reveal-exposure");
    expect(within(chart).getByText(/records exposed, not rows/)).toBeInTheDocument();
    expect(within(chart).getAllByText("500").length).toBeGreaterThan(0);
  });

  it("states the audio range-request caveat wherever asset.stream rows are counted", () => {
    renderScreen({
      reveals: page([
        entry({ seq: 9, actorUsername: "bulk", action: "reveal.personal", recordCount: 2 }),
      ]),
    });
    expect(screen.getByText(/one row is one play and not one request/)).toBeInTheDocument();
  });

  it("carries the chain verification, hmac-only included", () => {
    renderScreen({ verify: verifyFixture({ chainProtection: "hmac-only" }) });
    expect(screen.getByTestId("chain-verify")).toHaveAttribute("data-protection", "hmac-only");
  });

  it("flags a destructive row in the table and never says 'no reason given'", () => {
    renderScreen({
      list: page([
        entry({
          seq: 7,
          action: "reveal.personal",
          recordCount: 50,
          hasReasonText: true,
          reasonText: null,
        }),
      ]),
    });
    const table = screen.getByRole("table", { name: "audit entries" });
    expect(within(table).getByText("destructive")).toBeInTheDocument();
    expect(within(table).getByText(/you may not read it/)).toBeInTheDocument();
    expect(within(table).queryByText(/no reason given/i)).not.toBeInTheDocument();
    // `recordCount` is the exposure unit and belongs in the row.
    expect(within(table).getByText("50")).toBeInTheDocument();
  });

  it("hides the log from a role that may not read it, and asks for nothing", () => {
    // §12.2: `audit.read` is OPERATOR and OWNER. A refused read would write a
    // `permission.denied` row into the very log being refused, five times over.
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    renderWithProviders(<AuditScreen />, {
      client: makeTestQueryClient(),
      me: meFixture("support"),
      route: "/audit",
    });

    expect(screen.getByTestId("audit-forbidden")).toBeInTheDocument();
    expect(screen.queryByTestId("audit-signal")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows a dash, not a zero, when a row recorded no record count", () => {
    renderScreen({ list: page([entry({ seq: 8, action: "login.success", recordCount: null })]) });
    const table = screen.getByRole("table", { name: "audit entries" });
    const records = table.querySelector('td[data-column="records"]');
    expect(records?.textContent).toBe("—");
    expect(within(table).queryByText("0")).not.toBeInTheDocument();
  });
  /*
   * The `action` list box. It stays a real `<select multiple>` — 33 actions is far too many
   * for the pill toggles `outcome` uses, and its URL-backed OR semantics are untouched — but
   * its HEIGHT is now deliberate. Chromium sizes a list box as `size × row-height + padding`
   * and then lets `padding-top` push the rows down, so `py-1.5` on a `size={3}` control drew
   * three rows and the top 6px of a fourth: a half row bleeding off the bottom edge of a
   * borderless control, measured at 63px tall against a 573px scroll height. The control
   * therefore carries no padding of its own and the breathing room sits on the option rows,
   * which is the only property Chromium honours there.
   */
  describe("the action filter", () => {
    it("is still a real multi-select over the closed vocabulary", () => {
      renderScreen();
      const select = screen.getByLabelText("action");
      expect(select.tagName).toBe("SELECT");
      expect(select).toHaveAttribute("multiple");
      expect(select.querySelectorAll("option")).toHaveLength(AUDIT_ACTION_VALUES.length);
    });

    it("shows a whole number of rows: the height comes from the rows, not from padding", () => {
      renderScreen();
      const select = screen.getByLabelText("action");
      // Rows, not pixels: `size` is the row count and the option padding is the row height,
      // so the client box is an exact multiple of a row at any zoom.
      expect(select).toHaveAttribute("size", "5");
      expect(select.className).toMatch(/(?:^|\s)p-0(?:\s|$)/u);
      expect(select.className).not.toMatch(/(?:^|\s)py-/u);
      expect(select.className).toMatch(/\[&>option\]:py-1/u);
    });

    it("still drives the URL-backed filter state, which the reskin does not touch", () => {
      renderScreen();
      const select = screen.getByLabelText("action");
      fireEvent.change(select, { target: { value: "user.block" } });
      // The chip is the filter state made visible — it exists only because the parameter is
      // set, so it is the honest proof that choosing an option still filters.
      expect(screen.getByRole("button", { name: /remove filter action/iu })).toBeInTheDocument();
    });
  });

  /*
   * The filter bar's two toggle groups, and the defect they carried.
   *
   * Both hand-rolled their own class lists, and both painted the UNPRESSED state
   * `bg-surface-control text-ink-muted` — measured in Chromium at `rgb(240,240,243)` under
   * `rgb(99,99,99)` in light and `rgb(44,44,49)` under `rgb(178,178,186)` in dark. That is
   * grey on grey: it clears 5.28:1, so no contrast gate could ever see it, and the design
   * language names it in as many words as the thing not to do. They were the last two
   * grey-on-grey affordances in the console.
   *
   * They now take their two states from `segmentVariant` and from nowhere else, so the
   * pairing cannot drift again at one call site. What is asserted here is the REQUIREMENT —
   * unpressed carries no filled grey ground, pressed carries the brand tint under the brand
   * — rather than the exact class string, so a rename inside `buttonVariants` is free and a
   * re-grey is not.
   */
  describe("the filter bar's toggles are never grey-on-grey", () => {
    /** Every segment in the bar: the destructive flag plus one pill per outcome. */
    function segments(): HTMLElement[] {
      return [
        screen.getByTestId("audit-destructive-only"),
        ...screen
          .getAllByRole("button", { pressed: false })
          .filter((element) => ["ok", "denied", "error"].includes(element.textContent ?? "")),
      ];
    }

    it("gives an unpressed segment no filled ground and no muted-on-control pairing", () => {
      renderScreen();
      const unpressed = segments();
      expect(unpressed.length).toBeGreaterThanOrEqual(4);
      for (const element of unpressed) {
        expect(element).toHaveAttribute("aria-pressed", "false");
        // `quiet`: transparent until hover. The grey chip is gone, not recoloured.
        // Unprefixed: `disabled:bg-transparent` is in every variant's base, so a loose
        // /bg-transparent/ would match `secondary` as well and assert nothing.
        expect(element.className).toMatch(/(?:^|\s)bg-transparent(?:\s|$)/u);
        expect(element.className).not.toMatch(/(?:^|\s)bg-surface-control(?:\s|$)/u);
        expect(element.className).not.toMatch(/(?:^|\s)bg-neutral/u);
      }
    });

    it("gives a pressed segment the brand tint under the brand, so the two states differ by more than a shade", () => {
      renderScreen();
      const flag = screen.getByTestId("audit-destructive-only");
      fireEvent.click(flag);
      const pressed = screen.getByTestId("audit-destructive-only");
      expect(pressed).toHaveAttribute("aria-pressed", "true");
      expect(pressed.className).toMatch(/bg-brand-tint/u);
      expect(pressed.className).toMatch(/text-brand/u);
      // The asymmetry is the point: colour PRESENT versus colour ABSENT, not two shades of
      // the same chip. If the unpressed state ever gained the brand tint this fails.
      expect(pressed.className).not.toMatch(/(?:^|\s)bg-transparent(?:\s|$)/u);
    });

    it("keeps the flag glyph and the outcome vocabulary the toggles are named by", () => {
      renderScreen();
      expect(screen.getByTestId("audit-destructive-only").textContent).toContain("⚑");
      expect(screen.getByTestId("audit-destructive-only").textContent).toContain(
        "destructive only",
      );
      for (const outcome of ["ok", "denied", "error"]) {
        expect(screen.getByRole("button", { name: outcome })).toBeInTheDocument();
      }
    });
  });
});
