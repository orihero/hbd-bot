/**
 * `<OrderRefChip>` — a link to an order, wherever one is mentioned.
 *
 * Every screen that names an order (the live feed, the audit log, an attempt row, a user's
 * history) links to it through this component, so the href is built by `href.order()` and
 * never spelled by hand. §11.2's route params are camelCase (`/orders/:orderId`) and the
 * SERVER's are snake_case; that difference is a real trap and the `href` builder is where
 * it is settled once.
 *
 * The uuid is truncated for display and carried whole in the title and the link, for the
 * same reason `<CorrelationChip>` copies all thirty-two characters: a truncated identifier
 * that looks copyable is worse than one that does not.
 */

import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import { cn, type StatusGlyphKey } from "@/lib";
import { href } from "@/routes";

import { StatusPill } from "./StatusPill";

export interface OrderRefChipProps {
  orderId: string;
  /** Renders a glyph-only pill beside the id when the surface knows the state. */
  state?: StatusGlyphKey | null | undefined;
  /** How much of the uuid to show. The first segment is enough to recognise a row. */
  visibleChars?: number | undefined;
  className?: string | undefined;
}

export function OrderRefChip({
  orderId,
  state,
  visibleChars = 8,
  className,
}: OrderRefChipProps): ReactElement {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      {state === null || state === undefined ? null : <StatusPill state={state} isGlyphOnly />}
      <Link
        to={href.order(orderId)}
        data-testid="order-ref-chip"
        data-order-id={orderId}
        title={orderId}
        className={cn(
          // A link, so it keeps the hue as its text colour: `--brand` is the link hue in
          // this language (4.63:1 at its worst in light, 4.58:1 in dark) and an order
          // reference is the one thing on the row that navigates.
          "type-mono rounded-pill px-1.5 py-0.5 text-brand",
          "transition-colors duration-fast ease-standard hover:bg-brand-tint",
        )}
      >
        {orderId.slice(0, visibleChars)}
      </Link>
    </span>
  );
}
