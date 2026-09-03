/**
 * The shell's route element, and the one thing about it that is a §14 acceptance criterion
 * rather than a layout choice: while `mustChangePassword` is set, the rotation form is the
 * WHOLE tree.
 *
 * The negative assertion is the load-bearing one. If the gate were nested inside `AppShell`,
 * the rail and the top bar would still mount, `LivePill` would still poll `/ops/pulse` every
 * five seconds, and each of those refusals would write a `permission.denied` audit row
 * against an operator whose only available action is already on screen. Asserting that the
 * nav is absent is asserting that no such poll exists.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";

import type { MeResponse } from "@/api";
import {
  ensureMatchMedia,
  makeTestQueryClient,
  meFixture,
  resetPrefs,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { RootLayout } from "./RootLayout";

function renderLayout(me: MeResponse) {
  const client = makeTestQueryClient();
  client.setQueryData(queryKeys.auth.me(), me);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/orders"]}>
        <Routes>
          <Route path="/" element={<RootLayout />}>
            <Route path="orders" element={<p>the orders screen</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  resetPrefs();
  ensureMatchMedia();
});

describe("RootLayout", () => {
  it("renders the shell around the routed screen", () => {
    renderLayout(meFixture("owner"));
    expect(screen.getByText("the orders screen")).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });

  it("replaces the entire shell — rail and all — during a forced rotation", () => {
    renderLayout({ ...meFixture("owner"), mustChangePassword: true });
    expect(screen.getByTestId("password-rotation-form")).toHaveAttribute("data-forced", "true");
    expect(screen.queryByText("the orders screen")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
