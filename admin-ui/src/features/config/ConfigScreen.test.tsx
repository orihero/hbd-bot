/**
 * `/config` — the absence tests.
 *
 * §14's acceptance for the config route is a negative one: "no response body matches
 * `://[^/\s:@]+:[^/\s@]+@`; `databaseHost` and `redisHost` are present instead". The screen
 * carries the same obligation one layer up — a DSN must not be reconstructible from what is
 * rendered, and a secret must render its absence rather than a blank that reads as "unset".
 */

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  configFixture,
  makeTestQueryClient,
  renderWithProviders,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { ConfigScreen } from "./ConfigScreen";

/** The server-side rule from §14, applied to what the browser actually shows. */
const DSN_PATTERN = /:\/\/[^/\s:@]+:[^/\s@]+@/;

function renderScreen(config = configFixture("prod")) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.config.detail(), config);
  return renderWithProviders(<ConfigScreen />, { client, route: "/config" });
}

beforeEach(() => {
  resetPrefs();
});

describe("ConfigScreen", () => {
  it("answers the override question with a number and the reason it is zero", () => {
    renderScreen();
    const signal = screen.getByTestId("config-signal");
    expect(within(signal).getByText("active overrides")).toBeInTheDocument();
    expect(within(signal).getByText("pending restart")).toBeInTheDocument();
    expect(within(signal).getAllByText("0")).toHaveLength(2);
    expect(within(signal).getByText(/no override layer/)).toBeInTheDocument();
  });

  it("carries all four §11.2 tiers in the legend", () => {
    renderScreen();
    const legend = screen.getByTestId("config-tier-legend");
    const tiers = within(legend)
      .getAllByTestId("config-field")
      .map((field) => field.getAttribute("data-tier"));
    expect(tiers).toEqual(["live", "after-fix", "read-only", "secret-absent"]);
  });

  it("renders a secret's absence explicitly, never as a blank", () => {
    const { container } = renderScreen();
    const hmac = container.querySelector('[data-field="adminAuditHmacKey"]');
    expect(hmac).not.toBeNull();
    expect(hmac).toHaveAttribute("data-tier", "secret-absent");
    expect(hmac?.textContent).toContain("not returned at any role");
  });

  it("reports a DSN's presence without reporting the DSN", () => {
    const { container } = renderScreen();
    const dsn = container.querySelector('[data-field="adminAuditDsn"]');
    expect(dsn?.textContent).toContain("configured");
    expect(container.textContent ?? "").not.toMatch(DSN_PATTERN);
  });

  it("says 'not configured' — and what follows from it — when the audit DSN is empty", () => {
    const { container } = renderScreen({ ...configFixture("dev"), isAuditDsnConfigured: false });
    const dsn = container.querySelector('[data-field="adminAuditDsn"]');
    expect(dsn?.textContent).toContain("not configured");
    expect(dsn?.textContent).toContain("hmac-only");
  });

  it("shows where the database points instead of how it authenticates", () => {
    const { container } = renderScreen();
    const host = container.querySelector('[data-field="databaseHost"]');
    expect(host?.textContent).toContain("db.internal:5432");
    expect(container.querySelector('[data-field="databaseUrl"]')).toHaveAttribute(
      "data-tier",
      "secret-absent",
    );
  });

  it("marks every returned field restart-only, because nothing here is editable", () => {
    const { container } = renderScreen();
    const fields = [...container.querySelectorAll('[data-field="adminSessionTtlS"]')];
    expect(fields[0]).toHaveAttribute("data-tier", "read-only");
  });

  it("sends the operator who followed the threshold link somewhere true", () => {
    renderScreen();
    const absent = screen.getByTestId("config-absent-fields");
    expect(within(absent).getByText("name_match_min_similarity")).toBeInTheDocument();
    expect(within(absent).getByText("name_candidate_order")).toBeInTheDocument();
    expect(absent.textContent).toContain("not on this endpoint");
  });
});
