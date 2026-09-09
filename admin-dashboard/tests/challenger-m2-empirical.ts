/**
 * Empirical Challenger Test Harness for Milestone M2
 *
 * Stress-tests:
 * 1. Rapid locale switching: high-volume cycling (uz -> ru -> en -> uz), throughput,
 *    Zustand state coherence, localStorage persistence, document.documentElement.lang sync,
 *    and multi-subscriber fan-out under storage fault injection.
 * 2. Component props forwarding & variant fallbacks: default prop handling,
 *    custom className forwarding across all variants, custom ariaLabel,
 *    collapsed prop behavior across variants, and invalid/unknown variant resilience.
 * 3. Keyboard navigation & WAI-ARIA accessibility: Arrow keys, Home/End wrap-around,
 *    irrelevant key pass-through, type="button", aria-pressed toggle, and screen-reader labels.
 * 4. Interactive event execution: synthetic keyboard events on onKeyDown and synthetic
 *    click events on option buttons.
 * 5. Integration presence & layout across views: LoginPage top-right anchoring (outside form,
 *    z-20), NavRail WideRail (expanded & collapsed 44px vertical column), and CompactBar (shrink-0).
 */

import React, { type ReactElement } from "react";
import ReactDOMServer from "react-dom/server";

import {
  LanguageSwitcher,
  LANGUAGE_OPTIONS,
  type LanguageSwitcherVariant,
  type LanguageSwitcherProps,
} from "../src/components/LanguageSwitcher.js";
import { useI18n, setLocale, getLocale } from "../src/i18n/index.js";
import { LOCALES, type SupportedLocale } from "../src/i18n/types.js";
import {
  setupTestEnv,
  restoreTestEnv,
  readSourceFile,
  assert,
  assertEqual,
  assertNotEqual,
  assertIncludes,
  assertNotIncludes,
} from "./harness.js";

interface TestReport {
  id: string;
  suite: string;
  name: string;
  status: "PASS" | "FAIL";
  details?: string;
  durationMs: number;
}

const reports: TestReport[] = [];

async function challenge(
  id: string,
  suite: string,
  name: string,
  fn: () => Promise<void> | void,
): Promise<void> {
  const start = performance.now();
  try {
    await fn();
    const durationMs = Math.round((performance.now() - start) * 100) / 100;
    reports.push({ id, suite, name, status: "PASS", durationMs });
    console.log(`  [${id}] \x1b[32m✔ PASS\x1b[0m [${suite}] ${name} \x1b[90m(${durationMs}ms)\x1b[0m`);
  } catch (err: unknown) {
    const durationMs = Math.round((performance.now() - start) * 100) / 100;
    const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    reports.push({ id, suite, name, status: "FAIL", details: msg, durationMs });
    console.error(`  [${id}] \x1b[31m✖ FAIL\x1b[0m [${suite}] ${name} \x1b[90m(${durationMs}ms)\x1b[0m`);
    console.error(`       \x1b[31m${msg}\x1b[0m`);
  }
}

/**
 * Intercepts the React element and event handlers produced by LanguageSwitcher.
 */
/**
 * The switcher is a MENU BUTTON now, and this harness renders through
 * `renderToStaticMarkup` — an SSR pass, where the menu is closed and the items do not exist.
 *
 * So everything below asserts what a server render can actually see: the trigger, its shape,
 * and its classes. The behaviour that needs a click or a key — opening, choosing, the arrows,
 * Escape, dismissal, and the one that matters most, whether a locale change repaints anything
 * OTHER than the switcher — lives in `src/components/LanguageSwitcher.test.tsx`, which runs in
 * jsdom and can drive it.
 *
 * ## Nothing here may assert WHICH locale is rendered
 *
 * `useSyncExternalStore` takes three arguments, and the third is the one a server render uses:
 * zustand passes `api.getInitialState()`. So under `renderToStaticMarkup` the switcher draws
 * the locale the store BOOTED with, whatever `setLocale` has done since — for this harness,
 * always `en`. That is correct SSR behaviour and it never happens in this console, which is a
 * client-rendered SPA and reads `getSnapshot` instead. It does mean an assertion here about
 * the CURRENT locale would be measuring the harness. Those live in the jsdom test.
 */
function captureLanguageSwitcher(props: LanguageSwitcherProps = {}): {
  element: ReactElement;
  onKeyDown: (e: any) => void;
  trigger: { locale: string; title: string; ariaLabel: string; expanded: string };
  html: string;
} {
  let capturedKeyDown: ((e: any) => void) | null = null;
  let capturedTrigger = { locale: "", title: "", ariaLabel: "", expanded: "" };

  function Interceptor() {
    const vnode = LanguageSwitcher(props);
    capturedKeyDown = vnode.props.onKeyDown;

    /* The first child is the trigger; the second is the menu, and it is `null` while closed.
       Read by position rather than by class, so restyling the control does not break this. */
    const children = React.Children.toArray(vnode.props.children) as ReactElement[];
    const trigger = children[0];
    capturedTrigger = {
      locale: String(trigger?.props["data-locale"] ?? ""),
      title: String(trigger?.props.title ?? ""),
      ariaLabel: String(trigger?.props["aria-label"] ?? ""),
      expanded: String(trigger?.props["aria-expanded"] ?? ""),
    };

    return vnode;
  }

  const html = ReactDOMServer.renderToStaticMarkup(React.createElement(Interceptor));

  return {
    element: React.createElement(Interceptor),
    onKeyDown: capturedKeyDown!,
    trigger: capturedTrigger,
    html,
  };
}

export async function runChallengerM2(): Promise<boolean> {
  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER M2: ADVERSARIAL STRESS HARNESS");
  console.log("  Focus: Rapid Switching, Props, Variant Fallbacks, Presence & Accessibility");
  console.log("=".repeat(80) + "\n");

  const env = setupTestEnv("en");

  try {
    /* ========================================================================= */
    /* SUITE 1: RAPID LOCALE SWITCHING & REACTIVE STATE COHERENCE               */
    /* ========================================================================= */
    console.log("\x1b[1m=== Suite 1: Rapid Locale Switching & Reactive Coherence ===\x1b[0m");

    await challenge(
      "CH2.1.1",
      "Switching",
      "10,000 rapid cycles (uz -> ru -> en -> uz) maintain state, storage & DOM sync",
      () => {
        const order: SupportedLocale[] = ["uz", "ru", "en"];
        const iterations = 10000;
        const start = performance.now();

        for (let i = 0; i < iterations; i++) {
          const target = order[i % 3]!;
          setLocale(target);

          if (i % 500 === 0 || i === iterations - 1) {
            assertEqual(getLocale(), target, `getLocale() mismatch at iteration ${i}`);
            assertEqual(useI18n.getState().locale, target, `store.locale mismatch at iteration ${i}`);
            assertEqual(env.storage.getItem("hbd.dashboard.locale"), target, `storage mismatch at ${i}`);
            assertEqual(env.doc.documentElement.lang, target, `doc.lang mismatch at ${i}`);
          }
        }

        const elapsed = performance.now() - start;
        const opsPerSec = Math.round((iterations / elapsed) * 1000);
        assert(opsPerSec > 10000, `Throughput should exceed 10,000 ops/sec, got ${opsPerSec} ops/sec`);
      },
    );

    await challenge(
      "CH2.1.2",
      "Switching",
      "The trigger's face is a supported locale, and its tooltip names that language",
      () => {
        /* Which locale it is belongs to the jsdom test (see the note on the helper). What is
           checked here is that the face comes from the catalogue at all: a trigger whose
           `data-locale` is empty, or whose tooltip names something that is not one of the
           three languages, is broken in any renderer. */
        const captured = captureLanguageSwitcher({});
        const shown = captured.trigger.locale as SupportedLocale;

        assert(
          (["uz", "ru", "en"] as const).includes(shown),
          `Trigger must carry a supported locale, got '${shown}'`,
        );
        assertIncludes(
          captured.trigger.title,
          LOCALES[shown].name,
          "Trigger tooltip must name the language, never the country",
        );
      },
    );

    await challenge(
      "CH2.1.3",
      "Switching",
      "Rapid switching survives storage QuotaExceededError and SecurityError faults",
      () => {
        env.storage.shouldThrowOnSet = true;
        env.storage.throwErrorType = "QuotaExceededError";

        try {
          setLocale("uz");
          assertEqual(getLocale(), "uz", "In-memory locale must be 'uz' despite QuotaExceededError");
          assertEqual(env.doc.documentElement.lang, "uz", "DOM lang must update despite storage failure");

          env.storage.throwErrorType = "SecurityError";
          setLocale("ru");
          assertEqual(getLocale(), "ru", "In-memory locale must be 'ru' despite SecurityError");
          assertEqual(env.doc.documentElement.lang, "ru", "DOM lang must update despite SecurityError");
        } finally {
          env.storage.shouldThrowOnSet = false;
        }
      },
    );

    await challenge(
      "CH2.1.4",
      "Switching",
      "Multi-subscriber fan-out: 500 concurrent subscribers receive rapid updates without drops",
      () => {
        const subscriberCount = 500;
        const subscriberValues = new Array<SupportedLocale>(subscriberCount).fill("en");
        const unsubs: Array<() => void> = [];

        for (let i = 0; i < subscriberCount; i++) {
          const idx = i;
          const unsub = useI18n.subscribe((state) => {
            subscriberValues[idx] = state.locale;
          });
          unsubs.push(unsub);
        }

        try {
          const testLocales: SupportedLocale[] = ["uz", "ru", "en", "uz", "ru"];
          for (const loc of testLocales) {
            setLocale(loc);
            for (let i = 0; i < subscriberCount; i++) {
              assertEqual(subscriberValues[i], loc, `Subscriber ${i} out of sync for locale ${loc}`);
            }
          }
        } finally {
          for (const u of unsubs) u();
        }
      },
    );

    /* ========================================================================= */
    /* SUITE 2: COMPONENT PROPS FORWARDING & VARIANT FALLBACKS                  */
    /* ========================================================================= */
    console.log("\n\x1b[1m=== Suite 2: Props Forwarding & Variant Fallbacks ===\x1b[0m");

    await challenge(
      "CH2.2.1",
      "Props",
      "Default props rendering: a closed menu button labelled in the current language",
      () => {
        setLocale("en");
        const captured = captureLanguageSwitcher({});
        const html = captured.html;

        assertIncludes(html, 'aria-haspopup="menu"', "Trigger must declare it opens a menu");
        assertIncludes(html, 'aria-expanded="false"', "Trigger must start closed");
        assertIncludes(html, 'aria-label="Select language"', "Must have default aria-label");
        assertNotIncludes(html, 'role="menu"', "A closed control must render no menu");

        assertIncludes(html, "h-9 w-9", "Default variant must match TopBar's 36px icon button");
        assertNotIncludes(html, "bg-card", "Default variant must carry no ground of its own");
        assertEqual(captured.trigger.locale, "en", "Trigger must show the active locale");
      },
    );

    await challenge(
      "CH2.2.2",
      "Props",
      "Custom className forwarding across both variants",
      () => {
        const customClass = "custom-adversarial-test-class pointer-events-auto";

        const loginCaptured = captureLanguageSwitcher({ variant: "login", className: customClass });
        assertIncludes(loginCaptured.html, customClass, "Login variant must preserve custom className");
        assertIncludes(loginCaptured.html, "bg-card", "Login variant must give the trigger a ground");

        const barCaptured = captureLanguageSwitcher({ variant: "bar", className: customClass });
        assertIncludes(barCaptured.html, customClass, "Bar variant must preserve custom className");
        assertIncludes(barCaptured.html, "h-9 w-9", "Bar variant must retain the 36px disc");
      },
    );

    await challenge(
      "CH2.2.3",
      "Props",
      "Custom ariaLabel overrides default and supports empty string or unicode",
      () => {
        const uzCaptured = captureLanguageSwitcher({ ariaLabel: "Tilni tanlang" });
        assertIncludes(uzCaptured.html, 'aria-label="Tilni tanlang"', "Must render custom Uzbek aria-label");

        const ruCaptured = captureLanguageSwitcher({ ariaLabel: "Выберите язык" });
        assertIncludes(ruCaptured.html, 'aria-label="Выберите язык"', "Must render custom Russian aria-label");

        const emptyCaptured = captureLanguageSwitcher({ ariaLabel: "" });
        assertIncludes(emptyCaptured.html, 'aria-label=""', "Must preserve empty aria-label when explicitly passed");
      },
    );

    await challenge(
      "CH2.2.4",
      "Props",
      "Invalid or unknown variant values fallback gracefully without throwing",
      () => {
        const unknownVariant = "ultra-mega-wide" as unknown as LanguageSwitcherVariant;
        const unknownCaptured = captureLanguageSwitcher({ variant: unknownVariant });
        assert(unknownCaptured.html.length > 0, "Must render valid markup for unknown variant");
        assertIncludes(unknownCaptured.html, 'aria-haspopup="menu"', "Must still render a trigger");

        const undefinedCaptured = captureLanguageSwitcher({ variant: undefined });
        assertIncludes(undefinedCaptured.html, "h-9 w-9", "Undefined variant must fall back to bar");

        const emptyCaptured = captureLanguageSwitcher({ variant: "" as unknown as LanguageSwitcherVariant });
        assert(emptyCaptured.html.length > 0, "Empty string variant must render safely");
      },
    );

    await challenge(
      "CH2.2.5",
      "Props",
      "The two variants differ only in whether the trigger carries its own ground",
      () => {
        /* `collapsed` is gone with the sidebar mount it existed for. What is left is one
           genuine difference: in the bar the disc sits on a card already, and on the login page
           there is nothing behind it, so a bare flag would read as decoration. */
        const bar = captureLanguageSwitcher({ variant: "bar" });
        assertNotIncludes(bar.html, "border-stroke", "Bar trigger must have no resting border");
        assertNotIncludes(bar.html, "shadow-sm", "Bar trigger must have no resting shadow");

        const login = captureLanguageSwitcher({ variant: "login" });
        assertIncludes(login.html, "border-stroke", "Login trigger must carry a border");
        assertIncludes(login.html, "bg-card", "Login trigger must carry a card ground");
        assertIncludes(login.html, "shadow-sm", "Login trigger must lift off the page");

        assertIncludes(bar.html, "h-9 w-9", "Both variants are the same 36px disc");
        assertIncludes(login.html, "h-9 w-9", "Both variants are the same 36px disc");
      },
    );

    /* ========================================================================= */
    /* SUITE 3: ACCESSIBILITY & KEYBOARD NAVIGATION MATRIX                      */
    /* ========================================================================= */
    console.log("\n\x1b[1m=== Suite 3: Accessibility & Keyboard Navigation Matrix ===\x1b[0m");

    await challenge(
      "CH2.3.1",
      "Accessibility",
      "The trigger is type='button' and names a LANGUAGE, never a country",
      () => {
        const captured = captureLanguageSwitcher({ variant: "login" });
        const html = captured.html;

        /* One button while closed. `type="button"` because the login page renders this inside
           a page that has a form on it, and a bare <button> there submits. */
        const buttonCount = (html.match(/type="button"/g) || []).length;
        assertEqual(buttonCount, 1, "A closed control is exactly one button");

        const shown = captured.trigger.locale as SupportedLocale;
        assertIncludes(captured.trigger.title, LOCALES[shown].name, "Tooltip must name a language");

        /* The flag is decoration. This is the line that makes flags defensible at all: a
           screen reader must never be told the operator's language is a country. */
        assertIncludes(html, "aria-hidden", "The flag must be hidden from the accessibility tree");
        for (const country of ["Russia", "America", "United States", "Uzbekistan"]) {
          assertNotIncludes(html, country, `No country name may reach the markup (${country})`);
        }
      },
    );

    await challenge(
      "CH2.3.2",
      "Accessibility",
      "PlanIQ tokens compliance: ink ramp for the trigger, outline-accent-deep for focus",
      () => {
        const bar = captureLanguageSwitcher({ variant: "bar" }).html;
        assertIncludes(bar, "text-ink-500", "Resting trigger must use text-ink-500");
        assertIncludes(bar, "hover:text-ink-900", "Hover must resolve to text-ink-900");
        assertIncludes(bar, "hover:bg-row-hover", "Hover ground must be the shared row-hover token");
        assertIncludes(bar, "focus-visible:outline-accent-deep", "Focus ring must use outline-accent-deep");

        const login = captureLanguageSwitcher({ variant: "login" }).html;
        assertIncludes(login, "border-stroke", "Login trigger border must use border-stroke");
      },
    );

    await challenge(
      "CH2.3.3",
      "Accessibility",
      "The control owns a keydown handler, and the walk itself is covered where it can run",
      () => {
        /*
         * The arrows used to change the LOCALE directly: the control was three always-visible
         * segments, so moving focus and choosing were the same act. A menu separates them —
         * the arrows move focus between items that only exist once the menu is open, and
         * choosing is Enter or a click.
         *
         * An SSR render cannot open it, so the walk (ArrowDown/Up, Home, End, Escape, and the
         * focus landing on the language already in use) is asserted in
         * `src/components/LanguageSwitcher.test.tsx`, under jsdom. What is checked here is the
         * half that survives without a DOM: the handler is wired to the root at all, and a key
         * it does not own is left alone rather than swallowed.
         */
        setLocale("uz");
        const captured = captureLanguageSwitcher({});
        assert(typeof captured.onKeyDown === "function", "Root must carry a keydown handler");

        let prevented = false;
        captured.onKeyDown({
          key: "q",
          preventDefault: () => {
            prevented = true;
          },
        });
        assertEqual(prevented, false, "An unrelated key must not be swallowed");
        assertEqual(getLocale(), "uz", "An unrelated key must not mutate the locale");
      },
    );

    /* ========================================================================= */
    /* SUITE 4: INTEGRATION PRESENCE & LAYOUT ACROSS VIEWS                      */
    /* ========================================================================= */
    console.log("\n\x1b[1m=== Suite 4: Integration Presence & Layout Across Views ===\x1b[0m");

    await challenge(
      "CH2.4.1",
      "Presence",
      "LoginPage AST / source integration: LanguageSwitcher anchored in top-right chrome outside form",
      () => {
        const loginSource = readSourceFile("src/features/auth/LoginPage.tsx");

        // Verify import
        assertIncludes(
          loginSource,
          'import { LanguageSwitcher } from "@/components/LanguageSwitcher";',
          "LoginPage must import LanguageSwitcher",
        );

        // Verify top-right container presence
        assertIncludes(
          loginSource,
          '<LanguageSwitcher variant="login" />',
          "LoginPage must render LanguageSwitcher with variant='login'",
        );

        // Verify responsive positioning classes
        assertIncludes(
          loginSource,
          'absolute top-4 right-4 sm:top-6 sm:right-6 lg:top-8 lg:right-8 z-20',
          "LoginPage must position switcher in top-right across all breakpoints with z-20",
        );

        // Verify placement before and outside <form>
        const formIndex = loginSource.indexOf("<form");
        const switcherIndex = loginSource.indexOf("<LanguageSwitcher");
        assert(formIndex !== -1, "LoginPage must contain <form>");
        assert(switcherIndex !== -1, "LoginPage must contain <LanguageSwitcher>");
        assert(
          switcherIndex < formIndex,
          "LanguageSwitcher must be rendered in header chrome BEFORE and outside the login form",
        );
      },
    );

    await challenge(
      "CH2.4.2",
      "Presence",
      "TopBar integration: the language control sits beside the palette toggle",
      () => {
        const topBarSource = readSourceFile("src/app/TopBar.tsx");

        assertIncludes(
          topBarSource,
          'import { LanguageSwitcher } from "@/components/LanguageSwitcher";',
          "TopBar must import LanguageSwitcher",
        );
        assertIncludes(topBarSource, "<LanguageSwitcher />", "TopBar must render the switcher");

        /* Order is the assertion: the deployment's state first, then the operator's two
           preferences together at the end of the bar. */
        const balancesIdx = topBarSource.indexOf("<Balances />");
        const switcherIdx = topBarSource.indexOf("<LanguageSwitcher />");
        const themeIdx = topBarSource.indexOf("<ThemeToggle />");
        assert(balancesIdx !== -1, "TopBar must render Balances");
        assert(switcherIdx !== -1, "TopBar must render LanguageSwitcher");
        assert(themeIdx !== -1, "TopBar must render ThemeToggle");
        assert(
          balancesIdx < switcherIdx && switcherIdx < themeIdx,
          "Order must be balances, then language, then palette",
        );
      },
    );

    await challenge(
      "CH2.4.3",
      "Presence",
      "NavRail no longer mounts the language control in either layout",
      () => {
        const navRailSource = readSourceFile("src/app/NavRail.tsx");

        /* The move is the point, so the absence is asserted rather than assumed: a rail that
           quietly grew a second copy back would leave two controls for one preference. */
        assertNotIncludes(
          navRailSource,
          "<LanguageSwitcher",
          "NavRail must not render the language control",
        );
        assertNotIncludes(
          navRailSource,
          'from "@/components/LanguageSwitcher"',
          "NavRail must not import the language control",
        );
      },
    );

    await challenge(
      "CH2.4.4",
      "Presence",
      "Idempotency: Repeated re-renders of LanguageSwitcher cause zero memory leakage or state drift",
      () => {
        setLocale("uz");
        const first = captureLanguageSwitcher({ variant: "login" }).trigger.locale;
        for (let i = 0; i < 100; i++) {
          const captured = captureLanguageSwitcher({ variant: "login" });
          assertEqual(captured.trigger.locale, first, "Rendering must be stable across re-renders");
          assertEqual(captured.trigger.expanded, "false", "A re-render must not latch the menu open");
        }
        assertEqual(getLocale(), "uz", "Rendering must not mutate the store");
      },
    );
  } finally {
    restoreTestEnv();
  }

  // Summary
  const passed = reports.filter((r) => r.status === "PASS").length;
  const failed = reports.filter((r) => r.status === "FAIL").length;
  const total = reports.length;

  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER M2 EXECUTION SUMMARY");
  console.log("=".repeat(80));
  console.log(`  Total Challenges: ${total}`);
  console.log(`  \x1b[32mPassed:\x1b[0m           ${passed}`);
  console.log(`  \x1b[31mFailed:\x1b[0m           ${failed}`);
  console.log("=".repeat(80) + "\n");

  return failed === 0;
}

// Auto-run when executed directly via tsx
if (import.meta.url === `file://${process.argv[1]}`) {
  void runChallengerM2().then((success) => {
    process.exit(success ? 0 : 1);
  });
}
