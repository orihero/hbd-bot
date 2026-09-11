/**
 * The twelve clocks a retention sweep runs, as data.
 *
 * `SweepCounts` is a flat object of twelve integers and it is reported twice: once as
 * `rowsPastExpiry` (counted LIVE, right now, not read off any run) and once inside each
 * `PurgeRunView.counts` (what that run actually deleted). Rendering them as a table of
 * clocks rather than as two blobs of numbers is what lets an operator answer the question
 * they came with — *which* clock is behind — instead of only *whether* something is.
 *
 * The `clock` text on each row is what the sweep in `src/bayram/db/purge.py` actually keys on,
 * not a guess: `_purge_brief_notes` clears the note **and** the approved lyric on the brief
 * text clock, `_purge_attempt_transcripts` runs the song transcript on that same clock while
 * `_purge_attempt_identities` runs the name on the identity clock sixty days later, and the
 * three admin clocks (reasons, rows, sessions) belong to the panel rather than to the bot.
 */

import type { SweepCounts } from "@/api";

export interface SweepClock {
  /** The `SweepCounts` key. Also the row's React key and `data-clock` attribute. */
  readonly key: keyof SweepCounts;
  /** Our own label for what is deleted. */
  readonly label: string;
  /** Which retention clock governs it. */
  readonly clock: string;
}

export const SWEEP_CLOCKS: readonly SweepClock[] = [
  { key: "assetsDeleted", label: "assets", clock: "the asset's retention class" },
  { key: "briefNotesPurged", label: "brief notes and approved lyrics", clock: "brief text" },
  { key: "briefIdentitiesPurged", label: "brief identities", clock: "recipient identity" },
  {
    key: "attemptIdentitiesPurged",
    label: "attempt name text",
    clock: "recipient identity",
  },
  { key: "attemptTranscriptsPurged", label: "attempt transcripts", clock: "brief text" },
  {
    key: "nameRecordsDeleted",
    label: "name dictionary entries",
    clock: "the entry's own expiry — user-confirmed rows only",
  },
  { key: "abandonedOrdersDeleted", label: "abandoned draft orders", clock: "abandoned draft" },
  { key: "auditReasonsPurged", label: "audit reason text", clock: "audit reason · 90 days" },
  { key: "auditRowsDeleted", label: "audit rows", clock: "audit log · 730 days" },
  { key: "adminSessionsDeleted", label: "admin sessions", clock: "session expiry" },
  { key: "purgeRunsDeleted", label: "purge run records", clock: "the run history's own clock" },
  { key: "vendorUsageDeleted", label: "vendor call records", clock: "vendor usage · 400 days" },
];

/**
 * How the storage tally reads.
 *
 * `"keys_unrecorded"` is today's normal answer and it means **unknown**, never clean: the
 * asset rows carried no storage key, so the sweep deleted the database record and could not
 * reach the object. A `null` reconciliation on the response is a different fact again — no
 * run has ever happened — and a scheduler that never fired must not light a clean badge.
 */
export type ReconciliationTone = "good" | "warn" | "bad" | "unknown";

export interface ReconciliationPresentation {
  readonly tone: ReconciliationTone;
  readonly colorVar: string;
  readonly label: string;
  readonly note: string;
}

export function reconciliationPresentation(
  reconciliation: string | null,
): ReconciliationPresentation {
  switch (reconciliation) {
    case "reconciled":
      return {
        tone: "good",
        colorVar: "var(--success)",
        label: "reconciled",
        note: "every key the sweep returned was deleted from storage",
      };
    case "leaked":
      return {
        tone: "bad",
        colorVar: "var(--error)",
        label: "leaked",
        note: "objects outlived their rows — the bytes are still in the bucket",
      };
    case "keys_unrecorded":
      return {
        tone: "unknown",
        colorVar: "var(--caution)",
        label: "keys unrecorded",
        note: "the rows carried no storage key, so nothing could be reconciled — unknown, not clean",
      };
    case "nothing_to_reconcile":
      return {
        tone: "good",
        colorVar: "var(--neutral)",
        label: "nothing to reconcile",
        note: "the sweep deleted no assets in this run",
      };
    default:
      return {
        tone: "unknown",
        // `--neutral`, the palette's true grey for "nothing has happened yet", and NOT
        // `--ink-muted`: the caller paints this hue onto a chip whose GROUND it derives with
        // `tintVar`, and only the semantic FAMILIES ship a `-tint` member — `var(--ink-muted-tint)`
        // does not exist and would have painted no ground at all. `--neutral` is text-safe
        // (4.52:1 at its worst in light, 4.60:1 in dark), so the label still reads as prose.
        colorVar: "var(--neutral)",
        label: "no run has ever happened",
        note: "there is no reconciliation to report until a sweep has run",
      };
  }
}
