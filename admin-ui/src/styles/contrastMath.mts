/**
 * The contrast arithmetic, extracted so that exactly one implementation of it exists.
 *
 * Every number this repo states about colour — the 144 measured comments in `tokens.css`, the
 * bars in `tokenContrast.test.ts`, the ratios `tools/annotate-tokens.mts` writes — comes out
 * of the five functions below. They lived in the test file until the annotation generator
 * needed them too, and the alternative to extracting them was a second copy in `tools/`.
 *
 * A second copy is not a hypothetical risk here. This file's own history is two shipped
 * incidents caused by a number nobody recomputed (`--fg-2` annotated "4.6:1" while measuring
 * 4.34:1, which licensed 131 sub-AA prose sites), and a generator whose `over()` composited
 * in a slightly different order from the gate's would produce annotations the gate rejects —
 * or, far worse, annotations the gate accepts because both halves are wrong in the same way.
 * The gate and the generator are only a real cross-check of each other while they are
 * arithmetically the SAME program pointed at different jobs.
 *
 * `.mts` and not `.ts`: `tools/annotate-tokens.mts` runs under `tsx` on Node, outside Vite,
 * and the explicit module extension keeps the resolution unambiguous in both worlds.
 *
 * Nothing here reads a file or knows what a palette MEANS. A `Palette` is a flat map of
 * declaration text — the parsing lives in `paletteBlocks.mts`, the roles and bars in
 * `contrastRoles.mts`.
 */

/** One CSS block's declarations, resolved: `{"--ink": "#4d4d4d", "--st-held": "var(--brand)"}`. */
export type Palette = Readonly<Record<string, string>>;

export interface Rgba {
  readonly r: number;
  readonly g: number;
  readonly b: number;
  readonly a: number;
}

/** Resolve a token through any `var()` chain and parse it as `#rgb`/`#rrggbb`/`#rrggbbaa`. */
export function colorOf(palette: Palette, token: string): Rgba {
  let value = palette[token];
  for (let hop = 0; hop < 8 && value !== undefined; hop += 1) {
    const indirection = /^var\((--[\w-]+)\)$/u.exec(value);
    if (indirection === null) break;
    const next = indirection[1];
    if (next === undefined) break;
    value = palette[next];
  }
  if (value === undefined || !value.startsWith("#")) {
    throw new Error(`token ${token} did not resolve to a hex colour (got ${String(value)})`);
  }
  const hex = value.slice(1);
  const pair = (index: number): number => Number.parseInt(hex.slice(index, index + 2), 16);
  if (hex.length === 6) return { r: pair(0), g: pair(2), b: pair(4), a: 1 };
  if (hex.length === 8) return { r: pair(0), g: pair(2), b: pair(4), a: pair(6) / 255 };
  throw new Error(`token ${token} has an unsupported hex length: ${value}`);
}

/** True when a token resolves to a colour at all — the rest are radii, motion and layout. */
export function isColour(palette: Palette, token: string): boolean {
  try {
    colorOf(palette, token);
    return true;
  } catch {
    return false;
  }
}

/** Source-over compositing, so a `-tint` chip is measured against what is really behind it. */
export function over(top: Rgba, bottom: Rgba): Rgba {
  return {
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  };
}

export function relativeLuminance({ r, g, b }: Rgba): number {
  const channel = (raw: number): number => {
    const c = raw / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Straight-line distance in sRGB — "are these two visibly different colours at all". */
export function rgbDistance(a: Rgba, b: Rgba): number {
  return Math.hypot(a.r - b.r, a.g - b.g, a.b - b.b);
}

export function contrast(foreground: Rgba, background: Rgba): number {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * A ground expression is either a token (`--surface-card`) or a tint composited over a base
 * (`--brand-tint over --surface-card`). The second form is the one that matters: the tints
 * are 8-digit hexes and their real contrast depends entirely on what is behind them.
 */
export function ground(palette: Palette, expression: string): Rgba {
  const composed = /^(--[\w-]+) over (--[\w-]+)$/u.exec(expression);
  if (composed !== null) {
    const [, layer, base] = composed;
    if (layer === undefined || base === undefined) throw new Error(`bad ground ${expression}`);
    return over(colorOf(palette, layer), colorOf(palette, base));
  }
  return colorOf(palette, expression);
}

/** Contrast of a token against a ground expression, with alpha composited both sides. */
export function ratioOn(palette: Palette, token: string, expression: string): number {
  const behind = ground(palette, expression);
  return contrast(over(colorOf(palette, token), behind), behind);
}
