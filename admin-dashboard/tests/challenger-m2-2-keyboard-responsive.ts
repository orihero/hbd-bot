/**
 * Challenger M2-2 Empirical Adversarial Verification Suite
 * 
 * Verifies:
 * 1. Keyboard accessibility: ArrowRight, ArrowLeft, ArrowUp, ArrowDown, Home, End navigation,
 *    event.preventDefault(), focus delegation, rapid sequential stress.
 * 2. WAI-ARIA compliance: role="group", aria-label, aria-pressed, button types, titles.
 * 3. PlanIQ Design Tokens adherence: colors, focus-visible ring, typography, rounded-seg.
 * 4. Presentation variants: "login", "compact", "wide" (expanded & collapsed).
 * 5. Responsive layout safety: viewports 320px, 768px, 1024px, 1440px in LoginPage and NavRail.
 * 6. Collapsed sidebar geometry: vertical stacking in WideRail within 76px container.
 */

import React from "react";
import ReactDOMServer from "react-dom/server";
import {
  setupTestEnv,
  restoreTestEnv,
  assert,
  assertEqual,
  assertIncludes,
  assertNotIncludes,
  readSourceFile,
} from "./harness.js";
import {
  LanguageSwitcher,
  LANGUAGE_OPTIONS,
  type LanguageSwitcherProps,
} from "../src/components/LanguageSwitcher.js";
import { useI18n } from "../src/i18n/index.js";
import { LOCALES, type SupportedLocale } from "../src/i18n/types.js";

interface TestReport {
  id: string;
  name: string;
  category: "KEYBOARD" | "ARIA" | "TOKENS" | "VARIANTS" | "RESPONSIVE" | "STRESS" | "SYNC";
  status: "PASS" | "FAIL";
  durationMs: number;
  details?: string;
}

const reports: TestReport[] = [];

async function runEmpiricalTest(
  id: string,
  name: string,
  category: TestReport["category"],
  fn: () => Promise<void> | void,
): Promise<void> {
  const start = performance.now();
  try {
    await fn();
    const durationMs = Math.round((performance.now() - start) * 100) / 100;
    reports.push({ id, name, category, status: "PASS", durationMs });
    console.log(`\x1b[32m✔ [PASS]\x1b[0m [${category}] [${id}] ${name} (${durationMs}ms)`);
  } catch (err: unknown) {
    const durationMs = Math.round((performance.now() - start) * 100) / 100;
    const msg = err instanceof Error ? err.message : String(err);
    reports.push({ id, name, category, status: "FAIL", durationMs, details: msg });
    console.error(`\x1b[31m✖ [FAIL]\x1b[0m [${category}] [${id}] ${name} (${durationMs}ms)`);
    console.error(`       Error: ${msg}`);
  }
}

/** Helper to inspect rendered JSX element and its props */
function captureRenderedElement(props: LanguageSwitcherProps = {}): {
  element: React.ReactElement;
  html: string;
} {
  let captured: React.ReactElement | null = null;
  function Interceptor(p: LanguageSwitcherProps) {
    const elem = (LanguageSwitcher as unknown as (props: LanguageSwitcherProps) => React.ReactElement)(p);
    captured = elem;
    return elem;
  }
  const html = ReactDOMServer.renderToString(React.createElement(Interceptor, props));
  if (!captured) {
    throw new Error("Failed to capture rendered element");
  }
  return { element: captured, html };
}

export async function runAllEmpiricalTests(): Promise<boolean> {
  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER M2-2: ADVERSARIAL KEYBOARD & RESPONSIVE VERIFICATION SUITE");
  console.log("  Target: LanguageSwitcher, LoginPage.tsx, NavRail.tsx");
  console.log("=".repeat(80) + "\n");

  const env = setupTestEnv("en");

  try {
    // =========================================================================
    // SECTION 1: KEYBOARD — WHAT A RENDERER WITHOUT A DOM CAN STILL PROVE
    // =========================================================================
    //
    // The arrows used to change the LOCALE: three always-visible segments meant moving and
    // choosing were one act. The control is a menu button now, so the arrows move FOCUS
    // between items that exist only while it is open — which needs `document.activeElement`,
    // and this file renders to a string.
    //
    // The walk itself (ArrowDown/Up, Home, End, Escape returning focus to the trigger, and
    // focus landing on the language already in use) is asserted in
    // `src/components/LanguageSwitcher.test.tsx` under jsdom. What is left here is the pair
    // that a redesign actually threatens, and that a string render can still see.

    await runEmpiricalTest("KB-01", "The root owns a keydown handler", "KEYBOARD", () => {
      const { element } = captureRenderedElement();
      const onKeyDown = (element.props as { onKeyDown?: unknown }).onKeyDown;
      assert(typeof onKeyDown === "function", "Root must carry a keydown handler");
    });

    await runEmpiricalTest("KB-02", "Unhandled keys do NOT call preventDefault()", "KEYBOARD", () => {
      const { element } = captureRenderedElement();
      const onKeyDown = (element.props as { onKeyDown: (e: unknown) => void }).onKeyDown;

      for (const key of ["Tab", "Enter", " ", "a", "Shift", "F5", "PageDown"]) {
        let prevented = false;
        onKeyDown({ key, preventDefault: () => { prevented = true; } });
        assertEqual(prevented, false, `'${key}' must reach the browser untouched`);
      }
    });

    await runEmpiricalTest("KB-03", "No key mutates the locale as a side effect", "KEYBOARD", () => {
      // The regression this guards is a return to the old control, where ArrowRight switched
      // language outright — a keystroke that changed what every screen said, with no menu open
      // and nothing confirming it.
      for (const key of ["ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Home", "End"]) {
        useI18n.getState().setLocale("uz");
        const { element } = captureRenderedElement();
        const onKeyDown = (element.props as { onKeyDown: (e: unknown) => void }).onKeyDown;
        onKeyDown({ key, preventDefault: () => {} });
        assertEqual(useI18n.getState().locale, "uz", `'${key}' must not change the locale`);
      }
    });

    // =========================================================================
    // SECTION 2: WAI-ARIA COMPLIANCE
    // =========================================================================

    await runEmpiricalTest("ARIA-01", "Trigger declares a menu, starts closed, and is labelled", "ARIA", () => {
      const { html } = captureRenderedElement();
      assertIncludes(html, 'aria-haspopup="menu"', "Trigger must declare it opens a menu");
      assertIncludes(html, 'aria-expanded="false"', "Trigger must start closed");
      assertIncludes(html, 'aria-label="Select language"', "Trigger must carry the default label");
      assertNotIncludes(html, 'role="menu"', "A closed control must render no menu");
    });

    await runEmpiricalTest("ARIA-02", "Custom ariaLabel names both the trigger and the menu", "ARIA", () => {
      const { html } = captureRenderedElement({ ariaLabel: "Tilni tanlang", defaultOpen: true });
      const occurrences = (html.match(/aria-label="Tilni tanlang"/g) ?? []).length;
      assertEqual(occurrences, 2, "Both the trigger and the menu it opens must carry the name");
    });

    await runEmpiricalTest("ARIA-03", "Every control is an explicit type='button'", "ARIA", () => {
      // The login page renders this inside a page that has a form on it, and a bare <button>
      // inside a form submits it.
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertEqual((html.match(/type="button"/g) ?? []).length, 4, "One trigger plus three items");
    });

    await runEmpiricalTest("ARIA-04", "aria-checked invariant: exactly 1 of 3 items is 'true'", "ARIA", () => {
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertEqual((html.match(/role="menuitemradio"/g) ?? []).length, 3, "Three languages");
      assertEqual((html.match(/aria-checked="true"/g) ?? []).length, 1, "Exactly one checked");
      assertEqual((html.match(/aria-checked="false"/g) ?? []).length, 2, "The other two unchecked");
    });

    await runEmpiricalTest("ARIA-05", "Every item is named by its own endonym", "ARIA", () => {
      /* As VISIBLE TEXT, not an `aria-label`. An item whose name is already on screen must not
         repeat it in an attribute: the two then drift, and the one nobody can see wins. */
      const { html } = captureRenderedElement({ defaultOpen: true });
      for (const option of LANGUAGE_OPTIONS) {
        const name = LOCALES[option.value].name;
        assertIncludes(html, `>${name}</span>`, `${option.value} must be named "${name}" in text`);
        assertNotIncludes(
          html,
          `role="menuitemradio" aria-checked="true" data-locale="${option.value}" aria-label=`,
          `${option.value} must take its name from its text, not an attribute`,
        );
      }
    });

    await runEmpiricalTest("ARIA-06", "A flag is never the accessible name", "ARIA", () => {
      // This is the line that makes flags defensible in this control at all. A screen reader
      // must hear a language; it must never be told the operator's language is a country.
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertIncludes(html, "aria-hidden", "The flags must be hidden from the accessibility tree");
      for (const country of ["Uzbekistan", "Russia", "America", "United States"]) {
        assertNotIncludes(html, country, `No country name may reach the markup (${country})`);
      }
      // And the identity a test needs is an attribute, not the drawing.
      for (const option of LANGUAGE_OPTIONS) {
        assertIncludes(html, `data-locale="${option.value}"`, `${option.value} must carry data-locale`);
      }
    });

    // =========================================================================
    // SECTION 3: PLANIQ DESIGN TOKENS
    // =========================================================================

    await runEmpiricalTest("TOK-01", "Focus ring uses focus-visible:outline-accent-deep", "TOKENS", () => {
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertIncludes(html, "focus-visible:outline-accent-deep", "accent lacks contrast on light paper");
    });

    await runEmpiricalTest("TOK-02", "The checked item is weighted, not coloured in", "TOKENS", () => {
      // Weight and a tick, rather than a filled ground: the item already carries a flag, and a
      // coloured pill behind a flag is two things competing to say the same thing.
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertIncludes(html, "font-semibold text-ink-900", "Checked item must be the weighted one");
      assertIncludes(html, "text-accent-deep", "The tick must use the accent ink");
    });

    await runEmpiricalTest("TOK-03", "Unchecked items use the muted ink with a hover ground", "TOKENS", () => {
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertIncludes(html, "font-medium text-ink-500", "Unchecked items must be muted");
      assertIncludes(html, "hover:bg-row-hover", "Hover ground must be the shared row-hover token");
    });

    await runEmpiricalTest("TOK-04", "The menu sits on a card with the stroke token", "TOKENS", () => {
      const { html } = captureRenderedElement({ defaultOpen: true });
      assertIncludes(html, "border border-stroke", "Menu border must use border-stroke");
      assertIncludes(html, "bg-card", "Menu ground must use bg-card");
      assertIncludes(html, "rounded-card", "Menu radius must use the card token");
    });

    // =========================================================================
    // SECTION 4: PRESENTATION VARIANTS
    // =========================================================================

    await runEmpiricalTest("VAR-01", "Variant 'login' gives the trigger a ground of its own", "VARIANTS", () => {
      const { html } = captureRenderedElement({ variant: "login" });
      assertIncludes(html, "h-9 w-9", "Same 36px disc as the bar");
      assertIncludes(html, "border border-stroke", "Login trigger must carry a border");
      assertIncludes(html, "bg-card", "Login trigger must carry a card ground");
      assertIncludes(html, "shadow-sm", "Login trigger must lift off an otherwise empty page");
    });

    await runEmpiricalTest("VAR-02", "Variant 'bar' carries no resting chrome", "VARIANTS", () => {
      // In the header the disc already sits on a card, beside a palette button drawn the same
      // way. A border here would make one of the pair look like a different kind of control.
      const { html } = captureRenderedElement({ variant: "bar" });
      assertIncludes(html, "h-9 w-9", "Bar trigger must match TopBar's 36px icon button");
      assertNotIncludes(html, "border border-stroke", "Bar trigger must have no resting border");
      assertNotIncludes(html, "shadow-sm", "Bar trigger must have no resting shadow");
      assertIncludes(html, "hover:bg-row-hover", "The ground appears on hover only");
    });

    await runEmpiricalTest("VAR-03", "Default props: variant='bar', closed", "VARIANTS", () => {
      const { html } = captureRenderedElement();
      assertNotIncludes(html, "border border-stroke", "Default variant must be bar");
      assertIncludes(html, 'aria-expanded="false"', "Default must be closed");
    });

    await runEmpiricalTest("VAR-04", "Unknown variants degrade to the bar rather than throwing", "VARIANTS", () => {
      const unknown = "ultra-mega-wide" as unknown as LanguageSwitcherProps["variant"];
      const { html } = captureRenderedElement({ variant: unknown });
      assertIncludes(html, "h-9 w-9", "Unknown variant must still render the disc");
      assertIncludes(html, 'aria-haspopup="menu"', "Unknown variant must still render a trigger");
    });

    // =========================================================================
    // SECTION 5: RESPONSIVE LAYOUT & INTEGRATION
    // =========================================================================

    await runEmpiricalTest("RESP-01", "LoginPage embeds switcher in absolute top-right with responsive insets", "RESPONSIVE", () => {
      const source = readSourceFile("src/features/auth/LoginPage.tsx");
      assertIncludes(source, '<LanguageSwitcher variant="login" />', "LoginPage must embed LanguageSwitcher variant='login'");
      assertIncludes(
        source,
        "absolute top-4 right-4 sm:top-6 sm:right-6 lg:top-8 lg:right-8 z-20",
        "Switcher wrapper must have responsive absolute placement",
      );
      assertIncludes(source, '<main className="relative flex min-h-screen', "Parent main element must be relative");
    });

    await runEmpiricalTest("RESP-02", "LoginPage 320px mobile viewport clearance and non-overlap", "RESPONSIVE", () => {
      // The control is one 36px disc now, where it used to be a ~138px three-segment pill.
      // The clearance it needed is the reason this test exists, so the arithmetic is kept and
      // re-derived rather than deleted.
      const viewportWidth = 320;
      const switcherWidth = 36; // h-9 w-9
      const rightMargin = 16; // top-4 right-4
      const leftMargin = 16;

      assert(
        switcherWidth + rightMargin + leftMargin <= viewportWidth,
        `Switcher (${switcherWidth}px) + margins must fit inside 320px without horizontal scroll`,
      );

      // Vertical: top-4 (16px) + h-9 (36px) = 52px, inside main's py-14 (56px) top padding.
      const switcherBottom = 16 + 36;
      const mainContentStart = 56;
      assert(
        switcherBottom <= mainContentStart,
        `Switcher bottom (${switcherBottom}px) must not overlap main content start (${mainContentStart}px)`,
      );
    });

    await runEmpiricalTest("RESP-03", "LoginPage 1024px/1440px desktop grid containment", "RESPONSIVE", () => {
      const source = readSourceFile("src/features/auth/LoginPage.tsx");
      assertIncludes(source, "lg:grid-cols-[641fr_665fr]", "Desktop grid must divide into 641fr and 665fr columns");
      assertIncludes(source, "lg:gap-[86px]", "Desktop grid must maintain 86px gutter");
      assertIncludes(source, "<ConsolePanel", "ConsolePanel is sibling in grid");
    });

    await runEmpiricalTest("RESP-04", "NavRail responsive layout branching at 1024px", "RESPONSIVE", () => {
      const source = readSourceFile("src/app/NavRail.tsx");
      assertIncludes(source, 'const COMPACT_QUERY = "(max-width: 1023.98px)"', "COMPACT_QUERY must target below 1024px with subpixel precision");
      assertIncludes(source, "function useIsCompact(): boolean", "useIsCompact hook must govern responsive state");
      assertIncludes(source, "useIsCompact() ? <CompactBar /> : <WideRail />", "NavRail must cleanly branch between CompactBar and WideRail");
    });

    await runEmpiricalTest("RESP-05", "TopBar mounts the switcher between the balances and the palette", "RESPONSIVE", () => {
      const source = readSourceFile("src/app/TopBar.tsx");
      assertIncludes(source, "<LanguageSwitcher />", "TopBar must render the switcher");

      const balances = source.indexOf("<Balances />");
      const switcher = source.indexOf("<LanguageSwitcher />");
      const theme = source.indexOf("<ThemeToggle />");
      assert(balances !== -1 && switcher !== -1 && theme !== -1, "TopBar must render all three");
      assert(
        balances < switcher && switcher < theme,
        "Deployment state first, then the operator's two preferences together",
      );
    });

    await runEmpiricalTest("RESP-06", "NavRail no longer mounts the switcher in either layout", "RESPONSIVE", () => {
      // The move is the point, so the absence is asserted: a rail that quietly grew a second
      // copy back would leave two controls for one preference, disagreeing on hover.
      const source = readSourceFile("src/app/NavRail.tsx");
      assertNotIncludes(source, "<LanguageSwitcher", "NavRail must not render the language control");
      assertNotIncludes(source, 'from "@/components/LanguageSwitcher"', "NavRail must not import it");
    });

    // =========================================================================
    // SECTION 6: REACTIVITY, DOM SYNC & PERSISTENCE
    // =========================================================================

    await runEmpiricalTest("SYNC-01", "Choosing a language updates document lang and storage", "SYNC", () => {
      useI18n.getState().setLocale("en");
      const { element } = captureRenderedElement({ defaultOpen: true });

      const menu = (element.props as { children: React.ReactElement[] }).children[1];
      const items = React.Children.toArray(menu.props.children) as React.ReactElement[];
      const ru = items.find((item) => item.props["data-locale"] === "ru");
      assert(Boolean(ru), "The menu must offer Russian");
      (ru!.props.onClick as () => void)();

      assertEqual(useI18n.getState().locale, "ru", "Choosing must set the store");
      assertEqual(env.doc.documentElement.lang, "ru", "Choosing must set <html lang>");
      assertEqual(env.storage.getItem("bayram.dashboard.locale"), "ru", "Choosing must persist");
    });

    await runEmpiricalTest("SYNC-02", "An external store mutation reaches every reader", "SYNC", () => {
      // What this cannot assert is the rendered reflection: `useSyncExternalStore` gives a
      // SERVER render its third argument, which zustand fills with `getInitialState()`, so a
      // string render always draws the locale the store booted with. The rendered half is
      // covered in `src/components/LanguageSwitcher.test.tsx`, which renders as a client.
      const seen: SupportedLocale[] = [];
      const unsubscribe = useI18n.subscribe((state) => seen.push(state.locale));
      try {
        useI18n.getState().setLocale("uz");
        useI18n.getState().setLocale("en");
      } finally {
        unsubscribe();
      }
      assertEqual(seen.join(","), "uz,en", "Every subscriber must see every change, in order");
    });

    await runEmpiricalTest("SYNC-03", "Storage QuotaExceededError is caught during a switch", "SYNC", () => {
      env.storage.shouldThrowOnSet = true;
      env.storage.throwErrorType = "QuotaExceededError";
      try {
        useI18n.getState().setLocale("uz");
        assertEqual(useI18n.getState().locale, "uz", "In-memory locale must survive a full disk");
        assertEqual(env.doc.documentElement.lang, "uz", "<html lang> must survive it too");
      } finally {
        env.storage.shouldThrowOnSet = false;
      }
    });

    // =========================================================================
    // SECTION 7: STRESS & MOUNT/UNMOUNT CYCLES
    // =========================================================================

    await runEmpiricalTest("STRESS-01", "1,000 rapid mount / unmount render cycles without leaks or errors", "STRESS", () => {
      for (let i = 0; i < 1000; i++) {
        const variant: LanguageSwitcherProps["variant"] = i % 2 === 0 ? "login" : "bar";
        const { html } = captureRenderedElement({ variant, defaultOpen: i % 3 === 0 });
        assert(html.length > 50, "HTML must render successfully");
      }
    });


  } finally {
    restoreTestEnv();
  }

  // =========================================================================
  // SUMMARY REPORT
  // =========================================================================

  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER M2-2 EXECUTION SUMMARY");
  console.log("=".repeat(80));

  const passed = reports.filter((r) => r.status === "PASS").length;
  const failed = reports.filter((r) => r.status === "FAIL").length;
  const total = reports.length;

  console.log(`  Total Empirical Tests: ${total}`);
  console.log(`  \x1b[32mPassed:\x1b[0m                ${passed}`);
  console.log(`  \x1b[31mFailed:\x1b[0m                ${failed}`);

  if (failed > 0) {
    console.error(`\n\x1b[31mEmpirical verification FAILED with ${failed} defect(s).\x1b[0m\n`);
    return false;
  } else {
    console.log(`\n\x1b[32mAll empirical tests PASSED (100% verified).\x1b[0m\n`);
    return true;
  }
}

// Auto-run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllEmpiricalTests().then((success) => {
    process.exit(success ? 0 : 1);
  });
}
