/**
 * The gate that keeps a forced rotation from becoming a wall of 403s.
 *
 * §14 Slice 1a: while `must_change_password` is set, every route except
 * `POST /api/auth/password` and `GET /api/auth/me` answers 403 — logout included. A console
 * that renders its normal shell in that state fires one refused request per panel, writes an
 * audit row for each, and shows the operator a screen of red boxes whose remedy is nowhere on
 * it. So the rotation form replaces the whole authenticated tree until the flag clears.
 *
 * It is a component rather than a route because `/auth/password` has no route in
 * `routes.tsx` and this agent does not own that file: wrapping the shell's `<Outlet />` is
 * the one-line change that installs it —
 *
 * ```tsx
 * <AppShell>
 *   <PasswordRotationGate>
 *     <Outlet />
 *   </PasswordRotationGate>
 * </AppShell>
 * ```
 *
 * — and until it is made, `/login` still renders the same form off the same session state, so
 * an operator who reloads is never stuck.
 *
 * The session-ended redirect is here for the same reason: `UNAUTHENTICATED` is the ONLY code
 * that justifies bouncing to `/login` (`SESSION_ENDED_CODES`). A `FORBIDDEN` must not — a
 * role that lacks one permission still has a working session, and redirecting on it would log
 * an operator out of the console for opening the wrong page.
 */

import type { ReactElement, ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { SESSION_ENDED_CODES } from "@/api";
import { useSession } from "@/components/util";
import { href } from "@/routes";

import { ChangePasswordScreen } from "./ChangePasswordScreen";

export interface PasswordRotationGateProps {
  readonly children: ReactNode;
}

export function PasswordRotationGate({ children }: PasswordRotationGateProps): ReactElement {
  const session = useSession();
  const location = useLocation();

  if (session.mustChangePassword) {
    return <ChangePasswordScreen isForced />;
  }

  if (session.failure !== null && SESSION_ENDED_CODES.includes(session.failure.code)) {
    return (
      <Navigate
        to={href.login()}
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  return <>{children}</>;
}
