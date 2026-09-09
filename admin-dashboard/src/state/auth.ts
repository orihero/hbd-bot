/**
 * Session state. One `me()` at startup and nothing on a timer: the session's own TTL is the
 * server's business, and a poll would keep an idle tab's session alive forever, which is the
 * opposite of what an idle timeout is for. The session therefore ends in exactly two ways:
 * `signOut()`, or the server expiring it — which this app learns about on the next `me()`,
 * i.e. the next page load. There is no 401-driven teardown yet because there is nothing on
 * the dashboard that calls the API; the screen that adds one adds that too.
 */

import { create } from "zustand";

import {
  changePassword as changePasswordApi,
  login,
  logout,
  me,
  type MeResponse,
} from "@/api/auth";

/**
 * "Remember me" is a LOCAL preference. The login body has no remember/duration field —
 * session lifetime is `adminSessionTtlS`/`adminSessionIdleTtlS` on the server — so the
 * checkbox only decides whether this browser prefills the username next time.
 */
const REMEMBERED_USERNAME_KEY = "hbd.dashboard.rememberedUsername";

/**
 * The pinned wording for a forced rotation, copied from admin-ui's
 * `features/auth/authCopy.ts` (`FORCED_ROTATION_NOTE`).
 */
export const FORCED_ROTATION_NOTE =
  "This account was created with a temporary password. Until it is changed, every other route — including signing out — answers 403, so choose a new password to continue.";

export const FORCED_ROTATION_TITLE = "Create a new password";

/** The username to prefill the sign-in form with, or `""`. Never a password. */
export function readRememberedUsername(): string {
  try {
    return localStorage.getItem(REMEMBERED_USERNAME_KEY) ?? "";
  } catch {
    // Storage can be denied outright (private mode, blocked site data). Not remembering is
    // a fine outcome; failing to render the form is not.
    return "";
  }
}

function writeRememberedUsername(username: string, remember: boolean): void {
  try {
    if (remember) localStorage.setItem(REMEMBERED_USERNAME_KEY, username);
    else localStorage.removeItem(REMEMBERED_USERNAME_KEY);
  } catch {
    /* see readRememberedUsername */
  }
}

/** `"unknown"` only before `bootstrap()` has answered — it is what gates the route guards. */
export type AuthStatus = "unknown" | "anonymous" | "authed";

export interface AuthState {
  readonly status: AuthStatus;
  readonly account: MeResponse | null;
  /**
   * The server's rotation gate. True means credentials were verified but the temporary
   * password must be changed before accessing the console. `RequireAuth` intercepts this
   * to render the rotation form.
   */
  readonly mustChangePassword: boolean;
  /** The last failure message, already redacted and capped by the server. */
  readonly error: string | null;
  clearError: () => void;
  /** Resolves `true` when the session is live and `account` is populated. */
  signIn: (username: string, password: string, remember: boolean) => Promise<boolean>;
  signOut: () => Promise<void>;
  bootstrap: () => Promise<void>;
  /** Rotates the credential and updates local session state upon success. */
  changePassword: (currentPassword: string, newPassword: string) => Promise<boolean>;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "unknown",
  account: null,
  mustChangePassword: false,
  error: null,

  clearError() {
    set({ error: null });
  },

  async signIn(username, password, remember) {
    set({ error: null });

    const result = await login({ username, password });
    if (!result.ok) {
      set({ status: "anonymous", account: null, mustChangePassword: false, error: result.message });
      return false;
    }

    writeRememberedUsername(username, remember);

    // Login answers `{mustChangePassword}`, and the full account payload comes from me().
    // me() is allowed by the server even while mustChangePassword is true.
    const account = await me();
    if (!account.ok) {
      set({
        status: "anonymous",
        account: null,
        mustChangePassword: false,
        error: account.message,
      });
      return false;
    }

    const mustChange = result.data.mustChangePassword || account.data.mustChangePassword;
    set({
      status: "authed",
      account: account.data,
      mustChangePassword: mustChange,
      error: null,
    });
    return true;
  },

  async signOut() {
    // The local state drops whatever the server says: a logout that failed to reach the API
    // must still clear this tab, or the panel keeps rendering a session nobody has.
    await logout();
    set({ status: "anonymous", account: null, mustChangePassword: false, error: null });
  },

  async bootstrap() {
    const result = await me();
    if (!result.ok) {
      // A 401 here is the ordinary answer for a cold visitor, not something to report.
      set({ status: "anonymous", account: null, mustChangePassword: false, error: null });
      return;
    }

    set({
      status: "authed",
      account: result.data,
      mustChangePassword: result.data.mustChangePassword,
      error: null,
    });
  },

  async changePassword(currentPassword, newPassword) {
    set({ error: null });

    const result = await changePasswordApi({ currentPassword, newPassword });
    if (!result.ok) {
      set({ error: result.message });
      return false;
    }

    // On success the server rotated every session and issued a fresh one with must_change_password=False.
    const account = await me();
    if (!account.ok) {
      set({ error: account.message });
      return false;
    }

    set({
      status: "authed",
      account: account.data,
      mustChangePassword: false,
      error: null,
    });
    return true;
  },
}));
