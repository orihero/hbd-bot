/**
 * The user-detail screen's formatting, in one leaf module.
 *
 * Nothing here is decorative. Each function exists because the same value was about to be
 * printed two ways in two panels, and the two spellings would have disagreed about something
 * an operator reads aloud on a call:
 *
 *  - a `null` count is not a zero, so nothing here turns one into a number: the word that
 *    stands in for an absence is the caller's decision, and it differs per field;
 *  - a timestamp that cannot be parsed is printed VERBATIM, because the raw string is what
 *    goes into a bug report and a silent "Invalid Date" hides a contract change;
 *  - `uz_latn` and `uz_cyrl` are two SCRIPTS and are never collapsed into "Uzbek".
 */

import type { Language } from "@/api/users";
import { EMPTY_VALUE } from "@/features/reveal";

const INTEGER_FORMAT = new Intl.NumberFormat();

/**
 * Date AND time, because half of what this screen shows — a block's `changedAt`, a render
 * that failed — is only useful to the minute. The viewer's zone, deliberately: an operator
 * comparing this against a customer's "it stopped working after lunch" is in their own zone.
 */
const TIMESTAMP_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatInteger(value: number): string {
  return INTEGER_FORMAT.format(value);
}

/** A signed movement: `+5` / `−3`. The sign is the whole point of a ledger row. */
export function formatDelta(value: number): string {
  return value > 0 ? `+${INTEGER_FORMAT.format(value)}` : INTEGER_FORMAT.format(value);
}

/**
 * An RFC-3339 instant, or the string itself when it will not parse.
 *
 * Falling back to the raw value rather than to "Invalid Date" is the point: if the server ever
 * sends something this build does not understand, the operator can see and paste what arrived.
 */
export function formatTimestamp(at: string | null, absent: string = EMPTY_VALUE): string {
  if (at === null) return absent;
  const ms = Date.parse(at);
  return Number.isNaN(ms) ? at : TIMESTAMP_FORMAT.format(ms);
}

/**
 * The DAY of a retention stamp, taken off the front of the string rather than through a
 * formatter. A purge clock is a date the server decided; re-rendering it in the reader's
 * timezone can move it across midnight and make two operators disagree about when data went.
 */
export function formatDay(at: string): string {
  return at.slice(0, 10);
}

/** `a1b2c3d4…` — a UUID shortened for recognition. Never for comparison; that is `MONO_CLASS`. */
export function shortId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

/** `brief_ready` → `brief ready`. For the closed vocabularies whose members read as words. */
export function humaniseEnum(value: string): string {
  return value.replaceAll("_", " ");
}

/**
 * The four UI languages in full.
 *
 * `uz_latn` and `uz_cyrl` are the same language in two scripts and a customer who reads one
 * cannot necessarily read the other, so they are never collapsed — that is the difference
 * between sending somebody a song they can read and one they cannot.
 */
export const LANGUAGE_LABELS: Readonly<Record<Language, string>> = {
  uz_latn: "Uzbek (Latin)",
  uz_cyrl: "Uzbek (Cyrillic)",
  ru: "Russian",
  en: "English",
};

/**
 * The avatar monogram, from MASKED text only.
 *
 * A mask's first character is one the server already chose to show, so lifting it is not a
 * disclosure. Deriving a letter from REVEALED plaintext would be: it would put a bought,
 * audited character into a component with no audit row and no lifetime.
 */
export function initialsOf(
  firstNameMasked: string | null,
  lastNameMasked: string | null,
): string {
  const first = firstGrapheme(firstNameMasked);
  const last = firstGrapheme(lastNameMasked);
  const initials = `${first}${last}`;
  // Not a letter anywhere in either mask (a profile that is absent, or masked to bullets).
  return initials === "" ? "·" : initials;
}

function firstGrapheme(value: string | null): string {
  if (value === null) return "";
  const [...characters] = value.trim();
  const head = characters[0];
  if (head === undefined) return "";
  // A mask that begins with its own bullet has nothing to lift; a dot is honest, a bullet
  // repeated twice reads as a redaction of a name we do not have.
  return /\p{L}|\p{N}/u.test(head) ? head : "";
}
