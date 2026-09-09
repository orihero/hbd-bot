import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "@/app/AppShell";
import { NotFoundPage } from "@/app/NotFoundPage";
import { RedirectIfAuthed } from "@/app/RedirectIfAuthed";
import { RequireAuth } from "@/app/RequireAuth";
import { RouteErrorPage } from "@/app/RouteErrorPage";
import { PATH } from "@/app/paths";
import { AdminsScreen } from "@/features/admins/AdminsScreen";
import { AuditScreen } from "@/features/audit/AuditScreen";
import { BroadcastDetailScreen } from "@/features/broadcasts/BroadcastDetailScreen";
import { BroadcastsScreen } from "@/features/broadcasts/BroadcastsScreen";
import { BroadcastWizardScreen } from "@/features/broadcasts/wizard/BroadcastWizardScreen";
import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { AttemptDeepLink } from "@/features/generations/AttemptDeepLink";
import { GenerationsScreen } from "@/features/generations/GenerationsScreen";
import { ChatsPage } from "@/features/chats/ChatsPage";
import { UserDetailScreen } from "@/features/users/UserDetailScreen";
import { UsersScreen } from "@/features/users/UsersScreen";

/* Eight screens: lazy loading would add chunk boundaries and buy nothing at this size. */
export const router = createBrowserRouter([
  /*
   * `/login` is deliberately OUTSIDE `AppShell`. A sign-in screen has nothing to navigate to
   * and nobody to name in the rail's footer, and rendering the rail there would flash a nav
   * full of destinations at someone who cannot reach any of them.
   */
  {
    element: <RedirectIfAuthed />,
    errorElement: <RouteErrorPage />,
    children: [{ path: PATH.login, element: <LoginPage /> }],
  },
  {
    element: <RequireAuth />,
    errorElement: <RouteErrorPage />,
    /*
     * The shell is a second layout route rather than part of `RequireAuth` so the guard keeps
     * doing one thing. Every authed screen this app grows goes in here, beside the dashboard.
     */
    children: [
      { path: PATH.changePassword, element: <ChangePasswordPage isForced={false} /> },
      {
        element: <AppShell />,
        children: [
          { path: PATH.dashboard, element: <DashboardPage /> },
          { path: PATH.chats, element: <ChatsPage /> },
          { path: PATH.chatDetail, element: <ChatsPage /> },
          { path: PATH.users, element: <UsersScreen /> },
          /*
           * A sibling, not a child of `/users`: the detail screen replaces the list rather
           * than rendering inside it, so nesting would buy an `<Outlet />` nobody paints and
           * would keep the list's query — fifty rows and a count — mounted and refetching
           * behind a screen that never shows it.
           */
          { path: PATH.userDetail, element: <UserDetailScreen /> },
          { path: PATH.generations, element: <GenerationsScreen /> },
          /* The attempt is a panel on `/generations`; this path form redirects onto it. */
          { path: PATH.generationDetail, element: <AttemptDeepLink /> },
          /*
           * Campaigns. Three paths, and their ORDER is load-bearing.
           *
           * The wizard's literal `new` must be declared BEFORE `:broadcastId`, or
           * `/broadcasts/new` — the URL both the directory's "Message these users" and this
           * section's own primary action navigate to — is matched as a campaign whose id is the
           * word "new", and an operator who pressed Compose gets "no campaign has that id".
           * React Router ranks a static segment above a dynamic one whatever the order, so this
           * is belt and braces; the belt is that the table reads in the order it resolves.
           *
           * The wizard is declared below, above the detail route, for that reason.
           *
           * The detail is a SIBLING of the list, not a child: it replaces the list rather than
           * rendering inside it, so nesting would keep a fifty-row page — and its five-second
           * poll — mounted behind a screen that never shows it.
           */
          { path: PATH.broadcasts, element: <BroadcastsScreen /> },
          { path: PATH.broadcastNew, element: <BroadcastWizardScreen /> },
          { path: PATH.broadcastDetail, element: <BroadcastDetailScreen /> },
          /*
           * The two administration sections, after the operational ones so this table reads
           * in the rail's order — the rule in `navItems.ts` sits here, between the two.
           *
           * Neither has a detail sibling. An audit row is addressed by the filters that
           * found it, not by a path, and the roster has no per-account endpoint to route to.
           *
           * `/admins` carries no guard element either. It is owner-only, but the refusal
           * belongs to the server: a guard here would have to hold a second copy of §6.8's
           * rule, and a copy that drifts refuses an owner or admits a support operator the
           * API will refuse anyway. `AdminsScreen` renders the 403 as a denial instead.
           */
          { path: PATH.audit, element: <AuditScreen /> },
          { path: PATH.admins, element: <AdminsScreen /> },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage />, errorElement: <RouteErrorPage /> },
]);
