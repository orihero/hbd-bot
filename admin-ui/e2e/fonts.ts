/**
 * Glyph coverage, measured in a real browser — the half of §14 Slice 1d's font bullet that
 * jsdom structurally cannot do.
 *
 * `Oʻktam`, `Gʻulom`, `Дилноза` and `sanʼat` are already Vitest fixtures
 * (`src/components/domain/fixtures.ts`), and those tests are worth having: they prove the
 * strings survive the render path as codepoints. What they cannot prove is that anything is
 * *drawn*. jsdom has no font stack, no rasteriser and no `.notdef`, so a `Дилноза` rendered
 * as four tofu boxes and a `Дилноза` rendered in Mulish are the same string to it. The
 * acceptance bullet says "renders", and rendering is a browser fact.
 *
 * **How a missing glyph is detected.** Every font has a `.notdef` glyph — the hollow box —
 * and the browser draws it for any codepoint no font in the fallback chain covers. So the
 * test rasterises each character at 64px into an offscreen canvas, reduces the bitmap to a
 * fingerprint (painted-pixel count plus an FNV-1a hash of their positions), and compares it
 * with the fingerprint of a **control codepoint that no font on earth covers** — one from
 * an entirely unassigned plane. Identical bitmap means the browser drew the same box, which
 * means the character is tofu.
 *
 * That control is also what gives the check teeth, permanently rather than once: the spec
 * asserts the control itself is detected as missing and that it painted ink. If a future
 * browser stops drawing a box for unknown codepoints, this file's own negative control goes
 * red instead of the whole check quietly passing everything.
 *
 * ── WHAT CHANGED, AND WHY IT MATTERS ───────────────────────────────────────────────────
 *
 * This file used to end with a paragraph headed "What this cannot check, and it is a real
 * gap": §12.1 T7 promised "no CDN links for fonts or scripts — self-hosted Inter and
 * JetBrains Mono, which also guarantees U+02BB/U+02BC and Cyrillic coverage", and only the
 * no-CDN half had shipped. No binary was served, `--font-sans` was a list of family names
 * the operator's machine might happen to have, and so **this gate measured the host rather
 * than the bundle**. It certified whichever laptop ran it. On a bare Linux container it
 * would have gone red for a reason that was not a regression, and the pressure would have
 * been to delete it.
 *
 * That gap is closed. `src/styles/fonts.css` self-hosts four woff2 faces out of
 * `src/assets/fonts/`, and this file grew a second measurement to match — because "no tofu"
 * was never the assertion anybody actually wanted. A page can be free of tofu and still be
 * drawing every Uzbek name in whatever the OS reached for. So alongside "was anything
 * drawn?" the gate now asks **"which font drew it?"**, and the method is
 * :func:`measureProvenance`:
 *
 *   Rasterise one character twice — once in `"<family>", <rest of the stack>` and once in
 *   `<rest of the stack>` alone, with every self-hosted family stripped out. If the two
 *   bitmaps differ, `<family>` supplied the glyph. If they are identical, `<family>` had
 *   nothing for that codepoint and the browser fell through to the host either way.
 *
 * Both halves of that need a fallback that is *the same fallback*, which is why the control
 * is the real stack minus our families rather than a bare `sans-serif`: comparing against a
 * different chain would make every difference ambiguous.
 *
 * **And this method has a permanent, real negative control — not a synthetic one.**
 * Urbanist, the reskin's heading face, genuinely has no Cyrillic: not one codepoint in
 * U+0400-04FF. So the spec asserts Urbanist draws `Oʻktam` and does NOT draw `Дилноза`. A
 * change that made the discriminator answer "yes, ours drew it" for everything would turn
 * that assertion red rather than sail through. It is the check checking itself, against a
 * coverage hole that is a fact about a file in this repository.
 *
 * The host's own fonts are still permitted to exist and are still measured: the last
 * entries of every stack are system families, and a codepoint outside all four self-hosted
 * subsets is meant to reach them. What may not happen is one of the four acceptance
 * strings, or one of §11.3's status glyphs, arriving there.
 */

import type { Page } from "@playwright/test";

/**
 * Two codepoints no font covers: plane 5 is entirely unassigned, and — unlike the tempting
 * candidates in plane 14 — nothing in it is `Default_Ignorable_Code_Point`, so the browser
 * draws a box rather than nothing at all.
 *
 * There are two, adjacent, because the whole method rests on an assumption that has to be
 * checked rather than believed: that a browser draws the SAME box for every character it
 * cannot cover. Some platforms fall back to a "last resort" face whose boxes differ by
 * Unicode block, which would make bitmap equality the wrong operator. Adjacent codepoints in
 * one unassigned block are the tightest case for that, and the spec asserts the two agree
 * before it trusts a single comparison.
 */
export const MISSING_GLYPH_CONTROLS = ["\u{50000}", "\u{50001}"] as const;

/**
 * The families `src/styles/fonts.css` serves out of this repository.
 *
 * Two jobs. They are what :func:`measureProvenance` strips out of a stack to build its
 * control — a control containing one of our own faces would compare our font against our
 * font and find no difference anywhere. And they are the list the spec checks
 * `document.fonts` against, so a face that fails to load is named rather than silently
 * absorbed by the fallback chain.
 *
 * Kept in the same order as the `@font-face` rules. If a family is added there and not
 * here, the control stack keeps it and every provenance comparison involving it goes quiet.
 */
export const SELF_HOSTED_FACES = [
  "Mulish",
  "Urbanist",
  "Noto Sans Mono",
  "HBD Status Symbols",
] as const;

/** One character, rasterised. */
export interface GlyphMeasurement {
  readonly character: string;
  /** `U+02BB`, so a failure names the codepoint rather than showing an invisible diff. */
  readonly codepoint: string;
  /** `measureText().width` — 0 means the browser advanced nothing at all. */
  readonly advanceWidthPx: number;
  /** Painted pixels above the alpha floor. 0 means nothing was drawn. */
  readonly inkPixels: number;
  /** Ink count plus a hash of the painted positions: the bitmap, as one comparable string. */
  readonly signature: string;
}

/** Every sample character measured against one of the token font stacks. */
export interface StackCoverage {
  /** The custom property this stack came from — `--font-sans`, `--font-heading`, `--font-mono`. */
  readonly variable: string;
  /** The stack as the page computed it, e.g. `Mulish, "HBD Status Symbols", …`. */
  readonly stack: string;
  /** `ctx.font` after assignment. If the stack failed to parse this is the browser default. */
  readonly resolvedFont: string;
  /** The guaranteed-missing codepoints, measured the same way. The negative controls. */
  readonly controls: readonly GlyphMeasurement[];
  readonly glyphs: readonly GlyphMeasurement[];
}

export interface MeasureOptions {
  /** `--font-sans`, `--font-heading` or `--font-mono`, read off `:root` in the live document. */
  readonly variable: string;
  readonly characters: readonly string[];
  readonly controls: readonly string[];
}

/**
 * Rasterise each character in the stack `variable` resolves to, plus the control.
 *
 * Canvas rather than the DOM because a bitmap is the only honest evidence: an advance width
 * distinguishes "drew something" from "drew nothing", but a `.notdef` box has a perfectly
 * respectable advance width. The DOM half — that the strings really do appear on the page,
 * in the app's own stack — is :func:`renderSamples`.
 */
export async function measureStack(page: Page, options: MeasureOptions): Promise<StackCoverage> {
  return await page.evaluate(
    ({ variable, characters, controls }): StackCoverage => {
      const stack = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
      if (stack === "") throw new Error(`the document defines no ${variable}`);

      const size = 96;
      const fontPx = 64;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (ctx === null) throw new Error("this browser gave no 2d canvas context");
      ctx.font = `${String(fontPx)}px ${stack}`;
      const resolvedFont = ctx.font;
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#000000";

      const measure = (character: string): GlyphMeasurement => {
        ctx.clearRect(0, 0, size, size);
        const advanceWidthPx = ctx.measureText(character).width;
        // Inset from the origin so a glyph with a left side bearing or a descender is not
        // clipped by the canvas edge, which would make two different glyphs fingerprint
        // alike for a reason that has nothing to do with the font.
        ctx.fillText(character, 12, 76);
        const { data } = ctx.getImageData(0, 0, size, size);
        let inkPixels = 0;
        // FNV-1a over the indices of the painted pixels. Positions, not just a count: two
        // different glyphs can easily paint the same NUMBER of pixels.
        let hash = 0x811c9dc5;
        for (let index = 3; index < data.length; index += 4) {
          if ((data[index] ?? 0) > 8) {
            inkPixels += 1;
            hash = Math.imul(hash ^ index, 0x01000193) >>> 0;
          }
        }
        const point = character.codePointAt(0) ?? 0;
        return {
          character,
          codepoint: `U+${point.toString(16).toUpperCase().padStart(4, "0")}`,
          advanceWidthPx,
          inkPixels,
          signature: `${String(inkPixels)}:${hash.toString(16)}`,
        };
      };

      return {
        variable,
        stack,
        resolvedFont,
        controls: controls.map(measure),
        glyphs: characters.map(measure),
      };
    },
    {
      variable: options.variable,
      characters: [...options.characters],
      controls: [...options.controls],
    },
  );
}

/** One character, asked the question "did this family draw you?". */
export interface ProvenanceMeasurement {
  readonly character: string;
  readonly codepoint: string;
  /** The bitmap when the family leads the stack. */
  readonly withFamily: string;
  /** The bitmap of the same character with every self-hosted family removed. */
  readonly withoutFamily: string;
  /** Painted pixels with the family leading. 0 would mean nothing was drawn at all. */
  readonly inkPixels: number;
  /** `withFamily !== withoutFamily` — the family supplied this glyph. */
  readonly drawnByFamily: boolean;
}

export interface ProvenanceCoverage {
  readonly family: string;
  /** `--font-sans`, `--font-heading` or `--font-mono`: whose fallback tail was used. */
  readonly variable: string;
  /** The token stack with every entry in `SELF_HOSTED_FACES` struck out. */
  readonly controlStack: string;
  /** The token stack's families, in order, unquoted. What the spec asserts the order of. */
  readonly stackFamilies: readonly string[];
  /** Where `family` sits in that list. Never -1: `measureProvenance` throws first. */
  readonly position: number;
  readonly glyphs: readonly ProvenanceMeasurement[];
}

export interface ProvenanceOptions {
  /** The `@font-face` family under test — one of `SELF_HOSTED_FACES`. */
  readonly family: string;
  /** The token whose stack supplies the fallback tail both measurements share. */
  readonly variable: string;
  readonly characters: readonly string[];
}

/**
 * Ask, per character, whether `family` is the font that drew it.
 *
 * The comparison is between `"<family>", <tail>` and `<tail>`, where `<tail>` is the token
 * stack with every self-hosted family struck out. Two bitmaps, one variable: whether the
 * family is at the front. Different bitmaps mean the family won the character; identical
 * bitmaps mean it had nothing for that codepoint and the browser walked past it to the same
 * host font in both runs.
 *
 * The tail comes from the real token rather than from a hard-coded `sans-serif` for two
 * reasons. The comparison is only meaningful if both halves fall back the same way. And a
 * hard-coded control would keep passing after somebody replaced the tail of `--font-mono`
 * with something that has its own idea of U+02BB.
 *
 * Note what this does NOT claim: nothing here asserts the *host* lacks the glyph, and it
 * must not — a Mac has Дилноза in a dozen faces. It asserts the glyph came from ours.
 *
 * **And it refuses to measure a family the stack does not name.** That guard is not
 * defensive tidiness; without it this whole function is a lie by construction. It builds its
 * probe as `"<family>", <tail>` — it puts the family in front *itself* — so with the guard
 * removed it would happily report "Mulish drew every character" for a console whose
 * `--font-sans` had had Mulish deleted out of it. That exact hole was found by deleting
 * Mulish from the token and watching the suite stay green. The family must be IN the stack,
 * and `position` is returned so the spec can assert where.
 */
export async function measureProvenance(
  page: Page,
  options: ProvenanceOptions,
): Promise<ProvenanceCoverage> {
  return await page.evaluate(
    ({ family, variable, characters, ours }: {
      family: string;
      variable: string;
      characters: string[];
      ours: string[];
    }): ProvenanceCoverage => {
      const stack = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
      if (stack === "") throw new Error(`the document defines no ${variable}`);

      // Split on the commas that separate families, then drop the self-hosted ones by name.
      // Quotes are stripped for the comparison only; the entry is re-emitted verbatim so a
      // family that needs its quotes keeps them.
      const normalise = (entry: string): string => entry.trim().replace(/^["']|["']$/g, "");
      const stackFamilies = stack.split(",").map(normalise);
      const position = stackFamilies.indexOf(family);
      if (position === -1) {
        throw new Error(
          `${variable} does not name "${family}" — it is [${stackFamilies.join(", ")}]. ` +
            "Measuring provenance for a family the stack never consults would report that " +
            "our font drew a character the browser will in fact take from the host.",
        );
      }
      const tail = stack
        .split(",")
        .filter((entry) => !ours.includes(normalise(entry)))
        .map((entry) => entry.trim())
        .join(", ");
      if (tail === "") {
        throw new Error(
          `${variable} is nothing but self-hosted families, so there is no fallback to ` +
            "compare against and provenance cannot be measured",
        );
      }

      const size = 96;
      const fontPx = 64;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (ctx === null) throw new Error("this browser gave no 2d canvas context");
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#000000";

      const fingerprint = (font: string, character: string): { ink: number; signature: string } => {
        ctx.font = font;
        if (!ctx.font.startsWith(`${String(fontPx)}px `)) {
          throw new Error(`the browser refused the font shorthand ${font}`);
        }
        ctx.clearRect(0, 0, size, size);
        ctx.fillText(character, 12, 76);
        const { data } = ctx.getImageData(0, 0, size, size);
        let ink = 0;
        let hash = 0x811c9dc5;
        for (let index = 3; index < data.length; index += 4) {
          if ((data[index] ?? 0) > 8) {
            ink += 1;
            hash = Math.imul(hash ^ index, 0x01000193) >>> 0;
          }
        }
        return { ink, signature: `${String(ink)}:${hash.toString(16)}` };
      };

      const led = `${String(fontPx)}px "${family}", ${tail}`;
      const bare = `${String(fontPx)}px ${tail}`;

      return {
        family,
        variable,
        controlStack: tail,
        stackFamilies,
        position,
        glyphs: characters.map((character) => {
          const withFamily = fingerprint(led, character);
          const withoutFamily = fingerprint(bare, character);
          const point = character.codePointAt(0) ?? 0;
          return {
            character,
            codepoint: `U+${point.toString(16).toUpperCase().padStart(4, "0")}`,
            withFamily: withFamily.signature,
            withoutFamily: withoutFamily.signature,
            inkPixels: withFamily.ink,
            drawnByFamily: withFamily.signature !== withoutFamily.signature,
          };
        }),
      };
    },
    {
      family: options.family,
      variable: options.variable,
      characters: [...options.characters],
      ours: [...SELF_HOSTED_FACES] as string[],
    },
  );
}

/** What `document.fonts` says about one declared `@font-face` family. */
export interface FaceStatus {
  readonly family: string;
  /** `"unloaded" | "loading" | "loaded" | "error"`, straight off the `FontFace`. */
  readonly status: string;
}

/*
 * `FontFace` exposes no `src`, so where the binary came FROM is not readable here. That is
 * `readFontOrigins`'s job: it reads the `src` descriptor off the `CSSFontFaceRule` instead,
 * and the spec cross-checks both against the request log.
 */

/**
 * Force every self-hosted face to load, then report what `document.fonts` holds.
 *
 * `document.fonts.ready` is not enough on its own. A face is fetched lazily, when a
 * character it can serve is actually laid out, and a `unicode-range` narrows that further —
 * "HBD Status Symbols" is not requested at all until a page draws one of its nineteen
 * codepoints. A canvas probe never triggers that: `ctx.font` matches only against fonts
 * that are already loaded, so an unloaded face is invisible to it and every measurement
 * would silently be of the fallback. `load()` per family, with the text that will be
 * measured, is what makes the probe honest.
 */
export async function loadSelfHostedFaces(
  page: Page,
  requests: readonly { readonly family: string; readonly text: string }[],
): Promise<FaceStatus[]> {
  return await page.evaluate(
    async ({ entries }): Promise<FaceStatus[]> => {
      await Promise.all(
        entries.map(async (entry) => {
          await document.fonts.load(`64px "${entry.family}"`, entry.text);
        }),
      );
      await document.fonts.ready;
      const seen: FaceStatus[] = [];
      document.fonts.forEach((face) => {
        seen.push({ family: face.family, status: face.status });
      });
      return seen;
    },
    { entries: requests.map((request) => ({ ...request })) },
  );
}

/** One string to draw on the page, in one of the token stacks. */
export interface FontSample {
  /** What the failure message calls it — `Gʻulom`, `Дилноза`, … */
  readonly label: string;
  readonly text: string;
  /** `--font-sans`, `--font-heading` or `--font-mono`. */
  readonly variable: string;
}

/** What the page did with one sample, read back out of the DOM. */
export interface RenderedSample {
  readonly label: string;
  readonly variable: string;
  /** `textContent` after the render: the codepoints the DOM actually holds. */
  readonly readBack: string;
  /** The laid-out width of the whole string. */
  readonly widthPx: number;
  /** Per-character advance, from a `Range` over each character in the text node. */
  readonly characterWidthsPx: readonly number[];
}

/** The `data-testid` of the probe :func:`renderSamples` appends, so it can be screenshotted. */
export const PROBE_TEST_ID = "font-coverage-probe";

/**
 * Draw the four strings on the live page, in the console's own font tokens, and measure them.
 *
 * Styles are set through the CSSOM (`element.style.setProperty`) and never through a `style`
 * attribute or a `<style>` element: `style-src 'self' 'nonce-…'` polices markup, not the
 * object model, so this probe adds nothing the policy has to allow. That matters — a probe
 * that needed the CSP relaxed would be measuring a page nobody ships.
 */
export async function renderSamples(
  page: Page,
  samples: readonly FontSample[],
): Promise<RenderedSample[]> {
  return await page.evaluate(
    ({ samples: entries, testId }): RenderedSample[] => {
      document.querySelector(`[data-testid="${testId}"]`)?.remove();
      const probe = document.createElement("div");
      probe.setAttribute("data-testid", testId);
      probe.style.setProperty("position", "fixed");
      probe.style.setProperty("inset", "0 auto auto 0");
      probe.style.setProperty("z-index", "2147483647");
      probe.style.setProperty("padding", "16px");
      probe.style.setProperty("background", "var(--bg-0)");
      probe.style.setProperty("color", "var(--fg-0)");
      document.body.append(probe);

      const measured: RenderedSample[] = [];
      for (const entry of entries) {
        const line = document.createElement("div");
        line.style.setProperty("font-family", `var(${entry.variable})`);
        line.style.setProperty("font-size", "32px");
        line.style.setProperty("line-height", "44px");
        line.style.setProperty("white-space", "nowrap");
        line.textContent = entry.text;
        probe.append(line);

        const node = line.firstChild;
        const characterWidthsPx: number[] = [];
        if (node !== null) {
          // A Range per character rather than a span per character: wrapping each one in an
          // element would change shaping and kerning, which is exactly what is being measured.
          for (let index = 0; index < entry.text.length; index += 1) {
            const range = document.createRange();
            range.setStart(node, index);
            range.setEnd(node, index + 1);
            characterWidthsPx.push(range.getBoundingClientRect().width);
          }
        }
        measured.push({
          label: entry.label,
          variable: entry.variable,
          readBack: line.textContent,
          widthPx: line.getBoundingClientRect().width,
          characterWidthsPx,
        });
      }
      return measured;
    },
    { samples: samples.map((sample) => ({ ...sample })), testId: PROBE_TEST_ID },
  );
}

/** Where the document's fonts and stylesheets come from — the §12.1 T7 half. */
export interface FontOrigins {
  /** Families in `document.fonts`. Empty when the page declares no `@font-face` at all. */
  readonly loadedFaces: readonly string[];
  /** The `src` of every `@font-face` rule in a readable stylesheet. */
  readonly fontFaceSources: readonly string[];
  /** Every `<link rel="stylesheet">` the shell pulled in. */
  readonly stylesheetHrefs: readonly string[];
  /** Sheets whose `cssRules` threw — which only a cross-origin sheet does. */
  readonly unreadableSheetHrefs: readonly string[];
  /** `<link rel="preload" as="font">` hrefs. The build injects exactly one. */
  readonly fontPreloadHrefs: readonly string[];
}

/** Read the document's font provenance. A CDN link shows up in three of these four lists. */
export async function readFontOrigins(page: Page): Promise<FontOrigins> {
  return await page.evaluate((): FontOrigins => {
    const loadedFaces: string[] = [];
    document.fonts.forEach((face) => loadedFaces.push(face.family));

    const fontFaceSources: string[] = [];
    const unreadableSheetHrefs: string[] = [];
    for (const sheet of Array.from(document.styleSheets)) {
      let rules: CSSRuleList;
      try {
        rules = sheet.cssRules;
      } catch {
        unreadableSheetHrefs.push(sheet.href ?? "(inline)");
        continue;
      }
      for (const rule of Array.from(rules)) {
        if (rule instanceof CSSFontFaceRule) {
          fontFaceSources.push(rule.style.getPropertyValue("src"));
        }
      }
    }

    const stylesheetHrefs = Array.from(
      document.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"]'),
      (link) => link.href,
    );
    const fontPreloadHrefs = Array.from(
      document.querySelectorAll<HTMLLinkElement>('link[rel~="preload"][as="font"]'),
      (link) => link.href,
    );
    return {
      loadedFaces,
      fontFaceSources,
      stylesheetHrefs,
      unreadableSheetHrefs,
      fontPreloadHrefs,
    };
  });
}
