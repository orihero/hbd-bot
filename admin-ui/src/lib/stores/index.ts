/**
 * The three client stores, and only three (§11.1).
 *
 * Adding a fourth is a decision, not a convenience: everything else that looks like it wants
 * a store is either server state (TanStack Query owns it) or filter state (the URL owns it,
 * via `useSearchParamsState`).
 */

export {
  usePlayerStore,
  useIsCurrentTrack,
  type PlayerFailure,
  type PlayerFailureKind,
  type PlayerPhase,
  type PlayerState,
  type PlayerTrack,
  type StreamCapabilities,
} from "./usePlayerStore";
export {
  useFeedStore,
  useVisibleFeed,
  FEED_CAPACITY,
  type FeedEvent,
  type FeedSeverity,
  type FeedState,
} from "./useFeedStore";
export {
  usePrefsStore,
  applyTheme,
  initTheme,
  PREFS_STORAGE_KEY,
  type Density,
  type PrefsState,
  type ThemeChoice,
} from "./usePrefsStore";
