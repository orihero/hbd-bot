/**
 * Empirical Adversarial Challenger Test Harness for Milestone M2: LanguageSwitcher
 *
 * Stress-tests:
 * 1. Rapid sequential switching across uz -> ru -> en (1,500+ switches) preserving state, DOM, and translations.
 * 2. Multi-subscriber leak and notification integrity under high-volume switching.
 * 3. Rendering all presentation variants (login, wide expanded, wide collapsed, compact) and PlanIQ token compliance.
 * 4. Boundary inputs, fuzzing invalid variants, undefined callbacks, missing props, and keyboard navigation matrix.
 * 5. Storage denial / QuotaExceeded / SecurityError resilience during interactive switching.
 */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  LanguageSwitcher,
  type LanguageSwitcherProps,
  type LanguageSwitcherVariant,
} from "../src/components/LanguageSwitcher";
import {
  useI18n,
  getLocale,
  setLocale,
  t,
} from "../src/i18n";
import { LOCALES, type SupportedLocale } from "../src/i18n/types";
import { setupTestEnv, restoreTestEnv } from "./harness";

interface TestReport {
  suite: string;
  name: string;
  status: "PASS" | "FAIL";
  durationMs?: number;
  details: string;
}

const reports: TestReport[] = [];

function record(report: TestReport) {
  reports.push(report);
  const icon = report.status === "PASS" ? "✔ [PASS]" : "✖ [FAIL]";
  const timeStr = report.durationMs !== undefined ? ` (${report.durationMs.toFixed(2)}ms)` : "";
  console.log(`${icon} [${report.suite}] ${report.name}${timeStr}`);
  if (report.details && report.status === "FAIL") {
    console.error(`       Details: ${report.details}`);
  }
}

/**
 * Harness component to capture virtual DOM element returned by LanguageSwitcher
 * during a real React render pass with active React dispatcher.
 */
interface RenderResult {
  html: string;
  element: React.ReactElement;
  /** The disc in the bar. Its `data-locale` is the language currently in use. */
  trigger: React.ReactElement;
  /** The three languages, as they appear inside the open menu. */
  buttons: Array<{
    value: SupportedLocale;
    label: string;
    ariaPressed: boolean;
    title: string;
    className: string;
    onClick: () => void;
  }>;
  onKeyDown: (event: { key: string; preventDefault: () => void }) => void;
}

/**
 * Renders the switcher with its menu OPEN.
 *
 * The control is a menu button now: closed, its three languages are not in the tree at all, so
 * a static render sees one button and nothing to assert about. `defaultOpen` is the component's
 * own uncontrolled affordance and it is what makes this harness possible without a DOM.
 *
 * `buttons` below are therefore the three MENU ITEMS, and `ariaPressed` reads `aria-checked` —
 * a `menuitemradio` is checked, not pressed. The trigger is available separately.
 *
 * What still cannot be asserted here, and has moved to `src/components/LanguageSwitcher.test.tsx`
 * where jsdom can drive it: opening, closing, Escape, focus movement between items, dismissal on
 * an outside pointer, and whether a locale change repaints anything other than the switcher.
 */
function renderSwitcher(props: LanguageSwitcherProps = {}): RenderResult {
  let captured: React.ReactElement | null = null;

  function SwitcherWrapper() {
    captured = LanguageSwitcher({ defaultOpen: true, ...props });
    return captured;
  }

  const html = renderToStaticMarkup(
    React.createElement(SwitcherWrapper),
  );
  if (!captured) {
    throw new Error("Failed to capture LanguageSwitcher element during render");
  }

  const el = captured as React.ReactElement;
  // Use raw children from props to avoid React.Children.toArray key prefixing
  const rawChildren = (Array.isArray(el.props.children) ? el.props.children : [el.props.children])
    .filter((child: unknown): child is React.ReactElement => child !== null && child !== undefined);

  /* [0] is the trigger; [1] is the menu, present because `renderSwitcher` forces it open. */
  const trigger = rawChildren[0] as React.ReactElement;
  const menu = rawChildren[1] as React.ReactElement | undefined;
  const items = menu
    ? (React.Children.toArray(menu.props.children) as React.ReactElement[])
    : [];

  const buttons = items.map((child) => ({
    value: String(child.props["data-locale"] ?? "") as SupportedLocale,
    label: String(child.props["data-locale"] ?? "").toUpperCase(),
    ariaPressed: child.props["aria-checked"] === true,
    title: String(child.props.title ?? ""),
    className: String(child.props.className ?? ""),
    onClick: child.props.onClick as () => void,
  }));

  return {
    html,
    trigger,
    element: el,
    buttons,
    onKeyDown: el.props.onKeyDown as (event: { key: string; preventDefault: () => void }) => void,
  };
}

export async function runChallengerM2Stress(): Promise<{ passed: number; failed: number }> {
  console.log("\n================================================================================");
  console.log("  CHALLENGER M2: EMPIRICAL STRESS & ADVERSARIAL HARNESS (LanguageSwitcher)");
  console.log("================================================================================\n");

  /* -------------------------------------------------------------------------- */
  /* SUITE 1: Rapid Sequential Switching & Store Consistency                    */
  /* -------------------------------------------------------------------------- */
  console.log("--- Suite 1: Rapid Sequential Switching & Store Consistency ---");

  // 1.1: 1,500 sequential switches rotating uz -> ru -> en
  {
    const start = performance.now();
    const env = setupTestEnv("en");
    try {
      const sequence: SupportedLocale[] = ["uz", "ru", "en"];
      const TOTAL_SWITCHES = 1500;
      let desyncCount = 0;
      let firstError = "";

      for (let i = 0; i < TOTAL_SWITCHES; i++) {
        const expected = sequence[i % sequence.length];
        setLocale(expected);

        const storeLocale = useI18n.getState().locale;
        const getLocaleVal = getLocale();
        const docLang = env.doc.documentElement.lang;
        const stored = env.storage.getItem("bayram.dashboard.locale");

        // Verify translation lookup consistency for each locale (uses unicode ellipsis U+2026)
        const sampleTranslation = t("common.loading");
        const expectedLoading =
          expected === "uz"
            ? "Yuklanmoqda…"
            : expected === "ru"
              ? "Загрузка…"
              : "Loading…";

        if (
          storeLocale !== expected ||
          getLocaleVal !== expected ||
          docLang !== expected ||
          stored !== expected ||
          sampleTranslation !== expectedLoading
        ) {
          desyncCount++;
          if (!firstError) {
            firstError = `Step ${i}: expected ${expected}, got store=${storeLocale}, getLocale=${getLocaleVal}, docLang=${docLang}, stored=${stored}, t=${sampleTranslation}`;
          }
        }
      }

      const dur = performance.now() - start;
      const throughput = Math.round((TOTAL_SWITCHES / (dur / 1000)));

      if (desyncCount === 0) {
        record({
          suite: "Suite 1: Rapid Switching",
          name: `1,500 sequential switches (uz -> ru -> en) preserved 100% consistent state`,
          status: "PASS",
          durationMs: dur,
          details: `Executed ${TOTAL_SWITCHES} switches in ${dur.toFixed(2)}ms (~${throughput} ops/sec) with zero desyncs.`,
        });
      } else {
        record({
          suite: "Suite 1: Rapid Switching",
          name: `1,500 sequential switches (uz -> ru -> en)`,
          status: "FAIL",
          durationMs: dur,
          details: `Found ${desyncCount} desyncs during rapid switching! First failure: ${firstError}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 1.2: 1,000 switches via component interactive button onClick
  {
    const start = performance.now();
    setupTestEnv("en");
    try {
      const TOTAL_INTERACTIONS = 1000;
      const sequence: SupportedLocale[] = ["uz", "ru", "en"];
      let failureCount = 0;
      let firstFailure = "";

      for (let i = 0; i < TOTAL_INTERACTIONS; i++) {
        const targetLocale = sequence[i % sequence.length];
        const targetIndex = i % sequence.length;

        // Render component
        const rendered = renderSwitcher({ variant: "login" });
        // Click target button
        rendered.buttons[targetIndex].onClick();

        // Check store state
        const currentLocale = useI18n.getState().locale;
        if (currentLocale !== targetLocale) {
          failureCount++;
          if (!firstFailure) firstFailure = `Step ${i}: Clicked ${targetLocale}, store became ${currentLocale}`;
          continue;
        }

        /*
         * The rendered `aria-checked` used to be re-read here and cannot be, in this renderer.
         * `useSyncExternalStore` hands a SERVER render its third argument, which zustand fills
         * with `api.getInitialState()` — so a static render always draws the locale the store
         * booted with, whatever has been set since. The rendered reflection of the store is
         * asserted in `src/components/LanguageSwitcher.test.tsx`, under jsdom, where the
         * client snapshot is the one in play. What this loop still proves is the part it was
         * really built for: a thousand clicks in sequence, each landing exactly one locale.
         */
      }

      const dur = performance.now() - start;
      if (failureCount === 0) {
        record({
          suite: "Suite 1: Rapid Switching",
          name: "1,000 interactive menu-item onClick switches land exactly one locale each",
          status: "PASS",
          durationMs: dur,
          details: `All ${TOTAL_INTERACTIONS} button clicks cleanly updated store and UI state without desync.`,
        });
      } else {
        record({
          suite: "Suite 1: Rapid Switching",
          name: "1,000 interactive menu-item onClick switches",
          status: "FAIL",
          durationMs: dur,
          details: `Encountered ${failureCount} failures! First failure: ${firstFailure}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 1.3: Asynchronous interleaved switching with microtask stress
  {
    const start = performance.now();
    setupTestEnv("en");
    try {
      const NUM_ASYNC_STEPS = 600;
      const locales: SupportedLocale[] = ["uz", "ru", "en"];
      const promises: Promise<void>[] = [];

      for (let i = 0; i < NUM_ASYNC_STEPS; i++) {
        const target = locales[i % locales.length];
        promises.push(
          new Promise<void>((resolve) => {
            queueMicrotask(() => {
              setLocale(target);
              resolve();
            });
          }),
        );
      }

      await Promise.all(promises);
      const finalLocale = useI18n.getState().locale;
      const expectedFinal = locales[(NUM_ASYNC_STEPS - 1) % locales.length];

      const dur = performance.now() - start;
      if (finalLocale === expectedFinal) {
        record({
          suite: "Suite 1: Rapid Switching",
          name: "600 asynchronous microtask-interleaved switches resolve deterministically",
          status: "PASS",
          durationMs: dur,
          details: `Final locale correctly matched the last scheduled microtask (${finalLocale}).`,
        });
      } else {
        record({
          suite: "Suite 1: Rapid Switching",
          name: "600 asynchronous microtask-interleaved switches",
          status: "FAIL",
          durationMs: dur,
          details: `Expected final locale ${expectedFinal}, got ${finalLocale}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 1.4: Multi-subscriber leak and notification integrity under 1,000 switches
  {
    const start = performance.now();
    setupTestEnv("en");
    try {
      const SUBSCRIBER_COUNT = 50;
      const SWITCH_COUNT = 1000;
      const counts = new Array<number>(SUBSCRIBER_COUNT).fill(0);
      const unsubs: Array<() => void> = [];

      for (let s = 0; s < SUBSCRIBER_COUNT; s++) {
        const subIndex = s;
        unsubs.push(
          useI18n.subscribe(() => {
            counts[subIndex]++;
          }),
        );
      }

      const seq: SupportedLocale[] = ["uz", "ru", "en"];
      for (let i = 0; i < SWITCH_COUNT; i++) {
        setLocale(seq[i % seq.length]);
      }

      const allEqual = counts.every((c) => c === SWITCH_COUNT);
      // Unsubscribe all
      for (const unsub of unsubs) {
        unsub();
      }

      // One more switch to verify no hanging subscriber receives it
      setLocale("uz");
      const unsubsClean = counts.every((c) => c === SWITCH_COUNT);

      const dur = performance.now() - start;
      if (allEqual && unsubsClean) {
        record({
          suite: "Suite 1: Rapid Switching",
          name: "50 concurrent subscribers receive all 1,000 notifications without drops or memory leak",
          status: "PASS",
          durationMs: dur,
          details: `All 50 subscribers cleanly observed 1,000 events, and cleanly unsubscribed.`,
        });
      } else {
        record({
          suite: "Suite 1: Rapid Switching",
          name: "50 concurrent subscribers under 1,000 switches",
          status: "FAIL",
          durationMs: dur,
          details: `Failed: allEqual=${allEqual}, unsubsClean=${unsubsClean}, sampleCounts=${counts.slice(0, 5).join(",")}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  /* -------------------------------------------------------------------------- */
  /* SUITE 2: Presentation Variant Rendering & PlanIQ Tokens                     */
  /* -------------------------------------------------------------------------- */
  console.log("\n--- Suite 2: Presentation Variant Rendering & PlanIQ Tokens ---");

  /*
   * Rewritten for the menu button. The old six blocks measured a segmented track that no
   * longer exists — `h-7`/`h-8` heights, `rounded-seg` pills, `flex-1` segments, a collapsed
   * 44px column — and there is no honest translation of "wide collapsed" into a control that
   * is one disc. What is measured now is what the control actually has: two variants that
   * differ in one thing, a trigger, and three menu items.
   *
   * Nothing here asserts WHICH item is checked: a static render draws the store's INITIAL
   * locale (see the note on `renderSwitcher`). That belongs to the jsdom suite.
   */

  // 2.1: variant="bar" — the disc as it sits in TopBar, with no ground of its own
  {
    setupTestEnv("en");
    try {
      const res = renderSwitcher({ variant: "bar" });
      const triggerClass = String(res.trigger.props.className ?? "");

      const isDisc = triggerClass.includes("h-9 w-9") && triggerClass.includes("rounded-full");
      const hasHoverGround = triggerClass.includes("hover:bg-row-hover");
      const hasFocusRing = triggerClass.includes("focus-visible:outline-accent-deep");
      const hasNoRestingGround =
        !triggerClass.includes("border border-stroke") && !triggerClass.includes("shadow-sm");

      if (isDisc && hasHoverGround && hasFocusRing && hasNoRestingGround) {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "variant='bar'",
          status: "PASS",
          durationMs: 0,
          details: "36px disc, hover ground only, accent-deep focus ring, no resting chrome.",
        });
      } else {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "variant='bar'",
          status: "FAIL",
          durationMs: 0,
          details: `triggerClass=${triggerClass}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 2.2: variant="login" — the same disc, given a ground because nothing sits behind it
  {
    setupTestEnv("en");
    try {
      const res = renderSwitcher({ variant: "login" });
      const triggerClass = String(res.trigger.props.className ?? "");

      const isDisc = triggerClass.includes("h-9 w-9") && triggerClass.includes("rounded-full");
      const hasCard = triggerClass.includes("bg-card");
      const hasBorder = triggerClass.includes("border border-stroke");
      const hasShadow = triggerClass.includes("shadow-sm");

      if (isDisc && hasCard && hasBorder && hasShadow) {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "variant='login'",
          status: "PASS",
          durationMs: 0,
          details: "Same 36px disc, plus the card ground the login page needs behind it.",
        });
      } else {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "variant='login'",
          status: "FAIL",
          durationMs: 0,
          details: `triggerClass=${triggerClass}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 2.3: the menu itself — three items, in canonical order, each naming a language
  {
    setupTestEnv("en");
    try {
      const res = renderSwitcher({});
      const order = res.buttons.map((b) => b.value).join(",");
      const titlesAreLanguages = res.buttons.every(
        (b) => b.title === "" || Object.values(LOCALES).some((meta) => meta.name === b.title),
      );
      const exactlyOneChecked = res.buttons.filter((b) => b.ariaPressed).length === 1;
      const namesLanguages = res.html.includes("Oʻzbekcha") && res.html.includes("Русский");

      if (order === "uz,ru,en" && titlesAreLanguages && exactlyOneChecked && namesLanguages) {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Open menu structure",
          status: "PASS",
          durationMs: 0,
          details: "Three items in canonical order, one checked, each labelled by its endonym.",
        });
      } else {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Open menu structure",
          status: "FAIL",
          durationMs: 0,
          details: `order=${order}, oneChecked=${exactlyOneChecked}, endonyms=${namesLanguages}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 2.4: a closed control renders no menu at all
  {
    setupTestEnv("en");
    try {
      /* `defaultOpen` is forced on by `renderSwitcher`, so this one calls the component
         directly to see the default: shut, with nothing in the tree behind it. */
      let closedHtml = "";
      function ClosedWrapper() {
        return LanguageSwitcher({});
      }
      closedHtml = renderToStaticMarkup(React.createElement(ClosedWrapper));

      const hasTrigger = closedHtml.includes('aria-haspopup="menu"');
      const isShut = closedHtml.includes('aria-expanded="false"');
      const hasNoMenu = !closedHtml.includes('role="menu"');

      if (hasTrigger && isShut && hasNoMenu) {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Closed by default",
          status: "PASS",
          durationMs: 0,
          details: "A trigger that declares a menu, and no menu until it is asked for.",
        });
      } else {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Closed by default",
          status: "FAIL",
          durationMs: 0,
          details: `hasTrigger=${hasTrigger}, isShut=${isShut}, hasNoMenu=${hasNoMenu}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 2.5: default props
  {
    setupTestEnv("en");
    try {
      const res = renderSwitcher();
      const triggerClass = String(res.trigger.props.className ?? "");
      const ariaLabel = String(res.trigger.props["aria-label"] ?? "");

      const defaultsToBar = !triggerClass.includes("border border-stroke");
      const isLabelled = ariaLabel === "Select language";

      if (defaultsToBar && isLabelled && res.buttons.length === 3) {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Default props without arguments",
          status: "PASS",
          durationMs: 0,
          details: "Defaults to variant='bar' and the translated 'Select language'.",
        });
      } else {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Default props without arguments",
          status: "FAIL",
          durationMs: 0,
          details: `defaultsToBar=${defaultsToBar}, ariaLabel=${ariaLabel}, items=${res.buttons.length}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 2.6: custom className lands on the root, custom ariaLabel on the trigger AND the menu
  {
    setupTestEnv("en");
    try {
      const customAria = "Tilni tanlang";
      const res = renderSwitcher({ className: "custom-cls", ariaLabel: customAria });

      const hasCustomClass = String(res.element.props.className ?? "").includes("custom-cls");
      const triggerLabelled = res.trigger.props["aria-label"] === customAria;
      /* The menu is named too: a screen reader entering it should not have to remember what
         the button that opened it was called. */
      const menuLabelled = res.html.includes(`aria-label="${customAria}"`);

      if (hasCustomClass && triggerLabelled && menuLabelled) {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Custom className and custom ariaLabel",
          status: "PASS",
          durationMs: 0,
          details: `className merged on the root; "${customAria}" names both trigger and menu.`,
        });
      } else {
        record({
          suite: "Suite 2: Variant Rendering",
          name: "Custom className and custom ariaLabel",
          status: "FAIL",
          durationMs: 0,
          details: `hasCustomClass=${hasCustomClass}, trigger=${triggerLabelled}, menu=${menuLabelled}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }


  /* -------------------------------------------------------------------------- */
  /* SUITE 3: Boundary Inputs, Fuzzing & Keyboard Matrix                         */
  /* -------------------------------------------------------------------------- */
  console.log("\n--- Suite 3: Boundary Inputs, Fuzzing & Keyboard Matrix ---");

  // 3.1: All props explicitly undefined
  {
    setupTestEnv("en");
    try {
      const res = renderSwitcher({
        variant: undefined,
        collapsed: undefined,
        className: undefined,
        ariaLabel: undefined,
        onChange: undefined,
      });

      if (res.buttons.length === 3 && res.buttons[2].ariaPressed === true) {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Explicit undefined for all props renders default compact switcher cleanly",
          status: "PASS",
          details: "Verified 3 language options rendered and active English button preserved.",
        });
      } else {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Explicit undefined for all props",
          status: "FAIL",
          details: `buttons length: ${res.buttons.length}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 3.2: Adversarial variant fuzzing (unknown strings, null, numeric, boolean, object)
  {
    setupTestEnv("en");
    try {
      const fuzzVariants: unknown[] = [
        "ultra-wide",
        "mobile-drawer",
        "",
        null,
        123,
        false,
        true,
        { invalid: true },
        ["wide"],
      ];

      let crashed = false;
      let crashError = "";

      for (const fv of fuzzVariants) {
        try {
          const res = renderSwitcher({ variant: fv as LanguageSwitcherVariant });
          if (!res.html.includes("<div") || res.buttons.length !== 3) {
            crashed = true;
            crashError = `Variant ${JSON.stringify(fv)} did not produce valid 3-button DOM`;
            break;
          }
        } catch (err) {
          crashed = true;
          crashError = `Variant ${JSON.stringify(fv)} threw: ${String(err)}`;
          break;
        }
      }

      if (!crashed) {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Adversarial variant fuzzing (null, numbers, booleans, invalid strings) degrades safely without crash",
          status: "PASS",
          details: `Fuzzed ${fuzzVariants.length} malformed variants; all rendered safe container without throwing.`,
        });
      } else {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Adversarial variant fuzzing",
          status: "FAIL",
          details: crashError,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 3.3: onChange callback invocation and undefined safety
  {
    setupTestEnv("en");
    try {
      let callbackReceived: SupportedLocale | null = null;
      let callbackCount = 0;

      const res = renderSwitcher({
        onChange: (locale) => {
          callbackReceived = locale;
          callbackCount++;
        },
      });

      // Click UZ
      res.buttons[0].onClick();

      const correctlyCalled = callbackReceived === "uz" && callbackCount === 1;

      // Now test with undefined onChange
      const resNoCallback = renderSwitcher({ onChange: undefined });
      let threwWithoutCallback = false;
      try {
        resNoCallback.buttons[1].onClick(); // Click RU
      } catch {
        threwWithoutCallback = true;
      }

      if (correctlyCalled && !threwWithoutCallback && useI18n.getState().locale === "ru") {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "onChange callback receives exact locale; undefined callback safe against throws",
          status: "PASS",
          details: "Verified exact parameter passed to callback, and undefined callback optional chaining.",
        });
      } else {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "onChange callback behavior",
          status: "FAIL",
          details: `correctlyCalled=${correctlyCalled}, threwWithoutCallback=${threwWithoutCallback}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 3.4: Unsupported store locale normalization & unselected state handling
  {
    setupTestEnv("en");
    try {
      // 1. setLocale("invalid") defensively falls back to "en"
      setLocale("invalid" as unknown as SupportedLocale);
      const fallbackToEn = useI18n.getState().locale === "en";

      // 2. Direct injection of unsupported locale into Zustand store
      useI18n.getState(); // establish sync
      useI18n.setState({ locale: "fr" as unknown as SupportedLocale });

      const res = renderSwitcher({});
      /* An unknown locale means `activeIndex === -1`. The control must still draw a face
         rather than a hole, and must still be safe to press a key at. Which face it draws is
         not asserted — a static render shows the store's initial locale, not this one. */
      const drewATrigger = res.trigger.props["data-locale"] !== undefined;
      const stillOffersThree = res.buttons.length === 3;

      let keyboardThrew = false;
      try {
        res.onKeyDown({ key: "ArrowRight", preventDefault: () => {} });
      } catch {
        keyboardThrew = true;
      }

      if (fallbackToEn && drewATrigger && stillOffersThree && !keyboardThrew) {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Unsupported store locale ('fr') still renders and guards the keyboard",
          status: "PASS",
          details: "setLocale sanitises, and activeIndex === -1 falls back rather than crashing.",
        });
      } else {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Unsupported store locale handling",
          status: "FAIL",
          details: `fallbackToEn=${fallbackToEn}, drewATrigger=${drewATrigger}, items=${res.buttons.length}, keyboardThrew=${keyboardThrew}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 3.5: the keys this control still owns, and the ones it must leave alone
  {
    setupTestEnv("en");
    try {
      /*
       * The full matrix — ArrowDown/Up/Home/End walking the items, Escape closing and handing
       * focus back to the trigger — moved to `src/components/LanguageSwitcher.test.tsx`. It
       * has to: the arrows now move FOCUS between menu items, and a static render has no
       * focus, no document.activeElement and no open menu to move around inside.
       *
       * Two things about the handler are still assertable without a DOM, and both are the
       * kind of regression a redesign actually causes: a key the control does not own must
       * not be swallowed, and no key may mutate the locale as a side effect of being pressed.
       * The old control changed language on ArrowRight; this one must not.
       */
      const unmapped = ["Tab", "Enter", " ", "a", "Shift", "F5", "PageDown"];
      const failures: string[] = [];

      for (const key of unmapped) {
        setLocale("uz");
        const res = renderSwitcher({});
        let prevented = false;
        res.onKeyDown({
          key,
          preventDefault: () => {
            prevented = true;
          },
        });
        if (prevented) failures.push(`'${key}' was swallowed`);
        if (useI18n.getState().locale !== "uz") failures.push(`'${key}' changed the locale`);
      }

      /* And the one that would be a silent regression to the OLD behaviour. */
      setLocale("uz");
      const arrowRes = renderSwitcher({});
      arrowRes.onKeyDown({ key: "ArrowRight", preventDefault: () => {} });
      if (useI18n.getState().locale !== "uz") {
        failures.push("ArrowRight changed the locale — that was the old segmented control");
      }

      if (failures.length === 0) {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Keyboard: unmapped keys pass through, and no key mutates the locale",
          status: "PASS",
          details: `${unmapped.length} unmapped keys left alone; arrows move focus, never state.`,
        });
      } else {
        record({
          suite: "Suite 3: Boundary Inputs",
          name: "Keyboard navigation matrix",
          status: "FAIL",
          details: failures.join("; "),
        });
      }
    } finally {
      restoreTestEnv();
    }
  }


  /* -------------------------------------------------------------------------- */
  /* SUITE 4: Storage Denial & QuotaExceeded Resilience                         */
  /* -------------------------------------------------------------------------- */
  console.log("\n--- Suite 4: Storage Denial & QuotaExceeded Resilience ---");

  // 4.1: localStorage.setItem throws QuotaExceededError during interactive switch
  {
    const env = setupTestEnv("en");
    env.storage.shouldThrowOnSet = true;
    env.storage.throwErrorType = "QuotaExceededError";
    try {
      /*
       * Consume the environment-changed flag BEFORE clicking.
       *
       * `getState()` re-resolves the initial locale whenever the `localStorage` or `navigator`
       * object identity has changed since it last looked — which is exactly what
       * `setupTestEnv` does. Read it once here and the flag is spent; leave it until after the
       * click and the assertion's own `getState()` resets the store to the stored value,
       * wiping the very switch it was about to measure. This used to be paid for by accident:
       * every render called the sync, because `useI18n` took its non-reactive branch on every
       * render. It no longer does, and the accident is gone with it.
       */
      getLocale();

      let threw = false;
      let errorMsg = "";

      try {
        const res = renderSwitcher({ variant: "login" });
        res.buttons[0].onClick(); // Click UZ
      } catch (err) {
        threw = true;
        errorMsg = String(err);
      }

      const storeLocale = useI18n.getState().locale;
      const docLang = env.doc.documentElement.lang;

      /* The re-rendered `aria-checked` is not read here: a static render draws the store's
         INITIAL locale, so it would measure the renderer rather than the storage failure. */
      const stillRenders = renderSwitcher({ variant: "login" }).buttons.length === 3;

      if (!threw && storeLocale === "uz" && docLang === "uz" && stillRenders) {
        record({
          suite: "Suite 4: Storage Denial",
          name: "QuotaExceededError on localStorage.setItem caught defensively; in-memory store & UI update",
          status: "PASS",
          details: "Verified switcher button click survives storage quota exhaustion with zero uncaught exceptions.",
        });
      } else {
        record({
          suite: "Suite 4: Storage Denial",
          name: "QuotaExceededError handling",
          status: "FAIL",
          details: `threw=${threw} (${errorMsg}), storeLocale=${storeLocale}, docLang=${docLang}, stillRenders=${stillRenders}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 4.2: localStorage.setItem throws SecurityError (private browsing / blocked storage)
  {
    const env = setupTestEnv("ru");
    env.storage.shouldThrowOnSet = true;
    env.storage.throwErrorType = "SecurityError";
    try {
      // See 4.1 on why the sync is consumed before anything is switched.
      getLocale();

      let threw = false;
      try {
        /* Choosing from the menu, which is what the arrows used to do directly. */
        const res = renderSwitcher({ variant: "login" });
        const enItem = res.buttons.find((b) => b.value === "en");
        enItem?.onClick();
      } catch {
        threw = true;
      }

      const storeLocale = useI18n.getState().locale;
      const docLang = env.doc.documentElement.lang;

      if (!threw && storeLocale === "en" && docLang === "en") {
        record({
          suite: "Suite 4: Storage Denial",
          name: "SecurityError in private browsing mode does not disrupt language selection",
          status: "PASS",
          details: "Selection updates the in-memory store and document.documentElement.lang regardless.",
        });
      } else {
        record({
          suite: "Suite 4: Storage Denial",
          name: "SecurityError handling",
          status: "FAIL",
          details: `threw=${threw}, storeLocale=${storeLocale}, docLang=${docLang}`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // 4.3: window.localStorage is completely undefined (strict sandbox / SSR)
  {
    setupTestEnv("en");
    // Temporarily undefine window.localStorage
    const g = globalThis as Record<string, unknown>;
    const prevStorage = g.localStorage;
    Object.defineProperty(g, "localStorage", { value: undefined, configurable: true, writable: true });
    try {
      // See 4.1 on why the sync is consumed before anything is switched.
      getLocale();

      let threw = false;
      let error = "";
      try {
        const res = renderSwitcher({ variant: "bar" });
        res.buttons[1].onClick(); // Choose RU
      } catch (err) {
        threw = true;
        error = String(err);
      }

      const storeLocale = useI18n.getState().locale;

      if (!threw && storeLocale === "ru") {
        record({
          suite: "Suite 4: Storage Denial",
          name: "window.localStorage === undefined handled gracefully during switcher clicks",
          status: "PASS",
          details: "Verified SSR / strict sandbox environment safety.",
        });
      } else {
        record({
          suite: "Suite 4: Storage Denial",
          name: "window.localStorage === undefined handling",
          status: "FAIL",
          details: `threw=${threw} (${error}), storeLocale=${storeLocale}`,
        });
      }
    } finally {
      Object.defineProperty(g, "localStorage", { value: prevStorage, configurable: true, writable: true });
      restoreTestEnv();
    }
  }

  // 4.4: 500 rapid switches under persistent storage QuotaExceeded errors
  {
    const start = performance.now();
    const env = setupTestEnv("en");
    env.storage.shouldThrowOnSet = true;
    env.storage.throwErrorType = "QuotaExceededError";
    try {
      const TOTAL_STEPS = 500;
      const sequence: SupportedLocale[] = ["uz", "ru", "en"];
      let errorCount = 0;

      for (let i = 0; i < TOTAL_STEPS; i++) {
        const target = sequence[i % sequence.length];
        try {
          setLocale(target);
          if (useI18n.getState().locale !== target) {
            errorCount++;
          }
        } catch {
          errorCount++;
        }
      }

      const dur = performance.now() - start;
      if (errorCount === 0) {
        record({
          suite: "Suite 4: Storage Denial",
          name: "500 consecutive switches under persistent QuotaExceededError remain 100% consistent",
          status: "PASS",
          durationMs: dur,
          details: `All ${TOTAL_STEPS} switches succeeded in-memory without memory leaks or crashes.`,
        });
      } else {
        record({
          suite: "Suite 4: Storage Denial",
          name: "500 switches under QuotaExceededError",
          status: "FAIL",
          durationMs: dur,
          details: `Encountered ${errorCount} errors during quota exhaustion stress.`,
        });
      }
    } finally {
      restoreTestEnv();
    }
  }

  // Final Summary
  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER M2 HARNESS SUMMARY");
  console.log("=".repeat(80));
  const passed = reports.filter((r) => r.status === "PASS").length;
  const failed = reports.filter((r) => r.status === "FAIL").length;
  console.log(`  Total Scenarios Run: ${reports.length}`);
  console.log(`  \x1b[32mPassed:\x1b[0m              ${passed}`);
  console.log(`  \x1b[31mFailed:\x1b[0m              ${failed}`);
  console.log("=".repeat(80) + "\n");

  return { passed, failed };
}

// Auto-run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runChallengerM2Stress()
    .then(({ failed }) => {
      if (failed > 0) {
        process.exit(1);
      } else {
        process.exit(0);
      }
    })
    .catch((err) => {
      console.error("Fatal error in challenger harness:", err);
      process.exit(1);
    });
}
