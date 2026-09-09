/**
 * The ledger's three load-bearing renderings: the absent account, the settled debit, and the
 * operator who granted it.
 *
 * Each of these has an obvious wrong version that would look fine on screen — an empty grid
 * for a customer whose row was erased, a `consume` painted as a grant of nothing, an actor
 * masked to `admin:•••` — and each is the answer somebody is opening this table to get.
 */

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CreditLedgerEntryView, CreditLedgerPage } from "@/api";
import { renderWithProviders, resetPrefs } from "@/components/util/testRender";

import { CreditLedgerTable } from "./CreditLedgerTable";
import { NEVER_METERED_TITLE } from "./credits";

const ORDER = "3f2a9c10-8b44-4d21-9f0e-6a7c5b3e1d02";

beforeEach(() => {
  resetPrefs();
});

function entry(overrides: Partial<CreditLedgerEntryView> = {}): CreditLedgerEntryView {
  return {
    id: "9b8d7c6e-5a4f-4312-8e7d-1c2b3a495867",
    kind: "grant",
    reason: "admin_grant",
    delta: 3,
    orderId: null,
    generation: 0,
    idempotencyKey: "grant:admin:770000123:7a1b2c3d-4e5f-4061-8273-9a0b1c2d3e4f",
    actor: "admin:dilnoza",
    createdAt: "2026-09-01T10:00:00Z",
    ...overrides,
  };
}

function page(overrides: Partial<CreditLedgerPage> = {}): CreditLedgerPage {
  return {
    account: {
      telegramUserId: 770000123,
      telegramUserIdMasked: "•••••123",
      balance: 2,
      lifetimeGranted: 9,
      allowancePeriod: 41,
    },
    items: [entry()],
    meta: { nextCursor: null, total: null, isTotalExact: null },
    ...overrides,
  };
}

function renderTable(value: CreditLedgerPage | undefined) {
  return renderWithProviders(
    <CreditLedgerTable
      page={value}
      cursor={null}
      onCursorChange={vi.fn()}
      limit={25}
      isFetching={false}
    />,
  );
}

describe("CreditLedgerTable", () => {
  it("renders a null account as 'never metered' rather than as an empty table", () => {
    renderTable(page({ account: null, items: [] }));

    expect(screen.getByText(NEVER_METERED_TITLE)).toBeInTheDocument();
    expect(screen.getByTestId("credit-balance-chip")).toHaveAttribute(
      "data-state",
      "never-metered",
    );
  });

  it("still shows the movements when the account row was erased under them", () => {
    // `/forget` deletes `credit_accounts` and keeps `credit_ledger`, nulling its Telegram id.
    // The rows are the whole remaining record; hiding them behind an empty state loses it.
    renderTable(page({ account: null, items: [entry({ actor: "admin:dilnoza" })] }));

    expect(screen.queryByText(NEVER_METERED_TITLE)).not.toBeInTheDocument();
    expect(screen.getByTestId("credit-ledger-orphan-note")).toBeInTheDocument();
    expect(screen.getByText("admin:dilnoza")).toBeInTheDocument();
  });

  it("shows an account with a balance of 0 as metered-and-spent, not as never metered", () => {
    renderTable(
      page({
        account: {
          telegramUserId: 770000123,
          telegramUserIdMasked: "•••••123",
          balance: 0,
          lifetimeGranted: 4,
          allowancePeriod: 41,
        },
      }),
    );

    expect(screen.getByTestId("credit-balance-chip")).toHaveAttribute("data-state", "spent");
    expect(screen.queryByText(NEVER_METERED_TITLE)).not.toBeInTheDocument();
  });

  it("signs the delta in the text as well as in the colour, and gives consume its own mark", () => {
    renderTable(
      page({
        items: [
          entry({ id: "11111111-1111-4111-8111-111111111111", kind: "grant", delta: 3 }),
          entry({
            id: "22222222-2222-4222-8222-222222222222",
            kind: "debit",
            reason: "order_render",
            delta: -1,
            orderId: ORDER,
            generation: 1,
            actor: null,
          }),
          entry({
            id: "33333333-3333-4333-8333-333333333333",
            kind: "consume",
            reason: "order_delivered",
            delta: 0,
            orderId: ORDER,
            generation: 1,
            actor: null,
          }),
        ],
      }),
    );

    const deltas = screen.getAllByTestId("credit-delta");
    expect(deltas.map((cell) => cell.textContent)).toEqual(["+3", "−1", "±0"]);
    // The sign is an attribute too, so a row's direction survives greyscale AND a test.
    expect(deltas.map((cell) => cell.getAttribute("data-sign"))).toEqual([
      "positive",
      "negative",
      "zero",
    ]);
    // A settled debit is neither an increase nor a decrease: it must not be dropped.
    expect(screen.getByText("consume")).toBeInTheDocument();
  });

  it("publishes the actor verbatim, `admin:` prefix included, and names the pipeline's own", () => {
    renderTable(
      page({
        items: [
          entry({ id: "11111111-1111-4111-8111-111111111111", actor: "admin:dilnoza" }),
          entry({
            id: "22222222-2222-4222-8222-222222222222",
            kind: "debit",
            reason: "order_render",
            delta: -1,
            actor: null,
          }),
        ],
      }),
    );

    // Masked to `admin:•••` this table would send the operator to the audit log for every
    // grant, which is the question it was opened to answer.
    expect(screen.getByText("admin:dilnoza")).toBeInTheDocument();
    expect(screen.getByText("the pipeline")).toBeInTheDocument();
  });

  it("claims nothing while the page is still loading", () => {
    renderTable(undefined);

    expect(screen.queryByText(NEVER_METERED_TITLE)).not.toBeInTheDocument();
  });

  it("pages with the shared CursorPager", () => {
    const onCursorChange = vi.fn();
    renderWithProviders(
      <CreditLedgerTable
        page={page({ meta: { nextCursor: "cursor-2", total: null, isTotalExact: null } })}
        cursor={null}
        onCursorChange={onCursorChange}
        limit={25}
      />,
    );

    const pager = screen.getByRole("navigation", { name: /movements pagination/ });
    within(pager).getByRole("button", { name: /next/i }).click();

    expect(onCursorChange).toHaveBeenCalledWith("cursor-2");
  });
});
