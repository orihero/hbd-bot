/**
 * §11.4's Utility inventory: `AsyncBoundary`, `ErrorBoundary`, `EmptyState`, `ErrorState`,
 * `PermissionGate`, `CopyButton`, `KeyboardShortcuts` — plus the pieces they are built from
 * that screens legitimately need on their own (the skeleton primitives, the RBAC mirror,
 * the session hooks).
 *
 * `Button` / `buttonVariants` / `segmentVariant` live here too, and they are the ONLY
 * definition of a button, a tab or a toggle in this console. See `buttonVariants.ts` for the
 * four variants and the measured contrast of every pair they can paint; a call site that
 * hand-rolls a `bg-…`/`text-…` pair on a clickable is the defect that file was written to
 * end.
 *
 * Import from `@/components/util`, not from the files.
 */

export { AsyncBoundary, type AsyncBoundaryProps } from "./AsyncBoundary";
export {
  resolveAsyncState,
  keepsChildren,
  type AsyncStateInput,
  type AsyncStateKind,
} from "./asyncState";
export { Button, type ButtonProps } from "./Button";
export {
  buttonVariants,
  segmentVariant,
  type ButtonVariantProps,
  type SegmentVariant,
} from "./buttonVariants";
export { CopyButton, type CopyButtonProps } from "./CopyButton";
export { EmptyState, FilteredEmptyState, type EmptyStateProps, type FilteredEmptyStateProps } from "./EmptyState";
export { ErrorBoundary, type ErrorBoundaryProps } from "./ErrorBoundary";
export { ErrorState, type ErrorStateProps } from "./ErrorState";
export { useIsDocumentVisible, useMediaQuery, useNow, usePrefersReducedMotion } from "./hooks";
export { KeyboardShortcuts, type KeyboardShortcutsProps } from "./KeyboardShortcuts";
export { useShortcutHelp, type ShortcutHelpApi } from "./shortcutHelp";
export { isAppleKeyboard, isTypingTarget, shortcutRows, type ShortcutRow } from "./shortcuts";
export { PermissionGate, type PermissionGateProps } from "./PermissionGate";
export {
  RBAC_MATRIX,
  ROLE_PERMISSIONS,
  hasAllPermissions,
  hasAnyPermission,
  hasPermission,
  isPermitted,
} from "./rbac";
export {
  Skeleton,
  SkeletonTable,
  SkeletonText,
  type SkeletonProps,
  type SkeletonTableProps,
  type SkeletonTextProps,
} from "./Skeleton";
export {
  useHasAllPermissions,
  useHasAnyPermission,
  useHasPermission,
  useRole,
  useSession,
  type Session,
} from "./useSession";
