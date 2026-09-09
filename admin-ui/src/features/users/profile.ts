/**
 * What the panel may honestly say about a customer's contact profile.
 *
 * ## Why a named standing exists at all
 *
 * `/forget` DELETEs the `user_profiles` row rather than nulling its columns in place, and the
 * table carries no `*_expires_at` of any kind — it is kept while the account exists and
 * `/forget` is its whole erasure route. The consequence for this screen is exact and must not
 * be papered over: **an absent profile and an erased profile are the same absence**, and there
 * is no stamp anywhere on the wire that distinguishes them.
 *
 * So there is deliberately no `<PurgedValue>` on any profile field. `<PurgedValue>` draws a
 * lock and a date, and both would be invented here: the date does not exist and the lock would
 * claim the panel knows an erasure happened when what it actually knows is that a row is not
 * there. The opposite shortcut — leaving the cells blank — is no better, because a blank cell
 * on a console reads as a rendering bug and sends an operator to look for one. A named standing
 * is neither: it says which of the three things is true, and its hint says out loud which two
 * facts it cannot tell apart.
 *
 * ## Why this is a module and not three ternaries in a screen
 *
 * The distinction is worded twice — once in the list column and once in the detail panel — and
 * the sentence that matters is the one about not being able to tell erasure from absence. Two
 * copies of it drift, and the copy that drifts is the one that stops being true. One module,
 * one wording, two readers, plus a colocated test that pins the mapping.
 *
 * There is no `isProfilePurged` and no `profilePurgedAt` to read: nothing named that appears on
 * any wire, and nothing here should start expecting one.
 */

import { type UserView } from "@/api";

/**
 * The three things a `user_profiles` row can honestly be said to be.
 *
 *  - `absent` — no row. Either the account has never answered the language question, or
 *    `/forget` erased it. Indistinguishable, on purpose.
 *  - `language_only` — a row exists with no phone number: onboarding began and did not finish,
 *    so this person cannot order yet.
 *  - `onboarded` — language chosen and number shared.
 */
export type ProfileStanding = "absent" | "language_only" | "onboarded";

/**
 * The standing, from the two wire fields that carry it.
 *
 * `phoneMasked` is `null` exactly when the row holds no number, which is the server's own
 * `is_onboarded` predicate (`phone_e164 is not None`) seen through the mask — the mask never
 * turns a present number into `null`, it turns it into `"•••••42"`. Deriving the standing from
 * the masked value rather than from a second boolean is what keeps the label and the phone cell
 * on the same screen from disagreeing: they read one field.
 *
 * Ordering matters. `isProfilePresent` is tested FIRST, because an absent row has a `null`
 * `phoneMasked` too, and testing the phone first would report every erased account as
 * "onboarding unfinished" — an invented fact about a person who may have completed onboarding
 * years ago and then asked to be forgotten.
 *
 * `Pick` rather than the whole `UserView`, so the colocated test states its inputs instead of
 * building a twenty-field literal to exercise one branch.
 */
export function profileStandingOf(
  user: Pick<UserView, "isProfilePresent" | "phoneMasked">,
): ProfileStanding {
  if (!user.isProfilePresent) {
    return "absent";
  }
  return user.phoneMasked === null ? "language_only" : "onboarded";
}

/**
 * One short label per standing — the value a fact cell draws.
 *
 * Our chrome, never customer content, so it does not go through `<NameText>` and it is not
 * language-tagged. `Readonly<Record<ProfileStanding, string>>` and not a function with a
 * `default`: the compiler is what forces a fourth standing to be worded before it can ship,
 * and a `??` fallback is exactly how an unworded one reaches an operator as `undefined`.
 */
export const PROFILE_STANDING_LABEL: Readonly<Record<ProfileStanding, string>> = {
  absent: "no profile",
  language_only: "onboarding unfinished",
  onboarded: "onboarded",
};

/**
 * The sentence behind the label, carried on a `title`.
 *
 * Each one says what is NOT known as well as what is. The `absent` hint is the load-bearing
 * member: it is the only place in the console where the "deletion IS the erasure record"
 * consequence is spelled out to the person reading the screen, and an operator who does not
 * read it will otherwise conclude from a two-word label that this account never onboarded.
 */
export const PROFILE_STANDING_HINT: Readonly<Record<ProfileStanding, string>> = {
  absent:
    "No user_profiles row. Either this account has never answered the language question, or /forget erased it — the row is deleted outright, so the panel cannot tell those apart, and that absence IS the erasure record.",
  language_only:
    "They chose a language but have not shared a phone number yet, so they cannot order.",
  onboarded: "Language chosen and phone number shared.",
};

/** The single U+0020 the two masked names are joined with. Named so nobody "tidies" it. */
const NAME_JOINER = " ";

/**
 * The two masked names joined for display, or `null` when neither was shared.
 *
 * **No `.trim()` and no `.slice()`.** `slice` cuts UTF-16 code units and can split a surrogate
 * pair, which turns a name into a replacement character; `trim` would silently swallow a
 * server-sent value that is genuinely whitespace and make it indistinguishable from an absent
 * one. Nor is anything folded: this module sits outside the `components/domain/` ESLint fence,
 * so `toLowerCase` and friends are merely *available* here rather than banned — and the value
 * this function returns is handed straight to `<NameText>`, which exists precisely so that no
 * transform touches it. Availability is not permission.
 *
 * `null` and not `""`: an empty string is a rendered nothing that a caller cannot branch on, so
 * a screen would have to guess whether to draw an em dash. Returning `null` makes the two
 * decisions — "is there a name" and "how is it drawn" — belong to the caller and the component
 * respectively.
 */
export function displayNameOf(
  user: Pick<UserView, "firstNameMasked" | "lastNameMasked">,
): string | null {
  const parts = [user.firstNameMasked, user.lastNameMasked].filter(
    (part): part is string => part !== null,
  );
  return parts.length === 0 ? null : parts.join(NAME_JOINER);
}
