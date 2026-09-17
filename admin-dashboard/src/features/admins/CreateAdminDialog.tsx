/**
 * Add an operator — the first write this screen has ever had, and the only one on this build.
 *
 * Four properties of `POST /api/admins` shape this component, and each is a defect if dropped:
 *
 * 1. **The step-up subject is the USERNAME, not an id.** The account does not exist when the
 *    owner re-authenticates, so the grant is `admin.manage:{username}` — which means the name
 *    in the field and the name in the grant have to be the same string. The body that was sent
 *    is kept and replayed byte-identical after the grant lands; the username field is not
 *    reachable while the password prompt is up, because the confirm dialog is closed rather
 *    than layered under it. An edited name would spend the grant on somebody nobody asked for.
 * 2. **Lowercase is imposed as the operator types, not folded on the way out.** The server
 *    compares the composed scope whole, so `Dilnoza` re-authenticated and `dilnoza` created is
 *    a 403 that looks exactly like a wrong password. The field refuses to hold the spelling
 *    that would cause it.
 * 3. **Owner is not on the menu.** The database permits one active owner
 *    (`ix_admin_users_active_owner`) and ownership moves with the bootstrap CLI on the host,
 *    so an Owner option here would be a control that cannot work — the note under the select
 *    says where that handover happens instead. The server refuses `role: "owner"` with that
 *    same sentence; this is the half that arrives before the operator has typed a password.
 * 4. **The password is handed over, never kept.** It lives in this component's state, is
 *    cleared on close and on success, and is never echoed: the response is the account row
 *    with `mustChangePassword: true`, and what the new operator must do with the credential is
 *    said on the screen the dialog hands the result to.
 *
 * The reason trio is `ReasonFieldset`, the same one the block and grant dialogs use, because
 * this writes the same audit column under the same 90-day sweep.
 */

import { useEffect, useState, type JSX } from "react";

import { MAX_PASSWORD_CHARS, MAX_REASON_TEXT_CHARS, MIN_PASSWORD_CHARS } from "@/api/constants";
import {
  ADMIN_USERNAME_PATTERN,
  MAX_ADMIN_USERNAME_CHARS,
  MIN_ADMIN_USERNAME_CHARS,
  type AdminAccountView,
  type AdminCreateRequest,
} from "@/api/admins";
import { stepUpTargetOf } from "@/api/reveal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StepUpDialog } from "@/features/reveal";
import { FIELD_CONTROL_CLASS, SECTION_LABEL_CLASS } from "@/features/reveal/controls";
import { QueryErrorNote } from "@/features/users/detailKit";
import {
  EMPTY_REASON,
  REASON_CODE_REQUIRED_HINT,
  REASON_TEXT_HINT,
  REASON_TEXT_LABEL,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useI18n } from "@/i18n";
import { failureOf } from "@/lib/adminQuery";
import type { AdminRole } from "@/lib/rbac";

import { useCreateAdmin } from "./useAdmins";

/**
 * The roles this console can issue, in the order the matrix widens.
 *
 * `owner` is absent by construction rather than filtered out of the enum, so adding a fifth
 * role to the wire cannot silently make it creatable here.
 */
const CREATABLE_ROLES: readonly AdminRole[] = ["viewer", "support", "admin"];

/** What each creatable role may do, said where the choice is made. */
const ROLE_HINT_KEY = {
  viewer: "admins.roleHints.viewer",
  support: "admins.roleHints.support",
  admin: "admins.roleHints.admin",
} as const;

const ROLE_LABEL_KEY = {
  viewer: "admins.roles.viewer",
  support: "admins.roles.support",
  admin: "admins.roles.admin",
} as const;

/** The default: the narrowest role, so widening it is a decision somebody made on purpose. */
const DEFAULT_ROLE: AdminRole = "viewer";

interface FormState {
  readonly username: string;
  readonly password: string;
  readonly role: AdminRole;
}

const EMPTY_FORM: FormState = { username: "", password: "", role: DEFAULT_ROLE };

/** The server's own rule, restated so the form refuses before a round trip. */
function isUsernameValid(username: string): boolean {
  return (
    username.length >= MIN_ADMIN_USERNAME_CHARS &&
    username.length <= MAX_ADMIN_USERNAME_CHARS &&
    ADMIN_USERNAME_PATTERN.test(username)
  );
}

function isPasswordValid(password: string): boolean {
  return password.length >= MIN_PASSWORD_CHARS && password.length <= MAX_PASSWORD_CHARS;
}

export interface CreateAdminDialogProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  /** Handed the row the database wrote, so the screen can say what to do with the password. */
  readonly onCreated: (account: AdminAccountView) => void;
}

export function CreateAdminDialog({
  isOpen,
  onClose,
  onCreated,
}: CreateAdminDialogProps): JSX.Element {
  const { t } = useI18n();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);
  /** The body actually sent, kept so a step-up retry can resend it BYTE-IDENTICAL. */
  const [pending, setPending] = useState<AdminCreateRequest | null>(null);

  const create = useCreateAdmin();
  const { reset } = create;

  useEffect(() => {
    // A closed dialog holds no credential, no name and no previous failure. On close rather
    // than on open, so nothing survives in memory between two attempts.
    if (isOpen) return;
    reset();
    setForm(EMPTY_FORM);
    setReason(EMPTY_REASON);
    setPending(null);
  }, [isOpen, reset]);

  const failure = failureOf(create.error);
  const stepUpTarget = stepUpTargetOf(failure);
  const isUsernameOk = isUsernameValid(form.username);
  const isPasswordOk = isPasswordValid(form.password);

  function submit(body: AdminCreateRequest): void {
    setPending(body);
    create.mutate(body, {
      onSuccess: (account) => {
        onCreated(account);
        onClose();
      },
    });
  }

  function confirm(): void {
    const reasonBody = reasonBodyOf(reason);
    if (reasonBody === null || !isUsernameOk || !isPasswordOk) return;
    submit({
      ...reasonBody,
      username: form.username,
      password: form.password,
      role: form.role,
    });
  }

  return (
    <>
      <ConfirmDialog
        /* Closed while the password is being asked for: two focus fences cannot share a
           keyboard, and — the part that matters here — the username field must not be
           reachable while a grant is being taken for the name in it. */
        isOpen={isOpen && stepUpTarget === null}
        onClose={onClose}
        title={t("admins.create.title")}
        description={t("admins.create.description")}
        confirmLabel={
          isUsernameOk
            ? t("admins.create.submit", { username: form.username })
            : t("admins.create.submitFallback")
        }
        pendingLabel={t("admins.create.pending")}
        isPending={create.isPending}
        isConfirmDisabled={!isUsernameOk || !isPasswordOk || !canSubmitReason(reason)}
        onConfirm={confirm}
        reason={{
          label: REASON_TEXT_LABEL,
          value: reason.text,
          onChange: (text) => {
            setReason((current) => ({ ...current, text }));
          },
          hint: REASON_TEXT_HINT,
          maxLength: MAX_REASON_TEXT_CHARS,
          isRequired: false,
        }}
        error={
          create.error === null || stepUpTarget !== null ? undefined : (
            <QueryErrorNote error={create.error} noun={t("admins.create.noun")} />
          )
        }
      >
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className={SECTION_LABEL_CLASS}>{t("admins.create.usernameLabel")}</span>
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              data-testid="create-admin-username"
              value={form.username}
              maxLength={MAX_ADMIN_USERNAME_CHARS}
              disabled={create.isPending}
              aria-invalid={form.username.length > 0 && !isUsernameOk}
              onChange={(event) => {
                /* Lowercased here rather than on submit: the step-up scope is compared byte
                   for byte, so the spelling in this field IS the spelling that gets a grant. */
                const username = event.target.value.toLowerCase();
                setForm((current) => ({ ...current, username }));
              }}
              className={FIELD_CONTROL_CLASS}
            />
            <span className="text-[12px] leading-4 text-ink-400">
              {t("admins.create.usernameHint", {
                min: MIN_ADMIN_USERNAME_CHARS,
                max: MAX_ADMIN_USERNAME_CHARS,
              })}
            </span>
            {form.username.length > 0 && !isUsernameOk ? (
              <span role="alert" className="text-[12px] leading-4 text-required-deep">
                {t("admins.create.usernameInvalid")}
              </span>
            ) : null}
          </label>

          <label className="flex flex-col gap-1">
            <span className={SECTION_LABEL_CLASS}>{t("admins.create.passwordLabel")}</span>
            <input
              type="password"
              autoComplete="new-password"
              data-testid="create-admin-password"
              value={form.password}
              maxLength={MAX_PASSWORD_CHARS}
              disabled={create.isPending}
              aria-invalid={form.password.length > 0 && !isPasswordOk}
              onChange={(event) => {
                const password = event.target.value;
                setForm((current) => ({ ...current, password }));
              }}
              className={FIELD_CONTROL_CLASS}
            />
            <span className="text-[12px] leading-4 text-ink-400">
              {t("admins.create.passwordHint", { min: MIN_PASSWORD_CHARS })}
            </span>
          </label>

          <label className="flex flex-col gap-1">
            <span className={SECTION_LABEL_CLASS}>{t("admins.create.roleLabel")}</span>
            <select
              data-testid="create-admin-role"
              value={form.role}
              disabled={create.isPending}
              onChange={(event) => {
                const role = event.target.value as AdminRole;
                setForm((current) => ({ ...current, role }));
              }}
              className={FIELD_CONTROL_CLASS}
            >
              {CREATABLE_ROLES.map((role) => (
                <option key={role} value={role}>
                  {t(ROLE_LABEL_KEY[role as keyof typeof ROLE_LABEL_KEY])}
                </option>
              ))}
            </select>
            <span className="text-[12px] leading-4 text-ink-400">
              {t(ROLE_HINT_KEY[form.role as keyof typeof ROLE_HINT_KEY])}
            </span>
            {/* Why Owner is not in the list above, said before anybody looks for it. */}
            <span className="text-[12px] leading-4 text-ink-400">
              {t("admins.create.ownerNote")}
            </span>
          </label>

          <ReasonFieldset value={reason} onChange={setReason} isDisabled={create.isPending} />
          {reason.code === null ? (
            <p className="m-0 text-[12px] leading-4 text-ink-400">{REASON_CODE_REQUIRED_HINT}</p>
          ) : null}
        </div>
      </ConfirmDialog>

      <StepUpDialog
        isOpen={isOpen && stepUpTarget !== null}
        /* Cancelling drops back to the form with everything still typed: the owner declined to
           re-authenticate, they did not abandon the account they were creating. */
        onClose={reset}
        action={stepUpTarget?.action ?? "admin.manage"}
        /* Verbatim from the refusal — the username the handler composed its scope from, never
           a re-spelling of what is in the field. */
        subjectId={stepUpTarget?.subjectId ?? form.username}
        subjectLabel={form.username}
        note={t("admins.create.stepUpNote", { username: form.username })}
        onGranted={() => {
          // The server has no memory of what was being attempted, so the SAME body goes again.
          if (pending !== null) submit(pending);
        }}
      />
    </>
  );
}
