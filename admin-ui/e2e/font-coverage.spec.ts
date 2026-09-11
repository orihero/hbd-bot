/**
 * §14 Slice 1d: *"font-coverage snapshot renders `Oʻktam`, `Gʻulom`, `Дилноза`, `sanʼat`"*.
 *
 * The four strings already exist as Vitest fixtures, and those tests prove something real:
 * the codepoints survive the render path unfolded. They cannot prove the bullet's verb.
 * jsdom has no fonts, no rasteriser and no `.notdef`, so a name drawn as four hollow boxes
 * and a name drawn in Mulish are the same string to it — which is why this bullet, like the
 * CSP one next door, only closes in a browser.
 *
 * So: draw every character at 64px, fingerprint the bitmap, and compare it with a codepoint
 * from an unassigned Unicode plane that nothing on earth covers. Same bitmap means the
 * browser drew the same box, which means tofu.
 *
 * **The negative controls are the teeth, and they are permanent.** A check is only worth
 * running if it can fail, so two codepoints from that unassigned plane are measured
 * alongside the real ones, per stack, every run: both must paint ink, and both must paint
 * the *same* ink. A browser that stopped drawing `.notdef` boxes, or that drew a different
 * box per Unicode block, fails here — rather than quietly certifying every character on the
 * page. Aimed at a string of unassigned codepoints the check reports them by name:
 * `U+50000 (񐀀) advance=64.22px ink=3592px signature=3592:32e2d83d … drawn as .notdef`.
 *
 * ── THE PART THAT WAS MISSING, AND IS THE POINT OF THIS FILE NOW ───────────────────────
 *
 * This gate used to say, in its own header, that §12.1 T7 promised self-hosted faces and
 * the build shipped none — so coverage was "the host's rather than the bundle's". That is a
 * gate certifying the laptop it ran on. It would have gone green on a machine with Noto
 * installed and red on a bare CI container, and neither result would have been about this
 * repository.
 *
 * `src/styles/fonts.css` now self-hosts four woff2 faces. So "nothing is tofu" is no longer
 * the interesting question — a Mac draws every one of these strings beautifully with no help
 * from us at all. The question is **which font drew it**, and the second half of this spec
 * asks exactly that, per character, per face, by rasterising each one twice: once with the
 * face leading the stack and once with every self-hosted family struck out of it. Different
 * bitmap, our font drew it. Identical bitmap, the browser walked straight past us to the
 * host. `e2e/fonts.ts` carries the method.
 *
 * **Its negative control is a real coverage hole, not a synthetic one.** Urbanist — the
 * reskin's heading face — has no Cyrillic whatsoever; the upstream family ships latin and
 * latin-ext and stops. So this file asserts that Urbanist DOES draw `Oʻktam` and DOES NOT
 * draw `Дилноза`. The day somebody breaks the discriminator into always answering "ours
 * drew it", that assertion is what turns red. It is why `--font-heading` names Mulish
 * directly behind Urbanist, and it is why nobody may shorten that stack.
 *
 * It runs against `/login`, unauthenticated: the shell, the bundle's one stylesheet and the
 * design tokens are all present before anybody signs in, and coverage is a property of the
 * document rather than of a session. Keeping it out of `smoke.spec.ts` keeps that file what
 * its own header says it is — one operator's session, asserted as a whole.
 *
 * There is deliberately **no golden PNG.** Font rasterisation differs by OS, by version and
 * by hinting settings; a checked-in baseline image would fail on the next machine for a
 * reason that is not a regression, and the pressure would be to delete it. The measurement
 * is the assertion; the screenshot is attached to the report as evidence a human can look at.
 */

import { expect, test } from "@playwright/test";

import {
  MISSING_GLYPH_CONTROLS,
  PROBE_TEST_ID,
  SELF_HOSTED_FACES,
  loadSelfHostedFaces,
  measureProvenance,
  measureStack,
  readFontOrigins,
  renderSamples,
  type FontSample,
  type GlyphMeasurement,
  type ProvenanceCoverage,
  type StackCoverage,
} from "./fonts";
import { readManifest } from "./manifest";

const manifest = readManifest();
const { names } = manifest;

/**
 * The three token stacks. All three must draw all four strings: names head a page, fill a
 * table and appear in mono columns.
 */
const FONT_VARIABLES = ["--font-sans", "--font-heading", "--font-mono"] as const;

/** The bullet's four strings, in the bullet's order. */
const SAMPLES: readonly { readonly label: string; readonly text: string }[] = [
  { label: "Oʻktam", text: names.oktam },
  { label: "Gʻulom", text: names.gulom },
  { label: "Дилноза", text: names.dilnoza },
  { label: "sanʼat", text: names.sanat },
];

/**
 * The codepoints the bullet is really about, and the reason it names four strings rather
 * than one. U+02BB and U+02BC are different characters that look alike and are covered
 * independently; Cyrillic is a whole other script. A font can carry any one and miss the
 * others.
 */
const REQUIRED_CODEPOINTS = ["U+02BB", "U+02BC"] as const;

/** Every distinct character across the four strings — what actually gets rasterised. */
const CHARACTERS: readonly string[] = Array.from(
  new Set(SAMPLES.flatMap((sample) => Array.from(sample.text))),
);

/** The Latin half of those characters, and the Cyrillic half. Urbanist is asked about both. */
const CYRILLIC_CHARACTERS = CHARACTERS.filter((character) => /\p{Script=Cyrillic}/u.test(character));
const LATIN_CHARACTERS = CHARACTERS.filter(
  (character) => !/\p{Script=Cyrillic}/u.test(character),
);

/**
 * §11.3's status glyphs, and the reason a fourth face is vendored at all.
 *
 * "Status pills are never colour alone — glyph + text + colour." Neither Mulish nor Urbanist
 * contains ONE of these; before `bayram-status-symbols.woff2` they were drawn by whatever
 * symbol font the operator's OS happened to ship, which is fine on a Mac and is a row of
 * hollow boxes on a bare container. A pill whose glyph is tofu IS colour alone.
 *
 * The lock is included and is not decoration: §12.3's purged record renders `🔒 purged
 * <date>`, and it is graded.
 */
const STATUS_GLYPHS: readonly { readonly glyph: string; readonly meaning: string }[] = [
  { glyph: "○", meaning: "draft" },
  { glyph: "◔", meaning: "brief_ready" },
  { glyph: "◑", meaning: "lyrics_ready" },
  { glyph: "◆", meaning: "authorized" },
  { glyph: "◉", meaning: "generating" },
  { glyph: "✓", meaning: "delivered" },
  { glyph: "✗", meaning: "failed" },
  { glyph: "⊘", meaning: "cancelled" },
  { glyph: "⚑", meaning: "held" },
  { glyph: "↻", meaning: "retryable" },
  { glyph: "■", meaning: "terminal" },
  { glyph: "🔒", meaning: "purged" },
];

function describe(glyph: GlyphMeasurement): string {
  return (
    `${glyph.codepoint} (${glyph.character}) advance=${glyph.advanceWidthPx.toFixed(2)}px ` +
    `ink=${String(glyph.inkPixels)}px signature=${glyph.signature}`
  );
}

/** The characters whose bitmap is a control's — i.e. the ones drawn as `.notdef`. */
function tofu(coverage: StackCoverage): GlyphMeasurement[] {
  const boxes = new Set(coverage.controls.map((control) => control.signature));
  return coverage.glyphs.filter((glyph) => boxes.has(glyph.signature));
}

/** One line per character, for a provenance failure that says what was compared. */
function describeProvenance(coverage: ProvenanceCoverage): string {
  return coverage.glyphs
    .map(
      (glyph) =>
        `  ${glyph.codepoint} (${glyph.character}) ` +
        `with="${coverage.family}" → ${glyph.withFamily}  ` +
        `without → ${glyph.withoutFamily}  ` +
        (glyph.drawnByFamily ? "ours" : "THE HOST'S"),
    )
    .join("\n");
}

test("the four acceptance strings render with real glyphs, not tofu", async ({ page }, testInfo) => {
  const origin = new URL(manifest.baseUrl).origin;
  const offOrigin: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(origin) && !url.startsWith("data:") && !url.startsWith("about:")) {
      offOrigin.push(url);
    }
  });

  await page.goto("/login");
  await expect(page.getByTestId("login-form")).toBeVisible();

  // Every self-hosted face, forced to load with the text it will be measured against.
  // `document.fonts.ready` alone would not do it: a face is fetched only when a character it
  // can serve is laid out, and `ctx.font` matches only fonts that are ALREADY loaded — so
  // without this the canvas would quietly measure the fallback and report it as ours. The
  // status face narrows further still, with a `unicode-range` that keeps it out of prose.
  const statusText = STATUS_GLYPHS.map((entry) => entry.glyph).join("");
  const sampleText = SAMPLES.map((sample) => sample.text).join("");
  const faces = await loadSelfHostedFaces(page, [
    { family: "Mulish", text: sampleText },
    { family: "Urbanist", text: sampleText },
    { family: "Noto Sans Mono", text: sampleText },
    { family: "Bayram Status Symbols", text: statusText },
  ]);

  await test.step("§12.1 T7: the faces are self-hosted, and nothing comes from anywhere else", async () => {
    const fonts = await readFontOrigins(page);
    testInfo.annotations.push({
      type: "font-origins",
      description:
        `document.fonts=[${fonts.loadedFaces.join(", ")}] ` +
        `@font-face src=[${fonts.fontFaceSources.join(" | ")}] ` +
        `stylesheets=[${fonts.stylesheetHrefs.join(", ")}] ` +
        `preload=[${fonts.fontPreloadHrefs.join(", ")}]`,
    });

    // The half T7 promised and the build never delivered. An empty list here means the
    // console is back to naming families it does not ship, and every measurement below
    // would be of the host — green on a developer's Mac, red on a CI container, and about
    // neither. This assertion is what stops that regressing quietly.
    expect(
      fonts.fontFaceSources.length,
      "the document declares no @font-face at all: nothing is self-hosted and this whole " +
        "gate is measuring the host's fonts. See src/styles/fonts.css.",
    ).toBeGreaterThanOrEqual(SELF_HOSTED_FACES.length);

    for (const family of SELF_HOSTED_FACES) {
      const loaded = faces.filter(
        (face) => face.family.replace(/^["']|["']$/g, "") === family && face.status === "loaded",
      );
      expect(
        loaded.length,
        `${family} is not a loaded FontFace. document.fonts holds: ` +
          faces.map((face) => `${face.family}=${face.status}`).join(", "),
      ).toBeGreaterThan(0);
    }

    // A cross-origin sheet is the only thing that makes `cssRules` throw, so an unreadable
    // sheet IS the finding — there is nothing to inspect and nothing that should be there.
    expect(
      fonts.unreadableSheetHrefs,
      "a cross-origin stylesheet reached the console",
    ).toHaveLength(0);
    for (const href of fonts.stylesheetHrefs) {
      expect(href, "a stylesheet is served from another origin").toContain(origin);
    }
    for (const src of fonts.fontFaceSources) {
      expect(src, "an @font-face pulls its font from another origin").not.toMatch(
        /url\(\s*['"]?https?:\/\//i,
      );
      // `data:` is not `'self'`. The CSP names it for `img-src` and for nothing else, so a
      // font Vite inlined under `assetsInlineLimit` would be REFUSED and the face would
      // silently fall through to the host — see the comment on that option in vite.config.ts.
      expect(
        src,
        "an @font-face was inlined as a data: URI, which `default-src 'self'` refuses",
      ).not.toMatch(/url\(\s*['"]?data:/i);
    }

    // The build injects exactly one, at the top of <head>, pointing at the hashed body face.
    expect(
      fonts.fontPreloadHrefs,
      "the body face is not preloaded — see preloadBodyFont() in vite.config.ts",
    ).toHaveLength(1);
    expect(fonts.fontPreloadHrefs[0]).toContain(`${origin}/assets/`);
    expect(fonts.fontPreloadHrefs[0]).toMatch(/\.woff2$/);

    // The network's own account of it, which no amount of CSS inspection can talk round.
    expect(offOrigin, `the page fetched from off-origin hosts:\n${offOrigin.join("\n")}`).toEqual(
      [],
    );
  });

  for (const variable of FONT_VARIABLES) {
    await test.step(`every character is drawn by ${variable}`, async () => {
      const coverage = await measureStack(page, {
        variable,
        characters: CHARACTERS,
        controls: MISSING_GLYPH_CONTROLS,
      });
      testInfo.annotations.push({
        type: `coverage ${variable}`,
        description:
          `${coverage.resolvedFont} · controls ${coverage.controls.map(describe).join(" · ")}`,
      });

      // The stack the console actually declares, not the canvas default. `ctx.font` keeps
      // its previous value when the shorthand fails to parse, so a `10px sans-serif` here
      // would mean the whole measurement was of the wrong font.
      expect(coverage.stack, `${variable} is not defined on :root`).not.toBe("");
      expect(
        coverage.resolvedFont,
        `the browser refused the ${variable} stack and measured its own default instead`,
      ).toMatch(/^64px /);

      // THE TEETH, and the reason this check can fail rather than merely pass. Both
      // controls are codepoints from an unassigned plane, so both MUST be tofu; if the
      // browser drew nothing for them, or drew two different things, then bitmap equality
      // does not mean "missing glyph" on this platform and every assertion below is
      // decoration. Asserted per stack, because the fallback face differs between them.
      const [first, second] = coverage.controls;
      expect(first, "no control glyph was measured").toBeDefined();
      expect(second, "the second control glyph was not measured").toBeDefined();
      for (const control of coverage.controls) {
        expect(
          control.inkPixels,
          `the guaranteed-missing ${control.codepoint} painted nothing, so a .notdef box is ` +
            "not what this browser draws for an unknown character and the tofu test has no teeth",
        ).toBeGreaterThan(0);
      }
      expect(
        second?.signature,
        "two codepoints nothing covers drew two different boxes, so an identical bitmap is " +
          "not evidence of a missing glyph on this platform",
      ).toBe(first?.signature);

      for (const glyph of coverage.glyphs) {
        expect(glyph.advanceWidthPx, `${describe(glyph)} advanced no width`).toBeGreaterThan(0);
        expect(glyph.inkPixels, `${describe(glyph)} painted nothing`).toBeGreaterThan(0);
      }

      const missing = tofu(coverage);
      expect(
        missing,
        missing.length === 0
          ? ""
          : `drawn as .notdef by ${variable} (${coverage.resolvedFont}):\n` +
            `${missing.map(describe).join("\n")}\n` +
            "The self-hosted faces in src/styles/fonts.css do not cover them and neither " +
            "does this host. Regenerate with admin-ui/tools/build-fonts.py.",
      ).toHaveLength(0);

      for (const codepoint of REQUIRED_CODEPOINTS) {
        const glyph = coverage.glyphs.find((candidate) => candidate.codepoint === codepoint);
        expect(glyph, `${codepoint} is not among the sampled characters`).toBeDefined();
      }
      // Cyrillic, asserted as a range rather than by listing seven letters.
      const cyrillic = coverage.glyphs.filter((glyph) => /\p{Script=Cyrillic}/u.test(glyph.character));
      expect(cyrillic.length, "no Cyrillic character was sampled").toBeGreaterThan(0);
    });
  }

  await test.step("the body face draws every character of every name, not the host", async () => {
    const coverage = await measureProvenance(page, {
      family: "Mulish",
      variable: "--font-sans",
      characters: CHARACTERS,
    });
    testInfo.annotations.push({
      type: "provenance Mulish",
      description: `stack = [${coverage.stackFamilies.join(", ")}] control = ${coverage.controlStack}`,
    });
    // Mulish must LEAD, not merely appear. A stack that names it behind a system family
    // draws body text in whatever the operator has and keeps Mulish for the leftovers.
    expect(
      coverage.position,
      `--font-sans must begin with Mulish; it is [${coverage.stackFamilies.join(", ")}]`,
    ).toBe(0);
    // And it must end somewhere generic. A stack whose last entry is a named family is a
    // stack that has no answer at all for a codepoint nobody in it covers.
    expect(
      coverage.stackFamilies.at(-1),
      "--font-sans does not end in a generic family",
    ).toBe("sans-serif");
    const host = coverage.glyphs.filter((glyph) => !glyph.drawnByFamily);
    expect(
      host,
      `Mulish did not supply these, so the operator's machine did — and a machine without ` +
        `them draws tofu:\n${describeProvenance(coverage)}`,
    ).toHaveLength(0);
  });

  await test.step("the mono face draws them too: names appear in mono columns", async () => {
    const coverage = await measureProvenance(page, {
      family: "Noto Sans Mono",
      variable: "--font-mono",
      characters: CHARACTERS,
    });
    expect(
      coverage.position,
      `--font-mono must begin with Noto Sans Mono; it is [${coverage.stackFamilies.join(", ")}]`,
    ).toBe(0);
    expect(
      coverage.stackFamilies.at(-1),
      "--font-mono does not end in a generic family",
    ).toBe("monospace");
    const host = coverage.glyphs.filter((glyph) => !glyph.drawnByFamily);
    expect(
      host,
      "Noto Sans Mono did not supply these. It replaced JetBrains Mono precisely because " +
        "JetBrains Mono has no U+02BB and no Ғ/Қ/Ҳ, and a mono face that cannot spell an " +
        `Uzbek name is the defect §12.1 T7 thought it was preventing:\n` +
        describeProvenance(coverage),
    ).toHaveLength(0);
  });

  await test.step("Urbanist draws the Latin names — and provably does NOT draw the Cyrillic one", async () => {
    // THE PROVENANCE CHECK'S OWN NEGATIVE CONTROL, and the reason it is worth running.
    //
    // Urbanist has no Cyrillic at all. So this step asserts a positive and a negative
    // against the same face in the same run: it must supply U+02BB and U+02BC, and it must
    // supply none of `Дилноза`. If the discriminator ever degrades into answering "ours
    // drew it" for everything — a control stack that accidentally kept a self-hosted family,
    // a fingerprint that stopped distinguishing bitmaps — the second half of this step is
    // what goes red, while every other assertion in the file carries on passing.
    const latin = await measureProvenance(page, {
      family: "Urbanist",
      variable: "--font-heading",
      characters: LATIN_CHARACTERS,
    });
    // THE ORDER IS THE REQUIREMENT. Urbanist first because it is the display face; Mulish
    // immediately behind it because it is the only self-hosted face in this stack that can
    // draw Дилноза. Asserted by position, so "shorten the heading stack to Urbanist,
    // sans-serif" fails here rather than three months later in a screenshot.
    expect(
      latin.stackFamilies.slice(0, 2),
      `--font-heading must be Urbanist then Mulish; it is [${latin.stackFamilies.join(", ")}]`,
    ).toEqual(["Urbanist", "Mulish"]);
    expect(
      latin.stackFamilies.at(-1),
      "--font-heading does not end in a generic family",
    ).toBe("sans-serif");
    const notFromUrbanist = latin.glyphs.filter((glyph) => !glyph.drawnByFamily);
    expect(
      notFromUrbanist,
      `Urbanist should draw every Latin character of Oʻktam, Gʻulom and sanʼat, U+02BB and ` +
        `U+02BC included:\n${describeProvenance(latin)}`,
    ).toHaveLength(0);

    const cyrillic = await measureProvenance(page, {
      family: "Urbanist",
      variable: "--font-heading",
      characters: CYRILLIC_CHARACTERS,
    });
    expect(cyrillic.glyphs.length, "no Cyrillic character was measured").toBeGreaterThan(0);
    const unexpectedlyFromUrbanist = cyrillic.glyphs.filter((glyph) => glyph.drawnByFamily);
    expect(
      unexpectedlyFromUrbanist,
      "Urbanist reported drawing Cyrillic. Its cmap contains no codepoint in U+0400-04FF — " +
        "verified against the binary by admin-ui/tools/build-fonts.py — so either the face " +
        "was replaced, or this provenance check can no longer tell our font from the host's " +
        `and every other assertion in this file is decoration:\n${describeProvenance(cyrillic)}`,
    ).toHaveLength(0);

    // …and the stack must therefore hand Cyrillic to a face we DO ship. That is Mulish,
    // named second in `--font-heading` for this reason alone.
    const rescued = await measureProvenance(page, {
      family: "Mulish",
      variable: "--font-heading",
      characters: CYRILLIC_CHARACTERS,
    });
    const stranded = rescued.glyphs.filter((glyph) => !glyph.drawnByFamily);
    expect(
      stranded,
      "Urbanist cannot draw Cyrillic and Mulish did not pick it up, so a Cyrillic name in a " +
        "page heading is being drawn by the operator's machine. `--font-heading` must name " +
        `Mulish directly behind Urbanist:\n${describeProvenance(rescued)}`,
    ).toHaveLength(0);
  });

  await test.step("§11.3's status glyphs come from the vendored symbol face", async () => {
    const coverage = await measureProvenance(page, {
      family: "Bayram Status Symbols",
      variable: "--font-sans",
      characters: STATUS_GLYPHS.map((entry) => entry.glyph),
    });
    const host = coverage.glyphs.filter((glyph) => !glyph.drawnByFamily);
    const named = host
      .map((glyph) => {
        const entry = STATUS_GLYPHS.find((candidate) => candidate.glyph === glyph.character);
        return `${glyph.codepoint} ${glyph.character} (${entry?.meaning ?? "?"})`;
      })
      .join(", ");
    expect(
      host,
      "these status glyphs came from the host rather than bayram-status-symbols.woff2, so on a " +
        `machine without them the pill is colour alone: ${named}\n` +
        describeProvenance(coverage),
    ).toHaveLength(0);
    for (const glyph of coverage.glyphs) {
      expect(
        glyph.inkPixels,
        `${glyph.codepoint} painted nothing at all`,
      ).toBeGreaterThan(0);
    }
  });

  await test.step("the strings appear on the page, in the console's own tokens", async () => {
    const entries: FontSample[] = FONT_VARIABLES.flatMap((variable) =>
      SAMPLES.map((sample) => ({ label: sample.label, text: sample.text, variable })),
    );
    const rendered = await renderSamples(page, entries);
    expect(rendered).toHaveLength(entries.length);

    for (const [index, sample] of rendered.entries()) {
      const source = entries[index];
      expect(source).toBeDefined();
      // The DOM holds the codepoints it was given: no fold, no NFKD, no re-encode. The same
      // invariant `smoke.spec.ts` asserts on the ⌘K input, here on rendered text.
      expect(sample.readBack, `${sample.label} was rewritten on its way into the DOM`).toBe(
        source?.text,
      );
      expect(sample.widthPx, `${sample.label} laid out to nothing`).toBeGreaterThan(0);
      expect(sample.characterWidthsPx).toHaveLength(source?.text.length ?? 0);
      for (const width of sample.characterWidthsPx) {
        expect(width, `a character of ${sample.label} laid out to zero width`).toBeGreaterThan(0);
      }
    }

    // Evidence, not a baseline. See this file's header for why there is no golden PNG.
    await testInfo.attach("font-coverage.png", {
      body: await page.getByTestId(PROBE_TEST_ID).screenshot(),
      contentType: "image/png",
    });
  });
});
