/**
 * `/vendors`' one filter control: the vendor toggles.
 *
 * §11.4's inventory names `FilterBar` but no controls to put inside it, so — like
 * `/generations` and `/users` — this screen brings its own, built from the one button
 * definition (`Button` + `segmentVariant`) rather than from a hand-rolled `bg-…`/`text-…`
 * pair. Selected is the secondary idiom, unselected is `quiet`, and `aria-pressed` carries
 * the state for anyone who sees neither.
 *
 * There is deliberately NO sort control and no operation filter. No `/metrics/vendor-*`
 * route accepts either: a sort parameter would be silently ignored (contract D2 — the worst
 * kind of refusal, because the operator gets an order they did not ask for and nothing says
 * so), and the operation dimension is a COLUMN of the rollup rather than a query parameter,
 * so narrowing to it in the browser would leave the totals above describing a wider
 * population than the table below.
 *
 * This is a third copy of the toggle-group shape, and that is a conscious cost: if a fourth
 * screen needs it, the answer is a shared primitive under `components/data/`, never a
 * cross-feature import from here.
 */

import type { ReactElement } from "react";

import type { Vendor } from "@/api";
import { Button, segmentVariant } from "@/components/util";
import { humaniseEnum } from "@/lib";

export interface VendorTogglesProps {
  /** Our own closed vocabulary, in declaration order. */
  readonly values: readonly Vendor[];
  readonly selected: readonly Vendor[] | undefined;
  /** Emits `undefined` when the last chip is turned off, so the parameter is DROPPED — an
   *  empty `?vendor=` is a 422, and "none selected" means no filter, never "match none". */
  readonly onChange: (next: readonly Vendor[] | undefined) => void;
  readonly label?: string;
}

export function VendorToggles({
  values,
  selected,
  onChange,
  label = "vendor",
}: VendorTogglesProps): ReactElement {
  const active = selected ?? [];
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1">
      {/* `type-body-sm`, not `type-caption`: the caption scale uppercases, and this label
          sits in the same bar as the time picker's, which does not. */}
      <span className="type-body-sm text-ink-muted">{label}</span>
      {values.map((vendor) => {
        const isActive = active.includes(vendor);
        return (
          <Button
            key={vendor}
            variant={segmentVariant(isActive)}
            size="xs"
            shape="pill"
            aria-pressed={isActive}
            data-vendor={vendor}
            onClick={() => {
              const next = isActive
                ? active.filter((member) => member !== vendor)
                : [...active, vendor];
              onChange(next.length === 0 ? undefined : next);
            }}
          >
            {humaniseEnum(vendor)}
          </Button>
        );
      })}
    </div>
  );
}
