import type { Config } from "tailwindcss";

/**
 * Every value here is a `var(--token)` reference, never a literal. `src/styles/tokens.css`
 * is the single place a colour is decided; this file only gives the tokens utility names.
 *
 * No `darkMode` strategy either, and that is now a positive choice rather than a consequence
 * of there being one palette. There are two — `tokens.css` carries a `[data-theme="dark"]`
 * block and `state/theme.ts` writes the attribute — but every utility below already resolves
 * through a `var(--token)`, so the attribute reskins the whole app with no `dark:` variant
 * anywhere. A `darkMode` setting would only buy the ability to write `dark:bg-card`, which is
 * the shape that lets a component hold a palette decision the token file cannot see.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        card: "var(--card)",
        stroke: "var(--stroke)",
        "ink-900": "var(--ink-900)",
        "ink-800": "var(--ink-800)",
        "ink-500": "var(--ink-500)",
        "ink-400": "var(--ink-400)",
        "ink-300": "var(--ink-300)",
        accent: "var(--accent)",
        "accent-12": "var(--accent-12)",
        "accent-deep": "var(--accent-deep)",
        "on-accent": "var(--on-accent)",
        gridline: "var(--gridline)",
        label: "var(--label)",
        muted: "var(--muted)",
        required: "var(--required)",
        "required-24": "var(--required-24)",
        "required-06": "var(--required-06)",
        "checkbox-stroke": "var(--checkbox-stroke)",
        "required-deep": "var(--required-deep)",
        "cell-2": "var(--cell-2)",
        "row-hover": "var(--row-hover)",
        overlay: "var(--overlay)",
        "warn-deep": "var(--warn-deep)",
        /* Grounds, not ink: the kit's badge fill, the avatar's status dots, the caution tint
           --warn-deep is written on. Every one is declared in tokens.css. */
        "accent-70": "var(--accent-70)",
        "status-ok": "var(--status-ok)",
        warn: "var(--warn)",
        "warn-18": "var(--warn-18)",
        wordmark: "var(--wordmark)",
        d0: "var(--d0)",
        d1: "var(--d1)",
        d2: "var(--d2)",
        d3: "var(--d3)",
        d4: "var(--d4)",
        d5: "var(--d5)",
        d6: "var(--d6)",
      },
      borderRadius: {
        card: "var(--r-card)",
        pill: "var(--r-pill)",
        chip: "var(--r-chip)",
        seg: "var(--r-seg)",
        field: "var(--r-field)",
        panel: "var(--r-panel)",
        button: "var(--r-button)",
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
        field: "var(--shadow-field)",
      },
      fontFamily: {
        sans: ["var(--font)"],
        wordmark: ["var(--font-wordmark)"],
      },
    },
  },
  plugins: [],
} satisfies Config;
