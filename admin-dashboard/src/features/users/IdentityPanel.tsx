/**
 * Who this is — the panel a support call is read from, and the only place on the screen where
 * a single personal field can be unmasked.
 *
 * Everything personal arrives masked and is rendered through `<MaskedValue>`, which owns the
 * four states (masked, revealed, purged, not-permitted) and hides the Reveal affordance for a
 * role that has no cell. The subject is `UserView.id` — the `users` row's UUID — and never the
 * Telegram id: the block and grant routes key on the integer, `POST /api/reveal` keys on the
 * UUID, and sending the wrong one is a scope mismatch or a reveal of somebody else.
 *
 * ## The absences are four different sentences
 *
 * This panel exists to keep them apart, because a single "—" would make them one:
 *
 *  - **no `user_profiles` row at all** (`isProfilePresent: false`) — never onboarded, OR erased
 *    by `/forget`. That table has no retention clock and `/forget` DELETEs the row, so absence
 *    IS the erasure record and there is no stamp to show beside it. The panel says which two
 *    facts it cannot tell apart rather than picking one.
 *  - **the customer never shared a phone** — `phoneSharedAt` is null and there is no mask.
 *  - **we have their phone and it is masked** — a mask, and a date they shared it. Different
 *    sentence, different affordance: this one can be revealed, with a reason and an audit row.
 *  - **the column is NULL** — a masked twin of `null`. `<MaskedValue>` gives it no reveal
 *    affordance either: spending a step-up, a budget unit and an audit row to be told "nothing"
 *    is the reveal it exists to prevent.
 *
 * No `<PurgedValue>` anywhere in here, and that is not an omission: `user_profiles` carries no
 * `*_purged_at` column, so a lock-and-date on these fields would be an invented fact.
 */

import type { JSX } from "react";

import type { UserView } from "@/api/users";
import { MaskedValue } from "@/features/reveal";

import { Fact, FactGrid, PANEL_NOTE_CLASS, Panel } from "./detailKit";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";

import { formatTimestamp } from "./detailFormat";

/** The three readings of `isProfilePresent`, and what each one can and cannot claim. */
type ProfileStanding = "on-file" | "absent-with-orders" | "absent";

const STANDING_LABEL_KEY: Readonly<Record<ProfileStanding, TranslationPath>> = {
  "on-file": "users.profileStanding.onFile",
  "absent-with-orders": "users.profileStanding.absentWithOrders",
  absent: "users.profileStanding.absent",
};

const STANDING_HINT_KEY: Readonly<Record<ProfileStanding, TranslationPath>> = {
  "on-file": "users.profileStanding.onFileHint",
  "absent-with-orders": "users.profileStanding.absentWithOrdersHint",
  absent: "users.profileStanding.absentHint",
};

function standingOf(user: UserView): ProfileStanding {
  if (user.isProfilePresent) return "on-file";
  return user.orderCount > 0 ? "absent-with-orders" : "absent";
}

export interface IdentityPanelProps {
  readonly user: UserView;
}

export function IdentityPanel({ user }: IdentityPanelProps): JSX.Element {
  const { t } = useI18n();
  const standing = standingOf(user);
  /* OUR words for the subject, for every dialog this panel can open. The label of a dialog
     that exists to reveal somebody's name must not be their name. */
  const subjectLabel = user.telegramUserIdMasked;

  return (
    <Panel title={t("users.detail.profile")} ariaLabel={t("users.profileAria")}>
      <FactGrid>
        <Fact label={t("users.detail.standing")} hint={t(STANDING_HINT_KEY[standing])}>
          {t(STANDING_LABEL_KEY[standing])}
        </Fact>

        <Fact
          label={t("users.detail.firstContact")}
          hint={t("users.identityNotes.firstContact")}
        >
          {formatTimestamp(user.accountCreatedAt)}
        </Fact>

        <Fact label={t("users.detail.uiLanguage")} hint={t("users.identityNotes.uiLanguage")}>
          {t(LANGUAGE_LABEL_KEY[user.uiLanguage])}
        </Fact>

        <Fact
          label={t("users.detail.photo")}
          hint={t("users.identityNotes.photo")}
        >
          {user.hasAvatar ? (
            <span>{`captured ${formatTimestamp(user.avatarFetchedAt, "at an unrecorded time")}`}</span>
          ) : (
            <span className="text-ink-400">none captured</span>
          )}
        </Fact>

        <Fact label={t("users.detail.firstName")}>
          <MaskedValue
            masked={user.firstNameMasked}
            field="user_profiles.first_name"
            subjectId={user.id}
            subjectLabel={subjectLabel}
          />
        </Fact>

        <Fact label={t("users.detail.lastName")}>
          <MaskedValue
            masked={user.lastNameMasked}
            field="user_profiles.last_name"
            subjectId={user.id}
            subjectLabel={subjectLabel}
          />
        </Fact>

        <Fact
          label={t("users.detail.username")}
          hint={t("users.identityNotes.username")}
        >
          <MaskedValue
            masked={user.telegramUsernameMasked}
            field="user_profiles.telegram_username"
            subjectId={user.id}
            subjectLabel={subjectLabel}
          />
        </Fact>

        <Fact
          label={t("users.detail.phone")}
          hint={t("users.identityNotes.phone")}
        >
          {user.phoneMasked === null ? (
            <span className="text-ink-400">
              {user.phoneSharedAt === null ? "never shared" : "shared, then removed"}
            </span>
          ) : (
            <MaskedValue
              masked={user.phoneMasked}
              field="user_profiles.phone_e164"
              subjectId={user.id}
              subjectLabel={subjectLabel}
            />
          )}
        </Fact>

        <Fact
          label={t("users.detail.phoneShared")}
          hint={t("users.identityNotes.phoneShared")}
        >
          {user.phoneSharedAt === null ? (
            <span className="text-ink-400">never</span>
          ) : (
            formatTimestamp(user.phoneSharedAt)
          )}
        </Fact>

        <Fact label={t("users.detail.firstOrder")}>
          {user.firstOrderAt === null ? (
            <span className="text-ink-400">no orders</span>
          ) : (
            formatTimestamp(user.firstOrderAt)
          )}
        </Fact>

        <Fact label={t("users.detail.lastOrder")}>
          {user.lastOrderAt === null ? (
            <span className="text-ink-400">no orders</span>
          ) : (
            formatTimestamp(user.lastOrderAt)
          )}
        </Fact>
      </FactGrid>

      <p className={PANEL_NOTE_CLASS}>
        Masked is the normal state of every field here. Revealing one asks for a reason, may ask
        for your password again, spends a metered budget and writes an audit row naming you, this
        customer and the column — the row records WHICH column was read, never what it said.
      </p>
    </Panel>
  );
}
