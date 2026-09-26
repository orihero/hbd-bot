/**
 * The rule builder's public surface.
 *
 * `src/components/` has no barrel — a component is imported from its own file — but this is a
 * FOLDER of eight modules that are one feature, and the two screens that use it (the Users
 * filter panel and the campaign wizard) should not have to know which of the eight a given
 * helper lives in. Importing the individual files still works and nothing here re-exports
 * anything it does not own.
 */

export { SegmentBuilder, type SegmentBuilderProps } from "./SegmentBuilder";
export { RuleRow, type RuleRowProps } from "./RuleRow";
export {
  DAY_PRESETS,
  DEBOUNCE_MS as SEGMENT_INPUT_DEBOUNCE_MS,
  VALUE_EDITORS,
  ValueEditorSlot,
  valueEditorFor,
  type ValueEditor,
  type ValueEditorProps,
} from "./valueEditors";
export {
  buildSegmentChips,
  describeSegmentRule,
  segmentChipsLabel,
  segmentFilterCount,
  type SegmentChipOptions,
} from "./segmentChips";
export {
  SEGMENT_PREVIEW_DEBOUNCE_MS,
  SEGMENT_REGISTRY_STALE_TIME_MS,
  segmentKeys,
  useDebouncedSegment,
  useSegmentFields,
  useSegmentPreview,
  type SegmentKeys,
} from "./useSegmentFields";
export {
  MAX_RELATIVE_DAYS,
  MIN_RELATIVE_DAYS,
  formatSegmentIssue,
  isSegmentValid,
  issuesAt,
  segmentIssues,
  type SegmentIssue,
  type SegmentIssueCode,
} from "./segmentValidation";
export {
  appendAt,
  canNestAt,
  clearRules,
  defaultOpFor,
  groupForField,
  nodeAt,
  pathKey,
  removeAt,
  replaceAt,
  ruleForField,
  ruleWithOp,
  ruleWithValue,
  setMatchAt,
  withSort,
  type SegmentPath,
} from "./segmentTree";
export {
  fieldLabel,
  matchHeading,
  matchLabel,
  memberLabel,
  opLabel,
  useTranslate,
  type Translate,
} from "./segmentLabels";
export {
  dateInputValue,
  endOfLocalDayExclusiveIso,
  formatInstantDay,
  monthInputValue,
  monthRangeIso,
  startOfLocalDayIso,
} from "./instants";
