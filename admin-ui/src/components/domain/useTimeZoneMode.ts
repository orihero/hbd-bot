/**
 * Which clock a domain component renders in.
 *
 * §11.2: every column is `timestamptz`, three parties may be in three places, and "an
 * ambiguous 14:32 is a support incident". The top bar's UTC/local toggle is the single
 * source of that choice, so every domain component reads it from `usePrefsStore` rather
 * than taking a default of its own — otherwise flipping the toggle leaves half the screen
 * in the other zone, which is worse than having no toggle.
 *
 * The prop override exists for the one legitimate case: a surface that must show a fixed
 * zone regardless (a side-by-side UTC/local comparison, a test).
 */

import { usePrefsStore, type TimeZoneMode } from "@/lib";

export function useTimeZoneMode(override?: TimeZoneMode): TimeZoneMode {
  const stored = usePrefsStore((state) => state.timeZoneMode);
  return override ?? stored;
}
