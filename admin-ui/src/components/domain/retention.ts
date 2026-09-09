/**
 * The retention clocks a record is standing under, as data.
 *
 * §12.3: `identity_purged_at` is **always** displayed. "No name" and "name purged on
 * schedule 2026-05-14" are different facts and only one of them is defensible. A brief runs
 * two independent clocks (identity and note) that expire on different days under different
 * settings; an asset runs one, keyed on its `retentionClass`. Collapsing them into a single
 * "expires" field loses the ability to answer "why is the name gone but the note still
 * here", which is a question support actually gets.
 */

import type { AssetWireView, BriefWireView, RetentionClass } from "@/api";

export interface RetentionClock {
  /** Our own label — a closed vocabulary, never anything a customer wrote. */
  readonly label: string;
  /** When the clock runs out. `null` when this record has no clock of that kind. */
  readonly expiresAt: string | null;
  /** When the purge actually happened. Non-null means the value is already gone. */
  readonly purgedAt: string | null;
  /** The policy class, where the record carries one. */
  readonly retentionClass?: RetentionClass | undefined;
}

/**
 * A brief's two clocks, in the order they matter to support: the identity first, because
 * the name is what a "you spelled my sister's name wrong" conversation is about.
 */
export function briefRetentionClocks(brief: BriefWireView): readonly RetentionClock[] {
  return [
    {
      label: "recipient identity",
      expiresAt: brief.identityExpiresAt,
      purgedAt: brief.identityPurgedAt,
    },
    {
      label: "note",
      expiresAt: brief.noteExpiresAt,
      purgedAt: brief.notePurgedAt,
    },
  ];
}

/**
 * An asset's single clock. There is no `purgedAt` on the wire — an expired asset row is
 * DELETED by the sweep rather than blanked, so a row that is still here has not been
 * purged, and `null` is the honest answer rather than a guess.
 */
export function assetRetentionClocks(asset: AssetWireView): readonly RetentionClock[] {
  return [
    {
      label: "asset",
      expiresAt: asset.expiresAt,
      purgedAt: null,
      retentionClass: asset.retentionClass,
    },
  ];
}

/** How close a clock is to running out. Drives the colour, never the only channel. */
export type RetentionUrgency = "expired" | "soon" | "later" | "purged" | "none";

/** §11.2's `/assets` question is "what is about to expire", and it means within 7 days. */
export const EXPIRING_SOON_DAYS = 7;

export function retentionUrgency(clock: RetentionClock, daysLeft: number | null): RetentionUrgency {
  if (clock.purgedAt !== null) return "purged";
  if (daysLeft === null) return "none";
  if (daysLeft <= 0) return "expired";
  if (daysLeft <= EXPIRING_SOON_DAYS) return "soon";
  return "later";
}

export function retentionUrgencyColorVar(urgency: RetentionUrgency): string {
  switch (urgency) {
    case "expired":
      return "var(--error)";
    case "soon":
      return "var(--caution)";
    case "later":
      return "var(--ink-muted)";
    // `--ink-muted`, not the policed `--ink-mark`: this colour paints the WORDS "expires
    // today" / "4d past expiry" / the em dash. `--ink-muted` clears 4.5:1 on every ground of
    // every cell; `--ink-mark` is 3.56:1 at its worst and is a glyph colour only.
    case "purged":
      return "var(--ink-muted)";
    case "none":
      return "var(--ink-muted)";
  }
}
