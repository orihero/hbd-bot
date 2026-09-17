import { Navigate, Outlet, useLocation } from "react-router-dom";

import { PendingShell } from "@/app/PendingShell";
import { PATH } from "@/app/paths";
import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";
import { useAuthStore } from "@/state/auth";

/**
 * The gate on every authenticated route.
 *
 * `"unknown"` must render the neutral shell rather than redirect: bouncing to `/login`
 * before `me()` has answered would log out every returning operator on every page load.
 *
 * While `mustChangePassword` is true, §14 Slice 1a makes every route but
 * `POST /api/auth/password` and `GET /api/auth/me` answer 403. So the rotation form replaces
 * the whole authenticated tree until the credential is rotated.
 */
export function RequireAuth() {
  const status = useAuthStore((state) => state.status);
  const mustChangePassword = useAuthStore((state) => state.mustChangePassword);
  const location = useLocation();

  if (status === "unknown") return <PendingShell />;
  if (status === "anonymous") {
    // The attempted URL rides along so the sign-in lands back on it.
    return (
      <Navigate
        to={PATH.login}
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }

  if (mustChangePassword) {
    return <ChangePasswordPage isForced />;
  }

  return <Outlet />;
}
