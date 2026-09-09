/**
 * The domain barrel.
 *
 * These are the components that know what the data MEANS, as opposed to the layout and
 * table primitives that only know how it is shaped. Screens import from `@/components/domain`
 * and never reach past it, so the rules that live here — a name is never folded, a purged
 * record is never a blank, an absent source is never "nothing happened", retryability is
 * tri-state — are enforced in one directory with one ESLint fence over it (§11.4).
 *
 * NOT here, deliberately: `RetryOrderDialog`, `ModerationCard`, `ChatTranscript`,
 * `MessageBubble`, `AuditRow`, `ConfigDiffDialog`, `ConfirmDangerDialog`. Every one of them
 * needs an endpoint that does not exist on this build (retry, moderation, chat) and would be
 * a control that cannot work — §11.4's rule about role-based HIDING applies to phases as well
 * as to roles.
 *
 * `RevealDialog` and `RevealBudgetMeter` LEFT that list in Phase 2, because `POST /api/reveal`
 * exists now. They arrive with three files that are not §11.4 components and are exported all
 * the same, because the next four phases need them:
 *
 *  - `stepUp.ts` / `<StepUpPrompt>` — the app's ONE re-authentication path. `/api/reveal` is
 *    the first handler in the product that calls `deps.enforce_step_up`, so it is the first
 *    `403 STEP_UP_REQUIRED` with a remedy behind it; every later `A+S` cell (`order.retry`,
 *    `user.block`, `user.purge`, `config.write`, `audit.export`, …) refuses and recovers
 *    identically. Reuse it rather than writing a second re-auth form: two of them will
 *    disagree about the scope spelling and a scope mismatch is a permanent, silent 403.
 *  - `revealBudget.ts` — the budget as the client can honestly know it. There is no endpoint
 *    that answers "what is left"; the only figures that exist are on a reveal's response and
 *    on its 429.
 *  - `useReveal.ts` — the two mutations and the budget cache, so one reveal's cost is visible
 *    on the next dialog.
 */

export { AssetCard, PLAYBACK_IS_A_REVEAL_LABEL, UNRECORDED_STORAGE_KEY_LABEL } from "./AssetCard";
export type { AssetCardProps } from "./AssetCard";

export { AudioPlayer } from "./AudioPlayer";
export type { AudioPlayerProps } from "./AudioPlayer";

export { AttentionList } from "./AttentionList";
export type { AttentionListProps } from "./AttentionList";

export { CodepointTooltip } from "./CodepointTooltip";
export type { CodepointTooltipProps } from "./CodepointTooltip";

export {
  AMBIGUOUS_CODEPOINTS,
  codepointSequence,
  formatCodepoint,
  isAmbiguousCodepoint,
  toCodepoints,
} from "./codepoints";
export type { Codepoint } from "./codepoints";

export {
  feedSeverityColorVar,
  feedSeverityGlyph,
  rateBandColorVar,
  retryabilityColorVar,
  tintVar,
} from "./colors";

export { ConfigField, SECRET_ABSENT_VALUE } from "./ConfigField";
export type { ConfigFieldProps, ConfigTier } from "./ConfigField";

export { CorrelationChip } from "./CorrelationChip";
export type { CorrelationChipProps } from "./CorrelationChip";

export { CreditBalanceChip } from "./CreditBalanceChip";
export type { CreditBalanceChipProps } from "./CreditBalanceChip";

export { CreditLedgerTable } from "./CreditLedgerTable";
export type { CreditLedgerTableProps } from "./CreditLedgerTable";

export {
  CREDIT_BALANCE_COLOR_VAR,
  CREDIT_BALANCE_GLYPH,
  CREDIT_BALANCE_TITLES,
  CREDIT_KIND_COLOR_VAR,
  CREDIT_KIND_GLYPH,
  creditBalanceState,
  NEVER_METERED_BODY,
  NEVER_METERED_LABEL,
  NEVER_METERED_TITLE,
} from "./credits";
export type { CreditBalanceState } from "./credits";

export { DurationBadge } from "@/components/data";
export type { DurationBadgeProps } from "@/components/data";

export { ErrorCodeBadge } from "./ErrorCodeBadge";
export type { ErrorCodeBadgeProps } from "./ErrorCodeBadge";

export {
  CREDITS_RANGE_HINT,
  FRESH_GRANT_NOTICE,
  GRANT_TITLE,
  GrantCreditsButton,
  GrantCreditsDialog,
  REPLAY_NOTICE,
} from "./GrantCreditsDialog";
export type { GrantCreditsButtonProps, GrantCreditsDialogProps } from "./GrantCreditsDialog";

export { LiveFeed } from "./LiveFeed";
export type { LiveFeedProps } from "./LiveFeed";

export { NAME_DIR, NAME_LANG, NameText } from "./NameText";
export type { NameTextProps } from "./NameText";

export { ACTION_REASON_REQUIRED_HINT, ReasonConfirmDialog } from "./ReasonConfirmDialog";
export type { ReasonConfirmDialogProps, ReasonValue } from "./ReasonConfirmDialog";

export {
  LONG_REF_WARNING,
  NO_RETENTION_CLOCK_NOTE,
  REASON_REQUIRED_HINT,
  REVEAL_IS_LOGGED_NOTE,
  RevealButton,
  RevealDialog,
} from "./RevealDialog";
export type { RevealButtonProps, RevealDialogProps } from "./RevealDialog";

export { RevealBudgetMeter } from "./RevealBudgetMeter";
export type { RevealBudgetMeterProps, RevealCeilingsInput } from "./RevealBudgetMeter";

export {
  applyBudgetRefusal,
  applyRevealBudget,
  budgetBand,
  budgetBandColorVar,
  budgetScopeOf,
  BUDGET_BAND_GLYPH,
  BUDGET_BAND_LABEL,
  currentReading,
  currentSnapshot,
  formatResetIn,
  isSameWindow,
  readBudgetRefusal,
  remainingAfter,
  REVEAL_BUDGET_LABELS,
  REVEAL_BUDGET_UNITS,
  REVEAL_BUDGET_WINDOW_LABELS,
  REVEAL_BUDGET_WINDOW_S,
  secondsToReset,
  TIGHT_FRACTION,
  UNMEASURED,
  UNMEASURED_REVEAL_BUDGET,
  willExceedBudget,
  windowIndex,
  windowResetAt,
} from "./revealBudget";
export type {
  BudgetBand,
  BudgetRefusal,
  CounterReading,
  RevealBudgetSnapshot,
} from "./revealBudget";

export {
  ATTEMPT_REVEAL_FIELDS,
  BRIEF_REVEAL_FIELDS,
  canSubmitReveal,
  describeRevealCost,
  FREE,
  orderFields,
  revealCost,
  revealShapeOf,
  REVEAL_FIELD_HINTS,
  REVEAL_FIELD_LABELS,
  REVEAL_REASON_LABELS,
  REVEAL_SHAPE_LABELS,
  USER_PROFILE_REVEAL_FIELDS,
} from "./revealFields";
export type { RevealCost } from "./revealFields";

export {
  graceNote,
  grantWindowS,
  isSameTarget,
  isStepUpRequired,
  stepUpTargetOf,
  STEP_UP_EXPLANATION,
  ZERO_GRACE_NOTE,
} from "./stepUp";
export type { StepUpTarget } from "./stepUp";

export { StepUpPrompt, STEP_UP_TITLE } from "./StepUpPrompt";
export type { StepUpPromptProps } from "./StepUpPrompt";

export {
  useReveal,
  useRecordRevealBudget,
  useRevealBudget,
  useRevealCeilings,
  useStepUp,
} from "./useReveal";
export type { RevealCeilings } from "./useReveal";

export { OrderRefChip } from "./OrderRefChip";
export type { OrderRefChipProps } from "./OrderRefChip";

export { PipelineTimeline } from "./PipelineTimeline";
export type { PipelineTimelineProps } from "./PipelineTimeline";

export { PurgedRange } from "./PurgedRange";
export type { PurgedRangeProps } from "./PurgedRange";

export {
  assetTrack,
  isAudioAsset,
  isRetryableFailure,
  NUDGE_SECONDS,
  PLAYER_COPY,
  toPlayerFailure,
} from "./playback";

export { PURGE_GLYPH, PURGED_LABEL, PurgedValue } from "./PurgedValue";
export type { PurgedValueProps } from "./PurgedValue";

export {
  assetRetentionClocks,
  briefRetentionClocks,
  EXPIRING_SOON_DAYS,
  retentionUrgency,
  retentionUrgencyColorVar,
} from "./retention";
export type { RetentionClock, RetentionUrgency } from "./retention";

export { RetentionClocks } from "./RetentionClocks";
export type { RetentionClocksProps } from "./RetentionClocks";

export { buildSimilarityBuckets, DEFAULT_BUCKET_COUNT, formatSimilarity } from "./similarity";
export type { SimilarityBucket } from "./similarity";

export {
  AT_OR_ABOVE_THRESHOLD_LABEL,
  BELOW_THRESHOLD_LABEL,
  SimilarityHistogram,
  THRESHOLD_LINK_LABEL,
  THRESHOLD_UNKNOWN_LABEL,
} from "./SimilarityHistogram";
export type { SimilarityHistogramProps } from "./SimilarityHistogram";

export { StageMiniBar } from "./StageMiniBar";
export type { StageMiniBarProps } from "./StageMiniBar";

export {
  failedStage,
  INCONCLUSIVE_PLAN_LABEL,
  INFERRED_PLAN_LABEL,
  NO_RECORD_LABEL,
  NOT_PLANNED_LABEL,
  planEntries,
  stageOutcomeColorVar,
  stageOutcomeGlyph,
  stageOutcomeLabel,
} from "./stagePlan";
export type { StageEntry } from "./stagePlan";

export { StatusPill } from "./StatusPill";
export type { StatusPillProps } from "./StatusPill";

export {
  NEAR_THRESHOLD_GLYPH,
  NO_ATTEMPTS_LABEL,
  StrategyBakeoffChart,
} from "./StrategyBakeoffChart";
export type { BakeoffRow, StrategyBakeoffChartProps } from "./StrategyBakeoffChart";

export { TelegramUserChip } from "./TelegramUserChip";
export type { TelegramUserChipProps } from "./TelegramUserChip";

export {
  INFERRED_SOURCE_LABEL,
  STATE_TRANSITIONS_LABEL,
  TimelineSourceLegend,
} from "./TimelineSourceLegend";
export type { TimelineSourceLegendProps } from "./TimelineSourceLegend";

export {
  NO_PHOTO_NO_NAME_TITLE,
  NO_PHOTO_TITLE,
  USER_AVATAR_IMAGE_TESTID,
  USER_AVATAR_MONOGRAM_TESTID,
  UserAvatar,
} from "./UserAvatar";
export type { UserAvatarProps } from "./UserAvatar";

export { useTimeZoneMode } from "./useTimeZoneMode";
