/**
 * WCAG contrast, in every cell — §14's Slice 1d acceptance names it as a gate, not a nicety.
 * The palette is PlanIQ (plan §2.1–2.2) on the Gogo language's structure (§11.3 as amended
 * 2026-09-03): LIGHT-FIRST, and naming its tokens by role.
 *
 * "Cell", not "palette", is a habit worth keeping from the two months this file spent
 * measuring four of them. Colour briefly varied on TWO orthogonal attributes, a `data-palette`
 * registry crossed with `data-theme`, so `gogo` and `planiq` could ship side by side and be
 * compared on real data. The console then committed to `planiq` and the palette axis was
 * removed. Two cells remain — `light` and `dark` — and they are still DERIVED from the
 * stylesheet rather than hand-listed, which is why the axis cost nothing to add and nothing to
 * take away.
 *
 * `vitest.config.ts` sets `css: false`, so no rendering test in this suite can ever see a
 * real colour — jsdom gets class strings and inline `var()` text and nothing else. A green
 * suite therefore proves nothing at all about legibility unless some file reads the
 * stylesheet as text and does the arithmetic. This is that file. It does five things; each of
 * items 2–4 is what makes the one before it honest, and item 5 is what keeps every block in
 * the file complete and measured:
 *
 * Three things it no longer does ITSELF, and where they went. The arithmetic is
 * `contrastMath.mts`, the ROLES/GROUNDS vocabulary is `contrastRoles.mts`, and the block
 * grammar plus the palette registry is `paletteBlocks.mts`. Nothing moved for tidiness:
 * `tools/annotate-tokens.mts` WRITES the ratios and the ground names this file reads back, so
 * a second implementation of any of the three would let the generator emit a comment the gate
 * rejects — or, worse, one it accepts because both halves are wrong the same way. What stayed
 * here is everything that ASSERTS: the describes, the bars, the waivers, the source scan. A
 * tool may import the contract; it still cannot loosen it.
 *
 *  1. **A ROLES table.** Every colour token in `tokens.css` is declared with the bar it has
 *     to clear and the complete set of grounds it may legally sit on, and is measured
 *     against every one of them in every cell. The grounds are computed, including
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
 *  5. **The block invariants.** The cells above are read out of the stylesheet rather than
 *     hardcoded, and two invariants keep that honest: every theme block declares exactly the
 *     same key set (so no cell inherits a value the cascade would otherwise have arbitrated by
 *     source order), and no block outside `:root` declares a `var()` alias (so a theme can
 *     change what green IS but never what it MEANS). Both arrived with the two-palette axis
 *     and both outlived it: the console now ships ONE palette, and the third invariant that
 *     axis needed — a registry equal to `PaletteChoice` in both directions — went with it.
 *     What replaces it is the assertion that the axis stays gone, because a `[data-palette]`
 *     block nothing enumerates is a cell nobody has ever measured a ratio in.
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
 *     clear 4.5:1 on all five surfaces of every cell AND on all nine tints composited over
 *     the card and over the page ground — which is where a status pill puts its word.
 *  2. **`--ink-mark` is a MARK colour and can never be text.** Its best ground in one cell
 *     is readable — 4.49:1 on a white card — but a surface-agnostic component does not know
 *     which ground it landed on, so the bar is worst-case: 3.56:1 across both cells, above
 *     1.4.11's 3:1 and below 1.4.3's 4.5:1 everywhere it matters.
 *  3. **`--ink-rule` clears no bar at all**, in either cell, on any ground: 2.94:1 at the most
 *     generous ceiling either of them gives it. It may paint a rule, a hairline or a dead
 *     control and nothing else.
 *  4. **Cards have no border in this design, so "the border is not the boundary" is not a
 *     hypothesis about `--hairline` — it is the premise.** `--hairline` is 1.46:1 at best,
 *     taken across every cell. What separates a card from the ground is `--surface-card`
 *     against `--surface` plus `--shadow-card`, and the assertion at the bottom of this file
 *     is that those two surfaces really are different colours in every cell — 1.08:1 in
 *     light and 1.10:1 in dark, both recomputed when the palette axis was removed rather than
 *     carried over. (The 1.04:1 that used to stand here was `gogo/light`'s, and it left with
 *     `gogo`. An earlier version of this header stated a figure measured on two cells as
 *     though it covered four — this file's own defect class committed in its own header, and
 *     the reason every number here is recomputed on any change of scope.) The one border that
 *     carries meaning, a floating popover's
 *     ring, is `--edge`, and it is measured at 3:1.
 */

import { readdirSync, readFileSync } from "node:fs";
import { resolve, sep } from "node:path";

import { describe, expect, it } from "vitest";


import {
  colorOf,
  isColour,
  type Palette,
  ratioOn,
  relativeLuminance,
  rgbDistance,
} from "./contrastMath.mts";
import {
  type Bar,
  FAMILIES,
  GROUNDS,
  ORDER_STATES,
  PIPELINE_STATUSES,
  rankedGrounds,
  ROLES,
  SURFACES,
  THRESHOLD,
  tiedExtremeGrounds,
} from "./contrastRoles.mts";
import { annotationsIn, block, isPaletteValue, readStylesheet } from "./paletteBlocks.mts";

// Resolved from the Vitest root (`admin-ui/`), not from `import.meta.url`: under the jsdom
// environment `import.meta.url` is an `http://` URL and `fileURLToPath` rejects it.
const SRC_DIR = resolve(process.cwd(), "src");
const TOKENS_CSS = readFileSync(resolve(SRC_DIR, "styles/tokens.css"), "utf8");

/**
 * The whole stylesheet, resolved into its cells: `:root`'s two halves, the key set every theme
 * block owes, and one `Cell` per theme. The parsing and the annotation grammar live in
 * `paletteBlocks.mts` because `tools/annotate-tokens.mts` writes into the same file this
 * reads, and a generator that parsed it its own way could measure a ratio in one cell and
 * write the comment into another.
 */
const SHEET = readStylesheet(TOKENS_CSS);
const { root: ROOT, cells: CELLS, blocks: PALETTE_BLOCKS, paletteKeys: PALETTE_KEYS } = SHEET;

/** The cells in the shape `describe.each` wants. */
const PALETTES = CELLS.map((cell) => [cell.label, cell.tokens] as const);

function cellFor(theme: string): Palette {
  const found = CELLS.find((cell) => cell.theme === theme);
  if (found === undefined) throw new Error(`no ${theme} cell in the stylesheet`);
  return found.tokens;
}

const LIGHT = cellFor("light");
const DARK = cellFor("dark");


describe.each(PALETTES)("%s — every token clears the bar its role sets", (_name, palette) => {
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
 * What each GROUNDS entry is allowed to be — keyed on ROLE, not on the `--surface` prefix.
 *
 * Being in GROUNDS is how a colour token satisfies the completeness gate without declaring
 * a bar, and until now the price of that was one sentence a human wrote. That is the whole
 * of the "a sixth surface, green forever" evasion: a new ground satisfies completeness,
 * appears in no role's ground set, and is therefore never a surface any ink is measured on —
 * with every assertion in this file green while a component paints text on it.
 *
 * The prefix form (`^--surface` must be in `SURFACES`) was proposed and rejected in the plan
 * because it would not have covered `--scrim`, which PQ3 adds, and `--scrim` is precisely
 * the shape of the hole. Keying on the kind each entry DECLARES covers both: a new surface
 * has to say `kind: "surface"`, which puts it in `SURFACES`, which puts it into every
 * surface-agnostic role's ground set; and a translucent ground has to say what it sits over,
 * because a translucent token's real colour is not its own hex.
 * ------------------------------------------------------------------------------------- */

describe("every GROUNDS entry is held to the property that makes it safe to carry no bar", () => {
  const byKind = (kind: string): readonly string[] =>
    Object.entries(GROUNDS)
      .filter(([, ground]) => ground.kind === kind)
      .map(([token]) => token)
      .sort();

  it('the "surface" entries are exactly SURFACES, in both directions', () => {
    // The teeth. A sixth surface cannot be declared as a ground and then quietly not be one:
    // calling it a surface here forces it into SURFACES, and SURFACES is what every
    // surface-agnostic role's ground set is built from. Calling it something else instead is
    // what the three assertions below then have to be lied to about.
    expect(byKind("surface")).toEqual([...SURFACES].sort());
  });

  it.each(PALETTES)('%s: every "surface-alias" really IS a surface, colour for colour', (_name, palette) => {
    // `--surface-nav`, `--surface-topbar` and `--skeleton-base` carry no bar because they are
    // byte-identical to a surface that does. The instant one drifts a shade it stops being an
    // alias and starts being a ground in its own right that nothing is measured on — which is
    // the sixth surface again, arriving through the door marked "alias".
    const same = (a: string, b: string): boolean => {
      const x = colorOf(palette, a);
      const y = colorOf(palette, b);
      return x.r === y.r && x.g === y.g && x.b === y.b && x.a === y.a;
    };
    for (const token of byKind("surface-alias")) {
      expect(
        SURFACES.filter((surface) => same(token, surface)),
        `${token} is declared an alias of a surface but matches none of them. It is a ` +
          `SIXTH surface now: either add it to SURFACES so every ink is measured on it, or ` +
          `point it back at the surface it claims to name.`,
      ).not.toEqual([]);
    }
  });

  it('every "chip-tint" is a measurement ground over all five surfaces', () => {
    // A tint's whole safety argument is "the inks are measured ON it". `ALL_TINT_GROUNDS`
    // makes that true by construction for the nine families; this is what says the same of
    // the state and status tints, and what would fail if a tint were ever added to GROUNDS
    // without being added to a role's ground set.
    const measured = new Set(Object.values(ROLES).flatMap((role) => role.grounds));
    const unmeasured = byKind("chip-tint").filter((token) =>
      SURFACES.some((surface) => !measured.has(`${token} over ${surface}`)),
    );
    expect(
      unmeasured,
      `a chip ground nothing is measured on is a chip whose word's contrast nobody knows. ` +
        `Add it to the ink roles' grounds (see tintGrounds/ALL_TINT_GROUNDS).`,
    ).toEqual([]);
  });

  it.each(PALETTES)('%s: every "ramp-alias" resolves to a token that HAS a role', (_name, palette) => {
    // `--div-low` carries no bar because it is `--error-fill`, which carries one. That is
    // only true while the two really are the same colour in the cell being measured.
    for (const token of byKind("ramp-alias")) {
      const stop = colorOf(palette, token);
      const twins = Object.keys(ROLES).filter((role) => {
        const other = colorOf(palette, role);
        return (
          stop.r === other.r && stop.g === other.g && stop.b === other.b && stop.a === other.a
        );
      });
      expect(
        twins,
        `${token} is documented as measured through the token it aliases, but in this cell ` +
          `it matches no token that has a role. It is an unmeasured colour.`,
      ).not.toEqual([]);
    }
  });

  it.each(PALETTES)("%s: a translucent ground states what it sits over, and an opaque one does not", (_name, palette) => {
    // The half of PQ1's bullet that is checkable today, and the trap set for `--scrim`. A
    // translucent ground's contrast is a property of the composite, so an entry with alpha
    // and no stated backing is a claim nobody can recompute; and an `over` note on an opaque
    // token is a note that reads as evidence while being decoration.
    //
    // NOT landed here, and named so it is not mistaken for done: the second half of the same
    // bullet, "…and at least one measured line beside it". The only translucent ground on
    // this tree is `--skeleton-sheen`, which carries nothing and has nothing to measure, so
    // there is no subject to shape that assertion against. `--scrim` is that subject, and
    // landing it belongs to the tranche that adds it.
    for (const [token, ground] of Object.entries(GROUNDS)) {
      const translucent = colorOf(palette, token).a < 1;
      const named = ground.over ?? [];
      if (translucent) {
        expect(
          named,
          `${token} is translucent here, so its real colour is whatever is behind it. State ` +
            `the surfaces it is composited over in its GROUNDS entry.`,
        ).not.toEqual([]);
        expect(named.filter((surface) => !(SURFACES as readonly string[]).includes(surface))).toEqual(
          [],
        );
      } else {
        expect(
          named,
          `${token} is opaque here but claims to sit "over" something. An opaque ground is ` +
            `its own colour; the note would be evidence for a composite that never happens.`,
        ).toEqual([]);
      }
    }
  });
});

/* ------------------------------------------------------------------------------------- *
 * The palette axis. Colour is swappable; meaning is not. These assertions are the only
 * thing standing between "an operator can pick a palette" and "a palette can ship
 * unmeasured", and none of them is expressible until the axis exists — which is why they
 * are landed here, at a registry of ONE, where they can be watched failing on real drift
 * before anything depends on them.
 * ------------------------------------------------------------------------------------- */

/**
 * `tokens.css` with every comment removed — the CODE of the stylesheet.
 *
 * The prose in this file names selectors it does not declare: the header explains why the
 * `data-palette` axis was removed, and says `[data-palette="planiq"]` while doing so. Any
 * assertion that asks "which selectors does this file DECLARE" has to read the code and not
 * the documentation, or the answer is whatever the header happens to mention — and here that
 * would turn the very sentence recording the removal into a failure.
 */
const TOKENS_CSS_CODE = TOKENS_CSS.replace(/\/\*[\s\S]*?\*\//gu, "");

describe("the block invariants hold — a theme changes what green IS, never what it MEANS", () => {
  it("every block opens with a single canonical selector on its own line", () => {
    // `blockBody()` addresses a block by the exact text of its opening line, so the file has
    // to write that text exactly one way. This is not house style: `[data-theme="dark"] {` is
    // a SUBSTRING of `[data-palette="planiq"][data-theme="dark"] {`, so a grouped selector, a
    // stray second space or an indent is enough to make one palette measure another palette's
    // hexes. `blockBody` throws on the cases it can see (zero matches, two matches); this is
    // what sees the ones it cannot — an EXTRA top-level block nobody enumerated, and the
    // ORDER the blocks sit in.
    //
    // Order is asserted for a cascade reason, not a tidiness one. §2.0.3's completeness
    // argument turns on `[data-palette="x"][data-theme="dark"]` being (0,2,0) where the two
    // single-attribute blocks are both (0,1,0) and arbitrated by source order alone. Freezing
    // the order freezes the arbitration, and the `@media` tail is pinned with it so a fifth
    // block cannot be appended below the registry unnoticed.
    //
    // The captured group deliberately keeps the trailing space, so `:root  {` fails on the
    // double space a `trimEnd()` would have swallowed.
    const openings = [...TOKENS_CSS.matchAll(/^(\S[^{\n]*)\{/gmu)].map((match) => match[1] ?? "");
    expect(openings).toEqual([
      ...CELLS.map((cell) => `${cell.selector} `),
      "@media (prefers-reduced-motion: reduce) ",
    ]);
  });

  it("the three halves of :root are the ones §2.0.1 measured", () => {
    // `isPaletteValue` is the seam the whole cross product hangs off: it decides what a
    // palette block owns and what it may never touch. A classifier that quietly stopped
    // matching would make key-set parity VACUOUS — an empty required key set is satisfied by
    // an empty block — so its output is pinned to the counts measured off the live file.
    // These numbers move only when a token is deliberately added, and moving one without its
    // sibling (a hex with no alias, an alias with no hex) is drift this file exists to catch.
    // §2.0.1 measured 52/64/158 on the pre-PQ2a file; PQ2a added `--brand-solid-edge` (a hex,
    // so every block owes it) and `--ink-on-error` (an alias, so `:root` owns it alone), and
    // these three counts were hand-edited in the same change rather than after it — an
    // assertion that has to be relaxed to let a commit land is an assertion nobody trusts.
    const values = Object.values(ROOT);
    expect(values.filter(isPaletteValue)).toHaveLength(65); // 53 hexes + 12 shadow strings
    expect(values.filter((value) => value.startsWith("var("))).toHaveLength(65); // the aliases
    expect(values).toHaveLength(160); // …and 30 radius/motion/layout tokens, which is the rest
    // A `var(--x, #fff)` fallback would be an alias that also states a colour: it would drop
    // out of PALETTE_KEYS while reading to a human as a palette value. The grammar has none.
    expect(values.filter((value) => /^var\([^)]*,/u.test(value))).toEqual([]);
  });

  it.each(PALETTE_BLOCKS.map((cell) => [cell.label, cell] as const))(
    "%s declares every palette name :root does, and no others",
    (_label, cell) => {
      // A palette block is COMPLETE or it is a cascade accident. `[data-palette="x"]` and
      // `[data-theme="dark"]` are both (0,1,0), so when both match, SOURCE ORDER decides which
      // value wins — not intent. A block written as a diff against `:root` therefore leaks its
      // own light surfaces into another palette's dark cell, chosen by nothing but the order
      // the blocks happen to sit in the file, and every measurement above stays green while it
      // does. Completeness dissolves it: the combined selector is (0,2,0) and wins outright, so
      // there is nothing left for the cascade to arbitrate.
      //
      // This assertion FAILED on the tree it was written against, which is the only reason it
      // is trusted: `[data-theme="dark"]` carried 62 of the then-64 names, missing --brand-solid and
      // --ink-on-brand, both of which were being measured through `:root` by inheritance. Both
      // were added to the dark block at their existing :root values — the same two hexes, so
      // zero visual change and zero ratio change — and the assertion went green on real drift
      // rather than on a fixture.
      const declared = Object.keys(block(TOKENS_CSS, cell.selector)).sort();
      expect(
        declared.filter((token) => !PALETTE_KEYS.includes(token)),
        `${cell.label} declares a name :root does not. An alias or a non-colour token has ` +
          `escaped into a palette block, where every OTHER palette is blind to it.`,
      ).toEqual([]);
      expect(
        PALETTE_KEYS.filter((token) => !declared.includes(token)),
        `${cell.label} is not complete in all ${String(PALETTE_KEYS.length)}. An inherited ` +
          `value is a value chosen by source order, not by design — add the declaration to ` +
          `this block rather than relying on :root to supply it.`,
      ).toEqual([]);
    },
  );

  it.each(PALETTE_BLOCKS.map((cell) => [cell.label, cell] as const))(
    "%s declares no var() alias",
    (_label, cell) => {
      // §2.0.2, made mechanical. `--st-held: var(--brand)`, `--focus-ring: var(--brand-fill)`
      // and their 63 siblings say what a colour MEANS, and meaning is the half an operator
      // learns. A palette that could re-point `--st-held` at a different family would be a
      // palette that changes what the screen SAYS, and that is not a theme, it is a fork.
      //
      // Not subsumed by parity, and parity does not subsume this. Parity catches `--st-held`
      // in a palette block because the NAME is not in PALETTE_KEYS. It does not catch
      // `--brand: var(--accent)`, whose name is. Two invariants, two failure modes.
      const aliases = Object.entries(block(TOKENS_CSS, cell.selector))
        .filter(([, value]) => value.startsWith("var("))
        .map(([token, value]) => `${token}: ${value};`)
        .sort();
      expect(
        aliases,
        `${cell.label} declares an alias. Aliases live in :root and nowhere else, so that the ` +
          `operational vocabulary is identical in every palette.`,
      ).toEqual([]);
    },
  );

  it("the data-palette axis is gone, and stays gone", () => {
    // The console shipped `gogo` and `planiq` side by side on a `data-palette` attribute and
    // then committed to `planiq` outright, which deleted the registry that enumerated them.
    // This is what the registry-closure assertion turned into, and it guards the same defect
    // from the other side: with nothing enumerating palettes any more, a `[data-palette=…]`
    // block added to this file would be measured by NOTHING. Every assertion here runs on the
    // cells `readStylesheet` returns, and those are now the two themes and only the two
    // themes, so such a block would render in a browser and never be measured once.
    //
    // Asserted on the CODE, so the header may go on explaining why the axis was removed.
    expect(TOKENS_CSS_CODE).not.toContain("data-palette");
  });

  it("no block hides behind an indent", () => {
    // The canonical-form assertion above is anchored at column 0, which is what makes it able
    // to say anything about ORDER — and is also the one thing it cannot see past. `  [data-
    // palette="acme"] { … }` is valid CSS, applies in the browser at the same (0,1,0) the
    // enumerated blocks carry, and is invisible to every `^`-anchored scan in this file: no
    // cell measures it, `blockRange` is never asked for it, and nothing goes red. That is the
    // "a palette that ships UNMEASURED" failure with a leading space in front of it.
    //
    // So the closure is asserted on the code with the indent allowed and then required to be
    // absent: every `{` in the stylesheet opens either one of the four enumerated cells, the
    // reduced-motion `@media`, or the `:root` INSIDE that media block — which is the file's
    // one legitimate indented opening and is named here so it stays the only one.
    const openings = [...TOKENS_CSS_CODE.matchAll(/^[^\S\n]*([^{\n]*)\{/gmu)].map((match) =>
      (match[1] ?? "").trim(),
    );
    expect(openings.sort()).toEqual(
      [
        ...CELLS.map((cell) => cell.selector),
        "@media (prefers-reduced-motion: reduce)",
        ":root",
      ].sort(),
    );
  });

  it("no component reaches for a palette attribute either", () => {
    // The stylesheet is only half of it. `document.documentElement.setAttribute("data-palette",
    // …)` in a store or an effect would put an attribute on <html> that matches no rule in
    // tokens.css: nothing changes on screen, nothing goes red, and the control that writes it
    // looks broken to the operator and fine to the suite. Removing the axis means removing
    // both ends of it.
    // The CODE of each file, for the same reason `TOKENS_CSS_CODE` exists: several of these
    // files carry a header explaining why the axis was removed, and an assertion that could
    // not tell a rule from a sentence would turn the record of the removal into a failure.
    const offenders = sourceFiles().filter((rel) =>
      readFileSync(resolve(SRC_DIR, rel), "utf8")
        .replace(/\/\*[\s\S]*?\*\//gu, "")
        .replace(/^\s*\/\/.*$/gmu, "")
        .includes("data-palette"),
    );
    expect(offenders).toEqual([]);
  });

  it("every hex in a declaration is lowercase", () => {
    // `ANNOTATION` is `#[\da-f]{6,8}` with NO `i` flag, and so is the must-annotate filter. So
    // `--brand: #BD32AF;` would be (a) not required to carry an annotation and (b) unparsable
    // as one if it did — while `colorOf` still reads it and it still clears its role's bar.
    // The token drops out of half the contract with nothing red anywhere, which is the highest
    // probability way a reskin breaks this gate green: a hex pasted out of a design tool.
    //
    // Scoped to DECLARATION VALUES rather than to the whole file, deliberately. `tokens.css`
    // quotes uppercase hexes in its prose on purpose — PlanIQ's kit writes `#75FC96` and the
    // header says so when it explains what became of it — so a whole-file assertion would be
    // red on documentation that is doing its job.
    const shouting: string[] = [];
    for (const cell of CELLS) {
      for (const [token, value] of Object.entries(block(TOKENS_CSS, cell.selector))) {
        if (/#[\da-fA-F]*[A-F]/u.test(value)) shouting.push(`${cell.label} ${token}: ${value};`);
      }
    }
    expect(
      shouting.sort(),
      `A hex has to be lowercase to be seen by this file at all: the annotation grammar and ` +
        `the must-annotate scan are both case-SENSITIVE, so an uppercase value silently ` +
        `leaves the comment cross-check while still passing its role's bar.`,
    ).toEqual([]);
  });
});

/* ------------------------------------------------------------------------------------- *
 * The comment cross-check: every ratio tokens.css claims, recomputed, on the ground it
 * names — and that ground has to be the worst one the token's role allows.
 * ------------------------------------------------------------------------------------- */

/**
 * Each cell cross-checked against the annotations written in ITS OWN block — `annotationsIn()`
 * reads the raw block text, so a value carried by a cell but declared in another block has no
 * annotation here to be checked against, which is one more reason every block is complete.
 */
const ANNOTATED = CELLS.map((cell) => [cell.label, cell.selector, cell.tokens] as const);

describe.each(ANNOTATED)("%s: tokens.css states ratios it can prove", (_name, selector, palette) => {
  const found = annotationsIn(TOKENS_CSS, selector);

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
      //
      // TIE-AWARE, and it has to be: 16 of the 72 annotations on this tree sit on an exact
      // tie — 12 in dark, 4 in light, recounted when the palette axis was removed. A `-tint`
      // is opaque, so `--x-tint over <any surface>` composites to a byte-identical colour and
      // all five tint grounds return the same ratio to 1e-9. A
      // strict `toBe(ranked[0][0])` accepted exactly one of those five, chosen by nothing but
      // V8's stable sort plus the order `SURFACES` and `FAMILIES` happen to be written in, and
      // `tools/annotate-tokens.mts` deliberately KEEPS any tied ground rather than churning a
      // true comment into a different true comment. The two had therefore forked: repointing
      // one tied annotation makes `tokens:check` exit 0 and this assertion fail with "names X
      // but its worst ground is Y at the same ratio", which reads as a test bug and is how an
      // assertion gets relaxed. `tiedExtremeGrounds` is the same strictness stated correctly —
      // it accepts a ground only when it MEASURES the extreme, not when it sorts first.
      //
      // The ranking is `contrastRoles.mts`'s, not this file's, for the same reason the
      // arithmetic is: `tools/annotate-tokens.mts` WRITES the ground this assertion reads, so
      // a second ordering here would let the generator emit a ground the gate rejects.
      const tied = tiedExtremeGrounds(palette, annotation.token, role, annotation.best);
      const ranked = rankedGrounds(palette, annotation.token, role);
      const extreme = annotation.best ? ranked[ranked.length - 1] : ranked[0];
      expect(
        tied,
        `${annotation.token}'s comment names ${annotation.namedGround}, but its ` +
          `${annotation.best ? "best" : "worst"} ground is ${String(extreme?.[0])} at ` +
          `${String(extreme?.[1].toFixed(2))}:1. The grounds that measure that extreme, and ` +
          `which this comment may therefore name, are: ${tied.join(", ")}.`,
      ).toContain(annotation.namedGround);
    },
  );

  it("every token whose value is a literal colour carries an annotation", () => {
    // An alias (`--st-failed: var(--error)`) is measured through its target and needs no
    // number of its own. A literal hex is a new colour and must state what it measures.
    //
    // `{6,8}` and not `{6}`: `ANNOTATION` accepts an 8-digit hex, and so does the generator's
    // must-annotate scan, so a `{6}` here was the same rule written two ways — a translucent
    // ROLE token would have been a colour the grammar can annotate that nothing required to
    // be annotated. Latent rather than live on this tree (`--skeleton-sheen` is the only
    // 8-digit value and it is a GROUND, so the `ROLES[token] !== undefined` clause already
    // excluded it), and widened here anyway, because PlanIQ's kit leans on alpha and the
    // moment a `#75fc961f` becomes a role token is not the moment to be discovering this.
    const literal = Object.entries(block(TOKENS_CSS, selector))
      .filter(([token, value]) => /^#[\da-f]{6,8}$/u.test(value) && ROLES[token] !== undefined)
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
 * never can be: it is 2.94:1 at its ceiling, taken across both cells, so it fails
 * 1.4.11's 3:1 as well as 1.4.3's
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
 * Every file that can paint with a token: `.ts`, `.tsx`, `.mts` AND `.css`.
 *
 * The `.css` half is not hypothetical hygiene — `index.css` paints a scrollbar thumb with
 * `--ink-mark` today, and ESLint's copy of this rule cannot see it. `tokens.css` is included
 * as well: the DEFINITIONS there (`--ink-rule: #adadb4;`) are not uses and do not match.
 *
 * The `.mts` half closes a hole this tranche OPENED. `contrastMath`, `contrastRoles` and
 * `paletteBlocks` made `.mts` a first-class source extension inside `src/` for the first
 * time, and the extension matched neither this walk nor the ESLint fence beside it — so a
 * whole extension living in `src/` was invisible to both halves of the guard. It costs
 * nothing today (no `.mts` file names either policed token as a colour) and it is added
 * before something paints there rather than after, which is the only useful moment.
 */
function sourceFiles(): readonly string[] {
  return readdirSync(SRC_DIR, { recursive: true, encoding: "utf8" })
    .map((entry) => entry.split(sep).join("/"))
    .filter(
      (rel) =>
        /\.(?:m?tsx?|css)$/u.test(rel) &&
        !/\.d\.m?ts$/u.test(rel) &&
        !/\.test\.m?tsx?$/u.test(rel) &&
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
    // does not know which ground it landed on, so the bar is the worst case across every
    // cell — and there it is 3.56:1, a legitimate mark and never a word.
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

  it("…and .mts, the extension this tranche introduced into src/", () => {
    // The same canary for the newer half of the filter. `.mts` became a source extension
    // inside `src/` with `contrastMath`/`contrastRoles`/`paletteBlocks`, and it matched
    // neither this walk nor the ESLint fence — an entire extension in `src/` that both
    // halves of the guard were blind to. Enumerating them is deliberately NOT the shape used
    // for `.css`: modules are expected to multiply and a stylesheet is not. What must not
    // change is that the walk reaches them at all, so the filter cannot be narrowed back to
    // `tsx?` by someone tidying a regex.
    expect(sourceFiles().filter((file) => file.endsWith(".mts")).length).toBeGreaterThan(0);
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

  it("every surface is redefined in every theme block — nothing inherits another's ground", () => {
    // `--bg-inset` used to be defined only in the dark palette, so every code block in the
    // light theme was a dark-first surface nobody had looked at. All five surfaces, all four
    // ink tokens and all three line tokens are redefined explicitly in every block.
    //
    // Key-set parity above is strictly stronger than this — it demands all 65 names, not these
    // twelve — and this is kept anyway, deliberately. It asks the same question by a DIFFERENT
    // mechanism: parity's required set is COMPUTED from `:root` through `isPaletteValue`, and a
    // classifier that were ever narrowed would let parity go vacuously green against a shrunken
    // key set while a block quietly lost `--surface-sunken`. A hand-named list cannot go
    // vacuous. It is the same curated-list/computed-set pairing this file's header describes,
    // and the loop is inside ONE `it` so it costs one assertion whatever the registry grows to
    // — a second opinion is a fixed cost, not a per-cell measurement.
    for (const cell of PALETTE_BLOCKS) {
      const declared = block(TOKENS_CSS, cell.selector);
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
        expect(declared[token], `${token} is not redefined in ${cell.label}`).toBeDefined();
      }
    }
  });

  it("every semantic family is redefined in every palette block, in all three members", () => {
    // The family half of the canary above, for the same reason and at the same fixed cost.
    for (const cell of PALETTE_BLOCKS) {
      const declared = block(TOKENS_CSS, cell.selector);
      for (const family of FAMILIES) {
        for (const suffix of ["", "-fill", "-tint"]) {
          expect(
            declared[`--${family}${suffix}`],
            `--${family}${suffix} misses ${cell.label}`,
          ).toBeDefined();
        }
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
