/**
 * Tailwind 3.4 — a thin projection of `src/styles/tokens.css`.
 *
 * Every colour below is `var(--token)`, never a hex literal. That is what makes the theme
 * switch work: `[data-theme="dark"]` rebinds the variables and every utility follows in the
 * same paint. A hex here would be a colour that ignores the theme, and there would be no way
 * to see that from the class name.
 *
 * `darkMode: ["class", '[data-theme="dark"]']` is deliberately NOT the default `media`
 * strategy — but the polarity has FLIPPED with the reskin. LIGHT is home now: `:root` carries
 * the light palette, an unattributed document is light, and dark is opt-in via the attribute
 * the prefs store writes onto `<html>`.
 *
 * ## The old utility names are GONE, on purpose
 *
 * `bg-bg-0…3`, `bg-bg-inset`, `text-fg-0…3`, `border-line{,-strong,-accent}`,
 * `text-violet|cyan|green|amber|orange|red|magenta|slate` (and their `-hi`/`-dim` variants),
 * `shadow-e-1…3` and `shadow-glow-*` are not defined anywhere in this file. A component still
 * naming one now FAILS TO BUILD instead of rendering an undefined colour, which is how half a
 * reskin ships. The replacements, by role:
 *
 *   bg-bg-0        → bg-surface                text-fg-0  → text-ink
 *   bg-bg-1        → bg-surface-card           text-fg-1  → text-ink-muted
 *   bg-bg-2        → bg-surface-control        text-fg-2  → text-ink-mark   (policed)
 *   bg-bg-3        → bg-surface-control-hover  text-fg-3  → text-ink-rule   (policed)
 *   bg-bg-inset    → bg-surface-sunken
 *   border-line    → border-hairline           border-line-strong → border-hairline-strong
 *   border-line-accent → border-edge (a real boundary) or drop it — this design has none
 *   text-violet    → text-brand / text-accent  bg-violet-dim → bg-brand-tint / bg-accent-tint
 *   text-green     → text-success              text-red      → text-error
 *   text-amber     → text-caution              text-orange   → text-warning
 *   text-cyan      → text-info                 text-slate    → text-neutral / text-slate
 *   shadow-e-1     → shadow-2xs                shadow-e-2/3  → shadow-overlay
 *   shadow-glow-violet → shadow-ring-brand     shadow-glow-red → shadow-ring-error
 *
 * Every hue family projects three utilities: `text-x` (text-safe, 4.5:1), `bg-x-fill` /
 * `text-x-fill` (graphic, 3:1) and `bg-x-tint` (the chip ground). Put the WORD in `text-ink`
 * and the HUE in the ground and the glyph, and both bars are cleared by construction.
 */

import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/** A semantic hue family: text-safe, graphic and tint members from one token prefix. */
const family = (token: string) => ({
  DEFAULT: `var(--${token})`,
  fill: `var(--${token}-fill)`,
  tint: `var(--${token}-tint)`,
});

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

const fromList = (prefix: string, names: readonly string[]) =>
  Object.fromEntries(names.map((name) => [name, family(`${prefix}-${name}`)]));

const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        /* Surfaces. `bg-surface` is the page ground; `bg-surface-card` is every card. */
        surface: {
          DEFAULT: "var(--surface)",
          card: "var(--surface-card)",
          sunken: "var(--surface-sunken)",
          control: "var(--surface-control)",
          "control-hover": "var(--surface-control-hover)",
          nav: "var(--surface-nav)",
          topbar: "var(--surface-topbar)",
        },
        /*
         * Ink. `text-ink` and `text-ink-muted` are the only two that may paint a character.
         * `text-ink-mark` is glyphs and marks (3:1); `text-ink-rule` is rules and inactive
         * controls (no bar at all). Both of the latter are policed by `no-restricted-syntax`
         * in eslint.config.js and measured by src/styles/tokenContrast.test.ts.
         */
        ink: {
          DEFAULT: "var(--ink)",
          muted: "var(--ink-muted)",
          mark: "var(--ink-mark)",
          rule: "var(--ink-rule)",
          "on-brand": "var(--ink-on-brand)",
        },
        /* Lines. This design draws very few; where it used to, it uses space or a shadow. */
        hairline: {
          DEFAULT: "var(--hairline)",
          strong: "var(--hairline-strong)",
        },
        /* The one border that carries meaning: a floating popover's boundary ring. */
        edge: "var(--edge)",
        focus: "var(--focus-ring)",

        /* Semantic hue families. */
        brand: { ...family("brand"), solid: "var(--brand-solid)" },
        accent: family("accent"),
        success: family("success"),
        caution: family("caution"),
        warning: family("warning"),
        error: family("error"),
        info: family("info"),
        neutral: family("neutral"),
        slate: family("slate"),

        /* Order state and pipeline status, by NAME — a component never names the hue. */
        st: fromList("st", ORDER_STATES),
        pg: fromList("pg", PIPELINE_STATUSES),
        retryable: family("retryable"),
        terminal: family("terminal"),

        /* The categorical chart ramp. Graphic only — never a text colour. */
        chart: {
          1: "var(--c-1)",
          2: "var(--c-2)",
          3: "var(--c-3)",
          4: "var(--c-4)",
          5: "var(--c-5)",
          6: "var(--c-6)",
          7: "var(--c-7)",
          8: "var(--c-8)",
        },
        skeleton: {
          DEFAULT: "var(--skeleton-base)",
          sheen: "var(--skeleton-sheen)",
        },
      },
      /*
       * Gogo's radius scale, verbatim. `rounded-card` is the 28px every panel wears and
       * `rounded-button` the 16px every button does; prefer those over the rungs.
       */
      borderRadius: {
        /* `rounded` on its own is Tailwind's 4px otherwise, and this design has no 4px
           corner anywhere. */
        DEFAULT: "var(--r-2xs)",
        "4xs": "var(--r-4xs)",
        "3xs": "var(--r-3xs)",
        "2xs": "var(--r-2xs)",
        xs: "var(--r-xs)",
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
        "2xl": "var(--r-2xl)",
        "3xl": "var(--r-3xl)",
        "4xl": "var(--r-4xl)",
        full: "var(--r-full)",
        card: "var(--r-card)",
        button: "var(--r-button)",
        control: "var(--r-control)",
        pill: "var(--r-pill)",
      },
      /*
       * Gogo's shadow scale, verbatim in light and deepened in dark (a 4%-black shadow is
       * invisible on a near-black ground — see tokens.css). `shadow-card` is the whisper
       * that replaces every card border in this design.
       */
      boxShadow: {
        /*
         * `sm`, `DEFAULT`, `xl` and `inner` are OVERRIDDEN, not merely extended. Tailwind's
         * own values for them are literal `rgb(0 0 0 / …)` — a shadow that ignores the theme,
         * which is the exact hazard the header of this file warns about, and `shadow` and
         * `shadow-xl` are one keystroke from anything a component author types.
         */
        sm: "var(--shadow-2xs)",
        DEFAULT: "var(--shadow-xs)",
        xl: "var(--shadow-2xl)",
        inner: "var(--shadow-inset)",
        "2xs": "var(--shadow-2xs)",
        xs: "var(--shadow-xs)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        "2xl": "var(--shadow-2xl)",
        "2xs-darker": "var(--shadow-2xs-darker)",
        "xs-darker": "var(--shadow-xs-darker)",
        "md-darker": "var(--shadow-md-darker)",
        "lg-darker": "var(--shadow-lg-darker)",
        "2xl-darker": "var(--shadow-2xl-darker)",
        card: "var(--shadow-card)",
        "card-hover": "var(--shadow-card-hover)",
        overlay: "var(--shadow-overlay)",
        "ring-brand": "var(--ring-brand)",
        "ring-error": "var(--ring-error)",
        "ring-success": "var(--ring-success)",
      },
      /* All three defined in `src/styles/fonts.css`, beside the faces they name. */
      fontFamily: {
        sans: "var(--font-sans)",
        heading: "var(--font-heading)",
        mono: "var(--font-mono)",
      },
      /* The Gogo type scale, as `text-hero` … `text-mono`. Also `.type-*` in index.css. */
      fontSize: {
        hero: ["40px", { lineHeight: "44px", fontWeight: "700", letterSpacing: "-0.02em" }],
        metric: ["28px", { lineHeight: "34px", fontWeight: "700", letterSpacing: "-0.01em" }],
        h1: ["26px", { lineHeight: "34px", fontWeight: "700", letterSpacing: "-0.01em" }],
        h2: ["18px", { lineHeight: "26px", fontWeight: "600" }],
        h3: ["15px", { lineHeight: "22px", fontWeight: "600" }],
        body: ["14px", { lineHeight: "22px", fontWeight: "400" }],
        "body-sm": ["13px", { lineHeight: "20px", fontWeight: "400" }],
        button: ["14px", { lineHeight: "20px", fontWeight: "500" }],
        caption: ["11px", { lineHeight: "16px", fontWeight: "600", letterSpacing: "0.06em" }],
        mono: ["13px", { lineHeight: "20px" }],
      },
      transitionDuration: {
        instant: "var(--d-instant)",
        fast: "var(--d-fast)",
        base: "var(--d-base)",
        slow: "var(--d-slow)",
        pulse: "var(--d-pulse)",
      },
      transitionTimingFunction: {
        standard: "var(--ease-standard)",
        decel: "var(--ease-decel)",
        emphasis: "var(--ease-emphasis)",
      },
      spacing: {
        nav: "var(--nav-w)",
        "nav-collapsed": "var(--nav-w-collapsed)",
        topbar: "var(--topbar-h)",
        row: "var(--row-h)",
        "row-compact": "var(--row-h-compact)",
        gutter: "var(--gutter)",
        card: "var(--card-pad)",
      },
      keyframes: {
        /* `◉ generating` is the only animated status glyph (§11.3). */
        "pulse-ring": {
          "0%,100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.55", transform: "scale(1.06)" },
        },
        /* The skeleton shimmer — 1.2s, never a centred spinner (§11.4). */
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "pulse-ring": "pulse-ring var(--d-pulse) var(--ease-standard) infinite",
        shimmer: "shimmer 1.2s linear infinite",
      },
    },
  },
  plugins: [animate],
};

export default config;
