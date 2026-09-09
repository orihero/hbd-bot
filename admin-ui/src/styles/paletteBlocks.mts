/**
 * `tokens.css` as a data structure: the theme cells, the block grammar, and the
 * annotation grammar.
 *
 * This is the third of the three modules `tokenContrast.test.ts` and
 * `tools/annotate-tokens.mts` share, and it is the one the plan does not name — it exists
 * because "which blocks are there, and what does each declare" turned out to be neither
 * arithmetic (`contrastMath.mts`) nor meaning (`contrastRoles.mts`), and because a generator
 * that parsed the stylesheet its own way could write a comment into a block the gate reads
 * as a different block. Both halves of that sentence are the same failure: an annotation
 * measured in one cell and written into another, with every assertion green.
 *
 * Every function here takes the stylesheet TEXT rather than reading the file. The gate reads
 * it once from the Vitest root; the generator reads it, rewrites it and re-reads its own
 * output to prove the rewrite converged. Neither can be expressed by a module that owns the
 * `readFileSync` itself, and a module that did would also be unimportable from the jsdom
 * environment, where `import.meta.url` is an `http://` URL.
 *
 * ## One axis, stated once
 *
 * Colour varies on `data-theme` alone, and LIGHT IS HOME: the default is the ABSENCE of the
 * attribute, so `:root` is the light cell and it is also the only place the theme-INVARIANT
 * half of the file lives. Getting that polarity the wrong way round fails nothing on its own
 * — it silently measures the right numbers against the wrong grounds and stays green — which
 * is why `tokenContrast.test.ts` asserts it rather than assuming it.
 *
 * This module briefly carried a second axis, `data-palette`, so `gogo` and `planiq` could
 * ship side by side. That was removed when the console committed to `planiq` outright. Two
 * things the axis left behind are why this file still exists rather than folding back into
 * the gate: the anchored `blockRange`, and the invariant/colour split that composes each cell
 * from the INVARIANT half rather than from all of `:root`, so an incomplete block fails
 * loudly instead of inheriting silently. Both earned their place by catching real defects.
 */

import { type Palette } from "./contrastMath.mts";

/** The theme axis. `light` is the absence of its attribute — light is home. */
export const THEMES = ["light", "dark"] as const;

/** The selector carrying one cell. `light` has no attribute at all, so it is `:root`. */
export function selectorFor(theme: string): string {
  return theme === "light" ? ":root" : `[data-theme="${theme}"]`;
}

/**
 * `[` `]` `(` `)` `^` `{` `|` are all regex metacharacters and all appear in an attribute
 * selector. `RegExp.escape` would do this, but it is Node 24 and `package.json` declares
 * `"engines": {"node": ">=20.19"}`.
 */
export const escapeForRegExp = (literal: string): string =>
  literal.replace(/[$()*+.?[\\\]^{|}]/gu, "\\$&");

/**
 * Where one selector's block starts and ends in the stylesheet text: `[start, end)`, from the
 * `s` of the selector to the newline before its closing brace.
 *
 * The opening line must be EXACTLY `<selector> {`, at column 0, and must occur exactly once.
 * A plain `indexOf(selector + " {")` is a substring match, and a substring match over CSS
 * selectors is a trap that pays out the moment anyone adds a compound block. While the
 * two-palette axis existed it did exactly that: `[data-theme="dark"] {` is a SUBSTRING of
 * `[data-palette="planiq"][data-theme="dark"] {`, so `indexOf` handed back whichever the file
 * wrote first for BOTH — one cell measured against another cell's hexes, every assertion in
 * the gate green while it happened. The axis is gone; the anchoring stays, because the next
 * compound block will not announce itself either. It also keeps `:root` from ever resolving
 * to the indented `:root` inside the reduced-motion `@media`.
 *
 * Zero matches and two matches are both errors, and both name what went wrong rather than
 * returning a plausible block. In the gate this throws at module load, so a mis-written
 * selector takes the whole file to nothing rather than to a smaller green number — which is
 * the correct failure for a file whose entire job is to be the thing that cannot be evaded.
 */
export function blockRange(css: string, selector: string): readonly [number, number] {
  const openings = [...css.matchAll(new RegExp(`^${escapeForRegExp(selector)} \\{$`, "gmu"))];
  if (openings.length !== 1) {
    throw new Error(
      `tokens.css must contain exactly one \`${selector} {\` line at column 0; found ` +
        `${String(openings.length)}. A palette block is addressed by the exact text of its ` +
        `opening line, so that line has to be written once, canonically: one selector, no ` +
        `comma, one space before the brace.`,
    );
  }
  const start = openings[0]?.index ?? 0;
  return [start, css.indexOf("\n}", start)];
}

/** Pull one selector's declarations out of the stylesheet, as text. */
export function blockBody(css: string, selector: string): string {
  const [start, end] = blockRange(css, selector);
  return css.slice(start, end);
}

/** …and as a map. Later declarations of a name win, exactly as the cascade would resolve them. */
export function block(css: string, selector: string): Palette {
  const out: Record<string, string> = {};
  for (const match of blockBody(css, selector).matchAll(/(--[\w-]+):\s*([^;]+);/gu)) {
    const [, name, value] = match;
    if (name !== undefined && value !== undefined) out[name] = value.trim();
  }
  return out;
}

/**
 * A declaration carries a COLOUR value when it states a literal colour of its own: a hex, or
 * an elevation string built out of one. Everything else in `:root` is theme-INVARIANT — a
 * `var()` alias saying what a colour MEANS (`--st-held: var(--brand)`), or a radius,
 * duration, easing or length with no colour in it at all.
 *
 * `^var\(` and not "mentions var(": `--shadow-overlay: 0 0 0 1px var(--edge), 0px 3px 28px
 * #0000008a` is a colour value that legitimately reaches for its own theme's `--edge` and
 * that every block must restate. Conversely `--shadow-card: var(--shadow-xs)` is an alias and
 * belongs to nobody's theme. Classifying by VALUE and not by NAME is deliberate: the
 * name-prefix form of this rule misses `--topbar-h` and `--gutter`, which carry no prefix any
 * list would have thought to include.
 */
export function isPaletteValue(value: string): boolean {
  return !value.startsWith("var(") && value.includes("#");
}

export interface Cell {
  readonly theme: string;
  /** `light` / `dark` — the label every per-cell test name and every drift report carries. */
  readonly label: string;
  readonly selector: string;
  /** The invariant half of `:root`, with this block's own colour declarations over it. */
  readonly tokens: Palette;
}

export interface Stylesheet {
  /** `:root`, as declared — both halves of it. */
  readonly root: Palette;
  /**
   * The half of `:root` no theme block may touch: the `var()` aliases and the non-colour
   * tokens. Every cell is its own colour declarations laid over exactly this.
   *
   * Composing a cell from the INVARIANT half rather than from all of `:root` is the whole
   * point of the shape. Spreading all of `:root` would model the cascade correctly for a
   * COMPLETE block and paper over an incomplete one — and papering over an incomplete block
   * is precisely the failure §2.0.3 is about. So the composition is itself an enforcement of
   * completeness, independent of the parity assertion in the gate, and it is what turned the
   * two dark declarations that used to be missing from silent inheritance into two loud
   * failures the first time it ran.
   */
  readonly invariant: Palette;
  /** Every name a theme block must declare — computed from `:root`, never hand-listed. */
  readonly paletteKeys: readonly string[];
  /** Every cell: one per theme. */
  readonly cells: readonly Cell[];
  /** Every cell written as its own block — the cells minus the unattributed default. */
  readonly blocks: readonly Cell[];
}

/** Parse the whole stylesheet into its cells. */
export function readStylesheet(css: string): Stylesheet {
  const root = block(css, ":root");
  const invariant: Palette = Object.fromEntries(
    Object.entries(root).filter(([, value]) => !isPaletteValue(value)),
  );
  const paletteKeys = Object.entries(root)
    .filter(([, value]) => isPaletteValue(value))
    .map(([token]) => token)
    .sort();
  const cells: readonly Cell[] = THEMES.map((theme): Cell => {
    const selector = selectorFor(theme);
    return { theme, label: theme, selector, tokens: { ...invariant, ...block(css, selector) } };
  });
  return {
    root,
    invariant,
    paletteKeys,
    cells,
    blocks: cells.filter((cell) => cell.selector !== ":root"),
  };
}

/**
 * The annotation grammar `tokens.css` commits to, stated once:
 *
 *     --token: #hex;  /· N.NN:1 on <ground> — role ·/
 *     --token: #hex;  /· N.NN:1 at best on <ground> — role ·/
 *
 * `on` claims the token's WORST ground; `at best on` claims its BEST, and is what an `exempt`
 * token uses because its whole claim is a ceiling.
 *
 * One regex, read by the gate and written by the generator, because a grammar with two
 * implementations is a generator that can emit comments the gate cannot see. The match
 * deliberately ENDS at the em dash: everything after it is role prose a human wrote, and
 * `annotate-tokens.mts` rewrites only what this regex covers.
 */
export const ANNOTATION =
  /(--[\w-]+):\s*(#[\da-f]{6,8});\s*\/\* (\d+\.\d\d):1 (at best )?on (--[\w-]+(?: over --[\w-]+)?) —/gu;

export interface Annotation {
  readonly token: string;
  readonly claimed: number;
  readonly best: boolean;
  readonly namedGround: string;
}

/**
 * The annotations written inside ONE block.
 *
 * Scoped to the block on purpose: a value carried by a cell but declared in another block has
 * no annotation here to be checked against, which is one more reason every block is required
 * to be complete in all of its colour names.
 */
export function annotationsIn(css: string, selector: string): readonly Annotation[] {
  return [...blockBody(css, selector).matchAll(ANNOTATION)].map((match) => {
    const [, token, , claimed, best, namedGround] = match;
    if (token === undefined || claimed === undefined || namedGround === undefined) {
      throw new Error(`unparsable annotation: ${match[0]}`);
    }
    return { token, claimed: Number(claimed), best: best !== undefined, namedGround };
  });
}
