import type { ReactNode } from "react";

import { Segmented, type SegmentedOption } from "@/components/Segmented";
import type { Gran } from "@/features/dashboard/data";

interface ChartCardProps {
  readonly title: string;
  readonly sub: string;
  /** Small uppercase caveat riding on the title — "68% priced", "last 30d". */
  readonly cov?: string | undefined;
  /**
   * The figure's own viewBox ratio, as a CSS `aspect-ratio` value. Defaults to the 651x176 box
   * the six series charts are drawn in.
   *
   * A figure destined for a half-width column is drawn TALLER rather than smaller — house rule
   * 3, the type never shrinks — so `VendorUnits` is 651x352 and the two plan figures are
   * 651x244. Every drawing uses `preserveAspectRatio="xMidYMid meet"`, so the wrong box pads
   * instead of cropping; it would just pad the drawing down to a height it was not laid out
   * for, which is the same defect as shrinking the type.
   */
  readonly ratio?: string | undefined;
  readonly options?: readonly SegmentedOption<Gran>[] | undefined;
  readonly gran?: Gran | undefined;
  readonly onGranChange?: ((g: Gran) => void) | undefined;
  readonly children: ReactNode;
}

export function ChartCard({
  title,
  sub,
  cov,
  ratio,
  options,
  gran,
  onGranChange,
  children,
}: ChartCardProps) {
  const toggle =
    options !== undefined && options.length > 0 && gran !== undefined && onGranChange !== undefined;

  return (
    <article className="flex flex-col overflow-hidden rounded-card bg-card px-5 py-[18px]">
      <div className="flex h-[45px] items-start justify-between gap-3">
        <div>
          {/* An h3: the page's group labels are the h2s, so a chart title sits under the
              "Charts" label rather than beside it in the outline. */}
          <h3 className="m-0 text-base font-semibold leading-[1.35] tracking-[-.32px] text-ink-900">
            {title}
            {cov !== undefined && (
              <span className="ml-[6px] whitespace-nowrap rounded-md bg-bg px-[6px] py-[3px] text-[9px] font-bold uppercase tracking-[.06em] text-ink-300">
                {cov}
              </span>
            )}
          </h3>
          <p className="mb-0 mt-[2px] text-xs font-normal leading-[1.3] text-ink-400">{sub}</p>
        </div>
        {toggle && (
          <Segmented
            options={options}
            value={gran}
            onChange={onGranChange}
            variant="tog"
            ariaLabel={`${title} granularity`}
          />
        )}
      </div>

      {/* The figure tracks the drawing's own 651x176 ratio rather than a fixed 176px height.
          Every chart uses preserveAspectRatio="meet", so a box of the wrong ratio does not
          crop — it pads: a fixed 176px height would pin the drawing at natural size and leave
          blank card either side of it once the column is narrower than 691px.
          The card is therefore content-sized, NOT min-h-[257px]: at the design's 691px width
          this box is exactly 651x176 and 18 + 45 + 176 + 18 comes to the mockup's 257, while
          a narrower column shortens the card with the drawing instead of banding it. */}
      <div
        className="w-full [&>svg]:h-full [&>svg]:w-full"
        style={{ aspectRatio: ratio ?? "651 / 176" }}
      >
        {children}
      </div>
    </article>
  );
}
