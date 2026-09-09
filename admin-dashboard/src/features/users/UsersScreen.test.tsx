import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UsersFilters, UsersPage } from "@/api/users";
import { SEGMENT_FIELDS_FIXTURE } from "@/components/SegmentBuilder/fixtures";
import { UsersScreen } from "@/features/users/UsersScreen";
import { encodeSegment, type Segment } from "@/lib/segmentCodec";
import { useAuthStore } from "@/state/auth";

/**
 * The directory, with the audience builder on it.
 *
 * Three things have to hold for the builder to be the SAME filter the wizard uses rather than
 * a second one that looks like it, and each gets a test here:
 *
 * 1. **The URL is the state.** A `?segment=` token decodes into the builder, and an edit
 *    encodes back into the URL — byte for byte, so a link an operator pastes into a ticket
 *    reopens the audience they were looking at and the request the server sees is the one the
 *    address bar shows.
 * 2. **The chips say what the token hides.** A segment lives in the URL as one opaque string;
 *    without a chip per LEAF RULE the whole audience is invisible and "Filters · 1" stands
 *    over a nine-clause document.
 * 3. **The hand-off carries the document, not a description of it.** "Message these users"
 *    passes the same token to the wizard, so nobody retypes an audience — and it refuses while
 *    a quick filter is on, because those six parameters are not part of a segment.
 *
 * The registry is the REAL `GET /api/segments/fields` (`SEGMENT_FIELDS_FIXTURE`), so a field
 * that stopped being sortable, or an operator the server withdrew, fails here rather than in a
 * 422 an operator has to read.
 */

const { listUsers, getSegmentFields, previewSegment } = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getSegmentFields: vi.fn(),
  previewSegment: vi.fn(),
}));

/*
 * Only the FETCHERS are replaced. `importOriginal` keeps every schema, enum and helper the
 * screen reads out of these modules — `segmentFieldIndex` among them — so the test is driven
 * by the real contract and only the network is standing still.
 */
vi.mock("@/api/users", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, listUsers };
});

vi.mock("@/api/segments", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getSegmentFields, previewSegment };
});

const EMPTY_PAGE: UsersPage = {
  items: [],
  meta: { nextCursor: null, total: 0, isTotalExact: true },
};

/** "Songs delivered is at least 3" — one leaf rule, and the audience the four-name list opens on. */
const DELIVERED_AT_LEAST_3: Segment = {
  v: 1,
  match: "all",
  rules: [{ field: "delivered_order_count", op: "gte", value: 3 }],
};

/** Where the wizard would be. It never renders one; it reports the URL it was handed. */
function WizardProbe(): JSX.Element {
  const location = useLocation();
  return <p data-testid="wizard-url">{`${location.pathname}${location.search}`}</p>;
}

/*
 * `MemoryRouter`, deliberately NOT `createMemoryRouter`. A data router builds a `Request` for
 * every navigation, and jsdom's `AbortSignal` is not the one undici's `Request` will accept —
 * so under this environment `setSearchParams` rejects and the URL silently never moves, which
 * is exactly the behaviour these tests exist to check.
 */
function renderScreen(url: string): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/users" element={<UsersScreen />} />
          <Route path="/broadcasts/new" element={<WizardProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The filters of the most recent `GET /api/users`, once one has been made. */
async function lastRequest(): Promise<UsersFilters> {
  await waitFor(() => {
    expect(listUsers).toHaveBeenCalled();
  });
  const calls = listUsers.mock.calls;
  return calls[calls.length - 1]?.[0] as UsersFilters;
}

beforeEach(() => {
  listUsers.mockResolvedValue({ ok: true, data: EMPTY_PAGE });
  getSegmentFields.mockResolvedValue({ ok: true, data: SEGMENT_FIELDS_FIXTURE });
  previewSegment.mockResolvedValue({
    ok: true,
    data: {
      matched: 42,
      reachable: 40,
      skippedBlocked: 1,
      skippedBotBlocked: 2,
      byLanguage: [],
    },
  });
  useAuthStore.setState({
    account: {
      id: "00000000-0000-4000-8000-000000000001",
      username: "operator",
      role: "admin",
      lastLoginAt: null,
      mustChangePassword: false,
    },
  });
});

afterEach(() => {
  useAuthStore.setState({ account: null });
  vi.clearAllMocks();
});

describe("UsersScreen — a segment in the URL", () => {
  it("decodes the token, sends it back verbatim, and draws one chip per leaf rule", async () => {
    const token = encodeSegment(DELIVERED_AT_LEAST_3);
    renderScreen(`/users?segment=${encodeURIComponent(token)}`);

    // Verbatim: the bytes in the address bar are the bytes on the wire, which is what makes
    // this list and `/segments/preview` provably one population and one cache key.
    const filters = await lastRequest();
    expect(filters.segment).toBe(token);

    // The chip states the FIELD and the OPERATOR-folded VALUE in words — the token itself is
    // unreadable, and an invisible filter is one an operator reads a wrong conclusion through.
    expect(
      await screen.findByRole("button", {
        name: "Remove filter Songs delivered: is at least 3",
      }),
    ).toBeInTheDocument();

    // Counted as a LEAF RULE, never as the one `?segment=` key.
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters · 1");
  });

  it("counts every leaf rule, at every depth, in the Filters badge", async () => {
    const nested: Segment = {
      v: 1,
      match: "all",
      rules: [
        { field: "delivered_order_count", op: "gte", value: 3 },
        {
          match: "any",
          rules: [
            { field: "plan_status", op: "in", value: ["lapsed"] },
            { field: "is_blocked", op: "is_false" },
          ],
        },
      ],
    };
    renderScreen(`/users?segment=${encodeURIComponent(encodeSegment(nested))}`);

    await lastRequest();
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters · 3");

    // A nested chip carries its own group's connective, or it reads as one more thing EVERY
    // account must match — which inverts the audience.
    expect(
      await screen.findByRole("button", {
        name: "Remove filter Any · Plan status: is any of Plan expired, not bought again",
      }),
    ).toBeInTheDocument();
  });

  it("degrades a token it cannot read to the unfiltered list rather than an empty screen", async () => {
    renderScreen("/users?segment=not-a-real-token");

    const filters = await lastRequest();
    expect(filters.segment).toBeNull();
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters");
  });
});

describe("UsersScreen — editing the builder writes the URL", () => {
  it("round-trips an edit back into ?segment= as the same document", async () => {
    const user = userEvent.setup();
    const token = encodeSegment(DELIVERED_AT_LEAST_3);
    renderScreen(`/users?segment=${encodeURIComponent(token)}`);
    await lastRequest();

    // Removing the only chip empties the document, and an empty document narrows nothing — so
    // the parameter goes away entirely rather than lingering as a second spelling of the
    // plain list.
    await user.click(
      await screen.findByRole("button", { name: "Remove filter Songs delivered: is at least 3" }),
    );

    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.segment).toBeNull();
    });
    expect(screen.getByRole("button", { name: /Filters/u })).toHaveTextContent("Filters");
  });

  it("puts a rule composed in the panel into the URL, and hands the wizard the same bytes", async () => {
    const user = userEvent.setup();
    renderScreen("/users");
    await lastRequest();

    await user.click(screen.getByRole("button", { name: /^Filters/u }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    const rule = screen.getByRole("group", { name: "Rule 1" });
    await user.selectOptions(within(rule).getByLabelText("Field"), "plan_status");
    await user.click(screen.getByRole("button", { name: "Plan expired, not bought again" }));

    const expected: Segment = {
      v: 1,
      match: "all",
      rules: [{ field: "plan_status", op: "in", value: ["lapsed"] }],
    };
    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.segment).toBe(encodeSegment(expected));
    });

    // The hand-off carries the DOCUMENT the operator just composed — the same bytes, so the
    // audience they approved is the audience the wizard freezes.
    await user.click(screen.getByRole("button", { name: /^Message these users/u }));
    expect(screen.getByTestId("wizard-url")).toHaveTextContent(
      `/broadcasts/new?segment=${encodeURIComponent(encodeSegment(expected))}`,
    );
  });
});

describe("UsersScreen — the hand-off to the campaign wizard", () => {
  it("carries the current segment into the wizard path", async () => {
    const user = userEvent.setup();
    const token = encodeSegment(DELIVERED_AT_LEAST_3);
    renderScreen(`/users?segment=${encodeURIComponent(token)}`);
    await lastRequest();

    await user.click(screen.getByRole("button", { name: /^Message these users/u }));

    expect(screen.getByTestId("wizard-url")).toHaveTextContent(
      `/broadcasts/new?segment=${encodeURIComponent(token)}`,
    );
  });

  it("refuses while a quick filter is on, because a chip parameter is not a segment", async () => {
    renderScreen("/users?isBlocked=true");
    await lastRequest();

    const action = screen.getByRole("button", { name: /^Message these users/u });
    expect(action).toBeDisabled();
  });

  it("is absent for a role that cannot write campaigns", async () => {
    useAuthStore.setState({
      account: {
        id: "00000000-0000-4000-8000-000000000002",
        username: "viewer",
        role: "viewer",
        lastLoginAt: null,
        mustChangePassword: false,
      },
    });
    renderScreen("/users");
    await lastRequest();

    // Hidden, not disabled: a press would be a 403 and a `permission.denied` audit row against
    // somebody who did nothing wrong.
    expect(screen.queryByRole("button", { name: /^Message these users/u })).toBeNull();
  });
});

describe("UsersScreen — sorting is the server's, and only where the server allows it", () => {
  it("sends the registry's sort key and drops the total beside an aggregate sort", async () => {
    const user = userEvent.setup();
    renderScreen("/users");

    const first = await lastRequest();
    expect(first.withTotal).toBe(true);
    expect(first.sort).toBeNull();

    await user.click(await screen.findByRole("button", { name: /^Sort by Orders/u }));

    await waitFor(() => {
      const filters = listUsers.mock.calls[listUsers.mock.calls.length - 1]?.[0] as UsersFilters;
      expect(filters.sort).toBe("order_count");
      expect(filters.sortDir).toBe("desc");
      // `withTotal` and a sort on a computed column are a 422 together, and the sort is what
      // the operator just pressed — so the count is what goes.
      expect(filters.withTotal).toBe(false);
    });

    const header = screen.getByRole("columnheader", { name: /Orders/u });
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("offers no control on a column the server refuses to sort", async () => {
    renderScreen("/users");
    await lastRequest();

    // `is_blocked` and `ui_language` are filterable and deliberately not sortable; a header
    // that offered a control and then rendered a 422 would teach an operator that the panel is
    // unreliable about a refusal that is deliberate.
    await waitFor(() => {
      expect(getSegmentFields).toHaveBeenCalled();
    });
    const standing = screen.getByRole("columnheader", { name: "Standing" });
    expect(within(standing).queryByRole("button")).toBeNull();
    expect(standing).not.toHaveAttribute("aria-sort");
  });

  it("keeps a document's own ordering when the URL names no sort", async () => {
    const sorted: Segment = {
      ...DELIVERED_AT_LEAST_3,
      sort: { key: "delivered_order_count", dir: "desc" },
    };
    renderScreen(`/users?segment=${encodeURIComponent(encodeSegment(sorted))}`);

    const filters = await lastRequest();
    // Lifted out into the two parameters that own it: `?sort=` is where the server reads an
    // ordering, and the token left in the URL is the audience alone.
    expect(filters.sort).toBe("delivered_order_count");
    expect(filters.sortDir).toBe("desc");
    expect(filters.segment).toBe(encodeSegment(DELIVERED_AT_LEAST_3));
  });

  it("lets an explicit ?sort= override the document's own, as the server does", async () => {
    const sorted: Segment = {
      ...DELIVERED_AT_LEAST_3,
      sort: { key: "delivered_order_count", dir: "desc" },
    };
    renderScreen(
      `/users?segment=${encodeURIComponent(encodeSegment(sorted))}&sort=order_count&sortDir=asc`,
    );

    const filters = await lastRequest();
    expect(filters.sort).toBe("order_count");
    expect(filters.sortDir).toBe("asc");
  });
});

describe("UsersScreen — the audience count", () => {
  it("states reachable and the two overlapping skips without ever adding them up", async () => {
    const user = userEvent.setup();
    renderScreen(`/users?segment=${encodeURIComponent(encodeSegment(DELIVERED_AT_LEAST_3))}`);
    await lastRequest();

    await user.click(screen.getByRole("button", { name: /^Filters/u }));

    expect(await screen.findByText("42 accounts match this segment")).toBeInTheDocument();
    expect(
      screen.getByText(
        "40 of them can be messaged. 1 are barred by us and 2 have blocked the bot — the two overlap, so never add them together.",
      ),
    ).toBeInTheDocument();
  });

  it("is not asked for at all on an unfiltered list nobody has opened the panel on", async () => {
    renderScreen("/users");
    await lastRequest();

    expect(previewSegment).not.toHaveBeenCalled();
  });
});
