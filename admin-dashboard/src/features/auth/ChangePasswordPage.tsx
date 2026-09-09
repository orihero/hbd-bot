import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import {
  MAX_PASSWORD_CHARS,
  MIN_PASSWORD_CHARS,
} from "@/api/constants";
import { PATH } from "@/app/paths";
import { BrandMark, EyeIcon } from "@/components/icons";
import { ConsolePanel } from "@/features/auth/ConsolePanel";
import { FIELD_CONTROL_CLASS, LabelledField } from "@/features/auth/LabelledField";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/state/auth";

export interface ChangePasswordPageProps {
  /**
   * `true` when `mustChangePassword` put the operator here.
   * While forced, all other routes answer 403, so no navigation away is offered.
   */
  readonly isForced?: boolean;
}

export function ChangePasswordPage({ isForced = true }: ChangePasswordPageProps) {
  const { t } = useI18n();
  const changePassword = useAuthStore((state) => state.changePassword);
  const serverError = useAuthStore((state) => state.error);
  const clearError = useAuthStore((state) => state.clearError);
  const navigate = useNavigate();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [revealedCurrent, setRevealedCurrent] = useState(false);
  const [revealedNew, setRevealedNew] = useState(false);
  const [revealedConfirm, setRevealedConfirm] = useState(false);

  const [touchedNew, setTouchedNew] = useState(false);
  const [touchedConfirm, setTouchedConfirm] = useState(false);
  const [pending, setPending] = useState(false);

  const formId = useId();
  const currentPasswordId = `${formId}-current-password`;
  const newPasswordId = `${formId}-new-password`;
  const confirmPasswordId = `${formId}-confirm-password`;
  const errorId = `${formId}-error`;

  const isTooShort = touchedNew && newPassword.length > 0 && newPassword.length < MIN_PASSWORD_CHARS;
  const isMismatched =
    touchedConfirm && confirmPassword.length > 0 && confirmPassword !== newPassword;

  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= MIN_PASSWORD_CHARS &&
    confirmPassword === newPassword &&
    !pending;

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canSubmit) return;

    setPending(true);
    let ok = false;
    try {
      ok = await changePassword(currentPassword, newPassword);
    } finally {
      setPending(false);
    }

    if (ok) {
      navigate(PATH.dashboard, { replace: true });
    }
  }

  return (
    <div className="min-h-screen bg-bg lg:grid lg:grid-cols-[641fr_665fr] lg:grid-rows-[minmax(0,1fr)] lg:gap-[86px] lg:p-6">
      <main className="flex min-h-screen flex-col items-center justify-center px-6 py-14 sm:px-[50px] lg:min-h-0 lg:py-0">
        <div className="flex w-full max-w-[541px] flex-col items-center gap-10">
          {/* Brand Mark + Wordmark */}
          <div className="flex items-center gap-[17.78px]">
            <BrandMark className="h-[59.27px] w-[59.27px]" />
            <span className="font-wordmark text-[27.99px] font-medium leading-[39.19px] text-wordmark">
              hbd
            </span>
          </div>

          {/* Headline and description per PlanIQ node 0:24954 */}
          <div className="flex flex-col items-center gap-3 text-center">
            <h1 className="text-[28px] font-bold leading-[42px] text-label">
              {isForced
                ? t("auth.passwordChange.forcedTitle")
                : t("auth.passwordChange.title")}
            </h1>
            <p className="max-w-[480px] text-[16px] font-medium leading-6 tracking-[-0.176px] text-muted">
              {isForced
                ? t("auth.passwordChange.forcedNote")
                : t("auth.passwordChange.regularNote")}
            </p>
          </div>

          <form
            onSubmit={(event) => void handleSubmit(event)}
            className="flex w-full flex-col gap-8"
            noValidate
          >
            <div className="flex flex-col gap-6">
              {/* Current Password Field */}
              <LabelledField htmlFor={currentPasswordId} label={t("auth.passwordChange.currentPassword")}>
                <div className="relative">
                  <input
                    id={currentPasswordId}
                    name="currentPassword"
                    type={revealedCurrent ? "text" : "password"}
                    required
                    autoFocus
                    autoComplete="current-password"
                    maxLength={MAX_PASSWORD_CHARS}
                    disabled={pending}
                    value={currentPassword}
                    onChange={(event) => {
                      clearError();
                      setCurrentPassword(event.target.value);
                    }}
                    placeholder={t("auth.passwordChange.currentPlaceholder")}
                    className={cn(FIELD_CONTROL_CLASS, "pr-[42px]")}
                  />
                  <button
                    type="button"
                    onClick={() => setRevealedCurrent((cur) => !cur)}
                    aria-pressed={revealedCurrent}
                    aria-controls={currentPasswordId}
                    className="absolute right-[10px] top-1/2 -translate-y-1/2 rounded text-muted transition-colors hover:text-label focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <EyeIcon slashed={revealedCurrent} className="h-6 w-6" />
                    <span className="sr-only">
                      {revealedCurrent ? t("auth.login.hidePassword") : t("auth.login.showPassword")}
                    </span>
                  </button>
                </div>
              </LabelledField>

              {/* New Password Field */}
              <div className="flex flex-col gap-1.5">
                <LabelledField htmlFor={newPasswordId} label={t("auth.passwordChange.newPassword")}>
                  <div className="relative">
                    <input
                      id={newPasswordId}
                      name="newPassword"
                      type={revealedNew ? "text" : "password"}
                      required
                      autoComplete="new-password"
                      maxLength={MAX_PASSWORD_CHARS}
                      disabled={pending}
                      value={newPassword}
                      onBlur={() => setTouchedNew(true)}
                      onChange={(event) => {
                        clearError();
                        setNewPassword(event.target.value);
                      }}
                      placeholder={t("auth.passwordChange.newPlaceholder", { min: MIN_PASSWORD_CHARS })}
                      className={cn(
                        FIELD_CONTROL_CLASS,
                        "pr-[42px]",
                        isTooShort && "border-required focus:border-required focus:ring-required/30",
                      )}
                    />
                    <button
                      type="button"
                      onClick={() => setRevealedNew((cur) => !cur)}
                      aria-pressed={revealedNew}
                      aria-controls={newPasswordId}
                      className="absolute right-[10px] top-1/2 -translate-y-1/2 rounded text-muted transition-colors hover:text-label focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <EyeIcon slashed={revealedNew} className="h-6 w-6" />
                      <span className="sr-only">
                        {revealedNew ? t("auth.login.hidePassword") : t("auth.login.showPassword")}
                      </span>
                    </button>
                  </div>
                </LabelledField>
                {isTooShort ? (
                  <p className="text-[13px] font-medium leading-4 text-required">
                    {t("auth.passwordChange.tooShort", { min: MIN_PASSWORD_CHARS })}
                  </p>
                ) : (
                  <p className="text-[13px] font-medium leading-4 text-muted">
                    {t("auth.passwordChange.minLengthHint", { min: MIN_PASSWORD_CHARS })}
                  </p>
                )}
              </div>

              {/* Confirm New Password Field */}
              <div className="flex flex-col gap-1.5">
                <LabelledField htmlFor={confirmPasswordId} label={t("auth.passwordChange.confirmPassword")}>
                  <div className="relative">
                    <input
                      id={confirmPasswordId}
                      name="confirmPassword"
                      type={revealedConfirm ? "text" : "password"}
                      required
                      autoComplete="new-password"
                      maxLength={MAX_PASSWORD_CHARS}
                      disabled={pending}
                      value={confirmPassword}
                      onBlur={() => setTouchedConfirm(true)}
                      onChange={(event) => {
                        clearError();
                        setConfirmPassword(event.target.value);
                      }}
                      placeholder={t("auth.passwordChange.confirmPlaceholder")}
                      className={cn(
                        FIELD_CONTROL_CLASS,
                        "pr-[42px]",
                        isMismatched && "border-required focus:border-required focus:ring-required/30",
                      )}
                    />
                    <button
                      type="button"
                      onClick={() => setRevealedConfirm((cur) => !cur)}
                      aria-pressed={revealedConfirm}
                      aria-controls={confirmPasswordId}
                      className="absolute right-[10px] top-1/2 -translate-y-1/2 rounded text-muted transition-colors hover:text-label focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <EyeIcon slashed={revealedConfirm} className="h-6 w-6" />
                      <span className="sr-only">
                        {revealedConfirm ? t("auth.login.hidePassword") : t("auth.login.showPassword")}
                      </span>
                    </button>
                  </div>
                </LabelledField>
                {isMismatched && (
                  <p className="text-[13px] font-medium leading-4 text-required">
                    {t("auth.passwordChange.mismatched")}
                  </p>
                )}
              </div>

              {/* Server Failure / Alert */}
              {serverError !== null && (
                <p
                  id={errorId}
                  role="alert"
                  className="rounded-field border border-required-24 bg-required-06 px-3 py-2.5 text-[14px] font-medium leading-5 tracking-[-0.084px] text-required"
                >
                  {serverError}
                </p>
              )}
            </div>

            {/* Actions */}
            <div className="flex flex-col gap-3">
              <button
                type="submit"
                disabled={!canSubmit}
                aria-busy={pending}
                className="h-[47px] w-full rounded-field bg-accent text-[16px] font-medium leading-6 tracking-[-0.176px] text-on-accent shadow-[0_0_20px_rgba(0,0,0,0.02)] transition hover:brightness-105 active:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-deep focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-60"
              >
                {pending
                  ? t("auth.passwordChange.updating")
                  : isForced
                    ? t("auth.passwordChange.updateAndContinue")
                    : t("auth.passwordChange.submit")}
              </button>

              {!isForced && (
                <button
                  type="button"
                  onClick={() => navigate(PATH.dashboard)}
                  disabled={pending}
                  className="h-[43px] w-full rounded-field border border-stroke text-[15px] font-medium text-muted transition hover:bg-card hover:text-label"
                >
                  {t("common.cancel")}
                </button>
              )}
            </div>
          </form>
        </div>
      </main>

      <ConsolePanel />
    </div>
  );
}

export const Component = ChangePasswordPage;
