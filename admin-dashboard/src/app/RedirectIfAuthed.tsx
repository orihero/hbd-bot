import { Navigate, Outlet } from "react-router-dom";

import { PendingShell } from "@/app/PendingShell";
import { PATH } from "@/app/paths";
import { useAuthStore } from "@/state/auth";

/** The mirror of RequireAuth: a live session has no business on the sign-in screen. */
export function RedirectIfAuthed() {
  const status = useAuthStore((state) => state.status);

  if (status === "unknown") return <PendingShell />;
  if (status === "authed") return <Navigate to={PATH.dashboard} replace />;
  return <Outlet />;
}
