import { useId, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { MAX_PASSWORD_CHARS, MAX_USERNAME_CHARS } from "@/api/constants";
import { PATH } from "@/app/paths";
import { BrandMark, CheckIcon, EyeIcon } from "@/components/icons";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ConsolePanel } from "@/features/auth/ConsolePanel";
import { FIELD_CONTROL_CLASS, LabelledField } from "@/features/auth/LabelledField";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { readRememberedUsername, useAuthStore } from "@/state/auth";

/** Where to land after a successful sign-in, if a guard bounced the operator here. */
function readFrom(state: unknown): string {
  if (typeof state !== "object" || state === null) return PATH.dashboard;
  const from = (state as { from?: unknown }).from;
  // Only same-origin absolute paths: a `from` is route state and route state is attacker
  // reachable through history.pushState.
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//")
    ? from
    : PATH.dashboard;
}

export function LoginPage() {
  const { t } = useI18n();
  const signIn = useAuthStore((state) => state.signIn);
  const error = useAuthStore((state) => state.error);

  const navigate = useNavigate();
  const location = useLocation();

  // Lazy initialisers: the stored value only ever seeds these two, and a bare call would
  // re-read localStorage synchronously on every keystroke to throw the answer away.
  const [username, setUsername] = useState(readRememberedUsername);
  // The login body carries no remember/duration field, so the checkbox is a local preference
  // and needs no key of its own: a remembered username IS the preference, on by default for
  // whoever has one stored.
  const [remember, setRemember] = useState(() => readRememberedUsername() !== "");
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);
  const [pending, setPending] = useState(false);

  const formId = useId();
  const usernameId = `${formId}-username`;
  const passwordId = `${formId}-password`;
  const rememberId = `${formId}-remember`;
  const errorId = `${formId}-error`;
  const hintId = `${formId}-reset-hint`;

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (pending) return;

    setPending(true);
    let signedIn = false;
    try {
      signedIn = await signIn(username, password, remember);
    } finally {
      // `signIn` is documented not to reject, but a form that latches disabled with no error
      // is the worst way to find out that changed. Re-enabling is unconditional.
      setPending(false);
    }

    // RedirectIfAuthed already sends an authed visitor to "/", so this only decides the
    // destination when a guard passed a `from`. Whichever fires first, both land somewhere
    // legitimate.
    if (signedIn) navigate(readFrom(location.state), { replace: true });
  }

  return (
    /* 641/665 columns split by an 86px gutter inside a 24px page inset: the artboard's own
       proportions, expressed as fractions so they hold at any width above lg. */
    <div className="min-h-screen bg-bg lg:grid lg:grid-cols-[641fr_665fr] lg:grid-rows-[minmax(0,1fr)] lg:gap-[86px] lg:p-6">
      <main className="relative flex min-h-screen flex-col items-center justify-center px-6 py-14 sm:px-[50px] lg:min-h-0 lg:py-0">
        <div className="absolute top-4 right-4 sm:top-6 sm:right-6 lg:top-8 lg:right-8 z-20">
          <LanguageSwitcher variant="login" />
        </div>

        <div className="flex w-full max-w-[541px] flex-col items-center gap-11">
          {/* The mark is decorative; the wordmark beside it carries the name. */}
          <div className="flex items-center gap-[17.78px]">
            <BrandMark className="h-[59.27px] w-[59.27px]" />
            <span className="font-wordmark text-[27.99px] font-medium leading-[39.19px] text-wordmark">
              hbd
            </span>
          </div>

          <div className="flex flex-col items-center gap-3">
            <h1 className="text-[28px] font-bold leading-[42px] text-label">
              {t("auth.login.title")}
            </h1>
            <p className="text-center text-[16px] font-medium leading-6 tracking-[-0.176px] text-muted">
              {t("auth.loginSubtitleIssued")}
            </p>
          </div>

          <form
            onSubmit={(event) => void handleSubmit(event)}
            className="flex w-full flex-col gap-11"
          >
            <div className="flex flex-col gap-6">
              <LabelledField htmlFor={usernameId} label={t("auth.login.username")}>
                <input
                  id={usernameId}
                  name="username"
                  type="text"
                  required
                  autoFocus
                  autoComplete="username"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  maxLength={MAX_USERNAME_CHARS}
                  disabled={pending}
                  aria-invalid={error !== null}
                  {...(error === null ? {} : { "aria-describedby": errorId })}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder={t("auth.login.username")}
                  className={FIELD_CONTROL_CLASS}
                />
              </LabelledField>

              <LabelledField htmlFor={passwordId} label={t("auth.login.password")}>
                <div className="relative">
                  <input
                    id={passwordId}
                    name="password"
                    type={revealed ? "text" : "password"}
                    required
                    autoComplete="current-password"
                    maxLength={MAX_PASSWORD_CHARS}
                    disabled={pending}
                    aria-invalid={error !== null}
                    {...(error === null ? {} : { "aria-describedby": errorId })}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder={t("auth.login.password")}
                    className={cn(FIELD_CONTROL_CLASS, "pr-[42px]")}
                  />
                  <button
                    type="button"
                    onClick={() => setRevealed((current) => !current)}
                    aria-pressed={revealed}
                    aria-controls={passwordId}
                    className="absolute right-[10px] top-1/2 -translate-y-1/2 rounded text-muted transition-colors hover:text-label focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <EyeIcon slashed={revealed} className="h-6 w-6" />
                    <span className="sr-only">
                      {revealed ? t("auth.login.hidePassword") : t("auth.login.showPassword")}
                    </span>
                  </button>
                </div>
              </LabelledField>

              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
                <div className="flex items-center gap-2">
                  <span className="relative inline-flex h-[26px] w-[26px] shrink-0">
                    <input
                      id={rememberId}
                      type="checkbox"
                      checked={remember}
                      onChange={(event) => setRemember(event.target.checked)}
                      className="peer h-[26px] w-[26px] cursor-pointer appearance-none rounded-[6.5px] border-[1.625px] border-checkbox-stroke bg-card outline-none transition-colors checked:border-accent checked:bg-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                    />
                    <CheckIcon className="pointer-events-none absolute inset-0 m-auto h-[15px] w-[15px] text-ink-900 opacity-0 peer-checked:opacity-100" />
                  </span>
                  <label
                    htmlFor={rememberId}
                    className="cursor-pointer select-none text-[16px] font-medium leading-6 tracking-[-0.176px] text-muted"
                  >
                    {t("auth.login.rememberMe")}
                  </label>
                </div>

                {/* The kit paints this link --accent (#75FC96), which is ~1.4:1 on --bg and
                    unreadable. --accent-deep carries the accent role wherever accent is text. */}
                <button
                  type="button"
                  onClick={() => {
                    setHintOpen((current) => !current);
                  }}
                  aria-expanded={hintOpen}
                  aria-controls={hintId}
                  className="rounded text-[16px] font-medium leading-6 tracking-[-0.176px] text-accent-deep underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  {t("auth.login.forgotPassword")}
                </button>
              </div>

              {/* The kit puts a link here; there is no reset route to link to, so the button
                  above reveals the one true instruction instead of dead-ending. */}
              <p
                id={hintId}
                hidden={!hintOpen}
                className="-mt-3 text-[14px] font-medium leading-5 tracking-[-0.084px] text-muted"
              >
                {t("auth.login.resetHint")}
              </p>

              {error === null ? null : (
                <p
                  id={errorId}
                  role="alert"
                  className="rounded-field border border-required-24 bg-required-06 px-3 py-2.5 text-[14px] font-medium leading-5 tracking-[-0.084px] text-required"
                >
                  {error}
                </p>
              )}
            </div>

            {/* The artboard's block is 154px because it stacks submit + Google + a sign-up row
                at gap 18. Two of those three are gone here (no OAuth, no self-service accounts),
                so the block is content-sized: holding the 154 would leave a ~65px hole between
                the button and the line, which reads as a missing element rather than as rhythm. */}
            <div className="flex flex-col gap-[18px]">
              <button
                type="submit"
                disabled={pending}
                aria-busy={pending}
                className="h-[47px] w-full rounded-field bg-accent text-[16px] font-medium leading-6 tracking-[-0.176px] text-on-accent shadow-[0_0_20px_rgba(0,0,0,0.02)] transition hover:brightness-105 active:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-deep focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-60"
              >
                {pending ? t("auth.login.signingIn") : t("auth.login.signIn")}
              </button>

              <p className="text-center text-[16px] font-medium leading-6 tracking-[-0.176px] text-muted">
                {t("auth.login.ownerProvisionedNote")}
              </p>
            </div>
          </form>
        </div>
      </main>

      <ConsolePanel />
    </div>
  );
}
