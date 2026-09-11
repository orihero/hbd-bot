/**
 * §11.2, and this is the sentence the component exists for:
 *
 * > env badge (`dev` slate / `staging` amber / **`prod` with a glow ring**) — **an operator
 * > must never be unsure which database they are looking at**.
 *
 * The failure it prevents is a retry, a block or a purge executed against production while
 * the operator believed they were in staging.
 *
 * ## Why prod is no longer a ring, and no longer brand-coloured
 *
 * The reskin kept a ring and painted it in the BRAND hue. That was a safety regression, not a
 * style choice, and it is worth stating precisely why: in this palette the brand magenta is
 * AMBIENT. It is the active nav pill, every link, every order ref, the active tab, the
 * pressed state of every filter toggle and the ground of every secondary button. A pale
 * magenta chip with a magenta ring, in a console full of pale magenta, is technically
 * distinguishable from dev — three channels differ, and the old test proved it — and
 * completely fails to LEAP OUT, which is the entire function of the affordance. "Can an
 * operator tell these apart if they stop and compare?" is the wrong question. The question is
 * "does the wrong one catch their eye before they click retry?"
 *
 * So prod is the one chip in this console that is allowed to be loud, and it is loud in the
 * one way the rest of the console is not:
 *
 *  1. **It is SOLID, and it is inverted.** Every other chip in the console — every status
 *     pill, every environment below this one, every filter chip — is a pale `--x-tint` ground
 *     under a dark `--ink` label in the light theme, and a dark tint under a light label in
 *     dark. Prod is the opposite in BOTH themes: a saturated `--error` ground carrying
 *     `--surface-card` as its label. Nothing else in the chrome does that, so it does not
 *     compete with anything.
 *  2. **The hue is `--error`, not the brand.** Red is not decoration here: the title says
 *     every write reaches a real customer, and the chip should say the same thing before the
 *     title is hovered. It is also the one semantic hue that carries no ambient chrome role.
 *  3. **The glyph differs per environment**, so the badge does not depend on colour at all.
 *
 * ## Three channels, and every one of them survives greyscale
 *
 * §11.3's "never colour alone" applies hardest here, and "three distinguishing channels"
 * cannot mean three channels that are all hue:
 *
 *  | channel   | dev            | staging          | prod                          |
 *  | --------- | -------------- | ---------------- | ----------------------------- |
 *  | the WORD  | `dev`          | `staging`        | `prod`                        |
 *  | the GLYPH | `●` a dot      | `◆` a diamond    | `▲` a warning triangle        |
 *  | LUMINANCE | pale tint,     | pale tint,       | SOLID fill, INVERTED label —  |
 *  |           | dark label     | dark label       | the polarity flips            |
 *
 * Take the colour away entirely and prod is still the only chip whose ground and label have
 * swapped ends of the scale. That is what makes this robust rather than merely different: a
 * projector, a greyscale screenshot and a colour-blind operator all still see it.
 *
 * Quiet · intermediate · loud is deliberately an ORDERING, not three equal options. `dev`
 * takes the true grey and the plainest glyph, `staging` takes caution amber and a shape that
 * reads as "careful", and only prod inverts.
 *
 * ## Measured
 *
 *   variant   ground             label              light    dark
 *   dev       --neutral-tint     --ink              7.10     9.62
 *   staging   --caution-tint     --ink              7.22     7.97
 *   prod      --error            --surface-card     5.72     5.68
 *   unknown   --surface-control  --ink              7.43    11.13
 *
 * Prod's pair is the one this file introduces, and it is measured on both palettes because
 * `--error` moves between them: `#ffffff` on `#c02a4b` is 5.72:1 in light, and `#26262a` on
 * `#e38297` is 5.68:1 in dark. Both clear 1.4.3's 4.5:1 for the 11px label with room to
 * spare, and `text-surface-card` flips with the theme by construction — the light label in
 * light mode and the dark label in dark mode are the same token.
 *
 * ## Unknown is a state, not a default
 *
 * If `/api/config` has not answered — or answered `CAPABILITY_DISABLED`, which it does when
 * `BAYRAM_ADMIN_CONFIG_ENABLED` is off — the badge says so. Falling back to `dev` would be a
 * confident lie in exactly the situation the badge exists to prevent.
 */

import type { AdminEnvironment } from "@/api";
import { cn } from "@/lib/utils";

export interface EnvBadgeProps {
  /** `ConfigView.environment`, or `null` while unknown. */
  readonly environment: AdminEnvironment | null;
  readonly className?: string;
}

interface Variant {
  readonly label: string;
  /** The chip's ground AND its label, together — the two are one decision. */
  readonly chip: string;
  /** A shape, not a colour: the badge has to read in greyscale. */
  readonly glyph: string;
  readonly outline: string;
  readonly title: string;
}

const VARIANTS: Readonly<Record<AdminEnvironment, Variant>> = {
  dev: {
    label: "dev",
    // The quietest thing in the top bar: the true grey, and `--ink` at 6.61:1 over it.
    chip: "bg-neutral-tint text-ink",
    glyph: "●",
    outline: "",
    title: "Development database. Safe to poke.",
  },
  staging: {
    label: "staging",
    // Intermediate: caution amber, still a pale tint under a dark label.
    chip: "bg-caution-tint text-ink",
    glyph: "◆",
    outline: "",
    title: "Staging database. Real shape, fake people.",
  },
  prod: {
    label: "prod",
    /*
     * The loud one, and the only inverted chip in the console: a SOLID `--error` ground
     * carrying `--surface-card` as its label — 5.72:1 in light, 5.68:1 in dark. `--error`
     * rather than the brand because the brand hue is ambient chrome in this palette; a
     * brand-tinted prod chip sits in a console full of brand tint and stops registering.
     */
    chip: "bg-error text-surface-card",
    glyph: "▲",
    // Heavier than the 600 the caption scale sets, so the word itself is louder too.
    outline: "font-bold",
    title: "PRODUCTION database. Every write here reaches a real customer.",
  },
};

const UNKNOWN: Variant = {
  label: "env unknown",
  chip: "bg-surface-control text-ink",
  glyph: "?",
  // Dashed, because "we do not know" should not look like a fourth environment. This is a
  // decorative outline on a chip that is already carrying its own ground, which is what
  // `--hairline-strong` is for.
  outline: "border border-dashed border-hairline-strong",
  title:
    "The console could not read /api/config, so it does not know which database this is. " +
    "Do not assume.",
};

export function EnvBadge({ environment, className }: EnvBadgeProps) {
  const variant = environment === null ? UNKNOWN : VARIANTS[environment];
  return (
    <span
      title={variant.title}
      data-environment={environment ?? "unknown"}
      className={cn(
        "type-caption inline-flex shrink-0 items-center gap-1.5 rounded-pill px-3 py-1",
        variant.chip,
        variant.outline,
        className,
      )}
    >
      {/* The glyph takes the chip's own label colour — one pair to measure, not two. */}
      <span aria-hidden="true" className="leading-none">
        {variant.glyph}
      </span>
      <span className="sr-only">Environment:</span>
      <span>{variant.label}</span>
    </span>
  );
}
