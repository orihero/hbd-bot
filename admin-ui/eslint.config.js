/**
 * ESLint flat config.
 *
 * The rule that matters here is `no-restricted-syntax` inside `src/components/domain/`.
 * It is not style policing — it is the product's whole premise expressed as a lint rule
 * (§11.4).
 *
 * The bot exists to pronounce and spell an Uzbek recipient's name correctly. Uzbek Latin
 * uses U+02BB MODIFIER LETTER TURNED COMMA in `oʻ` and `gʻ`, and U+02BC MODIFIER LETTER
 * APOSTROPHE in `sanʼat`.
 *
 * A CORRECTION, because the reason this rule used to give was false. It said "NFKD folds
 * U+02BB to a plain ASCII apostrophe". It does not: NFC, NFD, NFKC and NFKD are ALL the
 * identity for U+02BB and U+02BC — neither codepoint has a decomposition mapping of any
 * kind, and both round-trip through all four forms unchanged. The rule is still exactly
 * right; only its stated reason was wrong, and a wrong reason is how a correct rule gets
 * argued away. What actually destroys these names:
 *
 *   - `toLowerCase`/`toUpperCase`/`toLocaleLowerCase`/`toLocaleUpperCase` — case folding
 *     `Gʻulom` to `gʻulom` is data loss whatever the locale does to the modifier letter,
 *     and under a Turkish or Azeri locale the surrounding Latin mangles as well.
 *   - `localeCompare` — locale-sensitive collation silently equates strings this product
 *     must keep distinct.
 *   - `normalize` — harmless on these two codepoints specifically, and banned anyway,
 *     because "which form and which codepoint" is not a judgement to re-make per call site
 *     inside the render path; it is the entry point to a whole class of folding.
 *   - `text-transform: uppercase` — alters what the operator reads with no trace at all in
 *     the data.
 *
 * One accidental call anywhere in the render path and the panel is showing the operator a
 * different name from the one the customer typed — while claiming, on the very same screen,
 * that name verification passed.
 *
 * So: user content reaches the DOM through `<NameText>` and nowhere else, and inside
 * `components/domain/` these calls do not exist. Formatting numbers, dates and our own
 * closed-vocabulary labels lives in `src/lib/format.ts`, outside the fenced directory, and
 * is free to use whatever it likes on strings WE wrote.
 *
 * Note the blind spot this rule cannot cover: a `text-transform` in a plain CSS file. That
 * is written down in `src/styles/index.css` instead. Only `.type-caption` may use it, and
 * only for our own chrome labels.
 */

import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

/** The identifiers that silently destroy an Uzbek name. */
const CASE_FOLDING_METHODS = [
  "normalize",
  "toLowerCase",
  "toLocaleLowerCase",
  "toUpperCase",
  "toLocaleUpperCase",
  "localeCompare",
].join("|");

const NAME_SAFETY_RULES = [
  {
    selector: `CallExpression > MemberExpression[property.name=/^(${CASE_FOLDING_METHODS})$/]`,
    message:
      "Banned in components/domain/: case folding Gʻulom to gʻulom is data loss, and " +
      "locale-aware folding and collation mangle Uzbek Latin further. (Note: NFC/NFD/NFKC/" +
      "NFKD are all the IDENTITY for U+02BB and U+02BC — normalize is banned because it is " +
      "the entry point to folding, not because it eats the turned comma.) User content " +
      "reaches the DOM through <NameText> unmodified. If you need to compare or fold OUR " +
      "OWN strings, do it in src/lib/.",
  },
  {
    selector: "Property[key.name='textTransform']",
    message:
      "Banned in components/domain/: text-transform destroys Uzbek Latin orthography with " +
      "no trace in the data. Only .type-caption may uppercase, and only our own labels.",
  },
  {
    selector:
      "JSXAttribute[name.name='className'] Literal[value=/(^|[\\s:'\"])(uppercase|lowercase|capitalize)(\\s|$|['\"])/]",
    message:
      "Banned in components/domain/: the Tailwind case utilities are text-transform. See " +
      "the note above the rule in eslint.config.js.",
  },
  {
    selector:
      "JSXAttribute[name.name='className'] TemplateElement[value.raw=/(^|[\\s:'\"])(uppercase|lowercase|capitalize)(\\s|$|['\"])/]",
    message:
      "Banned in components/domain/: the Tailwind case utilities are text-transform. See " +
      "the note above the rule in eslint.config.js.",
  },
];

/*
 * The second `no-restricted-syntax` block, and the second one that is not style policing.
 * Re-pointed for the Gogo palette (plan §11.3 as amended 2026-09-03).
 *
 * The palette names its text tokens by ROLE — `--ink`, `--ink-muted`, `--ink-mark`,
 * `--ink-rule` — precisely because the old positional numbering did not stop two separate
 * accessibility incidents. `--fg-2` was annotated "4.6:1 — floor for real text" and was
 * actually 4.34:1, which licensed 131 sub-AA prose sites; `--fg-3` was 2.05:1 at its worst
 * and painted characters in 41 more. Both tokens are gone. Two of the four replacements are
 * still policed, and the numbers below are MEASURED against the new palette:
 *
 *   `--ink-mark` is 3.52:1 at its worst and 4.49:1 at its best in the light palette, and
 *   3.58:1 / 6.22:1 in dark, over the full ground set (five surfaces plus the nine tints
 *   composited over the card and over the page ground). It therefore clears WCAG 1.4.11's
 *   3:1 for a graphic everywhere, and never clears 1.4.3's 4.5:1 for text taken worst-case —
 *   which is the only way a surface-agnostic component can be measured, because it does not
 *   know which ground it was dropped onto. It is a MARK colour: an aria-hidden glyph beside
 *   words that already say it, a legend swatch, a scrollbar thumb.
 *
 *   `--ink-rule` is 1.75:1 to 2.23:1 in light and 1.55:1 to 2.71:1 in dark. That is under
 *   1.4.3's 4.5:1 for text AND under 1.4.11's 3:1 for a meaningful graphic, so — unlike
 *   `--ink-mark` — it cannot even be waived down to a glyph. It may paint a rule, a hairline
 *   or an INACTIVE control, the two cases WCAG itself puts outside the requirement, and
 *   nothing else.
 *
 * So `--ink-mark` paints glyphs and marks, `--ink-rule` paints rules and dead controls, and
 * every muted LABEL is `--ink-muted`, which clears 4.5:1 on every ground of both palettes
 * (4.70:1 at its worst). This rule is the fast half of the guard; the measuring half is
 * `src/styles/tokenContrast.test.ts`, which scans `src/` and fails with the real ratio. A
 * genuine mark or rule needs BOTH an `eslint-disable-next-line` here and a justified entry in
 * that file's `MARK_WAIVERS` / `RULE_WAIVERS`, whose claim is checked against the source.
 *
 * The blind spot, stated so nobody has to rediscover it: this rule parses TypeScript, so the
 * `scrollbar-color: var(--ink-mark)` in `src/styles/index.css` is invisible to it. That is a
 * real consumer, not a hypothetical one, and the scan in `tokenContrast.test.ts` reads
 * `src/**\/*.css` as well so that it is measured and waived where the measuring is done.
 */
const INK_MARK_MESSAGE =
  "--ink-mark is 3.52:1 at worst and 4.49:1 at best in light (3.58:1 / 6.22:1 in dark) — it " +
  "clears WCAG 1.4.11's 3:1 for a graphic and never 1.4.3's 4.5:1 for text, taken worst-case " +
  "across both palettes. Use --ink-muted for anything an operator reads. If this really is a " +
  "glyph or a mark, waive it here AND add it to MARK_WAIVERS in " +
  "src/styles/tokenContrast.test.ts.";

const INK_RULE_MESSAGE =
  "--ink-rule is 1.75:1 to 2.23:1 in light and 1.55:1 to 2.71:1 in dark — under WCAG 1.4.3's " +
  "4.5:1 for text and under 1.4.11's 3:1 for a graphic, so it clears no bar at all. Use " +
  "--ink-muted for anything an operator reads. It is legitimate ONLY for a rule, a hairline " +
  "or an inactive control, which needs a waiver here AND a justified entry in RULE_WAIVERS " +
  "in src/styles/tokenContrast.test.ts.";

const mutedClass = (token) => `(^|[\\s:'"])text-${token}(\\s|$|['"])`;
const mutedVar = (token) => `var\\(--${token}\\)`;

const mutedTokenRules = (token, message) => [
  { selector: `Literal[value=/${mutedClass(token)}/]`, message },
  { selector: `TemplateElement[value.raw=/${mutedClass(token)}/]`, message },
  { selector: `Literal[value=/${mutedVar(token)}/]`, message },
  { selector: `TemplateElement[value.raw=/${mutedVar(token)}/]`, message },
];

const MUTED_TEXT_RULES = [
  ...mutedTokenRules("ink-mark", INK_MARK_MESSAGE),
  ...mutedTokenRules("ink-rule", INK_RULE_MESSAGE),
];

export default tseslint.config(
  { ignores: ["dist", "node_modules", "coverage", "**/*.d.ts"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      /* The client never throws; a rejected promise nobody awaited is how it starts to. */
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      /* `catch (e: unknown)` is the shape the never-throw client is built on. */
      "@typescript-eslint/use-unknown-in-catch-callback-variable": "error",
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "Call the API through src/api/, which never throws." },
      ],

      /*
       * Four of `strictTypeChecked`'s rules are switched off deliberately, each for a reason
       * that would otherwise be re-litigated in every review:
       *
       * `no-confusing-void-expression` fights Zustand's entire idiom — `set: (x) => set({x})`
       * is the documented shape of every store action, and bracing all forty of them buys
       * nothing.
       *
       * `no-invalid-void-type` would forbid `ApiResult<void>`, which is exactly the right
       * type for `/api/auth/logout` (204, empty body) and `/healthz` (200, empty body). The
       * alternative is inventing a placeholder type for "no body", which is worse.
       *
       * `restrict-template-expressions` is left ON: it is the rule that catches
       * `${maybeUndefined}` rendering the string "undefined" into an operator's URL.
       */
      "@typescript-eslint/no-confusing-void-expression": "off",
      "@typescript-eslint/no-invalid-void-type": "off",
    },
  },
  {
    /*
     * The contrast fence. Test files are exempt because `src/styles/tokenContrast.test.ts`
     * has to name the token it is measuring, and a component's own test may assert the one
     * waived colour it paints.
     */
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": ["error", ...MUTED_TEXT_RULES],
    },
  },
  {
    /*
     * The fence. Anything under components/domain/ renders customer-written content.
     *
     * `no-restricted-syntax` is a single rule, so a later block replaces the whole option
     * list rather than adding to it: the contrast rules above have to be repeated here or
     * `components/domain/` would silently lose them.
     */
    files: ["src/components/domain/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": ["error", ...NAME_SAFETY_RULES, ...MUTED_TEXT_RULES],
    },
  },
  {
    /* src/api/ is the one place `fetch` is allowed to be named. */
    files: ["src/api/**/*.ts"],
    rules: { "no-restricted-globals": "off" },
  },
  {
    /*
     * routes.tsx exports the route table, the path constants and the `href` builders and no
     * components at all. The Fast Refresh heuristic reads the `.tsx` extension and assumes
     * otherwise; splitting the constants out to satisfy it would put the paths a page away
     * from the routes that use them, which is the opposite of the point.
     */
    files: ["src/routes.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
  {
    /*
     * The build tooling. Type-aware linting is deliberately NOT applied here: these files
     * belong to tsconfig.node.json, and pointing the app project at them makes every
     * `import.meta` and every plugin type a parse error.
     */
    files: ["*.config.ts", "*.config.js"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      globals: globals.node,
      parserOptions: { project: null },
    },
  },
  {
    /*
     * The browser gate. `e2e/` is Node code that drives Chromium, so it gets the node
     * globals and the same type-aware rules as `src/` — it is in `tsconfig.json`'s
     * `include`, so `npm run typecheck` covers it too.
     *
     * The four `no-unsafe-*` rules are relaxed for the same reason the unit-test block
     * relaxes them: `page.evaluate` returns whatever the page returned, and the manifest
     * arrives as `JSON.parse` output. Both are checked at the boundary — `readManifest`
     * validates, and every `evaluate` here has an explicit return type — and re-stating
     * that in a cast per call site buys nothing.
     */
    files: ["e2e/**/*.ts"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: globals.node,
      parserOptions: {
        project: ["./tsconfig.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-return": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
  {
    files: ["src/test/**/*.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-empty-function": "off",
      "no-restricted-globals": "off",
    },
  },
);
