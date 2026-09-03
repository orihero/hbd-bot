/**
 * THE button definition. One file, four variants, and every button, tab, toggle and pill
 * affordance in the console routes through it.
 *
 * ## Why this file exists
 *
 * It did not, and that was the defect. Before this, "secondary button" was re-typed at every
 * call site, and it had drifted into two mutually exclusive readings of the same design:
 *
 *   - `/assets` "Show the 7-day window", the active `/orders/:id` tab, the nav rail's current
 *     row, every pressed filter toggle — `bg-brand-tint text-brand`, measured
 *     `rgba(189,50,175,0.14)` / `#A92D9D`. This is the language: **a tint of the hue with the
 *     hue as the label.**
 *   - `/orders/:id` "Reveal the brief", `/users/:id` "Reveal this order's brief", the reveal
 *     dialog's "Reveal attempt free text", every INACTIVE tab and toggle —
 *     `bg-surface-control text-ink-muted`, measured `rgb(240,240,243)` / `rgb(99,99,99)`.
 *     Grey on grey. It cleared 5.28:1, so no contrast gate could see it; the design language
 *     says, in as many words, not to do it.
 *
 * The second reading is gone. It is not re-pointed at the brand — that would have collapsed
 * "inactive tab" into "active tab" — it is replaced by `quiet`, the idiom `NavRail` already
 * used for a section the operator is not on: **no ground at all**, `--ink-muted` label, and a
 * `--surface-control` ground that appears only on hover. A dead grey chip becomes no chip.
 *
 * ## The four variants, and the meaning each one keeps
 *
 * | variant     | ground             | label            | what it means                    |
 * | ----------- | ------------------ | ---------------- | -------------------------------- |
 * | `primary`   | `--brand-solid`    | `--ink-on-brand` | the one action this view is for  |
 * | `secondary` | `--brand-tint`     | `--brand`        | an action, or a SELECTED segment |
 * | `danger`    | `--error-tint`     | `--error`        | destructive — same shape, hue of |
 * |             |                    |                  | what the click is about to do    |
 * | `quiet`     | none (hover only)  | `--ink-muted`    | dismissive, or an UNSELECTED     |
 * |             |                    |                  | segment                          |
 *
 * `secondary` and `danger` are the same idiom in two hues, which is the point: a destructive
 * affordance still reads destructive because the hue carries it, not because it is the only
 * button in the row wearing a colour.
 *
 * ## Measured, both palettes, every pair this file can paint
 *
 * WCAG 1.4.3 wants 4.5:1 for text. Every ratio below was computed from the hexes in
 * `tokens.css`, not estimated:
 *
 *   pair                                  light    dark
 *   --ink-on-brand on --brand-solid        4.95     4.95  (--brand-solid is theme-invariant)
 *   --brand on --brand-tint                4.82     4.60
 *   --error on --error-tint                4.71     4.64
 *   --ink-muted on --surface               5.76     7.72  (quiet, on the page ground)
 *   --ink-muted on --surface-card          6.01     7.16  (quiet, on a card)
 *   --ink-muted on --surface-control       5.28     6.60  (quiet, disabled-on-a-control)
 *   --ink-muted on --surface-control-hover 4.87     5.95  (the palette's worst ground)
 *   --ink on --surface-control             7.43    11.13  (quiet, hovered)
 *
 * The lowest number in the table is 4.60:1. Nothing here is marginal, and no variant uses a
 * policed token — `--ink-mark` and `--ink-rule` do not appear, so this file needs no waiver
 * in `src/styles/tokenContrast.test.ts`.
 *
 * ## Disabled
 *
 * `disabled:` strips the ground and steps the label back to `--ink-muted` — `CursorPager`'s
 * idiom, kept and generalised, and its reasoning is worth repeating: losing the button SHAPE
 * is a far louder signal than losing contrast, `--ink-muted` clears 4.87:1 on the worst
 * ground in the palette so a dead label is readable rather than merely present, and no
 * inactive-control exemption has to be claimed for it. `disabled:opacity-50` — which three
 * call sites used on a solid brand fill, taking white-on-magenta to roughly 2.4:1 — is gone.
 *
 * ## Sizes
 *
 * `md` is the design's own button box: `padding: 8px 20px`, `14px/500`, 16px radius. The
 * smaller rungs exist because a toggle strip and a table toolbar are not full-size buttons;
 * they are the same four variants at a smaller box, never a fifth colour scheme.
 */

import { cva, type VariantProps } from "class-variance-authority";

/**
 * Shared by every variant. Radius is NOT here — it belongs to `shape`, so that `cn()`'s
 * `twMerge` never has to resolve two `rounded-*` classes coming out of one `cva` call.
 */
const BUTTON_BASE = [
  "inline-flex shrink-0 items-center justify-center gap-1.5",
  "transition-[background-color,box-shadow,color] duration-fast ease-standard",
  // A dead control loses its ground, not its legibility. See the note above.
  "disabled:cursor-not-allowed disabled:bg-transparent disabled:text-ink-muted",
  "disabled:shadow-none disabled:hover:bg-transparent disabled:hover:shadow-none",
].join(" ");

export const buttonVariants = cva(BUTTON_BASE, {
  variants: {
    variant: {
      /* The one action a view is for. Gogo's `--primary` verbatim under white at 4.95:1. */
      primary: "bg-brand-solid text-ink-on-brand hover:shadow-md-darker",
      /* THE idiom: a tint of the hue with the hue as the label. Also the SELECTED segment. */
      secondary: "bg-brand-tint text-brand hover:shadow-2xs-darker",
      /* The same idiom in the error hue, so destructive still reads destructive. */
      danger: "bg-error-tint text-error hover:shadow-2xs-darker",
      /*
       * Dismissive, or an UNSELECTED segment. No ground until hover — the nav rail's
       * treatment for a section you are not on. This is what replaced grey-on-grey, and it
       * is deliberately NOT branded: an inactive tab beside an active one has to stay
       * visibly inactive.
       */
      quiet: "bg-transparent text-ink-muted hover:bg-surface-control hover:text-ink",
      /*
       * The secondary idiom in a hue chosen at RUNTIME — `LiveFeed`'s severity segments,
       * where the hue is the severity's own family and is not known until render.
       *
       * It paints no colour of its own, so a caller MUST supply both halves of the pair in an
       * inline `style`: `backgroundColor` from an `--x-tint` and `color` from that same
       * family's text-safe `--x`. Every such pair is measured by `tokenContrast.test.ts`,
       * which checks each family's text member against its own tint on both palettes — that
       * is the whole reason this variant hands the job to the token layer instead of
       * inventing a colour here.
       */
      tinted: "hover:shadow-2xs-darker",
    },
    size: {
      /* The design's button box: 8px 20px, 14px/500. */
      md: "text-button px-5 py-2",
      sm: "text-button px-4 py-1.5",
      xs: "type-body-sm px-3 py-1",
      chip: "type-caption px-2.5 py-1",
      /* A square target for an icon-only control — the top bar's row. */
      icon: "h-10 w-10 p-0",
      /*
       * No box at all. For the handful of affordances whose geometry is set by their
       * container — a nav row that is `h-10` and full width, the top bar's zone chip — and
       * which want the VARIANT without the padding. It is the box that is waived here, never
       * the colour pair.
       */
      none: "",
    },
    shape: {
      button: "rounded-button",
      pill: "rounded-pill",
    },
  },
  defaultVariants: { variant: "secondary", size: "md", shape: "button" },
});

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;

/** The variant of a segment in a tab strip, a toggle group or a segmented control. */
export type SegmentVariant = "secondary" | "quiet";

/**
 * The one place the selected/unselected pairing is decided.
 *
 * Selected is the secondary idiom — the brand tint with the brand as the label. Unselected is
 * `quiet`, and that asymmetry is the requirement, not an oversight: if an unselected segment
 * were also branded, "which tab am I on" would be answered by a shade rather than by the
 * presence of colour. Every consumer also carries `aria-selected` or `aria-pressed`, which is
 * the channel that does not depend on seeing either.
 */
export const segmentVariant = (isSelected: boolean): SegmentVariant =>
  isSelected ? "secondary" : "quiet";
