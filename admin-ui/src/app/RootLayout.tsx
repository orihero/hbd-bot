/**
 * The authenticated shell's route element.
 *
 * It is now what its placeholder said it would become: `<AppShell><Outlet /></AppShell>`, and
 * nothing in `routes.tsx` changed to make that happen.
 *
 * It stays a separate file from `components/layout/AppShell.tsx` on purpose. The router needs
 * a route element; `AppShell` is a component that takes children and knows nothing about
 * routing, which is what lets it be rendered in a test — or later, around a login screen —
 * without a router underneath it.
 *
 * `<PlayerBar>` sits inside `AppShell`, OUTSIDE the `<Outlet />`, so the single `<audio>`
 * element survives every route change (§11.1). Do not move it in here.
 *
 * `<PasswordRotationGate>` wraps `AppShell` rather than the `<Outlet />` inside it, and the
 * difference is not stylistic. While `must_change_password` is set, §14 Slice 1a makes every
 * route but `POST /auth/password` and `GET /auth/me` answer 403. A shell rendered around the
 * rotation form would still mount `LivePill` and its `/ops/pulse` poll — one refused request
 * every five seconds, each writing a `permission.denied` audit row, against an operator whose
 * only available action is on screen already. Outside the shell, the form is the whole tree,
 * which is what the gate's own docstring means by "replaces the whole authenticated tree".
 * (It also keeps `AuthPanel`'s `<main>` from nesting inside `AppShell`'s.)
 */

import { Outlet } from "react-router-dom";

import { AppShell } from "@/components/layout";
import { PasswordRotationGate } from "@/features/auth/PasswordRotationGate";

export function RootLayout() {
  return (
    <PasswordRotationGate>
      <AppShell>
        <Outlet />
      </AppShell>
    </PasswordRotationGate>
  );
}

export const Component = RootLayout;
