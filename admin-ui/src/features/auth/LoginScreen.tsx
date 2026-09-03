/**
 * `/login` — the one unauthenticated screen.
 *
 * Three server behaviours decide what this screen may say, and each one is a decision the UI
 * can only get wrong by being more helpful than the server.
 *
 * **1. No user enumeration.** §12.1 T1: an unknown username is verified against a
 * module-level dummy hash so timing and response match, and the 401 body is identical for
 * "no such account" and "wrong password". The screen renders the server's message and adds
 * `INDISTINGUISHABLE_NOTE` — an explanation of the sameness, never a way around it. There is
 * deliberately no "did you mean" affordance, no username-exists check, and no different
 * wording for a username that "looks wrong".
 *
 * **2. 429 is explicit and countable.** `LOGIN_RATE_LIMITED` carries `Retry-After`, already
 * parsed onto `ApiFailure.retryAfterS`. Submission is blocked while the countdown runs, so
 * the panel does not spend the operator's remaining budget for them. Two counters sit behind
 * that code — strict on `(username, client_ip)`, looser per username — and the screen does
 * not say which tripped: the second is a DoS aimed at a known username, and confirming it
 * worked is confirming it worked.
 *
 * **3. `mustChangePassword` is a gate.** §14 Slice 1a: while it is set, every route but
 * `POST /auth/password` and `GET /auth/me` is a 403 — logout included. A successful login
 * carrying it therefore goes straight to the rotation form on this same screen instead of
 * navigating into the console, which would be a wall of 403s and an audit row for each one.
 * Reloading the page lands here again and `useSession` re-derives the same state from
 * `/auth/me`, so the gate survives a refresh.
 *
 * The cookies are set by the server (`__Host-` prefixed, `Secure`, same-site). There is no
 * token in JavaScript here, nothing is written to `localStorage`, and the only thing this
 * screen keeps is what is in the two inputs.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactElement } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import {
  MAX_PASSWORD_CHARS,
  MAX_USERNAME_CHARS,
  failureOf,
  postLogin,
  unwrapAsync,
  type LoginRequest,
} from "@/api";
import { Button, Skeleton, useNow, useSession } from "@/components/util";
import { queryKeys } from "@/lib";
import { href } from "@/routes";

import { AuthFailureNotice, AuthPanel } from "./AuthPanel";
import {
  INDISTINGUISHABLE_NOTE,
  RATE_LIMITED_NOTE,
  retryDeadline,
  retrySecondsLeft,
} from "./authCopy";
import { ChangePasswordScreen } from "./ChangePasswordScreen";
import { FormField } from "./FormField";

/** Where a `<Navigate state>` from a session-ended redirect stashes the route to come back to. */
interface LoginLocationState {
  readonly from?: string;
}

export function LoginScreen(): ReactElement {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [retryUntil, setRetryUntil] = useState<number | null>(null);

  const now = useNow(1_000, retryUntil !== null);
  const secondsLeft = retrySecondsLeft(retryUntil, now);

  const state = location.state as LoginLocationState | null;
  const target = state?.from ?? href.live();

  const login = useMutation({
    mutationFn: (body: LoginRequest) => unwrapAsync(postLogin(body)),
    onSuccess: async (response) => {
      // `/auth/me` is the authority on the flag from here on — the login response carries it
      // once, and a reload has to reach the same conclusion without it.
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.me() });
      if (response.mustChangePassword) {
        // Stay. The rotation form is rendered below off the session, so there is no window
        // in which a route that would 403 is mounted.
        return;
      }
      navigate(target, { replace: true });
    },
    onError: (error: unknown) => {
      const failure = failureOf(error);
      setRetryUntil(failure === null ? null : retryDeadline(failure.retryAfterS, Date.now()));
    },
  });

  // A session that must rotate its password: the only screen it may see is the rotation
  // form, whether it arrived by signing in just now or by reloading this page.
  if (session.mustChangePassword) {
    return <ChangePasswordScreen isForced />;
  }

  // Already signed in and free to move: never show a sign-in form to a signed-in operator.
  if (session.me !== null) {
    return <Navigate to={target} replace />;
  }

  if (session.isPending) {
    // A brief skeleton rather than the form: flashing a login box at an operator who has a
    // valid cookie and is about to be redirected reads as "you were signed out".
    return (
      <AuthPanel title="Sign in">
        <Skeleton className="h-40 w-full" />
      </AuthPanel>
    );
  }

  const failure = failureOf(login.error);
  const isWaiting = secondsLeft !== null && secondsLeft > 0;
  const canSubmit =
    username.length > 0 && password.length > 0 && !login.isPending && !isWaiting;

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!canSubmit) return;
    login.mutate({ username, password });
  };

  return (
    <AuthPanel title="Sign in" subtitle="This console reads customer data. Every read is audited.">
      <form onSubmit={onSubmit} data-testid="login-form" className="flex flex-col gap-3" noValidate>
        <FormField
          id="username"
          label="Username"
          type="text"
          autoComplete="username"
          value={username}
          onChange={setUsername}
          maxLength={MAX_USERNAME_CHARS}
          autoFocus
        />
        <FormField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={setPassword}
          maxLength={MAX_PASSWORD_CHARS}
        />

        {failure === null ? null : (
          <AuthFailureNotice
            failure={failure}
            secondsLeft={secondsLeft}
            note={
              failure.code === "LOGIN_RATE_LIMITED" ? RATE_LIMITED_NOTE : INDISTINGUISHABLE_NOTE
            }
          />
        )}

        {/* The design's primary button, from the one definition: solid brand, white label
            at 4.95:1, pill, and a shadow that deepens on hover. */}
        <Button type="submit" variant="primary" shape="pill" className="mt-1 py-2.5" disabled={!canSubmit}>
          {login.isPending ? "Signing in…" : isWaiting ? `Wait ${String(secondsLeft)}s` : "Sign in"}
        </Button>
      </form>
    </AuthPanel>
  );
}

export const Component = LoginScreen;
