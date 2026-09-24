import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "**/*.d.ts"] },
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
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      /* The client never throws; a rejected promise nobody awaited is how it starts to. */
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/use-unknown-in-catch-callback-variable": "error",
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "Call the API through src/api/, which never throws." },
      ],
      /* Zustand's documented action idiom is `(x) => set({x})`; bracing every one buys nothing. */
      "@typescript-eslint/no-confusing-void-expression": "off",
      /* `ApiResult<void>` is the right type for logout's empty 204. */
      "@typescript-eslint/no-invalid-void-type": "off",
    },
  },
  {
    /* src/api/ is the one place `fetch` is allowed to be named. */
    files: ["src/api/**/*.ts"],
    rules: { "no-restricted-globals": "off" },
  },
  {
    /* The built-shell CSP gate. It is not under src/, so the block above never reached it and
       `eslint .` reported green on a file nobody was linting — the same silence that let it go
       untypechecked. It is a security gate, so it is held to src/'s type-aware rules, parsed
       against tsconfig.node.json (the project that now includes it) rather than tsconfig.json
       (which includes only src). Node globals, not browser: it runs under `tsx`. */
    files: ["tests/built-shell-csp.ts"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.node,
      parserOptions: {
        project: ["./tsconfig.node.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ["*.config.ts", "*.config.js"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      globals: globals.node,
      parserOptions: { project: null },
    },
  },
);
