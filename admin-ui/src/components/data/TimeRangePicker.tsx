/**
 * `TimeRangePicker` — §11.4, and the control that scopes `WindowQuery` on every windowed
 * endpoint (`/metrics/*`, `/orders`, `/users`, `/generations`, `/assets`).
 *
 * Presets are rows and they come first: nobody fights a calendar grid for "last 30 days".
 * The custom range sits behind a hairline, disclosed only when asked for. One picker per
 * screen, in the `FilterBar` row, scoping everything below it — never one per chart.
 *
 * ## The two things this must not get wrong
 *
 * **The emitted instant always carries an offset.** `zInstantParam` rejects a naive
 * timestamp, and every windowed endpoint 422s on one. `toISOString()` gives a `Z`, so a
 * preset and a custom range both emit something the URL codec will keep. A rejected value
 * would silently vanish from the URL and the operator would be looking at an unfiltered
 * screen that claims to be filtered.
 *
 * **The custom inputs say which clock they are in.** `<input type="datetime-local">` has no
 * zone and reads the browser's; there is no attribute that changes that. So the field is
 * labelled with the actual local offset and the resulting instant is echoed underneath in
 * the operator's chosen mode. §11.2's rule — an ambiguous "14:32" is a support incident —
 * applies to input as much as to output, and this is the one control in the console where
 * an operator types a time rather than reading one.
 *
 * **A preset emits BOTH bounds.** `from` and `to` are one window to this API: every windowed
 * router refuses exactly one of them with a 422 ("from and to are one window — give both
 * bounds or neither"), and `windowParams` in the API layer answers that by dropping a half
 * window on the floor. So a preset that emitted `{from, to: undefined}` produced an
 * UNFILTERED screen that claimed to be filtered — the worst of the three outcomes, because
 * nothing goes red. The picker closes the range at the moment of the click instead. Three
 * feature directories had each written the same `completeWindow` workaround around this;
 * the fix belongs here, once.
 *
 * ## Which preset is lit
 *
 * A preset's window is "now minus a span, up to now", so it stops matching the clock a second
 * after it is chosen. Re-deriving the active preset by comparing against a fresh `now` would
 * therefore un-light it immediately. Instead the picker remembers the exact PAIR it last
 * emitted: if `value` is still that pair, that preset is still the active one — which
 * survives a reload only as "custom", correctly, because a pasted URL genuinely names a
 * fixed window rather than a rolling one.
 */

import { useCallback, useRef, useState, type ReactElement, type ReactNode } from "react";

import { Button, segmentVariant } from "@/components/util";
import { cn, formatTimestamp, localOffsetLabel, timeZoneLabel, usePrefsStore } from "@/lib";

/** The shape `WindowQuery` takes. Both ends optional; absent `to` means "up to now". */
export interface TimeRange {
  readonly from?: string | undefined;
  readonly to?: string | undefined;
}

export interface TimeRangePreset {
  readonly id: string;
  readonly label: string;
  readonly ms: number;
}

export const TIME_RANGE_PRESETS = [
  { id: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { id: "7d", label: "Last 7 days", ms: 604_800_000 },
  { id: "30d", label: "Last 30 days", ms: 2_592_000_000 },
  { id: "90d", label: "Last 90 days", ms: 7_776_000_000 },
] as const satisfies readonly TimeRangePreset[];

export interface TimeRangePickerProps {
  readonly value: TimeRange;
  readonly onChange: (next: TimeRange) => void;
  /** Offer "All time" (both ends cleared). Off where the endpoint needs a window. */
  readonly isAllTime?: boolean;
  readonly className?: string;
  readonly label?: string;
}

export function TimeRangePicker({
  value,
  onChange,
  isAllTime = true,
  className,
  label = "time range",
}: TimeRangePickerProps): ReactElement {
  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);
  const [isCustomOpen, setIsCustomOpen] = useState(false);
  /** The exact pair each preset last emitted — see the header note. */
  const emitted = useRef<Map<string, TimeRange>>(new Map());

  const hasFrom = value.from !== undefined && value.from !== "";
  const hasTo = value.to !== undefined && value.to !== "";
  /** Exactly one bound: the API will not accept it, so the screen is not really filtered. */
  const isHalfWindow = hasFrom !== hasTo;

  const activePresetId = (() => {
    if (!hasFrom && !hasTo) return isAllTime ? "all" : null;
    for (const [id, range] of emitted.current) {
      if (range.from === value.from && range.to === value.to) return id;
    }
    return "custom";
  })();

  const choosePreset = useCallback(
    (preset: TimeRangePreset) => {
      // Closed at the instant of the click, not left open-ended: see the header note.
      const now = Date.now();
      const range: TimeRange = {
        from: new Date(now - preset.ms).toISOString(),
        to: new Date(now).toISOString(),
      };
      emitted.current.set(preset.id, range);
      setIsCustomOpen(false);
      onChange(range);
    },
    [onChange],
  );

  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)} aria-label={label}>
      <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1">
        {isAllTime && (
          <PresetButton
            isActive={activePresetId === "all"}
            onClick={() => {
              setIsCustomOpen(false);
              onChange({ from: undefined, to: undefined });
            }}
          >
            All time
          </PresetButton>
        )}
        {TIME_RANGE_PRESETS.map((preset) => (
          <PresetButton
            key={preset.id}
            isActive={activePresetId === preset.id}
            onClick={() => {
              choosePreset(preset);
            }}
          >
            {preset.label}
          </PresetButton>
        ))}
        <PresetButton
          isActive={activePresetId === "custom"}
          onClick={() => {
            setIsCustomOpen((open) => !open);
          }}
          aria-expanded={isCustomOpen}
        >
          Custom…
        </PresetButton>
      </div>

      {isCustomOpen && (
        /* The hairline the custom range sits behind — decoration, and the one rule this
           control draws. */
        <div className="mt-2 flex w-full flex-wrap items-end gap-3 border-t border-hairline pt-3">
          <CustomInstantField
            id="time-range-from"
            label="From"
            iso={value.from ?? null}
            onChange={(iso) => {
              onChange({ from: iso ?? undefined, to: value.to });
            }}
          />
          <CustomInstantField
            id="time-range-to"
            label="To"
            iso={value.to ?? null}
            onChange={(iso) => {
              onChange({ from: value.from, to: iso ?? undefined });
            }}
          />
          <p className="type-body-sm text-ink-muted">
            {isHalfWindow ? (
              /* `--warning`, not `--caution`: a half window means the screen is showing an
                 UNFILTERED list while claiming to be filtered. That is the harder of the two
                 non-fatal hues, and the sentence beside it carries the same fact in words. */
              <span
                className="mb-1 flex items-start gap-1.5 rounded-2xs bg-warning-tint px-2 py-1 text-ink"
                data-testid="half-window"
              >
                <span aria-hidden="true" className="text-warning">
                  ⚠
                </span>
                <span>
                  A window is both ends or neither — this range is not applied until the other
                  end is set.
                </span>
              </span>
            ) : null}
            entered in local time ({localOffsetLabel()}); shown in {timeZoneLabel(timeZoneMode)}
            {value.from === undefined ? null : (
              <>
                {" · "}
                <span className="num text-ink">{formatTimestamp(value.from, timeZoneMode)}</span>
                {" → "}
                <span className="num text-ink">
                  {value.to === undefined ? "now" : formatTimestamp(value.to, timeZoneMode)}
                </span>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

function PresetButton({
  isActive,
  onClick,
  children,
  ...rest
}: {
  readonly isActive: boolean;
  readonly onClick: () => void;
  readonly children: ReactNode;
  readonly "aria-expanded"?: boolean;
}): ReactElement {
  return (
    /*
     * The Gogo segmented control, from the one definition: a chosen segment is the secondary
     * idiom (the brand tint with the brand as its label); an unchosen one is `quiet` — no
     * ground at all until hover, rather than the filled grey chip it used to be. No borders
     * on either; a control carries a surface here, never an outline.
     */
    <Button
      variant={segmentVariant(isActive)}
      size="sm"
      shape="pill"
      onClick={onClick}
      aria-pressed={isActive}
      className="px-3"
      {...rest}
    >
      {/* Selection is a glyph as well as a colour — the bold check the spec asks for. It
          inherits the segment's own label colour, so it needs no colour of its own. */}
      <span aria-hidden="true" className={isActive ? "font-bold" : "opacity-0"}>
        ✓
      </span>
      {children}
    </Button>
  );
}

/**
 * One end of a custom range.
 *
 * `datetime-local` speaks the browser's zone in `YYYY-MM-DDTHH:mm`, so the conversion runs
 * in both directions through `Date`, and the value handed back out is always a full ISO
 * instant with a `Z`.
 */
function CustomInstantField({
  id,
  label,
  iso,
  onChange,
}: {
  readonly id: string;
  readonly label: string;
  readonly iso: string | null;
  readonly onChange: (iso: string | null) => void;
}): ReactElement {
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="type-caption text-ink-muted">{label}</span>
      <input
        id={id}
        type="datetime-local"
        className="num rounded-control bg-surface-control px-3 py-1.5 text-ink"
        value={toLocalInputValue(iso)}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") {
            onChange(null);
            return;
          }
          const ms = Date.parse(raw);
          onChange(Number.isNaN(ms) ? null : new Date(ms).toISOString());
        }}
      />
    </label>
  );
}

/** An ISO instant as the local `YYYY-MM-DDTHH:mm` the input expects. */
function toLocalInputValue(iso: string | null): string {
  if (iso === null || iso === "") return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const at = new Date(ms);
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${String(at.getFullYear())}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(
    at.getHours(),
  )}:${pad(at.getMinutes())}`;
}
