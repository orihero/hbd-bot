/**
 * The lookup box, and the three outcomes it exists to keep apart.
 *
 * A malformed reference, a well-formed one that matches nothing, and a match are three
 * different answers with three different next steps. Collapsing the first two — which is what
 * firing the request on any input would do, since the server answers a malformed one with a
 * 422 — would tell somebody their customer never paid when in fact a character was dropped in
 * transcription. That is the failure this file pins.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LookupQuery } from "@/api/billing";
import { en } from "@/i18n/locales/en";

import { LookupBox, classifyReference } from "./LookupBox";
import { FIXTURE_INTENT_ID, FIXTURE_PUBLIC_REF } from "./fixtures";

const { getIntentLookup } = vi.hoisted(() => ({ getIntentLookup: vi.fn() }));

vi.mock("@/api/billing", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getIntentLookup };
});

function renderBox(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/billing"]}>
        <Routes>
          <Route path="/billing" element={<LookupBox />} />
          <Route path="/billing/intents/:intentId" element={<p>dossier</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getIntentLookup.mockResolvedValue({ ok: true, data: { intentId: null, matchedOn: null } });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("classifyReference", () => {
  it("reads 24 lowercase hex as OUR payment reference", () => {
    // `secrets.token_hex(12)`. The alphabet is load-bearing: a `;` truncates a Payme
    // checkout-link value and an `=` terminates a key, which is why it is 0-9a-f.
    expect(classifyReference(FIXTURE_PUBLIC_REF)).toBe("ref");
  });

  it("reads an uppercase-bearing 24-hex value as PAYME's transaction id", () => {
    // Their identifier, pasted out of their cabinet, so it is matched case-insensitively.
    expect(classifyReference("66A1F0C2E4B7D3A19F5C8B20")).toBe("transactionId");
  });

  it("refuses anything that is not 24 hex characters", () => {
    expect(classifyReference("")).toBeNull();
    expect(classifyReference("a1b2c3")).toBeNull();
    expect(classifyReference("a1b2c3d4e5f60718293a4b5cZZ")).toBeNull();
    // A name is never a search term in this section. Billing is searched by the two
    // identifiers that are not people.
    expect(classifyReference("Dilnoza")).toBeNull();
  });
});

describe("LookupBox — three outcomes, not two", () => {
  it("says a malformed reference is malformed WITHOUT asking the server", async () => {
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(en.billing.lookup.label), "not-a-reference");

    expect(screen.getByTestId("lookup-malformed")).toHaveTextContent(
      en.billing.lookup.malformed,
    );
    expect(screen.getByRole("button", { name: en.billing.lookup.submit })).toBeDisabled();
    // The whole point: a 422 from the server would read exactly like "no such payment".
    expect(getIntentLookup).not.toHaveBeenCalled();
  });

  it("says no payment exists for a well-formed reference that matches nothing", async () => {
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(en.billing.lookup.label), FIXTURE_PUBLIC_REF);
    await user.click(screen.getByRole("button", { name: en.billing.lookup.submit }));

    await waitFor(() => {
      expect(screen.getByTestId("lookup-no-match")).toHaveTextContent(en.billing.lookup.noMatch);
    });
    // A 200 carrying two nulls, not an error — this is a FACT about the deployment.
    const query = getIntentLookup.mock.calls[0]?.[0] as LookupQuery;
    expect(query.ref).toBe(FIXTURE_PUBLIC_REF);
    expect(query.transactionId).toBeUndefined();
  });

  it("offers the dossier and says which index answered, on a match", async () => {
    getIntentLookup.mockResolvedValue({
      ok: true,
      data: { intentId: FIXTURE_INTENT_ID, matchedOn: "payme_transaction_id" },
    });
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(en.billing.lookup.label), "66A1F0C2E4B7D3A19F5C8B20");
    await user.click(screen.getByRole("button", { name: en.billing.lookup.submit }));

    await waitFor(() => {
      expect(screen.getByTestId("lookup-match")).toBeInTheDocument();
    });
    // An operator who pasted Payme's id needs to know we matched THEIRS and not ours.
    expect(screen.getByTestId("lookup-match")).toHaveTextContent(
      en.billing.lookup.matchedTransaction,
    );
    const query = getIntentLookup.mock.calls[0]?.[0] as LookupQuery;
    expect(query.transactionId).toBe("66A1F0C2E4B7D3A19F5C8B20");
    expect(query.ref).toBeUndefined();
  });

  it("drops the previous answer the moment a new reference is typed", async () => {
    const user = userEvent.setup();
    renderBox();

    const input = screen.getByLabelText(en.billing.lookup.label);
    await user.type(input, FIXTURE_PUBLIC_REF);
    await user.click(screen.getByRole("button", { name: en.billing.lookup.submit }));
    await waitFor(() => {
      expect(screen.getByTestId("lookup-no-match")).toBeInTheDocument();
    });

    await user.type(input, "{backspace}");
    // Leaving "no such payment" under a half-typed reference is how somebody reads a verdict
    // about a reference they are no longer asking about.
    expect(screen.queryByTestId("lookup-no-match")).not.toBeInTheDocument();
  });
});
