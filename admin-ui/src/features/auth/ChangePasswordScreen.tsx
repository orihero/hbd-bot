/**
 * The password rotation form — `POST /api/auth/password`.
 *
 * It exists in two modes and the difference is not cosmetic.
 *
 * **Forced** (`isForced`, from `mustChangePassword: true`): §14 Slice 1a makes every route
 * except this one and `GET /auth/me` answer 403 while the flag is set, *including logout*.
 * So the screen offers no navigation at all — there is nowhere that would work. Rendering a
 * "back to the console" link would be an invitation to collect a wall of 403s, and a "sign
 * out" button would be a control that 403s on click.
 *
 * **Voluntary**: the same form, reached by an operator who chose to rotate.
 *
 * Three server behaviours the form mirrors rather than reinvents:
 *
 *  - `currentPassword` is **required even on the forced path**. A bootstrapped account still
 *    proves it holds the temporary password before replacing it.
 *  - The new password's floor is `MIN_PASSWORD_CHARS` (8) and it is checked here before the
 *    round trip, because the server's 422 for it is a validation error and the operator can
 *    see the rule without spending an argon2 verify.
 *  - A wrong current password is a 403 carrying `"that is not your current password"`, and a
 *    `REAUTH_RATE_LIMITED` 429 is a DIFFERENT code from the login limiter because it has a
 *    remedy: sign in again for a fresh window. Both are rendered as the server sent them.
 *
 * On success the server revokes every session this credential authorised and issues a new
 * one, so the cookie in the browser is already the new session by the time this resolves.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactElement } from "react";
import { useNavigate } from "react-router-dom";

import {
  MIN_PASSWORD_CHARS,
  failureOf,
  postPasswordChange,
  unwrapAsync,
  type PasswordChangeRequest,
} from "@/api";
import { Button, useNow } from "@/components/util";
import { queryKeys } from "@/lib";
import { href } from "@/routes";

import { AuthFailureNotice, AuthPanel } from "./AuthPanel";
import {
  FORCED_ROTATION_NOTE,
  FORCED_ROTATION_TITLE,
  REAUTH_LIMITED_NOTE,
  retryDeadline,
  retrySecondsLeft,
} from "./authCopy";
import { FormField } from "./FormField";

export interface ChangePasswordScreenProps {
  /** `true` when `mustChangePassword` put the operator here. Removes every way out. */
  readonly isForced?: boolean;
}

export function ChangePasswordScreen({
  isForced = false,
}: ChangePasswordScreenProps = {}): ReactElement {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [retryUntil, setRetryUntil] = useState<number | null>(null);

  const now = useNow(1_000, retryUntil !== null);
  const secondsLeft = retrySecondsLeft(retryUntil, now);

  const change = useMutation({
    mutationFn: (body: PasswordChangeRequest) => unwrapAsync(postPasswordChange(body)),
    onSuccess: async () => {
      // The flag is on `/auth/me`; nothing else in the cache is trustworthy across a
      // credential rotation that revoked every other session either.
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.me() });
      navigate(href.live(), { replace: true });
    },
    onError: (error: unknown) => {
      const failure = failureOf(error);
      setRetryUntil(
        failure === null ? null : retryDeadline(failure.retryAfterS, Date.now()),
      );
    },
  });

  const failure = failureOf(change.error);
  const isTooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_CHARS;
  const isMismatched = confirmation.length > 0 && confirmation !== newPassword;
  const isWaiting = secondsLeft !== null && secondsLeft > 0;
  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= MIN_PASSWORD_CHARS &&
    confirmation === newPassword &&
    !change.isPending &&
    !isWaiting;

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!canSubmit) return;
    change.mutate({ currentPassword, newPassword });
  };

  return (
    <AuthPanel
      title={isForced ? FORCED_ROTATION_TITLE : "Change your password"}
      subtitle={
        isForced ? FORCED_ROTATION_NOTE : "The new password replaces every session it authorised."
      }
    >
      <form
        onSubmit={onSubmit}
        data-testid="password-rotation-form"
        data-forced={String(isForced)}
        className="flex flex-col gap-3"
        noValidate
      >
        <FormField
          id="currentPassword"
          label="Current password"
          type="password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={setCurrentPassword}
        />
        <FormField
          id="newPassword"
          label="New password"
          type="password"
          autoComplete="new-password"
          value={newPassword}
          onChange={setNewPassword}
          hint={`At least ${String(MIN_PASSWORD_CHARS)} characters.`}
          {...(isTooShort
            ? { error: `Too short — ${String(MIN_PASSWORD_CHARS)} characters minimum.` }
            : {})}
        />
        <FormField
          id="confirmPassword"
          label="New password again"
          type="password"
          autoComplete="new-password"
          value={confirmation}
          onChange={setConfirmation}
          {...(isMismatched ? { error: "The two entries do not match." } : {})}
        />

        {failure === null ? null : (
          <AuthFailureNotice
            failure={failure}
            secondsLeft={secondsLeft}
            {...(failure.code === "REAUTH_RATE_LIMITED" ? { note: REAUTH_LIMITED_NOTE } : {})}
          />
        )}

        {/* Same primary button as `/login` — the two screens are one flow, and they now
            share it by construction rather than by two matching class lists. */}
        <Button type="submit" variant="primary" shape="pill" className="mt-1 py-2.5" disabled={!canSubmit}>
          {change.isPending ? "Changing…" : "Change password"}
        </Button>
      </form>
    </AuthPanel>
  );
}

export const Component = ChangePasswordScreen;
