/**
 * `components/data/` — §11.4's Data inventory.
 *
 * Import from `@/components/data`, not from the files: `ChartFrame` is the fence that keeps
 * Recharts out of every other module (§11.1), and a deep import is how that fence starts to
 * leak.
 */

export { ChartFrame } from "./ChartFrame";
export type {
  ChartDatum,
  ChartFrameProps,
  ChartKind,
  ChartSeriesSpec,
} from "./ChartFrame";

export {
  CATEGORICAL_TONES,
  MARKER_RADIUS,
  MARKER_SHAPES,
  SERIES_DASH,
  categoricalTone,
  chartToneVar,
  isOrderStateTone,
  isSemanticTone,
  markerPath,
  orderStateTintVar,
  seriesDash,
  seriesMarker,
} from "./chartTokens";
export type { CategoricalTone, ChartTone, MarkerShape, SemanticTone } from "./chartTokens";

export { CodeBlock } from "./CodeBlock";
export type { CodeBlockProps } from "./CodeBlock";

export { CursorPager, PAGE_LIMIT_CHOICES } from "./CursorPager";
export type { CursorPagerProps } from "./CursorPager";

export { DataTable } from "./DataTable";
export type { DataColumn, DataTableProps } from "./DataTable";

export { DurationBadge } from "./DurationBadge";
export type { DurationBadgeProps } from "./DurationBadge";

export { FilterBar, FilterChip } from "./FilterBar";
export type { FilterBarProps } from "./FilterBar";

export { buildFilterChips, defaultChipFormat } from "./filterChips";
export type { FilterChipModel, FilterFieldDescriptor, FilterScalar } from "./filterChips";

export { JsonViewer } from "./JsonViewer";
export { REDACTED_KEY_SUFFIXES, isRedactedKey } from "./redaction";
export type { JsonViewerProps } from "./JsonViewer";

export { Sparkline } from "./Sparkline";
export type { SparklineProps } from "./Sparkline";

export { BAND_PRESENTATION, StatTile } from "./StatTile";
export type { DeltaTone, StatDelta, StatTileProps } from "./StatTile";

export { StateDistributionBar } from "./StateDistributionBar";
export type { StateDistributionBarProps } from "./StateDistributionBar";

export { TIME_RANGE_PRESETS, TimeRangePicker } from "./TimeRangePicker";
export type { TimeRange, TimeRangePickerProps, TimeRangePreset } from "./TimeRangePicker";

export { TimeZoneCaption, Timestamp } from "./Timestamp";
export type { TimestampProps } from "./Timestamp";

export { COPY_FEEDBACK_MS, useCopy } from "./useCopy";
export type { CopyState } from "./useCopy";
