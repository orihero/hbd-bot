/**
 * One place a `Language` becomes a phrase an operator reads.
 *
 * Four modules used to hold their own copy of this table — the users directory, the user
 * detail screen, the generations log and the language-mix figure — and the four agreed only
 * because nobody had edited one of them yet. They are keys now, resolved from
 * `segments.members.ui_language`, which is where the catalogue already spelled the same four
 * members for the segment builder.
 *
 * Two SCRIPTS of one language, never collapsed into "Uzbek": the API distinguishes them, and
 * which of the two a customer reads is the fact this label carries.
 */

import type { Language } from "@/api/users";
import type { TranslationPath } from "@/i18n/types";

export const LANGUAGE_LABEL_KEY: Readonly<Record<Language, TranslationPath>> = {
  uz_latn: "segments.members.ui_language.uz_latn",
  uz_cyrl: "segments.members.ui_language.uz_cyrl",
  ru: "segments.members.ui_language.ru",
  en: "segments.members.ui_language.en",
};
