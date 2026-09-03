/**
 * WCAG contrast, on BOTH palettes — §14's Slice 1d acceptance names it as a gate, not a
 * nicety. Rewritten for the Gogo palette (plan §11.3 as amended 2026-09-03), which is
 * LIGHT-FIRST and names its tokens by role.
 *
 * `vitest.config.ts` sets `css: false`, so no rendering test in this suite can ever see a
 * real colour — jsdom gets class strings and inline `var()` text and nothing else. A green
 * suite therefore proves nothing at all about legibility unless some file reads the
 * stylesheet as text and does the arithmetic. This is that file. It does four things, and
 * each of the last three is what makes the one before it honest:
 *
 *  1. **A ROLES table.** Every colour token in `tokens.css` is declared with the bar it has
 *     to clear and the complete set of grounds it may legally sit on, and is measured
 *     against every one of them on both palettes. The grounds are computed, including
 *     translucent tints composited over their real backing surface, because a chip's
 *     contrast depends on what is behind it.
 *  2. **A completeness check.** Every token in `tokens.css` that resolves to a colour must
 *     appear either in `ROLES` or in `GROUNDS` with a stated reason. A new token cannot be
 *     added without deciding, in this file, what bar it has to clear. The previous version
 *     of this file used a hand-written `PAIRS` list, which could only assert what its author
 *     remembered to list — and what its author forgot was the 4.5:1 text bar on `--fg-2`,
 *     which is how 131 sub-AA prose sites shipped green.
 *  3. **A comment cross-check.** `tokens.css` annotates each colour with a measured ratio
 *     and the ground it was measured on. Every one of those claims is recomputed here, AND
 *     the named ground is required to be the WORST ground in that token's role (or the best,
 *     for the `at best on` form used by tokens that must clear no bar). A comment cannot
 *     claim a flattering surface, and it cannot claim a number nobody measured. §11.3 shipped
 *     four wrong ratios and one of them — `--fg-2` annotated "4.6:1 — floor for real text"
 *     when it was 4.34:1 — licensed the incident above. This is the assertion that stops the
 *     next palette doing it again.
 *  4. **A source scan.** `src/**` is walked for every use of the two POLICED tokens,
 *     `--ink-mark` and `--ink-rule`, and each site is measured at the bar its own usage
 *     earns: TEXT, unless it carries a waiver here saying why it is a mark, a rule or an
 *     inactive control — and the waiver's claim is checked against the source. The walk
 *     reads `.css` as well as `.ts`/`.tsx`: ESLint's copy of this rule parses TypeScript and
 *     cannot see `scrollbar-color: var(--ink-mark)` in `index.css`, so the measuring half
 *     covers what the fast half cannot.
 *
 * Four thresholds, per WCAG 2.1:
 *
 *  - **4.5:1** — text (1.4.3). The console's reading sizes are 11–14px, so this is the
 *    default bar for anything made of characters.
 *  - **3:1** — large-scale text (1.4.3): ≥24px, or ≥18.66px bold. `.type-metric` (28px/700)
 *    and `.type-hero` (40px/700) qualify.
 *  - **3:1** — a graphical object that carries meaning without being text (1.4.11): the
 *    status dot beside a word that says the same thing, a chart series, a scrollbar thumb.
 *  - **no bar at all** — 1.4.3 exempts text in an INACTIVE user-interface component, and
 *    1.4.11 exempts decoration that carries nothing the words do not. An `"exempt"` role
 *    asserts no floor; what it asserts is a CEILING, so that a token declared "never text"
 *    cannot quietly become readable enough for somebody to use it as text.
 *
 * ## The four facts the components are written around
 *
 *  1. **`--ink` and `--ink-muted` are the only two tokens that may paint a character.** Both
 *     clear 4.5:1 on all five surfaces of both palettes AND on all nine tints composited over
 *     the card and over the page ground — which is where a status pill puts its word.
 *  2. **`--ink-mark` is a MARK colour and can never be text.** Its best ground in one palette
 *     is readable, but a surface-agnostic component does not know which ground it landed on,
 *     so the bar is worst-case: 3.52:1 globally, above 1.4.11's 3:1 and below 1.4.3's 4.5:1
 *     everywhere it matters.
 *  3. **`--ink-rule` clears no bar at all**, in either palette, on any ground: 2.71:1 at its
 *     ceiling. It may paint a rule, a hairline or a dead control and nothing else.
 *  4. **Cards have no border in this design, so "the border is not the boundary" is not a
 *     hypothesis about `--hairline` — it is the premise.** `--hairline` is 1.45:1 at best.
 *     What separates a card from the ground is `--surface-card` against `--surface` plus
 *     `--shadow-card`, and the assertion at the bottom of this file is that those two
 *     surfaces really are different colours in both palettes. The one border that carries
 *     meaning, a floating popover's ring, is `--edge`, and it is measured at 3:1.
 */

import { readdirSync, readFileSync } from "node:fs";
import { resolve, sep } from "node:path";

import { describe, expect, it } from "vitest";

// Resolved from the Vitest root (`admin-ui/`), not from `import.meta.url`: under the jsdom
// environment `import.meta.url` is an `http://` URL and `fileURLToPath` rejects it.
const SRC_DIR = resolve(process.cwd(), "src");
const TOKENS_CSS = readFileSync(resolve(SRC_DIR, "styles/tokens.css"), "utf8");

type Palette = Readonly<Record<string, string>>;

/** Pull one selector's declarations out of the stylesheet. */
function blockBody(selector: string): string {
  const start = TOKENS_CSS.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block in tokens.css`);
  const end = TOKENS_CSS.indexOf("\n}", start);
  return TOKENS_CSS.slice(start, end);
}

function block(selector: string): Palette {
  const out: Record<string, string> = {};
  for (const match of blockBody(selector).matchAll(/(--[\w-]+):\s*([^;]+);/gu)) {
    const [, name, value] = match;
    if (name !== undefined && value !== undefined) out[name] = value.trim();
  }
  return out;
}

/*
 * LIGHT IS HOME. `:root` is the light palette and `[data-theme="dark"]` overrides only what
 * changes — the reverse of the previous design, whose header said "dark is home". Getting
 * these two lines the wrong way round does not fail anything: it silently measures the right
 * numbers against the wrong grounds and stays green, which is why they are called out here.
 */
const LIGHT = block(":root");
const DARK: Palette = { ...LIGHT, ...block('[data-theme="dark"]') };
const PALETTES = [
  ["light", LIGHT],
  ["dark", DARK],
] as const;

/** Every ground a surface-agnostic component can be dropped onto. */
const SURFACES = [
  "--surface",
  "--surface-card",
  "--surface-sunken",
  "--surface-control",
  "--surface-control-hover",
] as const;

/** The nine semantic hue families, each with a `--x` / `--x-fill` / `--x-tint` trio. */
const FAMILIES = [
  "brand",
  "accent",
  "success",
  "caution",
  "warning",
  "error",
  "info",
  "neutral",
  "slate",
] as const;

const ORDER_STATES = [
  "draft",
  "brief-ready",
  "lyrics-ready",
  "authorized",
  "generating",
  "delivered",
  "failed",
  "cancelled",
  "held",
] as const;

const PIPELINE_STATUSES = [
  "started",
  "retrying",
  "succeeded",
  "degraded",
  "failed",
  "skipped",
] as const;

interface Rgba {
  readonly r: number;
  readonly g: number;
  readonly b: number;
  readonly a: number;
}

/** Resolve a token through any `var()` chain and parse it as `#rgb`/`#rrggbb`/`#rrggbbaa`. */
function colorOf(palette: Palette, token: string): Rgba {
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
function isColour(palette: Palette, token: string): boolean {
  try {
    colorOf(palette, token);
    return true;
  } catch {
    return false;
  }
}

/** Source-over compositing, so a `-tint` chip is measured against what is really behind it. */
function over(top: Rgba, bottom: Rgba): Rgba {
  return {
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  };
}

function relativeLuminance({ r, g, b }: Rgba): number {
  const channel = (raw: number): number => {
    const c = raw / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Straight-line distance in sRGB — "are these two visibly different colours at all". */
function rgbDistance(a: Rgba, b: Rgba): number {
  return Math.hypot(a.r - b.r, a.g - b.g, a.b - b.b);
}

function contrast(foreground: Rgba, background: Rgba): number {
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
function ground(palette: Palette, expression: string): Rgba {
  const composed = /^(--[\w-]+) over (--[\w-]+)$/u.exec(expression);
  if (composed !== null) {
    const [, layer, base] = composed;
    if (layer === undefined || base === undefined) throw new Error(`bad ground ${expression}`);
    return over(colorOf(palette, layer), colorOf(palette, base));
  }
  return colorOf(palette, expression);
}

/** Contrast of a token against a ground expression, with alpha composited both sides. */
function ratioOn(palette: Palette, token: string, expression: string): number {
  const behind = ground(palette, expression);
  return contrast(over(colorOf(palette, token), behind), behind);
}

/**
 * `text` → 4.5:1 (1.4.3). `large-text` → 3:1 (1.4.3, ≥24px or ≥18.66px bold). `graphic` →
 * 3:1 (1.4.11). `exempt` → no floor: 1.4.3 exempts an inactive control and 1.4.11 exempts
 * decoration, so what an exempt role asserts is a CEILING and, at a site, its EVIDENCE.
 */
type Bar = "text" | "large-text" | "graphic" | "exempt";

const THRESHOLD = {
  text: 4.5,
  "large-text": 3,
  graphic: 3,
  exempt: 0,
} as const satisfies Record<Bar, number>;

/* ------------------------------------------------------------------------------------- *
 * The ROLES table: every colour token, the bar it must clear, and every ground it may
 * legally sit on.
 * ------------------------------------------------------------------------------------- */

interface Role {
  /** The floor this token must clear on every one of its grounds, in both palettes. */
  readonly bar: Bar;
  /** Every ground expression this token may be painted on. */
  readonly grounds: readonly string[];
  /**
   * An upper bound, asserted per palette. Only for `exempt` tokens: a token documented as
   * "never text" that quietly became readable would invite exactly the misuse the role
   * exists to prevent.
   */
  readonly ceiling?: number;
  /** What this token is for, in one line — quoted in failure messages. */
  readonly what: string;
}

/*
 * A tint over EVERY surface it can actually be dropped onto — all five, not the two this
 * list used to carry.
 *
 * The two-ground version was a real measurement hole, and three separate reskin passes
 * walked into it independently. A `-tint` is translucent, so the ratio a chip really
 * achieves depends on what is behind it, and a tinted chip is not confined to the page and
 * the card: `DataTable` hovers a row to `--surface-control-hover`, `AttentionList` hovers
 * to `--surface-control`, and `CodeBlock`/`JsonViewer`/`CommandPalette` are `--surface-
 * sunken` wells. Every one of those grounds is darker than the card in the light palette,
 * so every one of them LOWERS the ratio of a hue painted on its own tint — and none of the
 * three was measured. The suite stayed green while `--error` on `--error-tint` on a hovered
 * table row sat at 3.90:1, below the 4.5:1 text bar, in shipped components.
 *
 * Widening this list is what lets the suite see that class of failure at all. It is
 * deliberately the FULL surface set rather than a curated one: a curated list is how the
 * hole got here, and "which surfaces may a chip land on" is not a question a token author
 * can answer for every component that will ever exist.
 */
const tintGrounds = (family: string): readonly string[] =>
  SURFACES.map((surface) => `--${family}-tint over ${surface}`);

/** Every tint of every family — the full ground set for the ink tokens. */
const ALL_TINT_GROUNDS: readonly string[] = FAMILIES.flatMap((family) => tintGrounds(family));

/** A `--x` / `--x-fill` / `--x-tint` trio, wherever it appears (families, states, statuses). */
function trio(token: string, what: string): Record<string, Role> {
  return {
    [`--${token}`]: {
      bar: "text",
      grounds: [...SURFACES, ...tintGrounds(token)],
      what: `${what} — text-safe member: a word may be painted with it`,
    },
    [`--${token}-fill`]: {
      bar: "graphic",
      grounds: SURFACES,
      what: `${what} — graphic member: dots, strokes, bars, never a character`,
    },
  };
}

const ROLES: Readonly<Record<string, Role>> = {
  "--ink": {
    bar: "text",
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "all prose and headings, and the word inside every tinted chip",
  },
  "--ink-muted": {
    bar: "text",
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "the one muted TEXT colour — descriptions, axis ticks, breadcrumbs",
  },
  "--ink-mark": {
    bar: "graphic",
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "marks and glyphs only — POLICED, never a character",
  },
  "--ink-rule": {
    bar: "exempt",
    ceiling: 3,
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "rules and inactive controls only — POLICED, clears no bar anywhere",
  },
  "--ink-on-brand": {
    bar: "text",
    grounds: ["--brand-solid"],
    what: "the label on a primary button",
  },
  "--brand-solid": {
    bar: "text",
    grounds: ["--ink-on-brand"],
    what: "Gogo's --primary verbatim, as the primary-button fill",
  },
  "--edge": {
    bar: "graphic",
    grounds: ["--surface", "--surface-card"],
    what: "the one border that carries meaning: a floating popover's boundary ring",
  },
  "--focus-ring": {
    bar: "graphic",
    grounds: SURFACES,
    what: "the :focus-visible outline, which is a UI-component boundary",
  },
  "--hairline": {
    bar: "exempt",
    ceiling: 3,
    grounds: SURFACES,
    what: "a decorative rule between dense rows — never the boundary of a control",
  },
  "--hairline-strong": {
    bar: "exempt",
    ceiling: 3,
    grounds: SURFACES,
    what: "a firmer decorative rule — still never the only thing identifying a control",
  },
  ...Object.assign(
    {},
    ...FAMILIES.map((family) => trio(family, `the ${family} family`)),
    ...ORDER_STATES.map((state) => trio(`st-${state}`, `order state ${state}`)),
    ...PIPELINE_STATUSES.map((status) => trio(`pg-${status}`, `pipeline status ${status}`)),
    trio("retryable", "the ↻ retryable error class"),
    trio("terminal", "the ■ terminal error class"),
  ),
  ...Object.fromEntries(
    [1, 2, 3, 4, 5, 6, 7, 8].map((slot) => [
      `--c-${String(slot)}`,
      {
        bar: "graphic",
        grounds: SURFACES,
        what: `categorical chart series ${String(slot)} — graphic only, never text`,
      } satisfies Role,
    ]),
  ),
};

/**
 * Colour tokens that are GROUNDS or ramp stops rather than foregrounds, each with the reason
 * it carries no bar of its own. Everything in `tokens.css` that resolves to a colour must be
 * in here or in `ROLES`; the completeness test below is what makes that true.
 */
const GROUNDS: Readonly<Record<string, string>> = {
  "--surface": "the page ground; measured as the BACKGROUND of every text token",
  "--surface-card": "every card, panel, rail and dialog",
  "--surface-sunken": "an inset well: code blocks, JSON viewers, the palette list",
  "--surface-control": "the ground a control carries instead of a border",
  "--surface-control-hover": "hover for a control and for a table row",
  "--surface-nav": "alias of --surface-card, so the rail names itself",
  "--surface-topbar": "alias of --surface-card, so the top bar names itself",
  ...Object.fromEntries(
    [
      ...FAMILIES,
      ...ORDER_STATES.map((state) => `st-${state}`),
      ...PIPELINE_STATUSES.map((status) => `pg-${status}`),
      "retryable",
      "terminal",
    ].map((token) => [
      `--${token}-tint`,
      "a chip/pill ground; measured under --ink, --ink-muted and its own family's text member",
    ]),
  ),
  "--seq-from": "sequential ramp stop — a FILL, always beside a legend or a value label",
  "--seq-to": "sequential ramp stop — a FILL, always beside a legend or a value label",
  "--div-low": "diverging ramp stop; aliases --error-fill, which is measured",
  "--div-mid": "diverging ramp stop; aliases --neutral-fill, which is measured",
  "--div-high": "diverging ramp stop; aliases --success-fill, which is measured",
  "--skeleton-base": "the shimmer's base stop; aliases --surface-control",
  "--skeleton-sheen": "the shimmer's moving highlight — decoration, carries nothing",
};

describe.each(PALETTES)("%s palette — every token clears the bar its role sets", (_name, palette) => {
  for (const [token, role] of Object.entries(ROLES)) {
    it(`${token} clears ${String(THRESHOLD[role.bar])}:1 on all ${String(role.grounds.length)} of its grounds`, () => {
      for (const expression of role.grounds) {
        const ratio = ratioOn(palette, token, expression);
        expect(
          ratio,
          `${token} (${role.what}) is ${ratio.toFixed(2)}:1 on ${expression}, below the ` +
            `${String(THRESHOLD[role.bar])}:1 its role requires. Darken or lighten the token ` +
            `in tokens.css and update its measured comment — do not widen the role.`,
        ).toBeGreaterThanOrEqual(THRESHOLD[role.bar]);
      }
    });

    if (role.ceiling !== undefined) {
      const ceiling = role.ceiling;
      it(`${token} stays BELOW ${String(ceiling)}:1 everywhere, as its role claims`, () => {
        for (const expression of role.grounds) {
          const ratio = ratioOn(palette, token, expression);
          expect(
            ratio,
            `${token} is documented as "${role.what}" but reaches ${ratio.toFixed(2)}:1 on ` +
              `${expression}. A token nobody may use as text must not look like one.`,
          ).toBeLessThan(ceiling);
        }
      });
    }
  }
});

describe("the ROLES table covers every colour in tokens.css", () => {
  const declared = new Set([...Object.keys(ROLES), ...Object.keys(GROUNDS)]);

  it.each(PALETTES)("%s: every colour token has a role or is a declared ground", (_name, palette) => {
    // A new token cannot be added to tokens.css without deciding, HERE, what bar it clears.
    // This is the assertion the previous hand-written PAIRS list did not have, and its
    // absence is how a token meant for marks came to be used for 131 paragraphs.
    const unclassified = Object.keys(palette)
      .filter((token) => isColour(palette, token))
      .filter((token) => !declared.has(token))
      .sort();
    expect(unclassified).toEqual([]);
  });

  it("no role or ground names a token tokens.css does not define", () => {
    const missing = [...declared].filter((token) => LIGHT[token] === undefined).sort();
    expect(missing).toEqual([]);
  });

  it("every ground a role names is itself a defined token", () => {
    const referenced = new Set(
      Object.values(ROLES)
        .flatMap((role) => role.grounds)
        .flatMap((expression) => expression.split(" over ")),
    );
    expect([...referenced].filter((token) => LIGHT[token] === undefined).sort()).toEqual([]);
  });
});

/* ------------------------------------------------------------------------------------- *
 * The comment cross-check: every ratio tokens.css claims, recomputed, on the ground it
 * names — and that ground has to be the worst one the token's role allows.
 * ------------------------------------------------------------------------------------- */

/**
 * The annotation grammar tokens.css commits to, stated once:
 *
 *     --token: #hex;  /· N.NN:1 on <ground> — role ·/
 *     --token: #hex;  /· N.NN:1 at best on <ground> — role ·/
 *
 * `on` claims the token's WORST ground; `at best on` claims its BEST, and is what an
 * `exempt` token uses because its whole claim is a ceiling.
 */
const ANNOTATION =
  /(--[\w-]+):\s*(#[\da-f]{6,8});\s*\/\* (\d+\.\d\d):1 (at best )?on (--[\w-]+(?: over --[\w-]+)?) —/gu;

interface Annotation {
  readonly token: string;
  readonly claimed: number;
  readonly best: boolean;
  readonly namedGround: string;
}

function annotations(selector: string): readonly Annotation[] {
  return [...blockBody(selector).matchAll(ANNOTATION)].map((match) => {
    const [, token, , claimed, best, namedGround] = match;
    if (token === undefined || claimed === undefined || namedGround === undefined) {
      throw new Error(`unparsable annotation: ${match[0]}`);
    }
    return { token, claimed: Number(claimed), best: best !== undefined, namedGround };
  });
}

const ANNOTATED = [
  ["light", ":root", LIGHT],
  ["dark", '[data-theme="dark"]', DARK],
] as const;

describe.each(ANNOTATED)("%s: tokens.css states ratios it can prove", (_name, selector, palette) => {
  const found = annotations(selector);

  it("finds annotations at all", () => {
    // A regex that silently matches nothing is a green test that checks nothing. Both blocks
    // annotate at least the four ink tokens and the nine families.
    expect(found.length).toBeGreaterThanOrEqual(20);
  });

  it.each(found.map((annotation) => [annotation.token, annotation] as const))(
    "%s's comment states its own measured ratio",
    (_token, annotation) => {
      const role = ROLES[annotation.token];
      expect(role, `${annotation.token} is annotated but has no role`).toBeDefined();
      if (role === undefined) return;

      const measured = ratioOn(palette, annotation.token, annotation.namedGround);
      expect(
        Number(measured.toFixed(2)),
        `${annotation.token}'s comment claims ${annotation.claimed.toFixed(2)}:1 on ` +
          `${annotation.namedGround} but it measures ${measured.toFixed(2)}:1. Do not write a ` +
          `ratio you have not measured — that defect shipped twice in this codebase.`,
      ).toBe(annotation.claimed);

      // …and the ground it names must be the extreme one, so a comment cannot pick a
      // flattering surface. --fg-2's "4.6:1 — floor for real text" was true of no surface at
      // all; the failure mode this closes is the version that is true of exactly one.
      const ranked = role.grounds
        .map((expression) => [expression, ratioOn(palette, annotation.token, expression)] as const)
        .sort((a, b) => a[1] - b[1]);
      const extreme = annotation.best ? ranked[ranked.length - 1] : ranked[0];
      expect(
        extreme?.[0],
        `${annotation.token}'s comment names ${annotation.namedGround}, but its ` +
          `${annotation.best ? "best" : "worst"} ground is ${String(extreme?.[0])} at ` +
          `${String(extreme?.[1].toFixed(2))}:1.`,
      ).toBe(annotation.namedGround);
    },
  );

  it("every token whose value is a literal colour carries an annotation", () => {
    // An alias (`--st-failed: var(--error)`) is measured through its target and needs no
    // number of its own. A literal hex is a new colour and must state what it measures.
    const literal = Object.entries(block(selector))
      .filter(([token, value]) => /^#[\da-f]{6}$/u.test(value) && ROLES[token] !== undefined)
      .map(([token]) => token);
    const annotated = new Set(found.map((annotation) => annotation.token));
    expect(literal.filter((token) => !annotated.has(token)).sort()).toEqual([]);
  });
});

/* ------------------------------------------------------------------------------------- *
 * The scan: every `--ink-mark` and `--ink-rule` the source paints, measured at the bar its
 * usage earns.
 * ------------------------------------------------------------------------------------- */

/**
 * A waiver is the ONLY way a policed token may paint something. Anything not waived is
 * measured as TEXT against every ground in its role, which neither policed token can clear —
 * so adding a `text-ink-mark`/`text-ink-rule` to a paragraph, a `<label>`, a table cell or a
 * `<dt>` fails this file. Adding a genuinely new mark or rule means adding a line here with
 * the reason, which is the review seam these lists exist to create.
 *
 * `line` is the trimmed source line, so a list survives edits above it and forces a
 * re-justification when the site itself is rewritten. A stale entry is a failure too —
 * see "the waiver list has no dead entries".
 */
interface Waiver {
  readonly file: string;
  readonly line: string;
  readonly kind: Exclude<Bar, "text">;
  /** Why this is not text an operator reads. */
  readonly why: string;
  /**
   * Objective evidence, ALL of which must match. `aria-hidden` is the machine-checkable
   * form of "this is a mark, not a word".
   */
  readonly evidence: readonly RegExp[];
  /**
   * Where the evidence is checked. `"tag"` (the default) means the enclosing JSX opening tag
   * or, for a constant consumed elsewhere, the file. `"file"` is for a site whose proof is
   * necessarily somewhere else — a CSS declaration, or a `boxShadow` inside a `style` object.
   */
  readonly against?: "tag" | "file";
}

/**
 * `--ink-mark` waivers. Six lived here before the reskin (EmptyState's decorative glyph,
 * CommandPalette's kind glyph, FilterBar's ×, LiveScreen's ⊘ capability mark,
 * TimelineSourceLegend's standing glyph, StatTile's unknown band). Those components are being
 * restyled by other agents and each must re-add its own entry, with its own evidence, against
 * its own rewritten line — a waiver matches on the exact trimmed source line precisely so
 * that rewriting the line forces the justification to be made again rather than inherited.
 */
const MARK_WAIVERS: readonly Waiver[] = [
  {
    file: "src/styles/index.css",
    line: "scrollbar-color: var(--ink-mark) transparent;",
    kind: "graphic",
    why: "The scrollbar thumb is a UI component, so WCAG 1.4.11's 3:1 applies to it and 1.4.3's 4.5:1 does not. It is also the live proof that this walk reads .css: ESLint parses TypeScript and cannot see this declaration at all.",
    evidence: [/scrollbar-color: var\(--ink-mark\) transparent;/u, /scrollbar-width: thin;/u],
    against: "file",
  },
];

/**
 * `--ink-rule` waivers. There is no `"graphic"` waiver available at this token and there
 * never can be: it is 2.71:1 at its ceiling, so it fails 1.4.11's 3:1 as well as 1.4.3's
 * 4.5:1. Every entry must be `"exempt"` — the two cases WCAG itself puts outside the contrast
 * requirement, an inactive control (1.4.3) and pure decoration (1.4.11) — and must prove it
 * against the source.
 *
 * Empty on purpose. The two sites that survived the previous sweep, `StageMiniBar`'s inset
 * outline on a ghosted segment and `CursorPager`'s `disabled:` label, belong to components
 * being restyled; each has to re-add its own entry here when it re-points to `--ink-rule`.
 */
const RULE_WAIVERS: readonly Waiver[] = [];

/**
 * `text-ink-mark` as a Tailwind class, or `var(--ink-mark)` in an inline style, a colour
 * constant or a CSS declaration. The `var(` half deliberately does not require the closing
 * paren, so a `var(--ink-rule, #fff)` fallback form is caught too.
 */
function tokenUse(token: string): RegExp {
  return new RegExp(`(?<![\\w-])(?:text-${token.slice(2)}|var\\(\\s*${token})(?![\\w-])`, "gu");
}

/**
 * Every file that can paint with a token: `.ts`, `.tsx` AND `.css`.
 *
 * The `.css` half is not hypothetical hygiene — `index.css` paints a scrollbar thumb with
 * `--ink-mark` today, and ESLint's copy of this rule cannot see it. `tokens.css` is included
 * as well: the DEFINITIONS there (`--ink-rule: #adadb4;`) are not uses and do not match.
 */
function sourceFiles(): readonly string[] {
  return readdirSync(SRC_DIR, { recursive: true, encoding: "utf8" })
    .map((entry) => entry.split(sep).join("/"))
    .filter(
      (rel) =>
        /\.(?:tsx?|css)$/u.test(rel) &&
        !/\.d\.ts$/u.test(rel) &&
        !/\.test\.tsx?$/u.test(rel) &&
        !rel.startsWith("test/"),
    )
    .sort();
}

/**
 * The JSX opening tag a match sits inside: back to the nearest `<`, then forward to the `>`
 * that closes it, ignoring the `>` of an arrow function inside a braced expression and any
 * `>` inside a string. Returns `null` when the match is not in JSX at all (a bare constant,
 * or a CSS declaration), which is exactly the case a waiver's `evidence` has to cover against
 * the whole file.
 */
function enclosingTag(source: string, index: number): string | null {
  let start = index;
  while (start > 0 && source[start] !== "<") start -= 1;
  if (source[start] !== "<" || !/[A-Za-z]/u.test(source[start + 1] ?? "")) return null;
  let depth = 0;
  let quote: string | null = null;
  for (let cursor = start; cursor < source.length; cursor += 1) {
    const char = source[cursor];
    if (quote !== null) {
      if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") quote = char;
    else if (char === "{") depth += 1;
    else if (char === "}") depth -= 1;
    else if (char === ">" && depth === 0) {
      const tag = source.slice(start, cursor + 1);
      return cursor >= index ? tag : null;
    }
  }
  return null;
}

interface TokenSite {
  readonly file: string;
  readonly lineNumber: number;
  readonly line: string;
  readonly tag: string | null;
}

function tokenSites(token: string): readonly TokenSite[] {
  const use = tokenUse(token);
  const sites: TokenSite[] = [];
  for (const file of sourceFiles()) {
    const source = readFileSync(resolve(SRC_DIR, file), "utf8");
    for (const match of source.matchAll(use)) {
      const index = match.index;
      const before = source.slice(0, index);
      const lineStart = before.lastIndexOf("\n") + 1;
      const lineEnd = source.indexOf("\n", index);
      sites.push({
        file: `src/${file}`,
        lineNumber: before.split("\n").length,
        line: source.slice(lineStart, lineEnd === -1 ? undefined : lineEnd).trim(),
        tag: enclosingTag(source, index),
      });
    }
  }
  return sites;
}

const MARK_SITES = tokenSites("--ink-mark");
const RULE_SITES = tokenSites("--ink-rule");

/**
 * One token, one scan. Both policed tokens are treated identically: unwaived means TEXT, and
 * text means 4.5:1 on every ground the token's role allows, in both palettes.
 */
function policeToken(
  token: string,
  sites: readonly TokenSite[],
  waivers: readonly Waiver[],
  waiverListName: string,
): void {
  const waiverFor = (site: TokenSite): Waiver | undefined =>
    waivers.find((waiver) => waiver.file === site.file && waiver.line === site.line);
  const role = ROLES[token];
  if (role === undefined) throw new Error(`${token} is policed but has no role`);

  describe(`${token} in the source, measured at the bar its usage earns`, () => {
    it("finds the uses it is supposed to be policing", () => {
      // A scan that silently matches nothing is a green test that guards nothing.
      expect(sites.length).toBeGreaterThanOrEqual(waivers.length);
    });

    it.each(sites.map((site) => [`${site.file}:${String(site.lineNumber)}`, site] as const))(
      "%s",
      (_where, site) => {
        const waiver = waiverFor(site);
        const bar: Bar = waiver?.kind ?? "text";
        // An unwaived site is TEXT, and text must clear 4.5:1 on every ground of both
        // palettes. Neither policed token ever does, so this is where a new prose site fails.
        // The failure message names the fix rather than the number.
        for (const [name, palette] of PALETTES) {
          for (const expression of role.grounds) {
            const ratio = ratioOn(palette, token, expression);
            expect(
              ratio,
              waiver === undefined
                ? `${site.file}:${String(site.lineNumber)} paints ${token} with no waiver, so ` +
                  `it is measured as text: ${ratio.toFixed(2)}:1 on ${expression} (${name}), ` +
                  `below 4.5:1. Use --ink-muted for anything an operator reads, or add a ` +
                  `justified entry to ${waiverListName} if this really is a glyph, a mark or a ` +
                  `rule.\n  ${site.line}`
                : `${site.file}:${String(site.lineNumber)} is waived as ${waiver.kind} but is ` +
                  `${ratio.toFixed(2)}:1 on ${expression} (${name}).`,
            ).toBeGreaterThanOrEqual(THRESHOLD[bar]);
          }
        }
      },
    );

    it.each(
      sites
        .filter((site) => waiverFor(site) !== undefined)
        .map((site) => [`${site.file}:${String(site.lineNumber)}`, site] as const),
    )("%s proves its waiver against the source", (_where, site) => {
      const waiver = waiverFor(site);
      expect(waiver).toBeDefined();
      if (waiver === undefined) return;
      // The waiver's claim is checked against the source, not taken on trust: a JSX site
      // must carry the evidence in its own opening tag; a shared constant, a rule inside a
      // style object or a CSS declaration proves it against the file that surrounds it.
      const file = readFileSync(resolve(SRC_DIR, site.file.slice(4)), "utf8");
      const haystack = waiver.against === "file" ? file : (site.tag ?? file);
      for (const evidence of waiver.evidence) {
        expect(haystack, `${site.file}: ${waiver.why}`).toMatch(evidence);
      }
    });

    it("the waiver list has no dead entries", () => {
      // A waiver that no longer matches any site is a licence nobody is using, and it would
      // silently start covering a future line with the same text.
      const unmatched = waivers.filter(
        (waiver) => !sites.some((site) => site.file === waiver.file && site.line === waiver.line),
      );
      expect(unmatched.map((waiver) => `${waiver.file} :: ${waiver.line}`)).toEqual([]);
    });

    it(`no muted LABEL is painted with ${token}`, () => {
      // The rule in one assertion, stated the way a reviewer would state it.
      const prose = sites.filter((site) => waiverFor(site) === undefined);
      expect(prose.map((site) => `${site.file}:${String(site.lineNumber)} ${site.line}`)).toEqual(
        [],
      );
    });
  });
}

policeToken("--ink-mark", MARK_SITES, MARK_WAIVERS, "MARK_WAIVERS");
policeToken("--ink-rule", RULE_SITES, RULE_WAIVERS, "RULE_WAIVERS");

describe("the policed tokens really cannot be used as text", () => {
  it("--ink-mark clears 3:1 everywhere and 4.5:1 nowhere, taken worst-case", () => {
    // Which is the whole difference between the two verdicts. A surface-agnostic component
    // does not know which ground it landed on, so the bar is the worst case across both
    // palettes — and there it is 3.52:1, a legitimate mark and never a word.
    const role = ROLES["--ink-mark"];
    expect(role).toBeDefined();
    const ratios = PALETTES.flatMap(([, palette]) =>
      (role?.grounds ?? []).map((expression) => ratioOn(palette, "--ink-mark", expression)),
    );
    expect(Math.min(...ratios)).toBeGreaterThanOrEqual(3);
    expect(Math.min(...ratios)).toBeLessThan(4.5);
  });

  it("--ink-rule clears NO bar: not 4.5:1 as text, not even 3:1 as a graphic", () => {
    // This is the fact that makes RULE_WAIVERS "exempt"-only. Unlike --ink-mark, there is no
    // legitimate mark or icon use of this token — a glyph painted with it is as unreadable as
    // a word, and the only survivors can be a rule and an inactive control.
    const role = ROLES["--ink-rule"];
    expect(role).toBeDefined();
    for (const [, palette] of PALETTES) {
      for (const expression of role?.grounds ?? []) {
        expect(ratioOn(palette, "--ink-rule", expression)).toBeLessThan(3);
      }
    }
  });

  it("--ink-muted is the muted-label colour that does clear AA everywhere", () => {
    // The fix every failure message above points at. It has to be true, or the advice is bad.
    const role = ROLES["--ink-muted"];
    expect(role).toBeDefined();
    for (const [, palette] of PALETTES) {
      for (const expression of role?.grounds ?? []) {
        expect(ratioOn(palette, "--ink-muted", expression)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("the scan reads .css as well, so a stylesheet cannot evade it", () => {
    // ESLint parses TypeScript only; `color: var(--ink-rule)` in a .css file would be
    // invisible to it. This is the assertion that keeps the walk honest if someone narrows
    // the filter. The list is enumerated rather than globbed so that a NEW stylesheet has to
    // be added here deliberately, which is the moment someone reads it for a policed token
    // on prose.
    expect(sourceFiles().filter((file) => file.endsWith(".css"))).toEqual([
      "styles/fonts.css",
      "styles/index.css",
      "styles/tokens.css",
    ]);
  });
});

/* ------------------------------------------------------------------------------------- *
 * The structural facts the components are written around.
 * ------------------------------------------------------------------------------------- */

describe("the structural facts the components are written around", () => {
  it("light is home: :root is the LIGHT palette and the attribute block is dark", () => {
    // The polarity flipped with the reskin, and getting it backwards is silent: every
    // measurement above would still run, against the wrong grounds, and still pass. So the
    // polarity itself is asserted, from the one property that cannot be argued with.
    expect(relativeLuminance(colorOf(LIGHT, "--surface"))).toBeGreaterThan(0.5);
    expect(relativeLuminance(colorOf(DARK, "--surface"))).toBeLessThan(0.1);
    expect(TOKENS_CSS).toContain('[data-theme="dark"] {');
    expect(TOKENS_CSS).not.toContain('[data-theme="light"] {');
  });

  it("a card is separated from the ground by COLOUR, not by a border", () => {
    // The old palette's premise was "every control carries its own ground because borders do
    // not reach 3:1". Gogo goes further: cards have no border at all, so the only things
    // distinguishing a card from the page are --surface-card against --surface and
    // --shadow-card. If those two surfaces were ever equal the card would vanish, and no
    // amount of shadow tuning would bring it back.
    for (const [name, palette] of PALETTES) {
      const card = relativeLuminance(colorOf(palette, "--surface-card"));
      const page = relativeLuminance(colorOf(palette, "--surface"));
      expect(Math.abs(card - page), `${name}: --surface-card equals --surface`).toBeGreaterThan(
        0.003,
      );
    }
    expect(TOKENS_CSS).toContain("--shadow-card: var(--shadow-xs);");
  });

  it("every surface is redefined for dark — no token inherits a light ground", () => {
    // `--bg-inset` used to be defined only in the dark palette, so every code block in the
    // light theme was a dark-first surface nobody had looked at. All five surfaces, all four
    // ink tokens and all three line tokens are now redefined explicitly.
    const darkOnly = block('[data-theme="dark"]');
    for (const token of [
      ...SURFACES,
      "--ink",
      "--ink-muted",
      "--ink-mark",
      "--ink-rule",
      "--hairline",
      "--hairline-strong",
      "--edge",
    ]) {
      expect(darkOnly[token], `${token} is not redefined for the dark theme`).toBeDefined();
    }
  });

  it("every semantic family is redefined for dark, in all three members", () => {
    const darkOnly = block('[data-theme="dark"]');
    for (const family of FAMILIES) {
      for (const suffix of ["", "-fill", "-tint"]) {
        expect(darkOnly[`--${family}${suffix}`], `--${family}${suffix} misses dark`).toBeDefined();
      }
    }
  });

  it("the order-state and pipeline-status families are aliases, so a state is re-pointed once", () => {
    // A component names the STATE, never the hue. `--st-delivered` resolves to `--success`
    // and nothing in components/ should ever say `--success` for a delivered order.
    for (const state of ORDER_STATES) {
      expect(LIGHT[`--st-${state}`], `--st-${state} is missing`).toMatch(/^var\(--[\w-]+\)$/u);
    }
    for (const status of PIPELINE_STATUSES) {
      expect(LIGHT[`--pg-${status}`], `--pg-${status} is missing`).toMatch(/^var\(--[\w-]+\)$/u);
    }
    expect(LIGHT["--retryable"]).toBe("var(--caution)");
    expect(LIGHT["--terminal"]).toBe("var(--error)");
  });

  it("semantic chart series keep semantic hues — delivered is success, failed is error", () => {
    // §11.3's rule, asserted at the palette rather than left to each chart: green must mean
    // the same thing on every surface, so the categorical ramp is never used for a status.
    expect(colorOf(LIGHT, "--st-delivered")).toEqual(colorOf(LIGHT, "--success"));
    expect(colorOf(DARK, "--st-delivered")).toEqual(colorOf(DARK, "--success"));
    expect(colorOf(LIGHT, "--st-failed")).toEqual(colorOf(LIGHT, "--error"));
    expect(colorOf(DARK, "--st-failed")).toEqual(colorOf(DARK, "--error"));
    // …and the two are far apart in colour. Note they are NOT far apart in LUMINANCE —
    // --success and --error are 1.00:1 against each other in the light palette, because both
    // were pushed to the same lightness to clear 4.5:1 on a white card. That is exactly why
    // §11.3 forbids hue as the only channel: a delivered series and a failed series are told
    // apart by ✓/✗, by their words and by dash pattern, never by green-versus-red alone.
    expect(rgbDistance(colorOf(LIGHT, "--success"), colorOf(LIGHT, "--error"))).toBeGreaterThan(60);
    expect(rgbDistance(colorOf(DARK, "--success"), colorOf(DARK, "--error"))).toBeGreaterThan(60);
  });

  it("adjacent categorical slots are never the same colour", () => {
    // Colour is never the only channel — series also differ by dash pattern and marker — but
    // two neighbours resolving to one hex would make the ramp shorter than it claims to be.
    for (const [, palette] of PALETTES) {
      const ramp = [1, 2, 3, 4, 5, 6, 7, 8].map((slot) => colorOf(palette, `--c-${String(slot)}`));
      const unique = new Set(ramp.map(({ r, g, b }) => `${String(r)},${String(g)},${String(b)}`));
      expect(unique.size).toBe(8);
    }
  });

  it("the reduced-motion block still zeroes every duration", () => {
    // Not contrast, but it lives in this file's stylesheet and it is the one rule that keeps
    // the ◉ generating pulse from being a vestibular hazard.
    const reduced = TOKENS_CSS.slice(TOKENS_CSS.indexOf("@media (prefers-reduced-motion: reduce)"));
    for (const token of ["--d-instant", "--d-fast", "--d-base", "--d-slow", "--d-pulse"]) {
      expect(reduced).toMatch(new RegExp(`${token}: (?:1ms|0ms);`, "u"));
    }
  });

  it("the font stacks are NOT here — they live beside the faces they name", () => {
    // `--font-sans` once named "Inter var", a family this bundle never shipped, because the
    // value lived here and the @font-face lived (or did not live) elsewhere. fonts.css owns
    // both now, and a palette rewrite must not reintroduce them.
    expect(TOKENS_CSS).not.toMatch(/--font-(?:sans|heading|mono):/u);
  });

  it("the removed token families are really gone from tokens.css", () => {
    // Positional names are what caused both accessibility incidents. If one comes back it
    // will come back here first, and Tailwind will silently resolve it for whoever asks.
    for (const dead of [
      "--fg-0",
      "--fg-1",
      "--fg-2",
      "--fg-3",
      "--bg-0",
      "--bg-1",
      "--bg-2",
      "--bg-3",
      "--bg-inset",
      "--border",
      "--border-strong",
      "--border-accent",
      "--violet",
      "--cyan",
      "--magenta",
      "--e-1",
      "--e-2",
      "--e-3",
      "--glow-violet",
      "--glow-red",
      "--glow-green",
    ]) {
      // Declarations only — the header prose names the dead tokens on purpose, to say what
      // each one became.
      expect(TOKENS_CSS, `${dead} is still declared`).not.toMatch(
        new RegExp(`^\\s*${dead}\\s*:`, "mu"),
      );
    }
  });
});
